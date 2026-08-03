"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_events import GoalEvent, GoalEventKind
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState
from .goal_gate_micro_scene import GoalGateMicroScene


class GoalGateServiceObserver:
    """Translate gate service records into idempotent Goal service facts."""

    def __init__(self) -> None:
        self._phase_by_event_id: dict[int, int] = {}

    def observe(
        self,
        context: GoalGateMicroScene,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        event = next(
            (
                item
                for item in context.facility_service_events
                if context.subject.unique_id in item.passenger_ids
                and self._phase_by_event_id.get(item.event_id, 0) < 2
            ),
            None,
        )
        if event is None or state.commitment is None:
            return None
        if event.facility_id != state.commitment.facility_id:
            return None
        phase = self._phase_by_event_id.get(event.event_id, 0)
        self._phase_by_event_id[event.event_id] = phase + 1
        kind = GoalEventKind.SERVICE_STARTED if phase == 0 else GoalEventKind.SERVICE_COMPLETED
        return GoalEvent(
            kind=kind.value,
            time_seconds=max(context.current_time_seconds, state.last_event_time_seconds),
            facility_id=event.facility_id,
        )
