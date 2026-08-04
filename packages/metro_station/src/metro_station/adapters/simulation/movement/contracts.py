from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import TYPE_CHECKING

from .waypoint_policy import intermediate_waypoint_radius

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
        scenario = passenger.model.scenario
        final_target_radius = float(scenario.jupedsim_target_radius_units)
        goal = getattr(passenger, "current_goal", None)
        goal_kind = getattr(goal, "kind", None)
        if goal_kind is None:
            legacy_goal = getattr(passenger, "goal", None)
            if isinstance(legacy_goal, Mapping):
                goal_kind = legacy_goal.get("kind")
        tactical_target = bool(getattr(passenger, "route", ())) or (
            goal_kind == "being_served"
        )
        radius = (
            intermediate_waypoint_radius(
                agent_radius=float(scenario.jupedsim_agent_radius_units),
                final_target_radius=final_target_radius,
            )
            if tactical_target
            else final_target_radius
        )
        return cls(
            passenger_id=int(passenger.unique_id),
            position=passenger.pos,
            target=passenger.target,
            radius=radius,
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
