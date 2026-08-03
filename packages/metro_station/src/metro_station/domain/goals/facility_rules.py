from __future__ import annotations

from .events import GoalEvent, GoalEventKind
from .state import PRE_SERVICE_REPLAN_STATES, AgentGoalState


def matches_committed_facility(
    event: GoalEvent,
    state: AgentGoalState,
    expected_kind: GoalEventKind,
) -> bool:
    return (
        event.kind == expected_kind.value
        and state.commitment is not None
        and event.facility_id == state.commitment.facility_id
    )


def is_pre_service_replan_event(state: AgentGoalState, event: GoalEvent) -> bool:
    if state.interaction_state not in PRE_SERVICE_REPLAN_STATES:
        return False
    if event.kind == GoalEventKind.PROGRESS_STALLED.value:
        return state.commitment is not None
    return matches_committed_facility(event, state, GoalEventKind.FACILITY_UNAVAILABLE)
