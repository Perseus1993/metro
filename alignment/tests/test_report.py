from __future__ import annotations

import json

import pytest

from metro_alignment.metrics.fundamental import WALKING_SPEED_PROXY_KEY
from metro_alignment.report import (
    validate_report_payload,
    walking_speed_proxy_recommendation,
    write_report,
)


def _comparison() -> dict:
    return {
        "scene_id": "scene-v1",
        "overall_verdict": "hold",
        "observed_dataset_id": "observed-v1",
        "release_blockers": ["proxy evidence"],
        "analysis_contract": {"walking_speed_proxy": {"desired_speed_release_eligible": False}},
        "trusted_parameters": {"jupedsim_desired_speed_mps": 1.22},
        "parameter_validation": {
            "schema_version": "alignment_parameter_validation.v1",
            "independent_holdout": {"available": False, "dataset_id": None},
            "multi_seed": {"seed_n": 1, "min_required": 10, "converged": False},
            "uncertainty": {
                "kind": "not_estimated",
                "confidence_level": None,
                "estimate": None,
                "lower": None,
                "upper": None,
                "relative_half_width": None,
            },
        },
        "inputs": {"observed": {"sha256": "abc"}},
        "metrics": {
            WALKING_SPEED_PROXY_KEY: {
                "observed": 1.25,
                "simulated": 1.0,
                "verdict": "outside_band",
                "support": {
                    "observed": {
                        "point_n": 120,
                        "agent_n": 10,
                        "frame_n": 60,
                        "window_n": 2,
                        "source_canonical_row_n": 1000,
                        "unit": "correlated_observed_metric_contributors",
                    },
                    "simulated": {
                        "point_n": 80,
                        "episode_n": 7,
                        "passenger_n": 5,
                        "frame_n": 40,
                        "seed_n": 1,
                        "seed_values": [42],
                        "unit": "correlated_simulated_metric_contributors",
                    },
                    "independence_warning": "contributors are correlated",
                },
            }
        },
    }


def test_report_does_not_present_hold_evidence_as_validated(tmp_path) -> None:
    recommendation = walking_speed_proxy_recommendation(
        _comparison(), source="comparison.json"
    )
    assert recommendation.status == "candidate_not_validated"
    assert recommendation.current_value == 1.22
    assert recommendation.suggestion == 1.22
    assert recommendation.evidence["diagnostic_candidate_value"] == 1.25
    assert recommendation.evidence["parameter_change_authorized"] is False
    assert recommendation.evidence["desired_speed_release_eligible"] is False
    output = tmp_path / "report.json"
    write_report(
        output,
        [recommendation],
        release_decision="hold",
        source_artifacts={"comparison": {"path": "comparison.json", "sha256": "abc"}},
        comparison=_comparison(),
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["release_decision"] == "hold"
    assert payload["parameter_table"][0]["sample_support"]["observed"]["point_n"] == 120
    assert payload["source_artifacts"]["comparison"]["sha256"] == "abc"


def test_report_rejects_missing_evidence() -> None:
    comparison = _comparison()
    comparison["metrics"][WALKING_SPEED_PROXY_KEY]["support"]["observed"]["point_n"] = 0
    with pytest.raises(ValueError, match="observed support"):
        walking_speed_proxy_recommendation(comparison, source="comparison.json")


def test_report_never_authorizes_a_semantically_blocked_top_level_pass() -> None:
    comparison = _comparison()
    comparison["overall_verdict"] = "pass"
    recommendation = walking_speed_proxy_recommendation(
        comparison, source="comparison.json"
    )
    assert recommendation.status == "candidate_not_validated"
    assert recommendation.suggestion == 1.22
    assert recommendation.evidence["parameter_change_authorized"] is False


def test_report_validator_rejects_forged_decision_and_parameter_change() -> None:
    comparison = _comparison()
    recommendation = walking_speed_proxy_recommendation(
        comparison, source="comparison.json"
    )
    payload = {
        "release_decision": "pass",
        "parameter_table": [
            {
                **recommendation.__dict__,
                "suggestion": 1.25,
                "evidence": {
                    **recommendation.evidence,
                    "parameter_change_authorized": True,
                },
            }
        ],
    }
    errors = validate_report_payload(payload, comparison)
    assert errors


def test_report_can_authorize_only_a_fully_release_eligible_comparison() -> None:
    comparison = _comparison()
    comparison["overall_verdict"] = "pass"
    comparison["release_blockers"] = []
    comparison["metrics"][WALKING_SPEED_PROXY_KEY]["verdict"] = "within_band"
    comparison["analysis_contract"]["walking_speed_proxy"].update(
        {
            "semantics": "independently_validated_desired_speed_evidence",
            "desired_speed_release_eligible": True,
        }
    )
    comparison["metrics"][WALKING_SPEED_PROXY_KEY]["support"]["simulated"].update(
        {"seed_n": 10, "seed_values": list(range(10))}
    )
    comparison["parameter_validation"] = {
        "schema_version": "alignment_parameter_validation.v1",
        "independent_holdout": {"available": True, "dataset_id": "holdout-v1"},
        "multi_seed": {"seed_n": 10, "min_required": 10, "converged": True},
        "uncertainty": {
            "kind": "confidence_interval_95",
            "confidence_level": 0.95,
            "estimate": 1.25,
            "lower": 1.2,
            "upper": 1.3,
            "relative_half_width": 0.04,
        },
    }
    recommendation = walking_speed_proxy_recommendation(
        comparison, source="comparison.json"
    )
    assert recommendation.status == "validated"
    assert recommendation.suggestion == 1.25
    assert recommendation.evidence["desired_speed_release_eligible"] is True
    assert recommendation.evidence["parameter_change_authorized"] is True


def test_report_validator_binds_current_value_to_trusted_comparison_baseline() -> None:
    comparison = _comparison()
    recommendation = walking_speed_proxy_recommendation(comparison, source="comparison.json")
    payload = {
        "release_decision": "hold",
        "parameter_table": [
            {
                **recommendation.__dict__,
                "current_value": 999.0,
                "suggestion": 999.0,
            }
        ],
    }
    assert validate_report_payload(payload, comparison)


def test_single_seed_and_unestimated_uncertainty_never_authorize() -> None:
    comparison = _comparison()
    comparison["overall_verdict"] = "pass"
    comparison["release_blockers"] = []
    comparison["metrics"][WALKING_SPEED_PROXY_KEY]["verdict"] = "within_band"
    comparison["analysis_contract"]["walking_speed_proxy"][
        "desired_speed_release_eligible"
    ] = True
    recommendation = walking_speed_proxy_recommendation(comparison, source="comparison.json")
    assert recommendation.status == "candidate_not_validated"
    assert recommendation.suggestion == 1.22
    assert recommendation.evidence["parameter_change_authorized"] is False
