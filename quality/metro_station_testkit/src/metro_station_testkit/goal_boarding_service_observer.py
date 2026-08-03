"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_events import GoalEvent, GoalEventKind
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState
from .goal_boarding_micro_scene import GoalBoardingMicroScene


class GoalBoardingServiceObserver:
    def __init__(self) -> None:
        self._phase_by_event_id: dict[int, int] = {}

    def observe(
        self,
        scene: GoalBoardingMicroScene,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        event = next(
            (
                item
                for item in scene.facility_service_events
                if scene.subject.unique_id in item.passenger_ids
                and self._phase_by_event_id.get(item.event_id, 0) < 2
            ),
            None,
        )
        if event is None or state.commitment is None:
            return None
        phase = self._phase_by_event_id.get(event.event_id, 0)
        self._phase_by_event_id[event.event_id] = phase + 1
        kind = GoalEventKind.SERVICE_STARTED if phase == 0 else GoalEventKind.SERVICE_COMPLETED
        return GoalEvent(
            kind=kind.value,
            time_seconds=max(scene.current_time_seconds, state.last_event_time_seconds),
            facility_id=event.facility_id,
        )
