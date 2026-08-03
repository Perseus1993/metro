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
from metro_station.adapters.simulation.facilities.process import FacilityKind, QueueLayout
from metro_station.adapters.simulation.facilities.stairs_runtime import StairsProcessAgent
from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.layout_queue_geometry import (
    _queue_layout_behind_service_entry,
    _queue_layout_with_service_entry_slot,
)
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_testkit.instant_movement_backend import InstantMovementBackend


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


def test_arrival_from_walking_has_one_full_queue_reaction_interval() -> None:
    model = _model()
    escalator = next(
        item
        for item in model.vertical_transports
        if isinstance(item, EscalatorProcessAgent)
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
        item
        for item in model.vertical_transports
        if isinstance(item, EscalatorProcessAgent)
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


def test_continuous_vertical_release_rejects_a_swept_path_through_a_hole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model()
    escalator = next(
        item
        for item in model.vertical_transports
        if isinstance(item, EscalatorProcessAgent)
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
        item
        for item in model.vertical_transports
        if isinstance(item, EscalatorProcessAgent)
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
        item
        for item in model.vertical_transports
        if isinstance(item, EscalatorProcessAgent)
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
        item
        for item in model.vertical_transports
        if isinstance(item, EscalatorProcessAgent)
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
    leader_ride.progress_steps = (
        leader_ride.total_steps * leader_ride.elapsed_seconds / duration
    )
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
    assert level_events[0].time_seconds == pytest.approx(
        model.facility_service_events[-1].end_time
    )


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
        item
        for item in model.vertical_transports
        if isinstance(item, EscalatorProcessAgent)
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
        item
        for item in model.vertical_transports
        if isinstance(item, EscalatorProcessAgent)
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
            assert hypot(
                slots[0][0] - facility.spec.position[0],
                slots[0][1] - facility.spec.position[1],
            ) >= facility._release_min_distance() - 1e-9
        else:
            assert slots[0] == pytest.approx(facility.spec.position)
        if facility.spec.kind in {FacilityKind.STAIRS.value, FacilityKind.ESCALATOR.value}:
            assert facility.queue.max_length == len(slots) - 1
        else:
            assert facility.queue.max_length == len(slots)
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
        -(
            (point[0] - service[0]) * forward[0]
            + (point[1] - service[1]) * forward[1]
        )
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
    with pytest.raises(RuntimeError, match="no reservable queue slot"):
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
        model._reserve_facility_approach_slot(passenger, facility)
        for passenger in passengers[:-1]
    ]
    targets = [facility.spec.queue_layout.slot(index) for index in reserved]

    assert len(set(reserved)) == len(reserved)
    assert len(set(targets)) == len(targets)
    assert 0 not in reserved
    assert all(
        hypot(
            target[0] - facility.spec.position[0],
            target[1] - facility.spec.position[1],
        )
        >= 1.0
        for target in targets
    )
    assert not model.facility_has_reservable_approach_slot(passengers[-1], facility)


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
    assert facility.queue.approach_slot_reservation(
        int(historical.unique_id)
    ) == historical_index
    assert [
        passenger.facility_approach_slots_by_stage[stage] for passenger in current
    ] == list(reversed(cohort_indices))
    for passenger in (historical, *current):
        passenger_id = int(passenger.unique_id)
        index = passenger.facility_approach_slots_by_stage[stage]
        assert facility.queue.approach_slot_reservation(passenger_id) == index
        assert model._facility_targeting_slot_indices[facility.facility_id][
            passenger_id
        ] == index
        assert model._facility_approach_reservation_registry[
            (passenger_id, stage)
        ].slot_index == index

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


def test_all_compiled_approach_portals_are_body_clear_after_safe_projection() -> None:
    model = _model()
    minimum_separation = max(
        model.scenario.jupedsim_agent_radius_units
        * model.scenario.jupedsim_clearance_multiplier,
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
            hypot(left[0] - right[0], left[1] - right[1])
            >= minimum_separation - 1e-7
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
        model._reserve_facility_approach_slot(passenger, facility)
        for passenger in passengers
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


def test_physically_inverted_arrival_waits_outside_then_makes_progress() -> None:
    model = _model()
    slot0, slot1 = model.gates[0].spec.queue_layout.slots[:2]
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


def test_approach_portals_fail_closed_without_a_stable_entry_level() -> None:
    model = _model()
    facility = model.vertical_transports[0]
    facility.spec = replace(facility.spec, entry_level_id=None)

    assert model._facility_approach_slot_indices(facility) == ()


def test_approach_portals_fail_closed_when_entry_level_geometry_is_unknown() -> None:
    model = _model()
    facility = model.vertical_transports[0]
    assert model._facility_approach_slot_indices(facility)
    facility.spec = replace(facility.spec, entry_level_id="unknown_level")

    assert model._facility_approach_slot_indices(facility) == ()


def test_approach_portals_recompute_when_area_provider_fails(monkeypatch) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    assert model._facility_approach_slot_indices(facility)
    monkeypatch.setattr(
        model,
        "jupedsim_walkable_area",
        lambda _level_id=None: (_ for _ in ()).throw(RuntimeError("projection failed")),
    )

    assert model._facility_approach_slot_indices(facility) == ()


def test_approach_portals_recompute_when_projection_implementation_changes(monkeypatch) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    assert model._facility_approach_slot_indices(facility)
    monkeypatch.setattr(
        model,
        "_project_facility_approach_point",
        lambda _facility, _point, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("projection failed")
        ),
    )

    assert model._facility_approach_slot_indices(facility) == ()


def test_approach_portals_recompute_bottom_level_projection_dependency(monkeypatch) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    assert model._facility_approach_slot_indices(facility)
    monkeypatch.setattr(
        facility_queue_routing_module,
        "project_to_safe_point",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("projection failed")),
    )

    assert model._facility_approach_slot_indices(facility) == ()


def test_approach_portals_recompute_when_facility_semantics_change() -> None:
    model = _model()
    facility = model.vertical_transports[0]
    vertical_indices = model._facility_approach_slot_indices(facility)
    facility.spec = replace(facility.spec, kind="gate")

    gate_indices = model._facility_approach_slot_indices(facility)

    assert 0 not in vertical_indices
    assert 0 in gate_indices
    assert len(gate_indices) > len(vertical_indices)


def test_raw_and_projected_approach_portals_are_both_body_clear(monkeypatch) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    service = facility.spec.position
    raw_first = (service[0] + 1.2, service[1])
    raw_second = (service[0] + 1.5, service[1])
    facility.spec = replace(
        facility.spec,
        queue_layout=QueueLayout(
            anchor=service,
            per_row=1,
            col_step=(0.0, 0.0),
            row_step=(0.8, 0.0),
            slots=(service, raw_first, raw_second),
        ),
    )
    monkeypatch.setattr(
        model,
        "_project_facility_approach_point",
        lambda _facility, point, **_kwargs: (point[0] * 10.0, point[1] * 10.0),
    )

    assert model._facility_approach_slot_indices(facility) == (1,)


def test_approach_proof_uses_one_area_snapshot_and_memoizes_success(monkeypatch) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    original_area_provider = model.jupedsim_walkable_area
    area_call_count = 0

    def counted_area(level_id=None):
        nonlocal area_call_count
        area_call_count += 1
        return original_area_provider(level_id)

    monkeypatch.setattr(model, "jupedsim_walkable_area", counted_area)

    first = model._facility_approach_slot_indices(facility)
    calls_after_first = area_call_count
    second = model._facility_approach_slot_indices(facility)

    assert first == second
    assert calls_after_first == 1
    assert area_call_count == 2


def test_explicit_projection_revision_invalidates_mutable_dependency(monkeypatch) -> None:
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
    assert model._facility_approach_slot_indices(facility)

    projector.failing = True
    model.invalidate_facility_approach_proofs()

    assert model._facility_approach_slot_indices(facility) == ()


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
    assert not model.facility_has_reservable_approach_slot(passenger, facility)
    with pytest.raises(RuntimeError, match="no reservable queue slot"):
        model._reserve_facility_approach_slot(passenger, facility)


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


def test_missing_demand_copy_cannot_duplicate_fallback_approach_slot() -> None:
    model = _model()
    facility = model.vertical_transports[0]
    layout = QueueLayout(
        anchor=facility.spec.position,
        per_row=1,
        col_step=(0.0, 0.0),
        row_step=(0.8, 0.0),
    )
    facility.spec = replace(facility.spec, queue_layout=layout)
    facility.queue = FacilityQueue(layout, max_length=1)
    first, second = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EVACUATE_STATION,
        )
        for _ in range(2)
    ]

    assert model._reserve_facility_approach_slot(first, facility) == 0
    del model._facility_targeting_reservations[facility.facility_id][
        int(first.unique_id)
    ]

    # A partially written reservation is revoked and recreated; it is never
    # accepted merely because the passenger and slot-index copies still agree.
    assert model._reserve_facility_approach_slot(first, facility) == 0
    with pytest.raises(RuntimeError, match="no reservable queue slot"):
        model._reserve_facility_approach_slot(second, facility)
    assert facility.queue.approach_slot_reservations == ((int(first.unique_id), 0),)
    assert model.facility_targeting_persons(facility) == 1


def test_proof_invalidation_sweeps_union_when_slot_index_copy_is_missing(
    monkeypatch,
) -> None:
    model = _model()
    facility = model.vertical_transports[0]
    layout = QueueLayout(
        anchor=facility.spec.position,
        per_row=1,
        col_step=(0.0, 0.0),
        row_step=(0.8, 0.0),
    )
    facility.spec = replace(facility.spec, queue_layout=layout)
    facility.queue = FacilityQueue(layout, max_length=1)
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    model.passengers.append(passenger)
    assert model._reserve_facility_approach_slot(passenger, facility) == 0
    del model._facility_targeting_slot_indices[facility.facility_id][
        int(passenger.unique_id)
    ]
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
    gate = model.gates[0]
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
    gate = model.gates[0]
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
    gate = model.gates[0]
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
                vertical.facility_id
                if corrupted_field == "facility_id"
                else vertical.queue
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
    gate = model.gates[0]
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
    gate = model.gates[0]
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
    assert queue.settling_motion_fraction(passenger) == pytest.approx(
        expected_first_fraction
    )
    if tick_seconds <= 1.0:
        model.current_time_seconds = arrival_time + 1.0 - tick_seconds
        assert queue.is_settling(passenger)
    model.current_time_seconds = arrival_time + 1.0
    assert not queue.is_settling(passenger)


def test_queue_compaction_dwells_before_reversing_direction() -> None:
    model = _model()
    gate = model.gates[0]
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
        item
        for item in model.vertical_transports
        if isinstance(item, EscalatorProcessAgent)
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
    assert escalator._interpolated_individual_vertical_position(ride) == pytest.approx(
        expected
    )
