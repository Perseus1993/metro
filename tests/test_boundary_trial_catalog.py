from __future__ import annotations

from collections import Counter

from metro_station_testkit.boundary_trial_catalog import (
    BOUNDARY_TRIAL_CASE_COUNT,
    boundary_trial_cases,
)


def test_boundary_trial_catalog_matches_planned_227_cases() -> None:
    cases = boundary_trial_cases()
    assert len(cases) == BOUNDARY_TRIAL_CASE_COUNT == 227
    assert len({case.case_id for case in cases}) == 227
    assert Counter(case.factors["group"] for case in cases) == {
        "A": 28,
        "B": 8,
        "C": 92,
        "D": 17,
        "E": 26,
        "F": 19,
        "G": 37,
    }


def test_boundary_trial_catalog_has_no_unresolved_audits() -> None:
    cases = boundary_trial_cases()
    assert {case.expected_class for case in cases} == {"VALID", "INVALID"}
    assert all(case.expected_diagnostic_codes for case in cases if case.expected_class == "INVALID")
