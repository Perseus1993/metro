"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_state import AgentGoalState, FacilityInteractionState
from .goal_stairs_fixture import CONCOURSE_LEVEL, PLATFORM_LEVEL
from .goal_stairs_micro_scene import GoalStairsMicroScene
from .goal_stairs_trace import GoalStairsTraceStep


def stairs_probe_checks(
    scenario_id: str,
    scene: GoalStairsMicroScene,
    state: AgentGoalState,
    traces: list[GoalStairsTraceStep],
    *,
    completed_at: float | None,
) -> dict[str, bool]:
    completed = state.current_node_id == "complete"
    facilities = [trace.committed_facility_id for trace in traces]
    stalls = [trace for trace in traces if trace.event_kind == "progress_stalled"]
    if scenario_id == "natural_descent":
        return _natural_checks(scene, state, completed)
    if scenario_id == "entrance_crowded":
        return {
            "completed": completed,
            "selected_stairs_1": "stairs_1" in facilities,
            "rerouted_stairs_2": "stairs_2" in facilities,
            "physical_entrance_blockers": any(trace.blocker_count > 0 for trace in traces),
            "stall_emitted": bool(stalls),
        }
    if scenario_id == "exit_crowded":
        return {
            "completed_after_clearance": completed,
            "stalled_without_graph_regression": bool(stalls)
            and all(
                trace.after_graph_state.startswith("enter_platform_landing")
                for trace in stalls
            ),
        }
    if scenario_id == "stairs_unavailable":
        return {
            "not_completed": not completed,
            "uncommitted": state.commitment is None,
            "waiting_for_candidates": state.interaction_state
            == FacilityInteractionState.EVALUATE_CANDIDATES.value,
            "never_changed_level": scene.subject.current_level_id == CONCOURSE_LEVEL,
        }
    return {
        **_natural_checks(scene, state, completed),
        "remained_on_platform": scene.subject.current_level_id == PLATFORM_LEVEL,
        "no_level_regression": _no_level_regression(traces),
        "no_second_vertical_service": len(scene.facility_service_events) == 1,
        "never_reentered_stairs": _never_reentered_stairs(scene, traces),
        "post_completion_observed": completed_at is not None
        and scene.current_time_seconds >= completed_at + 2.0,
    }


def _natural_checks(
    scene: GoalStairsMicroScene,
    state: AgentGoalState,
    completed: bool,
) -> dict[str, bool]:
    return {
        "completed": completed,
        "platform_level_reached": scene.subject.current_level_id == PLATFORM_LEVEL,
        "one_vertical_service": len(scene.facility_service_events) == 1,
        "no_retry": state.retry_count == 0,
    }


def _no_level_regression(traces: list[GoalStairsTraceStep]) -> bool:
    levels = [trace.current_level_id for trace in traces]
    try:
        platform_index = levels.index(PLATFORM_LEVEL)
    except ValueError:
        return False
    return CONCOURSE_LEVEL not in levels[platform_index:]


def _never_reentered_stairs(
    scene: GoalStairsMicroScene,
    traces: list[GoalStairsTraceStep],
) -> bool:
    if len(scene.facility_service_events) != 1:
        return False
    event = scene.facility_service_events[0]
    completion = next(
        (trace.time_seconds for trace in traces if trace.event_kind == "service_completed"),
        None,
    )
    if completion is None:
        return False
    exit_x = scene.stairs_by_id[event.facility_id].spec.exit_position[0]
    after_service = [
        (position, level_id)
        for time_seconds, position, level_id in scene.subject_history
        if time_seconds + 1e-9 >= completion
    ]
    return bool(after_service) and all(
        position[0] >= exit_x - 0.05 and level_id == PLATFORM_LEVEL
        for position, level_id in after_service
    )
