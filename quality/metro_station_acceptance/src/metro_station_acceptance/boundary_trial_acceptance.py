from __future__ import annotations

from typing import Any

from metro_station.adapters.simulation.design.layout_rules import element_size_limits
from metro_station_testkit.boundary_trial_catalog import (
    BOUNDARY_TRIAL_CASE_COUNT,
    BOUNDARY_TRIAL_GENERATOR_VERSION,
    boundary_trial_cases,
)

from .boundary_trial_design_probes import run_design_boundary_probe
from .boundary_trial_numeric_probes import run_numeric_probe
from .boundary_trial_reference_probes import run_reference_probe
from .layout_exploration_result import (
    ExplorationCaseResult,
    ExplorationStageResult,
    ExplorationSuiteReport,
    catalog_coverage,
)


def run_boundary_trial_acceptance() -> ExplorationSuiteReport:
    cases = boundary_trial_cases()
    results = tuple(_run_case(case) for case in cases)
    groups = {str(case.factors["group"]) for case in cases}
    checks = {
        "case_count_is_227": len(results) == BOUNDARY_TRIAL_CASE_COUNT,
        "all_groups_present": groups == set("ABCDEFG"),
        "no_audit_cases": all(case.expected_class != "AUDIT" for case in cases),
        "all_cases_meet_expectation": all(result.status == "ok" for result in results),
    }
    return ExplorationSuiteReport(
        "PM028-E2",
        BOUNDARY_TRIAL_GENERATOR_VERSION,
        results,
        catalog_coverage(cases),
        checks,
        metadata={"planned_case_count": BOUNDARY_TRIAL_CASE_COUNT},
    )


def _run_case(case: Any) -> ExplorationCaseResult:
    try:
        valid, codes = _observe(case)
        expectation_met = _expectation_met(case, valid, codes)
        checks = {
            "expected_validity": expectation_met,
            "no_unresolved_audit": case.expected_class != "AUDIT",
        }
        stage = ExplorationStageResult(
            "layout",
            "ok" if all(checks.values()) else "review",
            diagnostic_codes=codes,
            checks=checks,
        )
        return ExplorationCaseResult(
            case,
            "pass" if valid else "reject",
            (stage,),
            checks,
        )
    except Exception as exc:
        return ExplorationCaseResult(
            case,
            "error",
            (ExplorationStageResult("layout", "review", error=f"{type(exc).__name__}: {exc}"),),
            {"probe_completed": False},
        )


def _observe(case: Any) -> tuple[bool, tuple[str, ...]]:
    group = str(case.factors["group"])
    variant = str(case.factors["variant"])
    if group in {"A", "B", "D", "E"}:
        return run_design_boundary_probe(group, variant)
    if group == "C":
        return _size_probe(str(case.factors["kind"]), variant)
    if group == "F":
        return run_reference_probe(variant)
    if variant == "ID_EMPTY":
        return run_numeric_probe("id", "EMPTY")
    if variant == "ID_TOO_LONG":
        return run_numeric_probe("id", "TOO_LONG")
    return run_numeric_probe(str(case.factors["field"]), str(case.factors["injection"]))


def _size_probe(kind: str, variant: str) -> tuple[bool, tuple[str, ...]]:
    limits = element_size_limits(kind)
    if limits is None:
        raise ValueError(f"missing size limits for {kind!r}")
    width, height = _size_values(limits, variant)
    codes = []
    if not limits.min_width_m <= width <= limits.max_width_m:
        codes.append("layout.component_width_out_of_range")
    if not limits.min_height_m <= height <= limits.max_height_m:
        codes.append("layout.component_height_out_of_range")
    return not codes, tuple(codes)


def _size_values(limits: Any, variant: str) -> tuple[float, float]:
    width = limits.min_width_m
    height = limits.min_height_m
    if variant == "WIDTH_MIN_LOW":
        width -= 0.001
    elif variant == "WIDTH_MAX":
        width = limits.max_width_m
    elif variant == "WIDTH_MAX_HIGH":
        width = limits.max_width_m + 0.001
    elif variant == "HEIGHT_MIN_LOW":
        height -= 0.001
    elif variant == "HEIGHT_MAX":
        height = limits.max_height_m
    elif variant == "HEIGHT_MAX_HIGH":
        height = limits.max_height_m + 0.001
    elif variant.startswith("CORNER_"):
        width = limits.max_width_m if variant.split("_")[1] == "MAX" else limits.min_width_m
        height = limits.max_height_m if variant.split("_")[2] == "MAX" else limits.min_height_m
    return width, height


def _expectation_met(case: Any, valid: bool, codes: tuple[str, ...]) -> bool:
    if case.expected_class == "VALID":
        return valid
    if case.expected_class == "INVALID":
        return not valid and set(case.expected_diagnostic_codes).issubset(codes)
    return False

