from __future__ import annotations

from dataclasses import replace

from shapely.geometry import Point

from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.movement.backend import MovementBackend, MovementResult
from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.application.control_plans import (
    ACCESS_CLOSURE,
    CLOSE,
    CLOSURE_ZONE,
    DEPLOY,
    ESCALATOR_DIRECTION,
    ISOLATION_BARRIER,
    ONE_WAY_CHANNEL,
    OPEN,
    REMOVE,
    RESTORE_DIRECTION,
    SET_DIRECTION,
    STAFF_GUIDANCE,
    START_GUIDANCE,
    STOP_GUIDANCE,
    WATER_BARRIER,
    ControlEvent,
    ControlMeasure,
    ControlPlan,
)


LANE_1 = "entry_gate:gate_bank_a:lane_1"
WATER_CENTER = Point(51.0, 28.75)


class TrackingMovementBackend(MovementBackend):
    def __init__(self) -> None:
        self.geometry_refreshes = 0
        self.removed_passenger_ids: list[int] = []

    def move(self, passenger) -> MovementResult:
        return MovementResult(passenger.unique_id, passenger.pos, reached=False)

    def on_walkable_geometry_changed(self, model: object) -> None:
        self.geometry_refreshes += 1

    def remove_passenger(self, passenger) -> None:
        self.removed_passenger_ids.append(int(passenger.unique_id))


def _plan() -> ControlPlan:
    return ControlPlan(
        plan_id="timeline_01",
        name="R0 timeline",
        measures=(
            ControlMeasure(
                "water_a",
                WATER_BARRIER,
                "Water barrier A",
                level_id="l1_terminal",
                parameters={
                    "geometry": {
                        "shape": "rect",
                        "x_m": 50.0,
                        "y_m": 28.0,
                        "width_m": 2.0,
                        "height_m": 1.5,
                    }
                },
            ),
            ControlMeasure("close_lane", ACCESS_CLOSURE, "Close lane", target_id=LANE_1),
        ),
        events=(
            ControlEvent("deploy_water", "water_a", 0, DEPLOY),
            ControlEvent("close_lane_event", "close_lane", 0, CLOSE),
            ControlEvent("remove_water", "water_a", 10, REMOVE),
            ControlEvent("open_lane_event", "close_lane", 10, OPEN),
        ),
    )


def _scenario(plan: ControlPlan) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="control-test",
        hour=18,
        minutes=2,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="control-test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        movement_backend_name="jupedsim",
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
        control_plan=plan,
    )


def test_timeline_changes_walkable_geometry_facility_state_and_frame_evidence() -> None:
    backend = TrackingMovementBackend()
    model = MetroStationModel(_scenario(_plan()), movement_backend=backend)
    lane = model.facilities_by_id[LANE_1]
    assert model.jupedsim_walkable_area("l1_terminal").covers(WATER_CENTER)

    model.step()

    assert not model.jupedsim_walkable_area("l1_terminal").covers(WATER_CENTER)
    assert lane.is_forced_disabled
    assert backend.geometry_refreshes == 1
    assert {event["event_id"] for event in model.frames[-1]["control_events"]} == {
        "deploy_water",
        "close_lane_event",
    }
    assert {item["measure_id"] for item in model.frames[-1]["active_controls"]} == {
        "water_a",
        "close_lane",
    }

    model.step()
    model.step()

    assert model.jupedsim_walkable_area("l1_terminal").covers(WATER_CENTER)
    assert not lane.is_forced_disabled
    assert backend.geometry_refreshes == 2
    assert {event["event_id"] for event in model.frames[-1]["control_events"]} == {
        "remove_water",
        "open_lane_event",
    }
    assert model.frames[-1]["active_controls"] == []


def test_deployment_is_rejected_when_a_passenger_occupies_the_barrier_geometry() -> None:
    backend = TrackingMovementBackend()
    plan = replace(_plan(), events=(ControlEvent("deploy_water", "water_a", 0, DEPLOY),))
    model = MetroStationModel(_scenario(plan), movement_backend=backend)
    passenger = model._spawn_passenger(AgentIntent.EXIT_STATION)
    passenger.current_level_id = "l1_terminal"
    passenger.pos = (WATER_CENTER.x, WATER_CENTER.y)

    model.step()

    event = model.control_timeline_controller.applied_events[0]
    assert event.status == "rejected"
    assert event.details["reason"] == "passenger_occupies_deployment_geometry"
    assert model.jupedsim_walkable_area("l1_terminal").covers(WATER_CENTER)
    assert backend.geometry_refreshes == 0


def _geometry_measure(measure_id: str, kind: str) -> ControlMeasure:
    return ControlMeasure(
        measure_id,
        kind,
        measure_id,
        level_id="l1_terminal",
        parameters={
            "geometry": {
                "shape": "rect",
                "x_m": 50.0,
                "y_m": 28.0,
                "width_m": 2.0,
                "height_m": 1.5,
                "rotation_deg": 0.0,
            }
        },
    )


def _single_measure_plan(
    measure: ControlMeasure,
    start_action: str,
    end_action: str,
    *,
    parameters: dict | None = None,
) -> ControlPlan:
    return ControlPlan(
        plan_id=f"plan_{measure.measure_id}",
        name=measure.label,
        measures=(measure,),
        events=(
            ControlEvent(
                f"start_{measure.measure_id}",
                measure.measure_id,
                0,
                start_action,
                parameters=parameters or {},
            ),
            ControlEvent(f"end_{measure.measure_id}", measure.measure_id, 10, end_action),
        ),
    )


def test_isolation_barrier_and_closure_zone_share_blocking_semantics() -> None:
    for kind in (ISOLATION_BARRIER, CLOSURE_ZONE):
        backend = TrackingMovementBackend()
        measure = _geometry_measure(kind, kind)
        model = MetroStationModel(
            _scenario(_single_measure_plan(measure, DEPLOY, REMOVE)),
            movement_backend=backend,
        )

        model.step()
        assert not model.jupedsim_walkable_area("l1_terminal").covers(WATER_CENTER)

        model.step()
        model.step()
        assert model.jupedsim_walkable_area("l1_terminal").covers(WATER_CENTER)
        assert backend.geometry_refreshes == 2


def test_one_way_channel_rejects_opposing_movement_and_restores() -> None:
    backend = TrackingMovementBackend()
    measure = _geometry_measure("one_way", ONE_WAY_CHANNEL)
    plan = _single_measure_plan(
        measure,
        SET_DIRECTION,
        RESTORE_DIRECTION,
        parameters={"direction": "forward"},
    )
    model = MetroStationModel(_scenario(plan), movement_backend=backend)
    model.step()
    passenger = model._spawn_passenger(AgentIntent.EXIT_STATION)
    passenger.current_level_id = "l1_terminal"
    passenger.pos = (51.0, 28.75)

    blocked = model.control_timeline_controller.constrain_movement(
        model,
        passenger,
        MovementResult(int(passenger.unique_id), (50.5, 28.75), reached=False),
    )

    assert blocked.position == passenger.pos
    assert backend.removed_passenger_ids == [int(passenger.unique_id)]
    assert passenger.last_replan_reason == "one_way_direction:one_way"

    model.step()
    model.step()
    restored = model.control_timeline_controller.constrain_movement(
        model,
        passenger,
        MovementResult(int(passenger.unique_id), (50.5, 28.75), reached=False),
    )
    assert restored.position == (50.5, 28.75)


def test_idle_escalator_direction_changes_and_restores() -> None:
    facility_id = "vertical:down_escalator_a:down:b1_concourse:b2_platform"
    measure = ControlMeasure(
        "reverse_escalator",
        ESCALATOR_DIRECTION,
        "Reverse escalator",
        target_id=facility_id,
    )
    plan = _single_measure_plan(
        measure,
        SET_DIRECTION,
        RESTORE_DIRECTION,
        parameters={"direction": "up"},
    )
    scenario = replace(
        _scenario(plan),
        station_design=create_design("visual_demo_station"),
    )
    model = MetroStationModel(scenario, movement_backend=TrackingMovementBackend())
    facility = model.facilities_by_id[facility_id]
    original_entry = facility.spec.entry_level_id

    model.step()
    assert facility.spec.direction == "up"
    assert facility.spec.entry_level_id == "b2_platform"
    active_binding = model.facility_portal_binding(facility_id)
    assert active_binding.direction == facility.spec.direction
    assert active_binding.entry_point == facility.spec.position
    assert active_binding.exit_point == facility.spec.exit_position
    assert active_binding.entry_level_id == facility.spec.entry_level_id
    assert active_binding.exit_level_id == facility.spec.exit_level_id
    assert tuple(facility.queue.layout.slots) == active_binding.queue_slots
    assert facility.spec.queue_layout.slot(0) != facility.spec.queue_layout.slot(1)
    assert model.jupedsim_walkable_area("b2_platform").covers(
        Point(facility.spec.queue_layout.slot(1))
    )

    model.step()
    model.step()
    assert facility.spec.direction == "down"
    assert facility.spec.entry_level_id == original_entry
    assert model.facility_portal_binding(facility_id).direction == "down"


def test_escalator_direction_change_waits_until_the_queue_is_drained() -> None:
    facility_id = "vertical:down_escalator_a:down:b1_concourse:b2_platform"
    measure = ControlMeasure(
        "reverse_busy_escalator",
        ESCALATOR_DIRECTION,
        "Reverse busy escalator",
        target_id=facility_id,
    )
    plan = _single_measure_plan(
        measure,
        SET_DIRECTION,
        RESTORE_DIRECTION,
        parameters={"direction": "up"},
    )
    scenario = replace(
        _scenario(plan),
        station_design=create_design("visual_demo_station"),
    )
    model = MetroStationModel(scenario, movement_backend=TrackingMovementBackend())
    facility = model.facilities_by_id[facility_id]
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
    facility.queue.join(passenger)

    model.control_timeline_controller.apply_due(model)

    assert model.control_timeline_controller.applied_events == []
    assert model.control_timeline_controller.has_pending_events
    assert facility.spec.direction == "down"
    assert model.control_timeline_controller.active_controls() == ()

    facility.queue.remove(passenger)
    model.control_timeline_controller.apply_due(model)

    applied = model.control_timeline_controller.applied_events[0]
    assert applied.status == "applied"
    assert applied.applied_seconds >= applied.scheduled_seconds
    assert facility.spec.direction == "up"
    assert model.control_timeline_controller._pending_runtime_events == []


def test_escalator_reversal_refreshes_exact_evacuation_path_before_selection() -> None:
    facility_id = "vertical:up_escalator_a:up:b2_platform:b1_concourse"
    measure = ControlMeasure(
        "reverse_evacuation_escalator",
        ESCALATOR_DIRECTION,
        "Reverse evacuation escalator",
        target_id=facility_id,
    )
    plan = _single_measure_plan(
        measure,
        SET_DIRECTION,
        RESTORE_DIRECTION,
        parameters={"direction": "down"},
    )
    scenario = replace(
        _scenario(plan),
        station_design=create_design("visual_demo_station"),
    )
    model = MetroStationModel(scenario, movement_backend=TrackingMovementBackend())
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger.current_level_id = platform.level_id
    passenger.pos = platform.position
    passenger.goal_runtime = model.evacuation_goal_runtime_from_position(
        passenger,
        station_interior=True,
    )
    model.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
    passenger.evacuation_facility_path = (facility_id,)

    model.control_timeline_controller.apply_due(model)

    applied = model.control_timeline_controller.applied_events[0]
    assert applied.status == "applied"
    assert applied.details["passengers_replanned"] == 1
    assert model.facilities_by_id[facility_id].spec.direction == "down"
    assert passenger.evacuation_facility_path
    assert facility_id not in passenger.evacuation_facility_path


def test_newly_usable_reversed_escalator_can_replace_still_valid_old_path() -> None:
    facility_id = "vertical:down_escalator_a:down:b1_concourse:b2_platform"
    measure = ControlMeasure(
        "add_up_escalator",
        ESCALATOR_DIRECTION,
        "Add upward escalator",
        target_id=facility_id,
    )
    plan = _single_measure_plan(
        measure,
        SET_DIRECTION,
        RESTORE_DIRECTION,
        parameters={"direction": "up"},
    )
    scenario = replace(
        _scenario(plan),
        station_design=create_design("two_level_island_platform"),
    )
    model = MetroStationModel(scenario, movement_backend=TrackingMovementBackend())
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger.current_level_id = platform.level_id
    passenger.pos = model.layout_graph.facility_portal_binding_variant(
        facility_id,
        "up",
    ).entry_point
    passenger.goal_runtime = model.evacuation_goal_runtime_from_position(
        passenger,
        station_interior=True,
    )
    model.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
    old_path = passenger.evacuation_facility_path
    assert facility_id not in old_path

    model.control_timeline_controller.apply_due(model)

    applied = model.control_timeline_controller.applied_events[0]
    assert applied.status == "applied"
    assert applied.details["passengers_replanned"] == 1
    assert passenger.evacuation_facility_path != old_path
    assert passenger.evacuation_facility_path[0] == facility_id


def test_blocking_selected_vertical_portal_reroots_to_walkable_alternative() -> None:
    baseline = MetroStationModel(
        replace(
            _scenario(ControlPlan("empty", "empty", (), ())),
            station_design=create_design("visual_demo_station"),
        ),
        movement_backend=TrackingMovementBackend(),
    )
    baseline_passenger = baseline._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = baseline.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    baseline_passenger.current_level_id = platform.level_id
    baseline_passenger.pos = platform.position
    baseline.evacuation_goal_runtime_from_position(
        baseline_passenger,
        station_interior=True,
    )
    selected_id = baseline_passenger.evacuation_facility_path[0]
    selected = baseline.facilities_by_id[selected_id]
    x, y = selected.spec.position
    measure = ControlMeasure(
        "block_selected_portal",
        WATER_BARRIER,
        "Block selected portal",
        level_id=selected.spec.entry_level_id,
        parameters={
            "geometry": {
                "shape": "rect",
                "x_m": x - 0.7,
                "y_m": y - 0.7,
                "width_m": 1.4,
                "height_m": 1.4,
            }
        },
    )
    plan = ControlPlan(
        "block_portal_plan",
        "Block portal",
        (measure,),
        (ControlEvent("block_portal", measure.measure_id, 0, DEPLOY),),
    )
    model = MetroStationModel(
        replace(_scenario(plan), station_design=create_design("visual_demo_station")),
        movement_backend=TrackingMovementBackend(),
    )
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger.current_level_id = platform.level_id
    passenger.pos = platform.position
    passenger.goal_runtime = model.evacuation_goal_runtime_from_position(
        passenger,
        station_interior=True,
    )
    model.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
    assert passenger.evacuation_facility_path[0] == selected_id

    model.control_timeline_controller.apply_due(model)

    assert model.control_timeline_controller.applied_events[0].status == "applied"
    assert not model.jupedsim_walkable_area(selected.spec.entry_level_id).covers(
        Point(selected.spec.position)
    )
    assert passenger.evacuation_facility_path
    assert selected_id not in passenger.evacuation_facility_path


def test_wall_that_does_not_change_route_cost_keeps_evacuation_choice() -> None:
    measure = ControlMeasure(
        "detour_wall",
        WATER_BARRIER,
        "Detour wall",
        level_id="b2_platform",
        parameters={
            "geometry": {
                "shape": "rect",
                "x_m": 50.0,
                "y_m": 5.0,
                "width_m": 1.0,
                "height_m": 27.0,
            }
        },
    )
    plan = ControlPlan(
        "detour_wall_plan",
        "Detour wall",
        (measure,),
        (ControlEvent("deploy_detour_wall", measure.measure_id, 0, DEPLOY),),
    )
    model = MetroStationModel(
        replace(
            _scenario(plan),
            station_design=create_design("two_level_island_platform"),
        ),
        movement_backend=TrackingMovementBackend(),
    )
    passenger = model._spawn_passenger(AgentIntent.EVACUATE_STATION)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]
    passenger.current_level_id = platform.level_id
    passenger.pos = platform.position
    passenger.goal_runtime = model.evacuation_goal_runtime_from_position(
        passenger,
        station_interior=True,
    )
    model.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
    old_path = passenger.evacuation_facility_path
    old_facility = model.facilities_by_id[old_path[0]]

    model.control_timeline_controller.apply_due(model)

    area = model.jupedsim_walkable_area("b2_platform")
    assert area.covers(Point(old_facility.spec.position))
    assert all(
        area.covers(Point(facility.spec.position))
        for facility in model.vertical_transports
        if facility.spec.entry_level_id == "b2_platform"
    )
    # This barrier does not intersect or lengthen the selected tactical route.
    # Replanning must therefore remain deterministic instead of switching just
    # because a topology-change event occurred.
    assert passenger.evacuation_facility_path == old_path


def test_staff_guidance_biases_and_counts_target_selection() -> None:
    measure = ControlMeasure(
        "guide_lane",
        STAFF_GUIDANCE,
        "Guide lane",
        target_id=LANE_1,
    )
    plan = _single_measure_plan(measure, START_GUIDANCE, STOP_GUIDANCE)
    model = MetroStationModel(_scenario(plan), movement_backend=TrackingMovementBackend())
    model.step()
    facility = model.facilities_by_id[LANE_1]
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
    passenger.current_level_id = facility.spec.entry_level_id

    adjustment = model.control_timeline_controller.guidance_cost_adjustment(
        passenger,
        facility,
    )
    model.control_timeline_controller.record_guided_selection(passenger, facility)
    model.control_timeline_controller.record_guided_selection(passenger, facility)

    assert adjustment == -120.0
    assert sum(admin.guided_count for admin in model.admin_agents) == passenger.group_size

    model.step()
    model.step()
    assert model.control_timeline_controller.guidance_cost_adjustment(passenger, facility) == 0.0
