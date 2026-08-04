from __future__ import annotations

from dataclasses import replace
from math import ceil, hypot

import pytest

from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.facilities.elevator_runtime import (
    ElevatorProcessAgent,
)
from metro_station.adapters.simulation.facilities.escalator_runtime import (
    EscalatorProcessAgent,
)
from metro_station.adapters.simulation.facilities.vertical import (
    ElevatorConfig,
    VerticalFacilityConfig,
)
from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_testkit.instant_movement_backend import InstantMovementBackend


def _model(tick_seconds: int) -> MetroStationModel:
    scenario = StationSandboxScenario(
        station_name="facility_clock_invariance",
        hour=8,
        minutes=1,
        tick_seconds=tick_seconds,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("two_level_island_platform"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    return MetroStationModel(
        scenario,
        seed=37,
        movement_backend=InstantMovementBackend(),
    )


def _passenger(model: MetroStationModel) -> PassengerAgent:
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=model.step_index,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(passenger)
    return passenger


@pytest.mark.parametrize("tick_seconds", [1, 2, 4, 5])
def test_gate_traversal_duration_and_interpolation_are_tick_invariant(
    tick_seconds: int,
) -> None:
    model = _model(tick_seconds)
    gate = model.gates[0]
    passenger = _passenger(model)

    gate._start_service(passenger, None)
    active = gate.active_passes[0]
    event = model.facility_service_events[0]
    expected_duration = (
        (active.end_position[0] - active.start_position[0]) ** 2
        + (active.end_position[1] - active.start_position[1]) ** 2
    ) ** 0.5 / gate._walking_speed_m_s()

    assert event.end_time - event.start_time == pytest.approx(
        expected_duration,
        abs=1e-9,
    )
    assert active.duration_seconds == pytest.approx(expected_duration, abs=1e-9)
    assert active.total_steps == max(1, ceil(expected_duration / tick_seconds))

    gate._advance_active_passes()
    expected_ratio = (
        1.0
        if expected_duration <= 1e-12
        else min(1.0, tick_seconds / expected_duration)
    )
    expected_position = (
        active.start_position[0]
        + (active.end_position[0] - active.start_position[0]) * expected_ratio,
        active.start_position[1]
        + (active.end_position[1] - active.start_position[1]) * expected_ratio,
    )
    assert passenger.pos == pytest.approx(expected_position, abs=1e-9)


def test_gate_follower_waits_body_clear_and_delays_physical_event() -> None:
    model = _model(1)
    gate = model.gates[0]
    leader = _passenger(model)
    follower = _passenger(model)
    service_entry = gate._mechanical_service_entry_position()
    leader.pos = service_entry
    follower.pos = service_entry

    gate._start_service(leader, None, release_index=0)
    gate._advance_active_passes()
    gate._start_service(follower, None, release_index=0)
    follower_event = model.facility_service_events[-1]
    original_end_time = follower_event.end_time
    for _ in range(max(active.total_steps for active in gate.active_passes) + 2):
        gate._advance_active_passes()
        if not gate.has_active_service(leader):
            break
    for _ in range(gate.active_passes[0].total_steps + 2):
        gate._advance_active_passes()
        delayed_event = next(
            event
            for event in model.facility_service_events
            if event.event_id == follower_event.event_id
        )
        if delayed_event.end_time > original_end_time:
            break

    assert not gate.has_active_service(leader)
    assert gate.has_active_service(follower)
    assert hypot(
        leader.pos[0] - follower.pos[0],
        leader.pos[1] - follower.pos[1],
    ) >= gate._release_min_distance() - 1e-9
    assert delayed_event.end_time > original_end_time

    forward, _lateral = gate._release_axes()
    clearance = gate._release_min_distance() * 2.0
    active_follower = gate.active_passes[0]
    # Compiler-certified followers can own a different downstream release
    # cell.  Move the leader beyond the follower's actual cell; advancing from
    # the leader's earlier cell can leave it directly in front of that target
    # and should continue to apply physical backpressure.
    leader.pos = (
        active_follower.end_position[0] + forward[0] * clearance,
        active_follower.end_position[1] + forward[1] * clearance,
    )
    for _ in range(active_follower.total_steps + 2):
        gate._advance_active_passes()
        if not gate.has_active_service(follower):
            break
    assert not gate.active_passes


def test_gate_tick_five_blocking_counts_wall_clock_until_next_boundary() -> None:
    model = _model(5)
    gate = model.gates[0]
    passenger = _passenger(model)
    blocker = _passenger(model)
    passenger.pos = gate._mechanical_service_entry_position()

    gate._start_service(passenger, None, release_index=0)
    active = gate.active_passes[0]
    blocker.current_level_id = gate.spec.exit_level_id or gate.spec.entry_level_id
    blocker.pos = active.end_position
    original_event = model.facility_service_events[-1]
    model.step_index = 1
    gate._advance_active_passes()

    assert gate.has_active_service(passenger)
    delayed_event = next(
        event
        for event in model.facility_service_events
        if event.event_id == original_event.event_id
    )
    assert delayed_event.end_time == pytest.approx(
        model.current_time_seconds
        + model.scenario.tick_seconds
        + active.remaining_seconds,
        abs=1e-9,
    )
    assert delayed_event.end_time > original_event.end_time

    forward, _lateral = gate._release_axes()
    blocker.pos = (
        blocker.pos[0] + forward[0] * gate._release_min_distance() * 2.0,
        blocker.pos[1] + forward[1] * gate._release_min_distance() * 2.0,
    )
    model.step_index = 2
    gate._advance_active_passes()

    assert not gate.active_passes
    assert delayed_event.end_time >= model.current_time_seconds


@pytest.mark.parametrize("tick_seconds", [1, 2, 4, 5])
def test_elevator_surplus_time_dispatches_next_fifo_batch(
    tick_seconds: int,
) -> None:
    model = _model(tick_seconds)
    elevator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
    )
    config = ElevatorConfig(
        batch_capacity=1,
        min_dispatch_persons=1,
        boarding_seconds=0.6,
        travel_seconds=0.7,
        unload_seconds=0.4,
        return_seconds=0.5,
    )
    elevator.spec = replace(
        elevator.spec,
        vertical_config=VerticalFacilityConfig(elevator=config),
    )
    first = _passenger(model)
    second = _passenger(model)
    assert elevator.join_queue(first, authority="goal_graph")
    assert elevator.join_queue(second, authority="goal_graph")
    first.pos = elevator._service_entry_position(0)
    second.pos = elevator._service_entry_position(1)

    elevator._begin_boarding([first], loaded_persons=1)
    second.pos = elevator._service_entry_position(0)
    first_event = model.facility_service_events[0]
    model.step_index = 1

    for _ in range(8):
        if len(model.facility_service_events) >= 2:
            break
        elevator._advance_cabin()
        model.step_index += 1

    assert len(model.facility_service_events) >= 2
    first_event = next(
        event
        for event in model.facility_service_events
        if event.event_id == first_event.event_id
    )
    second_event = model.facility_service_events[1]
    assert first_event.passenger_ids == (int(first.unique_id),)
    assert second_event.passenger_ids == (int(second.unique_id),)
    assert second_event.start_time - first_event.start_time == pytest.approx(
        elevator.effective_cycle_seconds,
        abs=1e-9,
    )
    for event in (first_event, second_event):
        assert event.board_end_time - event.start_time == pytest.approx(
            elevator.effective_boarding_seconds,
            abs=1e-9,
        )
        assert event.arrive_time - event.board_end_time == pytest.approx(0.7, abs=1e-9)
        assert event.end_time - event.arrive_time == pytest.approx(
            elevator.effective_unloading_seconds,
            abs=1e-9,
        )


@pytest.mark.parametrize("tick_seconds", [1, 5])
def test_blocked_elevator_release_keeps_active_ownership_until_retry_succeeds(
    tick_seconds: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model(tick_seconds)
    elevator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
    )
    config = ElevatorConfig(
        batch_capacity=1,
        min_dispatch_persons=1,
        boarding_seconds=0.5,
        travel_seconds=0.5,
        unload_seconds=0.5,
        return_seconds=0.5,
    )
    elevator.spec = replace(
        elevator.spec,
        vertical_config=VerticalFacilityConfig(elevator=config),
    )
    passenger = _passenger(model)
    assert elevator.join_queue(passenger, authority="goal_graph")
    passenger.pos = elevator._service_entry_position(0)
    elevator._begin_boarding([passenger], loaded_persons=1)
    passenger.evacuation_pending = True
    evacuation_activations: list[tuple[int, str]] = []

    def activate_evacuation(active_passenger, *, completed_facility_id: str) -> None:
        evacuation_activations.append(
            (int(active_passenger.unique_id), completed_facility_id)
        )
        active_passenger.evacuation_pending = False

    monkeypatch.setattr(
        model,
        "_activate_passenger_evacuation",
        activate_evacuation,
    )
    event = model.facility_service_events[0]
    original_event_end = event.end_time
    original_configure = elevator._configure_unloading_motion_profile

    def blocked_unloading_profile(*_args, **_kwargs):
        return False

    monkeypatch.setattr(
        elevator,
        "_configure_unloading_motion_profile",
        blocked_unloading_profile,
    )
    elevator.boarding_remaining_seconds = 0.0
    elevator.travel_remaining_seconds = 0.0
    elevator.unload_remaining_seconds = 0.0
    elevator.cabin_state = "unloading"
    elevator._sync_legacy_step_counters()

    for attempt in (1, 2):
        elevator._advance_cabin()
        event = model.facility_service_events[0]
        assert event.end_time == pytest.approx(
            original_event_end + attempt * tick_seconds,
            abs=1e-9,
        )
        assert elevator.cabin_passengers == [passenger]
        assert elevator.cabin_load_persons == 1
        assert elevator.has_active_service(passenger)
        assert passenger.passive_facility_service
        assert passenger.evacuation_pending
        assert elevator.served_persons == 0
        assert int(passenger.unique_id) in elevator.physical_resource.passenger_ids
        assert elevator.active_event_id == event.event_id
        model.step_index += 1

    monkeypatch.setattr(
        elevator,
        "_configure_unloading_motion_profile",
        original_configure,
    )
    elevator._advance_cabin()

    assert elevator.cabin_passengers == []
    assert elevator.cabin_load_persons == 0
    assert not elevator.has_active_service(passenger)
    assert not passenger.passive_facility_service
    assert not passenger.evacuation_pending
    assert elevator.served_persons == 1
    assert int(passenger.unique_id) not in elevator.physical_resource.passenger_ids
    assert elevator.active_event_id is None
    assert len(model.facility_service_events) == 1
    assert evacuation_activations == [
        (int(passenger.unique_id), elevator.facility_id)
    ]


def _snapshot_passenger(model: MetroStationModel, passenger: PassengerAgent) -> dict:
    return next(
        item
        for item in model.frames[-1]["passengers"]
        if item["id"] == int(passenger.unique_id)
    )


def test_horizon_finalization_preserves_in_progress_gate_pass() -> None:
    model = _model(1)
    gate = model.gates[0]
    passenger = _passenger(model)
    passenger.pos = gate._service_entry_position(0)
    model.step_index = 58
    gate._start_service(passenger, None)
    event = model.facility_service_events[0]
    model.step_index = 59
    gate._advance_active_passes()
    model.step_index = 60
    position_at_horizon = passenger.pos
    served_at_horizon = gate.served_persons
    model.frames = [model.snapshot()]

    model._finalize_facilities()

    assert event.end_time > 60.0
    assert gate.served_persons == served_at_horizon == 0
    assert len(gate.active_passes) == 1
    assert passenger.passive_facility_service
    assert passenger.pos == position_at_horizon
    final = _snapshot_passenger(model, passenger)
    assert (final["x"], final["y"]) == pytest.approx(position_at_horizon, abs=1e-3)


def test_horizon_finalization_preserves_in_progress_vertical_ride() -> None:
    model = _model(1)
    escalator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, EscalatorProcessAgent)
    )
    passenger = _passenger(model)
    passenger.pos = escalator.spec.queue_layout.slot(0)
    assert escalator.queue.join(passenger)
    assert escalator.queue.pop(0) is passenger
    model.step_index = 58
    escalator._start_service(passenger, None)
    event = model.facility_service_events[0]
    model.step_index = 59
    escalator._advance_active_rides()
    model.step_index = 60
    position_at_horizon = passenger.pos
    model.frames = [model.snapshot()]

    model._finalize_facilities()

    assert event.end_time > 60.0
    assert escalator.served_persons == 0
    assert len(escalator.active_rides) == 1
    assert passenger.passive_facility_service
    assert passenger.pos == position_at_horizon
    final = _snapshot_passenger(model, passenger)
    assert (final["x"], final["y"]) == pytest.approx(position_at_horizon, abs=1e-3)


def test_horizon_finalization_preserves_in_progress_elevator_phase() -> None:
    model = _model(1)
    elevator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
    )
    passenger = _passenger(model)
    assert elevator.join_queue(passenger, authority="goal_graph")
    passenger.pos = elevator._service_entry_position(0)
    model.step_index = 58
    elevator._begin_boarding([passenger], loaded_persons=1)
    event = model.facility_service_events[0]
    model.step_index = 59
    elevator._advance_cabin()
    model.step_index = 60
    position_at_horizon = passenger.pos
    state_at_horizon = elevator.cabin_state
    remaining_at_horizon = (
        elevator.boarding_remaining_seconds,
        elevator.travel_remaining_seconds,
        elevator.unload_remaining_seconds,
    )
    model.frames = [model.snapshot()]

    model._finalize_facilities()

    assert event.end_time > 60.0
    assert elevator.served_persons == 0
    assert elevator.cabin_passengers == [passenger]
    assert elevator.cabin_load_persons == 1
    assert elevator.cabin_state == state_at_horizon
    assert (
        elevator.boarding_remaining_seconds,
        elevator.travel_remaining_seconds,
        elevator.unload_remaining_seconds,
    ) == remaining_at_horizon
    assert passenger.passive_facility_service
    assert passenger.pos == position_at_horizon
    final = _snapshot_passenger(model, passenger)
    assert (final["x"], final["y"]) == pytest.approx(position_at_horizon, abs=1e-3)
