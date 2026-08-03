"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_events import GoalEvent, GoalEventKind
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState
from .goal_journey_micro_scene import GoalJourneyMicroScene


class GoalJourneyServiceObserver:
    def __init__(self) -> None:
        self._phase_by_event_id: dict[int, int] = {}

    def observe(
        self,
        scene: GoalJourneyMicroScene,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        if state.commitment is None:
            return None
        event = next(
            (
                item
                for item in scene.facility_service_events
                if item.facility_id == state.commitment.facility_id
                and scene.subject.unique_id in item.passenger_ids
                and self._phase_by_event_id.get(item.event_id, 0) < 2
            ),
            None,
        )
        if event is None:
            return None
        phase = self._phase_by_event_id.get(event.event_id, 0)
        if phase == 0:
            self._phase_by_event_id[event.event_id] = 1
            return self._goal_event(scene, event.facility_id, GoalEventKind.SERVICE_STARTED)
        facility = scene.facilities_by_id[event.facility_id]
        if scene.current_time_seconds + 1e-9 < event.end_time:
            return None
        if facility.has_active_service(scene.subject):
            return None
        self._phase_by_event_id[event.event_id] = 2
        return self._goal_event(scene, event.facility_id, GoalEventKind.SERVICE_COMPLETED)

    @staticmethod
    def _goal_event(
        scene: GoalJourneyMicroScene,
        facility_id: str,
        kind: GoalEventKind,
    ) -> GoalEvent:
        return GoalEvent(
            kind=kind.value,
            time_seconds=scene.current_time_seconds,
            facility_id=facility_id,
        )
