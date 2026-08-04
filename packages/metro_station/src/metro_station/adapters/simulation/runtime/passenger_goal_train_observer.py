from __future__ import annotations

from ..planning.goal_events import GoalEvent, GoalEventKind
from .goal_event_ids import runtime_episode_event_id


class PassengerGoalTrainObserver:
    """Produce train facts without changing passenger or Goal state."""

    def waiting_event(self, model, passenger) -> GoalEvent | None:
        trains = [train for train in model.trains if train.is_boarding]
        line_id = passenger.target_line_id or passenger.assigned_line_id
        direction = passenger.target_direction or passenger.assigned_direction
        if line_id is not None:
            trains = [train for train in trains if train.line_id == line_id]
        if direction is not None:
            trains = [train for train in trains if train.direction == direction]
        assigned_platform_id = getattr(passenger, "assigned_platform_id", None)
        if assigned_platform_id is not None:
            trains = [train for train in trains if train.platform_id == assigned_platform_id]
        if not trains:
            return None
        available = [
            train for train in trains if train.capacity_remaining >= passenger.group_size
        ]
        kind = GoalEventKind.TRAIN_AVAILABLE if available else GoalEventKind.TRAIN_FULL
        episode_train = min(
            available or trains,
            key=lambda train: (str(train.platform_id), int(train.arrival_sequence)),
        )
        return self._event(
            model,
            passenger,
            kind,
            "platform",
            None if available else "all_matching_trains_full",
            episode_train,
        )

    def queued_event(self, model, passenger) -> GoalEvent | None:
        facility_id = passenger.goal_runtime.state.queued_facility_id
        facility = model.facilities_by_id.get(facility_id)
        if facility is None:
            return None
        train = model.train_for_facility(facility)
        if train is None or not train.is_boarding:
            return None
        kind = GoalEventKind.TRAIN_AVAILABLE
        reason = None
        if train.capacity_remaining < passenger.group_size:
            kind = GoalEventKind.TRAIN_FULL
            reason = "train_capacity_exhausted"
        return self._event(model, passenger, kind, str(facility_id), reason, train)

    def _event(
        self,
        model,
        passenger,
        kind,
        value: str,
        reason: str | None,
        train,
    ) -> GoalEvent:
        platform_id = str(train.platform_id)
        arrival_sequence = int(train.arrival_sequence)
        episode = f"{platform_id}:{arrival_sequence}"
        return GoalEvent(
            kind=kind.value,
            time_seconds=model.current_time_seconds,
            event_id=runtime_episode_event_id(
                passenger.unique_id,
                kind.value,
                value,
                episode,
            ),
            reason=reason,
            train_platform_id=platform_id,
            train_arrival_sequence=arrival_sequence,
        )
