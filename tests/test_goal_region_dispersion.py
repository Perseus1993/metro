from __future__ import annotations

from dataclasses import replace
from itertools import combinations
from math import hypot
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point as ShapelyPoint, Polygon

from metro_station.adapters.simulation.design import create_design
from metro_station.adapters.simulation.facilities.filters import (
    filter_facilities_for_passenger,
)
from metro_station.adapters.simulation.facilities.process import FacilityKind
from metro_station.adapters.simulation.facilities.vertical import VerticalFacilityConfig
from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.planning.plan import AgentIntent, FacilityStage
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.runtime.decision_holding import (
    DecisionHoldingCapacityError,
)
from metro_station.adapters.simulation.runtime.passenger_goal_region_router import (
    PassengerGoalRegionRouter,
)
from metro_station.adapters.simulation.runtime import evacuation_journey_rerouting
from metro_station.adapters.simulation.station.disruptions import (
    DISABLE_FACILITY,
    FacilityAvailabilityEvent,
)
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario


def _scenario() -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="hall-dispersion-test",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="unit",
        sample_hours=1,
        station_design=create_design("visual_demo_station"),
        audit_enabled=False,
        audit_print_events=False,
    )


def test_decision_regions_require_walkable_physical_waypoints() -> None:
    model = MetroStationModel(_scenario(), seed=42)
    router = PassengerGoalRegionRouter()
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)

    entry_route = router.route(model, passenger, "entry_gate_decision")
    assert entry_route
    assert entry_route[-1] != passenger.pos

    vertical_route = router.route(model, passenger, "vertical_decision")
    assert vertical_route
    assert not router.reached(passenger, vertical_route)
    assert (
        model.jupedsim_walkable_area(passenger.current_level_id)
        .buffer(1e-7)
        .covers(ShapelyPoint(vertical_route[-1]))
    )


def test_unknown_goal_region_fails_the_runtime_contract() -> None:
    model = MetroStationModel(_scenario(), seed=42)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)

    with pytest.raises(ValueError, match="unsupported region"):
        PassengerGoalRegionRouter().route(model, passenger, "misspelled_region")


def test_evacuation_selects_vertical_facility_only_after_physical_arrival() -> None:
    model = MetroStationModel(_scenario(), seed=42)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    passenger.pos = (50.0, 28.0)
    passenger.assigned_facility_id = None
    passenger.goal_runtime = model.evacuation_goal_runtime_from_position(
        passenger,
        station_interior=True,
    )
    model.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
    model.goal_coordinator.initialize(passenger)

    assert passenger.goal_runtime.state.current_node_id == "approach_vertical_decision"
    assert passenger.goal_runtime.state.commitment is None
    assert passenger.current_goal.kind == "goal_region"
    assert passenger.current_goal.label == "vertical_decision"
    assert passenger.pos != passenger.target

    passenger.pos = passenger.target
    passenger.route = []
    passenger.advance_after_movement(True)

    assert passenger.goal_runtime.state.current_node_id == "use_vertical_transfer"
    assert passenger.goal_runtime.state.commitment is not None
    assert passenger.assigned_facility_id is not None
    assert passenger.current_goal.facility_id == passenger.assigned_facility_id


@pytest.mark.parametrize(
    ("level_source", "expected_stages"),
    (
        ("concourse", ("exit_gate",)),
        ("platform", ("vertical_transfer", "exit_gate")),
    ),
)
def test_alarm_journey_is_rerooted_from_physical_level(
    level_source: str,
    expected_stages: tuple[str, ...],
) -> None:
    model = MetroStationModel(_scenario(), seed=45)
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
    if level_source == "concourse":
        gate = model.gates[0]
        passenger.current_level_id = gate.spec.exit_level_id
        passenger.pos = gate.spec.exit_position
    else:
        platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
        passenger.current_level_id = platform.level_id
        passenger.pos = platform.position

    runtime = model.evacuation_goal_runtime_from_position(
        passenger,
        station_interior=True,
    )
    actual_stages = tuple(
        node.facility_stage for node in runtime.graph.nodes if node.facility_stage
    )

    assert actual_stages == expected_stages


@pytest.mark.parametrize(
    "template_id",
    ("single_level_terminal", "two_level_island_platform", "three_level_transfer"),
)
def test_alarm_reroot_uses_walkable_components_on_nonvisual_templates(
    template_id: str,
) -> None:
    scenario = replace(
        _scenario(),
        station_name=f"reroot-{template_id}",
        station_design=create_design(template_id),
    )
    model = MetroStationModel(scenario, seed=46)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger.current_level_id = platform.level_id
    passenger.pos = platform.position

    runtime = model.evacuation_goal_runtime_from_position(
        passenger,
        station_interior=True,
    )
    vertical_nodes = [
        node for node in runtime.graph.nodes if node.facility_stage == "vertical_transfer"
    ]

    assert len(vertical_nodes) == len(passenger.evacuation_facility_path)
    assert all(
        facility_id in model.facilities_by_id for facility_id in passenger.evacuation_facility_path
    )


def test_alarm_reroot_excludes_statically_disabled_connector_when_alternative_exists() -> None:
    baseline = MetroStationModel(_scenario(), seed=47)
    baseline_passenger = baseline._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = baseline.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    baseline_passenger.current_level_id = platform.level_id
    baseline_passenger.pos = platform.position
    baseline.evacuation_goal_runtime_from_position(
        baseline_passenger,
        station_interior=True,
    )
    disabled_id = baseline_passenger.evacuation_facility_path[0]
    disabled = replace(_scenario(), disabled_facility_ids=(disabled_id,))
    model = MetroStationModel(disabled, seed=47)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger.current_level_id = platform.level_id
    passenger.pos = platform.position
    model.evacuation_goal_runtime_from_position(passenger, station_interior=True)

    assert passenger.evacuation_facility_path
    assert disabled_id not in passenger.evacuation_facility_path
    assert all(
        model.facilities_by_id[facility_id].is_open
        for facility_id in passenger.evacuation_facility_path
    )


def test_alarm_reroot_keeps_a_geodesic_path_when_all_connectors_are_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = MetroStationModel(_scenario(), seed=147)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger.current_level_id = platform.level_id
    passenger.pos = platform.position
    vertical_ids = {
        facility.facility_id
        for facility in model._facilities_for_stage(FacilityStage.VERTICAL_TRANSFER.value)
    }
    original_is_disabled = model.is_facility_disabled
    monkeypatch.setattr(
        model,
        "is_facility_disabled",
        lambda facility_id: facility_id in vertical_ids or original_is_disabled(facility_id),
    )

    model.evacuation_goal_runtime_from_position(passenger, station_interior=True)

    assert passenger.evacuation_facility_path
    assert all(facility_id in vertical_ids for facility_id in passenger.evacuation_facility_path)
    assert model.walking_cost_source_counts["physical_waypoint_geodesic"] > 0
    assert model.walking_cost_source_counts["euclidean_fallback"] == 0
    assert model.walking_cost_evaluation_count == sum(model.walking_cost_source_counts.values())


def test_dynamic_closure_refreshes_exact_evacuation_connector_path() -> None:
    baseline = MetroStationModel(_scenario(), seed=48)
    baseline_passenger = baseline._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = baseline.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    baseline_passenger.current_level_id = platform.level_id
    baseline_passenger.pos = platform.position
    baseline.evacuation_goal_runtime_from_position(
        baseline_passenger,
        station_interior=True,
    )
    disabled_id = baseline_passenger.evacuation_facility_path[0]
    disrupted = replace(
        _scenario(),
        facility_availability_events=(
            FacilityAvailabilityEvent(
                at_seconds=0,
                action=DISABLE_FACILITY,
                facility_id=disabled_id,
            ),
        ),
    )
    model = MetroStationModel(disrupted, seed=48)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger.current_level_id = platform.level_id
    passenger.pos = platform.position
    passenger.goal_runtime = model.evacuation_goal_runtime_from_position(
        passenger,
        station_interior=True,
    )
    model.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
    model.goal_coordinator.initialize(passenger)
    assert passenger.evacuation_facility_path[0] == disabled_id

    model.disruption_controller.apply_due(model)

    assert model.is_facility_disabled(disabled_id)
    assert passenger.evacuation_facility_path
    assert disabled_id not in passenger.evacuation_facility_path


def test_evacuation_connector_choice_changes_when_selected_route_becomes_slow() -> None:
    model = MetroStationModel(_scenario(), seed=49)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger.current_level_id = platform.level_id
    passenger.pos = platform.position
    model.evacuation_goal_runtime_from_position(passenger, station_interior=True)
    first_id = passenger.evacuation_facility_path[0]
    selected = model.facilities_by_id[first_id]
    original_cost = selected.routing_traversal_seconds

    if selected.spec.kind == FacilityKind.ELEVATOR.value:
        vertical = selected.spec.vertical_config or VerticalFacilityConfig()
        elevator = replace(selected._elevator_config, travel_seconds=100_000.0)
        selected.spec = replace(
            selected.spec,
            vertical_config=replace(vertical, elevator=elevator),
        )
    elif selected.spec.kind == FacilityKind.ESCALATOR.value:
        vertical = selected.spec.vertical_config or VerticalFacilityConfig()
        escalator = replace(selected._escalator_config, ride_time_seconds=100_000.0)
        selected.spec = replace(
            selected.spec,
            vertical_config=replace(vertical, escalator=escalator),
        )
    else:
        selected.spec = replace(selected.spec, travel_speed_m_s=0.0001)

    model.evacuation_goal_runtime_from_position(passenger, station_interior=True)

    assert selected.routing_traversal_seconds > original_cost * 100
    assert passenger.evacuation_facility_path[0] != first_id


def test_opposing_stair_flow_changes_route_using_actual_progress_penalty() -> None:
    model = MetroStationModel(_scenario(), seed=50)
    stairs = next(
        facility
        for facility in model.vertical_transports
        if facility.spec.kind == FacilityKind.STAIRS.value
        and facility.spec.direction in {"up", "both"}
    )
    vertical = stairs.spec.vertical_config or VerticalFacilityConfig()
    stairs_config = replace(
        stairs._stairs_config,
        bidirectional_conflict_factor=1.0,
    )
    stairs.spec = replace(
        stairs.spec,
        travel_speed_m_s=5.0,
        vertical_config=replace(vertical, stairs=stairs_config),
    )
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    passenger.current_level_id = stairs.spec.entry_level_id
    passenger.pos = stairs.spec.queue_anchor
    model.evacuation_goal_runtime_from_position(passenger, station_interior=True)
    assert passenger.evacuation_facility_path[0] == stairs.facility_id
    free_flow_seconds = stairs.routing_traversal_seconds
    sibling = model.facilities_by_id[stairs._stairs_config.sibling_facility_id]
    list.append(sibling.queue, SimpleNamespace(group_size=100))

    model.evacuation_goal_runtime_from_position(passenger, station_interior=True)

    assert stairs.routing_traversal_seconds > free_flow_seconds * 5
    assert passenger.evacuation_facility_path[0] != stairs.facility_id


def test_vertical_decision_refreshes_exact_path_with_current_queue_cost() -> None:
    model = MetroStationModel(_scenario(), seed=51)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger.current_level_id = platform.level_id
    passenger.pos = platform.position
    passenger.goal_runtime = model.evacuation_goal_runtime_from_position(
        passenger,
        station_interior=True,
    )
    model.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
    old_id = passenger.evacuation_facility_path[0]
    old_facility = model.facilities_by_id[old_id]
    blocker = SimpleNamespace(
        group_size=100,
        unique_id=-1,
        model=model,
        pos=old_facility.spec.queue_layout.slot(0),
    )
    assert old_facility.queue.join(blocker)
    model.goal_coordinator.initialize(passenger)
    if passenger.goal_runtime.state.commitment is None:
        passenger.pos = passenger.target
        passenger.route = []
        passenger.advance_after_movement(True)

    assert passenger.goal_runtime.state.commitment is not None
    assert passenger.goal_runtime.state.commitment.facility_id != old_id
    assert passenger.evacuation_facility_path[0] != old_id


def test_evacuation_connector_switch_obeys_replan_cooldown(monkeypatch) -> None:
    model = MetroStationModel(_scenario(), seed=5101)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    available = tuple(
        facility.facility_id
        for facility in model.vertical_transports
        if facility.spec.entry_level_id == passenger.current_level_id
        and facility.spec.direction in {"up", "both"}
        and facility.is_open
    )
    assert len(available) >= 2
    current_path = (available[0],)
    proposed_path = (available[1],)
    passenger.evacuation_facility_path = current_path
    passenger.decision_reconsider_after_seconds_by_region["vertical_decision"] = 30.0
    monkeypatch.setattr(
        evacuation_journey_rerouting,
        "_vertical_facility_path_and_cost_to_exit_component",
        lambda _model, _passenger: (proposed_path, 1.0),
    )
    monkeypatch.setattr(
        evacuation_journey_rerouting,
        "_evacuation_facility_path_cost_seconds",
        lambda _model, _passenger, path, *, require_open: 100.0 if path == current_path else 1.0,
    )

    assert (
        evacuation_journey_rerouting.refresh_evacuation_facility_path(
            model,
            passenger,
        )
        == current_path
    )
    model.step_index = 31
    assert (
        evacuation_journey_rerouting.refresh_evacuation_facility_path(
            model,
            passenger,
        )
        == proposed_path
    )


def test_evacuation_connector_switch_requires_minimum_cost_improvement(
    monkeypatch,
) -> None:
    model = MetroStationModel(_scenario(), seed=5102)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    available = tuple(
        facility.facility_id
        for facility in model.vertical_transports
        if facility.spec.entry_level_id == passenger.current_level_id
        and facility.spec.direction in {"up", "both"}
        and facility.is_open
    )
    assert len(available) >= 2
    current_path = (available[0],)
    proposed_path = (available[1],)
    passenger.evacuation_facility_path = current_path
    proposed_cost = [96.0]
    monkeypatch.setattr(
        evacuation_journey_rerouting,
        "_vertical_facility_path_and_cost_to_exit_component",
        lambda _model, _passenger: (proposed_path, proposed_cost[0]),
    )
    monkeypatch.setattr(
        evacuation_journey_rerouting,
        "_evacuation_facility_path_cost_seconds",
        lambda _model, _passenger, path, *, require_open: (
            100.0 if path == current_path else proposed_cost[0]
        ),
    )

    assert model.scenario.facility_replan_minimum_improvement_seconds == 5.0
    assert (
        evacuation_journey_rerouting.refresh_evacuation_facility_path(
            model,
            passenger,
        )
        == current_path
    )

    proposed_cost[0] = 94.0
    assert (
        evacuation_journey_rerouting.refresh_evacuation_facility_path(
            model,
            passenger,
        )
        == proposed_path
    )


def test_evacuation_path_viability_rejects_wrong_direction_connector() -> None:
    model = MetroStationModel(_scenario(), seed=5103)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    wrong_direction = next(
        facility for facility in model.vertical_transports if facility.spec.direction == "down"
    )
    binding = model.facility_portal_binding(wrong_direction.facility_id)
    passenger.current_level_id = binding.entry_level_id
    passenger.pos = binding.entry_point

    assert not evacuation_journey_rerouting._evacuation_facility_path_is_viable(
        model,
        passenger,
        (wrong_direction.facility_id,),
    )


def test_evacuation_path_excludes_an_elevator_that_cannot_serve_the_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = MetroStationModel(
        replace(_scenario(), elevator_cabin_capacity_persons=2),
        seed=5104,
    )
    elevator = next(
        facility
        for facility in model.vertical_transports
        if facility.spec.kind == "elevator" and facility.spec.direction == "up"
    )
    binding = model.facility_portal_binding(elevator.facility_id)
    passenger = PassengerAgent(
        model,
        group_size=3,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
        initial_position=binding.entry_point,
        initial_level_id=binding.entry_level_id,
    )
    model.passengers.append(passenger)
    monkeypatch.setattr(
        evacuation_journey_rerouting,
        "_walking_seconds_to_facility",
        lambda *_args, **_kwargs: 0.0,
    )
    monkeypatch.setattr(
        evacuation_journey_rerouting,
        "_vertical_service_cost_seconds",
        lambda _model, facility: (
            1.0 if facility.spec.kind == "elevator" else 100.0
        ),
    )

    path = evacuation_journey_rerouting._vertical_facility_path_to_exit_component(
        model,
        passenger,
    )

    assert path
    assert all(
        model.facilities_by_id[facility_id].spec.kind != "elevator"
        for facility_id in path
    )
    passenger.evacuation_facility_path = path
    candidates = filter_facilities_for_passenger(
        passenger,
        FacilityStage.VERTICAL_TRANSFER.value,
        model._facilities_for_stage(FacilityStage.VERTICAL_TRANSFER.value),
    )
    assert candidates
    assert candidates[0].facility_id == path[0]


def test_vertical_decision_region_is_derived_from_all_reachable_connectors() -> None:
    model = MetroStationModel(_scenario(), seed=43)
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
    router = PassengerGoalRegionRouter()
    passenger.pos = (50.0, 10.0)

    route = router.route(model, passenger, "vertical_decision")
    assert route
    assert not router.reached(passenger, route)
    target = route[-1]
    connector_entries = {
        facility.spec.position
        for facility in model.vertical_transports
        if facility.spec.direction in {"down", "both"}
        and facility.spec.entry_level_id == passenger.current_level_id
    }
    assert len(connector_entries) > 1
    assert target not in connector_entries


def test_passenger_already_inside_physical_decision_region_does_not_seek_center() -> None:
    model = MetroStationModel(_scenario(), seed=52)
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    router = PassengerGoalRegionRouter()
    candidates = filter_facilities_for_passenger(
        passenger,
        FacilityStage.VERTICAL_TRANSFER.value,
        model._facilities_for_stage(FacilityStage.VERTICAL_TRANSFER.value),
    )
    candidates = [
        facility
        for facility in candidates
        if facility.spec.entry_level_id == passenger.current_level_id
    ]
    approaches = tuple(
        router._representative_facility_approach(model, passenger, facility)
        for facility in candidates
    )
    area = model.jupedsim_walkable_area(passenger.current_level_id)
    decision_region = router._decision_region_domain(model, approaches, area)
    inside = decision_region.representative_point()
    passenger.pos = (float(inside.x), float(inside.y))

    route = router.route(model, passenger, "vertical_decision")

    assert route == (passenger.pos,)
    assert router.reached(passenger, route)


def test_decision_region_does_not_bridge_a_non_walkable_wall() -> None:
    model = MetroStationModel(_scenario(), seed=57)
    router = PassengerGoalRegionRouter()
    walkable_with_wall = Polygon(
        ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)),
        holes=(((1.5, 0.5), (2.5, 0.5), (2.5, 3.5), (1.5, 3.5)),),
    )

    assert not router._has_local_portal_access(
        model,
        (1.2, 2.0),
        ((2.8, 2.0),),
        walkable_with_wall,
    )


def test_decision_region_is_bounded_to_local_portal_catchments() -> None:
    model = MetroStationModel(_scenario(), seed=58)
    router = PassengerGoalRegionRouter()
    area = Polygon(((-100.0, -10.0), (100.0, -10.0), (100.0, 10.0), (-100.0, 10.0)))
    approaches = ((-20.0, 0.0), (20.0, 0.0))
    decision_region = router._decision_region_domain(model, approaches, area)

    assert not decision_region.covers(ShapelyPoint(0.0, 0.0))
    assert decision_region.covers(ShapelyPoint(approaches[0]))
    assert decision_region.covers(ShapelyPoint(approaches[1]))


def test_decision_observation_excludes_distant_portal_banks() -> None:
    model = MetroStationModel(_scenario(), seed=59)
    passenger = model._spawn_passenger(AgentIntent.EXIT_STATION)
    router = PassengerGoalRegionRouter()
    candidates = [
        facility
        for facility in model.vertical_transports
        if facility.spec.entry_level_id == passenger.current_level_id
        and facility.spec.direction in {"up", "both"}
    ]
    assert len(candidates) > 1
    near = candidates[0]
    passenger.pos = router._representative_facility_approach(model, passenger, near)

    observed = router.local_decision_facilities(
        model,
        passenger,
        "vertical_decision",
        candidates,
    )

    assert near in observed
    assert observed
    assert all(
        router._has_local_portal_access(
            model,
            passenger.pos,
            router._facility_decision_points(model, passenger, facility),
            model.jupedsim_walkable_area(passenger.current_level_id),
        )
        for facility in observed
    )
    assert len(observed) < len(candidates)


def test_disabled_local_decision_context_reroutes_to_live_catchment() -> None:
    model = MetroStationModel(_scenario(), seed=60)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger = model._spawn_passenger(
        AgentIntent.EXIT_STATION,
        initial_position=(50.0, 28.0),
        initial_level_id=platform.level_id,
    )
    assert passenger.goal_runtime.state.commitment is None
    recorded = set(passenger.decision_facility_ids_by_region.get("vertical_decision", ()))
    assert recorded
    model.disruption_controller.dynamic_disabled_ids.update(recorded)
    assert model.goal_coordinator.executor.region_router.decision_context_needs_reroute(
        model,
        passenger,
        "vertical_decision",
        model._facilities_for_stage(FacilityStage.VERTICAL_TRANSFER.value),
    )
    arrival = passenger.route[-1] if passenger.route else passenger.target
    passenger.target = arrival
    passenger.route = []
    passenger._sync_goal_target()
    assert passenger.goal_command_region_id == "vertical_decision"
    model.step_index += 1
    passenger.pos = arrival
    passenger.advance_after_movement(True)

    replacement = set(passenger.decision_facility_ids_by_region.get("vertical_decision", ()))
    assert replacement
    assert passenger.goal_runtime.state.commitment is None
    assert passenger.current_goal.kind == "goal_region"
    assert passenger.current_goal.label == "vertical_decision"
    assert replacement.isdisjoint(recorded)


def test_cost_change_en_route_retargets_decision_before_remote_selection() -> None:
    model = MetroStationModel(_scenario(), seed=61)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger = model._spawn_passenger(
        AgentIntent.EVACUATE_STATION,
        initial_position=(50.0, 28.0),
        initial_level_id=platform.level_id,
    )
    original_context = set(passenger.decision_facility_ids_by_region.get("vertical_decision", ()))
    assert original_context
    original_path_facility_id = passenger.evacuation_facility_path[0]
    router = model.goal_coordinator.executor.region_router
    original_target = passenger.decision_target_by_region["vertical_decision"]
    candidates = model._facilities_for_stage(FacilityStage.VERTICAL_TRANSFER.value)
    local = router._local_facilities_at_position(
        model,
        passenger,
        candidates,
        original_target,
        model.jupedsim_walkable_area(passenger.current_level_id),
    )
    assert local
    for facility in local:
        vertical = facility.spec.vertical_config or VerticalFacilityConfig()
        if facility.spec.kind == FacilityKind.ELEVATOR.value:
            facility.spec = replace(
                facility.spec,
                vertical_config=replace(
                    vertical,
                    elevator=replace(
                        facility._elevator_config,
                        travel_seconds=100_000.0,
                    ),
                ),
            )
        elif facility.spec.kind == FacilityKind.ESCALATOR.value:
            facility.spec = replace(
                facility.spec,
                vertical_config=replace(
                    vertical,
                    escalator=replace(
                        facility._escalator_config,
                        ride_time_seconds=100_000.0,
                    ),
                ),
            )
        else:
            facility.spec = replace(facility.spec, travel_speed_m_s=0.0001)
        list.append(
            facility.queue,
            SimpleNamespace(
                group_size=100,
                unique_id=-100 - len(facility.queue),
                model=model,
                pos=facility.spec.queue_layout.slot(0),
            ),
        )
    model.goal_coordinator.poll(passenger)

    replacement = set(passenger.decision_facility_ids_by_region["vertical_decision"])
    assert passenger.evacuation_facility_path[0] != original_path_facility_id, (
        original_path_facility_id,
        passenger.evacuation_facility_path[0],
        tuple((facility.facility_id, facility.queue_persons) for facility in local),
    )
    assert passenger.evacuation_facility_path[0] in replacement
    assert passenger.decision_target_by_region["vertical_decision"] != original_target
    assert passenger.goal_runtime.state.commitment is None
    assert passenger.current_goal.kind == "goal_region"
    assert passenger.current_goal.label == "vertical_decision"


def test_non_evacuation_cost_change_retargets_tactical_catchment() -> None:
    model = MetroStationModel(_scenario(), seed=161)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger = model._spawn_passenger(
        AgentIntent.EXIT_STATION,
        initial_position=(50.0, 28.0),
        initial_level_id=platform.level_id,
    )
    router = model.goal_coordinator.executor.region_router
    candidates = model._facilities_for_stage(FacilityStage.VERTICAL_TRANSFER.value)
    original_target = passenger.decision_target_by_region["vertical_decision"]
    original_context = set(passenger.decision_facility_ids_by_region["vertical_decision"])
    local = router._local_facilities_at_position(
        model,
        passenger,
        candidates,
        original_target,
        model.jupedsim_walkable_area(passenger.current_level_id),
    )
    assert local
    for facility in local:
        list.append(
            facility.queue,
            SimpleNamespace(
                group_size=100,
                unique_id=-200 - len(facility.queue),
                model=model,
                pos=facility.spec.queue_layout.slot(0),
            ),
        )

    assert router.decision_context_needs_reroute(
        model,
        passenger,
        "vertical_decision",
        candidates,
    )
    model.goal_coordinator.poll(passenger)

    replacement = set(passenger.decision_facility_ids_by_region["vertical_decision"])
    assert replacement != original_context
    assert (
        passenger.decision_preferred_facility_id_by_region["vertical_decision"]
        not in original_context
    )
    assert passenger.decision_target_by_region["vertical_decision"] != original_target
    assert passenger.goal_runtime.state.commitment is None


def test_boarding_unavailable_retains_owned_platform_waiting_target() -> None:
    model = MetroStationModel(_scenario(), seed=53)
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
    platform = model.platforms[0]
    passenger.assigned_platform_id = platform.platform_id
    passenger.assigned_line_id = platform.line_id
    passenger.assigned_direction = platform.direction
    passenger.current_level_id = model.boarding_doors_for_platform(platform)[0].spec.entry_level_id
    passenger.pos = model.layout_graph.platform_waiting_position(0)
    assert model.join_platform(passenger)
    router = PassengerGoalRegionRouter()

    route = router.route(model, passenger, "boarding_decision")

    reservation = model._platform_waiting_reservations[int(passenger.unique_id)]
    assert route == (reservation.point,)
    assert passenger in platform.waiting


@pytest.mark.parametrize(
    "template_id",
    ("visual_demo_station", "two_level_island_platform"),
)
def test_saturated_decision_uses_owned_body_clear_holding_slots(
    template_id: str,
) -> None:
    scenario = replace(
        _scenario(),
        station_name=f"decision-holding-{template_id}",
        station_design=create_design(template_id),
    )
    model = MetroStationModel(scenario, seed=7303)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    level_id = platform.level_id
    verticals = tuple(
        facility
        for facility in model.vertical_transports
        if model.facility_portal_binding(facility.facility_id).entry_level_id == level_id
    )
    assert verticals

    reservation_owners: list[PassengerAgent] = []
    for facility in verticals:
        for _slot_index in model._facility_approach_slot_indices(facility):
            owner = PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.EXIT_STATION,
                initial_position=platform.position,
                initial_level_id=level_id,
            )
            model._reserve_facility_approach_slot(owner, facility)
            reservation_owners.append(owner)

    passengers = tuple(
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EXIT_STATION,
            initial_position=platform.position,
            initial_level_id=level_id,
        )
        for _ in range(2)
    )
    router = PassengerGoalRegionRouter()
    targets = tuple(
        router.route(model, passenger, "vertical_decision")[-1] for passenger in passengers
    )
    minimum_distance = (
        model.scenario.jupedsim_agent_radius_units * model.scenario.jupedsim_clearance_multiplier
    )
    protected_arrival_distance = minimum_distance + model.scenario.jupedsim_target_radius_units
    protected = tuple(
        point
        for facility in verticals
        for point in model.facility_portal_binding(facility.facility_id).approach_slots
    )

    assert targets[0] != targets[1]
    assert router._distance(targets[0], targets[1]) >= minimum_distance - 1e-9
    assert all(
        router._distance(target, point) >= protected_arrival_distance - 1e-9
        for target in targets
        for point in protected
    )
    assert all(
        passenger.decision_holding_target_by_region["vertical_decision"] == target
        for passenger, target in zip(passengers, targets, strict=True)
    )

    for owner in reservation_owners:
        model._clear_all_facility_targeting_reservations(owner)
    rerouted = router.route(model, passengers[0], "vertical_decision")

    assert rerouted
    assert "vertical_decision" not in passengers[0].decision_holding_target_by_region
    assert not any(
        owner_id == int(passengers[0].unique_id)
        for owner_id, _region in model._decision_holding_reservations
    )


def test_holding_context_reconsiders_newly_reopened_facility_bank() -> None:
    model = MetroStationModel(_scenario(), seed=73031)
    gates = tuple(sorted(model.gates, key=lambda item: item.facility_id))
    assert len(gates) > 1
    escape_gate = gates[-1]
    reopened_gates = gates[:-1]
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
    model._clear_all_decision_holding_reservations(passenger)
    model._clear_all_facility_targeting_reservations(passenger)
    model.disruption_controller.dynamic_disabled_ids.update(
        gate.facility_id for gate in reopened_gates
    )
    reservation_owner = SimpleNamespace(
        unique_id=-73031,
        group_size=1,
        facility_approach_slots_by_stage={},
        facility_approach_facility_ids_by_stage={},
    )
    for _slot_index in model._facility_approach_slot_indices(escape_gate):
        owner = SimpleNamespace(
            unique_id=reservation_owner.unique_id,
            group_size=1,
            facility_approach_slots_by_stage={},
            facility_approach_facility_ids_by_stage={},
        )
        model._reserve_facility_approach_slot(owner, escape_gate)
        reservation_owner.unique_id -= 1

    router = model.goal_coordinator.executor.region_router
    passenger.set_route(
        router.route(model, passenger, "entry_gate_decision"),
        goal_kind="goal_region",
        goal_label="entry_gate_decision",
    )
    assert "entry_gate_decision" in passenger.decision_holding_target_by_region
    assert set(passenger.decision_facility_ids_by_region["entry_gate_decision"]) == {
        escape_gate.facility_id
    }

    model.disruption_controller.dynamic_disabled_ids.difference_update(
        gate.facility_id for gate in reopened_gates
    )

    assert router.decision_context_needs_reroute(
        model,
        passenger,
        "entry_gate_decision",
        model._facilities_for_stage(FacilityStage.ENTRY_GATE.value),
    )
    model.goal_coordinator.poll(passenger)

    preferred = passenger.decision_preferred_facility_id_by_region[
        "entry_gate_decision"
    ]
    assert preferred in {gate.facility_id for gate in reopened_gates}
    assert "entry_gate_decision" not in passenger.decision_holding_target_by_region


def test_decision_and_platform_standing_resources_share_body_clear_policy() -> None:
    model = MetroStationModel(_scenario(), seed=7304)
    platform = model.platforms[0]
    platform_level_id = model.boarding_doors_for_platform(platform)[0].spec.entry_level_id
    assert platform_level_id is not None
    platform_node = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    platform_waiters: list[PassengerAgent] = []
    for _ in range(12):
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        # ENTER_AND_BOARD is initialized on an entrance level.  Move this
        # synthetic standing-resource actor only after its real entry command
        # has compiled; constructing that intent directly on a platform would
        # be an invalid journey state now that entry decisions are portal-local.
        model._clear_all_decision_holding_reservations(passenger)
        model._clear_all_facility_targeting_reservations(passenger)
        passenger.pos = platform_node.position
        passenger.current_level_id = platform_level_id
        passenger.assigned_platform_id = platform.platform_id
        passenger.assigned_line_id = platform.line_id
        passenger.assigned_direction = platform.direction
        model.passengers.append(passenger)
        assert model.join_platform(passenger)
        platform_waiters.append(passenger)
    platform._layout_waiting()

    verticals = tuple(
        facility
        for facility in model.vertical_transports
        if model.facility_portal_binding(facility.facility_id).entry_level_id == platform_level_id
    )
    anchors = tuple(
        point
        for facility in verticals
        for point in model.facility_portal_binding(facility.facility_id).approach_slots
    )
    holding_region = next(
        region
        for region in model.layout_graph.decision_holding_regions
        if region.region_id == "vertical_decision"
        and region.level_id == platform_level_id
    )
    # Exercise the compiler's constructive capacity, not an arbitrary crowd
    # size.  These synthetic owners deliberately do not masquerade as live
    # passengers co-located at the platform centroid; runtime placement only
    # needs their stable ownership identity and current level.
    holding_passengers = tuple(
        SimpleNamespace(
            unique_id=-(730_400 + index),
            current_level_id=platform_level_id,
            decision_holding_target_by_region={},
        )
        for index in range(len(holding_region.slots))
    )
    holding_points = tuple(
        model._reserve_decision_holding_slot(
            passenger,
            "vertical_decision",
            anchors,
        )
        for passenger in holding_passengers
    )
    platform._layout_waiting()
    platform_points = tuple(
        model._platform_waiting_reservations[int(passenger.unique_id)].point
        for passenger in platform_waiters
    )
    minimum_distance = (
        model.scenario.jupedsim_agent_radius_units * model.scenario.jupedsim_clearance_multiplier
    )
    protected_arrival_distance = minimum_distance + model.scenario.jupedsim_target_radius_units

    assert len(set(holding_points)) == len(holding_points)
    assert all(
        hypot(left[0] - right[0], left[1] - right[1]) >= minimum_distance - 1e-9
        for left, right in combinations(holding_points, 2)
    )
    assert all(
        hypot(holding[0] - waiting[0], holding[1] - waiting[1]) >= minimum_distance - 1e-9
        for holding in holding_points
        for waiting in platform_points
    )
    assert all(
        hypot(holding[0] - protected[0], holding[1] - protected[1])
        >= protected_arrival_distance - 1e-9
        for holding in holding_points
        for protected in model._decision_holding_protected_points(platform_level_id)
    )
    overflow = SimpleNamespace(
        unique_id=-730_499,
        current_level_id=platform_level_id,
        decision_holding_target_by_region={},
    )
    with pytest.raises(DecisionHoldingCapacityError):
        model._reserve_decision_holding_slot(
            overflow,
            "vertical_decision",
            anchors,
        )


def test_decision_holding_is_finite_compiler_output_outside_main_flow_edges() -> None:
    model = MetroStationModel(_scenario(), seed=7305)
    minimum_distance = (
        model.scenario.jupedsim_agent_radius_units * model.scenario.jupedsim_clearance_multiplier
    )
    graph = model.layout_graph.station_graph

    assert model.layout_graph.decision_holding_regions
    for region in model.layout_graph.decision_holding_regions:
        assert region.slots
        assert all(
            hypot(left[0] - right[0], left[1] - right[1])
            >= model.scenario.personal_space_units - 1e-8
            for index, left in enumerate(region.slots)
            for right in region.slots[index + 1 :]
        )
        assert all(region.domain.buffer(1e-8).covers(ShapelyPoint(point)) for point in region.slots)
        assert (
            max(
                min(hypot(point[0] - anchor[0], point[1] - anchor[1]) for anchor in region.anchors)
                for point in region.slots
            )
            <= 6.0 + 1e-8
        )
        flow_lines = tuple(
            LineString((graph.nodes[edge.from_node].position, graph.nodes[edge.to_node].position))
            for edge in graph.edges
            if edge.kind == "walk"
            and not edge.level_change
            and graph.nodes[edge.from_node].level_id == region.level_id
            and graph.nodes[edge.to_node].level_id == region.level_id
            and graph.nodes[edge.from_node].position != graph.nodes[edge.to_node].position
        )
        assert all(
            line.distance(ShapelyPoint(point)) >= minimum_distance - 1e-8
            for point in region.slots
            for line in flow_lines
        )
        ingress_lines = []
        for binding in model.layout_graph.facility_portal_bindings:
            if binding.entry_level_id != region.level_id or not binding.approach_slots:
                continue
            tail = max(
                binding.approach_slots,
                key=lambda point: hypot(
                    point[0] - binding.entry_point[0],
                    point[1] - binding.entry_point[1],
                ),
            )
            dx = tail[0] - binding.entry_point[0]
            dy = tail[1] - binding.entry_point[1]
            length = hypot(dx, dy)
            if length <= 1e-6:
                continue
            upstream = (tail[0] + dx / length * 6.0, tail[1] + dy / length * 6.0)
            ingress_lines.append(LineString((binding.entry_point, tail)))
            ingress_lines.append(LineString((tail, upstream)))
        assert all(
            line.distance(ShapelyPoint(point)) >= minimum_distance - 1e-8
            for point in region.slots
            for line in ingress_lines
        )


def test_generated_entrance_spawns_are_native_safe_without_first_tick_projection() -> None:
    model = MetroStationModel(
        replace(
            _scenario(),
            station_design=create_design("three_level_transfer"),
        ),
        seed=99,
    )
    entrance = model.layout_graph.station_graph.nodes_matching(kind="entrance")[0]
    probe = object.__new__(PassengerAgent)
    probe.model = model
    clearance = max(
        0.02,
        model.scenario.jupedsim_agent_radius_units * 1.05,
    )
    native_safe_core = model.jupedsim_walkable_area(entrance.level_id).buffer(-clearance)

    samples = tuple(probe._sample_graph_node_position(entrance) for _ in range(128))

    assert all(native_safe_core.buffer(1e-9).covers(ShapelyPoint(point)) for point in samples)


def test_decision_holding_capacity_exhaustion_is_typed() -> None:
    model = MetroStationModel(_scenario(), seed=7306)
    platform_level_id = model.layout_graph.station_graph.nodes_matching(kind="platform")[0].level_id
    region = next(
        item
        for item in model.layout_graph.decision_holding_regions
        if item.region_id == "vertical_decision" and item.level_id == platform_level_id
    )
    object.__setattr__(
        model.layout_graph,
        "decision_holding_regions",
        (replace(region, slots=(region.slots[0],)),),
    )
    passengers = tuple(
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EXIT_STATION,
            initial_position=region.anchors[0],
            initial_level_id=region.level_id,
        )
        for _ in range(2)
    )

    model._reserve_decision_holding_slot(
        passengers[0],
        region.region_id,
        region.anchors,
    )
    with pytest.raises(DecisionHoldingCapacityError):
        model._reserve_decision_holding_slot(
            passengers[1],
            region.region_id,
            region.anchors,
        )


def test_closed_entry_gates_and_saturated_holding_reject_second_published_body() -> None:
    baseline = MetroStationModel(_scenario(), seed=73061)
    entry_gate_ids = tuple(gate.facility_id for gate in baseline.gates)
    model = MetroStationModel(
        replace(_scenario(), disabled_facility_ids=entry_gate_ids),
        seed=73061,
    )
    entrance_level_id = model.layout_graph.station_graph.nodes_matching(kind="entrance")[0].level_id
    region = next(
        item
        for item in model.layout_graph.decision_holding_regions
        if item.region_id == "entry_gate_decision" and item.level_id == entrance_level_id
    )
    object.__setattr__(
        model.layout_graph,
        "decision_holding_regions",
        tuple(
            replace(item, slots=(region.slots[0],)) if item is region else item
            for item in model.layout_graph.decision_holding_regions
        ),
    )
    first = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
        initial_position=region.anchors[0],
        initial_level_id=region.level_id,
    )
    with pytest.raises(DecisionHoldingCapacityError):
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
            initial_position=(region.anchors[0][0] - 0.5, region.anchors[0][1]),
            initial_level_id=region.level_id,
        )

    assert first.decision_holding_target_by_region == {
        "entry_gate_decision": region.slots[0]
    }
    assert all(not gate.is_open for gate in model.gates)


def test_decision_holding_revalidates_reservation_after_geometry_revision(
    monkeypatch,
) -> None:
    model = MetroStationModel(_scenario(), seed=7307)
    platform_level_id = model.layout_graph.station_graph.nodes_matching(kind="platform")[0].level_id
    region = next(
        item
        for item in model.layout_graph.decision_holding_regions
        if item.region_id == "vertical_decision" and item.level_id == platform_level_id
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
        initial_position=region.anchors[0],
        initial_level_id=region.level_id,
    )
    first = model._reserve_decision_holding_slot(
        passenger,
        region.region_id,
        region.anchors,
    )
    original_area = model.jupedsim_walkable_area(region.level_id)
    monkeypatch.setattr(
        model,
        "jupedsim_walkable_area",
        lambda _level_id: original_area.difference(ShapelyPoint(first).buffer(0.5)),
    )
    model._walkable_area_revision += 1

    second = model._reserve_decision_holding_slot(
        passenger,
        region.region_id,
        region.anchors,
    )

    assert second != first
    reservation = model._decision_holding_reservations[(int(passenger.unique_id), region.region_id)]
    assert reservation.walkable_area_revision == model._walkable_area_revision


def test_decision_holding_release_waits_for_physical_body_clearance() -> None:
    model = MetroStationModel(_scenario(), seed=7308)
    region = next(
        item
        for item in model.layout_graph.decision_holding_regions
        if item.region_id == "entry_gate_decision"
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
        initial_position=region.anchors[0],
        initial_level_id=region.level_id,
    )
    target = model._reserve_decision_holding_slot(
        passenger,
        region.region_id,
        region.anchors,
    )
    passenger.pos = target
    owner_key = (int(passenger.unique_id), region.region_id)

    model._clear_vacated_decision_holding_reservations(passenger, schedule=True)

    assert owner_key in model._decision_holding_reservations
    passenger.pos = (target[0] + 10.0, target[1])
    model._clear_vacated_decision_holding_reservations(passenger)
    assert owner_key not in model._decision_holding_reservations


def test_disabled_facility_portals_do_not_expand_decision_region() -> None:
    model = MetroStationModel(_scenario(), seed=54)
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
    router = PassengerGoalRegionRouter()
    facilities = filter_facilities_for_passenger(
        passenger,
        FacilityStage.VERTICAL_TRANSFER.value,
        model._facilities_for_stage(FacilityStage.VERTICAL_TRANSFER.value),
    )
    facilities = [
        facility
        for facility in facilities
        if facility.spec.entry_level_id == passenger.current_level_id
    ]
    open_facility = facilities[0]
    open_approach = router._representative_facility_approach(
        model,
        passenger,
        open_facility,
    )
    disabled_facility = max(
        facilities[1:],
        key=lambda facility: router._distance(
            open_approach,
            router._representative_facility_approach(model, passenger, facility),
        ),
    )
    model.disruption_controller.dynamic_disabled_ids.update(
        facility.facility_id for facility in facilities if facility is not open_facility
    )
    passenger.pos = router._representative_facility_approach(
        model,
        passenger,
        disabled_facility,
    )

    route = router.route(model, passenger, "vertical_decision")

    assert route[-1] != passenger.pos
    assert not router.reached(passenger, route)


def test_completed_facility_identity_precedes_nearest_exit_fallback() -> None:
    model = MetroStationModel(_scenario(), seed=55)
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
    first, second = model.gates[:2]
    first.spec = replace(first.spec, exit_position=(0.0, 0.0))
    second.spec = replace(second.spec, exit_position=(5.0, 0.0))
    passenger.current_level_id = first.spec.exit_level_id
    passenger.pos = (3.0, 0.0)
    passenger.assigned_facility_id = first.facility_id
    passenger.last_completed_facility_id = first.facility_id
    passenger.last_completed_facility_position = passenger.pos
    passenger.last_completed_facility_event_id = "accepted-service-completion"
    passenger.last_completed_facility_level_id = passenger.current_level_id
    router = PassengerGoalRegionRouter()

    target = router._membership_region_target(model, passenger, "paid_hall")

    assert target == passenger.pos


def test_rejected_service_completion_cannot_create_membership_evidence() -> None:
    model = MetroStationModel(_scenario(), seed=56)
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
    gate = model.gates[0]

    model.goal_coordinator.service_completed(
        passenger,
        gate.facility_id,
        float(model.current_time_seconds),
    )

    assert passenger.last_completed_facility_id is None
    assert passenger.last_completed_facility_event_id is None
    passenger.assigned_facility_id = gate.facility_id
    passenger.current_level_id = gate.spec.exit_level_id
    passenger.pos = model.layout_graph.station_graph.nodes_matching(kind="entrance")[0].position
    route = PassengerGoalRegionRouter().route(model, passenger, "paid_hall")
    assert not PassengerGoalRegionRouter().reached(passenger, route)


def test_membership_region_requires_coverage_by_completed_facility_exit() -> None:
    model = MetroStationModel(_scenario(), seed=44)
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
    router = PassengerGoalRegionRouter()
    gate = model.gates[0]
    passenger.assigned_facility_id = gate.facility_id
    passenger.current_level_id = gate.spec.exit_level_id
    passenger.pos = gate.spec.exit_position

    covered_route = router.route(model, passenger, "paid_hall")
    assert router.reached(passenger, covered_route)

    passenger.pos = model.layout_graph.station_graph.nodes_matching(kind="entrance")[0].position
    uncovered_route = router.route(model, passenger, "paid_hall")
    assert uncovered_route
    assert not router.reached(passenger, uncovered_route)
