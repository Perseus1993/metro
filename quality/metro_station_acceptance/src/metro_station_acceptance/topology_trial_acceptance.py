from __future__ import annotations

from typing import Any

from metro_station_testkit.layout_quality import inspect_layout_quality
from metro_station_testkit.topology_trial_catalog import (
    TOPOLOGY_TRIAL_GENERATOR_VERSION,
    topology_core_cases,
)
from metro_station_testkit.topology_trial_designs import generate_topology_trial_design
from metro_station_testkit.topology_trial_probes import (
    generate_topology_probe_design,
    topology_probe_cases,
)
from metro_station.adapters.simulation.compilation.validation import validate_station_design

from .generated_replay_contract import inspect_generated_replay_contract
from .layout_exploration_result import (
    ExplorationCaseResult,
    ExplorationStageResult,
    ExplorationSuiteReport,
    catalog_coverage,
)


def run_topology_trial_acceptance() -> ExplorationSuiteReport:
    core_cases = topology_core_cases()
    probe_cases = topology_probe_cases()
    cases = (*core_cases, *probe_cases)
    results = tuple(
        _run_case(case, probe=case.case_id.startswith("E1-PROBE")) for case in cases
    )
    checks = {
        "core_case_count_is_48": len(core_cases) == 48,
        "probe_case_count_is_16": len(probe_cases) == 16,
        "all_cases_meet_expectation": all(result.status == "ok" for result in results),
        "all_footprint_shapes_covered": len(
            {case.factors["footprint"] for case in core_cases}
        )
        == 4,
        "all_vertical_modes_covered": len(
            {case.factors["vertical"] for case in core_cases}
        )
        == 3,
        "all_fare_modes_covered": len({case.factors["fare"] for case in core_cases}) == 2,
        "both_mirror_states_covered": len({case.factors["mirror"] for case in core_cases})
        == 2,
    }
    return ExplorationSuiteReport(
        suite_id="PM028-E1",
        generator_version=TOPOLOGY_TRIAL_GENERATOR_VERSION,
        results=results,
        coverage=catalog_coverage(cases),
        checks=checks,
        metadata={"scope": "48 deterministic topology core cases"},
    )


def _run_case(case: Any, *, probe: bool = False) -> ExplorationCaseResult:
    try:
        document = (
            generate_topology_probe_design(case) if probe else generate_topology_trial_design(case)
        )
        if case.expected_class == "INVALID":
            return _invalid_result(case, document)
        quality = inspect_layout_quality(document)
        replay = inspect_generated_replay_contract(document)
        layout_stage = ExplorationStageResult(
            "layout",
            "ok" if quality.status == "ok" else "review",
            diagnostic_codes=tuple(issue.code for issue in quality.issues),
            checks=quality.checks,
            metrics={
                "levels": quality.level_count,
                "elements": quality.element_count,
                "queues": quality.queue_count,
                "graph_nodes": quality.graph_node_count,
                "graph_edges": quality.graph_edge_count,
            },
        )
        replay_stage = ExplorationStageResult(
            "replay",
            "ok" if replay.status == "ok" else "review",
            checks=replay.checks,
            metrics={
                "scene_entities": replay.scene_entity_count,
                "runtime_bindings": replay.runtime_binding_count,
                "asset_bindings": replay.asset_binding_count,
                "elevator_entities": replay.elevator_entity_count,
            },
        )
        checks = {
            "expected_valid_layout": quality.status == "ok",
            "expected_valid_replay": replay.status == "ok",
            "case_embedded_in_design": document.metadata.get("layout_exploration_case")
            == case.as_dict(),
        }
        return ExplorationCaseResult(
            case=case,
            observed_outcome="pass" if all(checks.values()) else "fail",
            stages=(layout_stage, replay_stage),
            checks=checks,
            artifacts={"design_fingerprint": quality.design_fingerprint},
        )
    except Exception as exc:
        return ExplorationCaseResult(
            case=case,
            observed_outcome="error",
            stages=(
                ExplorationStageResult(
                    "generation",
                    "review",
                    error=f"{type(exc).__name__}: {exc}",
                ),
            ),
            checks={"generation_completed": False},
        )


def _invalid_result(case: Any, document: Any) -> ExplorationCaseResult:
    issues = validate_station_design(document)
    codes = tuple(issue.code for issue in issues)
    expected_codes = set(case.expected_diagnostic_codes)
    checks = {
        "rejected_at_expected_stage": bool(issues),
        "expected_diagnostic_present": expected_codes.issubset(codes),
    }
    return ExplorationCaseResult(
        case=case,
        observed_outcome="reject" if issues else "pass",
        stages=(
            ExplorationStageResult(
                "layout",
                "ok" if all(checks.values()) else "review",
                diagnostic_codes=codes,
                checks=checks,
            ),
        ),
        checks=checks,
    )
