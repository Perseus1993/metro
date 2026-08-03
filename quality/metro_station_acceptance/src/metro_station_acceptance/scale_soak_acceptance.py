from __future__ import annotations

import multiprocessing
import time
import tracemalloc
from collections import defaultdict
from math import isfinite
from typing import Any, Callable

from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_testkit.demand_fault_catalog import demand_fault_cases
from metro_station_testkit.instant_movement_backend import InstantMovementBackend
from metro_station_testkit.layout_recipe import LayoutRecipe
from metro_station_testkit.layout_scenario_generator import generate_layout
from metro_station_testkit.scale_soak_catalog import (
    SCALE_SOAK_GENERATOR_VERSION,
    SCALE_SOAK_WORKLOADS,
    scale_soak_cases,
)

from .demand_fault_acceptance import run_demand_fault_acceptance
from .demand_fault_runtime_checks import runtime_checks, runtime_metrics
from .generated_scale_acceptance import _process_rss_mb
from .layout_exploration_result import (
    ExplorationCaseResult,
    ExplorationStageResult,
    ExplorationSuiteReport,
    catalog_coverage,
)


Workload = Callable[[], dict[str, Any]]


def run_scale_soak_acceptance(repetitions: int = 2) -> ExplorationSuiteReport:
    cases = scale_soak_cases(repetitions)
    workloads = _workloads()
    by_workload: dict[str, list[ExplorationCaseResult]] = defaultdict(list)
    results: list[ExplorationCaseResult] = []
    handles_before = _process_handle_count()
    children_before = len(multiprocessing.active_children())
    for case in cases:
        workload = str(case.factors["workload"])
        result = _run_soak_case(case, workloads[workload])
        by_workload[workload].append(result)
        results.append(result)
    handles_after = _process_handle_count()
    children_after = len(multiprocessing.active_children())
    regression_checks = {
        workload: _regression_check(workload_results)
        for workload, workload_results in by_workload.items()
    }
    checks = {
        "four_heavy_workloads_covered": set(by_workload) == set(SCALE_SOAK_WORKLOADS),
        "baseline_and_comparison_present": all(
            len(workload_results) == repetitions for workload_results in by_workload.values()
        ),
        "all_soak_executions_pass": all(result.status == "ok" for result in results),
        "wall_and_peak_memory_regression_within_20_percent": all(
            regression_checks.values()
        ),
        "no_child_process_leak": children_after == children_before,
        "process_handle_growth_bounded": (
            handles_before is None
            or handles_after is None
            or handles_after - handles_before <= 4
        ),
        "browser_lifecycle_covered_by_e5": True,
    }
    return ExplorationSuiteReport(
        suite_id="PM028-E6-SOAK",
        generator_version=SCALE_SOAK_GENERATOR_VERSION,
        results=tuple(results),
        coverage={
            **catalog_coverage(cases),
            "workload_regression_checks": regression_checks,
        },
        checks=checks,
        metadata={
            "repetitions": repetitions,
            "handles_before": handles_before,
            "handles_after": handles_after,
            "active_children_before": children_before,
            "active_children_after": children_after,
            "performance_policy": "second and later runs <= 120% of first-run baseline",
            "absolute_sla": "not frozen; workstation baseline only",
        },
    )


def _run_soak_case(case, workload: Workload) -> ExplorationCaseResult:
    rss_before = _process_rss_mb()
    tracemalloc.start()
    started = time.perf_counter()
    try:
        metrics = workload()
        wall_seconds = time.perf_counter() - started
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        rss_after = _process_rss_mb()
        simulated_seconds = float(metrics.get("simulated_seconds", 0.0))
        metrics = {
            **metrics,
            "wall_seconds": round(wall_seconds, 6),
            "real_time_factor": round(simulated_seconds / max(wall_seconds, 1e-9), 6),
            "traced_current_memory_mb": round(current_bytes / 1024 / 1024, 6),
            "traced_peak_memory_mb": round(peak_bytes / 1024 / 1024, 6),
            "rss_before_mb": round(rss_before, 6),
            "rss_after_mb": round(rss_after, 6),
            "rss_delta_mb": round(rss_after - rss_before, 6),
        }
        checks = {
            "execution_status_ok": metrics.get("execution_status") == "ok",
            "person_accounting_exact": int(metrics.get("person_accounting_error", -1)) == 0,
            "metrics_finite_non_negative": all(
                isfinite(float(value))
                and (key == "rss_delta_mb" or float(value) >= 0)
                for key, value in metrics.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            ),
            "frames_or_snapshots_present": int(metrics.get("snapshot_count", 0)) > 0,
            "traced_peak_memory_recorded": metrics["traced_peak_memory_mb"] > 0,
            "rss_recorded": metrics["rss_after_mb"] > 0,
        }
        stage = ExplorationStageResult(
            stage="soak",
            status="ok" if all(checks.values()) else "review",
            checks=checks,
            metrics=metrics,
        )
        return ExplorationCaseResult(
            case=case,
            observed_outcome="pass" if all(checks.values()) else "review",
            stages=(stage,),
            checks=checks,
        )
    except Exception as exc:
        return ExplorationCaseResult(
            case=case,
            observed_outcome="error",
            stages=(
                ExplorationStageResult(
                    stage="soak",
                    status="review",
                    error=f"{type(exc).__name__}: {exc}",
                ),
            ),
            checks={"execution_completed": False},
        )
    finally:
        tracemalloc.stop()


def _workloads() -> dict[str, Workload]:
    return {
        "HEAVY-SIX-ELEVATOR": _heavy_six_elevator_run,
        "BOTTLENECK-HALL": lambda: _demand_fault_run("TB4", "D1-SKEW", "BASELINE"),
        "DUAL-CONNECTOR-CLUSTER": lambda: _demand_fault_run(
            "TB4", "D2-COUNTER", "F1-ELEVATOR"
        ),
        "DEMAND-FAULT-COUPLING": lambda: _demand_fault_run(
            "TB3", "D3-PULSE", "F3-ESCALATOR"
        ),
    }


def _heavy_six_elevator_run() -> dict[str, Any]:
    document = generate_layout(
        LayoutRecipe(
            recipe_id="pm028-e6-soak-heavy-six",
            seed=20261201,
            archetype="three_level_transfer",
            entrance_count=4,
            gate_count=2,
            elevator_count=6,
            stairs_count=1,
            escalator_pair_count=1,
            mirror=True,
            asset_density="dense",
            geometry_variant=8,
            operation_profile="congested",
            topology_footprint="NECK",
            vertical_topology="DUAL_CLUSTER",
            fare_topology="SPLIT_ENTRY_EXIT",
        )
    )
    scenario = StationSandboxScenario(
        station_name="PM028 E6 heavy six elevator soak",
        hour=18,
        minutes=25,
        demand_minutes=15,
        tick_seconds=5,
        group_size=10,
        entry_count_hour=360,
        exit_count_hour=360,
        transfer_count_hour=360,
        source_label="PM-028-E6",
        sample_hours=1,
        station_design=document,
        train_headway_seconds=60,
        train_dwell_seconds=30,
        initial_train_offset_seconds=15,
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=42, movement_backend=InstantMovementBackend())
    started = time.perf_counter()
    frames = model.run()
    metrics = runtime_metrics(model, frames, time.perf_counter() - started)
    checks = runtime_checks(model, frames, "BASELINE")
    return {
        "execution_status": "ok" if all(checks.values()) else "review",
        "simulated_seconds": scenario.horizon_duration_seconds,
        "snapshot_count": len(frames),
        "trajectory_point_count": max(
            sum(len(frame.get("agents", ())) for frame in frames),
            int(metrics["spawned_persons"]),
        ),
        "facility_event_count": len(getattr(model, "facility_service_events", ())),
        "person_accounting_error": metrics["max_person_accounting_error"],
        "spawned_persons": metrics["spawned_persons"],
        "terminal_persons": metrics["terminal_persons"],
    }


def _demand_fault_run(topology: str, demand: str, fault: str) -> dict[str, Any]:
    case = next(
        item
        for item in demand_fault_cases()
        if item.seed == 42
        and item.factors["topology"] == topology
        and item.factors["demand"] == demand
        and item.factors["fault"] == fault
    )
    report = run_demand_fault_acceptance((case,))
    result = report.results[0]
    stage = result.stages[-1]
    metrics = stage.metrics
    return {
        "execution_status": "ok" if result.status == "ok" else "review",
        "simulated_seconds": 25 * 60,
        "snapshot_count": int(metrics.get("frame_count", 0)),
        "trajectory_point_count": int(metrics.get("spawned_persons", 0)),
        "facility_event_count": sum(
            len(events) for events in result.artifacts.get("applied_events", {}).values()
        ),
        "person_accounting_error": int(metrics.get("max_person_accounting_error", -1)),
        "spawned_persons": int(metrics.get("spawned_persons", 0)),
        "terminal_persons": int(metrics.get("terminal_persons", 0)),
    }


def _regression_check(results: list[ExplorationCaseResult]) -> bool:
    if len(results) < 2 or any(not result.stages for result in results):
        return False
    baseline = results[0].stages[-1].metrics
    if not baseline:
        return False
    baseline_wall = max(float(baseline["wall_seconds"]), 1e-9)
    baseline_memory = max(float(baseline["traced_peak_memory_mb"]), 1e-9)
    return all(
        float(result.stages[-1].metrics["wall_seconds"]) <= baseline_wall * 1.2
        and float(result.stages[-1].metrics["traced_peak_memory_mb"]) <= baseline_memory * 1.2
        for result in results[1:]
    )


def _process_handle_count() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        count = wintypes.DWORD()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        if kernel32.GetProcessHandleCount(kernel32.GetCurrentProcess(), ctypes.byref(count)):
            return int(count.value)
    except Exception:
        return None
    return None
