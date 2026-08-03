from __future__ import annotations

from heapq import heappop, heappush
from math import hypot
from typing import Any

from metro_station.domain.journeys import journey_graph_for_facility_chain
from shapely.geometry import Point as ShapelyPoint

from ..agents.passenger import PassengerAgent
from ..planning.plan import AgentIntent, FacilityStage
from .passenger_goal_runtime import PassengerGoalRuntime
from .physical_waypoint_routing import PhysicalWaypointRouter


def reroot_evacuation_goal_runtime(
    model: Any,
    passenger: PassengerAgent,
    *,
    station_interior: bool,
) -> PassengerGoalRuntime:
    """Compile an alarm journey from physical position and paid-area state."""

    station_graph = getattr(model.layout_graph, "station_graph", None)
    if station_graph is None:
        return model.goal_runtime_for_intent(AgentIntent.EVACUATE_STATION)
    facility_path = (
        _vertical_facility_path_to_exit_component(model, passenger)
        if station_interior
        else ()
    )
    passenger.evacuation_facility_path = facility_path
    facility_chain = (
        (FacilityStage.VERTICAL_TRANSFER.value,) * len(facility_path)
        + (FacilityStage.EXIT_GATE.value,)
        if station_interior
        else ()
    )
    return PassengerGoalRuntime(
        journey_graph_for_facility_chain(
            graph_id="station_evacuation",
            facility_chain=facility_chain,
            terminal_region_id="safe_zone",
        )
    )


def refresh_evacuation_facility_path(
    model: Any,
    passenger: PassengerAgent,
) -> tuple[str, ...]:
    """Recompute current-cost connectors at a physical decision boundary."""

    facility_path = _vertical_facility_path_to_exit_component(model, passenger)
    passenger.evacuation_facility_path = facility_path
    return facility_path


def _vertical_facility_path_to_exit_component(
    model: Any,
    passenger: PassengerAgent,
) -> tuple[str, ...]:
    start_level = passenger.current_level_id
    if start_level is None:
        station_graph = model.layout_graph.station_graph
        start_level = station_graph.nearest_node(passenger.pos).level_id
    exit_gates = model._facilities_for_stage(FacilityStage.EXIT_GATE.value)
    if start_level is None or not exit_gates:
        raise ValueError(
            "station topology cannot re-root an interior evacuation journey: "
            f"level={start_level!r}, "
            f"exit_gate_entries={len(exit_gates)}"
        )

    components_by_level: dict[str, tuple[Any, ...]] = {}

    def component(level_id: str, point: tuple[float, float]) -> tuple[str, int]:
        components = components_by_level.setdefault(
            level_id,
            _walkable_components(model.jupedsim_walkable_area(level_id)),
        )
        if not components:
            raise ValueError(f"level {level_id!r} has no walkable evacuation component")
        probe = ShapelyPoint(point)
        index = min(
            range(len(components)),
            key=lambda item: (
                0 if components[item].buffer(1e-7).covers(probe) else 1,
                components[item].distance(probe),
                item,
            ),
        )
        return level_id, index

    start = component(start_level, tuple(passenger.pos))
    targets = {
        component(
            str(gate.spec.entry_level_id or start_level),
            tuple(gate.spec.position),
        )
        for gate in exit_gates
    }
    if start in targets:
        return ()

    all_adjacency: dict[tuple[str, int], list[tuple[float, tuple[str, int], str]]] = {}
    available_adjacency: dict[
        tuple[str, int], list[tuple[float, tuple[str, int], str]]
    ] = {}
    for facility in model._facilities_for_stage(FacilityStage.VERTICAL_TRANSFER.value):
        if facility.spec.direction not in {"up", "both"}:
            continue
        entry_level = facility.spec.entry_level_id
        exit_level = facility.spec.exit_level_id
        if entry_level is None or exit_level is None or entry_level == exit_level:
            continue
        source = component(entry_level, tuple(facility.spec.position))
        target = component(exit_level, tuple(facility.spec.exit_position))
        edge = (
            _vertical_service_cost_seconds(model, facility),
            target,
            facility.facility_id,
        )
        all_adjacency.setdefault(source, []).append(edge)
        # Queue saturation is temporary and must not remove a topological edge.
        # Forced closure or a genuinely non-running connector does.
        if (
            facility.is_open
            and _facility_portals_are_walkable(model, facility)
            and model.facility_has_reservable_approach_slot(passenger, facility)
        ):
            available_adjacency.setdefault(source, []).append(edge)

    available_path = _shortest_facility_path(
        model,
        passenger,
        start,
        targets,
        available_adjacency,
        require_walkable_routes=True,
    )
    if available_path is not None:
        return available_path
    # If every physical path is temporarily unavailable, retain a real path so
    # the passenger waits for recovery rather than being teleported or crashing
    # the run.  Any later availability event re-runs this choice.
    physical_path = _shortest_facility_path(
        model,
        passenger,
        start,
        targets,
        all_adjacency,
        require_walkable_routes=False,
    )
    if physical_path is not None:
        return physical_path
    raise ValueError(
        "station topology has no directed vertical-facility path from "
        f"{start!r} to an exit-gate walkable component"
    )


def _shortest_facility_path(
    model: Any,
    passenger: PassengerAgent,
    start: tuple[str, int],
    targets: set[tuple[str, int]],
    adjacency: dict[
        tuple[str, int], list[tuple[float, tuple[str, int], str]]
    ],
    *,
    require_walkable_routes: bool,
) -> tuple[str, ...] | None:
    start_state = (start, "")
    heap: list[
        tuple[float, tuple[tuple[str, int], str], tuple[str, ...]]
    ] = [(0.0, start_state, ())]
    best_cost: dict[tuple[tuple[str, int], str], float] = {start_state: 0.0}
    while heap:
        cost, state, path = heappop(heap)
        if cost > best_cost.get(state, float("inf")):
            continue
        component_state, previous_facility_id = state
        if component_state in targets:
            return path
        start_position = (
            tuple(passenger.pos)
            if not previous_facility_id
            else tuple(model.facilities_by_id[previous_facility_id].spec.exit_position)
        )
        for service_cost, next_component, facility_id in sorted(
            adjacency.get(component_state, ())
        ):
            facility = model.facilities_by_id[facility_id]
            try:
                walking_seconds = _walking_seconds_to_facility(
                    model,
                    passenger,
                    facility,
                    start_position=start_position,
                    level_id=component_state[0],
                    use_passenger_route_provider=not previous_facility_id,
                    require_walkable_route=require_walkable_routes,
                )
            except (RuntimeError, ValueError):
                continue
            new_cost = cost + walking_seconds + service_cost
            next_state = (next_component, facility_id)
            if new_cost >= best_cost.get(next_state, float("inf")):
                continue
            best_cost[next_state] = new_cost
            heappush(heap, (new_cost, next_state, (*path, facility_id)))
    return None


def _vertical_service_cost_seconds(model: Any, facility: Any) -> float:
    """Queue plus traversal seconds for one vertical connector."""

    traversal_seconds = max(0.001, float(facility.routing_traversal_seconds))
    service_rate = max(0.001, float(facility.effective_service_persons_per_min))
    targeting = getattr(model, "facility_targeting_persons", None)
    targeting_persons = int(targeting(facility)) if callable(targeting) else 0
    queue_seconds = (
        max(0, int(facility.queue_persons) + targeting_persons)
        / service_rate
        * 60.0
    )
    return traversal_seconds + queue_seconds


def _walking_seconds_to_facility(
    model: Any,
    passenger: PassengerAgent,
    facility: Any,
    *,
    start_position: tuple[float, float],
    level_id: str,
    use_passenger_route_provider: bool,
    require_walkable_route: bool,
) -> float:
    """Use the tactical waypoint route for every same-component transfer."""

    walk_speed = max(0.001, float(model.desired_walk_speed_mps(passenger)))
    if not require_walkable_route:
        queue_anchor = facility.spec.queue_anchor
        return hypot(
            start_position[0] - queue_anchor[0],
            start_position[1] - queue_anchor[1],
        ) / walk_speed
    if use_passenger_route_provider:
        route = tuple(model.facility_walking_route(passenger, facility))
    else:
        target = model._safe_facility_queue_approach_target(passenger, facility)
        router = getattr(model, "_physical_waypoint_router", None)
        if router is None:
            router = PhysicalWaypointRouter()
            model._physical_waypoint_router = router
        route = router.route(
            model.jupedsim_walkable_area(level_id),
            start_position,
            (target,),
            level_id=level_id,
            clearance=max(
                0.02,
                min(
                    float(model.scenario.jupedsim_agent_radius_units),
                    float(model.scenario.jupedsim_target_radius_units) * 0.25,
                ),
            ),
        )
    points = (start_position, *route)
    distance = sum(
        hypot(right[0] - left[0], right[1] - left[1])
        for left, right in zip(points, points[1:])
    )
    return distance / walk_speed


def _facility_portals_are_walkable(model: Any, facility: Any) -> bool:
    entry_level = facility.spec.entry_level_id
    exit_level = facility.spec.exit_level_id
    if entry_level is None or exit_level is None:
        return False
    entry_area = model.jupedsim_walkable_area(entry_level).buffer(1e-7)
    exit_area = model.jupedsim_walkable_area(exit_level).buffer(1e-7)
    return entry_area.covers(ShapelyPoint(facility.spec.position)) and exit_area.covers(
        ShapelyPoint(facility.spec.exit_position)
    )


def _walkable_components(area: Any) -> tuple[Any, ...]:
    if area.is_empty:
        return ()
    if area.geom_type == "Polygon":
        return (area,)
    return tuple(
        geometry
        for geometry in getattr(area, "geoms", ())
        if geometry.geom_type == "Polygon" and not geometry.is_empty
    )
