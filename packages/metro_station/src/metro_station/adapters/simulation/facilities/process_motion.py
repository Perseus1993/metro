from __future__ import annotations

from math import sqrt


def minimum_jerk_progress(ratio: float) -> float:
    value = max(0.0, min(1.0, float(ratio)))
    return value * value * value * (10.0 + value * (-15.0 + 6.0 * value))


def minimum_jerk_duration_seconds(
    distance_m: float,
    *,
    minimum_seconds: float,
    maximum_speed_m_s: float,
    maximum_acceleration_m_s2: float,
) -> float:
    """Size a quintic process path from speed and acceleration contracts."""

    distance = max(0.0, float(distance_m))
    speed = max(0.1, float(maximum_speed_m_s))
    acceleration = max(0.1, float(maximum_acceleration_m_s2))
    return max(
        0.0,
        float(minimum_seconds),
        1.875 * distance / speed,
        sqrt(5.774 * distance / acceleration),
    )


__all__ = ["minimum_jerk_duration_seconds", "minimum_jerk_progress"]
