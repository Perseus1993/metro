from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from math import ceil, hypot, sqrt
from typing import Iterable

from shapely.geometry import LineString, Point as ShapelyPoint

from ..design.geometry import element_shape
from ..design.schema import DesignElement, StationDesignDocument
from ..design.vertical_landing import vertical_landing_position
from ..facilities.process import FacilitySpec, QueueLayout
from ..station.facility_portal_binding import (
    FacilityPortalBinding,
    Point,
    QueueSlotBinding,
)
from ..station.geometry import level_walkable_geometry
from ..station.graph import StationGraph
from ..station.layout_queue_geometry import minimum_vertical_approach_distance
from .geometry_reachability import GeometryCompilePolicy
from .facility_portal_contract import (
    NUMERICAL_TOLERANCE_M as _NUMERICAL_TOLERANCE_M,
    PROJECTION_TOLERANCE_M,
    facade_key as _facade_key,
    point_distance as _distance,
    queue_for_facility as _queue_for_facility,
    queues_by_owner as _queues_by_owner,
    topology_fingerprint as _topology_fingerprint,
)
from .facility_portal_route_validation import (
    validate_portal_binding_compatibility,
    validate_portal_binding_configuration,
)
from .facility_portal_validation import validate_facility_portals


def compile_facility_portal_bindings(
    document: StationDesignDocument,
    facilities: Iterable[FacilitySpec],
    *,
    policy: GeometryCompilePolicy,
    graph: StationGraph | None = None,
) -> tuple[FacilityPortalBinding, ...]:
    elements = document.element_by_id()
    queues_by_owner = _queues_by_owner(document.queues)
    fingerprint = _policy_fingerprint(policy)
    bindings: list[FacilityPortalBinding] = []
    for facility in facilities:
        source_id = facility.source_element_id
        if source_id is None or source_id not in elements:
            continue
        element = elements[source_id]
        queue = _queue_for_facility(queues_by_owner.get(source_id, ()), facility)
        raw_entry, raw_exit = _raw_facility_portals(document, element, facility)
        slots = tuple(
            (float(point[0]), float(point[1])) for point in facility.queue_layout.slots
        )
        (
            approach_slots,
            approach_slot_indices,
            approach_source_slot_indices,
            bridge_source_slot_indices,
        ) = _compiled_approach_slots(
            facility,
            slots,
            policy=policy,
            graph=graph,
            declared_capacity=(None if queue is None else int(queue.capacity)),
        )
        approach = approach_slots[-1] if approach_slots else facility.queue_layout.anchor
        entry_level = facility.entry_level_id or element.level_id
        exit_level = facility.exit_level_id or entry_level
        release_forward = _facility_release_forward(facility, graph)
        queue_id = None if queue is None else queue.id
        slot_bindings = _queue_slot_bindings(
            facility,
            facility.queue_layout,
            slots,
            queue_id=queue_id,
            approach_source_slot_indices=approach_source_slot_indices,
            approach_slot_indices=approach_slot_indices,
            bridge_source_slot_indices=bridge_source_slot_indices,
        )
        bindings.append(
            FacilityPortalBinding(
                facility_id=facility.facility_id,
                facade_key=_facade_key(facility),
                source_element_id=source_id,
                stage=facility.stage,
                kind=facility.kind,
                direction=facility.direction,
                raw_entry_point=raw_entry,
                entry_point=facility.position,
                entry_level_id=entry_level,
                raw_exit_point=raw_exit,
                exit_point=facility.exit_position,
                exit_level_id=exit_level,
                release_forward=release_forward,
                release_lateral=(-release_forward[1], release_forward[0]),
                approach_point=approach,
                queue_slots=slots,
                queue_slot_bindings=slot_bindings,
                approach_slots=approach_slots,
                approach_source_slot_indices=approach_source_slot_indices,
                approach_slot_indices=approach_slot_indices,
                queue_id=queue_id,
                source_queue_capacity=0 if queue is None else int(queue.capacity),
                declared_queue_capacity=len(approach_slots),
                queue_spacing_m=(
                    float(facility.fallback_queue_spacing)
                    if queue is None
                    else float(queue.spacing_m)
                ),
                projection_distance_m=max(
                    _distance(raw_entry, facility.position),
                    _distance(raw_exit, facility.exit_position),
                ),
                policy_fingerprint=fingerprint,
                activation_group_id=(
                    facility.facility_id if facility.kind == "escalator" else None
                ),
                activation_variant_id=(
                    facility.direction if facility.kind == "escalator" else None
                ),
                queue_topology_version=1,
                topology_fingerprint=_topology_fingerprint(slot_bindings),
                fallback_used=queue is None or queue.service_direction is None,
                queue_region=None if queue is None else element_shape(queue.geometry),
            )
        )
    return tuple(bindings)


def compile_reversed_escalator_portal_binding(
    document: StationDesignDocument,
    facility: FacilitySpec,
    binding: FacilityPortalBinding,
    *,
    policy: GeometryCompilePolicy,
) -> tuple[FacilitySpec, FacilityPortalBinding]:
    if facility.kind != "escalator" or binding.kind != "escalator":
        raise ValueError("only escalator facades have reversible portal bindings")
    direction = "up" if binding.direction == "down" else "down"
    entry = binding.exit_point
    exit_point = binding.entry_point
    entry_level = binding.exit_level_id
    exit_level = binding.entry_level_id
    domain = level_walkable_geometry(document, entry_level).buffer(-policy.agent_radius_m)
    if domain.is_empty:
        raise ValueError(f"reversed escalator entry level {entry_level!r} has no safe domain")
    spacing = max(0.4, float(binding.queue_spacing_m))
    slot_count = max(2, len(binding.queue_slots))
    dx = entry[0] - exit_point[0]
    dy = entry[1] - exit_point[1]
    length = hypot(dx, dy)
    directions: list[Point] = []
    if length > 0.001:
        forward = dx / length, dy / length
        directions.extend(
            (forward, (-forward[0], -forward[1]), (-forward[1], forward[0]), (forward[1], -forward[0]))
        )
    centroid = domain.centroid
    toward_center = float(centroid.x) - entry[0], float(centroid.y) - entry[1]
    center_length = hypot(*toward_center)
    if center_length > 0.001:
        directions.insert(0, (toward_center[0] / center_length, toward_center[1] / center_length))
    selected: tuple[Point, ...] | None = None
    for vector in directions:
        slots = (
            entry,
            *tuple(
                (
                    round(entry[0] + vector[0] * spacing * index, 4),
                    round(entry[1] + vector[1] * spacing * index, 4),
                )
                for index in range(1, slot_count)
            ),
        )
        if all(domain.buffer(_NUMERICAL_TOLERANCE_M).covers(ShapelyPoint(point)) for point in slots):
            selected = slots
            break
    if selected is None:
        raise ValueError(
            f"escalator {facility.facility_id!r} has no body-safe compiled reverse queue"
        )
    queue_region = LineString(selected).buffer(
        max(policy.agent_radius_m, spacing * 0.55),
        cap_style="round",
    )
    reversed_layout = QueueLayout(
        anchor=selected[0],
        per_row=1,
        col_step=(0.0, 0.0),
        row_step=(
            selected[1][0] - selected[0][0],
            selected[1][1] - selected[0][1],
        ),
        slots=selected,
    )
    reversed_spec = replace(
        facility,
        direction=direction,
        position=entry,
        exit_position=exit_point,
        entry_level_id=entry_level,
        exit_level_id=exit_level,
        queue_layout=reversed_layout,
        release_route=tuple(reversed(facility.release_route)),
    )
    source_indices = tuple(range(1, len(selected)))
    runtime_indices = tuple(range(1, len(selected)))
    slot_bindings = _queue_slot_bindings(
        reversed_spec,
        reversed_layout,
        selected,
        queue_id=f"compiled_reverse:{binding.facility_id}",
        approach_source_slot_indices=source_indices,
        approach_slot_indices=runtime_indices,
        bridge_source_slot_indices=(),
    )
    reversed_binding = FacilityPortalBinding(
        facility_id=binding.facility_id,
        facade_key=f"{binding.facade_key}|compiled_reverse:{direction}",
        source_element_id=binding.source_element_id,
        stage=binding.stage,
        kind=binding.kind,
        direction=direction,
        raw_entry_point=entry,
        entry_point=entry,
        entry_level_id=entry_level,
        raw_exit_point=exit_point,
        exit_point=exit_point,
        exit_level_id=exit_level,
        release_forward=_facility_release_forward(reversed_spec, None),
        release_lateral=(
            -_facility_release_forward(reversed_spec, None)[1],
            _facility_release_forward(reversed_spec, None)[0],
        ),
        approach_point=selected[-1],
        queue_slots=selected,
        queue_slot_bindings=slot_bindings,
        approach_slots=selected[1:],
        approach_source_slot_indices=source_indices,
        approach_slot_indices=runtime_indices,
        queue_id=f"compiled_reverse:{binding.facility_id}",
        # ``selected[0]`` is the service portal, not a standing place.  This
        # synthetic reverse queue therefore declares exactly the materialized
        # waiting capacity; counting the portal made every reversible variant
        # fail its own compile-time capacity gate by one slot.
        source_queue_capacity=len(selected) - 1,
        declared_queue_capacity=len(selected) - 1,
        queue_spacing_m=spacing,
        projection_distance_m=0.0,
        policy_fingerprint=_policy_fingerprint(policy),
        activation_group_id=binding.facility_id,
        activation_variant_id=direction,
        queue_topology_version=1,
        topology_fingerprint=_topology_fingerprint(slot_bindings),
        fallback_used=False,
        queue_region=queue_region,
    )
    return reversed_spec, reversed_binding


def _compiled_approach_slots(
    facility: FacilitySpec,
    slots: tuple[Point, ...],
    *,
    policy: GeometryCompilePolicy,
    graph: StationGraph | None,
    declared_capacity: int | None = None,
) -> tuple[
    tuple[Point, ...],
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...],
]:
    if not slots:
        return (), (), (), ()
    if facility.kind == "elevator":
        offset = _elevator_waiting_slot_offset(
            facility,
            slots,
            policy=policy,
            graph=graph,
            declared_capacity=declared_capacity,
        )
        waiting = slots[
            offset : (
                None
                if declared_capacity is None
                else offset + max(0, declared_capacity)
            )
        ]
        return (
            waiting,
            tuple(range(len(waiting))),
            tuple(range(offset, offset + len(waiting))),
            (),
        )
    if facility.kind in {"stairs", "escalator"}:
        # Slot zero is the mechanical entry. Authored vertical queues can
        # contain additional near-entry geometry that is useful for drawing
        # the facade but is not a safe standing target: a queued body there
        # would already occupy the service capture disk. This was formerly a
        # runtime-only filter; compiling it here makes the binding authoritative.
        minimum_service_distance = minimum_vertical_approach_distance(
            agent_radius_m=policy.agent_radius_m,
            personal_space_m=policy.personal_space_m,
        )
        candidates = tuple(
            index
            for index, point in enumerate(slots)
            if index > 0
            and _distance(point, facility.position)
            >= minimum_service_distance - _NUMERICAL_TOLERANCE_M
        )
        indices = (
            candidates
            if declared_capacity is None
            else candidates[: max(0, declared_capacity)]
        )
        first_waiting_index = min(indices, default=len(slots))
        bridge_indices = tuple(range(1, first_waiting_index))
        return (
            tuple(slots[index] for index in indices),
            indices,
            indices,
            bridge_indices,
        )
    stop = (
        len(slots)
        if declared_capacity is None
        else min(len(slots), max(0, declared_capacity))
    )
    indices = tuple(range(stop))
    return slots[:stop], indices, indices, ()


def _queue_slot_bindings(
    facility: FacilitySpec,
    layout: QueueLayout,
    slots: tuple[Point, ...],
    *,
    queue_id: str | None,
    approach_source_slot_indices: tuple[int, ...],
    approach_slot_indices: tuple[int, ...],
    bridge_source_slot_indices: tuple[int, ...],
) -> tuple[QueueSlotBinding, ...]:
    per_row = max(1, int(layout.per_row))
    runtime_by_source = dict(
        zip(
            approach_source_slot_indices,
            approach_slot_indices,
            strict=True,
        )
    )
    rank_by_source = {
        source_index: rank
        for rank, source_index in enumerate(approach_source_slot_indices)
    }
    bridge_sources = frozenset(int(index) for index in bridge_source_slot_indices)
    lane_id = "|".join(
        (
            queue_id or "unbound",
            facility.facility_id,
            facility.direction,
        )
    )
    return tuple(
        QueueSlotBinding(
            slot_id=(
                f"{facility.facility_id}:{facility.direction}:source_slot:{source_index}"
            ),
            position=position,
            lane_id=lane_id,
            row_index=(
                -1
                if source_index not in rank_by_source
                else rank_by_source[source_index] // per_row
            ),
            position_in_row=(
                -1
                if source_index not in rank_by_source
                else rank_by_source[source_index] % per_row
            ),
            service_rank=rank_by_source.get(source_index),
            runtime_slot_index=runtime_by_source.get(source_index),
            role=(
                "waiting"
                if source_index in rank_by_source
                else "bridge"
                if source_index in bridge_sources
                else "service_portal"
            ),
        )
        for source_index, position in enumerate(slots)
    )


def _elevator_waiting_slot_offset(
    facility: FacilitySpec,
    slots: tuple[Point, ...],
    *,
    policy: GeometryCompilePolicy,
    graph: StationGraph | None,
    declared_capacity: int | None,
) -> int:
    if len(slots) <= 1:
        return 0
    forward = _facility_release_forward(facility, graph)
    minimum = max(0.05, policy.two_body_clearance_m)
    clearance = minimum + float(facility.release_clearance_pad)
    personal = policy.personal_space_m * float(facility.release_personal_factor)
    spacing = max(
        float(facility.release_spacing_min),
        min(float(facility.release_spacing_max), max(clearance, personal)),
    )
    elevator = (
        None
        if facility.vertical_config is None
        else facility.vertical_config.elevator
    )
    batch_capacity = (
        len(slots) - 1 if elevator is None else max(1, int(elevator.batch_capacity))
    )
    maximum_arrival_bodies = max(
        1,
        min(
            batch_capacity,
            len(slots) - 1,
            len(slots) - 1 if declared_capacity is None else max(1, declared_capacity),
        ),
    )
    # The waiting line must clear the whole native arrival footprint, not
    # merely the portal centre. JuPedSim inserts a complete cabin grid before
    # unloading; a queue body outside the door corridor can still overlap a
    # corner cell and deadlock every chained elevator facade on that landing.
    # Mirror the runtime cabin grid dimensions and spacing so this is a
    # compile-time geometry contract for any layout/capacity combination.
    cabin_spacing = max(
        spacing,
        policy.personal_space_m,
        clearance,
    )
    column_count = max(1, ceil(sqrt(maximum_arrival_bodies)))
    row_count = max(1, ceil(maximum_arrival_bodies / column_count))
    maximum_cabin_offset = hypot(
        (row_count - 1) * cabin_spacing / 2.0,
        (column_count - 1) * cabin_spacing / 2.0,
    )
    arrival_clearance_radius = maximum_cabin_offset + clearance
    corridor_length = spacing * max(1, int(facility.release_forward_extra))
    portal = facility.position
    corridor = LineString(
        (
            portal,
            (
                portal[0] - forward[0] * corridor_length,
                portal[1] - forward[1] * corridor_length,
            ),
        )
    )
    for index, slot in enumerate(slots[1:], start=1):
        if (
            corridor.distance(ShapelyPoint(slot)) >= minimum - _NUMERICAL_TOLERANCE_M
            and _distance(portal, slot)
            >= arrival_clearance_radius - _NUMERICAL_TOLERANCE_M
        ):
            return index
    raise ValueError(
        f"elevator {facility.facility_id!r} has no compiled waiting slot outside "
        "its unloading corridor"
    )


def _facility_release_forward(
    facility: FacilitySpec,
    graph: StationGraph | None,
) -> Point:
    if facility.release_forward_hint is not None:
        dx = float(facility.release_forward_hint[0])
        dy = float(facility.release_forward_hint[1])
        length = hypot(dx, dy)
        if length <= 0.001:
            raise ValueError(
                f"facility {facility.facility_id!r} has a zero release-forward hint"
            )
        return dx / length, dy / length
    start = facility.position
    end = facility.exit_position
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = hypot(dx, dy)
    # Stacked elevator portals commonly have identical XY coordinates.  The
    # entry queue is on the *other* side of the connector contract and may be
    # laterally offset by generated-layout collision avoidance, so deriving
    # ``exit - queue_anchor`` points back into the cabin and is not a release
    # direction.  The authored same-level walk edge is the authoritative
    # outward direction at the exit landing.
    if length <= 0.001 and graph is not None and facility.source_element_id is not None:
        exit_nodes = [
            graph.nodes[node_id]
            for node_id in graph.node_ids_for_element(facility.source_element_id)
            if node_id in graph.nodes
            and (
                facility.exit_level_id is None
                or graph.nodes[node_id].level_id == facility.exit_level_id
            )
        ]
        if exit_nodes:
            exit_node = min(
                exit_nodes,
                key=lambda node: _distance(node.position, end),
            )
            for neighbor in graph.same_level_walk_neighbor_positions(exit_node.node_id):
                dx = neighbor[0] - end[0]
                dy = neighbor[1] - end[1]
                length = hypot(dx, dy)
                if length > 0.001:
                    break
    if length <= 0.001:
        anchor = facility.queue_layout.anchor
        dx = anchor[0] - end[0]
        dy = anchor[1] - end[1]
        length = hypot(dx, dy)
    if length <= 0.001:
        raise ValueError(
            f"vertical connector {facility.facility_id!r} has no compiled release axis"
        )
    return dx / length, dy / length


def _raw_facility_portals(
    document: StationDesignDocument,
    element: DesignElement,
    facility: FacilitySpec,
) -> tuple[Point, Point]:
    if element.role == "vertical_connector":
        levels = document.level_by_id()
        return (
            vertical_landing_position(
                element,
                facility.entry_level_id or element.level_id,
                levels,
                walkable_geometry=None,
            ),
            vertical_landing_position(
                element,
                facility.exit_level_id or element.level_id,
                levels,
                walkable_geometry=None,
            ),
        )
    if element.kind in {"gate", "platform_edge"}:
        # Gate and platform-edge portals are facade points selected by their
        # compiled queue.  A long platform edge's geometric centre is only a
        # graph representative and need not coincide with its boarding door.
        return facility.position, facility.exit_position
    center = element.geometry.center()
    return center, center


def _policy_fingerprint(policy: GeometryCompilePolicy) -> str:
    payload = json.dumps(asdict(policy), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "PROJECTION_TOLERANCE_M",
    "compile_facility_portal_bindings",
    "compile_reversed_escalator_portal_binding",
    "validate_facility_portals",
    "validate_portal_binding_compatibility",
    "validate_portal_binding_configuration",
]
