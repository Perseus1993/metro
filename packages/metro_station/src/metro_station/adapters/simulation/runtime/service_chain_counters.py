from __future__ import annotations

from typing import Any

WAITING_CAPACITY_RETRY = "waiting_capacity_retry"
STALLED_PLATFORM_PARKING = "stalled_platform_parking"


def increment_service_chain_counter(model: Any, code: str) -> None:
    """Increment a behavior counter independently of optional audit logging."""

    counts = getattr(model, "service_chain_event_counts", None)
    if counts is not None:
        counts[str(code)] += 1


__all__ = [
    "STALLED_PLATFORM_PARKING",
    "WAITING_CAPACITY_RETRY",
    "increment_service_chain_counter",
]
