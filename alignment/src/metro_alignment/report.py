from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any

from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.metrics.comparison import (
    OBSERVED_SUPPORT_KEYS,
    SIMULATED_SUPPORT_KEYS,
)
from metro_alignment.metrics.fundamental import WALKING_SPEED_PROXY_KEY

REPORT_SCHEMA_VERSION = "alignment_parameter_report.v5"


@dataclass(frozen=True)
class ParameterRecommendation:
    parameter: str
    current_value: Any
    observed_value: Any
    sample_support: dict[str, Any]
    source: str
    suggestion: Any
    status: str
    uncertainty: dict[str, Any]
    evidence: dict[str, Any]


def build_parameter_table(entries: list[ParameterRecommendation]) -> list[dict[str, Any]]:
    return [asdict(entry) for entry in entries]


def walking_speed_proxy_recommendation(
    comparison: dict[str, Any],
    *,
    source: str,
) -> ParameterRecommendation:
    metric = comparison.get("metrics", {}).get(WALKING_SPEED_PROXY_KEY)
    if not isinstance(metric, dict):
        raise TypeError(f"comparison lacks {WALKING_SPEED_PROXY_KEY}")
    observed = metric.get("observed")
    sample_support = metric.get("support", {})
    if not isinstance(sample_support, dict) or set(sample_support) != {
        "observed",
        "simulated",
        "independence_warning",
    }:
        raise ValueError("walking-speed proxy recommendation requires exact support sections")
    observed_support = sample_support.get("observed")
    simulated_support = sample_support.get("simulated")
    if not isinstance(observed_support, dict) or set(observed_support) != set(
        OBSERVED_SUPPORT_KEYS
    ):
        raise ValueError("walking-speed proxy recommendation requires exact observed support")
    if not isinstance(simulated_support, dict) or set(simulated_support) != set(
        SIMULATED_SUPPORT_KEYS
    ):
        raise ValueError("walking-speed proxy recommendation requires exact simulated support")
    observed_point_n = int(observed_support.get("point_n", 0))
    if observed is None or float(observed) <= 0.0 or observed_point_n <= 0:
        raise ValueError("walking-speed proxy recommendation requires observed support")
    try:
        current_value = float(
            comparison["trusted_parameters"]["jupedsim_desired_speed_mps"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("comparison lacks a trusted desired-speed baseline") from exc
    if not isfinite(current_value) or current_value <= 0.0:
        raise ValueError("trusted desired-speed baseline must be finite and > 0")
    overall = str(comparison.get("overall_verdict", "hold"))
    proxy_contract = comparison.get("analysis_contract", {}).get("walking_speed_proxy", {})
    desired_speed_release_eligible = (
        proxy_contract.get("desired_speed_release_eligible") is True
    )
    validation_errors = _parameter_validation_errors(
        comparison,
        observed=float(observed),
        sample_support=sample_support,
    )
    validation = comparison.get("parameter_validation", {})
    release_eligible = (
        overall == "pass"
        and metric.get("verdict") == "within_band"
        and not comparison.get("release_blockers")
        and desired_speed_release_eligible
        and not validation_errors
    )
    return ParameterRecommendation(
        parameter="jupedsim_desired_speed_mps",
        current_value=float(current_value),
        observed_value=float(observed),
        sample_support=sample_support,
        source=source,
        suggestion=float(observed) if release_eligible else float(current_value),
        status="validated" if release_eligible else "candidate_not_validated",
        uncertainty=dict(validation.get("uncertainty", {})),
        evidence={
            "comparison_verdict": metric.get("verdict"),
            "overall_verdict": overall,
            "metric_semantics": proxy_contract.get("semantics"),
            "desired_speed_release_eligible": desired_speed_release_eligible,
            "diagnostic_candidate_value": float(observed),
            "parameter_change_authorized": release_eligible,
            "parameter_validation": validation,
            "parameter_validation_errors": validation_errors,
            "comparison_input_hashes": comparison.get("inputs", {}),
        },
    )


def _parameter_validation_errors(
    comparison: dict[str, Any],
    *,
    observed: float,
    sample_support: dict[str, Any],
) -> list[str]:
    validation = comparison.get("parameter_validation")
    if not isinstance(validation, dict) or validation.get("schema_version") != (
        "alignment_parameter_validation.v1"
    ):
        return ["parameter validation contract is missing"]
    errors: list[str] = []
    holdout = validation.get("independent_holdout", {})
    holdout_id = holdout.get("dataset_id") if isinstance(holdout, dict) else None
    if (
        not isinstance(holdout, dict)
        or holdout.get("available") is not True
        or not isinstance(holdout_id, str)
        or not holdout_id.strip()
        or holdout_id == comparison.get("observed_dataset_id")
    ):
        errors.append("independent holdout evidence is unavailable")
    multi_seed = validation.get("multi_seed", {})
    simulated_seed_n = sample_support.get("simulated", {}).get("seed_n")
    if (
        not isinstance(multi_seed, dict)
        or not isinstance(multi_seed.get("seed_n"), int)
        or isinstance(multi_seed.get("seed_n"), bool)
        or multi_seed.get("seed_n") != simulated_seed_n
        or multi_seed.get("seed_n", 0) < 10
        or multi_seed.get("min_required") != 10
        or multi_seed.get("converged") is not True
    ):
        errors.append("multi-seed convergence evidence is insufficient")
    uncertainty = validation.get("uncertainty", {})
    try:
        estimate = float(uncertainty["estimate"])
        lower = float(uncertainty["lower"])
        upper = float(uncertainty["upper"])
        relative_half_width = float(uncertainty["relative_half_width"])
        expected_half_width = (upper - lower) / (2.0 * abs(estimate))
        uncertainty_valid = (
            uncertainty.get("kind") == "confidence_interval_95"
            and float(uncertainty.get("confidence_level")) == 0.95
            and all(
                isfinite(value)
                for value in (estimate, lower, upper, relative_half_width)
            )
            and estimate == observed
            and 0.0 < lower <= estimate <= upper
            and abs(relative_half_width - expected_half_width) <= 1e-12
            and relative_half_width <= 0.05
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        uncertainty_valid = False
    if not uncertainty_valid:
        errors.append("95% uncertainty interval is missing, inconsistent, or too wide")
    return errors


def validate_report_payload(payload: dict[str, Any], comparison: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("scene_id") != comparison.get("scene_id"):
        errors.append("parameter report scene_id contradicts comparison")
    rows = payload.get("parameter_table")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return ["parameter report must contain exactly one supported parameter row"]
    row = rows[0]
    try:
        expected = asdict(
            walking_speed_proxy_recommendation(
                comparison,
                source=str(row["source"]),
            )
        )
    except (KeyError, TypeError, ValueError) as exc:
        return [f"cannot deterministically rebuild parameter row: {exc}"]
    if row != expected:
        errors.append("parameter row differs from deterministic comparison-derived recommendation")
    expected_decision = (
        "pass" if expected["evidence"]["parameter_change_authorized"] is True else "hold"
    )
    if payload.get("release_decision") != expected_decision:
        errors.append("report release decision contradicts comparison-derived authorization")
    return errors


def write_report(
    path: Path,
    rows: list[ParameterRecommendation],
    *,
    release_decision: str,
    comparison: dict[str, Any],
    source_artifacts: dict[str, Any] | None = None,
) -> None:
    if release_decision not in {"pass", "hold"}:
        raise ValueError("release_decision must be pass or hold")
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "scene_id": comparison.get("scene_id"),
        "generated_at": datetime.now(UTC).isoformat(),
        "release_decision": release_decision,
        "source_artifacts": source_artifacts or {},
        "parameter_table": build_parameter_table(rows),
    }
    errors = validate_report_payload(payload, comparison)
    if errors:
        raise ValueError("invalid parameter report: " + "; ".join(errors))
    write_json_atomic(path, payload)
