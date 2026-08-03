from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Iterable

from ..station.train_disruptions import (
    RESUME_TRAIN_SERVICE,
    SUSPEND_TRAIN_SERVICE,
    TrainCapacityEvent,
    TrainServiceAvailabilityEvent,
)

if TYPE_CHECKING:
    from ..agents.transit import TrainAgent
    from .mesa_model import MetroStationModel


@dataclass(frozen=True)
class AppliedTrainServiceEvent:
    scheduled_seconds: int
    applied_seconds: float
    action: str
    platform_id: str
    train_state: str
    next_arrival_seconds: float
    platform_waiting_persons: int
    effective_suspended: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AppliedTrainCapacityEvent:
    scheduled_seconds: int
    applied_seconds: float
    platform_id: str
    capacity_persons_before: int
    capacity_persons_after: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class TrainDisruptionController:
    """Own train suspension state and cancellation/arrival evidence."""

    def __init__(
        self,
        events: tuple[TrainServiceAvailabilityEvent, ...],
        *,
        capacity_events: tuple[TrainCapacityEvent, ...] = (),
    ) -> None:
        self.events = events
        self.capacity_events = capacity_events
        self.suspended_platform_ids: set[str] = set()
        self.applied_events: list[AppliedTrainServiceEvent] = []
        self.applied_capacity_events: list[AppliedTrainCapacityEvent] = []
        self.capacity_by_platform_id: dict[str, int] = {}
        self.cancelled_arrivals: list[dict[str, object]] = []
        self.arrivals: list[dict[str, object]] = []
        self._next_event_index = 0
        self._next_capacity_event_index = 0

    def validate_platform_ids(self, available_ids: Iterable[str]) -> None:
        available = set(available_ids)
        scheduled = {event.platform_id for event in (*self.events, *self.capacity_events)}
        unknown = sorted(scheduled - available)
        if unknown:
            raise ValueError(
                "train_service_events contains unknown platforms: " + ", ".join(unknown)
            )

    @property
    def has_pending_events(self) -> bool:
        return self._next_event_index < len(self.events) or self._next_capacity_event_index < len(
            self.capacity_events
        )

    def is_suspended(self, platform_id: str) -> bool:
        return platform_id in self.suspended_platform_ids

    def capacity_for(self, platform_id: str, default_capacity: int) -> int:
        return int(self.capacity_by_platform_id.get(platform_id, default_capacity))

    def apply_due(self, model: MetroStationModel) -> None:
        while self._next_event_index < len(self.events):
            event = self.events[self._next_event_index]
            if event.at_seconds > model.current_time_seconds:
                break
            self._apply(model, event)
            self._next_event_index += 1
        while self._next_capacity_event_index < len(self.capacity_events):
            event = self.capacity_events[self._next_capacity_event_index]
            if event.at_seconds > model.current_time_seconds:
                break
            self._apply_capacity(model, event)
            self._next_capacity_event_index += 1

    def _apply_capacity(self, model: MetroStationModel, event: TrainCapacityEvent) -> None:
        before = self.capacity_for(event.platform_id, model.scenario.train_capacity_persons)
        self.capacity_by_platform_id[event.platform_id] = int(event.capacity_persons)
        applied = AppliedTrainCapacityEvent(
            scheduled_seconds=int(event.at_seconds),
            applied_seconds=float(model.current_time_seconds),
            platform_id=event.platform_id,
            capacity_persons_before=before,
            capacity_persons_after=int(event.capacity_persons),
        )
        self.applied_capacity_events.append(applied)
        model.audit.record(
            "train_capacity_changed",
            source="train_disruption_controller",
            severity="warning",
            step=model.step_index,
            context=applied.as_dict(),
        )

    def _apply(self, model: MetroStationModel, event: TrainServiceAvailabilityEvent) -> None:
        if event.action == SUSPEND_TRAIN_SERVICE:
            self.suspended_platform_ids.add(event.platform_id)
        elif event.action == RESUME_TRAIN_SERVICE:
            self.suspended_platform_ids.discard(event.platform_id)
        train = model.trains_by_platform_id[event.platform_id]
        platform = model.platforms_by_id[event.platform_id]
        applied = AppliedTrainServiceEvent(
            scheduled_seconds=int(event.at_seconds),
            applied_seconds=float(model.current_time_seconds),
            action=event.action,
            platform_id=event.platform_id,
            train_state=str(train.state),
            next_arrival_seconds=float(train.next_arrival_step * model.scenario.tick_seconds),
            platform_waiting_persons=int(platform.waiting_persons),
            effective_suspended=self.is_suspended(event.platform_id),
        )
        self.applied_events.append(applied)
        model.audit.record(
            "train_service_availability_changed",
            source="train_disruption_controller",
            severity="warning" if event.action == SUSPEND_TRAIN_SERVICE else "info",
            step=model.step_index,
            context=applied.as_dict(),
        )

    def record_cancelled_arrival(self, model: MetroStationModel, train: TrainAgent) -> None:
        evidence = self._train_event_evidence(model, train)
        self.cancelled_arrivals.append(evidence)
        model.audit.record(
            "train_arrival_cancelled",
            source="train_disruption_controller",
            severity="warning",
            step=model.step_index,
            context=evidence,
        )

    def record_arrival(self, model: MetroStationModel, train: TrainAgent) -> None:
        self.arrivals.append(self._train_event_evidence(model, train))

    def _train_event_evidence(
        self,
        model: MetroStationModel,
        train: TrainAgent,
    ) -> dict[str, object]:
        return {
            "time_seconds": float(model.current_time_seconds),
            "platform_id": train.platform_id,
            "line_id": train.line_id,
            "direction": train.direction,
            "suspended": self.is_suspended(train.platform_id),
        }

    def applied_event_dicts(self) -> list[dict[str, object]]:
        return [event.as_dict() for event in self.applied_events]

    def applied_capacity_event_dicts(self) -> list[dict[str, object]]:
        return [event.as_dict() for event in self.applied_capacity_events]

    def arrival_during_suspension_violations(self) -> int:
        return sum(1 for arrival in self.arrivals if bool(arrival["suspended"]))
