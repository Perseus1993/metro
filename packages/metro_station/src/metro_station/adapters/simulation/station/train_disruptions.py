from __future__ import annotations

from dataclasses import dataclass


SUSPEND_TRAIN_SERVICE = "suspend"
RESUME_TRAIN_SERVICE = "resume"
SUPPORTED_TRAIN_SERVICE_ACTIONS = frozenset({SUSPEND_TRAIN_SERVICE, RESUME_TRAIN_SERVICE})


@dataclass(frozen=True, order=True)
class TrainServiceAvailabilityEvent:
    """Scheduled suspension or recovery for one platform's train service."""

    at_seconds: int
    action: str
    platform_id: str

    def __post_init__(self) -> None:
        if int(self.at_seconds) < 0:
            raise ValueError(f"train event at_seconds must be >= 0; got {self.at_seconds!r}")
        if self.action not in SUPPORTED_TRAIN_SERVICE_ACTIONS:
            choices = ", ".join(sorted(SUPPORTED_TRAIN_SERVICE_ACTIONS))
            raise ValueError(f"train event action must be one of {choices}; got {self.action!r}")
        if not str(self.platform_id).strip():
            raise ValueError("train event platform_id must not be blank")

    def as_dict(self) -> dict[str, object]:
        return {
            "at_seconds": int(self.at_seconds),
            "action": self.action,
            "platform_id": self.platform_id,
        }


@dataclass(frozen=True, order=True)
class TrainCapacityEvent:
    """Scheduled per-platform train capacity change at a simulation boundary."""

    at_seconds: int
    platform_id: str
    capacity_persons: int

    def __post_init__(self) -> None:
        if int(self.at_seconds) < 0:
            raise ValueError("train capacity event at_seconds must be >= 0")
        if not str(self.platform_id).strip():
            raise ValueError("train capacity event platform_id must not be blank")
        if not isinstance(self.capacity_persons, int) or isinstance(self.capacity_persons, bool):
            raise ValueError("train capacity event capacity_persons must be an integer")
        if self.capacity_persons < 1:
            raise ValueError("train capacity event capacity_persons must be >= 1")

    def as_dict(self) -> dict[str, object]:
        return {
            "at_seconds": int(self.at_seconds),
            "platform_id": self.platform_id,
            "capacity_persons": int(self.capacity_persons),
        }


def validate_train_service_events(
    events: tuple[TrainServiceAvailabilityEvent, ...],
    *,
    horizon_seconds: float,
    tick_seconds: int,
) -> None:
    previous_time = -1
    suspended: set[str] = set()
    seen: set[tuple[int, str]] = set()
    for event in events:
        if not isinstance(event, TrainServiceAvailabilityEvent):
            raise TypeError("train_service_events must contain TrainServiceAvailabilityEvent")
        if event.at_seconds < previous_time:
            raise ValueError("train_service_events must be ordered by at_seconds")
        previous_time = event.at_seconds
        if event.at_seconds >= horizon_seconds:
            raise ValueError(
                "train event at_seconds must be before the simulation horizon; "
                f"got {event.at_seconds!r} >= {horizon_seconds!r}"
            )
        if event.at_seconds % int(tick_seconds) != 0:
            raise ValueError(
                "train event at_seconds must align with tick_seconds; "
                f"got {event.at_seconds!r} for {tick_seconds!r}-second ticks"
            )
        key = (event.at_seconds, event.platform_id)
        if key in seen:
            raise ValueError(
                "train_service_events must not change the same platform twice "
                f"at {event.at_seconds} seconds"
            )
        seen.add(key)
        if event.action == SUSPEND_TRAIN_SERVICE:
            if event.platform_id in suspended:
                raise ValueError(
                    f"train service {event.platform_id!r} is already suspended at "
                    f"{event.at_seconds} seconds"
                )
            suspended.add(event.platform_id)
            continue
        if event.platform_id not in suspended:
            raise ValueError(f"train service {event.platform_id!r} must be suspended before resume")
        suspended.remove(event.platform_id)


def validate_train_capacity_events(
    events: tuple[TrainCapacityEvent, ...],
    *,
    horizon_seconds: float,
    tick_seconds: int,
) -> None:
    previous_time = -1
    seen: set[tuple[int, str]] = set()
    for event in events:
        if not isinstance(event, TrainCapacityEvent):
            raise TypeError("train_capacity_events must contain TrainCapacityEvent")
        if event.at_seconds < previous_time:
            raise ValueError("train_capacity_events must be ordered by at_seconds")
        previous_time = event.at_seconds
        if event.at_seconds >= horizon_seconds:
            raise ValueError("train capacity event must be before the simulation horizon")
        if event.at_seconds % int(tick_seconds) != 0:
            raise ValueError("train capacity event at_seconds must align with tick_seconds")
        key = (event.at_seconds, event.platform_id)
        if key in seen:
            raise ValueError("train capacity may change at most once per platform and time")
        seen.add(key)
