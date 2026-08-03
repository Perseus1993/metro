from __future__ import annotations

from dataclasses import dataclass


DISABLE_FACILITY = "disable"
ENABLE_FACILITY = "enable"
SUPPORTED_FACILITY_ACTIONS = frozenset({DISABLE_FACILITY, ENABLE_FACILITY})


@dataclass(frozen=True, order=True)
class FacilityAvailabilityEvent:
    """Scheduled facility availability change applied at a simulation step boundary."""

    at_seconds: int
    action: str
    facility_id: str

    def __post_init__(self) -> None:
        if int(self.at_seconds) < 0:
            raise ValueError(f"facility event at_seconds must be >= 0; got {self.at_seconds!r}")
        if self.action not in SUPPORTED_FACILITY_ACTIONS:
            choices = ", ".join(sorted(SUPPORTED_FACILITY_ACTIONS))
            raise ValueError(f"facility event action must be one of {choices}; got {self.action!r}")
        if not str(self.facility_id).strip():
            raise ValueError("facility event facility_id must not be blank")

    def as_dict(self) -> dict[str, object]:
        return {
            "at_seconds": int(self.at_seconds),
            "action": self.action,
            "facility_id": self.facility_id,
        }


def validate_facility_availability_events(
    events: tuple[FacilityAvailabilityEvent, ...],
    *,
    horizon_seconds: float,
    tick_seconds: int,
    statically_disabled_ids: tuple[str, ...],
) -> None:
    previous_time = -1
    disabled: set[str] = set(statically_disabled_ids)
    static_ids = set(statically_disabled_ids)
    seen: set[tuple[int, str]] = set()

    for event in events:
        if not isinstance(event, FacilityAvailabilityEvent):
            raise TypeError("facility_availability_events must contain FacilityAvailabilityEvent")
        if event.at_seconds < previous_time:
            raise ValueError("facility_availability_events must be ordered by at_seconds")
        previous_time = event.at_seconds
        if event.at_seconds >= horizon_seconds:
            raise ValueError(
                "facility event at_seconds must be before the simulation horizon; "
                f"got {event.at_seconds!r} >= {horizon_seconds!r}"
            )
        if event.at_seconds % int(tick_seconds) != 0:
            raise ValueError(
                "facility event at_seconds must align with tick_seconds; "
                f"got {event.at_seconds!r} for {tick_seconds!r}-second ticks"
            )
        key = (event.at_seconds, event.facility_id)
        if key in seen:
            raise ValueError(
                "facility_availability_events must not change the same facility twice "
                f"at {event.at_seconds} seconds"
            )
        seen.add(key)
        if event.facility_id in static_ids:
            raise ValueError(
                "dynamic facility events cannot target statically disabled facility "
                f"{event.facility_id!r}"
            )
        if event.action == DISABLE_FACILITY:
            if event.facility_id in disabled:
                raise ValueError(
                    f"facility {event.facility_id!r} is already disabled at "
                    f"{event.at_seconds} seconds"
                )
            disabled.add(event.facility_id)
            continue
        if event.facility_id not in disabled:
            raise ValueError(
                f"facility {event.facility_id!r} must be disabled before it can be enabled"
            )
        disabled.remove(event.facility_id)
