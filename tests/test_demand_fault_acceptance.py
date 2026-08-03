from __future__ import annotations

from metro_station_acceptance.demand_fault_acceptance import run_demand_fault_acceptance
from metro_station_testkit.demand_fault_catalog import FAULT_PROFILES, demand_fault_cases


def _representative_cases():
    wanted = {"BASELINE", *FAULT_PROFILES}
    return tuple(
        case
        for case in demand_fault_cases()
        if case.seed == 41
        and case.factors["topology"] == "TB4"
        and case.factors["demand"] == "D2-COUNTER"
        and case.factors["fault"] in wanted
    )


def test_representative_baseline_and_all_fault_variants_pass_runtime_assertions() -> None:
    report = run_demand_fault_acceptance(_representative_cases())

    assert report.status == "ok"
    assert len(report.results) == 7
    assert all(result.status == "ok" for result in report.results), report.failed_case_ids
    assert report.metadata["max_person_accounting_error"] == 0
    assert report.checks["all_runs_meet_engineering_assertions"]


def test_same_seed_replay_has_identical_semantic_fingerprint() -> None:
    case = _representative_cases()[0]

    left = run_demand_fault_acceptance((case,)).results[0]
    right = run_demand_fault_acceptance((case,)).results[0]

    assert left.artifacts["run_semantic_fingerprint"] == right.artifacts["run_semantic_fingerprint"]
