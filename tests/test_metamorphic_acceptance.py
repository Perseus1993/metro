from __future__ import annotations

from metro_station_acceptance.metamorphic_acceptance import run_metamorphic_acceptance


def test_full_metamorphic_and_sensitivity_acceptance() -> None:
    report = run_metamorphic_acceptance()

    assert report.status == "ok", report.failed_case_ids
    assert len(report.results) == 150
    assert report.coverage["sensitivity"] == {"detected": 50, "total": 50}
