from __future__ import annotations

from collections import Counter

from metro_station_testkit.demand_fault_catalog import demand_fault_cases
from metro_station_testkit.demand_fault_scenarios import demand_fault_scenario


def test_all_84_configs_preflight_with_real_targets() -> None:
    cases = demand_fault_cases()
    representative = {
        (case.factors["topology"], case.factors["demand"], case.factors["fault"]): case
        for case in cases
    }
    scenarios = [demand_fault_scenario(case) for case in representative.values()]

    assert len(scenarios) == 84
    assert Counter(
        scenario.station_design.metadata["demand_fault_topology_id"] for scenario in scenarios
    ) == {
        "TB1": 21,
        "TB2": 21,
        "TB3": 21,
        "TB4": 21,
    }


def test_each_demand_profile_uses_the_formal_segment_contract() -> None:
    cases = demand_fault_cases()
    profiles = {}
    for case in cases:
        if case.factors["fault"] == "BASELINE" and case.seed == 41:
            profiles[str(case.factors["demand"])] = demand_fault_scenario(case)

    assert profiles["D1-SKEW"].entry_entrance_weights == (
        ("entrance_a", 0.9),
        ("entrance_b", 0.1),
    )
    assert len(profiles["D2-COUNTER"].demand_segments) == 1
    assert len(profiles["D3-PULSE"].demand_segments) == 3
    assert profiles["D3-PULSE"].demand_segments[1].transfer_count_hour == 1200
