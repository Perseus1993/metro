from __future__ import annotations

from collections import Counter

from metro_station_testkit.layout_quality import inspect_layout_quality
from metro_station_testkit.metamorphic_bases import (
    footprint_coverage,
    generate_metamorphic_base,
    metamorphic_base_recipes,
)
from metro_station_testkit.metamorphic_catalog import (
    INJECTIONS,
    TRANSFORMS,
    metamorphic_pair_cases,
    metamorphic_sensitivity_cases,
)


def test_metamorphic_catalog_has_100_pairs_and_50_sensitivity_cases() -> None:
    pairs = metamorphic_pair_cases()
    sensitivity = metamorphic_sensitivity_cases()

    assert len(pairs) == 100
    assert len(sensitivity) == 50
    assert Counter(case.factors["transform"] for case in pairs) == {
        transform: 20 for transform in TRANSFORMS
    }
    assert Counter(case.factors["injection"] for case in sensitivity) == {
        injection: 10 for injection in INJECTIONS
    }


def test_20_bases_cover_planned_layout_dimensions_and_are_valid() -> None:
    recipes = metamorphic_base_recipes()
    reports = [inspect_layout_quality(generate_metamorphic_base(index)) for index in range(20)]

    assert footprint_coverage() == {"RECT": 5, "L": 5, "T": 5, "NECK": 5}
    assert {recipe.level_count for recipe in recipes} == {1, 2, 3}
    assert {0, 1, 3, 6}.issubset({recipe.elevator_count for recipe in recipes})
    assert {recipe.asset_density for recipe in recipes} == {"sparse", "standard", "dense"}
    assert all(report.status == "ok" for report in reports), reports
