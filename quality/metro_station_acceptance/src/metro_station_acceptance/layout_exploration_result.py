from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from metro_station_testkit.layout_exploration_case import LayoutExplorationCase


@dataclass(frozen=True)
class ExplorationStageResult:
    stage: str
    status: str
    diagnostic_codes: tuple[str, ...] = ()
    checks: Mapping[str, bool] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "ok" and all(self.checks.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "passed": self.passed,
            "checks": dict(self.checks),
            "metrics": deepcopy(dict(self.metrics)),
        }


@dataclass(frozen=True)
class ExplorationCaseResult:
    case: LayoutExplorationCase
    observed_outcome: str
    stages: tuple[ExplorationStageResult, ...]
    checks: Mapping[str, bool]
    artifacts: Mapping[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "case": self.case.as_dict(),
            "observed_outcome": self.observed_outcome,
            "stages": [stage.as_dict() for stage in self.stages],
            "checks": dict(self.checks),
            "artifacts": deepcopy(dict(self.artifacts)),
        }


@dataclass(frozen=True)
class ExplorationSuiteReport:
    suite_id: str
    generator_version: str
    results: tuple[ExplorationCaseResult, ...]
    coverage: Mapping[str, Any]
    checks: Mapping[str, bool]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "layout_exploration_report.v1"

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    @property
    def failed_case_ids(self) -> tuple[str, ...]:
        return tuple(result.case.case_id for result in self.results if result.status != "ok")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "suite_id": self.suite_id,
            "generator_version": self.generator_version,
            "case_count": len(self.results),
            "failed_case_ids": list(self.failed_case_ids),
            "coverage": deepcopy(dict(self.coverage)),
            "results": [result.as_dict() for result in self.results],
            "checks": dict(self.checks),
            "metadata": deepcopy(dict(self.metadata)),
        }


def catalog_coverage(cases: tuple[LayoutExplorationCase, ...]) -> dict[str, Any]:
    factor_names = sorted({name for case in cases for name in case.factors})
    dimensions = {
        name: Counter(_factor_value(case.factors.get(name, "<missing>")) for case in cases)
        for name in factor_names
    }
    pairs: Counter[str] = Counter()
    for case in cases:
        present = [(name, _factor_value(case.factors[name])) for name in factor_names if name in case.factors]
        for index, (left_name, left_value) in enumerate(present):
            for right_name, right_value in present[index + 1 :]:
                pairs[f"{left_name}={left_value}|{right_name}={right_value}"] += 1
    return {
        "case_count": len(cases),
        "expected_classes": dict(sorted(Counter(case.expected_class for case in cases).items())),
        "dimensions": {
            name: dict(sorted(counts.items())) for name, counts in dimensions.items()
        },
        "pairs": dict(sorted(pairs.items())),
    }


def _factor_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)

