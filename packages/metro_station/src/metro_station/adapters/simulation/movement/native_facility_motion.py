from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


Point = tuple[float, float]


@dataclass(frozen=True)
class NativeFacilityMotion:
    """One process-owned target executed inside a native crowd session.

    The facility owns admission, timing, capacity, and the semantic phase.
    JuPedSim remains the sole position authority while the body is embedded in
    a public landing.  ``active_after_seconds`` preserves a sub-tick process
    boundary without moving the body before that boundary.
    """

    collision_level_id: str
    phase: str
    target: Point
    desired_speed_mps: float
    endpoint_tolerance_m: float
    episode_id: str
    active_after_seconds: float = 0.0
    terminal: bool = False

    def __post_init__(self) -> None:
        if not self.collision_level_id:
            raise ValueError("native facility motion requires a collision level")
        if not self.phase or not self.episode_id:
            raise ValueError("native facility motion requires phase and episode identity")
        numeric = (
            *self.target,
            self.desired_speed_mps,
            self.endpoint_tolerance_m,
            self.active_after_seconds,
        )
        if not all(isfinite(float(value)) for value in numeric):
            raise ValueError("native facility motion values must be finite")
        if self.desired_speed_mps <= 0.0:
            raise ValueError("native facility motion speed must be positive")
        if self.endpoint_tolerance_m <= 0.0:
            raise ValueError("native facility endpoint tolerance must be positive")
        if self.active_after_seconds < 0.0:
            raise ValueError("native facility activation offset cannot be negative")


__all__ = ["NativeFacilityMotion"]
