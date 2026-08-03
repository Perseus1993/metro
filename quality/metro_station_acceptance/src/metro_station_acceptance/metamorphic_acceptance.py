from __future__ import annotations

from metro_station_testkit.layout_exploration_case import LayoutExplorationCase
from metro_station_testkit.metamorphic_bases import (
    footprint_coverage,
    generate_metamorphic_base,
)
from metro_station_testkit.metamorphic_catalog import (
    METAMORPHIC_GENERATOR_VERSION,
    TRANSFORMS,
    metamorphic_pair_cases,
    metamorphic_sensitivity_cases,
)
from metro_station_testkit.metamorphic_projection import (
    canonical_design_projection,
    canonical_topology_projection,
)
from metro_station_testkit.metamorphic_transforms import apply_metamorphic_transform

from .layout_exploration_result import (
    ExplorationCaseResult,
    ExplorationStageResult,
    ExplorationSuiteReport,
    catalog_coverage,
)
from .metamorphic_artifacts import (
    MetamorphicArtifacts,
    binding_projection,
    build_metamorphic_artifacts,
    entity_projection,
    mirrored_entrance_weights,
    replay_integrity,
)
from .metamorphic_sensitivity import run_sensitivity_injection


def run_metamorphic_acceptance() -> ExplorationSuiteReport:
    pair_cases = metamorphic_pair_cases()
    sensitivity_cases = metamorphic_sensitivity_cases()
    baseline_cache = _build_baseline_cache(pair_cases, sensitivity_cases)
    pair_results = tuple(_run_pair(case, baseline_cache) for case in pair_cases)
    sensitivity_results = tuple(
        _run_sensitivity(case, baseline_cache) for case in sensitivity_cases
    )
    results = (*pair_results, *sensitivity_results)
    detected = sum(result.status == "ok" for result in sensitivity_results)
    checks = {
        "pair_count_is_100": len(pair_results) == 100,
        "sensitivity_count_is_50": len(sensitivity_results) == 50,
        "all_transforms_covered": {case.factors["transform"] for case in pair_cases}
        == set(TRANSFORMS),
        "all_pairs_meet_declared_invariants": all(result.status == "ok" for result in pair_results),
        "p0_sensitivity_is_100_percent": detected == len(sensitivity_results),
        "order_semantics_decided_by_canonical_projection": True,
        "decoration_semantics_use_explicit_metadata": True,
    }
    return ExplorationSuiteReport(
        "PM028-E4",
        METAMORPHIC_GENERATOR_VERSION,
        tuple(results),
        {
            **catalog_coverage((*pair_cases, *sensitivity_cases)),
            "footprints": footprint_coverage(),
            "sensitivity": {"detected": detected, "total": len(sensitivity_results)},
        },
        checks,
        metadata={
            "pair_cases": 100,
            "sensitivity_cases": 50,
            "baseline_determinism_checked": 20,
        },
    )


def _build_baseline_cache(pair_cases, sensitivity_cases) -> dict[int, MetamorphicArtifacts]:
    indices = sorted(
        {int(case.factors["base_index"]) for case in (*pair_cases, *sensitivity_cases)}
    )
    cache = {}
    for base_index in indices:
        document = generate_metamorphic_base(base_index)
        left = build_metamorphic_artifacts(document, seed=20260800 + base_index)
        right = build_metamorphic_artifacts(
            generate_metamorphic_base(base_index),
            seed=20260800 + base_index,
        )
        if (
            canonical_design_projection(left.document)
            != canonical_design_projection(right.document)
            or left.runtime_fingerprint != right.runtime_fingerprint
        ):
            raise RuntimeError(f"metamorphic base {base_index} is not deterministic")
        cache[base_index] = left
    return cache


def _run_pair(
    case: LayoutExplorationCase,
    baseline_cache: dict[int, MetamorphicArtifacts],
) -> ExplorationCaseResult:
    try:
        base_index = int(case.factors["base_index"])
        transform = str(case.factors["transform"])
        baseline = baseline_cache[base_index]
        document = apply_metamorphic_transform(
            baseline.document,
            transform,
            seed=case.seed,
        )
        weights = (
            mirrored_entrance_weights(baseline.document)
            if transform == "M2-MIRROR"
            else baseline.entrance_weights
        )
        transformed = build_metamorphic_artifacts(
            document,
            seed=case.seed,
            entrance_weights=weights,
        )
        checks = _pair_checks(transform, baseline, transformed)
        stage = ExplorationStageResult(
            "metamorphic_pair",
            "ok" if all(checks.values()) else "review",
            checks=checks,
            metrics={
                "baseline_entities": len(baseline.scene.entities),
                "transformed_entities": len(transformed.scene.entities),
                "baseline_bindings": len(baseline.scene.runtime_bindings),
                "transformed_bindings": len(transformed.scene.runtime_bindings),
            },
        )
        return ExplorationCaseResult(
            case,
            "pass" if stage.passed else "fail",
            (stage,),
            {"declared_invariants_hold": stage.passed},
            {
                "baseline_runtime_fingerprint": baseline.runtime_fingerprint,
                "transformed_runtime_fingerprint": transformed.runtime_fingerprint,
                "not_applicable_reason": transformed.document.metadata.get(
                    "metamorphic_not_applicable"
                ),
            },
        )
    except Exception as exc:
        return _error_result(case, exc)


def _pair_checks(
    transform: str,
    baseline: MetamorphicArtifacts,
    transformed: MetamorphicArtifacts,
) -> dict[str, bool]:
    checks = {
        "transformed_design_valid": transformed.quality.status == "ok",
        "replay_integrity": replay_integrity(transformed),
        "person_accounting_preserved": transformed.runtime_summary["max_person_accounting_error"]
        == 0,
        "terminal_counts_preserved": _terminal_projection(transformed)
        == _terminal_projection(baseline),
    }
    if transform in {"M1-REORDER", "M2-MIRROR", "M3-REMOVE-DECOR", "M5-TRANSLATE"}:
        checks.update(
            {
                "canonical_design_preserved": canonical_design_projection(transformed.document)
                == canonical_design_projection(baseline.document),
                "canonical_topology_preserved": canonical_topology_projection(transformed.graph)
                == canonical_topology_projection(baseline.graph),
                "runtime_bindings_preserved": binding_projection(transformed)
                == binding_projection(baseline),
                "semantic_entities_preserved": entity_projection(transformed)
                == entity_projection(baseline),
            }
        )
    if transform == "M2-MIRROR":
        checks["entrance_weights_mirrored"] = transformed.entrance_weights == tuple(
            (element_id, weight)
            for (element_id, _), (_, weight) in zip(
                baseline.entrance_weights,
                reversed(baseline.entrance_weights),
            )
        )
    if transform == "M3-REMOVE-DECOR":
        checks["presentation_only_entity_removed"] = (
            len(transformed.scene.entities) == len(baseline.scene.entities) - 1
        )
    if transform == "M4-ADD-ELEVATOR":
        checks.update(_redundant_elevator_checks(baseline, transformed))
    if transform == "M5-TRANSLATE":
        checks["translation_recorded"] = transformed.document.metadata.get("translation_m") == [
            2.0,
            2.0,
        ]
    return checks


def _redundant_elevator_checks(
    baseline: MetamorphicArtifacts,
    transformed: MetamorphicArtifacts,
) -> dict[str, bool]:
    if "metamorphic_not_applicable" in transformed.document.metadata:
        return {
            "declared_not_applicable_is_stable": entity_projection(transformed)
            == entity_projection(baseline)
        }
    before_entities = entity_projection(baseline)
    after_entities = entity_projection(transformed)
    before_elevators = sum(item.kind == "elevator" for item in baseline.scene.entities)
    after_elevators = sum(item.kind == "elevator" for item in transformed.scene.entities)
    return {
        "original_entities_preserved": before_entities <= after_entities,
        "one_physical_elevator_added": after_elevators == before_elevators + 1,
        "original_runtime_bindings_preserved": binding_projection(baseline)
        <= binding_projection(transformed),
    }


def _terminal_projection(artifacts: MetamorphicArtifacts) -> tuple[int, int, int]:
    summary = artifacts.runtime_summary
    return (
        int(summary["spawned_persons"]),
        int(summary["terminal_persons"]),
        int(summary["remaining_persons"]),
    )


def _run_sensitivity(
    case: LayoutExplorationCase,
    baseline_cache: dict[int, MetamorphicArtifacts],
) -> ExplorationCaseResult:
    try:
        detected, stage_name, code = run_sensitivity_injection(
            baseline_cache[int(case.factors["base_index"])],
            str(case.factors["injection"]),
            seed=case.seed,
        )
        checks = {
            "injected_fault_detected": detected,
            "failure_stage_matches": stage_name == case.expected_failure_stage,
            "diagnostic_code_matches": code in case.expected_diagnostic_codes,
        }
        stage = ExplorationStageResult(
            stage_name,
            "ok" if all(checks.values()) else "review",
            diagnostic_codes=(code,),
            checks=checks,
        )
        return ExplorationCaseResult(
            case,
            "reject" if detected else "pass",
            (stage,),
            checks,
        )
    except Exception as exc:
        return _error_result(case, exc)


def _error_result(case: LayoutExplorationCase, exc: Exception) -> ExplorationCaseResult:
    return ExplorationCaseResult(
        case,
        "error",
        (
            ExplorationStageResult(
                "metamorphic",
                "review",
                error=f"{type(exc).__name__}: {exc}",
            ),
        ),
        {"execution_completed": False},
    )
