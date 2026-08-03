"""Sequential paired comparison coordination through an executor port."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..analysis_cases import AnalysisCase
from .contracts import ComparisonRunSpec, RunSummary
from .experiment import ExperimentPlan
from .report_contracts import ComparisonReport
from .reporting import build_comparison_report


@dataclass(frozen=True)
class ComparisonProgress:
    completed_runs: int
    total_runs: int
    role: str
    seed: int
    status: str

    def as_dict(self) -> dict[str, int | str]:
        return {
            "completed_runs": self.completed_runs,
            "total_runs": self.total_runs,
            "step": self.completed_runs,
            "total_steps": self.total_runs,
            "role": self.role,
            "seed": self.seed,
            "status": self.status,
        }


class ComparisonCaseExecutor(Protocol):
    def execute(
        self,
        case: AnalysisCase,
        *,
        seed: int,
        role: str,
        spec: ComparisonRunSpec,
    ) -> RunSummary: ...


ProgressCallback = Callable[[ComparisonProgress], None]


def run_comparison(
    spec: ComparisonRunSpec,
    executor: ComparisonCaseExecutor,
    *,
    progress_callback: ProgressCallback | None = None,
    experiment_plan: ExperimentPlan | None = None,
) -> ComparisonReport:
    total = len(spec.seeds) * 2
    completed = 0
    runs: list[RunSummary] = []
    for seed in spec.seeds:
        for role, case in (("baseline", spec.baseline), ("candidate", spec.candidate)):
            _progress(progress_callback, completed, total, role, seed, "running")
            summary = _execute(executor, case, seed=seed, role=role, spec=spec)
            runs.append(summary)
            completed += 1
            _progress(progress_callback, completed, total, role, seed, summary.status)
    return build_comparison_report(spec, runs, experiment_plan=experiment_plan)


def run_algorithm_experiment(
    plan: ExperimentPlan,
    executor: ComparisonCaseExecutor,
    *,
    progress_callback: ProgressCallback | None = None,
) -> ComparisonReport:
    """Run the algorithm axis through the existing paired comparison engine."""

    return run_comparison(
        plan.comparison_spec(),
        executor,
        progress_callback=progress_callback,
        experiment_plan=plan,
    )


def _execute(
    executor: ComparisonCaseExecutor,
    case: AnalysisCase,
    *,
    seed: int,
    role: str,
    spec: ComparisonRunSpec,
) -> RunSummary:
    try:
        return executor.execute(case, seed=seed, role=role, spec=spec)
    except Exception as exc:
        return RunSummary.failed(
            role=role,
            case_id=case.case_id,
            seed=seed,
            error=f"{type(exc).__name__}: {exc}",
        )


def _progress(
    callback: ProgressCallback | None,
    completed: int,
    total: int,
    role: str,
    seed: int,
    status: str,
) -> None:
    if callback is None:
        return
    callback(ComparisonProgress(completed, total, role, seed, status))
