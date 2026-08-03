from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EscalatorMode(StrEnum):
    STAND = "stand"
    WALK = "walk"
    OFF = "off"
    BLOCKED = "blocked"


ESCALATOR_SPEED_FACTOR_BY_MODE: dict[EscalatorMode, float] = {
    EscalatorMode.STAND: 1.0,
    EscalatorMode.WALK: 1.35,
    EscalatorMode.OFF: 0.7,
    EscalatorMode.BLOCKED: 0.0,
}


@dataclass(frozen=True)
class EscalatorConfig:
    default_mode: EscalatorMode = EscalatorMode.STAND
    ride_time_seconds: float | None = None
    stand_capacity_ppm: int = 75
    walk_capacity_ppm: int = 115
    off_capacity_ppm: int = 60

    def capacity_for_mode(self, mode: EscalatorMode) -> int:
        if mode == EscalatorMode.STAND:
            return self.stand_capacity_ppm
        if mode == EscalatorMode.WALK:
            return self.walk_capacity_ppm
        if mode == EscalatorMode.OFF:
            return self.off_capacity_ppm
        return 0


@dataclass(frozen=True)
class ElevatorConfig:
    batch_capacity: int = 12
    min_dispatch_persons: int = 1
    max_dispatch_wait_seconds: float = 0.0
    boarding_seconds: float = 5.0
    travel_seconds: float = 35.0
    unload_seconds: float = 0.0
    return_seconds: float | None = None

    @property
    def return_trip_seconds(self) -> float:
        if self.return_seconds is None:
            return max(0.0, self.travel_seconds)
        return max(0.0, self.return_seconds)

    @property
    def cycle_seconds(self) -> float:
        return (
            max(0.0, self.boarding_seconds)
            + max(0.0, self.travel_seconds)
            + max(0.0, self.unload_seconds)
            + self.return_trip_seconds
        )


@dataclass(frozen=True)
class StairsConfig:
    base_capacity_ppm: int = 125
    fatigue_cost_up: float = 0.6
    fatigue_cost_down: float = 0.15
    bidirectional_conflict_factor: float = 0.3
    sibling_facility_id: str | None = None


@dataclass(frozen=True)
class VerticalFacilityConfig:
    escalator: EscalatorConfig | None = None
    elevator: ElevatorConfig | None = None
    stairs: StairsConfig | None = None


def default_escalator_config(service_persons_per_min: int = 75) -> EscalatorConfig:
    stand_capacity = max(1, int(service_persons_per_min))
    return EscalatorConfig(
        stand_capacity_ppm=stand_capacity,
        walk_capacity_ppm=max(1, round(stand_capacity * 115 / 75)),
        off_capacity_ppm=max(1, round(stand_capacity * 60 / 75)),
    )


def default_elevator_config(
    *,
    batch_capacity: int,
    boarding_seconds: float,
    travel_seconds: float,
    unload_seconds: float = 0.0,
    return_seconds: float | None = None,
    min_dispatch_persons: int = 1,
    max_dispatch_wait_seconds: float = 0.0,
) -> ElevatorConfig:
    parsed_travel_seconds = max(0.0, float(travel_seconds))
    parsed_capacity = max(1, int(batch_capacity))
    return ElevatorConfig(
        batch_capacity=parsed_capacity,
        min_dispatch_persons=max(1, min(parsed_capacity, int(min_dispatch_persons))),
        max_dispatch_wait_seconds=max(0.0, float(max_dispatch_wait_seconds)),
        boarding_seconds=max(0.0, float(boarding_seconds)),
        travel_seconds=parsed_travel_seconds,
        unload_seconds=max(0.0, float(unload_seconds)),
        return_seconds=(
            parsed_travel_seconds if return_seconds is None else max(0.0, float(return_seconds))
        ),
    )


def default_stairs_config(
    *,
    base_capacity_ppm: int,
    fatigue_cost_up: float,
    fatigue_cost_down: float,
    bidirectional_conflict_factor: float,
    sibling_facility_id: str | None = None,
) -> StairsConfig:
    return StairsConfig(
        base_capacity_ppm=max(1, int(base_capacity_ppm)),
        fatigue_cost_up=max(0.0, float(fatigue_cost_up)),
        fatigue_cost_down=max(0.0, float(fatigue_cost_down)),
        bidirectional_conflict_factor=max(0.0, min(1.0, float(bidirectional_conflict_factor))),
        sibling_facility_id=sibling_facility_id,
    )
