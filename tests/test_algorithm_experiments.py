from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from metro_station.adapters.routing_plugins import RoutingAlgorithmRegistry
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.application.analysis_cases import create_analysis_case
from metro_station.application.comparisons import (
    ALGORITHM_ROLES,
    ExperimentPlan,
    RunSummary,
    run_algorithm_experiment,
)
from metro_station.bootstrap import execute_algorithm_experiment


EXAMPLE_MANIFEST = Path("examples/evacuation_routing_plugin/manifest.json")


def _analysis_case():
    return create_analysis_case(
        name="Routing algorithm comparison",
        design=create_design("visual_demo_station").as_dict(),
        operations={"entry_count_hour": 0, "exit_count_hour": 0},
        simulation={
            "demand_minutes": 1,
            "horizon_minutes": 2,
            "tick_seconds": 10,
            "group_size": 1,
            "movement_backend": "batched_jupedsim",
            "scenario_mode": "evacuation",
            "evacuation": {
                "initial_platform_persons": 1,
                "alarm_delay_seconds": 0.0,
                "stop_train_service": True,
            },
        },
        seeds=(7, 42, 99),
    )


def _registry_and_plan():
    registry = RoutingAlgorithmRegistry.with_baseline()
    registry.register_manifest_file(EXAMPLE_MANIFEST)
    catalog = registry.catalog()
    selections = tuple(
        registry.preflight({"registration_id": item["registration_id"], "parameters": {}})
        for item in catalog
    )
    plan = ExperimentPlan.create(_analysis_case(), (selections[0], selections[1]))
    return registry, plan


def _summary(role, seed, selection, fingerprint):
    return RunSummary(
        role=role,
        case_id="case",
        seed=seed,
        status="ok",
        cleared=True,
        right_censored=False,
        clearance_time_s=10.0,
        remaining_agents=0,
        total_agents=1,
        peak_density_persons_m2=1.0,
        density_exposure_person_s=1.0,
        density_duration_above_threshold_s=0.0,
        max_gate_queue=0,
        max_vertical_queue=0,
        stuck_agents=0,
        algorithm_id=selection.plugin_id,
        algorithm_version=selection.plugin_version,
        algorithm_parameters=selection.parameters,
        paired_input_fingerprint=fingerprint,
        simulation_duration_ms=5.0,
        routing_compute_duration_ms=1.0,
        routing_decision_logs=({"request_id": f"{role}:{seed}"},),
    )


def test_experiment_plan_round_trip_and_strict_pairing() -> None:
    _, plan = _registry_and_plan()

    restored = ExperimentPlan.from_dict(plan.as_dict())

    assert restored == plan
    assert restored.semantic_fingerprint == plan.semantic_fingerprint
    assert restored.comparison_spec().baseline.semantic_fingerprint == (
        restored.comparison_spec().candidate.semantic_fingerprint
    )
    with pytest.raises(ValueError, match="exactly match"):
        replace(plan, seeds=(7, 42))


def test_existing_comparison_engine_runs_six_algorithm_pairs_and_keeps_evidence() -> None:
    _, plan = _registry_and_plan()
    calls = []

    class Executor:
        def execute(self, analysis_case, *, seed, role, spec):
            calls.append((role, seed, analysis_case.semantic_fingerprint))
            selection = plan.algorithms[ALGORITHM_ROLES.index(role)]
            return _summary(role, seed, selection, plan.paired_input_fingerprint(seed))

    report = run_algorithm_experiment(plan, Executor())

    assert [(role, seed) for role, seed, _ in calls] == [
        ("baseline", 7),
        ("candidate", 7),
        ("baseline", 42),
        ("candidate", 42),
        ("baseline", 99),
        ("candidate", 99),
    ]
    assert len({fingerprint for _, _, fingerprint in calls}) == 1
    assert report.status == "completed"
    assert report.experiment_plan == plan
    assert report.aggregate["algorithm_execution"]["candidate"]["failure_rate"] == 0
    assert len(report.aggregate["algorithm_execution"]["candidate"]["decision_log_refs"]) == 3


def test_registry_preflight_rejects_parameters_before_opening_process() -> None:
    registry, _ = _registry_and_plan()
    example = next(item for item in registry.catalog() if item["source"] != "builtin")

    with pytest.raises(ValueError, match="invalid plugin parameters"):
        registry.preflight(
            {
                "registration_id": example["registration_id"],
                "parameters": {"cost_multiplier": 0},
            }
        )


def test_real_station_runs_builtin_and_external_plugin_with_three_paired_seeds() -> None:
    registry, plan = _registry_and_plan()

    with registry.open_plan(plan) as algorithms:
        report = execute_algorithm_experiment(plan, algorithms)

    assert report.status == "completed"
    assert len(report.runs) == 6
    assert all(run.routing_decision_logs for run in report.runs)
    assert {run.algorithm_id for run in report.runs} == {
        "metro.shortest_path",
        "example.dijkstra",
    }
    for seed in plan.seeds:
        fingerprints = {run.paired_input_fingerprint for run in report.runs if run.seed == seed}
        assert fingerprints == {plan.paired_input_fingerprint(seed)}


def test_timeout_marks_report_partial_and_preserves_baseline_runs(tmp_path: Path) -> None:
    plugin_path = tmp_path / "slow_plugin.py"
    plugin_path.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    manifest = json.loads(EXAMPLE_MANIFEST.read_text(encoding="utf-8"))
    manifest["plugin_id"] = "test.slow_router"
    manifest["entry_point"] = ["python", plugin_path.name]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry = RoutingAlgorithmRegistry.with_baseline()
    registry.register_manifest_file(manifest_path, timeout_seconds=0.05)
    selections = tuple(
        registry.preflight({"registration_id": item["registration_id"], "parameters": {}})
        for item in registry.catalog()
    )
    plan = ExperimentPlan.create(_analysis_case(), (selections[0], selections[1]))

    with registry.open_plan(plan) as algorithms:
        report = execute_algorithm_experiment(plan, algorithms)

    assert report.status == "partial"
    baseline = [run for run in report.runs if run.role == "baseline"]
    candidate = [run for run in report.runs if run.role == "candidate"]
    assert all(run.status == "ok" and run.routing_decision_logs for run in baseline)
    assert all(run.status == "error" and run.routing_decision_logs for run in candidate)
    assert {run.routing_decision_logs[-1]["failure_code"] for run in candidate} == {"timeout"}
    execution = report.aggregate["algorithm_execution"]
    assert execution["baseline"]["failure_rate"] == 0
    assert execution["candidate"]["failure_rate"] == 1
