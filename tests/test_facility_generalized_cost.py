from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from metro_station.domain.goals.choice import MinimumPerceivedCostSelector
from metro_station.domain.goals.events import (
    DecisionObservation,
    FacilityObservation,
    GoalEvent,
    GoalEventKind,
)
from metro_station.domain.goals.state_machine import EventDrivenGoalStateMachine
from metro_station.domain.goals.commands import GoalCommandKind
from metro_station.domain.goals.state import FacilityInteractionState
from metro_station.adapters.simulation.planning.journeys import entry_gate_journey_graph
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from tests.test_passenger_goal_runtime import InstantMovementBackend, _scenario


def candidate(
    facility_id: str,
    *,
    walking: float,
    waiting: float = 0.0,
    service: float = 1.0,
    density: float = 0.0,
    available: bool = True,
    reachable: bool = True,
) -> FacilityObservation:
    return FacilityObservation(
        facility_id=facility_id,
        stage="entry_gate",
        available=available,
        reachable=reachable,
        walking_time_seconds=walking,
        queue_persons=0,
        estimated_wait_seconds=waiting,
        service_time_seconds=service,
        local_density_persons_m2=density,
        walking_distance_units=walking * 1.2,
        walking_cost_source="physical_waypoint_geodesic",
    )


def observation(
    time_seconds: float,
    candidates: tuple[FacilityObservation, ...],
    *,
    committed_facility_id: str | None = None,
    reconsider_after_seconds: float | None = None,
    replan_reason: str | None = None,
    minimum_improvement_seconds: float = 5.0,
) -> DecisionObservation:
    return DecisionObservation(
        time_seconds=time_seconds,
        current_region_id="entry_gate_decision",
        candidates=candidates,
        committed_facility_id=committed_facility_id,
        reconsider_after_seconds=reconsider_after_seconds,
        replan_reason=replan_reason,
        commitment_duration_seconds=10.0,
        replan_cooldown_seconds=30.0,
        minimum_improvement_seconds=minimum_improvement_seconds,
    )


def selected_state(machine: EventDrivenGoalStateMachine, candidates):
    graph = entry_gate_journey_graph()
    started = machine.start(graph)
    entered = machine.handle(
        graph,
        started.state,
        GoalEvent(
            kind=GoalEventKind.ENTERED_REGION.value,
            time_seconds=0.0,
            region_id="entry_gate_decision",
        ),
    )
    selected = machine.handle(
        graph,
        entered.state,
        GoalEvent(
            kind=GoalEventKind.CANDIDATES_UPDATED.value,
            time_seconds=1.0,
            observation=observation(1.0, candidates),
        ),
    )
    return graph, selected


def test_generalized_cost_is_recomputable_and_includes_service_and_ineligibility() -> None:
    selector = MinimumPerceivedCostSelector()
    result = selector.choose(
        "entry_gate",
        observation(
            1.0,
            (
                candidate("slow_near", walking=1.0, service=20.0),
                candidate("fast_far", walking=4.0, waiting=2.0, service=2.0, density=0.5),
                candidate("closed", walking=0.0, service=0.0, available=False),
            ),
        ),
    )

    assert result is not None
    assert result.facility_id == "fast_far"
    chosen = next(item for item in result.candidate_costs if item.facility_id == "fast_far")
    recomputed = (
        chosen.weighted_walking_seconds
        + chosen.weighted_queue_wait_seconds
        + chosen.weighted_service_seconds
        + chosen.weighted_density_seconds
    )
    assert result.score == recomputed == 10.0
    closed = next(item for item in result.candidate_costs if item.facility_id == "closed")
    assert closed.total_seconds is None
    assert closed.ineligible_reason == "unavailable"
    assert chosen.walking_cost_source == "physical_waypoint_geodesic"


def test_same_observation_is_deterministic_independent_of_candidate_order() -> None:
    selector = MinimumPerceivedCostSelector()
    candidates = (
        candidate("gate_b", walking=5.0),
        candidate("gate_a", walking=5.0),
    )
    forward = selector.choose("entry_gate", observation(1.0, candidates))
    reverse = selector.choose("entry_gate", observation(1.0, tuple(reversed(candidates))))
    assert forward is not None and reverse is not None
    assert forward.as_dict() == reverse.as_dict()
    assert forward.facility_id == "gate_a"


def test_stall_reassessment_preserves_queue_and_retains_during_commitment() -> None:
    machine = EventDrivenGoalStateMachine()
    initial = (
        candidate("gate_a", walking=2.0),
        candidate("gate_b", walking=8.0),
    )
    graph, selected = selected_state(machine, initial)
    captured = machine.handle(
        graph,
        selected.state,
        GoalEvent(
            kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
            time_seconds=2.0,
            facility_id="gate_a",
        ),
    )
    queued = machine.handle(
        graph,
        captured.state,
        GoalEvent(
            kind=GoalEventKind.QUEUE_JOINED.value,
            time_seconds=3.0,
            facility_id="gate_a",
        ),
    )
    stalled = machine.handle(
        graph,
        queued.state,
        GoalEvent(
            kind=GoalEventKind.PROGRESS_STALLED.value,
            time_seconds=5.0,
            reason="queue_cost_noise",
        ),
    )

    assert stalled.state.commitment is not None
    assert stalled.state.queued_facility_id == "gate_a"
    assert stalled.commands[0].kind == GoalCommandKind.OBSERVE_CANDIDATES.value

    reconsidered = machine.handle(
        graph,
        stalled.state,
        GoalEvent(
            kind=GoalEventKind.CANDIDATES_UPDATED.value,
            time_seconds=5.0,
            observation=observation(
                5.0,
                (
                    candidate("gate_a", walking=10.0),
                    candidate("gate_b", walking=1.0),
                ),
                committed_facility_id="gate_a",
                reconsider_after_seconds=11.0,
                replan_reason="queue_cost_noise",
            ),
        ),
    )
    assert reconsidered.state.interaction_state == FacilityInteractionState.QUEUEING.value
    assert reconsidered.state.queued_facility_id == "gate_a"
    assert reconsidered.state.retry_count == 0
    assert reconsidered.commands[0].selection_action == "retain"
    assert "commitment_or_cooldown" in str(reconsidered.commands[0].reason)


def test_expired_commitment_switches_only_for_material_benefit_and_blocks_a_b_a() -> None:
    machine = EventDrivenGoalStateMachine()
    graph, selected = selected_state(
        machine,
        (candidate("gate_a", walking=5.0), candidate("gate_b", walking=9.0)),
    )
    stalled = machine.handle(
        graph,
        selected.state,
        GoalEvent(
            kind=GoalEventKind.PROGRESS_STALLED.value,
            time_seconds=20.0,
            reason="movement_stalled",
        ),
    )
    switched = machine.handle(
        graph,
        stalled.state,
        GoalEvent(
            kind=GoalEventKind.CANDIDATES_UPDATED.value,
            time_seconds=20.0,
            observation=observation(
                20.0,
                (candidate("gate_a", walking=12.0), candidate("gate_b", walking=1.0)),
                committed_facility_id="gate_a",
                reconsider_after_seconds=11.0,
                replan_reason="movement_stalled",
            ),
        ),
    )
    assert switched.state.commitment is not None
    assert switched.state.commitment.facility_id == "gate_b"
    assert switched.state.retry_count == 1
    assert [command.kind for command in switched.commands] == [
        GoalCommandKind.REPLAN_STAGE.value,
        GoalCommandKind.SELECT_FACILITY.value,
        GoalCommandKind.WALK_TO_QUEUE.value,
    ]
    assert switched.commands[0].replan_cleanup_only

    stalled_again = machine.handle(
        graph,
        switched.state,
        GoalEvent(
            kind=GoalEventKind.PROGRESS_STALLED.value,
            time_seconds=21.0,
            reason="measurement_noise",
        ),
    )
    no_return = machine.handle(
        graph,
        stalled_again.state,
        GoalEvent(
            kind=GoalEventKind.CANDIDATES_UPDATED.value,
            time_seconds=21.0,
            observation=observation(
                21.0,
                (candidate("gate_a", walking=0.0), candidate("gate_b", walking=8.0)),
                committed_facility_id="gate_b",
                reconsider_after_seconds=50.0,
                replan_reason="measurement_noise",
            ),
        ),
    )
    assert no_return.state.commitment is not None
    assert no_return.state.commitment.facility_id == "gate_b"
    assert no_return.state.retry_count == 1
    assert no_return.commands[0].selection_action == "retain"


def test_unavailable_facility_forces_immediate_destructive_replan() -> None:
    machine = EventDrivenGoalStateMachine()
    graph, selected = selected_state(
        machine,
        (candidate("gate_a", walking=1.0), candidate("gate_b", walking=4.0)),
    )
    unavailable = machine.handle(
        graph,
        selected.state,
        GoalEvent(
            kind=GoalEventKind.FACILITY_UNAVAILABLE.value,
            time_seconds=2.0,
            facility_id="gate_a",
            reason="facility_disabled:gate_a",
        ),
    )
    assert unavailable.state.commitment is None
    assert unavailable.state.retry_count == 1
    assert unavailable.commands[0].kind == GoalCommandKind.REPLAN_STAGE.value
    assert not unavailable.commands[0].replan_cleanup_only

    alternative = machine.handle(
        graph,
        unavailable.state,
        GoalEvent(
            kind=GoalEventKind.CANDIDATES_UPDATED.value,
            time_seconds=2.0,
            observation=observation(
                2.0,
                (
                    candidate("gate_a", walking=1.0, available=False),
                    candidate("gate_b", walking=4.0),
                ),
                replan_reason="facility_disabled:gate_a",
            ),
        ),
    )
    assert alternative.state.commitment is not None
    assert alternative.state.commitment.facility_id == "gate_b"


def test_same_seed_runtime_logs_are_identical_and_export_recomputable_evidence() -> None:
    scenario = replace(
        _scenario(),
        minutes=1,
        demand_minutes=1,
        entry_count_hour=60,
        exit_count_hour=0,
        transfer_count_hour=0,
        audit_print_events=False,
    )

    def run_once():
        model = MetroStationModel(
            scenario,
            seed=73,
            movement_backend=InstantMovementBackend(),
        )
        model.run()
        return model

    first = run_once()
    second = run_once()
    first_runtime = cast(Any, first)
    second_runtime = cast(Any, second)
    assert (
        first_runtime.facility_choice_decision_logs
        == second_runtime.facility_choice_decision_logs
    )
    assert first_runtime.facility_choice_decision_logs

    decision = first_runtime.facility_choice_decision_logs[0]["decision"]
    chosen = next(
        item
        for item in decision["candidate_costs"]
        if item["facility_id"] == decision["facility_id"]
    )
    assert decision["score"] == (
        chosen["weighted_walking_seconds"]
        + chosen["weighted_queue_wait_seconds"]
        + chosen["weighted_service_seconds"]
        + chosen["weighted_density_seconds"]
    )
    exported = [
        event
        for frame in first_runtime.frames
        for event in frame.get("facility_choice_events", [])
    ]
    assert exported == first_runtime.facility_choice_decision_logs
