from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from metro_station.domain.time_boundaries import first_step_not_before


OPERATIONS_MODE = "operations"
EVACUATION_MODE = "evacuation"
SUPPORTED_SCENARIO_MODES = frozenset({OPERATIONS_MODE, EVACUATION_MODE})


@dataclass(frozen=True)
class EvacuationScenarioConfig:
    """First research-safe evacuation slice: platform population to station exterior."""

    initial_platform_persons: int
    alarm_delay_seconds: float = 0.0
    stop_train_service: bool = True

    def __post_init__(self) -> None:
        if int(self.initial_platform_persons) < 0:
            raise ValueError("initial_platform_persons must be >= 0")
        delay = float(self.alarm_delay_seconds)
        if not isfinite(delay) or delay < 0.0:
            raise ValueError("alarm_delay_seconds must be finite and >= 0")

    def validate_for_group_size(self, group_size: int) -> None:
        size = max(1, int(group_size))
        if self.initial_platform_persons % size != 0:
            raise ValueError(
                "initial_platform_persons must be divisible by group_size so the initial "
                "evacuation population is represented exactly"
            )

    def initial_groups(self, group_size: int) -> int:
        self.validate_for_group_size(group_size)
        return self.initial_platform_persons // max(1, int(group_size))

    def alarm_step(self, tick_seconds: float) -> int:
        return first_step_not_before(self.alarm_delay_seconds, tick_seconds)
