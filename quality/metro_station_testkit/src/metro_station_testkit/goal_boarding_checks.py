"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_state import AgentGoalState, FacilityInteractionState
from metro_station.adapters.simulation.planning.plan import AgentState
from .goal_boarding_micro_scene import GoalBoardingMicroScene
from .goal_boarding_trace import GoalBoardingTraceStep


def boarding_probe_checks(
    scenario_id: str,
    scene: GoalBoardingMicroScene,
    state: AgentGoalState,
    traces: list[GoalBoardingTraceStep],
    *,
    completed_at: float | None,
) -> dict[str, bool]:
    completed = state.current_node_id == "complete"
    facilities = [trace.committed_facility_id for trace in traces]
    stalls = [trace for trace in traces if trace.event_kind == "progress_stalled"]
    if scenario_id == "natural_boarding":
        return {
            **_completed_checks(scene, completed),
            "no_retry": state.retry_count == 0,
        }
    if scenario_id == "door_front_crowded":
        return {
            **_completed_checks(scene, completed),
            "selected_door_1": "door_1" in facilities,
            "rerouted_door_2": "door_2" in facilities,
            "physical_blockers": any(trace.blocker_count > 0 for trace in traces),
            "stall_emitted": bool(stalls),
        }
    if scenario_id == "alighting_conflict":
        return {
            **_completed_checks(scene, completed),
            "alighting_stall_observed": bool(stalls),
            "boarded_after_conflict_clearance": scene.boarded_persons == 1,
        }
    if scenario_id == "train_full":
        return {
            "not_completed": not completed,
            "not_boarded": scene.boarded_persons == 0,
            "train_capacity_zero": scene.train.capacity_remaining == 0,
            "waiting_for_next_train": state.interaction_state
            == FacilityInteractionState.QUEUEING.value
            and state.commitment is not None,
        }
    if scenario_id == "train_not_open":
        return {
            "not_completed": not completed,
            "not_boarded": scene.boarded_persons == 0,
            "train_away": scene.train.state == "away",
            "waiting_in_door_queue": state.interaction_state
            == FacilityInteractionState.QUEUEING.value,
        }
    return {
        **_completed_checks(scene, completed),
        "no_retry": state.retry_count == 0,
        "remained_departed": scene.subject.state == AgentState.DEPARTED.value,
        "not_readded_to_platform": scene.subject not in scene.passengers,
        "not_requeued": all(scene.subject not in door.queue for door in scene.doors),
        "post_completion_observed": completed_at is not None
        and scene.current_time_seconds >= completed_at + 2.0,
    }


def _completed_checks(
    scene: GoalBoardingMicroScene,
    completed: bool,
) -> dict[str, bool]:
    return {
        "completed": completed,
        "one_boarded_person": scene.boarded_persons == 1,
        "one_boarding_service": len(scene.facility_service_events) == 1,
        "passenger_departed": scene.subject.state == AgentState.DEPARTED.value,
        "train_load_incremented": scene.train.current_load_persons == 1,
    }
