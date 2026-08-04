from __future__ import annotations

from math import hypot

import pytest

from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.facilities.elevator_runtime import (
    ElevatorProcessAgent,
)
from metro_station.adapters.simulation.planning.plan import AgentIntent, AgentState
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_acceptance.generated_trajectory_gate import (
    _trajectory_authority_coverage,
)
from metro_station_testkit.metamorphic_bases import generate_metamorphic_base


def _model(
    *,
    tick_seconds: int = 1,
    radius: float = 0.18,
    document=None,
) -> MetroStationModel:
    scenario = StationSandboxScenario(
        station_name="elevator_native_landing_test",
        hour=8,
        minutes=1,
        tick_seconds=tick_seconds,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=(
            create_design("visual_demo_station") if document is None else document
        ),
        jupedsim_agent_radius_units=radius,
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=99)
    if not model.jupedsim.status.available:
        pytest.skip(model.jupedsim.status.message)
    return model


def _elevator(model: MetroStationModel) -> ElevatorProcessAgent:
    return next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
    )


def _place_rider(
    model: MetroStationModel,
    elevator: ElevatorProcessAgent,
    *,
    start_time: float | None = 0.0,
) -> PassengerAgent:
    rider = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(rider)
    rider.current_level_id = elevator.portal_entry_level_id
    entry = elevator._service_entry_position(0)
    rider.pos = model.movement_backend.place_passenger(
        rider,
        entry,
        target=entry,
        level_id=rider.current_level_id,
    )
    assert elevator.queue.join(rider)
    elevator._begin_boarding(
        [rider],
        loaded_persons=1,
        start_time=start_time,
    )
    return rider


def _place_walker(
    model: MetroStationModel,
    *,
    level_id: str,
    start: tuple[float, float],
    target: tuple[float, float],
) -> PassengerAgent:
    walker = PassengerAgent(
        model,
        group_size=1,
        created_step=model.step_index,
        intent=AgentIntent.EXIT_STATION,
    )
    model.passengers.append(walker)
    walker.current_level_id = level_id
    walker.state = AgentState.WALKING_TO_EXIT_GATE.value
    walker.pos = model.movement_backend.place_passenger(
        walker,
        start,
        target=target,
        level_id=level_id,
    )
    walker.target = target
    walker.route = []
    return walker


def _advance_native_tick(
    model: MetroStationModel,
    elevator: ElevatorProcessAgent,
) -> dict[int, tuple[str | None, int]]:
    elevator._advance_cabin(elapsed_seconds=float(model.scenario.tick_seconds))
    movement_results = model.movement_backend.step_all(list(model.passengers))
    for passenger, result in movement_results:
        model.movement_backend.commit_movement_result(passenger, result)
        passenger.pos = result.position

    identities: dict[int, tuple[str | None, int]] = {}
    for passenger in elevator.cabin_passengers:
        if passenger.native_facility_motion is None:
            continue
        passenger_id = int(passenger.unique_id)
        session_key = model.movement_backend._session_keys_by_passenger[passenger_id]
        session = model.movement_backend._sessions[session_key]
        identities[passenger_id] = (
            session_key,
            session._agent_ids[passenger_id],
        )
    elevator.commit_native_facility_motion_after_movement()
    model.step_index += 1
    return identities


def _finish_boarding(
    model: MetroStationModel,
    elevator: ElevatorProcessAgent,
) -> list[dict[int, tuple[str | None, int]]]:
    identities = []
    for _ in range(40):
        identities.append(_advance_native_tick(model, elevator))
        if elevator.cabin_state != "boarding":
            break
    assert elevator.cabin_state == "moving"
    return identities


def _minimum_common_trace_distance(
    model: MetroStationModel,
    first_id: int,
    second_id: int,
    *,
    phase: str,
) -> float:
    points = model.movement_backend.movement_trace()["points"]
    indexed = {
        (round(float(point["time_seconds"]), 9), int(point["passenger_id"])): point
        for point in points
    }
    distances = []
    for (time_seconds, passenger_id), first in indexed.items():
        if passenger_id != first_id or first["phase"] != phase:
            continue
        second = indexed.get((time_seconds, second_id))
        if second is None:
            continue
        distances.append(
            hypot(
                float(first["x"]) - float(second["x"]),
                float(first["y"]) - float(second["y"]),
            )
        )
    assert distances, f"no common high-frequency samples for {phase}"
    return min(distances)


def _planned_unloading_endpoints(
    elevator: ElevatorProcessAgent,
) -> dict[int, tuple[float, float]]:
    starts = elevator._cabin_positions_at_center(elevator.portal_exit_position)
    releases = elevator._plan_self_clear_unloading_releases(
        elevator.cabin_passengers,
        starts,
    )
    assert releases is not None
    return releases


def test_elevator_boarding_shares_the_native_landing_collision_world() -> None:
    model = _model()
    elevator = _elevator(model)
    rider = _place_rider(model, elevator)
    walker = _place_walker(
        model,
        level_id=str(elevator.portal_entry_level_id),
        start=(53.15, 19.83),
        target=(56.0, 19.83),
    )

    identities = _finish_boarding(model, elevator)

    active_identities = [item[int(rider.unique_id)] for item in identities if item]
    assert len(set(active_identities)) == 1
    assert all(
        session_key == elevator.portal_entry_level_id
        for session_key, _native_id in active_identities
    )
    minimum = _minimum_common_trace_distance(
        model,
        int(rider.unique_id),
        int(walker.unique_id),
        phase="elevator_boarding",
    )
    assert minimum >= elevator._release_min_distance() - 1e-6
    expected = elevator._boarding_positions_at_ratio(1.0)[int(rider.unique_id)]
    assert hypot(rider.pos[0] - expected[0], rider.pos[1] - expected[1]) <= 0.02


def test_elevator_unloading_shares_the_native_landing_collision_world() -> None:
    model = _model()
    elevator = _elevator(model)
    rider = _place_rider(model, elevator)
    _finish_boarding(model, elevator)
    expected = _planned_unloading_endpoints(elevator)
    elevator._advance_cabin(elapsed_seconds=elevator.travel_remaining_seconds)
    assert elevator.cabin_state == "moving"
    walker = _place_walker(
        model,
        level_id=str(elevator.portal_exit_level_id),
        start=(53.15, 29.57),
        target=(55.5, 29.57),
    )

    identities = []
    for _ in range(40):
        identities.append(_advance_native_tick(model, elevator))
        if not elevator.cabin_passengers:
            break

    assert elevator.cabin_state in {"returning", "idle"}
    active_identities = [item[int(rider.unique_id)] for item in identities if item]
    assert len(set(active_identities)) == 1
    assert all(
        session_key == elevator.portal_exit_level_id
        for session_key, _native_id in active_identities
    )
    minimum = _minimum_common_trace_distance(
        model,
        int(rider.unique_id),
        int(walker.unique_id),
        phase="elevator_unloading",
    )
    assert minimum >= elevator._release_min_distance() - 1e-6
    endpoint = expected[int(rider.unique_id)]
    assert hypot(rider.pos[0] - endpoint[0], rider.pos[1] - endpoint[1]) <= 0.02
    assert rider.current_level_id == elevator.portal_exit_level_id


@pytest.mark.parametrize("tick_seconds", (1, 2, 5))
@pytest.mark.parametrize("radius", (0.12, 0.18, 0.25, 0.35))
def test_elevator_native_landing_endpoint_contract_is_tick_and_radius_stable(
    tick_seconds: int,
    radius: float,
) -> None:
    model = _model(
        tick_seconds=tick_seconds,
        radius=radius,
        document=generate_metamorphic_base(1),
    )
    elevator = _elevator(model)
    rider = _place_rider(model, elevator)
    boarding_endpoint = elevator._boarding_positions_at_ratio(1.0)[int(rider.unique_id)]
    _finish_boarding(model, elevator)

    assert hypot(
        rider.pos[0] - boarding_endpoint[0],
        rider.pos[1] - boarding_endpoint[1],
    ) <= 0.02

    unloading_endpoint = _planned_unloading_endpoints(elevator)[int(rider.unique_id)]
    elevator._advance_cabin(elapsed_seconds=elevator.travel_remaining_seconds)
    for _ in range(40):
        _advance_native_tick(model, elevator)
        if not elevator.cabin_passengers:
            break

    assert elevator.cabin_state in {"returning", "idle"}
    assert hypot(
        rider.pos[0] - unloading_endpoint[0],
        rider.pos[1] - unloading_endpoint[1],
    ) <= 0.02


def test_elevator_landing_and_shaft_have_one_trace_authority_each() -> None:
    model = _model()
    elevator = _elevator(model)
    rider = _place_rider(model, elevator)
    _finish_boarding(model, elevator)
    elevator._advance_cabin(elapsed_seconds=elevator.travel_remaining_seconds)
    for _ in range(40):
        _advance_native_tick(model, elevator)
        if not elevator.cabin_passengers:
            break

    movement_points = [
        point
        for point in model.movement_backend.movement_trace()["points"]
        if int(point["passenger_id"]) == int(rider.unique_id)
    ]
    facility_points = [
        point
        for point in model.facility_motion_trace_recorder.as_dict()["points"]
        if int(point["passenger_id"]) == int(rider.unique_id)
    ]

    assert {point["phase"] for point in movement_points} >= {
        "elevator_boarding",
        "elevator_unloading",
    }
    assert {point["phase"] for point in facility_points} == {"elevator_travel"}
    assert all(point["authority"] == "jupedsim_committed_walk" for point in movement_points)
    assert all(point["authority"] == "facility_process_model" for point in facility_points)


def test_elevator_native_multi_passenger_cycle_preserves_fifo_and_logical_ids() -> None:
    model = _model()
    elevator = _elevator(model)
    riders = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        for _ in range(2)
    ]
    model.passengers.extend(riders)
    for index, rider in enumerate(riders):
        rider.current_level_id = elevator.portal_entry_level_id
        entry = elevator._service_entry_position(index)
        rider.pos = model.movement_backend.place_passenger(
            rider,
            entry,
            target=entry,
            level_id=rider.current_level_id,
        )
        assert elevator.queue.join(rider)
    elevator._begin_boarding(riders, loaded_persons=2, start_time=0.0)
    expected_ids = tuple(int(rider.unique_id) for rider in riders)

    boarding_identities = _finish_boarding(model, elevator)
    assert tuple(int(rider.unique_id) for rider in elevator.cabin_passengers) == expected_ids
    for passenger_id in expected_ids:
        identities = [item[passenger_id] for item in boarding_identities if passenger_id in item]
        assert len(set(identities)) == 1

    elevator._advance_cabin(elapsed_seconds=elevator.travel_remaining_seconds)
    unloading_identities = []
    for _ in range(40):
        unloading_identities.append(_advance_native_tick(model, elevator))
        if not elevator.cabin_passengers:
            break

    assert elevator.served_persons == 2
    assert elevator.cabin_passengers == []
    assert all(rider.current_level_id == elevator.portal_exit_level_id for rider in riders)
    assert hypot(
        riders[0].pos[0] - riders[1].pos[0],
        riders[0].pos[1] - riders[1].pos[1],
    ) >= elevator._release_min_distance() - 1e-6
    for passenger_id in expected_ids:
        identities = [
            item[passenger_id] for item in unloading_identities if passenger_id in item
        ]
        assert len(set(identities)) == 1

    event = model.facility_service_events[-1]
    assert tuple(event.passenger_ids) == expected_ids
    movement_points = model.movement_backend.movement_trace()["points"]
    assert {int(point["passenger_id"]) for point in movement_points} == set(expected_ids)


def test_elevator_native_three_passenger_unloading_cannot_settle_before_endpoints() -> None:
    """A full cabin must not form a stable personal-space unloading deadlock."""

    model = _model(document=create_design("three_level_transfer"))
    elevator = _elevator(model)
    riders = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        for _ in range(3)
    ]
    model.passengers.extend(riders)
    for index, rider in enumerate(riders):
        rider.current_level_id = elevator.portal_entry_level_id
        entry = elevator._service_entry_position(index)
        rider.pos = model.movement_backend.place_passenger(
            rider,
            entry,
            target=entry,
            level_id=rider.current_level_id,
        )
        assert elevator.queue.join(rider)
    elevator._begin_boarding(riders, loaded_persons=3, start_time=0.0)

    _finish_boarding(model, elevator)
    blocker = _place_walker(
        model,
        level_id=str(elevator.portal_exit_level_id),
        start=(69.9, 31.2),
        target=(69.9, 31.2),
    )
    elevator._advance_cabin(elapsed_seconds=elevator.travel_remaining_seconds)
    for _ in range(80):
        _advance_native_tick(model, elevator)
        if not elevator.cabin_passengers:
            break

    assert elevator.cabin_passengers == []
    assert elevator.served_persons == 3
    for rider in riders:
        assert rider.native_facility_motion is None
        assert hypot(
            rider.pos[0] - blocker.pos[0],
            rider.pos[1] - blocker.pos[1],
        ) >= elevator._release_min_distance() - 1e-6


def test_chained_elevator_waiting_line_keeps_full_arrival_footprint_clear() -> None:
    """A downstream queue must not occupy an upstream full-cabin landing."""

    model = _model(document=create_design("three_level_transfer"))
    upstream = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
        and facility.facility_id == "vertical:elevator_a:up:b3_platform:b2_transfer"
    )
    downstream = next(
        facility
        for facility in model.vertical_transports
        if isinstance(facility, ElevatorProcessAgent)
        and facility.facility_id == "vertical:elevator_a:up:b2_transfer:b1_concourse"
    )
    riders = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        for _ in range(4)
    ]
    model.passengers.extend(riders)
    for index, rider in enumerate(riders):
        rider.current_level_id = upstream.portal_entry_level_id
        entry = upstream._service_entry_position(index)
        rider.pos = model.movement_backend.place_passenger(
            rider,
            entry,
            target=entry,
            level_id=rider.current_level_id,
        )
        assert upstream.queue.join(rider)
    upstream._begin_boarding(riders, loaded_persons=4, start_time=0.0)
    _finish_boarding(model, upstream)

    blockers = [
        _place_walker(
            model,
            level_id=str(upstream.portal_exit_level_id),
            start=downstream.queue.layout.slot(index),
            target=downstream.queue.layout.slot(index),
        )
        for index in range(2)
    ]
    upstream._advance_cabin(elapsed_seconds=upstream.travel_remaining_seconds)
    for _ in range(100):
        _advance_native_tick(model, upstream)
        if not upstream.cabin_passengers:
            break

    assert upstream.cabin_passengers == []
    assert upstream.served_persons == 4
    for rider in riders:
        assert all(
            hypot(rider.pos[0] - blocker.pos[0], rider.pos[1] - blocker.pos[1])
            >= upstream._release_min_distance() - 1e-6
            for blocker in blockers
        )


def test_default_elevator_event_boundaries_match_trace_authority_handoffs() -> None:
    model = _model()
    elevator = _elevator(model)
    rider = _place_rider(model, elevator, start_time=None)
    event = model.facility_service_events[-1]
    assert event.start_time == pytest.approx(1.0)
    assert rider.native_facility_motion is not None
    assert rider.native_facility_motion.active_after_seconds == pytest.approx(1.0)

    # Production starts boarding after facility.step has already advanced the
    # current interval.  The body remains a collision blocker during [0, 1],
    # but its boarding episode must not begin before the event boundary.
    model.movement_backend.step_all(list(model.passengers))
    elevator.commit_native_facility_motion_after_movement()
    model.step_index += 1

    for _ in range(120):
        _advance_native_tick(model, elevator)
        if not elevator.cabin_passengers:
            break

    assert not elevator.cabin_passengers
    final_event = model.facility_service_events[-1]
    movement_trace = model.movement_backend.movement_trace()
    facility_trace = model.facility_motion_trace_recorder.as_dict()
    boarding_times = [
        float(point["time_seconds"])
        for point in movement_trace["points"]
        if int(point["passenger_id"]) == int(rider.unique_id)
        and point["phase"] == "elevator_boarding"
    ]
    assert boarding_times
    assert min(boarding_times) == pytest.approx(final_event.start_time, abs=0.011)
    assert max(boarding_times) == pytest.approx(
        final_event.board_end_time,
        abs=0.011,
    )

    coverage = _trajectory_authority_coverage(
        {
            "simulation_trace": {
                "snapshots": [],
                "facility_events": [final_event.as_dict()],
                "movement_trace": movement_trace,
                "facility_motion_trace": facility_trace,
            }
        }
    )
    assert coverage["facility_episode_coverage"]["passed"] is True
    assert coverage["facility_episode_coverage"]["obligation_count"] == 3


def test_tick_end_arrival_holds_connector_authority_until_landing_is_clear() -> None:
    model = _model()
    elevator = _elevator(model)
    rider = _place_rider(model, elevator)
    _finish_boarding(model, elevator)
    while elevator.travel_remaining_seconds > 1.0 + 1e-9:
        _advance_native_tick(model, elevator)
    assert elevator.travel_remaining_seconds == pytest.approx(1.0)

    portal = elevator.portal_exit_position
    walker = _place_walker(
        model,
        level_id=str(elevator.portal_exit_level_id),
        start=(portal[0] - 1.15, portal[1]),
        target=(portal[0] + 1.20, portal[1]),
    )

    _advance_native_tick(model, elevator)
    assert elevator.cabin_state == "moving"
    assert elevator.travel_remaining_seconds == pytest.approx(0.0)
    assert rider.native_facility_motion is None
    assert hypot(walker.pos[0] - portal[0], walker.pos[1] - portal[1]) < (
        elevator._release_min_distance()
    )

    original_arrive = float(model.facility_service_events[-1].arrive_time)
    _advance_native_tick(model, elevator)
    assert elevator.cabin_state == "moving"
    assert rider.native_facility_motion is None
    assert float(model.facility_service_events[-1].arrive_time) > original_arrive

    for _ in range(40):
        _advance_native_tick(model, elevator)
        if not elevator.cabin_passengers:
            break
    assert not elevator.cabin_passengers
    assert rider.current_level_id == elevator.portal_exit_level_id

    final_event = model.facility_service_events[-1]
    movement_trace = model.movement_backend.movement_trace()
    facility_trace = model.facility_motion_trace_recorder.as_dict()
    coverage = _trajectory_authority_coverage(
        {
            "simulation_trace": {
                "snapshots": [],
                "facility_events": [final_event.as_dict()],
                "movement_trace": movement_trace,
                "facility_motion_trace": facility_trace,
            }
        }
    )
    assert coverage["facility_episode_coverage"]["passed"] is True
    assert not [
        point
        for point in facility_trace["points"]
        if point["phase"] == "elevator_unloading"
    ]
    travel_times = [
        float(point["time_seconds"])
        for point in facility_trace["points"]
        if point["phase"] == "elevator_travel"
    ]
    assert max(travel_times) == pytest.approx(final_event.arrive_time, abs=0.011)
