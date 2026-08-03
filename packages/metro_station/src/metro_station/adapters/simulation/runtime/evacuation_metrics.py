from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .terminal_events import PassengerTerminalEvent


def evacuation_metrics(
    terminal_events: Iterable[PassengerTerminalEvent | Mapping[str, Any]],
    *,
    total_persons: int,
    remaining_persons: int,
) -> dict[str, int | float | None]:
    events = [_event_dict(event) for event in terminal_events]
    safe_events = [event for event in events if event.get("event") == "reached_safe_zone"]
    safe_events.sort(key=lambda event: float(event.get("time_seconds", 0.0)))
    total = max(0, int(total_persons))
    remaining = max(0, int(remaining_persons))
    evacuated = sum(max(0, int(event.get("persons", 0))) for event in safe_events)
    completion_rate = 1.0 if total <= 0 else min(1.0, evacuated / total)
    durations = [
        (float(event.get("duration_seconds", 0.0)), max(0, int(event.get("persons", 0))))
        for event in safe_events
    ]
    weighted_duration = sum(duration * persons for duration, persons in durations)
    return {
        "total_persons": total,
        "evacuated_persons": evacuated,
        "remaining_persons": remaining,
        "completion_rate": round(completion_rate, 6),
        "clearance_time_seconds": _clearance_time(safe_events, total, remaining),
        "t90_seconds": _threshold_time(safe_events, total, 0.90),
        "t95_seconds": _threshold_time(safe_events, total, 0.95),
        "t99_seconds": _threshold_time(safe_events, total, 0.99),
        "mean_evacuation_duration_seconds": (
            round(weighted_duration / evacuated, 6) if evacuated > 0 else None
        ),
    }


def _event_dict(
    event: PassengerTerminalEvent | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(event, PassengerTerminalEvent):
        return event.as_dict()
    return dict(event)


def _clearance_time(
    events: list[dict[str, Any]],
    total: int,
    remaining: int,
) -> float | None:
    if total <= 0:
        return 0.0
    if remaining > 0 or not events:
        return None
    return max(float(event.get("time_seconds", 0.0)) for event in events)


def _threshold_time(
    events: list[dict[str, Any]],
    total: int,
    threshold: float,
) -> float | None:
    if total <= 0:
        return 0.0
    required = total * threshold
    cumulative = 0
    for event in events:
        cumulative += max(0, int(event.get("persons", 0)))
        if cumulative >= required:
            return float(event.get("time_seconds", 0.0))
    return None
