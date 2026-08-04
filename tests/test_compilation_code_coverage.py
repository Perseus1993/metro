from __future__ import annotations

import os
import sys
from collections import Counter
from types import FrameType

import pytest

from metro_station.adapters.simulation.compilation.validation import validate_station_design
from metro_station_testkit.compilation_code_inventory import (
    COMPILATION_SOURCE_DIR,
    discover_compilation_codes,
    discover_emitter_sites,
    discover_literal_code_sites,
    discover_producer_sites,
)
from metro_station_testkit.compilation_negative_cases import (
    CompilationNegativeCase,
    compilation_negative_cases,
    validate_control_case,
    validate_negative_case,
)
from metro_station_testkit.layout_corpus import generate_scenario_corpus
from metro_station_testkit.layout_scenario_generator import generate_layout


COMPILATION_CASES = compilation_negative_cases()
FAST_CORPUS_RECIPES = 32
CORPUS_REHEARSAL_RECIPES = 256
SPATIAL_CAPACITY_EXTENSION_CODES = frozenset(
    {
        "capacity.certificate_duplicate",
        "capacity.certificate_empty",
        "capacity.coactive_slot_conflict",
        "capacity.demand_exceeds_storage",
        "capacity.forecast_margin_low",
        "capacity.internal_slot_conflict",
        "capacity.policy_mismatch",
        "capacity.slot_outside_certificate_domain",
        "corridors.outside_walkable_area",
        "holding.capacity_below_required",
        "platform.capacity_below_required",
        "release.batch_not_placeable",
        "release.capacity_not_materialized",
        "release.route_not_traversable",
    }
)


def test_01_inventory_matches_executable_case_registry() -> None:
    discovered = discover_compilation_codes()
    declared = {case.expected_code for case in COMPILATION_CASES}
    emitter_sites = discover_emitter_sites()
    producer_sites = discover_producer_sites()
    literal_sites = discover_literal_code_sites()

    assert discovered
    assert declared == discovered
    assert {site.code for site in emitter_sites if site.code is not None} <= discovered
    assert {site.code for site in literal_sites} == discovered
    assert len({(site.file, site.line) for site in emitter_sites}) == len(emitter_sites)
    assert len({(site.file, site.line) for site in producer_sites}) == len(producer_sites)
    assert all(case.status == "active" for case in COMPILATION_CASES)
    assert len({case.case_id for case in COMPILATION_CASES}) == len(COMPILATION_CASES)
    assert all(case.expected_path for case in COMPILATION_CASES)
    assert all(case.changed_fields for case in COMPILATION_CASES)
    assert all(case.validator and case.mutation for case in COMPILATION_CASES)


def test_01b_spatial_capacity_extension_keeps_all_14_diagnostic_contracts() -> None:
    """Keep the 14 new spatial-capacity contracts explicit and executable."""

    module_codes = {
        site.code
        for site in discover_literal_code_sites()
        if site.file.name == "spatial_capacity.py"
    }
    extension_cases = tuple(
        case
        for case in COMPILATION_CASES
        if case.expected_code in SPATIAL_CAPACITY_EXTENSION_CODES
    )

    # queues.capacity_not_materialized predates the spatial-capacity extension.
    assert module_codes - {"queues.capacity_not_materialized"} == (
        SPATIAL_CAPACITY_EXTENSION_CODES
    )
    assert {case.expected_code for case in extension_cases} == (
        SPATIAL_CAPACITY_EXTENSION_CODES
    )
    assert len(SPATIAL_CAPACITY_EXTENSION_CODES) == 14
    assert len(extension_cases) == 18
    assert all(case.status == "active" for case in extension_cases)
    assert all(not case.allowed_codes for case in extension_cases)


@pytest.mark.parametrize(
    "case",
    COMPILATION_CASES,
    ids=lambda case: case.case_id,
)
def test_02_control_to_mutant_pair_kills_diagnostic_mutations(
    case: CompilationNegativeCase,
) -> None:
    """Reject missing/substituted outcomes and whole-decision false positives."""

    control = _record_issues(validate_control_case(case))
    mutant = _record_issues(validate_negative_case(case))
    mutant_codes = {item[1] for item in mutant}

    assert control == (), f"positive control is not clean: {case.case_id}: {control!r}"
    assert mutant, case.case_id
    assert mutant_codes == set(case.expected_codes), case.case_id
    target_signatures = [
        (severity, code, path)
        for severity, code, path, _message in mutant
        if code == case.expected_code
    ]
    assert target_signatures == [
        (case.expected_severity, case.expected_code, case.expected_path)
    ], case.case_id
    assert any(
        severity == case.expected_severity
        and code == case.expected_code
        and case.expected_path == path
        for severity, code, path, _message in mutant
    ), case.case_id


def test_03_every_concrete_emitter_site_is_executed_by_a_mutant() -> None:
    emitter_sites = discover_emitter_sites()
    producer_sites = discover_producer_sites()
    visited_by_case: dict[str, frozenset[tuple[str, int]]] = {}

    for case in COMPILATION_CASES:
        _issues, case_lines = _trace_negative_case(case)
        visited_by_case[case.case_id] = case_lines

    targeted_emitter_ids: set[str] = set()
    for case in COMPILATION_CASES:
        module_name, function_name = case.validator.rsplit(".", 1)
        matches = tuple(
            site
            for site in emitter_sites
            if site.file.stem == module_name
            and site.function == function_name
            and site.line == case.target_emitter_line
            and (site.code is None or site.code == case.expected_code)
        )
        assert len(matches) == 1, case.case_id
        site = matches[0]
        location = (os.path.normcase(str(site.file.resolve())), site.line)
        assert location in visited_by_case[case.case_id], case.case_id
        targeted_emitter_ids.add(site.site_id)

    assert targeted_emitter_ids == {site.site_id for site in emitter_sites}

    targeted_producer_ids: set[str] = set()
    for case in COMPILATION_CASES:
        if case.target_producer_line is None:
            continue
        matches = tuple(
            site
            for site in producer_sites
            if site.code == case.expected_code
            and site.line == case.target_producer_line
        )
        assert len(matches) == 1, case.case_id
        site = matches[0]
        location = (os.path.normcase(str(site.file.resolve())), site.line)
        assert location in visited_by_case[case.case_id], case.case_id
        targeted_producer_ids.add(site.site_id)

    assert targeted_producer_ids == {site.site_id for site in producer_sites}


@pytest.mark.parametrize(
    "case",
    COMPILATION_CASES,
    ids=lambda case: case.case_id,
)
def test_04_cases_are_deterministic_and_reproducible(
    case: CompilationNegativeCase,
) -> None:
    first_control = _record_issues(validate_control_case(case))
    second_control = _record_issues(validate_control_case(case))
    first_mutant = _record_issues(validate_negative_case(case))
    second_mutant = _record_issues(validate_negative_case(case))

    assert first_control == second_control, case.case_id
    assert first_mutant == second_mutant, case.case_id


def test_05_fast_generated_recipe_false_positive_gate() -> None:
    _assert_generated_corpus_is_compiler_clean(FAST_CORPUS_RECIPES)


def test_06_256_recipe_pre_topology_extension_smoke_gate() -> None:
    if os.getenv("METRO_RUN_256_RECIPE_PRECHECK", "0") != "1":
        pytest.skip("Set METRO_RUN_256_RECIPE_PRECHECK=1 for the release corpus gate.")

    _assert_generated_corpus_is_compiler_clean(CORPUS_REHEARSAL_RECIPES)


def _assert_generated_corpus_is_compiler_clean(count: int) -> None:
    corpus = generate_scenario_corpus(count=count, seed=20260803)
    fail_by_recipe: list[tuple[str, tuple[str, ...]]] = []
    errors_by_code: Counter[str] = Counter()
    for recipe in corpus.recipes:
        document = generate_layout(recipe)
        error_codes = tuple(
            sorted(
                {
                    issue.code
                    for issue in validate_station_design(document)
                    if issue.severity == "error"
                }
            )
        )
        if not error_codes:
            continue
        fail_by_recipe.append((recipe.recipe_id, error_codes))
        errors_by_code.update(error_codes)

    assert not fail_by_recipe, fail_by_recipe
    assert not errors_by_code


def _record_issues(issues) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (item.severity, item.code, item.path, item.message) for item in issues
    )


def _trace_negative_case(
    case: CompilationNegativeCase,
) -> tuple[tuple[tuple[str, str, str, str], ...], frozenset[tuple[str, int]]]:
    visited: set[tuple[str, int]] = set()
    source_root = COMPILATION_SOURCE_DIR.resolve()
    source_prefix = os.path.normcase(f"{source_root}{os.sep}")

    def local_trace(frame: FrameType, event: str, _argument):
        if event == "line":
            visited.add(
                (os.path.normcase(frame.f_code.co_filename), frame.f_lineno)
            )
        return local_trace

    def global_trace(frame: FrameType, event: str, _argument):
        if event != "call":
            return None
        filename = os.path.normcase(frame.f_code.co_filename)
        if filename.startswith(source_prefix):
            return local_trace
        return None

    previous = sys.gettrace()
    sys.settrace(global_trace)
    try:
        issues = _record_issues(validate_negative_case(case))
    finally:
        sys.settrace(previous)
    return issues, frozenset(visited)
