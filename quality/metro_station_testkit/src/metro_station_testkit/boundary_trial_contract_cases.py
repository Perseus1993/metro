from __future__ import annotations

from .layout_exploration_case import LayoutExplorationCase


GENERATOR_VERSION = "boundary_trial_generator.v1"


def contract_boundary_cases() -> tuple[LayoutExplorationCase, ...]:
    cases = (*_queue_cases(), *_design_constraint_cases(), *_reference_cases(), *_numeric_cases())
    if len(cases) != 99:
        raise AssertionError(f"boundary contract catalog expected 99 cases; got {len(cases)}")
    return cases


def _queue_cases() -> tuple[LayoutExplorationCase, ...]:
    values = (
        ("SERVICE_1_999", "VALID", None),
        ("SERVICE_2_000", "VALID", None),
        ("SERVICE_2_001", "INVALID", "layout.queue_service_point_detached"),
        ("SERVICE_2_999_SPACING_1_2", "VALID", None),
        ("SERVICE_3_000_SPACING_1_2", "VALID", None),
        ("SERVICE_3_001_SPACING_1_2", "INVALID", "layout.queue_service_point_detached"),
        ("OWNER_LEVEL_MISMATCH", "INVALID", "layout.queue_owner_level_mismatch"),
        ("UNKNOWN_OWNER", "INVALID", "queues.unknown_owner"),
        ("OUTSIDE_FOOTPRINT", "INVALID", "layout.queue_outside_level_footprint"),
        ("QUEUE_OVERLAP", "INVALID", "quality.queues_overlap"),
        ("QUEUE_BLOCKS_COMPONENT", "INVALID", "quality.queue_blocks_component"),
        ("CAPACITY_ZERO", "INVALID", "queues.invalid_capacity"),
        ("CAPACITY_NEGATIVE", "INVALID", "queues.invalid_capacity"),
        (
            "CAPACITY_HUGE",
            "INVALID",
            "queues.capacity_exceeds_compiler_limit",
        ),
        ("SPACING_ZERO", "INVALID", "queues.invalid_spacing"),
        ("SPACING_NEGATIVE", "INVALID", "queues.invalid_spacing"),
        ("SPACING_NAN", "INVALID", "queues.invalid_spacing"),
    )
    return tuple(_case("D", variant, expected, code) for variant, expected, code in values)


def _design_constraint_cases() -> tuple[LayoutExplorationCase, ...]:
    values = (
        ("LEVELS_0", "INVALID", "levels.empty"),
        ("LEVELS_1", "VALID", None),
        ("LEVELS_3", "VALID", None),
        ("LEVELS_4", "INVALID", "levels.too_many"),
        ("FLOOR_HEIGHT_2_999", "INVALID", "levels.floor_height_out_of_range"),
        ("FLOOR_HEIGHT_3", "VALID", None),
        ("FLOOR_HEIGHT_12", "VALID", None),
        ("FLOOR_HEIGHT_12_001", "INVALID", "levels.floor_height_out_of_range"),
        ("DEPTH_27_999", "VALID", None),
        ("DEPTH_28", "VALID", None),
        ("DEPTH_28_001", "INVALID", "levels.depth_exceeded"),
        ("CANVAS_WITHIN", "VALID", None),
        ("CANVAS_EDGE", "VALID", None),
        ("CANVAS_OUT", "INVALID", "geometry.out_of_bounds"),
        ("GRID_ALIGNED", "VALID", None),
        ("GRID_OFFSET_1MM", "VALID", None),
        ("UNITS_METERS", "VALID", None),
        ("UNITS_UNKNOWN", "INVALID", "units.unsupported"),
        ("UNITS_EMPTY", "INVALID", "units.unsupported"),
        ("SCHEMA_CURRENT", "VALID", None),
        ("SCHEMA_UNKNOWN", "INVALID", "schema.unsupported"),
        ("SCHEMA_EMPTY", "INVALID", "schema.unsupported"),
        ("KIND_ALLOWED", "VALID", None),
        ("KIND_UNKNOWN", "INVALID", "elements.kind_not_allowed"),
        ("DUPLICATE_ORDER", "INVALID", "levels.duplicate_order"),
        ("DUPLICATE_ELEVATION", "INVALID", "levels.duplicate_elevation"),
    )
    return tuple(_case("E", variant, expected, code) for variant, expected, code in values)


def _reference_cases() -> tuple[LayoutExplorationCase, ...]:
    values = (
        ("DUPLICATE_LEVEL", "levels.duplicate_id"),
        ("DUPLICATE_ELEMENT", "elements.duplicate_id"),
        ("DUPLICATE_QUEUE", "queues.duplicate_id"),
        ("DUPLICATE_CONNECTION", "connections.duplicate_id"),
        ("DUPLICATE_PORT", "ports.duplicate_id"),
        ("DUPLICATE_SCENE_ENTITY", "scene.duplicate_entity_id"),
        ("DUPLICATE_RUNTIME_BINDING", "scene.duplicate_runtime_id"),
        ("DUPLICATE_ASSET_BINDING", "asset.duplicate_binding_id"),
        ("CONNECTION_UNKNOWN_ELEMENT", "connections.unknown_source"),
        ("CONNECTION_UNKNOWN_PORT", "connections.unknown_source_port"),
        ("QUEUE_UNKNOWN_OWNER", "queues.unknown_owner"),
        ("CONNECTOR_UNKNOWN_LEVEL", "connectors.unknown_level"),
        ("RUNTIME_UNKNOWN_ENTITY", "scene.runtime_unknown_entity"),
        ("ASSET_UNKNOWN_ASSET", "asset.unknown_asset"),
        ("ASSET_UNKNOWN_ENTITY", "asset.unknown_entity"),
        ("DUPLICATE_RUNTIME_ID", "scene.duplicate_runtime_id"),
        ("FINGERPRINT_TAMPER", "contract.fingerprint_mismatch"),
        ("POINTER_EXTERNAL", "replay.pointer_not_local"),
        ("POINTER_INVALID", "replay.pointer_not_local"),
    )
    return tuple(_case("F", variant, "INVALID", code) for variant, code in values)


def _numeric_cases() -> tuple[LayoutExplorationCase, ...]:
    fields = (
        "coordinate",
        "dimension",
        "rotation",
        "floor_height",
        "queue_capacity",
        "queue_spacing",
        "service_rate",
    )
    injections = ("NAN", "POS_INF", "NEG_INF", "NEG_ZERO", "HUGE")
    cases = []
    for field in fields:
        for injection in injections:
            expected, code = _numeric_expectation(field, injection)
            cases.append(
                _case(
                    "G",
                    f"{field.upper()}_{injection}",
                    expected,
                    code,
                    extra={"field": field, "injection": injection},
                )
            )
    cases.extend(
        (
            _case("G", "ID_EMPTY", "INVALID", "ids.blank"),
            _case("G", "ID_TOO_LONG", "INVALID", "ids.too_long"),
        )
    )
    return tuple(cases)


def _numeric_expectation(field: str, injection: str) -> tuple[str, str | None]:
    if injection in {"NAN", "POS_INF", "NEG_INF"}:
        return "INVALID", "numbers.non_finite"
    if injection == "NEG_ZERO":
        if field == "service_rate":
            return "VALID", None
        if field in {"dimension", "floor_height", "queue_capacity", "queue_spacing", "service_rate"}:
            return "INVALID", "numbers.non_positive"
        return "VALID", None
    if field in {"coordinate", "dimension", "floor_height", "queue_capacity"}:
        return "INVALID", "numbers.out_of_range"
    return "VALID", None


def _case(
    group: str,
    variant: str,
    expected_class: str,
    diagnostic_code: str | None,
    *,
    extra: dict[str, object] | None = None,
) -> LayoutExplorationCase:
    factors: dict[str, object] = {"group": group, "variant": variant}
    factors.update(extra or {})
    return LayoutExplorationCase(
        suite_id="PM028-E2",
        case_id=f"E2-{group}-{variant}",
        generator_version=GENERATOR_VERSION,
        expected_class=expected_class,
        factors=factors,
        expected_failure_stage="layout" if expected_class == "INVALID" else None,
        expected_diagnostic_codes=(() if diagnostic_code is None else (diagnostic_code,)),
    )
