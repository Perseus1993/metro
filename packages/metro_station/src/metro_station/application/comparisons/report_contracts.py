"""Versioned decision and report contracts for analysis comparisons."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .contracts import ComparisonRunSpec, RunSummary
from .experiment import ExperimentPlan


COMPARISON_REPORT_SCHEMA_VERSION = "comparison-report/v1"
RECOMMENDATIONS = frozenset({"adopt", "reject", "more_evidence"})


@dataclass(frozen=True)
class AnalystDecision:
    recommendation: str = "more_evidence"
    rationale: str = "No analyst decision recorded."
    analyst: str = ""

    def __post_init__(self) -> None:
        if self.recommendation not in RECOMMENDATIONS:
            raise ValueError(f"unsupported recommendation: {self.recommendation!r}")
        if not self.rationale.strip():
            raise ValueError("decision rationale must not be blank")

    def as_dict(self) -> dict[str, str]:
        return {
            "recommendation": self.recommendation,
            "rationale": self.rationale,
            "analyst": self.analyst,
        }


@dataclass(frozen=True)
class ComparisonReport:
    spec: ComparisonRunSpec
    runs: tuple[RunSummary, ...]
    status: str
    input_differences: tuple[dict[str, Any], ...]
    paired_results: tuple[dict[str, Any], ...]
    aggregate: dict[str, Any]
    experiment_plan: ExperimentPlan | None = None
    decision: AnalystDecision = field(default_factory=AnalystDecision)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    schema_version: str = COMPARISON_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != COMPARISON_REPORT_SCHEMA_VERSION:
            raise ValueError(f"unsupported comparison-report schema: {self.schema_version!r}")
        if self.status not in {"completed", "partial", "failed"}:
            raise ValueError(f"unsupported comparison status: {self.status!r}")
        if not self._evidence_ready() and _claims_readiness(self.decision.rationale):
            raise ValueError("uncalibrated evidence cannot claim production or safety readiness")

    def _evidence_ready(self) -> bool:
        return (
            self.spec.baseline.evidence.research_ready
            and self.spec.candidate.evidence.research_ready
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "status": self.status,
            "spec": self.spec.as_dict(),
            "input_differences": list(self.input_differences),
            "runs": [run.as_dict() for run in self.runs],
            "paired_results": list(self.paired_results),
            "aggregate": self.aggregate,
            "experiment_plan": (
                None if self.experiment_plan is None else self.experiment_plan.as_dict()
            ),
            "decision": self.decision.as_dict(),
            "evidence": {
                "baseline": self.spec.baseline.evidence.as_dict(),
                "candidate": self.spec.candidate.evidence.as_dict(),
            },
            "methodology": _methodology(self.experiment_plan),
        }


def _claims_readiness(rationale: str) -> bool:
    normalized = rationale.casefold()
    forbidden = (
        "production ready",
        "safety ready",
        "approved for production",
        "生产就绪",
        "安全就绪",
        "安全认证",
    )
    return any(phrase in normalized for phrase in forbidden)


def _methodology(plan: ExperimentPlan | None) -> dict[str, Any]:
    if plan is None:
        return {}
    return {
        "paired_inputs": (
            "Algorithms share one frozen analysis case, demand, control timeline, and seed."
        ),
        "automatic_conclusion": False,
        "limitations": [
            (
                "Facility closures are projected to routing-topology closed edges. Geometric "
                "barriers and one-way channels still constrain physical movement but are not "
                "reprojected as routing-edge closures in V0.2."
            ),
            "Process isolation is fault containment, not a security sandbox.",
        ],
    }
