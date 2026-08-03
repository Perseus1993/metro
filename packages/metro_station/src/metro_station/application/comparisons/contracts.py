"""Versioned contracts for paired comparison execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from ..analysis_cases import AnalysisCase
from .run_summary import RUN_SUMMARY_SCHEMA_VERSION, RunSummary


COMPARISON_RUN_SPEC_SCHEMA_VERSION = "comparison-run-spec/v1"

__all__ = [
    "COMPARISON_RUN_SPEC_SCHEMA_VERSION",
    "RUN_SUMMARY_SCHEMA_VERSION",
    "ComparisonRunSpec",
    "RunSummary",
]


@dataclass(frozen=True)
class ComparisonRunSpec:
    experiment_id: str
    baseline: AnalysisCase
    candidate: AnalysisCase
    seeds: tuple[int, ...]
    density_radius_m: float = 1.0
    density_threshold_persons_m2: float | None = 4.0
    schema_version: str = COMPARISON_RUN_SPEC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != COMPARISON_RUN_SPEC_SCHEMA_VERSION:
            raise ValueError(f"unsupported comparison spec schema: {self.schema_version!r}")
        if not self.experiment_id.strip():
            raise ValueError("experiment_id must not be blank")
        if self.baseline.case_id == self.candidate.case_id:
            raise ValueError("baseline and candidate must be distinct cases")
        if self.candidate.parent_case_id != self.baseline.case_id:
            raise ValueError("candidate must be cloned from baseline")
        if self.seeds != self.baseline.seeds or self.seeds != self.candidate.seeds:
            raise ValueError("comparison seeds must exactly match both cases")
        if self.baseline.simulation != self.candidate.simulation:
            raise ValueError("baseline and candidate simulation controls must match")
        if self.density_radius_m <= 0:
            raise ValueError("density_radius_m must be > 0")
        if self.density_threshold_persons_m2 is not None:
            if self.density_threshold_persons_m2 <= 0:
                raise ValueError("density threshold must be > 0")

    @classmethod
    def create(
        cls,
        baseline: AnalysisCase,
        candidate: AnalysisCase,
        *,
        density_radius_m: float = 1.0,
        density_threshold_persons_m2: float | None = 4.0,
    ) -> ComparisonRunSpec:
        return cls(
            experiment_id=uuid4().hex,
            baseline=baseline,
            candidate=candidate,
            seeds=baseline.seeds,
            density_radius_m=density_radius_m,
            density_threshold_persons_m2=density_threshold_persons_m2,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "baseline": self.baseline.as_dict(),
            "candidate": self.candidate.as_dict(),
            "seeds": list(self.seeds),
            "density_radius_m": self.density_radius_m,
            "density_threshold_persons_m2": self.density_threshold_persons_m2,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ComparisonRunSpec:
        values = dict(payload)
        values["baseline"] = AnalysisCase.from_dict(values["baseline"])
        values["candidate"] = AnalysisCase.from_dict(values["candidate"])
        values["seeds"] = tuple(int(seed) for seed in values.get("seeds", ()))
        return cls(**values)
