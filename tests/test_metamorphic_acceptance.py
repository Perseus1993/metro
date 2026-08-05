from __future__ import annotations

import pytest

from metro_station_acceptance.metamorphic_acceptance import (
    run_metamorphic_acceptance_for_base,
)
from metro_station_testkit.metamorphic_catalog import (
    SENSITIVITY_BASE_INDICES,
    TRANSFORMS,
    metamorphic_pair_cases,
    metamorphic_sensitivity_cases,
)


def test_metamorphic_catalog_preserves_full_acceptance_coverage() -> None:
    pair_cases = metamorphic_pair_cases()
    sensitivity_cases = metamorphic_sensitivity_cases()

    assert len(pair_cases) == 100
    assert len(sensitivity_cases) == 50
    assert {case.factors["transform"] for case in pair_cases} == set(TRANSFORMS)


@pytest.mark.parametrize("base_index", range(20))
def test_metamorphic_and_sensitivity_acceptance_by_base(base_index: int) -> None:
    report = run_metamorphic_acceptance_for_base(base_index)
    sensitivity_count = 5 if base_index in SENSITIVITY_BASE_INDICES else 0

    assert report.status == "ok", report.failed_case_ids
    assert len(report.results) == 5 + sensitivity_count
    assert report.coverage["sensitivity"] == {
        "detected": sensitivity_count,
        "total": sensitivity_count,
    }
