from __future__ import annotations

from math import cos, hypot, sin

from shapely.geometry import Point as ShapelyPoint


def has_initialization_clearance(
    candidate: tuple[float, float],
    starts: list[tuple[float, float]],
    radius: float,
    clearance_multiplier: float,
) -> bool:
    min_distance = max(0.05, radius * clearance_multiplier)
    for existing in starts:
        if hypot(candidate[0] - existing[0], candidate[1] - existing[1]) < min_distance:
            return False
    return True


def can_share_initialization_batch(
    candidate: tuple[float, float],
    starts: list[tuple[float, float]],
    radius: float,
    clearance_multiplier: float,
) -> bool:
    return has_initialization_clearance(candidate, starts, radius, clearance_multiplier)


def clearance_adjusted_position(
    candidate: tuple[float, float],
    starts: list[tuple[float, float]],
    radius: float,
    clearance_multiplier: float,
    *,
    walkable_area,
    seed: int,
) -> tuple[float, float] | None:
    if can_share_initialization_batch(candidate, starts, radius, clearance_multiplier):
        return candidate

    min_distance = max(0.05, radius * clearance_multiplier)
    for attempt in range(12):
        angle_seed = seed * 1103515245 + attempt * 12345
        angle = (angle_seed % 6283) / 1000.0
        distance = min_distance * (1.0 + 0.25 * (attempt // 4))
        adjusted = (
            candidate[0] + cos(angle) * distance,
            candidate[1] + sin(angle) * distance,
        )
        if not walkable_area.covers(ShapelyPoint(adjusted)):
            continue
        if has_initialization_clearance(adjusted, starts, radius, clearance_multiplier):
            return adjusted
    return None
