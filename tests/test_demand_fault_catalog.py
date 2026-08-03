from __future__ import annotations

from collections import Counter

from metro_station_testkit.demand_fault_catalog import (
    DEMAND_PROFILES,
    FAULT_PROFILES,
    SEEDS,
    demand_fault_cases,
    demand_fault_config_counts,
)
from metro_station_testkit.demand_fault_designs import (
    TOPOLOGY_BASES,
    generate_demand_fault_design,
)
from metro_station_testkit.layout_quality import inspect_layout_quality


def test_demand_fault_catalog_is_the_planned_252_run_matrix() -> None:
    cases = demand_fault_cases()

    assert demand_fault_config_counts(cases) == {
        "baseline_configs": 12,
        "fault_configs": 72,
        "runs": 252,
    }
    assert {case.seed for case in cases} == set(SEEDS)
    assert {case.factors["topology"] for case in cases} == set(TOPOLOGY_BASES)
    assert {case.factors["demand"] for case in cases} == set(DEMAND_PROFILES)
    assert {case.factors["fault"] for case in cases} == {"BASELINE", *FAULT_PROFILES}
    assert Counter(case.factors["fault"] for case in cases)["BASELINE"] == 36


def test_every_fault_run_references_exactly_one_same_seed_baseline() -> None:
    cases = demand_fault_cases()
    by_id = {case.case_id: case for case in cases}

    for case in cases:
        baseline = by_id[str(case.factors["baseline_case_id"])]
        assert baseline.factors["fault"] == "BASELINE"
        assert baseline.seed == case.seed
        assert baseline.factors["topology"] == case.factors["topology"]
        assert baseline.factors["demand"] == case.factors["demand"]
        assert baseline.factors["pairing_fingerprint"] == case.factors["pairing_fingerprint"]


def test_all_four_topology_bases_are_static_quality_valid() -> None:
    reports = {
        topology: inspect_layout_quality(generate_demand_fault_design(topology))
        for topology in TOPOLOGY_BASES
    }

    assert all(report.status == "ok" for report in reports.values()), reports
    assert {topology: report.level_count for topology, report in reports.items()} == {
        "TB1": 2,
        "TB2": 2,
        "TB3": 3,
        "TB4": 3,
    }
