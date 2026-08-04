from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from math import ceil


from ..planning.plan import AgentState, FacilityStage, RouteKey
from ..design.helpers import (
    gate_direction as _gate_direction,
    platform_direction as _platform_direction,
    platform_line_id as _platform_line_id,
    vertical_direction as _vertical_direction,
)
from ..design.schema import (
    MIN_COMPILED_QUEUE_SPACING_M,
    DesignElement,
    QueueSpec,
)
from ..design.vertical_landing import vertical_landing_outward_direction
from ..facilities.process import (
    DEFAULT_FALLBACK_QUEUE_CAPACITY,
    DEFAULT_FALLBACK_QUEUE_SPACING,
    DEFAULT_RELEASE_FORWARD_EXTRA,
    DEFAULT_RELEASE_SPACING_MAX,
    FacilityKind,
    FacilitySpec,
    QueueCrossingGuard,
)
from ..facilities.vertical import (
    VerticalFacilityConfig,
    default_elevator_config,
    default_escalator_config,
    default_stairs_config,
)
from .geometry import (
    dedupe_points,
    document_walkable_geometry,
    element_shape,
    level_walkable_geometry,
    project_to_safe_point,
    safe_core,
)
from .scenario import StationSandboxScenario
from .graph import GraphEdge, GraphNode, StationGraph
from .layout_gate_queues import (
    _gate_lane_count,
    _gate_lane_positions,
    _gate_lane_queue_layout,
    _gate_queue_crossing_guard,
)
from .layout_queue_geometry import (
    MAX_COMPILED_QUEUE_CAPACITY,
    _point_distance,
    _queue_layout,
    _queue_layout_behind_service_entry,
    _queue_layout_with_service_entry_slot,
    minimum_vertical_approach_distance,
)
from .layout_types import LayoutEdge, LayoutNode, Point
from .layout_vertical_facilities import (
    build_vertical_config as _build_vertical_config,
    default_vertical_service_rate as _default_vertical_service_rate,
    facility_kind_for_element as _facility_kind_for_element,
    link_stair_siblings as _link_stair_siblings,
    node_position as _node_position,
    queue_approach_forward as _queue_approach_forward,
    vertical_speed as _vertical_speed,
    vertical_speed_m_s as _vertical_speed_m_s,
    vertical_traversal_width as _vertical_traversal_width,
)


def _legacy_vertical_config(transport, scenario: StationSandboxScenario) -> VerticalFacilityConfig:
    if transport.kind == FacilityKind.ELEVATOR.value:
        return VerticalFacilityConfig(
            elevator=default_elevator_config(
                batch_capacity=scenario.elevator_cabin_capacity_persons,
                min_dispatch_persons=scenario.elevator_min_dispatch_persons,
                max_dispatch_wait_seconds=scenario.elevator_max_dispatch_wait_seconds,
                boarding_seconds=scenario.elevator_boarding_seconds,
                travel_seconds=scenario.elevator_cycle_seconds,
                unload_seconds=scenario.elevator_unload_seconds,
            )
        )
    if transport.kind == FacilityKind.STAIRS.value:
        return VerticalFacilityConfig(
            stairs=default_stairs_config(
                base_capacity_ppm=transport.persons_per_min,
                fatigue_cost_up=scenario.stair_fatigue_cost_up,
                fatigue_cost_down=scenario.stair_fatigue_cost_down,
                bidirectional_conflict_factor=scenario.stair_bidirectional_conflict_factor,
            )
        )
    return VerticalFacilityConfig(escalator=default_escalator_config(transport.persons_per_min))


def _layout_nodes_from_station_graph(nodes: dict[str, GraphNode]) -> dict[str, LayoutNode]:
    return {
        node_id: LayoutNode(node.node_id, node.node_id, node.position, node.level_id)
        for node_id, node in nodes.items()
    }


def _layout_edges_from_station_graph(edges: tuple[GraphEdge, ...]) -> tuple[LayoutEdge, ...]:
    return tuple(
        LayoutEdge(edge.from_node, edge.to_node, edge.kind)
        for edge in edges
        if edge.kind in {"walk", "vertical"}
    )


def _facility_specs_from_station_graph(
    station_graph: StationGraph,
    scenario: StationSandboxScenario,
) -> list[FacilitySpec]:
    document = station_graph.source_document
    if document is None:
        return []

    levels_by_id = document.level_by_id()
    walkable_geometry = document_walkable_geometry(document)
    facilities: list[FacilitySpec] = []

    for element in document.elements:
        owner_queues = tuple(
            queue for queue in document.queues if queue.owner_element_id == element.id
        )
        queue = owner_queues[0] if owner_queues else None
        element_level_domain = level_walkable_geometry(
            document,
            element.level_id,
            walkable_geometry,
        )
        if element.kind == "gate":
            facilities.extend(
                _gate_facility_specs(
                    element,
                    owner_queues,
                    station_graph,
                    scenario,
                    walkable_geometry=element_level_domain,
                )
            )
        elif element.role == "vertical_connector":
            ordered_levels = sorted(
                element.connects_levels,
                key=lambda level_id: levels_by_id[level_id].elevation_m,
                reverse=True,
            )
            direction = _vertical_direction(element)
            for upper, lower in zip(ordered_levels, ordered_levels[1:]):
                upper_position = _node_position(station_graph, f"vertical:{element.id}:{upper}")
                lower_position = _node_position(station_graph, f"vertical:{element.id}:{lower}")
                if direction in {"down", "both"}:
                    facilities.append(
                        _vertical_facility_spec(
                            element,
                            _vertical_facade_queue(
                                owner_queues,
                                level_id=upper,
                                direction="down",
                            ),
                            scenario,
                            direction="down",
                            position=upper_position,
                            exit_position=lower_position,
                            level_pair=(upper, lower),
                            walkable_geometry=level_walkable_geometry(
                                document,
                                upper,
                                walkable_geometry,
                            ),
                        )
                    )
                if direction in {"up", "both"}:
                    facilities.append(
                        _vertical_facility_spec(
                            element,
                            _vertical_facade_queue(
                                owner_queues,
                                level_id=lower,
                                direction="up",
                            ),
                            scenario,
                            direction="up",
                            position=lower_position,
                            exit_position=upper_position,
                            level_pair=(lower, upper),
                            walkable_geometry=level_walkable_geometry(
                                document,
                                lower,
                                walkable_geometry,
                            ),
                        )
                    )
        elif element.kind == "platform_edge":
            # A platform edge can expose a boarding facade anywhere along its
            # authored length.  Generated holding areas deliberately scan that
            # facade for a clear interval, so the compiled door portal must be
            # the selected service point rather than the graph representative
            # (which remains the platform node's routing centroid).
            position = (
                _node_position(station_graph, f"platform:{element.id}")
                if queue is None
                else queue.service_point_m
            )
            line_id = _platform_line_id(element)
            direction = _platform_direction(element)
            queue_layout = _queue_layout(
                queue,
                default_anchor=position,
                per_row=scenario.boarding_queue_slots_per_row,
                walkable_geometry=element_level_domain,
            )
            facilities.append(
                FacilitySpec(
                    facility_id=f"boarding_door:{element.id}",
                    stage=FacilityStage.BOARDING_DOOR.value,
                    label=element.label,
                    kind=FacilityKind.TRAIN_DOOR.value,
                    direction=direction,
                    position=position,
                    queue_layout=queue_layout,
                    exit_position=position,
                    service_persons_per_min=scenario.boarding_persons_per_min,
                    queue_state=AgentState.QUEUEING_DOOR.value,
                    service_state=AgentState.BOARDING_TRAIN.value,
                    release_route=(queue_layout.anchor, position),
                    train_gated=True,
                    train_capacity_limited=True,
                    line_id=line_id,
                    platform_id=f"platform:{line_id}:{direction}",
                    entry_level_id=element.level_id,
                    exit_level_id=element.level_id,
                    source_element_id=element.id,
                )
            )

    return _link_stair_siblings(facilities)


def _gate_facility_specs(
    element: DesignElement,
    queues: tuple[QueueSpec, ...],
    station_graph: StationGraph,
    scenario: StationSandboxScenario,
    *,
    walkable_geometry,
) -> list[FacilitySpec]:
    gate_direction = _gate_direction(element)
    facilities: list[FacilitySpec] = []
    if gate_direction in {"entry", "bidirectional"}:
        queue = _gate_facade_queue(queues, direction="in")
        position = _node_position(station_graph, f"gate:{element.id}:entry")
        exit_position = _node_position(station_graph, f"gate:{element.id}:paid")
        facilities.extend(
            _gate_lane_facility_specs(
                element,
                queue,
                scenario,
                stage=FacilityStage.ENTRY_GATE.value,
                facility_prefix="entry_gate",
                direction="in",
                position=position,
                exit_position=exit_position,
                queue_state=AgentState.QUEUEING_GATE.value,
                service_state=AgentState.PASSING_GATE.value,
                walkable_geometry=walkable_geometry,
                queue_crossing_guard=_gate_queue_crossing_guard(
                    scenario,
                    enabled=True,
                ),
            )
        )
    if gate_direction in {"exit", "bidirectional"}:
        queue = _gate_facade_queue(queues, direction="out")
        position = _node_position(station_graph, f"gate:{element.id}:exit")
        exit_position = _node_position(station_graph, f"gate:{element.id}:unpaid")
        facilities.extend(
            _gate_lane_facility_specs(
                element,
                queue,
                scenario,
                stage=FacilityStage.EXIT_GATE.value,
                facility_prefix="exit_gate",
                direction="out",
                position=position,
                exit_position=exit_position,
                queue_state=AgentState.QUEUEING_EXIT_GATE.value,
                service_state=AgentState.PASSING_EXIT_GATE.value,
                walkable_geometry=walkable_geometry,
                queue_crossing_guard=_gate_queue_crossing_guard(
                    scenario,
                    enabled=False,
                ),
            )
        )
    return facilities


def _gate_facade_queue(
    queues: tuple[QueueSpec, ...],
    *,
    direction: str,
) -> QueueSpec | None:
    exact = tuple(queue for queue in queues if queue.service_direction == direction)
    if len(exact) > 1:
        raise ValueError(f"multiple gate queues declare direction {direction!r}")
    if exact:
        return exact[0]
    legacy = tuple(queue for queue in queues if queue.service_direction is None)
    if len(legacy) > 1:
        raise ValueError("multiple undirected gate queues declared")
    return legacy[0] if legacy else None


def _gate_lane_facility_specs(
    element: DesignElement,
    queue: QueueSpec | None,
    scenario: StationSandboxScenario,
    *,
    stage: str,
    facility_prefix: str,
    direction: str,
    position: Point,
    exit_position: Point,
    queue_state: str,
    service_state: str,
    walkable_geometry,
    queue_crossing_guard: QueueCrossingGuard,
) -> list[FacilitySpec]:
    lane_count = _gate_lane_count(element)
    base_layout = _queue_layout(
        queue,
        default_anchor=position,
        per_row=scenario.gate_queue_slots_per_row,
        walkable_geometry=walkable_geometry,
        fallback_queue_spacing=DEFAULT_FALLBACK_QUEUE_SPACING,
    )
    lane_positions = _gate_lane_positions(
        element,
        lane_count,
        position,
        exit_position,
        queue=queue,
        edge_inset_max=scenario.gate_lane_edge_inset_max,
    )
    fallback_queue_spacing = DEFAULT_FALLBACK_QUEUE_SPACING
    fallback_queue_capacity = DEFAULT_FALLBACK_QUEUE_CAPACITY
    facilities: list[FacilitySpec] = []
    for lane_index, (lane_position, lane_exit_position) in enumerate(lane_positions):
        facility_id = (
            f"{facility_prefix}:{element.id}"
            if lane_count == 1
            else f"{facility_prefix}:{element.id}:lane_{lane_index + 1}"
        )
        label = element.label if lane_count == 1 else f"{element.label} lane {lane_index + 1}"
        facilities.append(
            FacilitySpec(
                facility_id=facility_id,
                stage=stage,
                label=label,
                kind=FacilityKind.GATE.value,
                direction=direction,
                position=lane_position,
                queue_layout=_gate_lane_queue_layout(
                    base_layout,
                    element,
                    queue=queue,
                    lane_index=lane_index,
                    lane_count=lane_count,
                    lane_position=lane_position,
                    walkable_geometry=walkable_geometry,
                    edge_inset_max=scenario.gate_lane_edge_inset_max,
                    fallback_queue_spacing=fallback_queue_spacing,
                    fallback_queue_capacity=fallback_queue_capacity,
                ),
                exit_position=lane_exit_position,
                service_persons_per_min=scenario.gate_service_persons_per_min,
                queue_state=queue_state,
                service_state=service_state,
                release_route=(lane_position, lane_exit_position),
                entry_level_id=element.level_id,
                exit_level_id=element.level_id,
                source_element_id=element.id,
                fallback_queue_spacing=fallback_queue_spacing,
                fallback_queue_capacity=fallback_queue_capacity,
                queue_crossing_guard=queue_crossing_guard,
            )
        )
    return facilities


def _route_registry_from_station_graph(
    station_graph: StationGraph,
) -> dict[str, Callable[[Point, object | None], tuple[Point, ...]]]:
    gate_decision_points = _gate_decision_points_by_stage(station_graph)
    return {
        RouteKey.CURRENT_POSITION.value: lambda start, _passenger=None: (start,),
        RouteKey.ENTRY_GATE_DECISION.value: lambda start, _passenger=None: _gate_decision_route(
            station_graph,
            start,
            FacilityStage.ENTRY_GATE.value,
            gate_decision_points.get(FacilityStage.ENTRY_GATE.value, ()),
            start_level_id=_route_start_level(_passenger),
        ),
        RouteKey.AFTER_GATE.value: lambda start, _passenger=None: (
            station_graph.route_from_position_to(
                start,
                kind="facility_entry",
                facility_stage=FacilityStage.VERTICAL_TRANSFER.value,
                direction=("down", "both"),
                start_level_id=_route_start_level(_passenger),
                start_kind="facility_exit",
                start_facility_stage=FacilityStage.ENTRY_GATE.value,
            )
        ),
        RouteKey.AFTER_VERTICAL.value: lambda start, passenger=None: _after_vertical_route(
            station_graph, start, passenger
        ),
        RouteKey.PLATFORM_TO_VERTICAL.value: lambda start, _passenger=None: (
            station_graph.route_from_position_to(
                start,
                kind="facility_entry",
                facility_stage=FacilityStage.VERTICAL_TRANSFER.value,
                direction=("up", "both"),
                start_level_id=_route_start_level(_passenger),
            )
        ),
        RouteKey.AFTER_EXIT_VERTICAL.value: lambda start, _passenger=None: _gate_decision_route(
            station_graph,
            start,
            FacilityStage.EXIT_GATE.value,
            gate_decision_points.get(FacilityStage.EXIT_GATE.value, ()),
            start_level_id=_route_start_level(_passenger),
        ),
    }


def _gate_decision_points_by_stage(
    station_graph: StationGraph,
) -> dict[str, tuple[Point, ...]]:
    document = station_graph.source_document
    if document is None:
        return {}

    queues_by_owner = {queue.owner_element_id: queue for queue in document.queues}
    walkable_geometry = document_walkable_geometry(document)
    points_by_stage: dict[str, list[Point]] = {
        FacilityStage.ENTRY_GATE.value: [],
        FacilityStage.EXIT_GATE.value: [],
    }
    for element in document.elements:
        if element.kind != "gate":
            continue
        queue = queues_by_owner.get(element.id)
        if queue is None:
            continue

        point = _queue_approach_point(
            queue,
            level_walkable_geometry(document, queue.level_id, walkable_geometry),
        )
        gate_direction = _gate_direction(element)
        if gate_direction in {"entry", "bidirectional"}:
            points_by_stage[FacilityStage.ENTRY_GATE.value].append(point)
        if gate_direction in {"exit", "bidirectional"}:
            points_by_stage[FacilityStage.EXIT_GATE.value].append(point)

    return {stage: tuple(dedupe_points(points)) for stage, points in points_by_stage.items()}


def _queue_approach_point(
    queue: QueueSpec,
    walkable_geometry,
) -> Point:
    shape = element_shape(queue.geometry)
    domain = shape
    if walkable_geometry is not None:
        clipped = shape.intersection(walkable_geometry)
        if not clipped.is_empty:
            domain = clipped

    core = safe_core(domain, min(0.18, max(0.05, queue.spacing_m * 0.2)))
    min_x, min_y, max_x, max_y = core.bounds
    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    service_x, service_y = queue.service_point_m
    span_x = max_x - min_x
    span_y = max_y - min_y

    if abs(service_x - center[0]) >= abs(service_y - center[1]):
        offset = min(max(0.15, queue.spacing_m * 0.5), max(0.0, span_x / 2.0))
        x = min_x + offset if service_x > center[0] else max_x - offset
        raw = (x, center[1])
    else:
        offset = min(max(0.15, queue.spacing_m * 0.5), max(0.0, span_y / 2.0))
        y = min_y + offset if service_y > center[1] else max_y - offset
        raw = (center[0], y)

    return project_to_safe_point(core, raw, clearance=0.0, require_inside=False)


def _gate_decision_route(
    station_graph: StationGraph,
    start: Point,
    stage: str,
    decision_points: tuple[Point, ...],
    *,
    start_level_id: str | None,
) -> tuple[Point, ...]:
    if not decision_points:
        return station_graph.route_from_position_to(
            start,
            kind="facility_entry",
            facility_stage=stage,
            start_level_id=start_level_id,
        )

    decision_point = min(decision_points, key=lambda point: _point_distance(start, point))
    return (decision_point,)


def _route_platform_line_id(passenger: object | None) -> str | None:
    return getattr(passenger, "assigned_line_id", None)


def _after_vertical_route(
    station_graph: StationGraph,
    start: Point,
    passenger: object | None,
) -> tuple[Point, ...]:
    return station_graph.route_from_position_to(
        start,
        kind="platform",
        direction=_route_platform_direction(passenger),
        line_id=_route_platform_line_id(passenger),
        start_level_id=_route_start_level(passenger),
    )


def _route_platform_direction(passenger: object | None) -> str | tuple[str | None, ...] | None:
    direction = getattr(passenger, "assigned_direction", None)
    return direction if direction is not None else ("down", None)


def _route_start_level(passenger: object | None) -> str | None:
    return getattr(passenger, "current_level_id", None)


def _vertical_facility_spec(
    element: DesignElement,
    queue: QueueSpec | None,
    scenario: StationSandboxScenario,
    *,
    direction: str,
    position: Point,
    exit_position: Point,
    level_pair: tuple[str, str],
    walkable_geometry,
) -> FacilitySpec:
    # The station graph owns the connector portal. A QueueSpec describes the
    # waiting domain on one landing; its authored service point must not move
    # the physical connector endpoint or shorten the inter-floor traversal.
    service_entry = position
    if queue is not None and _point_distance(
        queue.service_point_m,
        service_entry,
    ) > max(0.35, float(queue.spacing_m) * 1.6):
        raise ValueError(
            f"queue {queue.id!r} is detached from directional landing "
            f"{element.id!r} {level_pair[0]!r} {direction!r}"
        )
    queue_for_compilation = (
        replace(
            queue,
            service_point_m=service_entry,
            capacity=_vertical_queue_compilation_capacity(
                queue,
                element,
                scenario,
            ),
        )
        if queue is not None
        else None
    )
    queue_layout = _queue_layout(
        queue_for_compilation,
        default_anchor=service_entry,
        per_row=scenario.vertical_queue_slots_per_row,
        walkable_geometry=walkable_geometry,
    )
    queue_layout = _queue_layout_behind_service_entry(
        queue_layout,
        service_entry,
        exit_position,
        approach_forward=(
            None
            if element.kind in {FacilityKind.STAIRS.value, FacilityKind.ESCALATOR.value}
            else _queue_approach_forward(queue_layout, service_entry)
        ),
    )
    queue_layout = _queue_layout_with_service_entry_slot(
        queue_layout,
        service_entry,
        walkable_geometry=walkable_geometry,
    )
    return FacilitySpec(
        facility_id=f"vertical:{element.id}:{direction}:{level_pair[0]}:{level_pair[1]}",
        stage=FacilityStage.VERTICAL_TRANSFER.value,
        label=element.label,
        kind=_facility_kind_for_element(element),
        direction=direction,
        position=service_entry,
        queue_layout=queue_layout,
        exit_position=exit_position,
        service_persons_per_min=element.capacity or _default_vertical_service_rate(element),
        queue_state=AgentState.QUEUEING_VERTICAL.value,
        service_state=AgentState.RIDING_VERTICAL.value,
        release_route=(service_entry, exit_position),
        speed_units_per_tick=_vertical_speed(element, scenario),
        travel_speed_m_s=_vertical_speed_m_s(element, scenario),
        entry_level_id=level_pair[0],
        exit_level_id=level_pair[1],
        source_element_id=element.id,
        vertical_config=_build_vertical_config(element, scenario),
        traversal_width_m=_vertical_traversal_width(
            element,
            service_entry,
            exit_position,
            scenario,
        ),
        release_forward_hint=(
            vertical_landing_outward_direction(element)
            if element.kind == FacilityKind.ELEVATOR.value
            and _point_distance(service_entry, exit_position) <= 0.001
            else None
        ),
    )


def _vertical_queue_compilation_capacity(
    queue: QueueSpec,
    element: DesignElement,
    scenario: StationSandboxScenario,
) -> int:
    """Include operational portal/corridor slots without shrinking occupancy.

    Source capacity counts waiting bodies. The internal path also needs one
    service-entry point and, for elevators, enough prefix points to keep the
    full unloading corridor free. The reserve follows the same physical
    release constants as ``FacilitySpec`` instead of a template-sized magic
    number.
    """

    minimum_approach_distance = minimum_vertical_approach_distance(
        agent_radius_m=float(scenario.jupedsim_agent_radius_units),
        personal_space_m=float(scenario.personal_space_units),
    )
    # The service point and every sub-setback prefix point are non-occupiable
    # topology bridges. Generate enough tail candidates that removing those
    # bridge points cannot silently shrink the authored waiting capacity.
    reserve = max(
        1,
        int(ceil(minimum_approach_distance / max(0.001, float(queue.spacing_m)))),
    )
    if element.kind == FacilityKind.ELEVATOR.value:
        corridor_length = (
            DEFAULT_RELEASE_SPACING_MAX * DEFAULT_RELEASE_FORWARD_EXTRA
        )
        reserve += int(
            ceil(
                corridor_length
                / max(MIN_COMPILED_QUEUE_SPACING_M, float(queue.spacing_m))
            )
        )
    return min(
        MAX_COMPILED_QUEUE_CAPACITY,
        int(queue.capacity) + reserve,
    )


def _vertical_facade_queue(
    queues: tuple[QueueSpec, ...],
    *,
    level_id: str,
    direction: str,
) -> QueueSpec | None:
    on_landing = tuple(queue for queue in queues if queue.level_id == level_id)
    exact = tuple(
        queue for queue in on_landing if queue.service_direction == direction
    )
    if len(exact) > 1:
        raise ValueError(
            f"multiple queues declare landing {level_id!r} direction {direction!r}"
        )
    if exact:
        return exact[0]
    legacy = tuple(queue for queue in on_landing if queue.service_direction is None)
    if len(legacy) > 1:
        raise ValueError(f"multiple undirected queues declare landing {level_id!r}")
    return legacy[0] if legacy else None
