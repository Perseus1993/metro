from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent


@dataclass(frozen=True)
class MovementRequest:
    passenger_id: int
    position: tuple[float, float]
    target: tuple[float, float]
    radius: float
    level: str | None
    desired_speed_mps: float

    @classmethod
    def from_passenger(cls, passenger: PassengerAgent) -> "MovementRequest":
        return cls(
            passenger_id=int(passenger.unique_id),
            position=passenger.pos,
            target=passenger.target,
            radius=float(passenger.model.scenario.jupedsim_target_radius_units),
            level=passenger.current_level_id,
            desired_speed_mps=_desired_speed_mps(passenger),
        )


@dataclass(frozen=True)
class MovementResult:
    passenger_id: int
    position: tuple[float, float]
    reached: bool = False


def _movement_suppressed_this_step(passenger: PassengerAgent) -> bool:
    method = getattr(passenger, "movement_suppressed_this_step", None)
    return bool(callable(method) and method())


def _desired_speed_mps(passenger: PassengerAgent) -> float:
    desired_speed = getattr(passenger.model, "desired_walk_speed_mps", None)
    if callable(desired_speed):
        return float(desired_speed(passenger))
    return float(getattr(passenger.model.scenario, "jupedsim_desired_speed_mps", 1.2))
