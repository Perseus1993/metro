from __future__ import annotations

from dataclasses import replace

import pytest

from metro_station.application.analysis_cases import clone_analysis_case
from metro_station.application.comparisons import (
    ComparisonRunSpec,
    RunSummary,
    build_comparison_report,
    build_run_summary,
    run_comparison,
)
from tests.test_analysis_cases import case


def summary(role: str, seed: int, *, clearance: float = 100.0) -> RunSummary:
    source = case() if role == "baseline" else clone_analysis_case(case(), name="Candidate")
    return RunSummary(
        role=role,
        case_id=source.case_id,
        seed=seed,
        status="ok",
        cleared=True,
        right_censored=False,
        clearance_time_s=clearance,
        remaining_agents=0,
        total_agents=10,
        peak_density_persons_m2=2.0 if role == "baseline" else 3.0,
        density_exposure_person_s=20.0,
        density_duration_above_threshold_s=10.0,
        max_gate_queue=0,
        max_vertical_queue=1,
        stuck_agents=0,
    )


def spec(seeds: tuple[int, ...] = (7, 42)) -> ComparisonRunSpec:
    baseline = replace(case(), seeds=seeds)
    candidate = clone_analysis_case(baseline, name="Candidate")
    return ComparisonRunSpec.create(baseline, candidate)


def test_run_summary_projects_clearance_density_queues_and_bottleneck() -> None:
    frames = [
        {
            "time_seconds": 0,
            "passengers": [{"id": 1, "x": 0, "y": 0, "n": 2, "current_level_id": "L1"}],
            "facilities": [
                {"id": "gate", "queue_persons": 2, "active_persons": 1, "queue_capacity": 3}
            ],
            "metrics": {"gate_queue_persons": 2, "vertical_queue_persons": 1},
            "control_events": [
                {
                    "event_id": "deploy_water",
                    "applied_seconds": 0.0,
                    "status": "applied",
                    "action": "deploy",
                }
            ],
        },
        {
            "time_seconds": 5,
            "passengers": [],
            "facilities": [],
            "metrics": {"gate_queue_persons": 0, "vertical_queue_persons": 0},
        },
    ]

    result = build_run_summary(
        role="baseline",
        case_id="case-a",
        seed=42,
        frames=frames,
        clearance={
            "cleared": True,
            "right_censored": False,
            "clearance_time_s": 5,
            "remaining_agents": 0,
            "total_agents": 2,
        },
        density_radius_m=1.0,
        density_threshold_persons_m2=0.5,
    )

    assert result.cleared is True
    assert result.peak_density_persons_m2 == pytest.approx(2 / 3.141592653589793, abs=1e-6)
    assert result.density_exposure_person_s == 10
    assert result.max_gate_queue == 2
    assert result.max_vertical_queue == 1
    assert result.top_bottleneck["facility_id"] == "gate"
    assert result.control_events[0]["event_id"] == "deploy_water"


def test_comparison_report_has_paired_and_aggregate_deltas() -> None:
    active_spec = spec((7,))
    baseline = summary("baseline", 7, clearance=100)
    candidate = replace(
        summary("candidate", 7, clearance=90),
        case_id=active_spec.candidate.case_id,
    )
    baseline = replace(baseline, case_id=active_spec.baseline.case_id)

    report = build_comparison_report(active_spec, (baseline, candidate))

    clearance = report.paired_results[0]["metrics"]["clearance_time_s"]
    assert report.status == "completed"
    assert clearance["delta"] == -10
    assert clearance["relative_change"] == -0.1
    density = report.aggregate["candidate_minus_baseline"]["peak_density_persons_m2"]
    assert density["mean_delta"] == 1
    assert report.decision.recommendation == "more_evidence"


def test_zero_baseline_relative_change_is_none() -> None:
    active_spec = spec((7,))
    baseline = replace(summary("baseline", 7), case_id=active_spec.baseline.case_id)
    candidate = replace(summary("candidate", 7), case_id=active_spec.candidate.case_id)

    report = build_comparison_report(active_spec, (baseline, candidate))

    queue = report.paired_results[0]["metrics"]["max_gate_queue"]
    assert queue["delta"] == 0
    assert queue["relative_change"] is None


def test_comparison_service_runs_strict_seed_pairs_and_keeps_failures() -> None:
    active_spec = spec((7, 42))
    calls = []
    progress = []

    class Executor:
        def execute(self, analysis_case, *, seed, role, spec):
            calls.append((role, seed))
            if role == "candidate" and seed == 42:
                raise RuntimeError("candidate failed")
            return replace(summary(role, seed), case_id=analysis_case.case_id)

    report = run_comparison(active_spec, Executor(), progress_callback=progress.append)

    assert calls == [("baseline", 7), ("candidate", 7), ("baseline", 42), ("candidate", 42)]
    assert report.status == "partial"
    assert len(progress) == 8
    assert progress[-1].as_dict()["step"] == 4
    assert progress[-1].as_dict()["total_steps"] == 4
    failed = next(run for run in report.runs if run.status == "error")
    assert failed.error == "RuntimeError: candidate failed"


def test_comparison_spec_rejects_mismatched_simulation_controls() -> None:
    baseline = case()
    candidate = clone_analysis_case(baseline, name="Candidate")
    candidate = replace(
        candidate,
        simulation={**candidate.simulation, "horizon_minutes": 16},
    )

    with pytest.raises(ValueError, match="simulation controls"):
        ComparisonRunSpec.create(baseline, candidate)
