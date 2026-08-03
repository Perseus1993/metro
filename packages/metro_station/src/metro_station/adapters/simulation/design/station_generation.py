from __future__ import annotations

from dataclasses import replace
from math import atan2, degrees

from shapely.geometry import Polygon, box

from .geometry import element_shape
from .schema import (
    DesignConnection,
    DesignElement,
    ElementGeometry,
    QueueSpec,
    StationDesignDocument,
)
from .templates import with_standard_graph_contract
from .vertical_landing import (
    design_level_walkable_geometry,
    vertical_facade_pairs,
    vertical_interior_direction,
    vertical_landing_position,
)


QUEUE_COMPONENT_KINDS = {"gate", "escalator", "stairs", "elevator", "platform_edge"}


def generate_station(document: StationDesignDocument) -> StationDesignDocument:
    """Complete editor-owned infrastructure without inventing strategic facilities.

    The user remains responsible for placing entrances, gates, platforms, and vertical
    connectors. Generation only derives queues, ports, and walk connections needed to compile
    those choices into the station graph.
    """

    queues = with_generated_queues(document)
    generated = replace(document, queues=queues)
    generated = with_standard_graph_contract(generated)
    connections = _with_generated_inputs(generated)
    return replace(
        generated,
        connections=connections,
        metadata={
            **generated.metadata,
            "generation_state": "generated",
            "generated_by": "design_inspector",
        },
    )


def with_generated_queues(document: StationDesignDocument) -> tuple[QueueSpec, ...]:
    """Complete every service facade with a landing-local queue specification."""

    queues = list(document.queues)
    occupied_by_level = _occupied_by_level(document, queues)
    footprints = _level_footprints(document)
    walkable_by_level = {
        level.id: design_level_walkable_geometry(document, level.id)
        for level in document.levels
    }
    levels_by_id = document.level_by_id()
    for element in document.elements:
        if element.kind not in QUEUE_COMPONENT_KINDS:
            continue
        if element.role == "vertical_connector":
            for direction, entry_level_id, exit_level_id in vertical_facade_pairs(
                element,
                levels_by_id,
            ):
                if _queue_for_facade(
                    queues,
                    element.id,
                    entry_level_id,
                    direction,
                ) is not None:
                    continue
                footprint = footprints.get(entry_level_id)
                walkable = walkable_by_level.get(entry_level_id)
                if footprint is None or walkable is None:
                    continue
                queue = _generated_vertical_queue(
                    element,
                    direction=direction,
                    entry_level_id=entry_level_id,
                    exit_level_id=exit_level_id,
                    levels_by_id=levels_by_id,
                    footprint=footprint,
                    entry_walkable_geometry=walkable,
                    exit_walkable_geometry=walkable_by_level.get(exit_level_id),
                    occupied=occupied_by_level.setdefault(entry_level_id, []),
                )
                queues.append(queue)
                occupied_by_level[entry_level_id].append(element_shape(queue.geometry))
            continue
        if any(queue.owner_element_id == element.id for queue in queues):
            continue
        footprint = footprints.get(element.level_id)
        if footprint is None:
            continue
        occupied = occupied_by_level.setdefault(element.level_id, [])
        queue = _generated_queue(element, footprint, occupied)
        queues.append(queue)
        occupied.append(element_shape(queue.geometry))
    return tuple(queues)


def _queue_for_facade(
    queues: list[QueueSpec] | tuple[QueueSpec, ...],
    owner_element_id: str,
    level_id: str,
    direction: str,
) -> QueueSpec | None:
    candidates = tuple(
        queue
        for queue in queues
        if queue.owner_element_id == owner_element_id and queue.level_id == level_id
    )
    return next(
        (queue for queue in candidates if queue.service_direction == direction),
        next((queue for queue in candidates if queue.service_direction is None), None),
    )


def _generated_vertical_queue(
    element: DesignElement,
    *,
    direction: str,
    entry_level_id: str,
    exit_level_id: str,
    levels_by_id,
    footprint,
    entry_walkable_geometry,
    exit_walkable_geometry,
    occupied,
) -> QueueSpec:
    queue_width, queue_depth, capacity, kind = _queue_dimensions(element)
    service_point = vertical_landing_position(
        element,
        entry_level_id,
        levels_by_id,
        walkable_geometry=entry_walkable_geometry,
    )
    forward = vertical_interior_direction(
        element,
        entry_level_id,
        exit_level_id,
        levels_by_id,
        entry_walkable_geometry=entry_walkable_geometry,
        exit_walkable_geometry=exit_walkable_geometry,
    )
    lateral = (-forward[1], forward[0])
    outward_axes = (
        (-forward[0], -forward[1], 0.0),
        (lateral[0], lateral[1], 2.0),
        (-lateral[0], -lateral[1], 2.0),
    )
    candidates: list[tuple[float, ElementGeometry, tuple[float, float]]] = []
    for scale in (1.0, 0.8, 0.6, 0.45):
        width = max(2.0, queue_width * scale)
        depth = max(2.0, queue_depth * scale)
        for outward_x, outward_y, alignment_penalty in outward_axes:
            across = (-outward_y, outward_x)
            for service_offset in (
                0.0,
                -width * 0.25,
                width * 0.25,
                -width * 0.5,
                width * 0.5,
            ):
                front_center = (
                    service_point[0] - across[0] * service_offset,
                    service_point[1] - across[1] * service_offset,
                )
                left_front = (
                    front_center[0] + across[0] * width / 2.0,
                    front_center[1] + across[1] * width / 2.0,
                )
                right_front = (
                    front_center[0] - across[0] * width / 2.0,
                    front_center[1] - across[1] * width / 2.0,
                )
                left_back = (
                    left_front[0] + outward_x * depth,
                    left_front[1] + outward_y * depth,
                )
                right_back = (
                    right_front[0] + outward_x * depth,
                    right_front[1] + outward_y * depth,
                )
                geometry = ElementGeometry(
                    "polygon",
                    points_m=(left_front, right_front, right_back, left_back),
                )
                shape = element_shape(geometry)
                if not footprint.buffer(0.01).covers(shape) or not entry_walkable_geometry.buffer(
                    0.01
                ).covers(shape):
                    continue
                collision = sum(shape.intersection(other).area for other in occupied)
                shrink_penalty = (1.0 - scale) * 10.0
                candidates.append(
                    (
                        collision + alignment_penalty + shrink_penalty,
                        geometry,
                        (outward_x, outward_y),
                    )
                )
    if not candidates:
        raise ValueError(
            f"no body-sized queue domain fits landing {element.id!r} "
            f"{entry_level_id!r} {direction!r}"
        )
    _score, geometry, outward = min(candidates, key=lambda item: item[0])
    return QueueSpec(
        id=f"queue_{element.id}_{entry_level_id}_{direction}",
        owner_element_id=element.id,
        kind=kind,
        level_id=entry_level_id,
        geometry=geometry,
        service_point_m=service_point,
        capacity=capacity,
        spacing_m=0.8,
        direction_deg=degrees(atan2(outward[1], outward[0])),
        label=f"{element.label} {direction} {entry_level_id} queue",
        service_direction=direction,
    )


def _generated_queue(element: DesignElement, footprint, occupied) -> QueueSpec:
    queue_width, queue_height, capacity, kind = _queue_dimensions(element)
    owner = element_shape(element.geometry)
    min_x, min_y, max_x, max_y = owner.bounds
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    candidates = (
        (center_x - queue_width / 2.0, max_y, "below"),
        (center_x - queue_width / 2.0, min_y - queue_height, "above"),
        (max_x, center_y - queue_height / 2.0, "right"),
        (min_x - queue_width, center_y - queue_height / 2.0, "left"),
    )
    valid = [
        candidate
        for candidate in candidates
        if footprint.buffer(0.01).covers(
            box(
                candidate[0],
                candidate[1],
                candidate[0] + queue_width,
                candidate[1] + queue_height,
            )
        )
    ]
    pool = valid or list(candidates)
    x_m, y_m, side = min(
        pool,
        key=lambda candidate: _queue_collision_score(
            candidate,
            queue_width,
            queue_height,
            occupied,
        ),
    )
    service_point = _service_point(side, center_x, center_y, min_x, min_y, max_x, max_y)
    return QueueSpec(
        id=f"queue_{element.id}",
        owner_element_id=element.id,
        kind=kind,
        level_id=element.level_id,
        geometry=ElementGeometry(
            "rect",
            x_m=x_m,
            y_m=y_m,
            width_m=queue_width,
            height_m=queue_height,
        ),
        service_point_m=service_point,
        capacity=capacity,
        spacing_m=0.8,
        direction_deg={"below": 270.0, "above": 90.0, "right": 180.0, "left": 0.0}[side],
        label=f"{element.label} generated queue",
    )


def _queue_dimensions(element: DesignElement) -> tuple[float, float, int, str]:
    width = max(4.0, min(18.0, element.geometry.bounds()[2] - element.geometry.bounds()[0]))
    if element.kind == "platform_edge":
        return max(12.0, width), 6.0, 80, "holding_area"
    if element.kind == "gate":
        return max(8.0, width), 7.0, 40, "lane"
    return max(8.0, width), 6.0, 32, "lane"


def _queue_collision_score(candidate, width: float, height: float, occupied) -> float:
    shape = box(candidate[0], candidate[1], candidate[0] + width, candidate[1] + height)
    return sum(shape.intersection(other).area for other in occupied)


def _service_point(
    side: str,
    center_x: float,
    center_y: float,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> tuple[float, float]:
    if side == "below":
        return center_x, max_y
    if side == "above":
        return center_x, min_y
    if side == "right":
        return max_x, center_y
    return min_x, center_y


def _with_generated_inputs(document: StationDesignDocument) -> tuple[DesignConnection, ...]:
    result = list(document.connections)
    existing_ids = {connection.id for connection in result}
    zones_by_level = {
        element.level_id: element
        for element in document.elements
        if element.role == "floor" and element.metadata.get("graph_node", True)
    }
    for element in document.elements:
        zone = zones_by_level.get(element.level_id)
        if zone is None:
            continue
        endpoint = _generated_input_endpoint(element)
        if endpoint is None:
            continue
        connection_id = f"conn_generate_{zone.id}_to_{element.id}_{endpoint}"
        if connection_id in existing_ids or _has_connection(result, zone.id, element.id, endpoint):
            continue
        result.append(
            DesignConnection(
                connection_id,
                zone.id,
                element.id,
                "walk",
                bidirectional=False,
                source_port_id="walk",
                target_port_id=endpoint,
                metadata={"generated": True},
            )
        )
        existing_ids.add(connection_id)
    return tuple(result)


def _generated_input_endpoint(element: DesignElement) -> str | None:
    if element.kind in {"entrance", "platform_edge"}:
        return "walk"
    if element.kind == "gate":
        return "service"
    return None


def _has_connection(
    connections: list[DesignConnection],
    source_id: str,
    target_id: str,
    target_port_id: str,
) -> bool:
    return any(
        connection.source_id == source_id
        and connection.target_id == target_id
        and connection.target_port_id == target_port_id
        for connection in connections
    )


def _level_footprints(document: StationDesignDocument) -> dict[str, Polygon]:
    return {
        level.id: Polygon(level.footprint) for level in document.levels if len(level.footprint) >= 3
    }


def _occupied_by_level(
    document: StationDesignDocument,
    queues: list[QueueSpec],
) -> dict[str, list[object]]:
    occupied: dict[str, list[object]] = {level.id: [] for level in document.levels}
    for element in _solid_elements(document):
        level_ids = (
            element.connects_levels
            if element.role == "vertical_connector"
            else (element.level_id,)
        )
        for level_id in level_ids:
            occupied.setdefault(level_id, []).append(element_shape(element.geometry))
    for queue in queues:
        occupied.setdefault(queue.level_id, []).append(element_shape(queue.geometry))
    return occupied


def _solid_elements(document: StationDesignDocument) -> tuple[DesignElement, ...]:
    return tuple(
        element
        for element in document.elements
        if element.role != "floor"
        and not (element.kind == "obstacle" and not element.metadata.get("blocking", True))
    )
