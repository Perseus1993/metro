from __future__ import annotations

from dataclasses import replace
from itertools import combinations
from math import ceil

import pytest

from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.facilities.elevator_runtime import ElevatorProcessAgent
from metro_station.adapters.simulation.facilities.escalator_runtime import (
    EscalatorProcessAgent,
)
from metro_station.adapters.simulation.facilities.stairs_runtime import StairsProcessAgent
from metro_station.adapters.simulation.facilities.vertical import (
    ElevatorConfig,
    EscalatorConfig,
    VerticalFacilityConfig,
)
from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_testkit.instant_movement_backend import InstantMovementBackend


def _model(
    *,
    tick_seconds: int = 1,
    layout_id: str = "two_level_island_platform",
) -> MetroStationModel:
    scenario = StationSandboxScenario(
        station_name="elevator_pose_test",
        hour=8,
        minutes=1,
        tick_seconds=tick_seconds,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design(layout_id),
        elevator_cabin_capacity_persons=6,
        elevator_min_dispatch_persons=1,
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    return MetroStationModel(scenario, seed=13, movement_backend=InstantMovementBackend())


def _relative_positions(
    passengers: list[PassengerAgent],
) -> dict[tuple[int, int], tuple[float, float]]:
    return {
        (int(left.unique_id), int(right.unique_id)): (
            right.pos[0] - left.pos[0],
            right.pos[1] - left.pos[1],
        )
        for left, right in combinations(passengers, 2)
    }


def test_elevator_batch_preserves_distinct_rigid_body_poses() -> None:
    model = _model()
    elevator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
    )
    passenger_count = min(6, int(elevator.queue.max_length or 6))
    passengers = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        for _ in range(passenger_count)
    ]
    model.passengers.extend(passengers)
    for index, passenger in enumerate(passengers):
        assert elevator.join_queue(passenger, authority="goal_graph")
        passenger.pos = elevator._service_entry_position(index)

    queue_positions = [passenger.pos for passenger in passengers]
    elevator._begin_boarding(passengers, loaded_persons=passenger_count)

    # Boarding starts from each passenger's actual queue pose.  Beginning a
    # batch must not snap the full group into the cabin in one frame.
    assert [passenger.pos for passenger in passengers] == queue_positions
    boarding_seconds = elevator._elevator_config.boarding_seconds
    for step in range(1, 41):
        ratio = step / 40.0
        elevator.boarding_remaining_seconds = boarding_seconds * (1.0 - ratio)
        elevator._sync_legacy_step_counters()
        elevator._update_boarding_positions()
        minimum_boarding_distance = min(
            (
                (left.pos[0] - right.pos[0]) ** 2
                + (left.pos[1] - right.pos[1]) ** 2
            )
            ** 0.5
            for left, right in combinations(passengers, 2)
        )
        assert minimum_boarding_distance >= elevator._release_min_distance() - 1e-9

    cabin_positions = [passenger.pos for passenger in passengers]
    assert len(set(cabin_positions)) == len(passengers)
    minimum_distance = min(
        ((left.pos[0] - right.pos[0]) ** 2 + (left.pos[1] - right.pos[1]) ** 2) ** 0.5
        for left, right in combinations(passengers, 2)
    )
    assert minimum_distance >= 0.39
    cabin_relatives = _relative_positions(passengers)

    midpoint = elevator._interpolated_vertical_position(1, 2)
    elevator._set_cabin_positions(midpoint)

    moved_relatives = _relative_positions(passengers)
    for pair, relative in cabin_relatives.items():
        assert moved_relatives[pair] == pytest.approx(relative, abs=1e-9)


def test_elevator_dispatch_uses_largest_feasible_fifo_prefix(monkeypatch) -> None:
    model = _model()
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
        for _ in range(4)
    ]
    attempted_sizes: list[int] = []

    def plan(candidate):
        attempted_sizes.append(len(candidate))
        if len(candidate) > 2:
            raise RuntimeError("synthetic cabin geometry limit")
        return {int(passenger.unique_id): (0.0, 0.0) for passenger in candidate}

    monkeypatch.setattr(elevator, "_plan_cabin_offsets", plan)

    prefix, geometry_limited = elevator._largest_feasible_boarding_prefix(passengers)

    assert attempted_sizes == [4, 3, 2]
    assert prefix == passengers[:2]
    assert geometry_limited
    assert not elevator._should_wait_for_boarders(
        loaded_persons=2,
        blocked_by_unready=False,
        geometry_limited=True,
        force=False,
    )


def test_opposite_elevator_facades_share_one_exclusive_physical_connector() -> None:
    model = _model()
    by_source: dict[str, list] = {}
    for facility in model.vertical_transports:
        if isinstance(facility, ElevatorProcessAgent):
            by_source.setdefault(str(facility.spec.source_element_id), []).append(facility)
    opposing = next(items for items in by_source.values() if len(items) == 2)
    first, second = opposing

    assert first.physical_resource is second.physical_resource
    assert first.physical_resource.acquire(first.facility_id, (101,))
    assert first.is_open
    assert second.is_open
    assert not second.can_start_physical_service
    assert not second.physical_resource.acquire(second.facility_id, (202,))

    assert first.physical_resource.retain(first.facility_id)
    first.physical_resource.release(first.facility_id, (101,))
    assert second.is_open
    assert not second.can_start_physical_service
    assert not second.physical_resource.acquire(second.facility_id, (202,))

    first.physical_resource.release_retention(first.facility_id)
    assert second.can_start_physical_service
    assert second.physical_resource.acquire(second.facility_id, (202,))


def test_reasserting_existing_queue_ownership_is_side_effect_free() -> None:
    model = _model()
    elevator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(passenger)

    assert elevator.join_queue(passenger, authority="goal_graph")
    event_count = len(model.goal_parity.events)
    assert elevator.join_queue(passenger, authority="goal_graph")

    assert elevator.queue == [passenger]
    assert len(model.goal_parity.events) == event_count


def test_opposite_escalator_waits_without_queue_handoff_or_duplicate_join() -> None:
    model = _model(layout_id="three_level_transfer")
    by_source: dict[str, list[EscalatorProcessAgent]] = {}
    for facility in model.vertical_transports:
        if isinstance(facility, EscalatorProcessAgent):
            by_source.setdefault(str(facility.spec.source_element_id), []).append(facility)
    active, waiting = next(items for items in by_source.values() if len(items) == 2)
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    model.passengers.append(passenger)
    assert waiting.join_queue(passenger, authority="goal_graph")
    passenger.pos = waiting._service_entry_position(0)
    waiting.service_credit = 1.0
    queue_event_count = len(model.goal_parity.events)
    assert active.physical_resource.acquire(active.facility_id, (101,))

    waiting.step()

    assert waiting.queue == [passenger]
    assert waiting.active_rides == []
    assert len(model.goal_parity.events) == queue_event_count
    assert waiting.physical_resource.waiting_facility_ids == [waiting.facility_id]

    active.physical_resource.release(active.facility_id, (101,))
    for _ in range(20):
        if waiting._passenger_at_mechanical_entry(passenger):
            break
        waiting._layout_queue()
        passenger.move_directly_toward_target()
    assert waiting._passenger_at_mechanical_entry(passenger)
    waiting.step()

    assert waiting.queue == []
    assert [ride.passenger for ride in waiting.active_rides] == [passenger]
    assert waiting.physical_resource.active_facility_id == waiting.facility_id


def test_stale_escalator_waiter_withdraws_when_queue_head_leaves_entry() -> None:
    model = _model(layout_id="three_level_transfer")
    by_source: dict[str, list[EscalatorProcessAgent]] = {}
    for facility in model.vertical_transports:
        if isinstance(facility, EscalatorProcessAgent):
            by_source.setdefault(str(facility.spec.source_element_id), []).append(facility)
    active, stale = next(items for items in by_source.values() if len(items) == 2)

    stale_passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    model.passengers.append(stale_passenger)
    assert stale.join_queue(stale_passenger, authority="goal_graph")
    stale_passenger.pos = stale.spec.queue_layout.slot(0)
    stale.service_credit = 1.0
    assert active.physical_resource.acquire(active.facility_id, (101,))
    stale.step()
    assert stale.physical_resource.waiting_facility_ids == [stale.facility_id]

    # The request loses its lease as soon as the queue head is no longer at
    # the mechanical entry.  Keeping it would block a ready opposite facade
    # even after the physical resource becomes idle.
    stale_entry = stale.spec.queue_layout.slot(0)
    stale_passenger.pos = (stale_entry[0] + 10.0, stale_entry[1] + 10.0)
    active_passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(active_passenger)
    assert active.join_queue(active_passenger, authority="goal_graph")
    active_passenger.pos = active.spec.queue_layout.slot(0)
    active.service_credit = 1.0
    active.physical_resource.release(active.facility_id, (101,))

    stale.step()
    active.step()

    assert stale.facility_id not in stale.physical_resource.waiting_facility_ids
    assert [ride.passenger for ride in active.active_rides] == [active_passenger]
    assert active.physical_resource.active_facility_id == active.facility_id


def test_opposite_elevator_waits_and_retries_when_dispatch_timer_expires() -> None:
    model = _model()
    by_source: dict[str, list[ElevatorProcessAgent]] = {}
    for facility in model.vertical_transports:
        if isinstance(facility, ElevatorProcessAgent):
            by_source.setdefault(str(facility.spec.source_element_id), []).append(facility)
    active, waiting = next(items for items in by_source.values() if len(items) == 2)
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    model.passengers.append(passenger)
    assert waiting.join_queue(passenger, authority="goal_graph")
    passenger.pos = waiting._service_entry_position(0)
    waiting.cabin_state = "waiting"
    waiting.boarding_wait_remaining_seconds = 0.0
    waiting._sync_legacy_step_counters()
    assert active.physical_resource.acquire(active.facility_id, (101,))
    assert active.physical_resource.retain(active.facility_id)

    waiting._advance_cabin()

    assert waiting.cabin_state == "waiting"
    assert waiting.queue == [passenger]
    assert waiting.cabin_passengers == []
    assert passenger.passive_facility_service is False

    active.physical_resource.release(active.facility_id, (101,))
    active.physical_resource.release_retention(active.facility_id)
    waiting._advance_cabin()

    assert waiting.cabin_state == "boarding"
    assert waiting.queue == []
    assert waiting.cabin_passengers == [passenger]
    assert waiting.physical_resource.active_facility_id == waiting.facility_id


def test_shared_elevator_dispatch_does_not_starve_opposite_direction() -> None:
    model = _model(tick_seconds=1)
    elevators = [
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
        and facility.spec.source_element_id == "elevator_a"
    ]
    assert [facility.spec.direction for facility in elevators] == ["down", "up"]
    down, up = elevators
    config = ElevatorConfig(
        batch_capacity=1,
        min_dispatch_persons=1,
        boarding_seconds=1,
        travel_seconds=1,
        unload_seconds=1,
        return_seconds=1,
    )
    for elevator in elevators:
        elevator.spec = replace(
            elevator.spec,
            vertical_config=VerticalFacilityConfig(elevator=config),
        )

    def enqueue(elevator: ElevatorProcessAgent, intent: AgentIntent) -> None:
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=model.step_index,
            intent=intent,
        )
        model.passengers.append(passenger)
        assert elevator.join_queue(passenger, authority="goal_graph")

    demand_count = min(
        6,
        int(down.queue.max_length or 6),
        int(up.queue.max_length or 6),
    )
    assert demand_count >= 2
    for _ in range(demand_count):
        enqueue(down, AgentIntent.ENTER_AND_BOARD)
        enqueue(up, AgentIntent.EXIT_STATION)

    first_up_service_step: int | None = None
    for step_index in range(80):
        for elevator in elevators:
            for index, passenger in enumerate(elevator.queue):
                passenger.pos = elevator._service_entry_position(index)
        for elevator in elevators:
            elevator.step()
        model.step_index += 1
        active_passengers = {
            id(passenger)
            for elevator in elevators
            for passenger in (*elevator.queue, *elevator.cabin_passengers)
        }
        model.passengers[:] = [
            passenger
            for passenger in model.passengers
            if id(passenger) in active_passengers
        ]

        cabin_owners = [
            elevator.facility_id
            for elevator in elevators
            if elevator.cabin_state in {"boarding", "moving", "unloading", "returning"}
        ]
        assert len(cabin_owners) <= 1
        assert down.physical_resource.passenger_ids == {
            int(passenger.unique_id)
            for elevator in elevators
            for passenger in elevator.cabin_passengers
        }
        if up.served_persons and first_up_service_step is None:
            first_up_service_step = step_index
        if all(
            not elevator.queue
            and not elevator.cabin_passengers
            and elevator.cabin_state == "idle"
            for elevator in elevators
        ):
            break
    else:
        pytest.fail("shared elevator did not drain both FIFO queues within 80 ticks")
    assert down.served_persons == demand_count
    assert up.served_persons == demand_count
    assert abs(down.served_persons - up.served_persons) <= 1
    assert first_up_service_step is not None
    assert first_up_service_step <= 12
    event_ids = [event.event_id for event in model.facility_service_events]
    passenger_ids = [event.passenger_ids[0] for event in model.facility_service_events]
    assert len(event_ids) == len(set(event_ids))
    assert len(passenger_ids) == len(set(passenger_ids))


@pytest.mark.parametrize("tick_seconds", [1, 5])
def test_disabling_waiting_elevator_withdraws_before_owner_release(
    tick_seconds: int,
) -> None:
    model = _model(tick_seconds=tick_seconds)
    elevators = [
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
        and facility.spec.source_element_id == "elevator_a"
    ]
    down, up = elevators
    config = ElevatorConfig(
        batch_capacity=1,
        min_dispatch_persons=1,
        boarding_seconds=1,
        travel_seconds=1,
        unload_seconds=1,
        return_seconds=1,
    )
    for elevator in elevators:
        elevator.spec = replace(
            elevator.spec,
            vertical_config=VerticalFacilityConfig(elevator=config),
        )

    def enqueue(elevator: ElevatorProcessAgent, intent: AgentIntent) -> None:
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=model.step_index,
            intent=intent,
        )
        model.passengers.append(passenger)
        assert elevator.join_queue(passenger, authority="goal_graph")
        passenger.pos = elevator._service_entry_position(len(elevator.queue) - 1)

    enqueue(down, AgentIntent.ENTER_AND_BOARD)
    enqueue(down, AgentIntent.ENTER_AND_BOARD)
    enqueue(up, AgentIntent.EXIT_STATION)
    down.step()
    up.step()
    assert up.facility_id in up.physical_resource.waiting_facility_ids

    model.disruption_controller.dynamic_disabled_ids.add(up.facility_id)
    up.on_availability_changed(
        disabled=True,
        time_seconds=float(model.current_time_seconds),
    )

    assert up.facility_id not in up.physical_resource.waiting_facility_ids
    for _ in range(6):
        for index, passenger in enumerate(down.queue):
                passenger.pos = down._service_entry_position(index)
        down.step()
        up.step()
        model.step_index += 1

    down_events = [
        event
        for event in model.facility_service_events
        if event.facility_id == down.facility_id
    ]
    assert len(down_events) == 2
    assert all(event.facility_id != up.facility_id for event in model.facility_service_events)


def test_blocking_escalator_immediately_withdraws_dispatch_request() -> None:
    model = _model(layout_id="three_level_transfer")
    escalator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, EscalatorProcessAgent)
    )
    escalator.physical_resource.request(escalator.facility_id)

    escalator.set_mode("blocked")

    assert escalator.facility_id not in escalator.physical_resource.waiting_facility_ids


def test_opposite_stairs_keep_parallel_directional_capacity() -> None:
    model = _model()
    by_source: dict[str, list[StairsProcessAgent]] = {}
    for facility in model.vertical_transports:
        if isinstance(facility, StairsProcessAgent):
            by_source.setdefault(str(facility.spec.source_element_id), []).append(facility)
    first, second = next(items for items in by_source.values() if len(items) == 2)

    assert first.physical_resource is not second.physical_resource
    assert first.is_open
    assert second.is_open


def test_vertical_travel_duration_is_stable_across_process_tick_sizes() -> None:
    fine_model = _model(tick_seconds=1)
    coarse_model = _model(tick_seconds=5)
    fine = next(
        facility
        for facility in fine_model.vertical_transports
        if isinstance(facility, StairsProcessAgent) and facility.spec.direction == "down"
    )
    coarse = next(
        facility
        for facility in coarse_model.vertical_transports
        if isinstance(facility, StairsProcessAgent) and facility.spec.direction == "down"
    )

    fine_duration_s = fine._ride_duration_seconds(None)
    coarse_duration_s = coarse._ride_duration_seconds(None)

    assert coarse_duration_s == pytest.approx(fine_duration_s, abs=1e-9)
    assert fine.travel_speed_units_per_tick == pytest.approx(fine.travel_speed_m_s)
    assert coarse.travel_speed_units_per_tick == pytest.approx(
        coarse.travel_speed_m_s * coarse_model.scenario.tick_seconds
    )


@pytest.mark.parametrize("tick_seconds", [1, 2, 4, 5])
def test_elevator_physical_phase_boundaries_are_tick_invariant(
    tick_seconds: int,
) -> None:
    model = _model(tick_seconds=tick_seconds)
    elevator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
    )
    config = ElevatorConfig(
        batch_capacity=2,
        min_dispatch_persons=1,
        boarding_seconds=3.25,
        travel_seconds=7.5,
        unload_seconds=2.75,
        return_seconds=4.5,
    )
    elevator.spec = replace(
        elevator.spec,
        vertical_config=VerticalFacilityConfig(elevator=config),
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(passenger)
    assert elevator.join_queue(passenger, authority="goal_graph")
    passenger.pos = elevator._service_entry_position(0)

    elevator._begin_boarding([passenger], loaded_persons=1)
    event = model.facility_service_events[0]

    # Vertical service ownership commits at the process callback boundary;
    # the first published pose is one physical interval later.
    assert event.commit_time == pytest.approx(model.current_time_seconds, abs=1e-9)
    assert event.start_time - event.commit_time == pytest.approx(
        tick_seconds,
        abs=1e-9,
    )
    assert event.board_end_time - event.start_time == pytest.approx(3.25, abs=1e-9)
    assert event.arrive_time - event.board_end_time == pytest.approx(7.5, abs=1e-9)
    assert event.end_time - event.arrive_time == pytest.approx(2.75, abs=1e-9)

    # A coarse process interval may cross several phase boundaries.  Its
    # unused physical seconds must advance the next phase rather than vanish.
    elevator._advance_cabin()
    consumed = float(tick_seconds)
    assert elevator.boarding_remaining_seconds == pytest.approx(
        max(0.0, 3.25 - consumed),
        abs=1e-9,
    )
    expected_travel_remaining = 7.5 - max(0.0, consumed - 3.25)
    assert elevator.travel_remaining_seconds == pytest.approx(
        max(0.0, expected_travel_remaining),
        abs=1e-9,
    )
    active_service_seconds = 3.25 + 7.5 + 2.75
    remaining_calls = ceil(
        max(0.0, active_service_seconds - float(tick_seconds)) / tick_seconds
    )
    for _ in range(remaining_calls):
        elevator._advance_cabin()
    assert elevator.cabin_passengers == []
    assert passenger.passive_facility_service is False
    assert elevator.served_persons == 1


@pytest.mark.parametrize("tick_seconds", [1, 2, 4, 5])
def test_escalator_event_duration_and_commit_are_tick_invariant(
    tick_seconds: int,
) -> None:
    model = _model(tick_seconds=tick_seconds)
    escalator = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, EscalatorProcessAgent)
    )
    config = EscalatorConfig(ride_time_seconds=7.3)
    escalator.spec = replace(
        escalator.spec,
        vertical_config=VerticalFacilityConfig(escalator=config),
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(passenger)
    passenger.pos = escalator.spec.queue_layout.slot(0)
    assert escalator.queue.join(passenger)
    assert escalator.queue.pop(0) is passenger

    escalator._start_service(passenger, None)
    event = model.facility_service_events[0]
    ride = escalator.active_rides[0]

    # The process owns the rider at the callback boundary; the first published
    # pose is one physical interval later.  Faults at that later boundary must
    # therefore preserve the already-committed ride.
    assert event.commit_time == pytest.approx(model.current_time_seconds, abs=1e-9)
    assert event.start_time - event.commit_time == pytest.approx(
        tick_seconds,
        abs=1e-9,
    )
    assert event.end_time - event.start_time == pytest.approx(7.3, abs=1e-9)
    assert ride.duration_seconds == pytest.approx(7.3, abs=1e-9)


@pytest.mark.parametrize("tick_seconds", [1, 2, 4, 5])
def test_stairs_event_duration_and_commit_are_tick_invariant(
    tick_seconds: int,
) -> None:
    model = _model(tick_seconds=tick_seconds)
    stairs = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, StairsProcessAgent) and facility.spec.direction == "down"
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(passenger)
    passenger.pos = stairs._service_entry_position(0)
    expected_duration = stairs._ride_duration_seconds(None)

    stairs._start_service(passenger, None)
    event = model.facility_service_events[0]
    ride = stairs.active_rides[0]

    assert event.commit_time == pytest.approx(model.current_time_seconds, abs=1e-9)
    assert event.start_time - event.commit_time == pytest.approx(
        tick_seconds,
        abs=1e-9,
    )
    assert event.end_time - event.start_time == pytest.approx(
        expected_duration,
        abs=1e-9,
    )
    assert ride.duration_seconds == pytest.approx(expected_duration, abs=1e-9)
