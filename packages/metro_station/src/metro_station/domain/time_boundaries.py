from __future__ import annotations

from math import ceil, isfinite


def first_step_not_before(time_seconds: float, tick_seconds: float) -> int:
    """Return the first fixed-step boundary at or after a physical time."""

    time_value = float(time_seconds)
    tick_value = float(tick_seconds)
    if not isfinite(time_value) or time_value < 0.0:
        raise ValueError(f"time_seconds must be finite and >= 0; got {time_seconds!r}")
    if not isfinite(tick_value) or tick_value <= 0.0:
        raise ValueError(f"tick_seconds must be finite and > 0; got {tick_seconds!r}")
    return max(0, int(ceil(time_value / tick_value - 1e-12)))


def positive_steps_to_cover(duration_seconds: float, tick_seconds: float) -> int:
    """Return a positive number of steps whose duration never ends early."""

    return max(1, first_step_not_before(duration_seconds, tick_seconds))
