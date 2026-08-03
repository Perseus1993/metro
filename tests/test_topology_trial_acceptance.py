from __future__ import annotations

from metro_station_acceptance.topology_trial_acceptance import (
    run_topology_trial_acceptance,
)
from metro_station_testkit.topology_trial_catalog import topology_core_cases
from metro_station_testkit.topology_trial_designs import generate_topology_trial_design
from metro_station_testkit.topology_trial_probes import topology_probe_cases


def test_topology_trial_catalog_has_exact_core_matrix() -> None:
    cases = topology_core_cases()
    assert len(cases) == 48
    assert {case.expected_class for case in cases} == {"VALID"}
    assert len({case.case_id for case in cases}) == 48


def test_adjacent_chain_and_split_fare_compile_without_fallback() -> None:
    case = next(
        case
        for case in topology_core_cases()
        if case.factors["footprint"] == "L"
        and case.factors["vertical"] == "CHAIN"
        and case.factors["fare"] == "SPLIT_ENTRY_EXIT"
        and case.factors["mirror"] is True
    )
    design = generate_topology_trial_design(case)
    gates = {element.gate_direction for element in design.elements if element.kind == "gate"}
    elevators = [element for element in design.elements if element.kind == "elevator"]

    assert gates == {"entry", "exit"}
    assert {len(element.connects_levels) for element in elevators} == {2}


def test_topology_probe_catalog_closes_all_initial_audits() -> None:
    cases = topology_probe_cases()
    assert len(cases) == 16
    assert {case.expected_class for case in cases} == {"VALID", "INVALID"}


def test_all_topology_core_and_probe_cases_meet_expectations() -> None:
    report = run_topology_trial_acceptance()
    assert report.status == "ok", report.failed_case_ids
    assert len(report.results) == 64
