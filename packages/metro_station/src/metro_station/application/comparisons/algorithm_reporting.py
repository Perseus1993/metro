"""Validation and execution evidence for the routing-algorithm report axis."""

from __future__ import annotations

from typing import Any

from .contracts import RunSummary
from .experiment import ALGORITHM_ROLES, ExperimentPlan


def validate_algorithm_matrix(
    plan: ExperimentPlan,
    runs: tuple[RunSummary, ...],
) -> None:
    for role, selection in zip(ALGORITHM_ROLES, plan.algorithms, strict=True):
        selected = [run for run in runs if run.role == role]
        for run in selected:
            if (run.algorithm_id, run.algorithm_version) != (
                selection.plugin_id,
                selection.plugin_version,
            ):
                raise ValueError(f"{role} run algorithm identity does not match experiment plan")
            if run.algorithm_parameters != selection.parameters:
                raise ValueError(f"{role} run parameters do not match experiment plan")
            if run.paired_input_fingerprint != plan.paired_input_fingerprint(run.seed):
                raise ValueError(f"{role} run paired input fingerprint drifted")


def algorithm_execution(
    runs: tuple[RunSummary, ...],
    plan: ExperimentPlan | None,
) -> dict[str, Any]:
    if plan is None:
        return {}
    result: dict[str, Any] = {}
    for role, selection in zip(ALGORITHM_ROLES, plan.algorithms, strict=True):
        selected = [run for run in runs if run.role == role]
        failed = sum(run.status == "error" for run in selected)
        ok = sum(run.status == "ok" for run in selected)
        result[role] = {
            "algorithm_id": selection.plugin_id,
            "algorithm_version": selection.plugin_version,
            "parameters": selection.parameters,
            "runs": len(selected),
            "ok_runs": ok,
            "failed_runs": failed,
            "failure_rate": round(failed / len(selected), 6),
            "stability_rate": round(ok / len(selected), 6),
            "decision_log_count": sum(len(run.routing_decision_logs) for run in selected),
            "decision_log_refs": [
                log.get("request_id")
                for run in selected
                for log in run.routing_decision_logs
                if log.get("request_id")
            ],
        }
    return result
