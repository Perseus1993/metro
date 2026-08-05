from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.formal_profiles import MULTI_SEED_NIGHTLY_PROFILE_ID
from metro_alignment.metrics.fundamental import WALKING_SPEED_PROXY_KEY

AGGREGATE_SCHEMA_VERSION = "alignment_multi_seed_aggregate.v1"
FORMAL_SIMULATION_SCHEMA_VERSION = "alignment_simulation_metrics.v5"
REQUIRED_SEEDS = tuple(range(41, 51))
T_CRITICAL_95_DF9 = 2.2621571627409915
ROOT = Path(__file__).resolve().parents[2]
ZERO_FINAL_METRICS = (
    "pending_alighting_persons",
    "alignment_pending_source_groups",
    "alignment_pending_source_persons",
    "alignment_pending_entry_groups",
    "alignment_pending_entry_persons",
    "alignment_entry_dropped_persons",
    "alignment_source_dropped_persons",
    "jupedsim_missing_agents",
    "jupedsim_degraded_holds",
    "alignment_active_boardings",
    "alignment_reserved_boarding_persons",
)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(value: Any) -> str:
    content = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return _sha256_bytes(content.encode("utf-8"))


def _portable_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _generator_record() -> dict[str, str]:
    return {
        "module": "metro_alignment.multi_seed",
        "source_sha256": _sha256_file(Path(__file__).resolve()),
    }


def confidence_interval_95(values: Iterable[float]) -> dict[str, Any]:
    sample = [float(value) for value in values]
    if len(sample) != len(REQUIRED_SEEDS) or any(not math.isfinite(value) for value in sample):
        raise ValueError("95% convergence requires exactly 10 finite seed values")
    mean = statistics.fmean(sample)
    standard_deviation = statistics.stdev(sample)
    half_width = T_CRITICAL_95_DF9 * standard_deviation / math.sqrt(len(sample))
    relative = math.inf if mean == 0.0 else half_width / abs(mean)
    return {
        "kind": "student_t_confidence_interval_95",
        "confidence_level": 0.95,
        "n": len(sample),
        "degrees_of_freedom": 9,
        "t_critical": T_CRITICAL_95_DF9,
        "estimate": mean,
        "sample_standard_deviation": standard_deviation,
        "half_width": half_width,
        "lower": mean - half_width,
        "upper": mean + half_width,
        "relative_half_width": relative,
        "threshold": 0.05,
        "numerically_converged": relative <= 0.05,
    }


def _metric_value(payload: dict[str, Any], metric_key: str) -> float:
    try:
        value = float(payload["metrics"][metric_key]["p50"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"manifest lacks finite metrics.{metric_key}.p50") from exc
    if not math.isfinite(value):
        raise ValueError(f"metrics.{metric_key}.p50 must be finite")
    return value


def _validate_step5(payload: dict[str, Any]) -> None:
    final = payload.get("final_frame_metrics")
    if not isinstance(final, dict):
        raise TypeError("formal manifest lacks final_frame_metrics")
    failures = [f"{key}={final.get(key)!r}" for key in ZERO_FINAL_METRICS if final.get(key) != 0]
    for key in ("alignment_entry_demand_conserved", "alignment_source_demand_conserved"):
        if final.get(key) is not True:
            failures.append(f"{key}={final.get(key)!r}")
    if final.get("alignment_requested_due_source_persons") != final.get(
        "alignment_scheduled_source_persons"
    ):
        failures.append("requested/scheduled source persons differ")
    if final.get("spawned_entry_persons") != final.get("alignment_scheduled_entry_persons"):
        failures.append("spawned/scheduled entry persons differ")
    if final.get("spawned_exit_persons") != final.get("alignment_scheduled_source_persons"):
        failures.append("spawned exit/scheduled source persons differ")
    if not isinstance(final.get("departed_trains"), int) or final["departed_trains"] <= 0:
        failures.append(f"departed_trains={final.get('departed_trains')!r}")
    if failures:
        raise ValueError("Step 5 final metrics failed: " + "; ".join(failures))


def _validate_content_addressed_artifacts(source: Path, payload: dict[str, Any]) -> None:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise TypeError("formal manifest lacks content-addressed artifacts")
    for key in ("canonical", "movement_trace"):
        record = artifacts.get(key)
        if not isinstance(record, dict):
            raise TypeError(f"formal manifest lacks artifacts.{key}")
        relative = record.get("path")
        expected_sha = record.get("sha256")
        expected_size = record.get("size_bytes")
        if not isinstance(relative, str) or not isinstance(expected_sha, str):
            raise TypeError(f"invalid artifacts.{key} record")
        artifact = (source.parent / relative).resolve()
        if not artifact.is_file():
            raise ValueError(f"missing artifacts.{key}: {artifact}")
        if artifact.stat().st_size != expected_size or _sha256_file(artifact) != expected_sha:
            raise ValueError(f"artifacts.{key} size/hash mismatch: {artifact}")
        if f"sha256-{expected_sha}" not in artifact.name:
            raise ValueError(f"artifacts.{key} is not content-address named: {artifact}")


def _validate_formal_runner_provenance(payload: dict[str, Any]) -> None:
    provenance = payload.get("runner_provenance")
    expected = {
        "mode": "formal_control_profile",
        "profile_id": MULTI_SEED_NIGHTLY_PROFILE_ID,
        "control_id": "mixed-600",
        "publication_scope": "nightly_seed_bundle",
        "trace_replay": False,
        "manual_model_step": False,
    }
    if not isinstance(provenance, dict):
        raise TypeError("formal multi-seed manifest lacks runner_provenance")
    contradictions = {
        key: (provenance.get(key), value)
        for key, value in expected.items()
        if provenance.get(key) != value
    }
    if contradictions:
        raise ValueError(f"formal runner provenance mismatch: {contradictions}")


def _cohort_record(payload: dict[str, Any]) -> dict[str, Any]:
    scene_config = dict(payload.get("scene_config", {}))
    scene_config.pop("seed", None)
    return {
        "scene_id": payload.get("scene_id"),
        "canonical_schema_version": payload.get("canonical_schema_version"),
        "metric_schema_version": payload.get("metric_schema_version"),
        "scene_config_schema_version": payload.get("scene_config_schema_version"),
        "scene_config_without_seed_sha256": _canonical_sha(scene_config),
        "design_sha256": payload.get("design_sha256"),
        "metro_runtime_fingerprint": payload.get("metro_runtime_fingerprint"),
        "analysis_runtime_fingerprint": payload.get("analysis_runtime_fingerprint"),
        "formal_profile_id": payload.get("runner_provenance", {}).get("profile_id"),
    }


def aggregate_formal_manifests(
    paths: Iterable[Path], *, metric_key: str = WALKING_SPEED_PROXY_KEY
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    cohort: dict[str, Any] | None = None
    seen: set[int] = set()
    for source in sorted((Path(path).resolve() for path in paths), key=lambda item: item.as_posix()):
        content = source.read_bytes()
        payload = json.loads(content)
        if payload.get("schema_version") != FORMAL_SIMULATION_SCHEMA_VERSION:
            raise ValueError(f"{source} is not a formal simulation v5 manifest")
        seed = payload.get("simulation_seed")
        if not isinstance(seed, int) or seed not in REQUIRED_SEEDS or seed in seen:
            raise ValueError(f"invalid or duplicate fixed seed in {source}: {seed!r}")
        if payload.get("scene_config", {}).get("seed") != seed:
            raise ValueError(f"scene_config seed mismatch in {source}")
        _validate_step5(payload)
        _validate_content_addressed_artifacts(source, payload)
        _validate_formal_runner_provenance(payload)
        support = payload.get("metrics", {}).get("metric_support", {}).get(metric_key, {})
        if support.get("seed_n") != 1 or support.get("seed_values") != [seed]:
            raise ValueError(f"metric support seed binding mismatch in {source}")
        current_cohort = _cohort_record(payload)
        if cohort is None:
            cohort = current_cohort
        elif current_cohort != cohort:
            raise ValueError(f"cohort fingerprint mismatch in {source}")
        seen.add(seed)
        runs.append(
            {
                "seed": seed,
                "value": _metric_value(payload, metric_key),
                "manifest": {
                    "path": _portable_path(source),
                    "sha256": _sha256_bytes(content),
                    "size_bytes": len(content),
                },
                "step5_passed": True,
            }
        )
    if seen != set(REQUIRED_SEEDS):
        raise ValueError(f"fixed seed set must be {list(REQUIRED_SEEDS)}, got {sorted(seen)}")
    runs.sort(key=lambda item: item["seed"])
    interval = confidence_interval_95(run["value"] for run in runs)
    return {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "generator": _generator_record(),
        "evidence_mode": "formal_simulation_v5",
        "scope": "Step 5 multi-seed convergence only; geometry and holdout gates are separate",
        "metric": {"key": metric_key, "statistic": "p50", "unit": "m/s"},
        "required_seeds": list(REQUIRED_SEEDS),
        "seed_n": len(runs),
        "runs": runs,
        "cohort": cohort,
        "cohort_sha256": _canonical_sha(cohort),
        "uncertainty": interval,
        "converged": bool(interval["numerically_converged"]),
        "gate_status": "pass" if interval["numerically_converged"] else "fail",
        "release_eligible_for_multi_seed_gate": bool(interval["numerically_converged"]),
    }


def aggregate_legacy_smoke(
    path: Path, *, metric_key: str = "free_flow_speed_m_s"
) -> dict[str, Any]:
    source = Path(path).resolve()
    content = source.read_bytes()
    payload = json.loads(content)
    value = _metric_value(payload, metric_key)
    interval = confidence_interval_95([value] * len(REQUIRED_SEEDS))
    return {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "generator": _generator_record(),
        "evidence_mode": "legacy_single_run_replay_smoke",
        "scope": "pipeline/schema smoke only; repeated values are not independent runs",
        "metric": {"key": metric_key, "statistic": "p50", "unit": "m/s"},
        "required_seeds": list(REQUIRED_SEEDS),
        "seed_n": 0,
        "synthetic_labels": list(REQUIRED_SEEDS),
        "source": {
            "path": _portable_path(source),
            "sha256": _sha256_bytes(content),
            "size_bytes": len(content),
            "source_schema_version": payload.get("schema_version"),
        },
        "uncertainty": interval,
        "converged": False,
        "gate_status": "smoke_only",
        "release_eligible_for_multi_seed_gate": False,
        "warning": (
            "One legacy run was replayed under ten labels; its zero variance is not "
            "multi-seed convergence evidence."
        ),
    }


def write_aggregate(path: Path, payload: dict[str, Any]) -> None:
    write_json_atomic(path, payload)
