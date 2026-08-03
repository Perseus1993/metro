"""Build paired and aggregate comparison reports."""

from __future__ import annotations

from statistics import mean, median
from typing import Any, Iterable

from ..analysis_cases import diff_analysis_cases
from .contracts import ComparisonRunSpec, RunSummary
from .algorithm_reporting import algorithm_execution, validate_algorithm_matrix
from .experiment import ExperimentPlan
from .report_contracts import AnalystDecision, ComparisonReport


METRICS = (
    "clearance_time_s",
    "remaining_agents",
    "peak_density_persons_m2",
    "density_exposure_person_s",
    "density_duration_above_threshold_s",
    "max_gate_queue",
    "max_vertical_queue",
    "stuck_agents",
    "simulation_duration_ms",
    "routing_compute_duration_ms",
)


def build_comparison_report(
    spec: ComparisonRunSpec,
    runs: Iterable[RunSummary],
    *,
    decision: AnalystDecision | None = None,
    experiment_plan: ExperimentPlan | None = None,
) -> ComparisonReport:
    run_list = tuple(runs)
    _validate_run_matrix(spec, run_list)
    if experiment_plan is not None:
        validate_algorithm_matrix(experiment_plan, run_list)
    paired = tuple(_paired_result(seed, run_list) for seed in spec.seeds)
    ok_count = sum(run.status == "ok" for run in run_list)
    status = "completed" if ok_count == len(run_list) else "partial" if ok_count else "failed"
    return ComparisonReport(
        spec=spec,
        runs=run_list,
        status=status,
        input_differences=tuple(
            difference.as_dict()
            for difference in diff_analysis_cases(spec.baseline, spec.candidate)
        ),
        paired_results=paired,
        aggregate={
            "baseline": _role_aggregate(run_list, "baseline"),
            "candidate": _role_aggregate(run_list, "candidate"),
            "candidate_minus_baseline": _delta_aggregate(paired),
            "algorithm_execution": algorithm_execution(run_list, experiment_plan),
        },
        experiment_plan=experiment_plan,
        decision=decision or AnalystDecision(),
    )


def _paired_result(seed: int, runs: tuple[RunSummary, ...]) -> dict[str, Any]:
    baseline = next(run for run in runs if run.role == "baseline" and run.seed == seed)
    candidate = next(run for run in runs if run.role == "candidate" and run.seed == seed)
    return {
        "seed": seed,
        "status": "ok" if baseline.status == candidate.status == "ok" else "error",
        "baseline": baseline.as_dict(),
        "candidate": candidate.as_dict(),
        "metrics": {
            metric: _metric_pair(getattr(baseline, metric), getattr(candidate, metric))
            for metric in METRICS
        },
    }


def _metric_pair(baseline: Any, candidate: Any) -> dict[str, float | None]:
    if baseline is None or candidate is None:
        return {
            "baseline": baseline,
            "candidate": candidate,
            "delta": None,
            "relative_change": None,
        }
    baseline_value = float(baseline)
    candidate_value = float(candidate)
    delta = candidate_value - baseline_value
    relative = None if baseline_value == 0 else delta / baseline_value
    return {
        "baseline": baseline_value,
        "candidate": candidate_value,
        "delta": round(delta, 6),
        "relative_change": None if relative is None else round(relative, 6),
    }


def _role_aggregate(runs: tuple[RunSummary, ...], role: str) -> dict[str, Any]:
    selected = [run for run in runs if run.role == role]
    ok = [run for run in selected if run.status == "ok"]
    return {
        "runs": len(selected),
        "ok_runs": len(ok),
        "failed_runs": len(selected) - len(ok),
        "failure_rate": round((len(selected) - len(ok)) / len(selected), 6) if selected else 0.0,
        "stability_rate": round(len(ok) / len(selected), 6) if selected else 0.0,
        "cleared_runs": sum(run.cleared for run in ok),
        "right_censored_runs": sum(run.right_censored for run in ok),
        "metrics": {
            metric: _summary_values(
                [
                    float(value)
                    for run in ok
                    if (value := getattr(run, metric)) is not None
                    and (metric != "clearance_time_s" or run.cleared)
                ]
            )
            for metric in METRICS
        },
    }


def _delta_aggregate(paired: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for metric in METRICS:
        metric_pairs = [pair["metrics"][metric] for pair in paired if pair["status"] == "ok"]
        deltas = [float(item["delta"]) for item in metric_pairs if item["delta"] is not None]
        relatives = [
            float(item["relative_change"])
            for item in metric_pairs
            if item["relative_change"] is not None
        ]
        rows[metric] = {
            "sample_count": len(deltas),
            "mean_delta": _mean(deltas),
            "median_delta": _median(deltas),
            "mean_relative_change": _mean(relatives),
        }
    return rows


def _summary_values(values: list[float]) -> dict[str, float | int | None]:
    return {
        "sample_count": len(values),
        "mean": _mean(values),
        "median": _median(values),
        "min": None if not values else round(min(values), 6),
        "max": None if not values else round(max(values), 6),
    }


def _mean(values: list[float]) -> float | None:
    return None if not values else round(mean(values), 6)


def _median(values: list[float]) -> float | None:
    return None if not values else round(median(values), 6)


def _validate_run_matrix(spec: ComparisonRunSpec, runs: tuple[RunSummary, ...]) -> None:
    expected = {(role, seed) for seed in spec.seeds for role in ("baseline", "candidate")}
    actual = {(run.role, run.seed) for run in runs}
    if len(actual) != len(runs) or actual != expected:
        raise ValueError("run summaries must contain exactly one baseline/candidate pair per seed")
