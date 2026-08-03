from __future__ import annotations

from dataclasses import dataclass

from ..planning.goal_events import GoalEvent, GoalEventKind
from ..planning.goal_state import AgentGoalState, FacilityInteractionState


@dataclass(frozen=True)
class ProductionServiceObservationContext:
    kind: GoalEventKind
    facility_id: str
    time_seconds: float
    event_id: str


class ProductionGoalServiceEventObserver:
    """Validate production facility facts without changing Goal state."""

    def __init__(self) -> None:
        self._emitted_event_ids: set[str] = set()

    def observe(
        self,
        context: ProductionServiceObservationContext,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        if context.event_id in self._emitted_event_ids:
            return None
        if not self._matches_commitment(context, state):
            return None
        if not self._legal_phase(context.kind, state):
            return None
        self._emitted_event_ids.add(context.event_id)
        return GoalEvent(
            kind=context.kind.value,
            time_seconds=max(context.time_seconds, state.last_event_time_seconds),
            event_id=context.event_id,
            stage=state.current_stage,
            facility_id=context.facility_id,
        )

    @staticmethod
    def _matches_commitment(
        context: ProductionServiceObservationContext,
        state: AgentGoalState,
    ) -> bool:
        return state.commitment is not None and (
            state.commitment.facility_id == context.facility_id
        )

    @staticmethod
    def _legal_phase(kind: GoalEventKind, state: AgentGoalState) -> bool:
        if kind == GoalEventKind.SERVICE_STARTED:
            return (
                state.interaction_state == FacilityInteractionState.QUEUEING.value
                and state.queued_facility_id == state.commitment.facility_id
            )
        if kind == GoalEventKind.SERVICE_COMPLETED:
            return state.interaction_state == FacilityInteractionState.IN_SERVICE.value
        return False
