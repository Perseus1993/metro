from __future__ import annotations

from unittest.mock import patch

from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.movement.contracts import MovementResult
from metro_station.adapters.simulation.movement.movement_backend_contract import (
    MovementBackend,
)
from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_acceptance.generated_acceptance_profile import (
    stratified_simulation_sample,
    trajectory_geometry_corpus,
)
from metro_station_testkit.layout_corpus import generate_geometry_scenario_matrix
from metro_station_testkit.layout_scenario_generator import generate_layout


class _InstantMovementBackend(MovementBackend):
    def move(self, passenger: PassengerAgent) -> MovementResult:
        return MovementResult(
            int(passenger.unique_id),
            tuple(passenger.target),
            reached=True,
        )


def _bidirectional_model() -> MetroStationModel:
    recipes = stratified_simulation_sample(
        trajectory_geometry_corpus(generate_geometry_scenario_matrix()),
        16,
    )
    recipe = next(
        item
        for item in recipes
        if item.recipe_id
        == "geometry-two_level_island-u-dual_cluster-bidirectional-seed-7"
    )
    scenario = StationSandboxScenario(
        station_name="bidirectional_gate_unit",
        hour=18,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="unit",
        sample_hours=1,
        station_design=generate_layout(recipe),
        audit_enabled=False,
        audit_print_events=False,
    )
    return MetroStationModel(
        scenario,
        seed=99,
        movement_backend=_InstantMovementBackend(),
    )


def _queued_passenger(model, gate, intent: AgentIntent) -> PassengerAgent:
    # The test exercises only physical-lane arbitration. Constructing an exit
    # intent directly on the concourse would be an invalid full journey (it
    # normally starts on a platform), so use the neutral entry constructor and
    # then place the body at the tested facade.
    del intent
    with patch.object(model.goal_coordinator, "initialize"):
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
            initial_position=gate._service_entry_position(),
            initial_level_id=gate.portal_entry_level_id,
        )
    passenger.pos = gate._service_entry_position()
    model.passengers.append(passenger)
    assert gate.queue.join(passenger)
    return passenger


def test_opposite_gate_facades_share_one_fair_physical_lane() -> None:
    model = _bidirectional_model()
    entry = model.gates[-1]
    exit_gate = next(
        gate
        for gate in model.exit_gates
        if gate._physical_lane_key() == entry._physical_lane_key()
    )
    entry.state = "open"
    exit_gate.state = "open"
    first_entry = _queued_passenger(model, entry, AgentIntent.ENTER_AND_BOARD)
    first_exit = _queued_passenger(model, exit_gate, AgentIntent.EXIT_STATION)

    assert entry._can_start_service(first_entry, None)
    entry.queue.pop(0)
    entry._start_service(first_entry, None)
    assert not exit_gate._can_start_service(first_exit, None)

    second_entry = _queued_passenger(model, entry, AgentIntent.ENTER_AND_BOARD)
    assert not entry._can_start_service(second_entry, None)
    while entry.active_passes:
        entry._advance_active_passes()

    assert exit_gate._can_start_service(first_exit, None)
    assert not entry._can_start_service(second_entry, None)


def test_gate_endpoint_preflight_failure_leaves_queue_and_semantics_unchanged() -> None:
    model = _bidirectional_model()
    gate = model.gates[-1]
    gate.state = "open"
    passenger = _queued_passenger(model, gate, AgentIntent.ENTER_AND_BOARD)
    passenger.enter_facility_queue(gate.spec)
    queue_before = tuple(gate.queue)
    state_before = passenger.state
    goal_before = passenger.current_goal
    parity_event_count_before = len(model.goal_parity.events)
    service_event_count_before = len(model.facility_service_events)
    active_pass_count_before = len(gate.active_passes)

    with patch.object(
        model.movement_backend,
        "resolve_placement",
        side_effect=RuntimeError("injected endpoint rejection"),
    ):
        gate.service_credit = 1.0
        gate._serve_queue(None)

    assert tuple(gate.queue) == queue_before
    assert passenger.state == state_before
    assert passenger.current_goal == goal_before
    assert len(model.goal_parity.events) == parity_event_count_before
    assert len(model.facility_service_events) == service_event_count_before
    assert len(gate.active_passes) == active_pass_count_before
