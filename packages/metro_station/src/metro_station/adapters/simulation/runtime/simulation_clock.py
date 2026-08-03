from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite
from typing import Any


LEGACY_SCALED_CLOCK = "legacy_scaled"
PHYSICAL_CLOCK = "physical"
SUPPORTED_CLOCK_MODES = frozenset({LEGACY_SCALED_CLOCK, PHYSICAL_CLOCK})


@dataclass(frozen=True)
class SimulationClock:
    """Couples the Mesa process clock to JuPedSim's integration clock."""

    mesa_tick_seconds: float
    jupedsim_dt_seconds: float
    mode: str = LEGACY_SCALED_CLOCK
    legacy_iterations_per_tick: int = 150

    def __post_init__(self) -> None:
        if self.mode not in SUPPORTED_CLOCK_MODES:
            choices = ", ".join(sorted(SUPPORTED_CLOCK_MODES))
            raise ValueError(f"Unsupported simulation clock mode {self.mode!r}; use {choices}.")
        self._require_positive("mesa_tick_seconds", self.mesa_tick_seconds)
        self._require_positive("jupedsim_dt_seconds", self.jupedsim_dt_seconds)
        if int(self.legacy_iterations_per_tick) < 1:
            raise ValueError("legacy_iterations_per_tick must be >= 1")
        if self.mode == PHYSICAL_CLOCK:
            self._physical_iterations_per_tick()

    @classmethod
    def from_scenario(cls, scenario: Any) -> "SimulationClock":
        return cls(
            mesa_tick_seconds=float(scenario.tick_seconds),
            jupedsim_dt_seconds=float(getattr(scenario, "jupedsim_dt_seconds", 0.01)),
            mode=str(getattr(scenario, "simulation_clock_mode", LEGACY_SCALED_CLOCK)),
            legacy_iterations_per_tick=int(scenario.jupedsim_iterations_per_tick),
        )

    @property
    def jupedsim_iterations_per_tick(self) -> int:
        if self.mode == LEGACY_SCALED_CLOCK:
            return int(self.legacy_iterations_per_tick)
        return self._physical_iterations_per_tick()

    @property
    def jupedsim_elapsed_seconds_per_tick(self) -> float:
        return self.jupedsim_iterations_per_tick * self.jupedsim_dt_seconds

    @property
    def research_valid(self) -> bool:
        return self.mode == PHYSICAL_CLOCK and self.mesa_tick_seconds <= 1.0

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": self.mode,
            "mesa_tick_seconds": self.mesa_tick_seconds,
            "jupedsim_dt_seconds": self.jupedsim_dt_seconds,
            "jupedsim_iterations_per_tick": self.jupedsim_iterations_per_tick,
            "jupedsim_elapsed_seconds_per_tick": self.jupedsim_elapsed_seconds_per_tick,
            "research_valid": self.research_valid,
        }
        if not self.research_valid:
            payload["research_invalid_reason"] = (
                "legacy_time_scaling"
                if self.mode != PHYSICAL_CLOCK
                else "process_time_resolution_exceeds_one_second"
            )
        return payload

    def _physical_iterations_per_tick(self) -> int:
        ratio = self.mesa_tick_seconds / self.jupedsim_dt_seconds
        rounded = round(ratio)
        if not isclose(ratio, rounded, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(
                "Physical clock requires mesa_tick_seconds to be an integer multiple of "
                f"jupedsim_dt_seconds; got {self.mesa_tick_seconds} / "
                f"{self.jupedsim_dt_seconds} = {ratio}."
            )
        return max(1, int(rounded))

    @staticmethod
    def _require_positive(name: str, value: float) -> None:
        if not isfinite(float(value)) or float(value) <= 0.0:
            raise ValueError(f"{name} must be > 0; got {value!r}")
