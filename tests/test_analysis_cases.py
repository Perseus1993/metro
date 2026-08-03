from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from metro_station.application.analysis_cases import (
    AnalysisCase,
    EvidenceStatus,
    analysis_case_from_json,
    analysis_case_to_json,
    clone_analysis_case,
    create_analysis_case,
    diff_analysis_cases,
    revise_case,
)


def case() -> AnalysisCase:
    return create_analysis_case(
        name="Baseline",
        design={
            "schema_version": "metro-station-design/v2",
            "elements": [{"id": "floor", "kind": "walkable_area"}],
            "levels": [],
            "queues": [],
            "connections": [],
        },
        operations={"entry_count_hour": 600, "exit_count_hour": 200},
        simulation={"demand_minutes": 3, "horizon_minutes": 15, "tick_seconds": 5},
        seeds=(7, 42, 99),
    )


def test_analysis_case_round_trip_preserves_semantics() -> None:
    original = case()

    restored = analysis_case_from_json(analysis_case_to_json(original))

    assert restored.as_dict() == original.as_dict()
    assert restored.semantic_fingerprint == original.semantic_fingerprint


def test_analysis_case_v1_matches_golden_file() -> None:
    path = Path("tests/fixtures/analysis_comparison/analysis_case_v1.json")
    source = path.read_text(encoding="utf-8")

    restored = analysis_case_from_json(source)

    assert analysis_case_to_json(restored) == source


def test_unknown_newer_analysis_case_schema_is_rejected() -> None:
    payload = case().as_dict()
    payload["schema_version"] = "analysis-case/v2"

    with pytest.raises(ValueError, match="unsupported analysis-case schema"):
        AnalysisCase.from_dict(payload)


def test_display_identity_does_not_change_semantic_fingerprint() -> None:
    original = case()
    clone = clone_analysis_case(original, name="Candidate")

    assert clone.case_id != original.case_id
    assert clone.parent_case_id == original.case_id
    assert clone.semantic_fingerprint == original.semantic_fingerprint
    assert diff_analysis_cases(original, clone) == ()


def test_browser_numeric_round_trip_does_not_change_fingerprint() -> None:
    original = case()
    original.design["origin"] = {"x": 0.0, "scale": 1.0, "spacing": 0.5}
    payload = original.as_dict()
    payload["design"]["origin"] = {"x": 0, "scale": 1, "spacing": 0.5}

    restored = AnalysisCase.from_dict(payload)

    assert restored.semantic_fingerprint == original.semantic_fingerprint


def test_water_barrier_is_the_only_decision_relevant_difference() -> None:
    baseline = case()
    candidate = clone_analysis_case(baseline, name="Candidate")
    changed = deepcopy(candidate.design)
    changed["elements"].append(
        {"id": "water_barrier_a", "kind": "obstacle", "metadata": {"blocking": True}}
    )

    candidate = revise_case(candidate, design=changed)
    differences = [item.as_dict() for item in diff_analysis_cases(baseline, candidate)]

    assert [item["path"] for item in differences] == ["design.elements.water_barrier_a"]
    assert differences[0]["kind"] == "added"


def test_case_rejects_invalid_clearance_window_and_duplicate_seeds() -> None:
    with pytest.raises(ValueError, match="demand_minutes"):
        create_analysis_case(
            name="Invalid",
            design={"elements": []},
            operations={},
            simulation={"demand_minutes": 3, "horizon_minutes": 3, "tick_seconds": 5},
        )
    with pytest.raises(ValueError, match="duplicates"):
        create_analysis_case(
            name="Invalid",
            design={"elements": []},
            operations={},
            simulation={"demand_minutes": 1, "horizon_minutes": 2, "tick_seconds": 5},
            seeds=(42, 42),
        )


def test_case_rejects_fingerprint_tampering() -> None:
    payload = case().as_dict()
    payload["operations"]["entry_count_hour"] = 601

    with pytest.raises(ValueError, match="fingerprint mismatch"):
        AnalysisCase.from_dict(payload)


def test_evidence_readiness_cannot_contradict_calibration_status() -> None:
    with pytest.raises(ValueError, match="contradicts"):
        EvidenceStatus.from_dict(
            {
                "schema_version": "evidence-status/v1",
                "calibration_profile_id": "default",
                "calibration_status": "uncalibrated",
                "research_ready": True,
                "product_version": "0.1.0",
                "model_version": "test",
                "safe_use_boundary": "internal only",
            }
        )
