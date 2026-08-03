"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_events import GoalEvent, GoalEventKind
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState
from .goal_stairs_micro_scene import GoalStairsMicroScene


class GoalStairsServiceObserver:
    def __init__(self) -> None:
        self._started_event_ids: set[int] = set()
        self._completed_event_ids: set[int] = set()

    def observe(
        self,
        scene: GoalStairsMicroScene,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        event = next(
            (
                item
                for item in scene.facility_service_events
                if scene.subject.unique_id in item.passenger_ids
            ),
            None,
        )
        if event is None or state.commitment is None:
            return None
        if event.event_id not in self._started_event_ids:
            self._started_event_ids.add(event.event_id)
            return self._goal_event(scene, event.facility_id, GoalEventKind.SERVICE_STARTED)
        if event.event_id in self._completed_event_ids:
            return None
        stairs = scene.stairs_by_id[event.facility_id]
        if scene.current_time_seconds + 1e-9 < event.end_time:
            return None
        if stairs.has_active_service(scene.subject):
            return None
        self._completed_event_ids.add(event.event_id)
        return self._goal_event(scene, event.facility_id, GoalEventKind.SERVICE_COMPLETED)

    @staticmethod
    def _goal_event(
        scene: GoalStairsMicroScene,
        facility_id: str,
        kind: GoalEventKind,
    ) -> GoalEvent:
        return GoalEvent(
            kind=kind.value,
            time_seconds=scene.current_time_seconds,
            facility_id=facility_id,
        )
