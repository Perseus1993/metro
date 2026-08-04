"""Bounded background-job registry for paired analysis comparisons."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from threading import Lock, Thread
from time import time
from typing import Any, Mapping
from uuid import uuid4

from metro_station.application.analysis_cases import AnalysisCase
from metro_station.application.comparisons import (
    AnalystDecision,
    ComparisonProgress,
    ComparisonReport,
    ComparisonRunSpec,
    ExperimentPlan,
)
from metro_station.bootstrap import execute_analysis_comparison

from .algorithm_api import execute_registered_experiment, experiment_plan_from_request


MAX_COMPARISON_JOBS = 20


@dataclass
class ComparisonJob:
    job_id: str
    spec: ComparisonRunSpec
    experiment_plan: ExperimentPlan | None = None
    status: str = "queued"
    progress: dict[str, Any] = field(default_factory=dict)
    report: ComparisonReport | None = None
    error: str | None = None
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)


_LOCK = Lock()
_JOBS: dict[str, ComparisonJob] = {}


def start_comparison_job(request: Mapping[str, Any]) -> dict[str, Any]:
    experiment_plan = _optional_experiment_plan(request)
    spec = (
        experiment_plan.comparison_spec()
        if experiment_plan is not None
        else comparison_spec_from_payload(request)
    )
    job = ComparisonJob(job_id=uuid4().hex, spec=spec, experiment_plan=experiment_plan)
    with _LOCK:
        _JOBS[job.job_id] = job
        _trim_jobs_locked()
    Thread(
        target=_run_job,
        args=(job.job_id,),
        name=f"comparison-job-{job.job_id[:8]}",
        daemon=True,
    ).start()
    return _job_payload(job)


def comparison_job_payload(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return None if job is None else _job_payload(job)


def comparison_job_report(job_id: str) -> ComparisonReport | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return None if job is None else job.report


def record_decision(job_id: str, request: Mapping[str, Any]) -> dict[str, Any] | None:
    decision = AnalystDecision(
        recommendation=str(request.get("recommendation") or "more_evidence"),
        rationale=str(request.get("rationale") or ""),
        analyst=str(request.get("analyst") or ""),
    )
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job.report is None:
            return None
        job.report = replace(job.report, decision=decision)
        job.updated_at = time()
        return _job_payload(job)


def comparison_spec_from_payload(request: Mapping[str, Any]) -> ComparisonRunSpec:
    if request.get("schema_version") == "comparison-run-spec/v1":
        return ComparisonRunSpec.from_dict(request)
    baseline = AnalysisCase.from_dict(_object(request, "baseline"))
    candidate = AnalysisCase.from_dict(_object(request, "candidate"))
    return ComparisonRunSpec.create(
        baseline,
        candidate,
        density_radius_m=float(request.get("density_radius_m", 1.0)),
        density_threshold_persons_m2=_optional_float(
            request.get("density_threshold_persons_m2", 4.0)
        ),
    )


def _run_job(job_id: str) -> None:
    _update(job_id, status="running")
    try:
        with _LOCK:
            spec = _JOBS[job_id].spec
            experiment_plan = _JOBS[job_id].experiment_plan

        def callback(progress: ComparisonProgress) -> None:
            _record_progress(job_id, progress)

        if experiment_plan is not None:
            report = execute_registered_experiment(
                experiment_plan,
                progress_callback=callback,
            )
        else:
            report = execute_analysis_comparison(spec, progress_callback=callback)
    except Exception as exc:
        _update(job_id, status="error", error=f"{type(exc).__name__}: {exc}")
        return
    _update(job_id, status="done", report=report)


def _record_progress(job_id: str, progress: ComparisonProgress) -> None:
    _update(job_id, progress=progress.as_dict())


def _update(job_id: str, **changes: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = time()


def _job_payload(job: ComparisonJob) -> dict[str, Any]:
    total = int(job.progress.get("total_runs", len(job.spec.seeds) * 2))
    completed = int(job.progress.get("completed_runs", 0))
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": {**job.progress, "fraction": completed / total if total else 0.0},
        "report": None if job.report is None else job.report.as_dict(),
        "experiment_plan": (None if job.experiment_plan is None else job.experiment_plan.as_dict()),
        "error": job.error,
    }


def _trim_jobs_locked() -> None:
    finished = sorted(
        (job for job in _JOBS.values() if job.status not in {"queued", "running"}),
        key=lambda job: job.created_at,
    )
    while len(_JOBS) > MAX_COMPARISON_JOBS and finished:
        _JOBS.pop(finished.pop(0).job_id, None)


def _object(source: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return dict(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_experiment_plan(request: Mapping[str, Any]) -> ExperimentPlan | None:
    is_plan = request.get("schema_version") == "experiment-plan/v1"
    is_algorithm_axis = request.get("comparison_axis") == "evacuation_routing"
    if not is_plan and not is_algorithm_axis:
        return None
    return experiment_plan_from_request(request)
