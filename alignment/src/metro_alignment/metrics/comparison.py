from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

from metro_alignment.canonical import CANONICAL_SCHEMA_VERSION
from metro_alignment.metro_contract import SCENE_CONFIG_SCHEMA_VERSION

from .fundamental import (
    FUNDAMENTAL_MIN_BIN_N,
    METRIC_SCHEMA_VERSION,
    WALKING_SPEED_PROXY_KEY,
    analysis_contract_consistency_errors,
    fundamental_in_band_fraction,
)

WALKING_SPEED_PROXY_RELATIVE_ERROR_THRESHOLD = 0.15
FUNDAMENTAL_BAND_THRESHOLD = 0.8
FUNDAMENTAL_SUPPORT_THRESHOLD = 0.8
FUNDAMENTAL_MIN_SUPPORTED_BINS = 3
FUNDAMENTAL_MIN_DENSITY_HIGH_P_M2 = 0.3
COMPARISON_SCHEMA_VERSION = "alignment_comparison.v5"
OBSERVED_ARTIFACT_SCHEMA_VERSION = "alignment_observed_metrics.v5"
SIMULATION_ARTIFACT_SCHEMA_VERSION = "alignment_simulation_metrics.v5"
SOURCE_PREFLIGHT_ARTIFACT_SCHEMA_VERSION = "alignment_source_preflight_artifact.v2"
OBSERVED_SUPPORT_KEYS = frozenset(
    {"point_n", "agent_n", "frame_n", "window_n", "source_canonical_row_n", "unit"}
)
SIMULATED_SUPPORT_KEYS = frozenset(
    {"point_n", "episode_n", "passenger_n", "frame_n", "seed_n", "seed_values", "unit"}
)


@dataclass(frozen=True)
class ComparisonResult:
    observed: float | None
    simulated: float | None
    rel_error: float | None
    absolute_error: float | None
    verdict: str
    reason: str = ""
    support: dict[str, Any] | None = None


def geometry_release_blockers(
    simulation_artifact: dict[str, Any],
    *,
    trusted_geometry_status: str,
    trusted_evidence_sha256: str | None,
) -> list[str]:
    comparability = simulation_artifact.get("scientific_comparability", {})
    artifact_is_consistent = (
        isinstance(comparability, dict)
        and comparability.get("geometry_evidence_status") == trusted_geometry_status
        and comparability.get("geometry_evidence_sha256") == trusted_evidence_sha256
    )
    trusted_is_releasable = (
        trusted_geometry_status == "observed_matched"
        and isinstance(trusted_evidence_sha256, str)
        and len(trusted_evidence_sha256) == 64
    )
    if (
        not artifact_is_consistent
        or not trusted_is_releasable
        or comparability.get("release_eligible") is not True
    ):
        evidence = (
            comparability.get("geometry_evidence", "missing geometry evidence")
            if isinstance(comparability, dict)
            else "invalid geometry evidence"
        )
        return [f"simulation geometry is not observed-matched: {evidence}"]
    return []


def relative_error(observed: float, simulated: float) -> float:
    if not isfinite(observed) or not isfinite(simulated):
        raise ValueError("relative error inputs must be finite")
    if observed == 0.0:
        raise ValueError("relative error is undefined for an observed value of zero")
    return (simulated - observed) / observed


def _require_metric_payload(name: str, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise TypeError(f"{name} metrics must be an object")
    if payload.get("schema_version") != METRIC_SCHEMA_VERSION:
        raise ValueError(f"{name} metrics must use {METRIC_SCHEMA_VERSION}")


def _finite_number(name: str, value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _measurement_area_id(payload: dict[str, Any]) -> str | None:
    area = payload.get("method", {}).get("measurement_area", {})
    if not isinstance(area, dict) or not area.get("comparable"):
        return None
    value = area.get("id")
    return str(value) if value else None


def _analysis_contract(payload: dict[str, Any]) -> dict[str, Any] | None:
    contract = payload.get("analysis_contract")
    if not isinstance(contract, dict) or contract.get("schema_version") != (
        "alignment_analysis_contract.v1"
    ):
        return None
    return contract


def metric_support_errors(
    payload: object,
    metric_key: str,
    *,
    side: str,
    context: Mapping[str, Any] | None = None,
) -> list[str]:
    if not isinstance(payload, dict):
        return [f"{side} metric payload must be an object"]
    support_table = payload.get("metric_support")
    if not isinstance(support_table, dict):
        return [f"{side} metric support table must be an object"]
    support = support_table.get(metric_key)
    if not isinstance(support, dict):
        return [f"{side} {metric_key} support must be an object"]
    expected = OBSERVED_SUPPORT_KEYS if side == "observed" else SIMULATED_SUPPORT_KEYS
    if set(support) != set(expected):
        return [f"{side} {metric_key} support keys must exactly equal {sorted(expected)}"]
    errors: list[str] = []
    count_keys = expected - {"unit", "seed_values"}
    counts: dict[str, int] = {}
    for key in count_keys:
        value = support.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"{side} {metric_key} {key} must be a positive integer")
        else:
            counts[key] = value
    if side == "observed":
        if support.get("unit") != "correlated_observed_metric_contributors":
            errors.append(f"{side} {metric_key} support unit is invalid")
        if counts and not (
            counts.get("agent_n", 0) <= counts.get("point_n", 0)
            and counts.get("frame_n", 0) <= counts.get("point_n", 0)
            and counts.get("window_n", 0) <= counts.get("frame_n", 0)
            and counts.get("point_n", 0) <= counts.get("source_canonical_row_n", 0)
        ):
            errors.append(f"{side} {metric_key} support counts are inconsistent")
    else:
        seeds = support.get("seed_values")
        if support.get("unit") != "correlated_simulated_metric_contributors":
            errors.append(f"{side} {metric_key} support unit is invalid")
        if (
            not isinstance(seeds, list)
            or any(not isinstance(seed, int) or isinstance(seed, bool) for seed in seeds)
            or len(seeds) != counts.get("seed_n", -1)
            or len(set(seeds)) != len(seeds)
        ):
            errors.append(f"{side} {metric_key} seed support is inconsistent")
        if counts and not (
            counts.get("passenger_n", 0) <= counts.get("episode_n", 0) <= counts.get("point_n", 0)
            and counts.get("frame_n", 0) <= counts.get("point_n", 0)
        ):
            errors.append(f"{side} {metric_key} support counts are inconsistent")
    limits = context or {}
    exact_source_rows = limits.get("source_canonical_row_n")
    if (
        side == "observed"
        and exact_source_rows is not None
        and support.get("source_canonical_row_n") != exact_source_rows
    ):
        errors.append(f"{side} {metric_key} source row support is stale")
    expected_seed = limits.get("expected_seed")
    if (
        side == "simulated"
        and expected_seed is not None
        and (support.get("seed_n") != 1 or support.get("seed_values") != [expected_seed])
    ):
        errors.append(f"{side} {metric_key} seed support disagrees with manifest seed")
    for key in (
        "point_n",
        "agent_n",
        "frame_n",
        "window_n",
        "episode_n",
        "passenger_n",
    ):
        maximum = limits.get(f"max_{key}")
        if maximum is not None and (
            not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or support.get(key, 0) > maximum
        ):
            errors.append(f"{side} {metric_key} {key} exceeds source artifact support")
    if metric_key == WALKING_SPEED_PROXY_KEY:
        metric = payload.get(metric_key)
        if not isinstance(metric, dict):
            errors.append(f"{side} walking-speed metric must be an object")
        elif support.get("point_n") != int(metric.get("n", -1)):
            errors.append(f"{side} walking-speed support does not reconcile to metric n")
    elif metric_key == "fundamental_diagram":
        fundamental = payload.get("fundamental_diagram")
        bins = fundamental.get("bins") if isinstance(fundamental, dict) else None
        if not isinstance(bins, list) or any(not isinstance(row, dict) for row in bins):
            errors.append(f"{side} fundamental bins must be an array of objects")
        elif support.get("frame_n") != sum(int(row.get("n", 0)) for row in bins):
            errors.append(f"{side} FD frame support does not reconcile to binned frame n")
    return errors


def _comparison_support(
    observed: dict[str, Any], simulated: dict[str, Any], metric_key: str
) -> dict[str, Any]:
    return {
        "observed": observed.get("metric_support", {}).get(metric_key, {}),
        "simulated": simulated.get("metric_support", {}).get(metric_key, {}),
        "independence_warning": (
            "metric contributors are correlated within agents, windows, episodes, and seeds"
        ),
    }


def compare_metric_tables(
    observed: dict[str, Any],
    simulated: dict[str, Any],
    *,
    observed_support_context: Mapping[str, Any] | None = None,
    simulated_support_context: Mapping[str, Any] | None = None,
) -> dict[str, ComparisonResult]:
    _require_metric_payload("observed", observed)
    _require_metric_payload("simulated", simulated)
    support_errors = {
        metric_key: [
            *metric_support_errors(
                observed,
                metric_key,
                side="observed",
                context=observed_support_context,
            ),
            *metric_support_errors(
                simulated,
                metric_key,
                side="simulated",
                context=simulated_support_context,
            ),
        ]
        for metric_key in (WALKING_SPEED_PROXY_KEY, "fundamental_diagram")
    }
    walking_support = _comparison_support(observed, simulated, WALKING_SPEED_PROXY_KEY)
    fundamental_support = _comparison_support(observed, simulated, "fundamental_diagram")

    observed_errors = analysis_contract_consistency_errors(observed)
    simulated_errors = analysis_contract_consistency_errors(simulated)
    observed_contract = _analysis_contract(observed)
    simulated_contract = _analysis_contract(simulated)
    if (
        any(support_errors.values())
        or observed_errors
        or simulated_errors
        or observed_contract is None
        or (observed_contract != simulated_contract)
    ):
        reason = (
            "comparison requires internally consistent, identical normalized analysis contracts; "
            f"observed_errors={observed_errors}; simulated_errors={simulated_errors}; "
            f"support_errors={support_errors}"
        )
        unavailable_walking = ComparisonResult(
            observed=None,
            simulated=None,
            rel_error=None,
            absolute_error=None,
            verdict="unavailable",
            reason=reason,
            support=walking_support,
        )
        unavailable_fundamental = ComparisonResult(
            observed=None,
            simulated=None,
            rel_error=None,
            absolute_error=None,
            verdict="unavailable",
            reason=reason,
            support=fundamental_support,
        )
        return {
            WALKING_SPEED_PROXY_KEY: unavailable_walking,
            "fundamental_support_coverage": unavailable_fundamental,
            "fundamental_conditional_in_band_fraction": unavailable_fundamental,
        }

    observed_free = observed.get(WALKING_SPEED_PROXY_KEY)
    simulated_free = simulated.get(WALKING_SPEED_PROXY_KEY)
    if not isinstance(observed_free, dict) or not isinstance(simulated_free, dict):
        raise TypeError(f"both metric payloads require {WALKING_SPEED_PROXY_KEY}")
    observed_n = int(observed_free.get("n", 0))
    simulated_n = int(simulated_free.get("n", 0))
    if observed_n <= 0 or simulated_n <= 0:
        free_flow_result = ComparisonResult(
            observed=None,
            simulated=None,
            rel_error=None,
            absolute_error=None,
            verdict="unavailable",
            reason="walking-speed proxy comparison requires non-empty samples",
            support=walking_support,
        )
    else:
        observed_p50 = _finite_number("observed walking-speed proxy p50", observed_free.get("p50"))
        simulated_p50 = _finite_number(
            "simulated walking-speed proxy p50", simulated_free.get("p50")
        )
        if observed_p50 <= 0.0:
            free_flow_result = ComparisonResult(
                observed=observed_p50,
                simulated=simulated_p50,
                rel_error=None,
                absolute_error=simulated_p50 - observed_p50,
                verdict="unavailable",
                reason="observed walking-speed proxy p50 must be > 0",
                support=walking_support,
            )
        else:
            error = relative_error(observed_p50, simulated_p50)
            free_flow_result = ComparisonResult(
                observed=observed_p50,
                simulated=simulated_p50,
                rel_error=error,
                absolute_error=simulated_p50 - observed_p50,
                verdict=(
                    "within_band"
                    if abs(error) <= WALKING_SPEED_PROXY_RELATIVE_ERROR_THRESHOLD
                    else "outside_band"
                ),
                support=walking_support,
            )

    observed_area_id = _measurement_area_id(observed)
    simulated_area_id = _measurement_area_id(simulated)
    observed_profile = observed.get("fundamental_diagram", {}).get("bins", [])
    simulated_profile = simulated.get("fundamental_diagram", {}).get("bins", [])
    if not observed_area_id or observed_area_id != simulated_area_id:
        support_result = ComparisonResult(
            observed=FUNDAMENTAL_SUPPORT_THRESHOLD,
            simulated=None,
            rel_error=None,
            absolute_error=None,
            verdict="unavailable",
            reason="fundamental diagram requires the same explicit measurement_area_id",
            support=fundamental_support,
        )
        conditional_result = ComparisonResult(
            observed=FUNDAMENTAL_BAND_THRESHOLD,
            simulated=None,
            rel_error=None,
            absolute_error=None,
            verdict="unavailable",
            reason=support_result.reason,
            support=fundamental_support,
        )
    elif not observed_profile or not simulated_profile:
        support_result = ComparisonResult(
            observed=FUNDAMENTAL_SUPPORT_THRESHOLD,
            simulated=None,
            rel_error=None,
            absolute_error=None,
            verdict="unavailable",
            reason="fundamental diagram requires non-empty observed and simulated bins",
            support=fundamental_support,
        )
        conditional_result = ComparisonResult(
            observed=FUNDAMENTAL_BAND_THRESHOLD,
            simulated=None,
            rel_error=None,
            absolute_error=None,
            verdict="unavailable",
            reason=support_result.reason,
            support=fundamental_support,
        )
    else:
        band = fundamental_in_band_fraction(observed_profile, simulated_profile)
        fraction = _finite_number(
            "conditional fundamental in-band fraction", band["conditional_in_band_fraction"]
        )
        support = _finite_number("fundamental support coverage", band["support_coverage"])
        total_n = int(band["total_n"])
        supported_bins = int(band["supported_bin_count"])
        max_density = float(band["max_supported_density_high_p_m2"])
        support_ready = (
            total_n > 0
            and support >= FUNDAMENTAL_SUPPORT_THRESHOLD
            and supported_bins >= FUNDAMENTAL_MIN_SUPPORTED_BINS
            and max_density > FUNDAMENTAL_MIN_DENSITY_HIGH_P_M2
        )
        support_result = ComparisonResult(
            observed=FUNDAMENTAL_SUPPORT_THRESHOLD,
            simulated=support,
            rel_error=relative_error(FUNDAMENTAL_SUPPORT_THRESHOLD, support),
            absolute_error=support - FUNDAMENTAL_SUPPORT_THRESHOLD,
            verdict="within_band" if support_ready else "unavailable",
            reason=(
                ""
                if support_ready
                else (
                    f"FD support requires coverage>=0.8, >=3 bins with n>={FUNDAMENTAL_MIN_BIN_N} "
                    "on both sides, "
                    "and density support above 0.3 persons/m^2"
                )
            ),
            support={
                **fundamental_support,
                "fd_total_frame_n": total_n,
                "fd_matched_frame_n": int(band["matched_n"]),
                "fd_supported_bin_count": supported_bins,
            },
        )
        matched_n = int(band["matched_n"])
        conditional_result = ComparisonResult(
            observed=FUNDAMENTAL_BAND_THRESHOLD,
            simulated=fraction,
            rel_error=(
                relative_error(FUNDAMENTAL_BAND_THRESHOLD, fraction) if matched_n > 0 else None
            ),
            absolute_error=fraction - FUNDAMENTAL_BAND_THRESHOLD,
            verdict=(
                "unavailable"
                if matched_n <= 0
                else ("within_band" if fraction >= FUNDAMENTAL_BAND_THRESHOLD else "outside_band")
            ),
            reason=("" if matched_n > 0 else "fundamental profiles have no overlapping bins"),
            support={
                **fundamental_support,
                "fd_matched_frame_n": matched_n,
                "fd_hit_frame_n": round(fraction * matched_n),
            },
        )

    return {
        WALKING_SPEED_PROXY_KEY: free_flow_result,
        "fundamental_support_coverage": support_result,
        "fundamental_conditional_in_band_fraction": conditional_result,
    }


def build_comparison_payload(
    *,
    scene_id: str,
    observed_artifact: dict[str, Any],
    simulation_artifact: dict[str, Any],
    trusted_observed_dataset_id: str,
    trusted_desired_speed_mps: float,
    trusted_geometry_status: str,
    trusted_evidence_sha256: str | None,
    observed_input: dict[str, str],
    simulation_input: dict[str, str],
) -> dict[str, Any]:
    """Build the complete comparison artifact from trusted inputs.

    Keeping this deterministic builder in the library lets the CLI, acceptance
    verifier, and review agents reject hand-edited verdicts and thresholds.
    """
    if (
        observed_artifact.get("schema_version") != OBSERVED_ARTIFACT_SCHEMA_VERSION
        or observed_artifact.get("canonical_schema_version") != CANONICAL_SCHEMA_VERSION
        or observed_artifact.get("metric_schema_version") != METRIC_SCHEMA_VERSION
    ):
        raise ValueError("observed artifact wrapper schema is stale or foreign")
    if (
        simulation_artifact.get("schema_version") != SIMULATION_ARTIFACT_SCHEMA_VERSION
        or simulation_artifact.get("canonical_schema_version") != CANONICAL_SCHEMA_VERSION
        or simulation_artifact.get("metric_schema_version") != METRIC_SCHEMA_VERSION
        or simulation_artifact.get("scene_config_schema_version")
        != SCENE_CONFIG_SCHEMA_VERSION
    ):
        raise ValueError("simulation artifact wrapper schema is stale or foreign")
    if simulation_artifact.get("scene_id") != scene_id:
        raise ValueError("scene_id does not match simulation artifact")
    if observed_artifact.get("dataset_id") != trusted_observed_dataset_id:
        raise ValueError("observed dataset does not match the trusted scene binding")
    observed_metrics = observed_artifact.get("metrics")
    simulated_metrics = simulation_artifact.get("metrics")
    if not isfinite(trusted_desired_speed_mps) or trusted_desired_speed_mps <= 0.0:
        raise ValueError("trusted desired speed must be finite and > 0")
    sampling = observed_artifact.get("metadata", {}).get("sampling", {})
    provenance = simulation_artifact.get("trace_provenance", {})
    results = compare_metric_tables(
        observed_metrics,
        simulated_metrics,
        observed_support_context={
            "source_canonical_row_n": sampling.get("source_rows"),
            "max_point_n": observed_artifact.get("metadata", {}).get("n"),
            "max_agent_n": observed_artifact.get("metadata", {}).get("agent_count"),
            "max_frame_n": sampling.get("packed_frame_count"),
            "max_window_n": sampling.get("window_count"),
        },
        simulated_support_context={
            "expected_seed": simulation_artifact.get("simulation_seed"),
            "max_point_n": provenance.get("canonical_point_count"),
            "max_episode_n": provenance.get("episode_count"),
            "max_passenger_n": provenance.get("passenger_count"),
        },
    )
    verdicts = {name: result.verdict for name, result in results.items()}
    release_blockers = geometry_release_blockers(
        simulation_artifact,
        trusted_geometry_status=trusted_geometry_status,
        trusted_evidence_sha256=trusted_evidence_sha256,
    )
    analysis_contract = observed_metrics.get("analysis_contract", {})
    if (
        analysis_contract.get("walking_speed_proxy", {}).get(
            "desired_speed_release_eligible"
        )
        is not True
    ):
        release_blockers.append(
            "desired-speed evidence is a low-global-density speed-truncated proxy"
        )
    overall = (
        "pass"
        if verdicts and set(verdicts.values()) == {"within_band"} and not release_blockers
        else "hold"
    )
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "scene_id": scene_id,
        "observed_dataset_id": trusted_observed_dataset_id,
        "overall_verdict": overall,
        "release_blockers": release_blockers,
        "analysis_contract": analysis_contract,
        "trusted_parameters": {
            "jupedsim_desired_speed_mps": float(trusted_desired_speed_mps),
        },
        "parameter_validation": {
            "schema_version": "alignment_parameter_validation.v1",
            "independent_holdout": {"available": False, "dataset_id": None},
            "multi_seed": {
                "seed_n": simulated_metrics.get("metric_support", {})
                .get(WALKING_SPEED_PROXY_KEY, {})
                .get("seed_n", 0),
                "min_required": 10,
                "converged": False,
            },
            "uncertainty": {
                "kind": "not_estimated",
                "confidence_level": None,
                "estimate": None,
                "lower": None,
                "upper": None,
                "relative_half_width": None,
            },
        },
        "comparison_thresholds": {
            "walking_speed_proxy_p50_rel_error_max": (
                WALKING_SPEED_PROXY_RELATIVE_ERROR_THRESHOLD
            ),
            "fundamental_support_coverage_min": FUNDAMENTAL_SUPPORT_THRESHOLD,
            "fundamental_conditional_in_band_fraction_min": FUNDAMENTAL_BAND_THRESHOLD,
            "fundamental_min_supported_bins": FUNDAMENTAL_MIN_SUPPORTED_BINS,
            "fundamental_min_density_high_p_m2_exclusive": (
                FUNDAMENTAL_MIN_DENSITY_HIGH_P_M2
            ),
        },
        "inputs": {
            "observed": dict(observed_input),
            "simulation": dict(simulation_input),
        },
        "metrics": {name: asdict(result) for name, result in results.items()},
    }


def build_preflight_blocked_comparison_payload(
    *,
    scene_id: str,
    observed_artifact: dict[str, Any],
    preflight_artifact: dict[str, Any],
    trusted_observed_dataset_id: str,
    trusted_desired_speed_mps: float,
    trusted_geometry_status: str,
    observed_input: dict[str, str],
    preflight_input: dict[str, str],
) -> dict[str, Any]:
    """Build an explicit hold when preflight is current but no formal simulation exists."""

    if (
        observed_artifact.get("schema_version") != OBSERVED_ARTIFACT_SCHEMA_VERSION
        or observed_artifact.get("canonical_schema_version") != CANONICAL_SCHEMA_VERSION
        or observed_artifact.get("metric_schema_version") != METRIC_SCHEMA_VERSION
    ):
        raise ValueError("observed artifact wrapper schema is stale or foreign")
    report = preflight_artifact.get("preflight", {})
    if (
        preflight_artifact.get("schema_version")
        != SOURCE_PREFLIGHT_ARTIFACT_SCHEMA_VERSION
        or preflight_artifact.get("scene_id") != scene_id
        or preflight_artifact.get("scene_config_schema_version")
        != SCENE_CONFIG_SCHEMA_VERSION
        or preflight_artifact.get("runtime_status") != "ready"
        or preflight_artifact.get("scientific_status") != "eligible"
        or preflight_artifact.get("blocker") is not None
        or not isinstance(report, dict)
        or report.get("status") != "pass"
        or report.get("runtime_status") != "ready"
        or report.get("scientific_status") != "eligible"
        or report.get("outcome") != "eligible"
        or report.get("blockers") != []
    ):
        raise ValueError("source preflight artifact is stale, failed, or foreign")
    if observed_artifact.get("dataset_id") != trusted_observed_dataset_id:
        raise ValueError("observed dataset does not match the trusted scene binding")
    if not isfinite(trusted_desired_speed_mps) or trusted_desired_speed_mps <= 0.0:
        raise ValueError("trusted desired speed must be finite and > 0")

    observed_metrics = observed_artifact.get("metrics")
    if not isinstance(observed_metrics, dict):
        raise TypeError("observed metrics must be an object")
    sampling = observed_artifact.get("metadata", {}).get("sampling", {})
    observed_context = {
        "source_canonical_row_n": sampling.get("source_rows"),
        "max_point_n": observed_artifact.get("metadata", {}).get("n"),
        "max_agent_n": observed_artifact.get("metadata", {}).get("agent_count"),
        "max_frame_n": sampling.get("packed_frame_count"),
        "max_window_n": sampling.get("window_count"),
    }
    observed_support: dict[str, dict[str, Any]] = {}
    for metric_key in (WALKING_SPEED_PROXY_KEY, "fundamental_diagram"):
        errors = metric_support_errors(
            observed_metrics,
            metric_key,
            side="observed",
            context=observed_context,
        )
        if errors:
            raise ValueError(f"observed {metric_key} support is invalid: {errors}")
        observed_support[metric_key] = dict(
            observed_metrics["metric_support"][metric_key]
        )

    unavailable_simulated_support = {
        "point_n": 0,
        "episode_n": 0,
        "passenger_n": 0,
        "frame_n": 0,
        "seed_n": 0,
        "seed_values": [],
        "unit": "correlated_simulated_metric_contributors",
    }

    def support(metric_key: str) -> dict[str, Any]:
        return {
            "observed": observed_support[metric_key],
            "simulated": dict(unavailable_simulated_support),
            "independence_warning": (
                "observed contributors are correlated; no current formal simulated "
                "contributors are available"
            ),
        }

    observed_p50 = float(observed_metrics[WALKING_SPEED_PROXY_KEY]["p50"])
    reason = "current formal simulation evidence is unavailable after source preflight"
    results = {
        WALKING_SPEED_PROXY_KEY: ComparisonResult(
            observed=observed_p50,
            simulated=None,
            rel_error=None,
            absolute_error=None,
            verdict="unavailable",
            reason=reason,
            support=support(WALKING_SPEED_PROXY_KEY),
        ),
        "fundamental_support_coverage": ComparisonResult(
            observed=None,
            simulated=None,
            rel_error=None,
            absolute_error=None,
            verdict="unavailable",
            reason=reason,
            support=support("fundamental_diagram"),
        ),
        "fundamental_conditional_in_band_fraction": ComparisonResult(
            observed=None,
            simulated=None,
            rel_error=None,
            absolute_error=None,
            verdict="unavailable",
            reason=reason,
            support=support("fundamental_diagram"),
        ),
    }
    analysis_contract = observed_metrics.get("analysis_contract", {})
    release_blockers = [reason]
    if trusted_geometry_status != "observed_matched":
        release_blockers.append(
            f"simulation geometry is not observed-matched: trusted status={trusted_geometry_status}"
        )
    if (
        analysis_contract.get("walking_speed_proxy", {}).get(
            "desired_speed_release_eligible"
        )
        is not True
    ):
        release_blockers.append(
            "desired-speed evidence is a low-global-density speed-truncated proxy"
        )
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "scene_id": scene_id,
        "observed_dataset_id": trusted_observed_dataset_id,
        "simulation_evidence_status": "unavailable_after_preflight",
        "overall_verdict": "hold",
        "release_blockers": release_blockers,
        "analysis_contract": analysis_contract,
        "trusted_parameters": {
            "jupedsim_desired_speed_mps": float(trusted_desired_speed_mps),
        },
        "parameter_validation": {
            "schema_version": "alignment_parameter_validation.v1",
            "independent_holdout": {"available": False, "dataset_id": None},
            "multi_seed": {"seed_n": 0, "min_required": 10, "converged": False},
            "uncertainty": {
                "kind": "not_estimated",
                "confidence_level": None,
                "estimate": None,
                "lower": None,
                "upper": None,
                "relative_half_width": None,
            },
        },
        "comparison_thresholds": {
            "walking_speed_proxy_p50_rel_error_max": (
                WALKING_SPEED_PROXY_RELATIVE_ERROR_THRESHOLD
            ),
            "fundamental_support_coverage_min": FUNDAMENTAL_SUPPORT_THRESHOLD,
            "fundamental_conditional_in_band_fraction_min": FUNDAMENTAL_BAND_THRESHOLD,
            "fundamental_min_supported_bins": FUNDAMENTAL_MIN_SUPPORTED_BINS,
            "fundamental_min_density_high_p_m2_exclusive": (
                FUNDAMENTAL_MIN_DENSITY_HIGH_P_M2
            ),
        },
        "inputs": {
            "observed": dict(observed_input),
            "source_preflight": dict(preflight_input),
        },
        "metrics": {name: asdict(result) for name, result in results.items()},
    }
