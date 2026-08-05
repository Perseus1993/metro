from __future__ import annotations

from dataclasses import replace
from math import atan2, cos, degrees, floor, radians, sin

from shapely.geometry import Polygon, box

from .geometry import element_shape
from .schema import (
    DesignConnection,
    DesignElement,
    ElementGeometry,
    QueueSpec,
    StationDesignDocument,
)
from .spatial_reservations import (
    SpatialReservation,
    conflicting_area,
    level_spatial_reservations,
    queue_reservation,
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

    queues = _normalize_service_queue_directions(document, list(document.queues))
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
                occupied_by_level[entry_level_id].append(queue_reservation(queue))
            continue
        if element.kind == "gate":
            directions = {
                "entry": ("in",),
                "exit": ("out",),
                "bidirectional": ("in", "out"),
            }.get(element.gate_direction or "bidirectional", ("in", "out"))
            footprint = footprints.get(element.level_id)
            if footprint is None:
                continue
            occupied = occupied_by_level.setdefault(element.level_id, [])
            for direction in directions:
                if _queue_for_facade(
                    queues,
                    element.id,
                    element.level_id,
                    direction,
                ) is not None:
                    continue
                queue = _generated_queue(
                    element,
                    footprint,
                    occupied,
                    service_direction=direction,
                )
                queues.append(queue)
                occupied.append(queue_reservation(queue))
            continue
        if any(queue.owner_element_id == element.id for queue in queues):
            continue
        footprint = footprints.get(element.level_id)
        if footprint is None:
            continue
        occupied = occupied_by_level.setdefault(element.level_id, [])
        queue = _generated_queue(
            element,
            footprint,
            occupied,
            service_direction=(
                element.direction if element.kind == "platform_edge" else None
            ),
        )
        queues.append(queue)
        occupied.append(queue_reservation(queue))
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
    if element.kind == "elevator":
        # A multi-stop elevator exposes both an up and a down facade on an
        # intermediate landing.  Giving both the same doorway-normal queue
        # makes their occupiable slots overlap.  Partition the shared landing
        # deterministically by travel direction while retaining fallback axes
        # for constrained footprints.
        preferred_lateral = lateral if direction == "up" else (-lateral[0], -lateral[1])
        opposite_lateral = (-preferred_lateral[0], -preferred_lateral[1])
        outward_axes = (
            (preferred_lateral[0], preferred_lateral[1], 0.0),
            (-forward[0], -forward[1], 20.0),
            (opposite_lateral[0], opposite_lateral[1], 40.0),
        )
    else:
        outward_axes = (
            (-forward[0], -forward[1], 0.0),
            (lateral[0], lateral[1], 2.0),
            (-lateral[0], -lateral[1], 2.0),
        )
    candidates: list[
        tuple[float, float, ElementGeometry, tuple[float, float]]
    ] = []
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
                collision = conflicting_area(
                    shape,
                    occupied,
                    facility_owner_id=element.id,
                )
                shrink_penalty = (1.0 - scale) * 10.0
                candidates.append(
                    (
                        collision + alignment_penalty + shrink_penalty,
                        collision,
                        geometry,
                        (outward_x, outward_y),
                    )
                )
    collision_free = [candidate for candidate in candidates if candidate[1] <= 0.01]
    if not collision_free:
        raise ValueError(
            f"spatial_capacity.queue_domain_unavailable: no body-sized, "
            f"collision-free queue domain fits landing {element.id!r} "
            f"{entry_level_id!r} {direction!r}"
        )
    _score, _collision, geometry, outward = min(
        collision_free,
        key=lambda item: item[0],
    )
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


def _generated_queue(
    element: DesignElement,
    footprint,
    occupied,
    *,
    service_direction: str | None = None,
) -> QueueSpec:
    queue_width, queue_height, capacity, kind = _queue_dimensions(element)
    # A rotated facade can make a full nominal queue rectangle graze an
    # otherwise unrelated resource even though a slightly smaller domain
    # still materialises every declared body slot.  Search deterministic
    # scaled domains instead of accepting the least-overlapping invalid one.
    minimum_queue_width = 1.0 if element.kind == "platform_edge" else 2.0
    candidates = tuple(
        (scale, candidate)
        for scale in (1.0, 0.98, 0.95, 0.9, 0.8, 0.7)
        for candidate in _generated_queue_candidates(
            element,
            queue_width=max(minimum_queue_width, queue_width * scale),
            queue_height=max(2.0, queue_height * scale),
        )
    )
    preferred_side: str | None = None
    if element.kind == "gate" and service_direction in {"in", "out"}:
        width = float(element.geometry.width_m)
        height = float(element.geometry.height_m)
        service_sides = (
            {"in": "above", "out": "below"}
            if width >= height
            else {"in": "left", "out": "right"}
        )
        preferred_side = service_sides[service_direction]
    valid = [
        (scale, candidate)
        for scale, candidate in candidates
        if footprint.buffer(0.01).covers(element_shape(candidate[0]))
    ]
    if not valid:
        raise ValueError(
            f"no generated queue domain for {element.id!r} fits inside "
            f"level {element.level_id!r}"
        )
    collision_free = [
        (scale, candidate)
        for scale, candidate in valid
        if conflicting_area(
            element_shape(candidate[0]),
            occupied,
            facility_owner_id=element.id,
        )
        <= 0.01
    ]
    if not collision_free:
        raise ValueError(
            "spatial_capacity.queue_domain_unavailable: no collision-free "
            f"generated queue domain fits {element.id!r} on "
            f"level {element.level_id!r}"
        )
    # Direction supplies a stable preferred facade, but it cannot authorize a
    # queue outside the compiled level or on another live spatial resource.
    preferred = (
        [item for item in collision_free if item[1][2] == preferred_side]
        if preferred_side is not None
        else []
    )
    pool = preferred or collision_free
    _scale, (geometry, service_point, side) = min(
        pool,
        key=lambda item: (
            conflicting_area(
                element_shape(item[1][0]),
                occupied,
                facility_owner_id=element.id,
            ),
            -item[0],
            item[1][2],
        ),
    )
    return QueueSpec(
        id=(
            f"queue_{element.id}"
            if service_direction is None
            else f"queue_{element.id}_{service_direction}"
        ),
        owner_element_id=element.id,
        kind=kind,
        level_id=element.level_id,
        geometry=geometry,
        service_point_m=service_point,
        # Capacity is a constructive claim tied to the selected domain, not a
        # template constant.  When collision avoidance shrinks a generated
        # queue, reduce the authored demand contract conservatively with area;
        # the portal compiler will still prove the exact slot count.
        capacity=max(1, floor(capacity * _scale * _scale)),
        spacing_m=0.8,
        direction_deg=(
            {"below": 270.0, "above": 90.0, "right": 180.0, "left": 0.0}[side]
            + float(element.geometry.rotation_deg)
        )
        % 360.0,
        label=f"{element.label} generated queue",
        service_direction=service_direction,
    )


def _generated_queue_candidates(
    element: DesignElement,
    *,
    queue_width: float,
    queue_height: float,
) -> tuple[tuple[ElementGeometry, tuple[float, float], str], ...]:
    geometry = element.geometry
    if geometry.shape == "rect":
        min_x = geometry.x_m
        min_y = geometry.y_m
        max_x = min_x + geometry.width_m
        max_y = min_y + geometry.height_m
        center_x, center_y = geometry.center()
        # A platform edge is much longer than its holding area.  Treating its
        # centre as the only legal queue facade made generated layouts place
        # every holding area on top of the same lift/escalator bank.  Candidate
        # generation must expose the free intervals along the full facade so
        # the joint occupancy scorer below can select a genuinely clear area.
        horizontal_starts = _facade_candidate_starts(
            min_x,
            max_x,
            queue_width,
            scan_full_facade=element.kind == "platform_edge",
        )
        vertical_starts = _facade_candidate_starts(
            min_y,
            max_y,
            queue_height,
            scan_full_facade=element.kind == "platform_edge",
        )
        local = (
            *((x_m, max_y, "below") for x_m in horizontal_starts),
            *((x_m, min_y - queue_height, "above") for x_m in horizontal_starts),
            *((max_x, y_m, "right") for y_m in vertical_starts),
            *((min_x - queue_width, y_m, "left") for y_m in vertical_starts),
        )
        result = []
        for x_m, y_m, side in local:
            queue_center = _rotate_generated_point(
                (x_m + queue_width / 2.0, y_m + queue_height / 2.0),
                (center_x, center_y),
                geometry.rotation_deg,
            )
            queue_geometry = ElementGeometry(
                "rect",
                x_m=queue_center[0] - queue_width / 2.0,
                y_m=queue_center[1] - queue_height / 2.0,
                width_m=queue_width,
                height_m=queue_height,
                rotation_deg=geometry.rotation_deg,
            )
            service_point = _rotate_generated_point(
                _candidate_service_point(
                    side,
                    x_m=x_m,
                    y_m=y_m,
                    queue_width=queue_width,
                    queue_height=queue_height,
                    min_x=min_x,
                    min_y=min_y,
                    max_x=max_x,
                    max_y=max_y,
                ),
                (center_x, center_y),
                geometry.rotation_deg,
            )
            result.append((queue_geometry, service_point, side))
        return tuple(result)

    min_x, min_y, max_x, max_y = element_shape(geometry).bounds
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    return tuple(
        (
            ElementGeometry(
                "rect",
                x_m=x_m,
                y_m=y_m,
                width_m=queue_width,
                height_m=queue_height,
            ),
            _service_point(side, center_x, center_y, min_x, min_y, max_x, max_y),
            side,
        )
        for x_m, y_m, side in (
            (center_x - queue_width / 2.0, max_y, "below"),
            (center_x - queue_width / 2.0, min_y - queue_height, "above"),
            (max_x, center_y - queue_height / 2.0, "right"),
            (min_x - queue_width, center_y - queue_height / 2.0, "left"),
        )
    )


def _facade_candidate_starts(
    minimum: float,
    maximum: float,
    queue_extent: float,
    *,
    scan_full_facade: bool,
) -> tuple[float, ...]:
    available = max(0.0, maximum - minimum - queue_extent)
    if not scan_full_facade or available <= 0.01:
        return (minimum + available / 2.0,)
    return tuple(
        minimum + available * fraction
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0)
    )


def _candidate_service_point(
    side: str,
    *,
    x_m: float,
    y_m: float,
    queue_width: float,
    queue_height: float,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> tuple[float, float]:
    if side == "below":
        return x_m + queue_width / 2.0, max_y
    if side == "above":
        return x_m + queue_width / 2.0, min_y
    if side == "right":
        return max_x, y_m + queue_height / 2.0
    return min_x, y_m + queue_height / 2.0


def _rotate_generated_point(
    point: tuple[float, float],
    origin: tuple[float, float],
    rotation_deg: float,
) -> tuple[float, float]:
    angle = radians(float(rotation_deg))
    dx = point[0] - origin[0]
    dy = point[1] - origin[1]
    return (
        origin[0] + dx * cos(angle) - dy * sin(angle),
        origin[1] + dx * sin(angle) + dy * cos(angle),
    )


def _normalize_service_queue_directions(
    document: StationDesignDocument,
    queues: list[QueueSpec],
) -> list[QueueSpec]:
    elements = document.element_by_id()
    normalized: list[QueueSpec] = []
    for queue in queues:
        element = elements.get(queue.owner_element_id)
        if element is None or queue.service_direction is not None:
            normalized.append(queue)
            continue
        if element.kind == "gate":
            direction = "in" if element.gate_direction == "entry" else "out"
            normalized.append(replace(queue, service_direction=direction))
            continue
        if element.role == "vertical_connector":
            matching = tuple(
                direction
                for direction, entry_level_id, _exit_level_id in vertical_facade_pairs(
                    element,
                    document.level_by_id(),
                )
                if entry_level_id == queue.level_id
            )
            if len(matching) == 1:
                normalized.append(replace(queue, service_direction=matching[0]))
                continue
        if element.kind == "platform_edge" and element.direction in {"up", "down"}:
            normalized.append(replace(queue, service_direction=element.direction))
            continue
        normalized.append(queue)
    return normalized


def _queue_dimensions(element: DesignElement) -> tuple[float, float, int, str]:
    element_width = element.geometry.bounds()[2] - element.geometry.bounds()[0]
    if element.kind == "platform_edge":
        return max(1.0, min(18.0, element_width)), 6.0, element.capacity or 80, "holding_area"
    width = max(4.0, min(18.0, element_width))
    if element.kind == "gate":
        # Seven metres of queue depth materializes six body-clear slots per
        # lane after the scenario radius is buffered out.  Declare exactly
        # that physical capacity instead of relying on runtime truncation.
        lane_count = max(1, int(element.capacity or 1))
        return max(8.0, width), 7.0, lane_count * 6, "lane"
    # A vertical facade is a single FIFO line, not area occupancy.  Four
    # explicit body-clear places are guaranteed by the minimum generated
    # landing domain; larger queues must enlarge that domain instead of
    # declaring capacity that the runtime silently truncates.
    return max(8.0, width), 6.0, 4, "lane"


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
) -> dict[str, list[SpatialReservation]]:
    return level_spatial_reservations(document, queues)


def _solid_elements(document: StationDesignDocument) -> tuple[DesignElement, ...]:
    return tuple(
        element
        for element in document.elements
        if element.role != "floor"
        and not (element.kind == "obstacle" and not element.metadata.get("blocking", True))
    )
