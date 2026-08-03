from __future__ import annotations

from .boundary_trial_contract_cases import contract_boundary_cases
from .layout_exploration_case import LayoutExplorationCase, validate_case_catalog


BOUNDARY_TRIAL_GENERATOR_VERSION = "boundary_trial_generator.v1"
BOUNDARY_TRIAL_CASE_COUNT = 227


def boundary_trial_cases() -> tuple[LayoutExplorationCase, ...]:
    cases = (
        *_clearance_cases(),
        *_footprint_cases(),
        *_size_cases(),
        *contract_boundary_cases(),
    )
    validate_case_catalog(cases)
    if len(cases) != BOUNDARY_TRIAL_CASE_COUNT:
        raise AssertionError(
            f"boundary catalog expected {BOUNDARY_TRIAL_CASE_COUNT} cases; got {len(cases)}"
        )
    return cases


def _clearance_cases() -> tuple[LayoutExplorationCase, ...]:
    variants = (
        ("CLEARANCE_BELOW", "INVALID", "layout.component_clearance_too_small"),
        ("CLEARANCE_EXACT", "VALID", None),
        ("CLEARANCE_ABOVE", "VALID", None),
        ("CLEARANCE_NOISE_LOW", "INVALID", "layout.component_clearance_too_small"),
        ("OVERLAP_BELOW", "INVALID", "layout.component_clearance_too_small"),
        ("OVERLAP_EXACT", "INVALID", "layout.component_clearance_too_small"),
        ("OVERLAP_ABOVE", "INVALID", "layout.components_overlap"),
    )
    fixtures = ("gate_elevator", "elevator_stairs", "shop_equipment", "queue_facility")
    return tuple(
        _case(
            f"E2-A-{fixture.upper()}-{variant}",
            expected,
            {"group": "A", "fixture": fixture, "variant": variant},
            code,
        )
        for fixture in fixtures
        for variant, expected, code in variants
    )


def _footprint_cases() -> tuple[LayoutExplorationCase, ...]:
    values = (
        ("FOOTPRINT_IN", "VALID", None),
        ("FOOTPRINT_EXACT", "VALID", None),
        ("FOOTPRINT_TOL_EXACT", "VALID", None),
        ("FOOTPRINT_TOL_OUT", "INVALID", "layout.component_outside_level_footprint"),
        ("VERTICAL_TOUCH", "VALID", None),
        ("VERTICAL_MISS", "INVALID", "layout.vertical_connector_misses_level"),
        ("QUEUE_TOL_EXACT", "VALID", None),
        ("QUEUE_TOL_OUT", "INVALID", "layout.queue_outside_level_footprint"),
    )
    return tuple(
        _case(
            f"E2-B-{variant}",
            expected,
            {"group": "B", "variant": variant},
            code,
        )
        for variant, expected, code in values
    )


def _size_cases() -> tuple[LayoutExplorationCase, ...]:
    kinds = (
        "entrance",
        "gate",
        "escalator",
        "stairs",
        "elevator",
        "platform_edge",
        "shop",
        "service_room",
        "equipment",
        "obstacle",
    )
    single_axis = (
        ("WIDTH_MIN_LOW", "INVALID", "layout.component_width_out_of_range"),
        ("WIDTH_MIN", "VALID", None),
        ("WIDTH_MAX", "VALID", None),
        ("WIDTH_MAX_HIGH", "INVALID", "layout.component_width_out_of_range"),
        ("HEIGHT_MIN_LOW", "INVALID", "layout.component_height_out_of_range"),
        ("HEIGHT_MIN", "VALID", None),
        ("HEIGHT_MAX", "VALID", None),
        ("HEIGHT_MAX_HIGH", "INVALID", "layout.component_height_out_of_range"),
    )
    cases = [
        _case(
            f"E2-C-{kind.upper()}-{variant}",
            expected,
            {"group": "C", "kind": kind, "variant": variant},
            code,
        )
        for kind in kinds
        for variant, expected, code in single_axis
    ]
    for kind in ("gate", "elevator", "platform_edge"):
        for corner in ("MIN_MIN", "MIN_MAX", "MAX_MIN", "MAX_MAX"):
            cases.append(
                _case(
                    f"E2-C-{kind.upper()}-CORNER-{corner}",
                    "VALID",
                    {"group": "C", "kind": kind, "variant": f"CORNER_{corner}"},
                )
            )
    return tuple(cases)


def _case(
    case_id: str,
    expected_class: str,
    factors: dict[str, object],
    diagnostic_code: str | None = None,
) -> LayoutExplorationCase:
    return LayoutExplorationCase(
        suite_id="PM028-E2",
        case_id=case_id,
        generator_version=BOUNDARY_TRIAL_GENERATOR_VERSION,
        expected_class=expected_class,
        factors=factors,
        expected_failure_stage="layout" if expected_class == "INVALID" else None,
        expected_diagnostic_codes=(() if diagnostic_code is None else (diagnostic_code,)),
    )
