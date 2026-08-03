from __future__ import annotations

from time import perf_counter
from typing import Any, Callable

from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station_testkit.demand_fault_catalog import (
    DEMAND_FAULT_GENERATOR_VERSION,
    DEMAND_PROFILES,
    FAULT_PROFILES,
    SEEDS,
    demand_fault_cases,
    demand_fault_config_counts,
)
from metro_station_testkit.demand_fault_scenarios import demand_fault_scenario
from metro_station_testkit.instant_movement_backend import InstantMovementBackend
from metro_station_testkit.layout_exploration_case import LayoutExplorationCase
from metro_station_testkit.layout_quality import inspect_layout_quality

from .demand_fault_runtime_checks import (
    failure_snapshot_window,
    runtime_checks,
    runtime_fingerprint,
    runtime_metrics,
)
from .layout_exploration_result import (
    ExplorationCaseResult,
    ExplorationStageResult,
    ExplorationSuiteReport,
    catalog_coverage,
)


BackendFactory = Callable[[], Any]


def run_demand_fault_acceptance(
    cases: tuple[LayoutExplorationCase, ...] | None = None,
    *,
    movement_backend_factory: BackendFactory = InstantMovementBackend,
) -> ExplorationSuiteReport:
    full_matrix = cases is None
    selected = demand_fault_cases() if full_matrix else cases
    assert selected is not None
    results = tuple(
        _run_case(case, movement_backend_factory=movement_backend_factory) for case in selected
    )
    counts = demand_fault_config_counts(selected)
    baseline_ids = {
        result.case.case_id for result in results if result.case.factors["fault"] == "BASELINE"
    }
    checks = {
        "planned_run_count_is_252": not full_matrix or len(selected) == 252,
        "baseline_config_count_is_12": not full_matrix or counts["baseline_configs"] == 12,
        "fault_config_count_is_72": not full_matrix or counts["fault_configs"] == 72,
        "three_seeds_covered": not full_matrix
        or {case.seed for case in selected} == set(SEEDS),
        "three_demands_covered": not full_matrix
        or {case.factors["demand"] for case in selected} == set(DEMAND_PROFILES),
        "six_fault_variants_covered": not full_matrix
        or {
            case.factors["fault"] for case in selected if case.factors["fault"] != "BASELINE"
        }
        == set(FAULT_PROFILES),
        "all_baseline_references_resolve": all(
            str(case.factors["baseline_case_id"]) in baseline_ids for case in selected
        ),
        "all_runs_meet_engineering_assertions": all(result.status == "ok" for result in results),
        "train_full_observed_in_matrix": _train_full_observed(results, selected),
    }
    max_error = max(
        (
            int(result.stages[-1].metrics.get("max_person_accounting_error", 0))
            for result in results
            if result.stages
        ),
        default=0,
    )
    return ExplorationSuiteReport(
        "PM028-E3",
        DEMAND_FAULT_GENERATOR_VERSION,
        results,
        {**catalog_coverage(selected), "config_counts": counts},
        checks,
        metadata={
            "max_person_accounting_error": max_error,
            "actual_runtime_seconds": round(
                sum(
                    float(result.stages[-1].metrics.get("elapsed_seconds", 0.0))
                    for result in results
                ),
                6,
            ),
            "movement_backend": movement_backend_factory.__name__,
        },
    )


def _run_case(
    case: LayoutExplorationCase,
    *,
    movement_backend_factory: BackendFactory,
) -> ExplorationCaseResult:
    try:
        scenario = demand_fault_scenario(case)
        station_design = scenario.station_design
        if station_design is None:
            raise ValueError("demand-fault scenario requires an embedded station design")
        quality = inspect_layout_quality(station_design)
        preflight = ExplorationStageResult(
            "preflight",
            "ok" if quality.status == "ok" else "review",
            diagnostic_codes=tuple(issue.code for issue in quality.issues),
            checks={"design_quality_valid": quality.status == "ok"},
            metrics={
                "levels": quality.level_count,
                "elements": quality.element_count,
                "graph_nodes": quality.graph_node_count,
            },
        )
        started = perf_counter()
        model = MetroStationModel(
            scenario,
            seed=case.seed,
            movement_backend=movement_backend_factory(),
        )
        frames = model.run()
        elapsed = perf_counter() - started
        metrics = runtime_metrics(model, frames, elapsed)
        checks = runtime_checks(model, frames, str(case.factors["fault"]))
        simulation = ExplorationStageResult(
            "simulation",
            "ok" if all(checks.values()) else "review",
            checks=checks,
            metrics=metrics,
        )
        first_failure_tick, snapshots = failure_snapshot_window(frames)
        artifacts = _artifacts(case, model, quality.design_fingerprint, metrics)
        if first_failure_tick is not None:
            artifacts["first_violation_tick"] = first_failure_tick
            artifacts["snapshot_window"] = snapshots
        result_checks = {
            "preflight_passed": preflight.passed,
            "simulation_passed": simulation.passed,
            "pairing_fingerprint_present": bool(case.factors["pairing_fingerprint"]),
        }
        return ExplorationCaseResult(
            case,
            "pass" if all(result_checks.values()) else "fail",
            (preflight, simulation),
            result_checks,
            artifacts,
        )
    except Exception as exc:
        return ExplorationCaseResult(
            case,
            "error",
            (
                ExplorationStageResult(
                    "simulation",
                    "review",
                    error=f"{type(exc).__name__}: {exc}",
                ),
            ),
            {"run_completed": False},
        )


def _artifacts(case, model, design_fingerprint: str, metrics: dict[str, Any]) -> dict[str, Any]:
    scenario = model.scenario
    return {
        "design_fingerprint": design_fingerprint,
        "pairing_fingerprint": case.factors["pairing_fingerprint"],
        "baseline_case_id": case.factors["baseline_case_id"],
        "run_semantic_fingerprint": runtime_fingerprint(model, metrics),
        "event_plan": {
            "facilities": [event.as_dict() for event in scenario.facility_availability_events],
            "control_plan": None
            if scenario.control_plan is None
            else scenario.control_plan.as_dict(),
            "train_service": [event.as_dict() for event in scenario.train_service_events],
            "train_capacity": [event.as_dict() for event in scenario.train_capacity_events],
        },
        "applied_events": {
            "facilities": model.disruption_controller.applied_event_dicts(),
            "controls": [
                event.as_dict() for event in model.control_timeline_controller.applied_events
            ],
            "train_service": model.train_disruption_controller.applied_event_dicts(),
            "train_capacity": model.train_disruption_controller.applied_capacity_event_dicts(),
        },
    }


def _train_full_observed(
    results: tuple[ExplorationCaseResult, ...],
    cases: tuple[LayoutExplorationCase, ...],
) -> bool:
    if not any(case.factors["fault"] == "F5A-TRAIN-FULL" for case in cases):
        return True
    return any(
        int(result.stages[-1].metrics.get("graph_event_counts", {}).get("train_full", 0)) > 0
        for result in results
        if result.case.factors["fault"] == "F5A-TRAIN-FULL" and result.stages
    )
