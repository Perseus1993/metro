from __future__ import annotations

from metro_station_acceptance.boundary_trial_acceptance import (
    run_boundary_trial_acceptance,
)


def test_all_227_boundary_cases_meet_declared_expectations() -> None:
    report = run_boundary_trial_acceptance()
    assert report.status == "ok", report.failed_case_ids
    assert len(report.results) == 227
