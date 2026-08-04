from __future__ import annotations

from copy import copy
from dataclasses import replace
from math import cos, hypot, radians, sin
from types import SimpleNamespace

import pytest
from shapely.geometry import Point as ShapelyPoint, Polygon

from metro_station.adapters.simulation.runtime import (
    facility_queue_routing as facility_queue_routing_module,
)
from metro_station.adapters.simulation.runtime.approach_slot_assignment import (
    rebalance_current_step_approach_slots,
)

from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.facilities.elevator_runtime import ElevatorProcessAgent
from metro_station.adapters.simulation.facilities.escalator_runtime import (
    EscalatorProcessAgent,
)
from metro_station.adapters.simulation.facilities.facility_queue import FacilityQueue
from metro_station.adapters.simulation.facilities.process import QueueLayout
from metro_station.adapters.simulation.facilities.stairs_runtime import StairsProcessAgent
from metro_station.adapters.simulation.facilities.vertical import (
    ElevatorConfig,
    VerticalFacilityConfig,
)
from metro_station.adapters.simulation.planning.plan import AgentIntent, WALKING_STATES
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.layout_queue_geometry import (
    _queue_layout_behind_service_entry,
    _queue_layout_with_service_entry_slot,
)
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_testkit.instant_movement_backend import InstantMovementBackend
from metro_station_testkit.metamorphic_bases import generate_metamorphic_base
from metro_station_testkit.metamorphic_transforms import apply_metamorphic_transform


def _model(
    *,
    tick_seconds: int = 1,
    design_template: str = "visual_demo_station",
) -> MetroStationModel:
    scenario = StationSandboxScenario(
        station_name="facility_transition_test",
        hour=8,
        minutes=1,
        tick_seconds=tick_seconds,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design(design_template),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    return MetroStationModel(
        scenario,
        seed=23,
        movement_backend=InstantMovementBackend(),
    )


def _gate_with_slots(model: MetroStationModel, count: int = 2):
    return next(gate for gate in model.gates if len(gate.spec.queue_layout.slots) >= count)


def test_arrival_from_walking_has_one_full_queue_reaction_interval() -> None:
    model = _model()
    escalator = next(
        item for item in model.vertical_transports if isinstance(item, EscalatorProcessAgent)
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    passenger.pos = escalator.spec.queue_layout.slot(3)
    start = passenger.pos

    assert escalator.join_queue(
        passenger,
        authority="goal_graph",
        settle_after_walking=True,
    )
    escalator._layout_queue()
    assert passenger.pos == start

    model.step_index = 1
    escalator._layout_queue()
    assert passenger.pos == start

    model.step_index = 2
    escalator._layout_queue()
    assert passenger.pos != start


def test_passive_vertical_service_starts_from_actual_queue_portal() -> None:
    model = _model()
    escalator = next(
        item for item in model.vertical_transports if isinstance(item, EscalatorProcessAgent)
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    passenger.pos = escalator._safe_queue_slot(0)
    start = passenger.pos
    ride_steps = escalator._ride_steps_from_seconds(None)
    assert escalator.queue.join(passenger)
    assert escalator.queue.pop(0) is passenger

    escalator._start_passive_ride(
        passenger,
        mode="stand",
        ride_steps=ride_steps,
    )

    assert passenger.pos == start
    assert escalator.active_rides[0].start_position == start
    assert model.facility_service_events[0].start_position == start

    escalator._advance_active_rides()
    displacement = hypot(passenger.pos[0] - start[0], passenger.pos[1] - start[1])
    assert displacement <= escalator.travel_speed_units_per_tick + 0.05
    assert displacement > 0.0


def test_escalator_ride_emits_five_hz_process_motion_truth() -> None:
    model = _model()
    escalator = next(
        item for item in model.vertical_transports if isinstance(item, EscalatorProcessAgent)
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    passenger.pos = escalator._safe_queue_slot(0)
    assert escalator.queue.join(passenger)
    assert escalator.queue.pop(0) is passenger
    escalator._start_passive_ride(
        passenger,
        mode="stand",
        ride_steps=escalator._ride_steps_from_seconds(None),
    )
    model.step_index = 1

    escalator._advance_active_rides()

    payload = model.facility_motion_trace_recorder.as_dict()
    points = [point for point in payload["points"] if point["phase"] == "escalator_ride"]
    assert points
    assert "escalator_ride" in payload["metadata"]["coverage"]
    assert (
        max(right["time_seconds"] - left["time_seconds"] for left, right in zip(points, points[1:]))
        <= 0.200001
    )


def test_elevator_board_travel_and_unload_emit_declared_process_phases() -> None:
    model = _model()
    elevator = next(
        item for item in model.vertical_transports if isinstance(item, ElevatorProcessAgent)
    )
    elevator.spec = replace(
        elevator.spec,
        vertical_config=VerticalFacilityConfig(
            elevator=ElevatorConfig(
                batch_capacity=1,
                min_dispatch_persons=1,
                boarding_seconds=0.6,
                travel_seconds=0.7,
                unload_seconds=0.4,
                return_seconds=0.5,
            )
        ),
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    assert elevator.join_queue(passenger, authority="goal_graph")
    passenger.pos = elevator._service_entry_position(0)
    elevator._begin_boarding([passenger], loaded_persons=1, start_time=0.0)

    elevator._advance_cabin(elapsed_seconds=elevator.effective_boarding_seconds + 0.7)
    assert elevator.cabin_state == "unloading"
    assert elevator.effective_unloading_seconds >= 0.4
    elevator._advance_cabin(elapsed_seconds=elevator.effective_unloading_seconds)

    payload = model.facility_motion_trace_recorder.as_dict()
    expected_phases = {
        "elevator_boarding",
        "elevator_travel",
        "elevator_unloading",
    }
    assert expected_phases <= set(payload["metadata"]["coverage"])
    for phase in expected_phases:
        points = [point for point in payload["points"] if point["phase"] == phase]
        assert points
        assert all(
            right["time_seconds"] - left["time_seconds"] <= 0.200001
            for left, right in zip(points, points[1:])
        )
    unloading = [point for point in payload["points"] if point["phase"] == "elevator_unloading"]
    assert any(
        hypot(
            right["x"] - left["x"],
            right["y"] - left["y"],
        )
        > 1e-6
        for left, right in zip(unloading, unloading[1:])
    )
    assert (unloading[-1]["x"], unloading[-1]["y"]) == pytest.approx(
        passenger.pos,
        abs=0.001,
    )


@pytest.mark.parametrize("base_index", (1, 7))
def test_elevator_dispatch_prefix_always_has_a_finite_self_clear_unload(
    base_index: int,
) -> None:
    scenario = StationSandboxScenario(
        station_name=f"elevator_unload_metamorphic_{base_index}",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=generate_metamorphic_base(base_index),
        elevator_cabin_capacity_persons=6,
        elevator_min_dispatch_persons=1,
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(
        scenario,
        seed=271828,
        movement_backend=InstantMovementBackend(),
    )
    elevator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
    )
    passengers = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        for _ in range(3)
    ]
    model.passengers.extend(passengers)
    for index, passenger in enumerate(passengers):
        assert elevator.join_queue(passenger, authority="goal_graph")
        passenger.pos = elevator._service_entry_position(index)

    elevator._start_boarding(force=True, start_time=0.0)
    largest_dispatch = len(elevator.cabin_passengers)
    for step in range(1, 161):
        model.step_index = step
        elevator._advance_cabin(elapsed_seconds=1.0)
        if elevator.served_persons == len(passengers):
            break

    assert 0 < largest_dispatch <= len(passengers)
    assert elevator.served_persons == len(passengers)
    assert elevator.cabin_load_persons == 0
    assert elevator.cabin_state != "unloading"
    assert not any(elevator.has_active_service(passenger) for passenger in passengers)


@pytest.mark.parametrize("base_index,radius", ((1, 0.25), (1, 0.35), (7, 0.35)))
@pytest.mark.parametrize("tick_seconds", (1, 5))
def test_mirrored_elevator_unloading_uses_one_sequential_occupancy_contract(
    base_index: int,
    radius: float,
    tick_seconds: int,
) -> None:
    document = apply_metamorphic_transform(
        generate_metamorphic_base(base_index),
        "M2-MIRROR",
        seed=20260800 + base_index,
    )
    scenario = StationSandboxScenario(
        station_name="mirrored_elevator_unloading",
        hour=8,
        minutes=1,
        tick_seconds=tick_seconds,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=document,
        jupedsim_agent_radius_units=radius,
        elevator_cabin_capacity_persons=6,
        elevator_min_dispatch_persons=1,
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(
        scenario,
        seed=271828,
        movement_backend=InstantMovementBackend(),
    )
    elevator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
    )
    passengers = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        for _ in range(3)
    ]
    model.passengers.extend(passengers)
    for index, passenger in enumerate(passengers):
        assert elevator.join_queue(passenger, authority="goal_graph")
        passenger.pos = elevator._service_entry_position(index)

    elevator._start_boarding(force=True, start_time=0.0)
    admitted = tuple(elevator.cabin_passengers)
    assert admitted
    for step in range(1, 241):
        model.step_index = step
        elevator._advance_cabin(elapsed_seconds=float(tick_seconds))
        if elevator.served_persons >= len(admitted):
            break

    assert elevator.served_persons >= len(admitted)
    assert elevator.cabin_state != "unloading"
    assert not any(elevator.has_active_service(passenger) for passenger in admitted)


def test_elevator_rejects_an_oversized_fifo_group_without_blocking_followers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model()
    elevator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
    )
    monkeypatch.setattr(
        ElevatorProcessAgent,
        "cabin_capacity_persons",
        property(lambda _self: 2),
    )
    oversized = PassengerAgent(
        model,
        group_size=3,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    follower = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.extend((oversized, follower))

    assert not elevator.join_queue(oversized, authority="goal_graph")
    assert tuple(elevator.queue) == ()
    assert elevator.join_queue(follower, authority="goal_graph")
    follower.pos = elevator._service_entry_position(0)
    boarded, loaded_persons, _blocked, _geometry_limited = (
        elevator._ready_boarding_batch()
    )

    assert boarded == [follower]
    assert loaded_persons == 1
    assert elevator.cabin_load_persons == 0


def test_train_door_rejects_a_live_body_in_its_swept_boarding_path() -> None:
    model = _model()
    door = model.boarding_doors[0]
    train = model.train_for_facility(door)
    assert train is not None
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    blocker = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    model.passengers.extend((rider, blocker))
    rider.current_level_id = door.spec.entry_level_id
    blocker.current_level_id = door.spec.entry_level_id
    rider.pos = door._service_entry_position(0)
    endpoint = model.clamp_position(door.portal_entry_position)
    blocker.pos = (
        (rider.pos[0] + endpoint[0]) / 2.0,
        (rider.pos[1] + endpoint[1]) / 2.0,
    )
    train.state = "boarding"
    train.close_step = 100

    assert not door._can_start_service(rider, train)
    with pytest.raises(RuntimeError, match="swept path"):
        door._start_service(rider, train)

    assert not door.active_boardings
    assert train.current_load_persons == 0
    assert train.reserved_boarding_persons == 0


def test_train_door_requires_precise_queue_head_handoff_before_admission() -> None:
    model = _model()
    door = model.boarding_doors[0]
    train = model.train_for_facility(door)
    assert train is not None
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(rider)
    rider.current_level_id = door.spec.entry_level_id
    handoff = door._service_entry_position(0)
    portal = model.clamp_position(door.portal_entry_position)
    dx = handoff[0] - portal[0]
    dy = handoff[1] - portal[1]
    length = hypot(dx, dy)
    assert length > 0.4
    # This is inside the old 0.45 m semantic region but is not yet at the
    # physical queue-head handoff.  Admission here lets a follower occupy the
    # rider's swept crossing corridor before native motion begins.
    rider.pos = (
        handoff[0] + dx / length * 0.4,
        handoff[1] + dy / length * 0.4,
    )
    train.state = "boarding"
    train.close_step = 100

    assert hypot(rider.pos[0] - handoff[0], rider.pos[1] - handoff[1]) < 0.45
    assert not door._can_start_service(rider, train)

    rider.pos = handoff
    assert door._can_start_service(rider, train)


def test_train_door_does_not_compact_follower_into_active_crossing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model()
    door = model.boarding_doors[0]
    train = model.train_for_facility(door)
    assert train is not None
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    follower = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.extend((rider, follower))
    for passenger in (rider, follower):
        passenger.current_level_id = door.spec.entry_level_id
        assert door.join_queue(passenger, authority="goal_graph")
    rider.pos = door._service_entry_position(0)
    follower.pos = door._service_entry_position(1)
    original_motion = door._boarding_motion
    monkeypatch.setattr(
        door,
        "_boarding_motion",
        lambda passenger: (*original_motion(passenger)[:2], 10.0),
    )
    train.state = "boarding"
    train.close_step = 100

    door.step(train)
    assert door.active_boardings
    follower_position = tuple(follower.pos)
    model.step_index += 1
    door.step(train)

    assert door.active_boardings
    assert tuple(follower.pos) == follower_position


def test_train_door_active_crossing_reserves_handoff_from_late_arrival() -> None:
    model = _model()
    door = model.boarding_doors[0]
    train = model.train_for_facility(door)
    assert train is not None
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    late_arrival = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.extend((rider, late_arrival))
    for passenger in (rider, late_arrival):
        passenger.current_level_id = door.spec.entry_level_id
    rider.pos = door._service_entry_position(0)
    late_arrival.pos = door._service_entry_position(1)
    train.state = "boarding"
    train.close_step = 100

    assert 0 in model._available_facility_approach_slot_indices(door)
    door._start_service(rider, train)

    assert door.lifecycle_reserved_queue_slot_indices == (0,)
    assert 0 not in model._available_facility_approach_slot_indices(door)
    assert not door.join_queue(late_arrival, authority="goal_graph")

    active = door.active_boardings[0]
    active.elapsed_seconds = active.duration_seconds
    rider.pos = active.end_position
    rider.train_door_motion_episode_id = (
        f"train_door:{door.facility_id}:{active.event_id}:boarding"
    )
    door.commit_active_boardings_after_movement()

    assert door.lifecycle_reserved_queue_slot_indices == ()
    assert 0 in model._available_facility_approach_slot_indices(door)
    assert door.join_queue(late_arrival, authority="goal_graph")


def test_train_departure_counts_only_a_completed_door_crossing() -> None:
    model = _model()
    door = model.boarding_doors[0]
    train = model.train_for_facility(door)
    assert train is not None
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(passenger)
    passenger.current_level_id = door.spec.entry_level_id
    passenger.pos = door._service_entry_position(0)
    train.state = "boarding"
    train.close_step = 100

    door._start_service(passenger, train)

    assert train.current_load_persons == 0
    assert train.reserved_boarding_persons == 1
    train.close_step = 0
    for step in range(6):
        model.step_index = step
        train.step()
        door.step(train)
        if train.state == "away":
            break

    assert train.state == "away"
    assert train.departure_safety_hold_steps > 0
    assert train.reserved_boarding_persons == 0
    assert train.last_departed_load_persons == 1
    assert door.served_persons == 1


def test_train_door_does_not_admit_service_past_close_boundary() -> None:
    model = _model()
    door = model.boarding_doors[0]
    train = model.train_for_facility(door)
    assert train is not None
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(passenger)
    passenger.current_level_id = door.spec.entry_level_id
    passenger.pos = door._service_entry_position(0)
    model.step_index = 10
    train.state = "boarding"
    train.close_step = 11

    assert not door._can_start_service(passenger, train)
    with pytest.raises(RuntimeError, match="close boundary"):
        door._start_service(passenger, train)

    assert not door.active_boardings
    assert train.current_load_persons == 0
    assert train.reserved_boarding_persons == 0


def test_train_door_commits_a_native_body_that_crossed_past_the_portal() -> None:
    model = _model()
    door = model.boarding_doors[0]
    train = model.train_for_facility(door)
    assert train is not None
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(rider)
    rider.current_level_id = door.spec.entry_level_id
    rider.pos = door._service_entry_position(0)
    train.state = "boarding"
    train.close_step = 100

    door._start_service(rider, train)
    active = door.active_boardings[0]
    active.elapsed_seconds = active.duration_seconds
    dx = active.end_position[0] - active.start_position[0]
    dy = active.end_position[1] - active.start_position[1]
    length = hypot(dx, dy)
    overshoot = 0.03
    native_endpoint = (
        active.end_position[0] + dx / length * overshoot,
        active.end_position[1] + dy / length * overshoot,
    )
    rider.pos = native_endpoint
    rider.train_door_motion_episode_id = (
        f"train_door:{door.facility_id}:{active.event_id}:boarding"
    )

    door.commit_active_boardings_after_movement()

    assert not door.active_boardings
    assert train.reserved_boarding_persons == 0
    assert train.current_load_persons == 1
    assert rider.pos == pytest.approx(native_endpoint)
    event = next(
        item for item in model.facility_service_events if item.event_id == active.event_id
    )
    assert event.end_position == pytest.approx(native_endpoint)


def test_train_door_boarding_body_shares_the_live_jupedsim_collision_world() -> None:
    scenario = StationSandboxScenario(
        station_name="train_door_dynamic_collision_test",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("visual_demo_station"),
        simulation_clock_mode="physical",
        movement_backend_name="jupedsim",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=23)
    if not model.jupedsim.status.available:
        pytest.skip(model.jupedsim.status.message)

    door = model.boarding_doors[0]
    train = model.train_for_facility(door)
    assert train is not None
    train.state = "boarding"
    train.arrival_sequence = 1
    train.close_step = 100
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    walker = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    model.passengers.extend((rider, walker))
    rider.current_level_id = door.portal_entry_level_id
    walker.current_level_id = door.portal_entry_level_id
    rider.pos = door._service_entry_position(0)
    endpoint = tuple(door.portal_entry_position)
    dx = rider.pos[0] - endpoint[0]
    dy = rider.pos[1] - endpoint[1]
    path_length = hypot(dx, dy)
    ux, uy = dx / path_length, dy / path_length
    walker.pos = (endpoint[0] - ux * 0.55, endpoint[1] - uy * 0.55)
    walker.target = (endpoint[0] + ux * 0.2, endpoint[1] + uy * 0.2)
    walker.state = next(iter(WALKING_STATES))

    door._start_service(rider, train)
    model.step_index = 1
    door._advance_active_boardings()
    results = model.movement_backend.step_all(list(model.passengers))
    for passenger, result in results:
        passenger.apply_movement_result(result)
    door.commit_active_boardings_after_movement()

    observed_clearance = hypot(walker.pos[0] - rider.pos[0], walker.pos[1] - rider.pos[1])
    assert int(rider.unique_id) in model.movement_backend.active_passenger_ids()
    assert observed_clearance >= door._release_min_distance() - 1e-9


@pytest.mark.parametrize("tick_seconds", (1, 2, 5))
def test_train_door_native_body_reaches_declared_endpoint_before_commit(
    tick_seconds: int,
) -> None:
    scenario = StationSandboxScenario(
        station_name="train_door_native_endpoint_test",
        hour=8,
        minutes=1,
        tick_seconds=tick_seconds,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("visual_demo_station"),
        simulation_clock_mode="physical",
        movement_backend_name="jupedsim",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=29)
    if not model.jupedsim.status.available:
        pytest.skip(model.jupedsim.status.message)

    door = model.boarding_doors[0]
    train = model.train_for_facility(door)
    assert train is not None
    train.state = "boarding"
    train.arrival_sequence = 1
    train.close_step = 100
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(rider)
    rider.current_level_id = door.portal_entry_level_id
    rider.pos = door._service_entry_position(0)

    door._start_service(rider, train)
    for step in range(20):
        model.step_index = step
        door._advance_active_boardings()
        model.movement_backend.step_all(list(model.passengers))
        door.commit_active_boardings_after_movement()
        if not door.active_boardings:
            break

    assert not door.active_boardings
    assert train.reserved_boarding_persons == 0
    assert train.current_load_persons == 1
    assert hypot(
        rider.pos[0] - door.portal_entry_position[0],
        rider.pos[1] - door.portal_entry_position[1],
    ) <= 0.02 + 1e-9


def test_continuous_vertical_release_rejects_a_swept_path_through_a_hole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model()
    escalator = next(
        item for item in model.vertical_transports if isinstance(item, EscalatorProcessAgent)
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    walkable_with_wall = Polygon(
        ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)),
        holes=(((1.5, 0.5), (2.5, 0.5), (2.5, 3.5), (1.5, 3.5)),),
    )
    monkeypatch.setattr(
        model,
        "jupedsim_walkable_area",
        lambda _level_id: walkable_with_wall,
    )

    assert not escalator._continuous_release_path_is_clear(
        passenger,
        (1.0, 2.0),
        (3.0, 2.0),
    )


def test_continuous_vertical_release_cannot_overtake_an_exit_blocker() -> None:
    model = _model()
    escalator = next(
        item for item in model.vertical_transports if isinstance(item, EscalatorProcessAgent)
    )
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    blocker = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    blocker.current_level_id = escalator.spec.exit_level_id
    blocker.pos = escalator.spec.exit_position
    model.passengers.extend((rider, blocker))

    with pytest.raises(RuntimeError, match="physically blocked"):
        escalator._vertical_release_position(
            rider,
            0,
            preferred_release_position=escalator.spec.exit_position,
        )


def test_blocked_vertical_release_restores_authoritative_ride_progress() -> None:
    model = _model()
    escalator = next(
        item for item in model.vertical_transports if isinstance(item, EscalatorProcessAgent)
    )
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    blocker = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    rider.pos = escalator._safe_queue_slot(0)
    blocker.current_level_id = escalator.spec.exit_level_id
    blocker.pos = escalator.spec.exit_position
    model.passengers.extend((rider, blocker))
    assert escalator.queue.join(rider)
    assert escalator.queue.pop(0) is rider
    escalator._start_passive_ride(
        rider,
        mode="stand",
        ride_steps=escalator._ride_steps_from_seconds(None),
    )
    ride = escalator.active_rides[0]
    duration_seconds = float(ride.duration_seconds or 0.0)
    tick_seconds = escalator._process_interval_seconds()
    ride.elapsed_seconds = max(0.0, duration_seconds - tick_seconds / 2.0)
    ride.progress_steps = ride.total_steps * ride.elapsed_seconds / duration_seconds
    ride.remaining_seconds = duration_seconds - ride.elapsed_seconds
    escalator._update_active_ride_position(ride)
    position_before = rider.pos
    elapsed_before = ride.elapsed_seconds
    event_end_before = model.facility_service_events[-1].end_time

    escalator._advance_active_rides()

    assert escalator.active_rides == [ride]
    assert rider.pos == position_before
    assert ride.elapsed_seconds == pytest.approx(elapsed_before)
    assert ride.remaining_seconds == pytest.approx(duration_seconds - elapsed_before)
    assert ride.remaining_seconds > 0.0
    assert model.facility_service_events[-1].end_time > event_end_before
    assert escalator.served_persons == 0


def test_connector_spacing_never_rewinds_an_already_blocked_rider() -> None:
    model = _model(design_template="two_level_island_platform")
    escalator = next(
        item for item in model.vertical_transports if isinstance(item, EscalatorProcessAgent)
    )
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    rider.pos = escalator._safe_queue_slot(0)
    assert escalator.queue.join(rider)
    assert escalator.queue.pop(0) is rider
    escalator._start_passive_ride(
        rider,
        mode="stand",
        ride_steps=escalator._ride_steps_from_seconds(None),
    )
    ride = escalator.active_rides[0]
    duration = float(ride.duration_seconds or 0.0)
    elapsed_before = duration * 0.8
    ride.elapsed_seconds = elapsed_before
    ride.progress_steps = ride.total_steps * 0.8
    position = escalator._ride_position_at_elapsed(ride, elapsed_before)
    start = ride.start_position
    end = escalator._ride_position_at_elapsed(ride, duration)
    axis_length = hypot(end[0] - start[0], end[1] - start[1])
    backward = (
        (start[0] - end[0]) / axis_length,
        (start[1] - end[1]) / axis_length,
    )
    occupied_behind = (
        position[0] + backward[0] * 0.2,
        position[1] + backward[1] * 0.2,
    )

    capped = escalator._cap_elapsed_for_connector_spacing(
        ride,
        elapsed_before,
        duration,
        [occupied_behind],
        [],
    )

    assert capped == pytest.approx(elapsed_before)
    assert capped >= elapsed_before


@pytest.mark.parametrize(
    ("tick_seconds", "design_template"),
    (
        (5, "visual_demo_station"),
        (1, "three_level_transfer"),
        (5, "three_level_transfer"),
    ),
)
def test_blocked_stairs_head_propagates_body_clear_fifo_backpressure(
    tick_seconds: int,
    design_template: str,
) -> None:
    model = _model(tick_seconds=tick_seconds, design_template=design_template)
    stairs = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, StairsProcessAgent) and facility.spec.direction == "up"
    )
    leader = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    follower = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    blocker = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.extend((leader, follower, blocker))

    leader.pos = stairs._safe_queue_slot(0)
    assert stairs.queue.join(leader)
    assert stairs.queue.pop(0) is leader
    stairs._start_passive_ride(
        leader,
        mode="walk",
        ride_steps=stairs._ride_steps_from_seconds(None),
    )
    leader_ride = stairs.active_rides[0]
    duration = float(leader_ride.duration_seconds or 0.0)
    tick = stairs._process_interval_seconds()
    connector_length = hypot(
        stairs.spec.exit_position[0] - leader_ride.start_position[0],
        stairs.spec.exit_position[1] - leader_ride.start_position[1],
    )
    leader_ratio = max(0.5, 1.0 - tick / max(2.0 * duration, 1e-9))
    leader_ride.elapsed_seconds = duration * leader_ratio
    leader_ride.progress_steps = leader_ride.total_steps * leader_ride.elapsed_seconds / duration
    stairs._update_active_ride_position(leader_ride)

    follower.pos = stairs._safe_queue_slot(0)
    assert stairs.queue.join(follower)
    assert stairs.queue.pop(0) is follower
    stairs._start_passive_ride(
        follower,
        mode="walk",
        ride_steps=stairs._ride_steps_from_seconds(None),
    )
    follower_ride = stairs.active_rides[1]
    body_clear_ratio = (stairs._release_min_distance() + 0.05) / connector_length
    follower_ride.elapsed_seconds = duration * max(0.0, leader_ratio - body_clear_ratio)
    follower_ride.progress_steps = (
        follower_ride.total_steps * follower_ride.elapsed_seconds / duration
    )
    stairs._update_active_ride_position(follower_ride)
    blocker.current_level_id = stairs.spec.exit_level_id
    blocker.pos = stairs.spec.exit_position

    stairs._advance_active_rides()

    assert stairs.active_rides == [leader_ride, follower_ride]
    separation = hypot(
        leader.pos[0] - follower.pos[0],
        leader.pos[1] - follower.pos[1],
    )
    assert separation >= stairs._release_min_distance() - 1e-6
    assert stairs.served_persons == 0

    model.passengers.remove(blocker)
    stairs._advance_active_rides()

    assert stairs.served_persons == 1
    assert stairs.active_rides == [follower_ride]


@pytest.mark.parametrize("tick_seconds", (1, 5))
def test_three_level_stairs_does_not_admit_follower_into_occupied_entry(
    tick_seconds: int,
) -> None:
    model = _model(tick_seconds=tick_seconds, design_template="three_level_transfer")
    stairs = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, StairsProcessAgent) and facility.spec.direction == "up"
    )
    leader, follower = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EVACUATE_STATION,
        )
        for _ in range(2)
    ]
    model.passengers.extend((leader, follower))
    entry = stairs._service_entry_position(0)
    leader.pos = entry
    assert stairs.queue.join(leader)
    stairs._serve_queue()
    assert len(stairs.active_rides) == 1

    follower.pos = entry
    assert stairs.queue.join(follower)
    stairs._serve_queue()

    assert len(stairs.active_rides) == 1
    assert stairs.active_rides[0].passenger is leader
    assert tuple(stairs.queue) == (follower,)
    assert hypot(leader.pos[0] - follower.pos[0], leader.pos[1] - follower.pos[1]) == 0.0


@pytest.mark.parametrize("tick_seconds", (1, 5))
@pytest.mark.parametrize(
    "design_template",
    ("two_level_island_platform", "visual_demo_station"),
)
def test_elevator_unloading_uses_the_same_swept_release_contract(
    tick_seconds: int,
    design_template: str,
) -> None:
    model = _model(tick_seconds=tick_seconds, design_template=design_template)
    elevator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
    )
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    blocker = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.extend((rider, blocker))
    rider.pos = elevator._service_entry_position(0)
    assert elevator.queue.join(rider)
    elevator._begin_boarding([rider], loaded_persons=1)
    assert rider.current_level_id == elevator.spec.entry_level_id
    assert not [
        event
        for event in model.goal_parity.events
        if event.stream == "physical" and event.kind == "level_changed"
    ]
    elevator._set_cabin_positions(elevator.spec.exit_position)
    elevator.cabin_state = "unloading"
    elevator.unload_remaining_seconds = 0.0
    blocker.current_level_id = elevator.spec.exit_level_id
    blocker.pos = elevator.spec.exit_position
    cabin_position = rider.pos

    assert not elevator._finish_unloading()
    assert elevator.cabin_passengers == [rider]
    assert rider.pos == cabin_position
    assert rider.current_level_id == elevator.spec.entry_level_id
    assert elevator.served_persons == 0

    model.passengers.remove(blocker)
    assert elevator._finish_unloading()
    assert elevator.cabin_passengers == []
    assert rider.current_level_id == elevator.spec.exit_level_id
    assert elevator.served_persons == 1
    level_events = [
        event
        for event in model.goal_parity.events
        if event.stream == "physical" and event.kind == "level_changed"
    ]
    assert len(level_events) == 1
    assert level_events[0].level_id == elevator.spec.exit_level_id
    assert level_events[0].time_seconds == pytest.approx(model.facility_service_events[-1].end_time)


def test_vertical_lane_capacity_excludes_wall_clipped_exit_lanes() -> None:
    model = _model()
    stairs = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, StairsProcessAgent) and facility.spec.direction == "up"
    )
    spacing = max(
        model.scenario.jupedsim_agent_radius_units * 2.2,
        model.scenario.personal_space_units * 0.5,
    )
    capacity = stairs._physical_lane_capacity(spacing)
    offsets = stairs._physical_lane_layout(capacity, spacing)
    exit_area = model.jupedsim_walkable_area(stairs.spec.exit_level_id)
    body_radius = model.scenario.jupedsim_agent_radius_units

    assert len(offsets) == capacity
    assert all(
        exit_area.buffer(1e-7).covers(
            ShapelyPoint(
                stairs._offset_vertical_position(stairs.spec.exit_position, offset)
            ).buffer(body_radius)
        )
        for offset in offsets
    )


def test_escalator_rejects_direct_ride_start_away_from_service_portal() -> None:
    model = _model()
    escalator = next(
        item
        for item in model.vertical_transports
        if isinstance(item, EscalatorProcessAgent) and len(item.spec.queue_layout.slots) > 2
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    service = escalator.spec.queue_layout.slots[0]
    next_slot = escalator.spec.queue_layout.slots[1]
    direction = (next_slot[0] - service[0], next_slot[1] - service[1])
    direction_length = hypot(*direction)
    passenger.pos = (
        service[0] + direction[0] / direction_length * 0.44,
        service[1] + direction[1] / direction_length * 0.44,
    )
    assert escalator.queue.join(passenger)
    assert escalator.queue.pop(0) is passenger

    with pytest.raises(RuntimeError, match="away from its service portal"):
        escalator._start_passive_ride(passenger, mode="stand", ride_steps=2)


def test_escalator_rejects_unowned_ride_start_at_service_portal() -> None:
    model = _model()
    escalator = next(
        item for item in model.vertical_transports if isinstance(item, EscalatorProcessAgent)
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    passenger.pos = escalator.spec.queue_layout.slot(0)

    with pytest.raises(RuntimeError, match="does not own the queue-head handoff"):
        escalator._start_passive_ride(passenger, mode="stand", ride_steps=2)


def test_queue_reaction_interval_is_tick_index_invariant() -> None:
    model = _model()
    escalator = next(
        item for item in model.vertical_transports if isinstance(item, EscalatorProcessAgent)
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.step_index = 37
    passenger.pos = escalator.spec.queue_layout.slot(4)

    assert escalator.join_queue(
        passenger,
        authority="goal_graph",
        settle_after_walking=True,
    )
    assert escalator.queue.is_settling(passenger)
    model.step_index = 38
    assert escalator.queue.is_settling(passenger)
    model.step_index = 39
    assert not escalator.queue.is_settling(passenger)


def test_compiled_gate_lane_queues_are_connected_and_runtime_bounded() -> None:
    model = _model()

    for gate in model.gates:
        slots = gate.spec.queue_layout.slots
        assert slots
        assert gate.queue.max_length == len(slots)
        assert all(
            hypot(right[0] - left[0], right[1] - left[1]) <= 0.81
            for left, right in zip(slots, slots[1:], strict=False)
        )


def test_compiled_vertical_queues_start_at_service_and_are_connected() -> None:
    model = _model()

    for facility in model.vertical_transports:
        slots = facility.queue.layout.slots
        if isinstance(facility, ElevatorProcessAgent):
            assert (
                hypot(
                    slots[0][0] - facility.spec.position[0],
                    slots[0][1] - facility.spec.position[1],
                )
                >= facility._release_min_distance() - 1e-9
            )
        else:
            assert slots[0] == pytest.approx(facility.spec.position)
        binding = model.facility_portal_binding(facility.facility_id)
        assert facility.queue.max_length == binding.declared_queue_capacity
        assert (
            tuple(facility.queue.layout.slot(index) for index in binding.approach_slot_indices)
            == binding.approach_slots
        )
        assert all(
            hypot(right[0] - left[0], right[1] - left[1]) <= 1.29
            for left, right in zip(slots, slots[1:], strict=False)
        )


@pytest.mark.parametrize("angle_deg", (0.0, 31.0, 90.0, 173.0, 271.0))
def test_vertical_queue_path_invariants_survive_rigid_transforms(
    angle_deg: float,
) -> None:
    angle = radians(angle_deg)
    forward = (cos(angle), sin(angle))
    lateral = (-forward[1], forward[0])
    service = (13.25, -7.75)

    def transform(depth: float, offset: float) -> tuple[float, float]:
        return (
            service[0] - forward[0] * depth + lateral[0] * offset,
            service[1] - forward[1] * depth + lateral[1] * offset,
        )

    raw_slots = tuple(
        transform(depth, offset)
        for depth in (0.8, 1.6, 2.4, 3.2)
        for offset in (-1.6, -0.8, 0.0, 0.8, 1.6)
    )
    layout = QueueLayout(
        anchor=raw_slots[-1],
        per_row=5,
        col_step=(lateral[0] * 0.8, lateral[1] * 0.8),
        row_step=(-forward[0] * 0.8, -forward[1] * 0.8),
        slots=tuple(reversed(raw_slots)),
    )

    ordered = _queue_layout_behind_service_entry(
        layout,
        service,
        (service[0] + forward[0], service[1] + forward[1]),
        approach_forward=forward,
    )
    ordered = _queue_layout_with_service_entry_slot(ordered, service)

    assert len(ordered.slots) >= 8
    assert ordered.slots[0] == pytest.approx(service)
    depths = [
        -((point[0] - service[0]) * forward[0] + (point[1] - service[1]) * forward[1])
        for point in ordered.slots
    ]
    assert all(depth >= -0.15 for depth in depths)
    assert all(right + 0.21 >= left for left, right in zip(depths, depths[1:]))
    assert all(
        hypot(right[0] - left[0], right[1] - left[1]) <= 1.29
        for left, right in zip(ordered.slots, ordered.slots[1:], strict=False)
    )


def test_queue_reservations_fail_closed_at_compiled_slot_capacity() -> None:
    model = _model()
    gate = min(model.gates, key=lambda item: len(item.spec.queue_layout.slots))
    capacity = len(gate.spec.queue_layout.slots)
    passengers = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EVACUATE_STATION,
        )
        for _ in range(capacity + 1)
    ]

    for passenger in passengers[:capacity]:
        model._reserve_facility_approach_slot(passenger, gate)

    overflow = passengers[-1]
    assert not model.facility_has_reservable_approach_slot(overflow, gate)
    with pytest.raises(RuntimeError, match="no reservable compiled queue slot"):
        model._reserve_facility_approach_slot(overflow, gate)


def test_vertical_reservations_are_unique_body_clear_portals() -> None:
    model = _model()
    facility = next(
        item
        for item in model.vertical_transports
        if len(model._facility_approach_slot_indices(item)) >= 4
    )
    approach_indices = model._facility_approach_slot_indices(facility)
    passengers = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EVACUATE_STATION,
        )
        for _ in range(len(approach_indices) + 1)
    ]

    reserved = [
        model._reserve_facility_approach_slot(passenger, facility) for passenger in passengers[:-1]
    ]
    targets = [facility.spec.queue_layout.slot(index) for index in reserved]

    assert len(set(reserved)) == len(reserved)
    assert len(set(targets)) == len(targets)
    assert 0 not in reserved
    minimum_body_clearance = model.scenario.jupedsim_agent_radius_units * 2.0
    assert all(
        hypot(
            target[0] - facility.spec.position[0],
            target[1] - facility.spec.position[1],
        )
        >= minimum_body_clearance
        for target in targets
    )
    assert not model.facility_has_reservable_approach_slot(passengers[-1], facility)


def test_queue_tail_portal_is_not_recycled_before_body_compacts() -> None:
    model = _model()
    facility = next(
        item
        for item in model.vertical_transports
        if len(model._facility_approach_slot_indices(item)) >= 4
    )
    approach_indices = model._facility_approach_slot_indices(facility)
    current_slot = approach_indices[-1]
    assigned_slot = approach_indices[-2]
    queued = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    queued.pos = facility.spec.queue_layout.slot(current_slot)

    assert facility.join_queue(
        queued,
        authority="goal_graph",
        preferred_slot_index=assigned_slot,
    )
    assert current_slot in facility.queue.occupied_slot_indices

    follower = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    assert not model.facility_has_reservable_approach_slot(follower, facility)


def test_same_step_approach_cohort_minimises_crossing_without_rewriting_history() -> None:
    model = _model()
    facility = next(
        item
        for item in model.vertical_transports
        if len(model._facility_approach_slot_indices(item)) >= 4
    )
    stage = facility.spec.stage
    layout = getattr(facility, "approach_queue_layout", facility.spec.queue_layout)
    approach_indices = model._facility_approach_slot_indices(facility)
    historical = PassengerAgent(
        model,
        group_size=1,
        created_step=model.step_index,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.append(historical)
    historical_index = model._reserve_facility_approach_slot(historical, facility)
    model.step_index = 20
    current = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=3,
            intent=AgentIntent.EVACUATE_STATION,
        )
        for _ in range(3)
    ]
    model.passengers.extend(current)

    cohort_indices = approach_indices[1:4]
    for passenger, expected_index in zip(
        current,
        reversed(cohort_indices),
        strict=True,
    ):
        passenger.pos = layout.slot(expected_index)
        model._reserve_facility_approach_slot(passenger, facility)
    rebalance_current_step_approach_slots(model)

    assert historical_index == approach_indices[0]
    assert historical.facility_approach_slots_by_stage[stage] == historical_index
    assert facility.queue.approach_slot_reservation(int(historical.unique_id)) == historical_index
    assert [passenger.facility_approach_slots_by_stage[stage] for passenger in current] == list(
        reversed(cohort_indices)
    )
    for passenger in (historical, *current):
        passenger_id = int(passenger.unique_id)
        index = passenger.facility_approach_slots_by_stage[stage]
        assert facility.queue.approach_slot_reservation(passenger_id) == index
        assert model._facility_targeting_slot_indices[facility.facility_id][passenger_id] == index
        assert (
            model._facility_approach_reservation_registry[(passenger_id, stage)].slot_index == index
        )

    historical.pos = layout.slot(historical_index)
    assert facility.join_queue(
        historical,
        authority="goal_graph",
        settle_after_walking=True,
        preferred_slot_index=historical_index,
    )
    model._clear_facility_targeting_reservation(historical, stage)
    spatial_order = sorted(
        current,
        key=lambda passenger: passenger.facility_approach_slots_by_stage[stage],
    )
    for passenger in spatial_order:
        index = passenger.facility_approach_slots_by_stage[stage]
        assert facility.join_queue(
            passenger,
            authority="goal_graph",
            settle_after_walking=True,
            preferred_slot_index=index,
        )
        model._clear_facility_targeting_reservation(passenger, stage)
    assert list(facility.queue) == [historical, *spatial_order]


def test_same_step_rebalance_retargets_preselection_region_route() -> None:
    model = _model()
    facility = next(
        item
        for item in model.vertical_transports
        if len(model._facility_approach_slot_indices(item)) >= 2
    )
    stage = facility.spec.stage
    layout = getattr(facility, "approach_queue_layout", facility.spec.queue_layout)
    first_index, second_index = model._facility_approach_slot_indices(facility)[:2]
    first = PassengerAgent(
        model,
        group_size=1,
        created_step=model.step_index,
        intent=AgentIntent.EVACUATE_STATION,
    )
    second = PassengerAgent(
        model,
        group_size=1,
        created_step=model.step_index,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.extend((first, second))
    entry_level_id = model.facility_portal_binding(facility.facility_id).entry_level_id
    first.current_level_id = entry_level_id
    second.current_level_id = entry_level_id
    assert model._reserve_facility_approach_slot(first, facility) == first_index
    assert model._reserve_facility_approach_slot(second, facility) == second_index

    first.pos = (layout.slot(second_index)[0], layout.slot(second_index)[1] + 0.4)
    second.pos = (layout.slot(first_index)[0], layout.slot(first_index)[1] + 0.4)
    first.set_route(
        (layout.slot(first_index),),
        goal_kind="goal_region",
        goal_label="vertical_decision",
    )
    second.set_route(
        (layout.slot(second_index),),
        goal_kind="queue_approach",
        goal_label=f"{facility.spec.label} queue approach",
        facility_id=facility.facility_id,
        stage=stage,
    )

    rebalance_current_step_approach_slots(model)

    assert first.facility_approach_slots_by_stage[stage] == second_index
    assert second.facility_approach_slots_by_stage[stage] == first_index
    assert first.current_goal.kind == "goal_region"
    assert first.current_goal.label == "vertical_decision"
    assert first.current_goal.facility_id is None
    assert first.current_goal.stage is None
    first_terminal = first.route[-1] if first.route else first.target
    assert first_terminal == pytest.approx(layout.slot(second_index))
    assert second.current_goal.kind == "queue_approach"
    assert second.current_goal.facility_id == facility.facility_id
    second_terminal = second.route[-1] if second.route else second.target
    assert second_terminal == pytest.approx(layout.slot(first_index))


def test_same_step_rebalance_retargets_pending_navigation_transition() -> None:
    model = _model()
    facility = next(
        item
        for item in model.vertical_transports
        if len(model._facility_approach_slot_indices(item)) >= 2
    )
    stage = facility.spec.stage
    first_index, second_index = model._facility_approach_slot_indices(facility)[:2]
    first_slot = model._facility_approach_slot_position(facility, first_index)
    second_slot = model._facility_approach_slot_position(facility, second_index)
    first = PassengerAgent(
        model,
        group_size=1,
        created_step=model.step_index,
        intent=AgentIntent.EVACUATE_STATION,
    )
    second = PassengerAgent(
        model,
        group_size=1,
        created_step=model.step_index,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.extend((first, second))
    entry_level_id = model.facility_portal_binding(facility.facility_id).entry_level_id
    first.current_level_id = entry_level_id
    second.current_level_id = entry_level_id
    model._reserve_facility_approach_slot(first, facility)
    model._reserve_facility_approach_slot(second, facility)
    first.pos = (second_slot[0], second_slot[1] + 0.4)
    second.pos = (first_slot[0], first_slot[1] + 0.4)
    first.set_target((first.pos[0] + 0.2, first.pos[1]), goal_kind="walk")
    first._pending_route_transition = (
        (first_slot,),
        "goal_region",
        "vertical_decision",
        None,
        None,
    )
    second.set_target(
        second_slot,
        goal_kind="queue_approach",
        facility_id=facility.facility_id,
        stage=stage,
    )

    rebalance_current_step_approach_slots(model)

    assert first.facility_approach_slots_by_stage[stage] == second_index
    pending = first._pending_route_transition
    terminal = pending[0][-1] if pending is not None else first.target
    assert terminal == pytest.approx(second_slot)
    goal = first.current_goal if pending is None else pending
    assert (goal.kind if pending is None else goal[1]) == "goal_region"


def test_same_step_rebalance_leaves_cohort_atomic_when_navigation_is_foreign() -> None:
    model = _model()
    facility = next(
        item
        for item in model.vertical_transports
        if len(model._facility_approach_slot_indices(item)) >= 2
    )
    stage = facility.spec.stage
    first_index, second_index = model._facility_approach_slot_indices(facility)[:2]
    first_slot = model._facility_approach_slot_position(facility, first_index)
    second_slot = model._facility_approach_slot_position(facility, second_index)
    passengers = tuple(
        PassengerAgent(
            model,
            group_size=1,
            created_step=model.step_index,
            intent=AgentIntent.EVACUATE_STATION,
        )
        for _ in range(2)
    )
    model.passengers.extend(passengers)
    for passenger in passengers:
        model._reserve_facility_approach_slot(passenger, facility)
    passengers[0].pos = (second_slot[0], second_slot[1] + 0.4)
    passengers[1].pos = (first_slot[0], first_slot[1] + 0.4)
    for index, passenger in enumerate(passengers):
        passenger.set_target(
            (100.0 + index, 100.0),
            goal_kind="foreign_navigation",
        )

    rebalance_current_step_approach_slots(model)

    assert [passenger.facility_approach_slots_by_stage[stage] for passenger in passengers] == [
        first_index,
        second_index,
    ]
    assert [
        facility.queue.approach_slot_reservation(int(passenger.unique_id))
        for passenger in passengers
    ] == [first_index, second_index]


def test_same_step_rebalance_empty_route_cannot_leave_old_slot_target(monkeypatch) -> None:
    model = _model()
    facility = next(
        item
        for item in model.vertical_transports
        if len(model._facility_approach_slot_indices(item)) >= 2
    )
    stage = facility.spec.stage
    layout = getattr(facility, "approach_queue_layout", facility.spec.queue_layout)
    first_index, second_index = model._facility_approach_slot_indices(facility)[:2]
    first = PassengerAgent(
        model,
        group_size=1,
        created_step=model.step_index,
        intent=AgentIntent.EVACUATE_STATION,
    )
    second = PassengerAgent(
        model,
        group_size=1,
        created_step=model.step_index,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.extend((first, second))
    model._reserve_facility_approach_slot(first, facility)
    model._reserve_facility_approach_slot(second, facility)
    first.pos = (layout.slot(second_index)[0], layout.slot(second_index)[1] + 0.4)
    second.pos = (layout.slot(first_index)[0], layout.slot(first_index)[1] + 0.4)
    first.set_target(layout.slot(first_index), goal_kind="goal_region")
    second.set_target(layout.slot(second_index), goal_kind="goal_region")
    monkeypatch.setattr(model, "route_to_facility_queue_slot", lambda *_args: ())

    rebalance_current_step_approach_slots(model)

    assert first.facility_approach_slots_by_stage[stage] == second_index
    assert second.facility_approach_slots_by_stage[stage] == first_index
    assert first.target == pytest.approx(layout.slot(second_index))
    assert second.target == pytest.approx(layout.slot(first_index))


@pytest.mark.parametrize("failure_phase", ("prepare_route", "commit_navigation"))
def test_same_step_rebalance_is_atomic_under_injected_failure(
    monkeypatch,
    failure_phase: str,
) -> None:
    model = _model()
    facility = next(
        item
        for item in model.vertical_transports
        if len(model._facility_approach_slot_indices(item)) >= 2
    )
    stage = facility.spec.stage
    first_index, second_index = model._facility_approach_slot_indices(facility)[:2]
    first = PassengerAgent(
        model,
        group_size=1,
        created_step=model.step_index,
        intent=AgentIntent.EVACUATE_STATION,
    )
    second = PassengerAgent(
        model,
        group_size=1,
        created_step=model.step_index,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.extend((first, second))
    model._reserve_facility_approach_slot(first, facility)
    model._reserve_facility_approach_slot(second, facility)
    first_slot = model._facility_approach_slot_position(facility, first_index)
    second_slot = model._facility_approach_slot_position(facility, second_index)
    first.pos = (second_slot[0], second_slot[1] + 0.4)
    second.pos = (first_slot[0], first_slot[1] + 0.4)
    first.set_target(first_slot, goal_kind="goal_region")
    second.set_target(second_slot, goal_kind="goal_region")
    passenger_ids = (int(first.unique_id), int(second.unique_id))

    def canonical_state():
        return (
            tuple(sorted(model._facility_targeting_slot_indices[facility.facility_id].items())),
            tuple(
                passenger.facility_approach_slots_by_stage[stage] for passenger in (first, second)
            ),
            facility.queue.approach_reservation_state(),
            tuple(
                model._facility_approach_reservation_registry[(passenger_id, stage)]
                for passenger_id in passenger_ids
            ),
            tuple(
                (
                    passenger.target,
                    tuple(passenger.route),
                    passenger.route_segment_start,
                    passenger._pending_route_transition,
                    passenger.corner_recovery_anchor,
                    passenger.corner_recovery_speed_limit_mps,
                    passenger.current_goal,
                )
                for passenger in (first, second)
            ),
        )

    before = canonical_state()
    route_call_count = 0

    def prepared_route(_passenger, _facility, slot_index):
        nonlocal route_call_count
        route_call_count += 1
        # Prepare must not fake a transaction by mutating shared reservations
        # before asking the explicit-slot route provider.
        assert canonical_state() == before
        if failure_phase == "prepare_route" and route_call_count == 2:
            raise RuntimeError("injected route preparation failure")
        return (model._facility_approach_slot_position(facility, slot_index),)

    monkeypatch.setattr(model, "route_to_facility_queue_slot", prepared_route)
    if failure_phase == "commit_navigation":
        monkeypatch.setattr(
            second,
            "set_route",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected navigation commit failure")
            ),
        )

    with pytest.raises(RuntimeError, match="injected"):
        rebalance_current_step_approach_slots(model)

    assert canonical_state() == before


def test_all_compiled_approach_portals_are_body_clear_after_safe_projection() -> None:
    model = _model()
    minimum_separation = max(
        model.scenario.jupedsim_agent_radius_units * model.scenario.jupedsim_clearance_multiplier,
        model.scenario.personal_space_units * 0.5,
    )

    for facility in model.facilities:
        indices = model._facility_approach_slot_indices(facility)
        points = [
            model._project_facility_approach_point(
                facility,
                facility.spec.queue_layout.slot(index),
            )
            for index in indices
        ]
        assert all(
            hypot(left[0] - right[0], left[1] - right[1]) >= minimum_separation - 1e-7
            for left_index, left in enumerate(points)
            for right in points[left_index + 1 :]
        )


def test_pending_reservations_preserve_fifo_under_reverse_join_order() -> None:
    model = _model()
    facility = next(
        item
        for item in model.vertical_transports
        if len(model._facility_approach_slot_indices(item)) >= 3
    )
    passengers = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EVACUATE_STATION,
        )
        for _ in range(3)
    ]
    priorities = [
        model._reserve_facility_approach_slot(passenger, facility) for passenger in passengers
    ]
    for passenger, priority in reversed(tuple(zip(passengers, priorities, strict=True))):
        passenger.pos = facility.spec.queue_layout.slot(priority)
        assert facility.join_queue(
            passenger,
            authority="goal_graph",
            preferred_slot_index=priority,
        )
        model._clear_facility_targeting_reservation(passenger, facility.spec.stage)

    assert list(facility.queue) == passengers
    for _ in range(20):
        facility._layout_queue()
        assigned = [
            facility.queue._assigned_slot_index_by_passenger_id[id(passenger)]
            for passenger in facility.queue
        ]
        assert len(set(assigned)) == len(assigned)
        assert all(
            hypot(left.pos[0] - right.pos[0], left.pos[1] - right.pos[1]) >= 0.395
            for left_index, left in enumerate(facility.queue)
            for right in facility.queue[left_index + 1 :]
        )

    assert [
        facility.queue._assigned_slot_index_by_passenger_id[id(passenger)]
        for passenger in facility.queue
    ] == [0, 1, 2]


def test_reused_physical_slot_never_reuses_fifo_priority() -> None:
    model = _model()
    facility = next(
        item
        for item in model.vertical_transports
        if len(model._facility_approach_slot_indices(item)) >= 3
    )
    first, earlier_pending, later = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EVACUATE_STATION,
        )
        for _ in range(3)
    ]
    first_slot = model._reserve_facility_approach_slot(first, facility)
    earlier_slot = model._reserve_facility_approach_slot(earlier_pending, facility)
    first.pos = facility.spec.queue_layout.slot(first_slot)
    assert facility.join_queue(
        first,
        authority="goal_graph",
        settle_after_walking=True,
        preferred_slot_index=first_slot,
    )
    model._clear_facility_targeting_reservation(first, facility.spec.stage)
    assert facility.queue.pop(0) is first

    reused_slot = model._reserve_facility_approach_slot(later, facility)
    assert reused_slot > earlier_slot
    later.pos = facility.spec.queue_layout.slot(reused_slot)
    assert not facility.join_queue(
        later,
        authority="goal_graph",
        settle_after_walking=True,
        preferred_slot_index=reused_slot,
    )

    earlier_pending.pos = facility.spec.queue_layout.slot(earlier_slot)
    assert facility.join_queue(
        earlier_pending,
        authority="goal_graph",
        settle_after_walking=True,
        preferred_slot_index=earlier_slot,
    )
    model._clear_facility_targeting_reservation(
        earlier_pending,
        facility.spec.stage,
    )
    assert facility.join_queue(
        later,
        authority="goal_graph",
        settle_after_walking=True,
        preferred_slot_index=reused_slot,
    )
    model._clear_facility_targeting_reservation(later, facility.spec.stage)

    assert list(facility.queue) == [earlier_pending, later]


def test_released_inner_approach_slot_compacts_tail_claim_and_reopens_capacity() -> None:
    model = _model()
    facility = next(
        item
        for item in model.vertical_transports
        if len(model._facility_approach_slot_indices(item)) >= 3
    )
    released, pending, follower = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EVACUATE_STATION,
        )
        for _ in range(3)
    ]
    released_slot = model._reserve_facility_approach_slot(released, facility)
    pending_slot = model._reserve_facility_approach_slot(pending, facility)
    assert pending_slot > released_slot
    model._clear_facility_targeting_reservation(released, facility.spec.stage)

    pending.current_level_id = facility.portal_entry_level_id
    old_target = model._facility_approach_slot_position(facility, pending_slot)
    pending.pos = old_target
    pending.set_route(
        (old_target,),
        goal_kind="queue_approach",
        goal_label="pending queue approach",
        facility_id=facility.facility_id,
        stage=facility.spec.stage,
    )
    model.passengers.append(pending)

    rebalance_current_step_approach_slots(model)

    compacted_slot = pending.facility_approach_slots_by_stage[facility.spec.stage]
    assert compacted_slot == released_slot
    assert pending.target == pytest.approx(
        model._facility_approach_slot_position(facility, compacted_slot)
    )
    follower_slot = model._reserve_facility_approach_slot(follower, facility)
    assert follower_slot > compacted_slot


def test_physically_inverted_arrival_waits_outside_then_makes_progress() -> None:
    model = _model()
    slot0, slot1 = _gate_with_slots(model).spec.queue_layout.slots[:2]
    queue = FacilityQueue(
        QueueLayout(
            anchor=slot0,
            per_row=1,
            col_step=(0.0, 0.0),
            row_step=(0.8, 0.0),
            slots=(slot0, slot1),
        ),
        max_length=2,
    )
    head, follower = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        for _ in range(2)
    ]
    head.pos = ((slot0[0] + slot1[0]) / 2.0, (slot0[1] + slot1[1]) / 2.0)
    follower.pos = slot0
    assert queue.join(head)
    assert not queue.join(follower, settle=True)
    assert list(queue) == [head]

    follower.pos = slot1
    assert queue.join(follower, settle=True)
    for step in range(1, 8):
        model.step_index = step
        queue.layout_positions(
            speed=0.2,
            goal_label="test queue",
            facility_id="test",
            stage="entry_gate",
        )

    assert hypot(head.pos[0] - slot0[0], head.pos[1] - slot0[1]) <= 0.12
    assert hypot(follower.pos[0] - slot1[0], follower.pos[1] - slot1[1]) <= 0.12


@pytest.mark.parametrize(
    "spec_change",
    (
        {"entry_level_id": None},
        {"entry_level_id": "unknown_level"},
        {"kind": "gate"},
        {
            "queue_layout": QueueLayout(
                anchor=(999.0, 999.0),
                per_row=1,
                col_step=(0.0, 0.0),
                row_step=(0.8, 0.0),
                slots=((999.0, 999.0),),
            )
        },
    ),
)
def test_compiled_approach_topology_ignores_mutated_runtime_spec(spec_change) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    compiled_indices = model._facility_approach_slot_indices(facility)

    facility.spec = replace(facility.spec, **spec_change)

    assert model._facility_approach_slot_indices(facility) == compiled_indices
    assert compiled_indices == facility.portal_binding.approach_slot_indices


def test_compiled_approach_topology_does_not_call_runtime_projectors(monkeypatch) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    expected = facility.portal_binding.approach_slot_indices
    monkeypatch.setattr(
        model,
        "jupedsim_walkable_area",
        lambda _level_id=None: (_ for _ in ()).throw(RuntimeError("must not run")),
    )
    monkeypatch.setattr(
        model,
        "_project_facility_approach_point",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("must not run")),
    )
    monkeypatch.setattr(
        facility_queue_routing_module,
        "project_to_safe_point",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("must not run")),
    )

    assert model._facility_approach_slot_indices(facility) == expected


def test_explicit_projection_revision_does_not_recompile_portal_topology(monkeypatch) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    original_projector = facility_queue_routing_module.project_to_safe_point

    class MutableProjector:
        failing = False

        def __call__(self, *args, **kwargs):
            if self.failing:
                raise RuntimeError("projection failed")
            return original_projector(*args, **kwargs)

    projector = MutableProjector()
    monkeypatch.setattr(facility_queue_routing_module, "project_to_safe_point", projector)
    expected = model._facility_approach_slot_indices(facility)

    projector.failing = True
    model.invalidate_facility_approach_proofs()

    assert model._facility_approach_slot_indices(facility) == expected


def test_invalidated_proof_revokes_durable_approach_reservation(monkeypatch) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    reserved_index = model._reserve_facility_approach_slot(passenger, facility)
    passenger_id = int(passenger.unique_id)
    assert reserved_index in model._facility_approach_slot_indices(facility)

    monkeypatch.setattr(
        model,
        "_project_facility_approach_point",
        lambda _facility, _point, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("projection failed")
        ),
    )
    model.invalidate_facility_approach_proofs()

    assert passenger_id not in model._facility_targeting_reservations[facility.facility_id]
    assert passenger_id not in model._facility_targeting_slot_indices[facility.facility_id]
    with pytest.raises(RuntimeError, match="stale"):
        model._facility_queue_approach_target(passenger, facility)
    assert model.facility_has_reservable_approach_slot(passenger, facility)
    assert model._reserve_facility_approach_slot(passenger, facility) in (
        facility.portal_binding.approach_slot_indices
    )


def test_proof_invalidation_requests_replan_for_active_targeting_passenger(
    monkeypatch,
) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.append(passenger)
    model._reserve_facility_approach_slot(passenger, facility)
    replanned_ids: list[int] = []
    monkeypatch.setattr(
        model.progress_monitor.replan_policy,
        "replan",
        lambda _model, item, **_kwargs: replanned_ids.append(int(item.unique_id)) or True,
    )

    replanned = model.invalidate_facility_approach_proofs(reason="test_geometry_change")

    assert replanned == 1
    assert replanned_ids == [int(passenger.unique_id)]
    assert facility.facility_id not in passenger.facility_approach_facility_ids_by_stage.values()


def test_missing_demand_copy_cannot_duplicate_compiled_approach_slot() -> None:
    model = _model()
    facility = model.vertical_transports[0]
    first, second = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EVACUATE_STATION,
        )
        for _ in range(2)
    ]

    first_slot = model._reserve_facility_approach_slot(first, facility)
    del model._facility_targeting_reservations[facility.facility_id][int(first.unique_id)]

    # A partially written reservation is revoked and recreated; it is never
    # accepted merely because the passenger and slot-index copies still agree.
    assert model._reserve_facility_approach_slot(first, facility) == first_slot
    second_slot = model._reserve_facility_approach_slot(second, facility)
    assert second_slot != first_slot
    assert {slot for _passenger_id, slot in facility.queue.approach_slot_reservations} == {
        first_slot,
        second_slot,
    }
    assert model.facility_targeting_persons(facility) == 2


def test_proof_invalidation_sweeps_union_when_slot_index_copy_is_missing(
    monkeypatch,
) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.append(passenger)
    assert model._reserve_facility_approach_slot(passenger, facility) in (
        facility.portal_binding.approach_slot_indices
    )
    del model._facility_targeting_slot_indices[facility.facility_id][int(passenger.unique_id)]
    replanned_ids: list[int] = []
    monkeypatch.setattr(
        model.progress_monitor.replan_policy,
        "replan",
        lambda _model, item, **_kwargs: replanned_ids.append(int(item.unique_id)) or True,
    )

    replanned = model.invalidate_facility_approach_proofs(reason="test_partial_write")

    assert replanned == 1
    assert replanned_ids == [int(passenger.unique_id)]
    assert not model._facility_targeting_reservations
    assert not model._facility_targeting_slot_indices
    assert not model._facility_targeting_proof_revisions
    assert facility.queue.approach_slot_reservations == ()
    assert passenger.facility_approach_slots_by_stage == {}
    assert passenger.facility_approach_facility_ids_by_stage == {}


@pytest.mark.parametrize("missing_passenger_copy", ("slot", "facility"))
def test_target_fails_closed_when_either_passenger_claim_copy_is_missing(
    missing_passenger_copy: str,
) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    passenger = PassengerAgent(
        model,
        group_size=2,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model._reserve_facility_approach_slot(passenger, facility)
    stage = facility.spec.stage
    if missing_passenger_copy == "slot":
        passenger.facility_approach_slots_by_stage.pop(stage)
    else:
        passenger.facility_approach_facility_ids_by_stage.pop(stage)

    with pytest.raises(RuntimeError, match="stale"):
        model._facility_queue_approach_target(passenger, facility)

    passenger_id = int(passenger.unique_id)
    assert passenger_id not in model._facility_targeting_reservations[facility.facility_id]
    assert passenger_id not in model._facility_targeting_slot_indices[facility.facility_id]
    assert passenger_id not in model._facility_targeting_proof_revisions[facility.facility_id]
    assert facility.queue.approach_slot_reservation(passenger_id) is None


def test_conflicting_same_stage_facilities_are_cleared_as_one_invalid_claim() -> None:
    model = _model()
    first, second = model.gates[:2]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model._reserve_facility_approach_slot(passenger, second)
    passenger_id = int(passenger.unique_id)
    first_slot = model._available_facility_approach_slot_indices(first)[0]
    model._facility_targeting_reservations[first.facility_id][passenger_id] = 1
    model._facility_targeting_slot_indices[first.facility_id][passenger_id] = first_slot
    model._facility_targeting_proof_revisions[first.facility_id][passenger_id] = (
        model._facility_approach_proof_revision
    )
    first.queue.reserve_approach_slot(passenger_id, first_slot)

    model.facility_has_reservable_approach_slot(passenger, first)

    for facility in (first, second):
        assert passenger_id not in model._facility_targeting_reservations[facility.facility_id]
        assert passenger_id not in model._facility_targeting_slot_indices[facility.facility_id]
        assert passenger_id not in model._facility_targeting_proof_revisions[facility.facility_id]
        assert facility.queue.approach_slot_reservation(passenger_id) is None
    assert passenger.facility_approach_slots_by_stage == {}
    assert passenger.facility_approach_facility_ids_by_stage == {}


def test_three_conflicting_same_stage_facilities_are_all_cleared() -> None:
    model = _model()
    first, mapped, third = model.gates[:3]
    passenger = PassengerAgent(
        model,
        group_size=2,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model._reserve_facility_approach_slot(passenger, mapped)
    passenger_id = int(passenger.unique_id)
    for facility in (first, third):
        slot = model._available_facility_approach_slot_indices(facility)[0]
        model._facility_targeting_reservations[facility.facility_id][passenger_id] = 2
        model._facility_targeting_slot_indices[facility.facility_id][passenger_id] = slot
        model._facility_targeting_proof_revisions[facility.facility_id][passenger_id] = (
            model._facility_approach_proof_revision
        )
        facility.queue.reserve_approach_slot(passenger_id, slot)

    model.facility_has_reservable_approach_slot(passenger, first)

    for facility in (first, mapped, third):
        assert passenger_id not in model._facility_targeting_reservations[facility.facility_id]
        assert facility.queue.approach_slot_reservation(passenger_id) is None


def test_wrong_stage_pointer_does_not_clear_valid_other_stage_reservation() -> None:
    model = _model()
    vertical = model.vertical_transports[0]
    gate = _gate_with_slots(model)
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    vertical_slot = model._reserve_facility_approach_slot(passenger, vertical)
    passenger_id = int(passenger.unique_id)
    gate_stage = gate.spec.stage
    passenger.facility_approach_slots_by_stage[gate_stage] = 99
    passenger.facility_approach_facility_ids_by_stage[gate_stage] = vertical.facility_id

    assert model._reserve_facility_approach_slot(passenger, gate) >= 0

    assert model._facility_targeting_slot_indices[vertical.facility_id][passenger_id] == (
        vertical_slot
    )
    assert vertical.queue.approach_slot_reservation(passenger_id) == vertical_slot
    assert passenger.facility_approach_slots_by_stage[vertical.spec.stage] == vertical_slot
    assert model._existing_facility_approach_reservation_is_valid(passenger, vertical)


def test_unknown_facility_pointer_fails_target_closed_and_clears_local_stage() -> None:
    model = _model()
    gate = _gate_with_slots(model)
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    passenger.facility_approach_slots_by_stage[gate.spec.stage] = 99
    passenger.facility_approach_facility_ids_by_stage[gate.spec.stage] = "missing-gate"
    passenger_id = int(passenger.unique_id)
    model._facility_targeting_reservations["missing-gate"][passenger_id] = 1
    model._facility_targeting_slot_indices["missing-gate"][passenger_id] = 99
    model._facility_targeting_proof_revisions["missing-gate"][passenger_id] = (
        model._facility_approach_proof_revision
    )

    with pytest.raises(RuntimeError, match="stale"):
        model._facility_queue_approach_target(passenger, gate)

    assert gate.spec.stage not in passenger.facility_approach_slots_by_stage
    assert gate.spec.stage not in passenger.facility_approach_facility_ids_by_stage
    assert passenger_id not in model._facility_targeting_reservations["missing-gate"]
    assert passenger_id not in model._facility_targeting_slot_indices["missing-gate"]
    assert passenger_id not in model._facility_targeting_proof_revisions["missing-gate"]


def test_departure_releases_claim_when_passenger_slot_copy_is_missing() -> None:
    model = _model()
    facility = model.vertical_transports[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.append(passenger)
    model._reserve_facility_approach_slot(passenger, facility)
    passenger_id = int(passenger.unique_id)
    passenger.facility_approach_slots_by_stage.pop(facility.spec.stage)

    model.complete_departure(passenger, boarded=False, goal_authorized=True)

    assert passenger_id not in model._facility_targeting_reservations[facility.facility_id]
    assert passenger_id not in model._facility_targeting_slot_indices[facility.facility_id]
    assert passenger_id not in model._facility_targeting_proof_revisions[facility.facility_id]
    assert facility.queue.approach_slot_reservation(passenger_id) is None
    assert not any(key[0] == passenger_id for key in model._facility_approach_reservation_registry)


def test_terminal_release_removes_unknown_outer_facility_claims_by_owner() -> None:
    model = _model()
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.append(passenger)
    passenger_id = int(passenger.unique_id)
    ghost_id = "removed-facility"
    model._facility_targeting_reservations[ghost_id][passenger_id] = 1
    model._facility_targeting_slot_indices[ghost_id][passenger_id] = 7
    model._facility_targeting_proof_revisions[ghost_id][passenger_id] = (
        model._facility_approach_proof_revision
    )

    model.complete_departure(passenger, boarded=False, goal_authorized=True)

    assert passenger_id not in model._facility_targeting_reservations[ghost_id]
    assert passenger_id not in model._facility_targeting_slot_indices[ghost_id]
    assert passenger_id not in model._facility_targeting_proof_revisions[ghost_id]


def test_facility_object_replacement_releases_registry_owned_old_queue() -> None:
    model = _model()
    original = model.vertical_transports[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model._reserve_facility_approach_slot(passenger, original)
    passenger_id = int(passenger.unique_id)
    original_queue = original.queue
    replacement = copy(original)
    replacement.queue = FacilityQueue(
        original.spec.queue_layout,
        max_length=original.queue.max_length,
        ordered=original.queue.ordered,
        reaction_seconds=original.queue.reaction_seconds,
    )
    model.facilities[model.facilities.index(original)] = replacement
    model.facilities_by_id[original.facility_id] = replacement

    model.facility_has_reservable_approach_slot(passenger, replacement)

    assert original_queue.approach_slot_reservation(passenger_id) is None
    assert passenger_id not in model._facility_targeting_reservations[original.facility_id]
    assert (passenger_id, original.spec.stage) not in (
        model._facility_approach_reservation_registry
    )


@pytest.mark.parametrize("corrupted_field", ("facility_id", "queue"))
def test_corrupt_registry_record_cannot_damage_other_stage_claim(
    corrupted_field: str,
) -> None:
    model = _model()
    gate = _gate_with_slots(model)
    vertical = model.vertical_transports[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model._reserve_facility_approach_slot(passenger, gate)
    vertical_slot = model._reserve_facility_approach_slot(passenger, vertical)
    passenger_id = int(passenger.unique_id)
    gate_key = (passenger_id, gate.spec.stage)
    gate_record = model._facility_approach_reservation_registry[gate_key]
    model._facility_approach_reservation_registry[gate_key] = replace(
        gate_record,
        **{
            corrupted_field: (
                vertical.facility_id if corrupted_field == "facility_id" else vertical.queue
            )
        },
    )

    model.facility_has_reservable_approach_slot(passenger, gate)

    assert model._facility_targeting_slot_indices[vertical.facility_id][passenger_id] == (
        vertical_slot
    )
    assert vertical.queue.approach_slot_reservation(passenger_id) == vertical_slot
    assert model._existing_facility_approach_reservation_is_valid(passenger, vertical)


def test_proof_invalidation_uses_owner_key_to_release_replaced_old_queue() -> None:
    model = _model()
    original = model.vertical_transports[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.append(passenger)
    model._reserve_facility_approach_slot(passenger, original)
    passenger_id = int(passenger.unique_id)
    owner_key = (passenger_id, original.spec.stage)
    old_queue = original.queue
    replacement = copy(original)
    replacement.queue = FacilityQueue(
        original.spec.queue_layout,
        max_length=original.queue.max_length,
    )
    model.facilities[model.facilities.index(original)] = replacement
    model.facilities_by_id[original.facility_id] = replacement
    model._facility_approach_reservation_registry[owner_key] = replace(
        model._facility_approach_reservation_registry[owner_key],
        passenger_id=passenger_id + 1000,
    )

    model.invalidate_facility_approach_proofs(reason="test_owner_key")

    assert old_queue.approach_slot_reservation(passenger_id) is None
    assert owner_key not in model._facility_approach_reservation_registry


@pytest.mark.parametrize("missing_handle", ("facility", "queue"))
@pytest.mark.parametrize("cleanup_path", ("lazy", "departure", "invalidation"))
def test_single_registry_handle_loss_still_releases_detached_old_queue(
    missing_handle: str,
    cleanup_path: str,
) -> None:
    model = _model()
    original = model.vertical_transports[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.append(passenger)
    model._reserve_facility_approach_slot(passenger, original)
    passenger_id = int(passenger.unique_id)
    owner_key = (passenger_id, original.spec.stage)
    old_queue = original.queue
    replacement = copy(original)
    replacement.queue = FacilityQueue(
        original.spec.queue_layout,
        max_length=original.queue.max_length,
    )
    model.facilities[model.facilities.index(original)] = replacement
    model.facilities_by_id[original.facility_id] = replacement
    model._facility_approach_reservation_registry[owner_key] = replace(
        model._facility_approach_reservation_registry[owner_key],
        **{missing_handle: None},
    )

    if cleanup_path == "lazy":
        model.facility_has_reservable_approach_slot(passenger, replacement)
    elif cleanup_path == "departure":
        model.complete_departure(passenger, boarded=False, goal_authorized=True)
    else:
        model.invalidate_facility_approach_proofs(reason="test_single_handle")

    assert old_queue.approach_slot_reservation(passenger_id) is None
    assert owner_key not in model._facility_approach_reservation_registry


def test_non_record_registry_value_fails_closed_without_attribute_error() -> None:
    model = _model()
    facility = model.vertical_transports[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model._reserve_facility_approach_slot(passenger, facility)
    passenger_id = int(passenger.unique_id)
    owner_key = (passenger_id, facility.spec.stage)
    model._facility_approach_reservation_registry[owner_key] = object()

    model.facility_has_reservable_approach_slot(passenger, facility)

    assert passenger_id not in model._facility_targeting_reservations[facility.facility_id]
    assert passenger_id not in model._facility_targeting_slot_indices[facility.facility_id]
    assert facility.queue.approach_slot_reservation(passenger_id) is None
    assert owner_key not in model._facility_approach_reservation_registry


def test_vertical_release_avoids_passengers_already_waiting_downstream() -> None:
    model = _model()
    facility = model.vertical_transports[0]
    rider, blocker = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EVACUATE_STATION,
        )
        for _ in range(2)
    ]
    rider.current_level_id = facility.spec.entry_level_id
    blocker.current_level_id = facility.spec.exit_level_id
    blocker.pos = facility.spec.exit_position
    model.passengers.extend((rider, blocker))

    release = facility._vertical_release_position(rider, 0)

    assert hypot(release[0] - blocker.pos[0], release[1] - blocker.pos[1]) >= (
        facility._release_min_distance() - 1e-7
    )


def test_degenerate_vertical_release_uses_station_topology_not_global_axis() -> None:
    scenario = replace(
        _model().scenario,
        station_name="topological-release-direction",
        station_design=create_design("three_level_transfer"),
    )
    model = MetroStationModel(
        scenario,
        seed=24,
        movement_backend=InstantMovementBackend(),
    )
    facility = next(
        item
        for item in model.vertical_transports
        if item.spec.kind == "stairs" and item.spec.direction == "up"
    )
    forward, _lateral = facility._release_axes()
    graph = model.layout_graph.station_graph
    exit_node = next(
        graph.nodes[node_id]
        for node_id in graph.node_ids_for_element(facility.spec.source_element_id)
        if graph.nodes[node_id].level_id == facility.spec.exit_level_id
    )
    floor_target = graph.same_level_walk_neighbor_positions(exit_node.node_id)[0]
    floor_vector = (
        floor_target[0] - facility.spec.exit_position[0],
        floor_target[1] - facility.spec.exit_position[1],
    )

    assert forward[0] * floor_vector[0] + forward[1] * floor_vector[1] > 0


def test_queue_follower_does_not_deadlock_on_nearest_slot_tie() -> None:
    model = _model()
    gate = _gate_with_slots(model)
    slot0, slot1 = gate.spec.queue_layout.slots[:2]
    midpoint = ((slot0[0] + slot1[0]) / 2.0, (slot0[1] + slot1[1]) / 2.0)
    queue = FacilityQueue(
        QueueLayout(
            anchor=slot0,
            per_row=1,
            col_step=(0.0, 0.0),
            row_step=(slot1[0] - slot0[0], slot1[1] - slot0[1]),
            slots=(slot0, slot1),
        ),
        max_length=2,
    )
    head = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    follower = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    head.pos = slot0
    follower.pos = midpoint
    assert queue.join(head)
    assert queue.join(follower)

    for _ in range(20):
        queue.layout_positions(
            speed=0.2,
            goal_label="test queue",
            facility_id="test",
            stage="entry_gate",
        )

    assert hypot(follower.pos[0] - slot1[0], follower.pos[1] - slot1[1]) <= 0.12


def test_queue_layout_never_moves_head_through_unprocessed_follower() -> None:
    model = _model()
    gate = _gate_with_slots(model)
    slot0, slot1 = gate.spec.queue_layout.slots[:2]
    midpoint = ((slot0[0] + slot1[0]) / 2.0, (slot0[1] + slot1[1]) / 2.0)
    queue = FacilityQueue(
        QueueLayout(
            anchor=slot0,
            per_row=1,
            col_step=(0.0, 0.0),
            row_step=(slot1[0] - slot0[0], slot1[1] - slot0[1]),
            slots=(slot0, slot1),
        ),
        max_length=2,
    )
    head = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    follower = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    head.pos = midpoint
    follower.pos = slot0
    assert queue.join(head)
    assert queue.join(follower)

    for _ in range(8):
        queue.layout_positions(
            speed=0.2,
            goal_label="test queue",
            facility_id="test",
            stage="entry_gate",
        )
        assert hypot(head.pos[0] - follower.pos[0], head.pos[1] - follower.pos[1]) >= 0.395


@pytest.mark.parametrize("tick_seconds", (0.25, 0.5, 1.0, 2.0, 5.0))
def test_queue_reaction_dwell_uses_physical_time(tick_seconds: float) -> None:
    model = SimpleNamespace(
        current_time_seconds=0.0,
        scenario=SimpleNamespace(tick_seconds=tick_seconds),
    )
    passenger = SimpleNamespace(pos=(0.0, 0.0), model=model)
    queue = FacilityQueue(
        QueueLayout((0.0, 0.0), 1, (0.0, 0.0), (0.8, 0.0), ((0.0, 0.0),)),
        reaction_seconds=1.0,
    )

    assert queue.join(passenger, settle=True)
    arrival_time = tick_seconds
    model.current_time_seconds = arrival_time
    expected_first_fraction = max(0.0, (tick_seconds - 1.0) / tick_seconds)
    assert queue.settling_motion_fraction(passenger) == pytest.approx(expected_first_fraction)
    if tick_seconds <= 1.0:
        model.current_time_seconds = arrival_time + 1.0 - tick_seconds
        assert queue.is_settling(passenger)
    model.current_time_seconds = arrival_time + 1.0
    assert not queue.is_settling(passenger)


def test_queue_compaction_dwells_before_reversing_direction() -> None:
    model = _model()
    gate = _gate_with_slots(model)
    slot0, slot1 = gate.spec.queue_layout.slots[:2]
    midpoint = ((slot0[0] + slot1[0]) / 2.0, (slot0[1] + slot1[1]) / 2.0)
    queue = FacilityQueue(
        QueueLayout(
            anchor=slot0,
            per_row=1,
            col_step=(0.0, 0.0),
            row_step=(slot1[0] - slot0[0], slot1[1] - slot0[1]),
            slots=(slot0, slot1),
        ),
        max_length=2,
        reaction_seconds=1.0,
    )
    head = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    follower = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    head.pos = slot0
    follower.pos = midpoint
    assert queue.join(head)
    assert queue.join(follower)

    for _ in range(4):
        queue.layout_positions(
            speed=0.2,
            goal_label="test queue",
            facility_id="test",
            stage="entry_gate",
        )
        model.step_index += 1
    assert hypot(follower.pos[0] - slot1[0], follower.pos[1] - slot1[1]) <= 0.12
    queue.pop(0)
    before_reversal = follower.pos

    queue.layout_positions(
        speed=0.2,
        goal_label="test queue",
        facility_id="test",
        stage="entry_gate",
    )

    assert follower.pos == before_reversal


@pytest.mark.parametrize("release_index", (0, 1))
def test_vertical_boarding_bridge_preserves_lane_destination(
    release_index: int,
) -> None:
    model = _model()
    escalator = next(
        item for item in model.vertical_transports if isinstance(item, EscalatorProcessAgent)
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    passenger.pos = escalator._safe_queue_slot(0)
    ride_steps = escalator._ride_steps_from_seconds(None)
    expected_offset = escalator._ride_lateral_offset(
        passenger,
        release_index=release_index,
        release_count=2,
    )

    assert escalator.queue.join(passenger)
    assert escalator.queue.pop(0) is passenger
    escalator._start_passive_ride(
        passenger,
        mode="stand",
        ride_steps=ride_steps,
        release_index=release_index,
        release_count=2,
    )
    ride = escalator.active_rides[0]
    ride.progress_steps = float(ride.total_steps)

    expected = escalator._offset_vertical_position(
        escalator.spec.exit_position,
        expected_offset,
    )
    assert escalator._interpolated_individual_vertical_position(ride) == pytest.approx(expected)
