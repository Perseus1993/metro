from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from metro_alignment.analysis_runtime import analysis_runtime_fingerprint
from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.canonical import (
    CANONICAL_COLUMNS,
    CANONICAL_SCHEMA_VERSION,
    read_canonical,
    validate,
)
from metro_alignment.datasets.registry import (
    get_dataset_spec,
    is_portable_basename,
    list_dataset_specs,
)
from metro_alignment.formal_contract import (
    ArtifactRecord,
    ControlRunArtifact,
    LadderManifest,
)
from metro_alignment.formal_profiles import final_ladder_profile
from metro_alignment.metrics.comparison import (
    COMPARISON_SCHEMA_VERSION,
    SIMULATION_ARTIFACT_SCHEMA_VERSION,
    build_comparison_payload,
    build_preflight_blocked_comparison_payload,
    metric_support_errors,
)
from metro_alignment.metrics.fundamental import (
    METRIC_SCHEMA_VERSION,
    WALKING_SPEED_PROXY_KEY,
    analysis_contract_consistency_errors,
)
from metro_alignment.metro_contract import (
    SCENE_CONFIG_SCHEMA_VERSION,
    scene_config_sha256,
    verify_scene_config_record,
)
from metro_alignment.metro_runtime import metro_source_fingerprint
from metro_alignment.metro_scene import build_metro_scenario
from metro_alignment.metro_trace import movement_trace_to_canonical
from metro_alignment.observed_evidence import compute_observed_evidence
from metro_alignment.report import REPORT_SCHEMA_VERSION, validate_report_payload
from metro_alignment.saturated_flow import SaturatedFlowArtifact
from metro_alignment.scenes import build_scene_config, list_scene_configs
from metro_alignment.simulation_evidence import (
    compute_simulated_metrics,
    simulated_trajectory_summary,
)

ROOT = Path(__file__).resolve().parents[1]
Status = Literal["pass", "fail", "pending"]


@dataclass(frozen=True)
class StepResult:
    step: int
    name: str
    status: Status
    evidence: list[str]
    blockers: list[str]
    release_authorized: bool | None = None


def _run(command: list[str]) -> tuple[bool, str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, output[-2000:]


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("JSON artifact root must be an object")
    return payload


def _load_json_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    content = path.read_bytes()
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise TypeError("JSON artifact root must be an object")
    return payload, hashlib.sha256(content).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _acceptance_source_fingerprint() -> str:
    files = [Path(__file__).resolve(), ROOT / ".gitignore"]
    files.extend((ROOT / "scripts").glob("*.py"))
    files.extend((ROOT / "tests").rglob("*.py"))
    digest = hashlib.sha256()
    for path in sorted(set(files), key=lambda item: item.relative_to(ROOT).as_posix()):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _ready_scene_configs() -> tuple[list[tuple[str, Any]], list[str]]:
    try:
        ready = [
            (scene_id, config)
            for scene_id, config in list_scene_configs()
            if config.status == "ready"
        ]
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return [], [f"scene registry is invalid: {exc}"]
    if not ready:
        return [], ["scene registry has no ready scene"]
    return ready, []


def _dataset_registry_specs() -> tuple[list[Any], list[str]]:
    try:
        specs = list(list_dataset_specs())
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return [], [f"dataset registry is invalid: {exc}"]
    if not any(spec.status == "active" for spec in specs):
        return specs, ["dataset registry has no active dataset"]
    return specs, []


def _step1() -> StepResult:
    evidence: list[str] = []
    blockers: list[str] = []
    lock_ok, lock_output = _run(["uv", "lock", "--check", "--project", "."])
    if lock_ok:
        evidence.append("uv lock --check passed")
    else:
        blockers.append(f"uv lock failed: {lock_output}")
    try:
        import metro_station
        import pedpy

        import metro_alignment

        evidence.append(
            f"imports passed: alignment={metro_alignment.__version__}, "
            f"metro={metro_station.__version__}, PedPy={pedpy.__version__}"
        )
    except ImportError as exc:
        blockers.append(f"independent environment import failed: {exc}")
    return StepResult(1, "基础工程化", "fail" if blockers else "pass", evidence, blockers)


def _step2(test_ok: bool) -> StepResult:
    evidence: list[str] = []
    specs, blockers = _dataset_registry_specs()
    active = [spec.dataset_id for spec in specs if spec.status == "active"]
    pending = [spec.dataset_id for spec in specs if spec.status == "pending"]
    if active and all(spec.license.strip() and spec.citation.strip() for spec in specs):
        evidence.append(f"registry active={active}; pending={pending}")
    else:
        blockers.append("registry requires >=1 active dataset and complete license/citation")
    if test_ok:
        evidence.append("download 200/206 resume and verified-skip behavior tests passed")
    else:
        blockers.append("test suite failed; download behavior is not accepted")
    return StepResult(2, "数据注册与下载", "fail" if blockers else "pass", evidence, blockers)


def _parquet_null_count(parquet: pq.ParquetFile, column_name: str) -> int | None:
    index = parquet.schema_arrow.names.index(column_name)
    count = 0
    for row_group in range(parquet.metadata.num_row_groups):
        statistics = parquet.metadata.row_group(row_group).column(index).statistics
        if statistics is None or statistics.null_count is None:
            return None
        count += int(statistics.null_count)
    return count


def _check_canonical_unchecked(dataset_id: str) -> tuple[list[str], list[str]]:
    canonical = ROOT / "data" / "canonical" / f"{dataset_id}.parquet"
    metadata_path = ROOT / "data" / "canonical" / f"{dataset_id}.meta.json"
    evidence: list[str] = []
    blockers: list[str] = []
    if not canonical.exists() or not metadata_path.exists():
        return evidence, [f"{dataset_id}: canonical/meta missing"]
    parquet = pq.ParquetFile(canonical)
    if parquet.schema_arrow.names == list(CANONICAL_COLUMNS):
        evidence.append(f"{dataset_id}: exact canonical column order")
    else:
        blockers.append(f"real parquet columns are {parquet.schema_arrow.names}")
    fields = {field.name: field.type for field in parquet.schema_arrow}
    type_checks = {
        "dataset_id": pa.types.is_string(fields.get("dataset_id"))
        or pa.types.is_large_string(fields.get("dataset_id")),
        "agent_id": pa.types.is_int64(fields.get("agent_id")),
        "frame": pa.types.is_int64(fields.get("frame")),
        "t_s": pa.types.is_float64(fields.get("t_s")),
        "x_m": pa.types.is_float64(fields.get("x_m")),
        "y_m": pa.types.is_float64(fields.get("y_m")),
    }
    if all(type_checks.values()):
        evidence.append(f"{dataset_id}: exact canonical physical dtypes")
    else:
        blockers.append(f"real parquet dtype checks failed: {type_checks}")
    for column in ("dataset_id", "t_s", "x_m", "y_m"):
        null_count = _parquet_null_count(parquet, column)
        if null_count == 0:
            evidence.append(f"{dataset_id}: {column} row-group null_count=0")
        else:
            blockers.append(f"{column} null_count is unavailable/nonzero: {null_count}")
    try:
        metadata = _load_json(metadata_path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        blockers.append(f"canonical metadata is unreadable: {exc}")
        return evidence, blockers
    rows = int(parquet.metadata.num_rows)
    if metadata.get("row_count") == rows and metadata.get("validation", {}).get(
        "strict_time_per_agent"
    ):
        evidence.append(f"{dataset_id}: validated rows={rows}; strict per-agent time recorded")
    else:
        blockers.append("metadata row count/full strict-time validation is stale or missing")
    return evidence, blockers


def _check_canonical(dataset_id: str) -> tuple[list[str], list[str]]:
    try:
        return _check_canonical_unchecked(dataset_id)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        return [], [f"{dataset_id}: canonical evidence is unreadable: {exc}"]


def _step3() -> StepResult:
    evidence: list[str] = []
    specs, blockers = _dataset_registry_specs()
    for spec in specs:
        if spec.status != "active":
            continue
        dataset_evidence, dataset_blockers = _check_canonical(spec.dataset_id)
        evidence.extend(dataset_evidence)
        blockers.extend(dataset_blockers)
    return StepResult(3, "Canonical 统一格式", "fail" if blockers else "pass", evidence, blockers)


def _check_observed_unchecked(dataset_id: str) -> tuple[list[str], list[str]]:
    path = ROOT / "data" / "metrics" / f"{dataset_id}_observed.json"
    if not path.exists():
        return [], [f"{dataset_id}: observed metrics missing"]
    try:
        payload = _load_json(path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        return [], [f"{dataset_id}: observed metrics are unreadable: {exc}"]
    evidence: list[str] = []
    blockers: list[str] = []
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        blockers.append("observed metrics must be an object")
        metrics = {}
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        blockers.append("observed metadata must be an object")
        metadata = {}
    sampling = metadata.get("sampling")
    if not isinstance(sampling, dict):
        blockers.append("observed sampling metadata must be an object")
        sampling = {}
    input_artifacts = payload.get("input_artifacts")
    if not isinstance(input_artifacts, dict):
        blockers.append("observed input_artifacts must be an object")
        input_artifacts = {}
    if (
        payload.get("schema_version") != "alignment_observed_metrics.v5"
        or payload.get("dataset_id") != dataset_id
        or payload.get("canonical_schema_version") != CANONICAL_SCHEMA_VERSION
        or payload.get("metric_schema_version") != METRIC_SCHEMA_VERSION
    ):
        blockers.append("observed wrapper schema/dataset/version contract is stale or misbound")
    contract_errors = analysis_contract_consistency_errors(metrics)
    if contract_errors:
        blockers.append(f"analysis contract contradicts method payload: {contract_errors}")
    for metric_key in (WALKING_SPEED_PROXY_KEY, "fundamental_diagram"):
        support_errors = metric_support_errors(
            metrics,
            metric_key,
            side="observed",
            context={
                "source_canonical_row_n": sampling.get("source_rows"),
                "max_point_n": metadata.get("n"),
                "max_agent_n": metadata.get("agent_count"),
                "max_frame_n": sampling.get("packed_frame_count"),
                "max_window_n": sampling.get("window_count"),
            },
        )
        if support_errors:
            blockers.append(f"{metric_key} contributor support failed: {support_errors}")
    if payload.get("analysis_runtime_fingerprint") == analysis_runtime_fingerprint():
        evidence.append("observed analysis runtime fingerprint matches current code and lock")
    else:
        blockers.append("observed analysis runtime fingerprint is missing or stale")
    expected_inputs = {
        "canonical": ROOT / "data" / "canonical" / f"{dataset_id}.parquet",
        "canonical_metadata": ROOT / "data" / "canonical" / f"{dataset_id}.meta.json",
    }
    for name, expected_path in expected_inputs.items():
        record = input_artifacts.get(name, {})
        if not isinstance(record, dict):
            blockers.append(f"observed input artifact record must be an object: {name}")
            record = {}
        recorded_path = (path.parent / Path(str(record.get("path", "")))).resolve()
        if (
            recorded_path == expected_path.resolve()
            and expected_path.exists()
            and expected_path.stat().st_size == int(record.get("size_bytes", -1))
            and _sha256(expected_path) == record.get("sha256")
        ):
            evidence.append(f"observed input hash verified: {name}")
        else:
            blockers.append(f"observed input artifact is missing, stale, or misbound: {name}")
    try:
        canonical = read_canonical(expected_inputs["canonical"])
        rebuilt_metrics, rebuilt_metadata = compute_observed_evidence(
            canonical,
            spec=get_dataset_spec(dataset_id),
        )
        if metrics != rebuilt_metrics or payload.get("metadata") != rebuilt_metadata:
            blockers.append(
                "observed metrics/metadata differ from deterministic canonical recomputation"
            )
        else:
            evidence.append("observed metrics and contributor support exactly recomputed")
        for name, expected_path in expected_inputs.items():
            record = input_artifacts.get(name, {})
            if not isinstance(record, dict):
                record = {}
            if (
                expected_path.stat().st_size != int(record.get("size_bytes", -1))
                or _sha256(expected_path) != record.get("sha256")
            ):
                blockers.append(f"observed input changed during recomputation: {name}")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        blockers.append(f"observed deterministic recomputation failed: {exc}")
    free_flow = metrics.get(WALKING_SPEED_PROXY_KEY, {})
    bins = metrics.get("fundamental_diagram", {}).get("bins", [])
    contract = metrics.get("analysis_contract", {})
    if (
        contract.get("schema_version") == "alignment_analysis_contract.v1"
        and contract.get("library", {}).get("name") == "PedPy"
        and contract.get("speed", {}).get("physical_window_s") == 0.4
        and contract.get("density", {}).get("method") == "compute_classic_density"
        and contract.get("walking_speed_proxy", {}).get("desired_speed_release_eligible") is False
        and contract.get("measurement", {}).get("comparison_polygon_sha256")
    ):
        evidence.append("normalized analysis contract records a shared 0.4s speed window")
    else:
        blockers.append("normalized analysis contract is incomplete or unsafe")
    if metrics.get("schema_version") == METRIC_SCHEMA_VERSION:
        evidence.append(f"metric schema={METRIC_SCHEMA_VERSION}")
    else:
        blockers.append("observed metric schema is stale")
    method = metrics.get("method", {})
    if (
        method.get("library") == "PedPy"
        and method.get("measurement_area", {}).get("source") == "explicit"
    ):
        evidence.append("PedPy methods and explicit measurement area recorded")
    else:
        blockers.append("PedPy method or explicit measurement area missing")
    required = {"n", "p5", "p25", "p50", "p75", "p95"}
    try:
        percentile_values = [float(free_flow[key]) for key in ("p5", "p25", "p50", "p75", "p95")]
    except (KeyError, TypeError, ValueError):
        percentile_values = []
    if (
        required.issubset(free_flow)
        and int(free_flow.get("n", 0)) >= 30
        and all(isfinite(value) for value in percentile_values)
        and percentile_values == sorted(percentile_values)
        and 0.5 <= float(free_flow.get("p50", 0.0)) <= 2.5
    ):
        evidence.append(f"walking-speed proxy n={free_flow['n']} p50={free_flow['p50']:.3f}m/s")
    else:
        blockers.append("walking-speed proxy sample/percentiles fail method sanity gate")
    if bins:
        evidence.append(f"fundamental diagram populated bins={len(bins)}")
    else:
        blockers.append("fundamental diagram bins are empty")
    if sampling.get("strategy") == "complete_contiguous_frame_windows":
        packed_frames = int(sampling.get("packed_frame_count", 0))
        binned_frames = sum(int(row.get("n", 0)) for row in bins)
        if (
            sampling.get("time_rebased") is True
            and sampling.get("source_continuity_verified") is True
            and 0 < binned_frames <= packed_frames
        ):
            evidence.append(
                f"sample windows rebased; FD frames={binned_frames}/{packed_frames} packed"
            )
        else:
            blockers.append(
                f"sample frame-gap gate failed: rebased={sampling.get('time_rebased')}, "
                f"FD={binned_frames}, packed={packed_frames}"
            )
    return evidence, [f"{dataset_id}: {blocker}" for blocker in blockers]


def _check_observed(dataset_id: str) -> tuple[list[str], list[str]]:
    try:
        return _check_observed_unchecked(dataset_id)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        return [], [f"{dataset_id}: observed evidence has an invalid shape: {exc}"]


def _step4() -> StepResult:
    evidence: list[str] = []
    specs, blockers = _dataset_registry_specs()
    for spec in specs:
        if spec.status != "active":
            continue
        dataset_evidence, dataset_blockers = _check_observed(spec.dataset_id)
        evidence.extend(f"{spec.dataset_id}: {item}" for item in dataset_evidence)
        blockers.extend(dataset_blockers)
    return StepResult(4, "观测侧指标", "fail" if blockers else "pass", evidence, blockers)


def _require_source_preflight_semantics(preflight: dict) -> dict:
    scene_class = preflight.get("scene_class")
    scene_config = preflight.get("scene_config")
    if scene_class not in {"observation_matched", "synthetic_declared"}:
        raise ValueError("source preflight must declare a supported scene_class")
    if not isinstance(scene_config, dict) or scene_config.get("scene_class") != scene_class:
        raise ValueError("source preflight scene_class must match scene_config")
    report = preflight.get("preflight")
    if not isinstance(report, dict):
        raise TypeError("source preflight report must be an object")
    passed = report.get("status") == "pass"
    expected_outer = (
        {
            "runtime_status": "ready",
            "scientific_status": "eligible",
            "blocker": None,
            "release_eligible": False,
        }
        if passed
        else {
            "runtime_status": "not_started",
            "scientific_status": "model_invalid",
            "blocker": "alighting_source_geometry_conflict",
            "release_eligible": False,
        }
    )
    for key, expected in expected_outer.items():
        if preflight.get(key) != expected:
            raise ValueError(
                f"source preflight {key}={preflight.get(key)!r}, expected {expected!r}"
            )
    expected_inner = (
        {
            "schema_version": "alignment_source_geometry_preflight.v3",
            "runtime_status": "ready",
            "scientific_status": "eligible",
            "outcome": "eligible",
            "status": "pass",
            "capacity_certificate": True,
            "compiler_rejection_reproduced": False,
        }
        if passed
        else {
            "schema_version": "alignment_source_geometry_preflight.v3",
            "runtime_status": "not_started",
            "scientific_status": "source_geometry_conflict",
            "outcome": "model_invalid",
            "status": "fail",
            "capacity_certificate": True,
            "compiler_rejection_reproduced": True,
        }
    )
    for key, expected in expected_inner.items():
        if report.get(key) != expected:
            raise ValueError(
                f"source preflight report {key}={report.get(key)!r}, "
                f"expected {expected!r}"
            )
    compiler_codes = report.get("compiler_error_codes")
    if not isinstance(compiler_codes, list) or (
        (passed and compiler_codes)
        or (not passed and "capacity.coactive_slot_conflict" not in compiler_codes)
    ):
        raise ValueError("source preflight compiler error codes contradict its status")
    blockers = report.get("blockers")
    if not isinstance(blockers, list) or (passed and blockers) or (not passed and not blockers):
        raise ValueError("source preflight report blockers contradict its status")
    queue_reports = report.get("queue_reports")
    if not isinstance(queue_reports, list) or not queue_reports:
        raise ValueError("source preflight report must contain nonempty queue_reports")
    expected_queue_status = "pass" if passed else "conflict"
    if any(row.get("status") != expected_queue_status for row in queue_reports):
        raise ValueError("source preflight queue status contradicts its outcome")
    return report


def _load_formal_artifact(
    parent: Path,
    raw_record: Any,
) -> tuple[ArtifactRecord, Path, bytes]:
    record = ArtifactRecord.model_validate(raw_record)
    root = parent.resolve()
    path = (root / record.path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"formal artifact is missing: {record.path}")
    content = path.read_bytes()
    if len(content) != record.size_bytes or hashlib.sha256(content).hexdigest() != record.sha256:
        raise ValueError(f"formal artifact size/hash mismatch: {record.path}")
    return record, path, content


def _require_formal_ladder(
    *,
    active_manifest: Path,
    active_payload: dict[str, Any],
    scene_id: str,
    current_design_sha256: str,
) -> list[str]:
    profile = final_ladder_profile()
    provenance = active_payload.get("runner_provenance")
    expected_provenance = {
        "mode": "formal_control_profile",
        "profile_id": profile.profile_id,
        "profile_sha256": profile.sha256,
        "trace_replay": False,
        "manual_model_step": False,
        "diagnostic_input_reused": False,
    }
    if not isinstance(provenance, dict):
        raise TypeError("active simulation lacks formal runner provenance")
    contradictions = {
        key: (provenance.get(key), expected)
        for key, expected in expected_provenance.items()
        if provenance.get(key) != expected
    }
    if contradictions:
        raise ValueError(f"active simulation formal runner provenance mismatch: {contradictions}")
    if active_payload.get("formal_control_id") != profile.publication_control_id:
        raise ValueError("active simulation was not published by the mixed control")

    ladder_record, _, ladder_bytes = _load_formal_artifact(
        active_manifest.parent,
        active_payload.get("ladder_manifest"),
    )
    ladder = LadderManifest.model_validate_json(ladder_bytes)
    if ladder.scene_id != scene_id:
        raise ValueError("ladder scene does not match the active simulation")
    if ladder.profile_id != profile.profile_id or ladder.profile_sha256 != profile.sha256:
        raise ValueError("ladder profile is missing or stale")
    if tuple(control.control_id for control in ladder.controls) != tuple(
        control.control_id for control in profile.controls
    ):
        raise ValueError("ladder controls differ from the frozen profile")
    cohort = ladder.runtime_cohort
    base_scene = build_scene_config(scene_id)
    if cohort.base_scene_config_sha256 != scene_config_sha256(base_scene):
        raise ValueError("ladder base SceneConfig fingerprint is stale")
    if cohort.design_sha256 != current_design_sha256:
        raise ValueError("ladder station design fingerprint is stale")
    if cohort.metro_runtime_fingerprint != metro_source_fingerprint():
        raise ValueError("ladder Metro runtime fingerprint is stale")
    if cohort.analysis_runtime_fingerprint != analysis_runtime_fingerprint():
        raise ValueError("ladder analysis runtime fingerprint is stale")

    active_saturated = ArtifactRecord.model_validate(
        active_payload.get("saturated_flow_artifact")
    )
    qualifier_seen = False
    for expected_spec, evidence in zip(profile.controls, ladder.controls, strict=True):
        control_record, _, control_bytes = _load_formal_artifact(
            active_manifest.parent,
            evidence.control_artifact,
        )
        control = ControlRunArtifact.model_validate_json(control_bytes)
        if (
            control.control_id != expected_spec.control_id
            or control.control_spec_sha256 != expected_spec.sha256
            or control.profile_sha256 != profile.sha256
            or control.runtime_cohort != cohort
            or control.simulation_manifest != evidence.simulation_manifest
            or control.saturated_flow_artifact != evidence.saturated_flow_artifact
        ):
            raise ValueError(f"formal control artifact mismatch: {expected_spec.control_id}")
        if control_record != evidence.control_artifact:
            raise ValueError(f"formal control record changed: {expected_spec.control_id}")
        _, _, simulation_bytes = _load_formal_artifact(
            active_manifest.parent,
            evidence.simulation_manifest,
        )
        simulation = json.loads(simulation_bytes)
        expected_simulation_fields = {
            "schema_version": SIMULATION_ARTIFACT_SCHEMA_VERSION,
            "scene_id": scene_id,
            "simulation_seed": expected_spec.seed,
            "scene_config_sha256": evidence.scene_config_sha256,
            "design_sha256": cohort.design_sha256,
            "metro_runtime_fingerprint": cohort.metro_runtime_fingerprint,
            "analysis_runtime_fingerprint": cohort.analysis_runtime_fingerprint,
        }
        simulation_contradictions = {
            key: (simulation.get(key), expected)
            for key, expected in expected_simulation_fields.items()
            if simulation.get(key) != expected
        }
        if simulation_contradictions:
            raise ValueError(
                f"control simulation manifest mismatch: {expected_spec.control_id}: "
                f"{simulation_contradictions}"
            )
        if expected_spec.saturated_flow is None:
            continue
        qualifier_seen = True
        if evidence.saturated_flow_artifact != active_saturated:
            raise ValueError("active saturated-flow record differs from the ladder qualifier")
        _, _, saturated_bytes = _load_formal_artifact(
            active_manifest.parent,
            evidence.saturated_flow_artifact,
        )
        saturated = SaturatedFlowArtifact.model_validate_json(saturated_bytes)
        if saturated.gate_status != "pass" or saturated.runtime_cohort != cohort:
            raise ValueError("saturated-flow qualifier is not a current-cohort pass")
    if not qualifier_seen:
        raise ValueError("ladder lacks the preregistered saturated-flow qualifier")
    return [
        f"formal ladder manifest hash={ladder_record.sha256}",
        f"formal controls={','.join(control.control_id for control in ladder.controls)}",
        "preregistered saturated-flow qualifier=pass",
    ]


def _check_simulation_unchecked(scene_id: str) -> tuple[list[str], list[str]]:
    preflight_evidence: list[str] = []
    preflight_path = ROOT / "data" / "metrics" / f"{scene_id}_source_preflight.json"
    if preflight_path.exists():
        try:
            preflight = _load_json(preflight_path)
            config = build_scene_config(scene_id)
            _, current_design_sha256 = build_metro_scenario(config)
            if preflight.get("schema_version") != "alignment_source_preflight_artifact.v2":
                raise ValueError("source preflight artifact schema is stale")
            verify_scene_config_record(preflight, config)
            if preflight.get("design_sha256") != current_design_sha256:
                raise ValueError("source preflight design hash is stale")
            if preflight.get("metro_runtime_fingerprint") != metro_source_fingerprint():
                raise ValueError("source preflight Metro fingerprint is stale")
            if preflight.get(
                "analysis_runtime_fingerprint"
            ) != analysis_runtime_fingerprint():
                raise ValueError("source preflight analysis fingerprint is stale")
            report = _require_source_preflight_semantics(preflight)
            preflight_evidence = [
                "current-fingerprint source geometry preflight completed",
                f"runtime_status={preflight.get('runtime_status')}",
                f"scientific_status={preflight.get('scientific_status')}",
            ]
            if report.get("status") == "fail":
                blockers = report.get("blockers")
                return (
                    preflight_evidence,
                    [
                        (
                            f"{scene_id}: blocker={preflight.get('blocker')}; "
                            f"details={blockers}"
                        )
                    ],
                )
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            return [], [f"{scene_id}: source preflight evidence is invalid: {exc}"]
    manifest = ROOT / "data" / "metrics" / f"{scene_id}_simulated.json"
    if not manifest.exists():
        return preflight_evidence, [f"{scene_id}: simulation manifest missing"]
    try:
        payload = _load_json(manifest)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        return [], [f"{scene_id}: simulation manifest is unreadable: {exc}"]
    evidence: list[str] = []
    blockers: list[str] = []
    if payload.get("schema_version") != "alignment_simulation_metrics.v5":
        blockers.append(
            "current formal simulation bundle is unavailable after source preflight"
            if preflight_evidence
            else "simulation manifest schema is stale"
        )
        return preflight_evidence, [f"{scene_id}: {item}" for item in blockers]
    if (
        payload.get("canonical_schema_version") != CANONICAL_SCHEMA_VERSION
        or payload.get("metric_schema_version") != METRIC_SCHEMA_VERSION
        or payload.get("scene_config_schema_version") != SCENE_CONFIG_SCHEMA_VERSION
    ):
        blockers.append("simulation wrapper dependency schema versions are stale")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        blockers.append("simulation metrics must be an object")
        metrics = {}
    provenance = payload.get("trace_provenance")
    if not isinstance(provenance, dict):
        blockers.append("simulation trace_provenance must be an object")
        provenance = {}
    contract_errors = analysis_contract_consistency_errors(metrics)
    if contract_errors:
        blockers.append(f"analysis contract contradicts method payload: {contract_errors}")
    for metric_key in (WALKING_SPEED_PROXY_KEY, "fundamental_diagram"):
        support_errors = metric_support_errors(
            metrics,
            metric_key,
            side="simulated",
            context={
                "expected_seed": payload.get("simulation_seed"),
                "max_point_n": provenance.get("canonical_point_count"),
                "max_episode_n": provenance.get("episode_count"),
                "max_passenger_n": provenance.get("passenger_count"),
            },
        )
        if support_errors:
            blockers.append(f"{metric_key} contributor support failed: {support_errors}")
    if payload.get("scene_id") != scene_id:
        blockers.append("simulation manifest scene_id is misbound")
    if payload.get("analysis_runtime_fingerprint") == analysis_runtime_fingerprint():
        evidence.append("simulation analysis runtime fingerprint matches current code and lock")
    else:
        blockers.append("simulation analysis runtime fingerprint is missing or stale")
    scene_config_record = payload.get("scene_config")
    if not isinstance(scene_config_record, dict):
        blockers.append("simulation scene_config must be an object")
        scene_config_record = {}
    simulation_seed = payload.get("simulation_seed")
    if (
        isinstance(simulation_seed, int)
        and not isinstance(simulation_seed, bool)
        and simulation_seed == scene_config_record.get("seed")
    ):
        evidence.append(f"seed provenance={simulation_seed}")
    else:
        blockers.append("run seed and manifest seed differ")
    trusted_scene = None
    current_design_sha256 = None
    try:
        trusted_scene = build_scene_config(scene_id)
        verify_scene_config_record(payload, trusted_scene)
        _, current_design_sha256 = build_metro_scenario(trusted_scene)
        if payload.get("design_sha256") != current_design_sha256:
            raise ValueError("current station design hash differs from the manifest")
        evidence.append("exact scene config and current station design hash verified")
    except (KeyError, TypeError, ValueError) as exc:
        blockers.append(f"scene replay contract failed: {exc}")
    if current_design_sha256 is not None:
        try:
            evidence.extend(
                _require_formal_ladder(
                    active_manifest=manifest,
                    active_payload=payload,
                    scene_id=scene_id,
                    current_design_sha256=current_design_sha256,
                )
            )
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            blockers.append(f"formal ladder evidence failed: {exc}")
    if (
        provenance.get("authority") in {"jupedsim", "jupedsim_committed_walk"}
        and provenance.get("included_phases") == ["walking"]
        and provenance.get("coordinates") == "station_model_meters"
        and int(provenance.get("canonical_point_count", 0)) > 0
    ):
        evidence.append(
            f"official walking trace authority={provenance.get('authority')} "
            f"points={provenance.get('canonical_point_count')}"
        )
    else:
        blockers.append(f"official walking trace provenance failed: {provenance}")
    if payload.get("metro_runtime_fingerprint") == metro_source_fingerprint():
        evidence.append(
            "Metro source fingerprint="
            + str(payload["metro_runtime_fingerprint"].get("source_tree_sha256"))
        )
    else:
        blockers.append("simulation artifact Metro source fingerprint is missing or stale")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        blockers.append("simulation artifacts must be an object")
        artifacts = {}
    canonical_record = artifacts.get("canonical", {})
    trace_record = artifacts.get("movement_trace", {})
    if not isinstance(canonical_record, dict):
        blockers.append("canonical artifact record must be an object")
        canonical_record = {}
    if not isinstance(trace_record, dict):
        blockers.append("movement_trace artifact record must be an object")
        trace_record = {}
    resolved: dict[str, tuple[Path, bytes]] = {}
    for name, record in (("canonical", canonical_record), ("movement_trace", trace_record)):
        relative = Path(str(record.get("path", "")))
        path = (manifest.parent / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(manifest.parent.resolve()):
            blockers.append(f"{name} artifact path is not portable")
            continue
        try:
            content = path.read_bytes()
            if (
                len(content) != int(record.get("size_bytes", -1))
                or hashlib.sha256(content).hexdigest() != record.get("sha256")
            ):
                raise ValueError("recorded size or SHA-256 differs")
        except (OSError, TypeError, ValueError) as exc:
            blockers.append(f"{name} artifact missing or hash mismatch: {exc}")
        else:
            evidence.append(f"{name} artifact hash verified from one immutable snapshot")
            resolved[name] = (path, content)
    if "canonical" in resolved and "movement_trace" in resolved and trusted_scene is not None:
        _, canonical_content = resolved["canonical"]
        _, trace_content = resolved["movement_trace"]
        try:
            frame = pd.read_parquet(io.BytesIO(canonical_content))
            errors = validate(frame)
            duplicates = int(frame.duplicated(["agent_id", "t_s"]).sum())
            if errors or duplicates or frame.empty or int(frame["agent_id"].min()) < 90_000_000:
                raise ValueError(
                    f"canonical violations={errors}, duplicates={duplicates}, empty={frame.empty}"
                )
            raw_trace = json.loads(trace_content)
            conversion = movement_trace_to_canonical(
                raw_trace,
                dataset_id=f"simulation:{scene_id}",
                phases=("walking",),
            )
            pd.testing.assert_frame_equal(
                conversion.trajectory,
                frame,
                check_exact=True,
                check_dtype=True,
                check_like=False,
            )
            rebuilt_metrics = compute_simulated_metrics(conversion, config=trusted_scene)
            rebuilt_summary = simulated_trajectory_summary(conversion)
            if provenance != conversion.provenance:
                raise ValueError("trace provenance differs from raw-trace reconstruction")
            if metrics != rebuilt_metrics:
                raise ValueError("metrics differ from deterministic raw-trace recomputation")
            if payload.get("trajectory") != rebuilt_summary:
                raise ValueError("trajectory summary differs from raw-trace reconstruction")
            for name, (artifact_path, _) in resolved.items():
                record = artifacts[name]
                if (
                    artifact_path.stat().st_size != int(record.get("size_bytes", -1))
                    or _sha256(artifact_path) != record.get("sha256")
                ):
                    raise ValueError(f"{name} artifact changed during recomputation")
            evidence.append(
                f"raw trace exactly reproduces canonical, provenance, metrics, and summary; "
                f"rows={len(frame)}"
            )
        except (AssertionError, KeyError, OSError, TypeError, ValueError) as exc:
            blockers.append(f"simulation deterministic reconstruction failed: {exc}")
    return [*preflight_evidence, *evidence], [f"{scene_id}: {item}" for item in blockers]


def _check_simulation(scene_id: str) -> tuple[list[str], list[str]]:
    try:
        return _check_simulation_unchecked(scene_id)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        return [], [f"{scene_id}: simulation evidence has an invalid shape: {exc}"]


def _step5() -> StepResult:
    evidence: list[str] = []
    ready, blockers = _ready_scene_configs()
    for scene_id, _ in ready:
        scene_evidence, scene_blockers = _check_simulation(scene_id)
        evidence.extend(f"{scene_id}: {item}" for item in scene_evidence)
        blockers.extend(scene_blockers)
    return StepResult(5, "仿真轨迹对齐", "fail" if blockers else "pass", evidence, blockers)


def _check_comparison_unchecked(scene_id: str) -> tuple[list[str], list[str]]:
    path = ROOT / "data" / "metrics" / f"comparison_{scene_id}.json"
    if not path.exists():
        return [], [f"{scene_id}: comparison missing"]
    try:
        payload = _load_json(path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        return [], [f"{scene_id}: comparison is unreadable: {exc}"]
    if payload.get("schema_version") != COMPARISON_SCHEMA_VERSION:
        return [], [f"{scene_id}: comparison schema is stale"]
    if payload.get("scene_id") != scene_id:
        return [], [f"{scene_id}: comparison scene_id is misbound"]
    integrity_errors = _comparison_integrity_errors(scene_id, payload)
    if integrity_errors:
        return [], [f"{scene_id}: {item}" for item in integrity_errors]
    verdicts = {name: metric.get("verdict") for name, metric in payload.get("metrics", {}).items()}
    thresholds = payload.get("comparison_thresholds", {})
    expected_thresholds = {
        "walking_speed_proxy_p50_rel_error_max": 0.15,
        "fundamental_support_coverage_min": 0.8,
        "fundamental_conditional_in_band_fraction_min": 0.8,
        "fundamental_min_supported_bins": 3,
        "fundamental_min_density_high_p_m2_exclusive": 0.3,
    }
    release_blockers = payload.get("release_blockers", [])
    if (
        payload.get("overall_verdict") == "pass"
        and verdicts
        and set(verdicts.values()) == {"within_band"}
        and thresholds == expected_thresholds
        and not release_blockers
    ):
        return [f"gates={verdicts}"], []
    return (
        [
            f"comparison executed; gates={verdicts}",
            f"release_blockers={release_blockers}",
        ],
        [f"{scene_id}: calibration thresholds and geometry qualification are not all releasable"],
    )


def _check_comparison(scene_id: str) -> tuple[list[str], list[str]]:
    try:
        return _check_comparison_unchecked(scene_id)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        return [], [f"{scene_id}: comparison evidence has an invalid shape: {exc}"]


def _comparison_integrity_errors(scene_id: str, payload: dict[str, Any]) -> list[str]:
    scene = build_scene_config(scene_id)
    observed_path = (
        ROOT / "data" / "metrics" / f"{scene.observed_dataset_id}_observed.json"
    )
    simulation_path = ROOT / "data" / "metrics" / f"{scene_id}_simulated.json"
    preflight_path = ROOT / "data" / "metrics" / f"{scene_id}_source_preflight.json"
    blocked_after_preflight = (
        payload.get("simulation_evidence_status") == "unavailable_after_preflight"
    )
    required_input = preflight_path if blocked_after_preflight else simulation_path
    if not observed_path.exists() or not required_input.exists():
        return ["comparison inputs are missing"]
    try:
        observed, observed_sha256 = _load_json_snapshot(observed_path)
        if blocked_after_preflight:
            preflight, preflight_sha256 = _load_json_snapshot(preflight_path)
            expected = build_preflight_blocked_comparison_payload(
                scene_id=scene_id,
                observed_artifact=observed,
                preflight_artifact=preflight,
                trusted_observed_dataset_id=scene.observed_dataset_id,
                trusted_desired_speed_mps=scene.jupedsim_desired_speed_mps,
                trusted_geometry_status=scene.geometry_evidence_status,
                observed_input={"path": observed_path.name, "sha256": observed_sha256},
                preflight_input={
                    "path": preflight_path.name,
                    "sha256": preflight_sha256,
                },
            )
        else:
            simulation, simulation_sha256 = _load_json_snapshot(simulation_path)
            expected = build_comparison_payload(
                scene_id=scene_id,
                observed_artifact=observed,
                simulation_artifact=simulation,
                trusted_observed_dataset_id=scene.observed_dataset_id,
                trusted_desired_speed_mps=scene.jupedsim_desired_speed_mps,
                trusted_geometry_status=scene.geometry_evidence_status,
                trusted_evidence_sha256=scene.geometry_evidence_sha256,
                observed_input={"path": observed_path.name, "sha256": observed_sha256},
                simulation_input={
                    "path": simulation_path.name,
                    "sha256": simulation_sha256,
                },
            )
    except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError) as exc:
        return [f"comparison cannot be rebuilt from trusted inputs: {exc}"]
    if payload != expected:
        return ["comparison differs from deterministic trusted-input rebuild"]
    return []


def _step6() -> StepResult:
    evidence: list[str] = []
    ready, blockers = _ready_scene_configs()
    for scene_id, _ in ready:
        scene_evidence, scene_blockers = _check_comparison(scene_id)
        evidence.extend(f"{scene_id}: {item}" for item in scene_evidence)
        blockers.extend(scene_blockers)
    return StepResult(6, "观测-仿真对比", "fail" if blockers else "pass", evidence, blockers)


def _check_report_unchecked(scene_id: str) -> tuple[list[str], list[str], bool]:
    path = ROOT / "data" / "metrics" / f"parameter_report_{scene_id}.json"
    if not path.is_file():
        return [], [f"{scene_id}: parameter report missing"], False
    try:
        payload, _ = _load_json_snapshot(path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        return [], [f"{scene_id}: parameter report is unreadable: {exc}"], False
    rows = payload.get("parameter_table", [])
    required = {
        "parameter",
        "current_value",
        "observed_value",
        "sample_support",
        "source",
        "suggestion",
        "status",
        "uncertainty",
        "evidence",
    }
    comparison_record = payload.get("source_artifacts", {}).get("comparison", {})
    relative = Path(str(comparison_record.get("path", "")))
    metrics_root = (ROOT / "data" / "metrics").resolve()
    comparison_path = (metrics_root / relative).resolve()
    expected_comparison_path = metrics_root / f"comparison_{scene_id}.json"
    source_path_is_safe = (
        bool(relative.name)
        and not relative.is_absolute()
        and relative == Path(relative.name)
        and relative.suffix == ".json"
        and is_portable_basename(relative.name)
        and comparison_path.is_relative_to(metrics_root)
        and comparison_path == expected_comparison_path
    )
    comparison: dict[str, Any] = {}
    comparison_sha256: str | None = None
    comparison_load_error = ""
    if source_path_is_safe and comparison_path.is_file():
        try:
            comparison, comparison_sha256 = _load_json_snapshot(comparison_path)
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            comparison_load_error = str(exc)
    source_is_fresh = (
        comparison_sha256 is not None
        and comparison_record.get("sha256") == comparison_sha256
    )
    source_scene_matches = comparison.get("scene_id") == scene_id
    comparison_errors = (
        _comparison_integrity_errors(scene_id, comparison) if source_scene_matches else []
    )
    source_matches_row = (
        isinstance(rows, list)
        and bool(rows)
        and isinstance(rows[0], dict)
        and rows[0].get("source") == str(relative)
    )
    report_errors = validate_report_payload(payload, comparison)
    rows_valid = (
        isinstance(rows, list)
        and len(rows) == 1
        and isinstance(rows[0], dict)
        and required.issubset(rows[0])
    )
    if (
        payload.get("schema_version") == REPORT_SCHEMA_VERSION
        and payload.get("scene_id") == scene_id
        and rows_valid
        and source_is_fresh
        and source_scene_matches
        and source_matches_row
        and not comparison_errors
        and not report_errors
    ):
        if payload.get("release_decision") == "hold" and any(
            row.get("status") == "validated" for row in rows
        ):
            return [], [f"{scene_id}: hold report labels a parameter as validated"], False
        decision = payload.get("release_decision")
        return (
            [f"report rows={len(rows)}; release_decision={decision}"],
            [],
            decision == "pass",
        )
    return (
        [],
        [
            (
                f"{scene_id}: report schema/required fields, comparison source hash, or "
                "semantic invariants "
                f"are invalid: report={report_errors}; comparison={comparison_errors}; "
                f"source_safe={source_path_is_safe}; source_scene_matches={source_scene_matches}; "
                f"source_matches_row={source_matches_row}; load_error={comparison_load_error}"
            )
        ],
        False,
    )


def _check_report(scene_id: str) -> tuple[list[str], list[str], bool]:
    try:
        return _check_report_unchecked(scene_id)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        return [], [f"{scene_id}: report evidence has an invalid shape: {exc}"], False


def _step7() -> StepResult:
    evidence: list[str] = []
    ready, blockers = _ready_scene_configs()
    authorizations: list[bool] = []
    for scene_id, _ in ready:
        scene_evidence, scene_blockers, authorized = _check_report(scene_id)
        evidence.extend(f"{scene_id}: {item}" for item in scene_evidence)
        blockers.extend(scene_blockers)
        authorizations.append(authorized)
    status: Status = "pass" if not blockers else "fail"
    if blockers and all(blocker.endswith("parameter report missing") for blocker in blockers):
        status = "pending"
    return StepResult(
        7,
        "结果报告",
        status,
        evidence,
        blockers,
        release_authorized=bool(authorizations) and all(authorizations) and not blockers,
    )


def _step8(test_ok: bool, ruff_ok: bool) -> StepResult:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    evidence: list[str] = []
    blockers: list[str] = []
    for pattern in ("data/raw/", "data/canonical/", "data/metrics/*.movement_trace.json"):
        if pattern in ignore:
            evidence.append(f"ignored: {pattern}")
        else:
            blockers.append(f"missing ignore rule: {pattern}")
    specs, registry_errors = _dataset_registry_specs()
    blockers.extend(registry_errors)
    active_specs = [spec for spec in specs if spec.status == "active"]
    ignore_targets = [
        ROOT / "data" / "raw" / spec.dataset_id / file_spec.name
        for spec in active_specs
        for file_spec in spec.files
    ]
    ignore_targets.extend(
        ROOT / "data" / "canonical" / f"{spec.dataset_id}.parquet" for spec in active_specs
    )
    ready, scene_registry_errors = _ready_scene_configs()
    blockers.extend(scene_registry_errors)
    ignore_targets.extend(
        ROOT / "data" / "metrics" / f"{scene_id}_simulated.movement_trace.json"
        for scene_id, _ in ready
    )
    for target in ignore_targets:
        ignored, _ = _run(["git", "check-ignore", "-q", str(target)])
        if ignored:
            evidence.append(f"git confirms ignored: {target.relative_to(ROOT)}")
        else:
            blockers.append(f"git does not ignore: {target.relative_to(ROOT)}")
    if test_ok:
        evidence.append("full pytest suite passed")
    else:
        blockers.append("full pytest suite failed")
    if ruff_ok:
        evidence.append("ruff passed")
    else:
        blockers.append("ruff failed")
    return StepResult(8, "交付与隔离", "fail" if blockers else "pass", evidence, blockers)


def _aggregate_statuses(steps: list[StepResult]) -> tuple[str, str]:
    implementation_steps = [step for step in steps if step.step != 6]
    implementation_status = (
        "pass" if all(step.status == "pass" for step in implementation_steps) else "hold"
    )
    report_step = next(step for step in steps if step.step == 7)
    release_status = (
        "pass"
        if all(step.status == "pass" for step in steps)
        and report_step.release_authorized is True
        else "hold"
    )
    return implementation_status, release_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run executable Step 1-8 acceptance gates.")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--require-release", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime_at_start = {
        "analysis": analysis_runtime_fingerprint(),
        "metro": metro_source_fingerprint(),
        "acceptance": _acceptance_source_fingerprint(),
    }
    if args.skip_tests:
        runtime_at_end = {
            "analysis": analysis_runtime_fingerprint(),
            "metro": metro_source_fingerprint(),
            "acceptance": _acceptance_source_fingerprint(),
        }
        skipped_steps = [
            StepResult(
                step=step,
                name="未执行正式验收",
                status="fail",
                evidence=[],
                blockers=["--skip-tests disables formal acceptance and cannot produce a pass"],
            )
            for step in range(1, 9)
        ]
        payload = {
            "schema_version": "alignment_acceptance.v4",
            "generated_at": datetime.now(UTC).isoformat(),
            "implementation_status": "hold",
            "release_status": "hold",
            "steps": [asdict(step) for step in skipped_steps],
            "commands": {
                "pytest": {"passed": False, "tail": "skipped by caller"},
                "ruff": {"passed": False, "tail": "skipped by caller"},
            },
            "runtime_fingerprints": runtime_at_end,
        }
        if args.out:
            write_json_atomic(args.out, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
        raise SystemExit(1)
    test_ok, test_output = _run([sys.executable, "-m", "pytest", "-q"])
    ruff_ok, ruff_output = _run([sys.executable, "-m", "ruff", "check", "."])
    steps = [
        _step1(),
        _step2(test_ok),
        _step3(),
        _step4(),
        _step5(),
        _step6(),
        _step7(),
        _step8(test_ok, ruff_ok),
    ]
    runtime_at_end = {
        "analysis": analysis_runtime_fingerprint(),
        "metro": metro_source_fingerprint(),
        "acceptance": _acceptance_source_fingerprint(),
    }
    if runtime_at_end != runtime_at_start:
        last = steps[-1]
        steps[-1] = replace(
            last,
            status="fail",
            blockers=[
                *last.blockers,
                "source, lock, tests, or Metro tree changed during acceptance execution",
            ],
        )
    implementation_status, release_status = _aggregate_statuses(steps)
    payload = {
        "schema_version": "alignment_acceptance.v4",
        "generated_at": datetime.now(UTC).isoformat(),
        "implementation_status": implementation_status,
        "release_status": release_status,
        "steps": [asdict(step) for step in steps],
        "commands": {
            "pytest": {"passed": test_ok, "tail": test_output},
            "ruff": {"passed": ruff_ok, "tail": ruff_output},
        },
        "runtime_fingerprints": runtime_at_end,
    }
    if args.out:
        write_json_atomic(args.out, payload)
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    print(text)
    required_status = release_status if args.require_release else implementation_status
    raise SystemExit(0 if required_status == "pass" else 1)


if __name__ == "__main__":
    main()
