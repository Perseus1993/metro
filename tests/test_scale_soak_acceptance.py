from __future__ import annotations

from metro_station_acceptance.scale_soak_acceptance import run_scale_soak_acceptance
from metro_station_testkit.scale_soak_catalog import SCALE_SOAK_WORKLOADS, scale_soak_cases


def test_scale_soak_catalog_has_four_workloads_and_two_repetitions() -> None:
    cases = scale_soak_cases()

    assert len(cases) == 8
    assert {str(case.factors["workload"]) for case in cases} == set(SCALE_SOAK_WORKLOADS)
    assert {int(case.factors["repetition"]) for case in cases} == {1, 2}


def test_four_workload_scale_soak_records_memory_accounting_and_regression() -> None:
    report = run_scale_soak_acceptance()

    assert report.status == "ok", [
        (result.case.case_id, result.status, result.checks, result.stages[-1].error)
        for result in report.results
    ]
    assert len(report.results) == 8
    assert all(result.stages[-1].metrics["person_accounting_error"] == 0 for result in report.results)
    assert all(result.stages[-1].metrics["rss_after_mb"] > 0 for result in report.results)
    assert report.checks["wall_and_peak_memory_regression_within_20_percent"]
    assert report.checks["no_child_process_leak"]
