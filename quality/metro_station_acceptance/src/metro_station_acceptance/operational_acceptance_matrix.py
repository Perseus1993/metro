"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from metro_station.adapters.simulation.movement.backend import MovementBackend
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from .operational_acceptance import (
    OperationalAcceptanceReport,
    run_operational_acceptance,
)
from .operational_acceptance_scenarios import OPERATIONAL_SCENARIOS


@dataclass(frozen=True)
class OperationalAcceptanceMatrix:
    layout_id: str
    seeds: tuple[int, ...]
    scenario_ids: tuple[str, ...]
    reports: tuple[OperationalAcceptanceReport, ...]

    @property
    def status(self) -> str:
        return (
            "ok"
            if self.reports and all(report.status == "ok" for report in self.reports)
            else "review"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "layout_id": self.layout_id,
            "seeds": self.seeds,
            "scenario_ids": self.scenario_ids,
            "reports": [report.as_dict() for report in self.reports],
        }


def run_operational_acceptance_matrix(
    *,
    layout_id: str = "visual_demo_station",
    seeds: tuple[int, ...] = (41, 42, 43),
    scenario_ids: tuple[str, ...] = OPERATIONAL_SCENARIOS,
    movement_backend_factory: Callable[[], MovementBackend] | None = None,
    station_design: StationDesignDocument | None = None,
) -> OperationalAcceptanceMatrix:
    reports = tuple(
        run_operational_acceptance(
            scenario_id,
            layout_id=layout_id,
            seed=seed,
            movement_backend=(
                None if movement_backend_factory is None else movement_backend_factory()
            ),
            station_design=station_design,
        )
        for scenario_id in scenario_ids
        for seed in seeds
    )
    return OperationalAcceptanceMatrix(
        layout_id=layout_id,
        seeds=seeds,
        scenario_ids=scenario_ids,
        reports=reports,
    )
