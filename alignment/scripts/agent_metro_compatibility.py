from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from metro_station.adapters.simulation.station.compiler import DesignCompiler

from metro_alignment.analysis_runtime import analysis_runtime_fingerprint
from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.canonical import CANONICAL_SCHEMA_VERSION, validate
from metro_alignment.metrics.comparison import metric_support_errors
from metro_alignment.metrics.fundamental import (
    METRIC_SCHEMA_VERSION,
    WALKING_SPEED_PROXY_KEY,
    analysis_contract_consistency_errors,
)
from metro_alignment.metro_contract import SCENE_CONFIG_SCHEMA_VERSION, verify_scene_config_record
from metro_alignment.metro_runtime import metro_source_fingerprint
from metro_alignment.metro_scene import build_metro_request
from metro_alignment.metro_trace import movement_trace_to_canonical
from metro_alignment.scenes import build_scene_config, list_scene_configs
from metro_alignment.simulation_evidence import (
    compute_simulated_metrics,
    simulated_trajectory_summary,
)

ROOT = Path(__file__).resolve().parents[1]
SIMULATION_SCHEMA_VERSION = "alignment_simulation_metrics.v5"
SUPPORTED_AUTHORITIES = {"jupedsim", "jupedsim_committed_walk"}


@dataclass(frozen=True)
class ArtifactSnapshot:
    path: Path
    content: bytes


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("JSON artifact root must be an object")
    return payload


def _finding(severity: str, message: str, evidence: str) -> dict[str, str]:
    return {"severity": severity, "message": message, "evidence": evidence}


def _review_scene_registry(findings: list[dict[str, str]]) -> list[str]:
    evidence: list[str] = []
    ready = []
    pending = []
    for scene_id, config in list_scene_configs():
        if config.status == "ready":
            ready.append(scene_id)
            if config.measurement_bounds_m is None or not config.measurement_area_id:
                findings.append(_finding("P1", "ready scene lacks measurement contract", scene_id))
        else:
            pending.append(scene_id)
            if not config.pending_reason:
                findings.append(_finding("P1", "pending scene lacks reason", scene_id))
    if not ready:
        findings.append(_finding("P0", "no ready scene exercises the Metro seam", "registry"))
    evidence.append(f"ready={ready}; pending={pending}")
    return evidence


def _review_artifact_record(
    manifest_path: Path,
    name: str,
    record: dict[str, Any],
    findings: list[dict[str, str]],
) -> ArtifactSnapshot | None:
    raw_path = Path(str(record.get("path", "")))
    if not raw_path.name or raw_path.is_absolute():
        findings.append(_finding("P1", f"{name} path is missing or absolute", str(raw_path)))
        return None
    path = (manifest_path.parent / raw_path).resolve()
    try:
        path.relative_to(manifest_path.parent.resolve())
    except ValueError:
        findings.append(_finding("P1", f"{name} escapes manifest directory", str(raw_path)))
        return None
    if not path.is_file():
        findings.append(_finding("P1", f"{name} artifact is missing", str(path)))
        return None
    content = path.read_bytes()
    if len(content) != int(record.get("size_bytes", -1)):
        findings.append(_finding("P1", f"{name} size mismatch", str(path)))
    if hashlib.sha256(content).hexdigest() != record.get("sha256"):
        findings.append(_finding("P1", f"{name} SHA-256 mismatch", str(path)))
    return ArtifactSnapshot(path=path, content=content)


def _review_manifest(scene_id: str, findings: list[dict[str, str]]) -> list[str]:
    evidence: list[str] = []
    path = ROOT / "data" / "metrics" / f"{scene_id}_simulated.json"
    if not path.exists():
        findings.append(_finding("P1", "Metro simulation manifest is missing", str(path)))
        return evidence
    try:
        payload = _read_json(path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        findings.append(_finding("P1", "simulation manifest is unreadable", f"{path}: {exc}"))
        return evidence
    if payload.get("schema_version") != SIMULATION_SCHEMA_VERSION:
        findings.append(_finding("P1", "simulation manifest schema is stale", str(path)))
        return evidence
    if (
        payload.get("canonical_schema_version") != CANONICAL_SCHEMA_VERSION
        or payload.get("metric_schema_version") != METRIC_SCHEMA_VERSION
        or payload.get("scene_config_schema_version") != SCENE_CONFIG_SCHEMA_VERSION
    ):
        findings.append(
            _finding("P1", "simulation wrapper dependency schema is stale", str(path))
        )
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        findings.append(_finding("P1", "simulation metrics must be an object", str(path)))
        metrics = {}
    provenance = payload.get("trace_provenance")
    if not isinstance(provenance, dict):
        findings.append(_finding("P1", "trace provenance must be an object", str(path)))
        provenance = {}
    if metrics.get("schema_version") != METRIC_SCHEMA_VERSION:
        findings.append(_finding("P1", "simulation metric schema is stale", str(path)))
    contract_errors = analysis_contract_consistency_errors(metrics)
    if contract_errors:
        findings.append(
            _finding(
                "P1",
                "simulation analysis contract contradicts its method payload",
                f"{path}: {contract_errors}",
            )
        )
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
            findings.append(
                _finding(
                    "P1",
                    "simulation metric contributor support contract failed",
                    f"{path}: {metric_key}: {support_errors}",
                )
            )
    if payload.get("scene_id") != scene_id:
        findings.append(_finding("P1", "simulation manifest scene_id is misbound", str(path)))
    comparability = payload.get("scientific_comparability", {})
    if (
        comparability.get("geometry_evidence_status") == "proxy"
        and comparability.get("release_eligible") is False
        and comparability.get("geometry_evidence")
    ):
        evidence.append(f"{scene_id} geometry is explicitly proxy and release-ineligible")
    elif (
        comparability.get("geometry_evidence_status") == "observed_matched"
        and comparability.get("release_eligible") is True
    ):
        evidence.append(f"{scene_id} geometry is observed-matched and release-eligible")
    else:
        findings.append(
            _finding(
                "P1",
                "simulation geometry qualification is missing/inconsistent",
                str(comparability),
            )
        )
    seed = payload.get("simulation_seed")
    scene_config_record = payload.get("scene_config")
    if not isinstance(scene_config_record, dict):
        findings.append(_finding("P1", "scene_config must be an object", str(path)))
        scene_config_record = {}
    if seed != scene_config_record.get("seed"):
        findings.append(
            _finding("P1", "CLI/request/manifest seed contract is inconsistent", str(seed))
        )
    try:
        current_config = build_scene_config(scene_id)
        verify_scene_config_record(payload, current_config)
        request, current_design_sha256 = build_metro_request(current_config)
        scenario = request.scenario
        if scenario.simulation_clock_mode != "physical":
            raise ValueError("alignment Metro scenario must use a physical clock")
        if scenario.movement_backend_name != "jupedsim":
            raise ValueError("alignment Metro scenario must use the JuPedSim movement backend")
        if request.seed != current_config.seed or request.seed != seed:
            raise ValueError("SimulationRequest does not preserve the manifest/config seed")
        DesignCompiler.compile(scenario.station_design, scenario)
        if current_design_sha256 != payload.get("design_sha256"):
            findings.append(
                _finding(
                    "P1",
                    "manifest design hash differs from the current compiled scene",
                    f"manifest={payload.get('design_sha256')}; current={current_design_sha256}",
                )
            )
        else:
            evidence.append("exact scene config and current Metro design compilation verified")
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        findings.append(_finding("P1", "current Metro scene contract failed", str(exc)))
    if payload.get("metro_runtime_fingerprint") == metro_source_fingerprint():
        evidence.append("manifest Metro source fingerprint matches current package sources")
    else:
        findings.append(
            _finding(
                "P1",
                "simulation evidence was produced by a different or unidentified Metro source tree",
                str(payload.get("metro_runtime_fingerprint")),
            )
        )
    if payload.get("analysis_runtime_fingerprint") == analysis_runtime_fingerprint():
        evidence.append("manifest alignment analysis fingerprint matches current code and lock")
    else:
        findings.append(
            _finding(
                "P1",
                "simulation metrics were produced by stale alignment analysis code",
                str(payload.get("analysis_runtime_fingerprint")),
            )
        )
    if provenance.get("authority") not in SUPPORTED_AUTHORITIES:
        findings.append(_finding("P1", "trace authority is unsupported", str(provenance)))
    if provenance.get("included_phases") != ["walking"]:
        findings.append(_finding("P1", "metric trajectory is not walking-only", str(provenance)))
    if provenance.get("coordinates") != "station_model_meters":
        findings.append(_finding("P1", "trace coordinates are not station meters", str(provenance)))
    if int(provenance.get("canonical_point_count", 0)) <= 0:
        findings.append(
            _finding("P1", "walking trace contains no canonical points", str(provenance))
        )

    records = payload.get("artifacts")
    if not isinstance(records, dict):
        findings.append(_finding("P1", "artifacts must be an object", str(path)))
        records = {}
    canonical_record = records.get("canonical", {})
    trace_record = records.get("movement_trace", {})
    if not isinstance(canonical_record, dict):
        findings.append(_finding("P1", "canonical artifact record must be an object", str(path)))
        canonical_record = {}
    if not isinstance(trace_record, dict):
        findings.append(
            _finding("P1", "movement_trace artifact record must be an object", str(path))
        )
        trace_record = {}
    canonical_snapshot = _review_artifact_record(
        path, "canonical", canonical_record, findings
    )
    trace_snapshot = _review_artifact_record(
        path, "movement_trace", trace_record, findings
    )
    if canonical_snapshot and trace_snapshot:
        frame = pd.read_parquet(io.BytesIO(canonical_snapshot.content))
        errors = validate(frame)
        if errors:
            findings.append(
                _finding("P1", "simulation canonical contract failed", "; ".join(errors))
            )
        if not frame.empty and int(frame["agent_id"].min()) < 90_000_000:
            findings.append(
                _finding(
                    "P1",
                    "episode-aware simulation ID namespace failed",
                    str(canonical_snapshot.path),
                )
            )
        duplicate_agent_time = int(frame.duplicated(["agent_id", "t_s"]).sum())
        if duplicate_agent_time:
            findings.append(
                _finding(
                    "P1", "duplicate simulation agent-time rows remain", str(duplicate_agent_time)
                )
            )
        evidence.append(
            f"walking canonical rows={len(frame):,}, agents={frame['agent_id'].nunique():,}, "
            f"duplicate_agent_time={duplicate_agent_time}"
        )
        try:
            raw_trace = json.loads(trace_snapshot.content)
            reconstructed = movement_trace_to_canonical(
                raw_trace,
                dataset_id=f"simulation:{scene_id}",
                phases=("walking",),
            )
            pd.testing.assert_frame_equal(
                reconstructed.trajectory,
                frame,
                check_exact=True,
                check_dtype=True,
                check_like=False,
            )
            if reconstructed.provenance != provenance:
                findings.append(
                    _finding(
                        "P1",
                        "manifest trace provenance differs from an independent raw-trace parse",
                        f"rebuilt={reconstructed.provenance}; manifest={provenance}",
                    )
                )
            else:
                evidence.append(
                    "raw movement trace independently parsed; canonical and provenance match exactly"
                )
            rebuilt_metrics = compute_simulated_metrics(reconstructed, config=current_config)
            if rebuilt_metrics != metrics:
                findings.append(
                    _finding(
                        "P1",
                        "simulation metrics differ from independent raw-trace recomputation",
                        str(path),
                    )
                )
            elif simulated_trajectory_summary(reconstructed) != payload.get("trajectory"):
                findings.append(
                    _finding(
                        "P1",
                        "simulation trajectory summary differs from raw-trace recomputation",
                        str(path),
                    )
                )
            else:
                evidence.append("simulation metrics and trajectory summary exactly recomputed")
        except (AssertionError, KeyError, TypeError, ValueError) as exc:
            findings.append(
                _finding("P1", "raw trace does not reproduce saved canonical evidence", str(exc))
            )
    evidence.append(
        f"seed={seed}; design_sha256={payload.get('design_sha256')}; "
        f"authority={provenance.get('authority')}"
    )
    return evidence


def run(round_id: int) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    try:
        evidence = _review_scene_registry(findings)
        scenes = list_scene_configs()
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        findings.append(_finding("P0", "scene registry is invalid", str(exc)))
        evidence = []
        scenes = ()
    for scene_id, config in scenes:
        if config.status == "ready":
            evidence.extend(_review_manifest(scene_id, findings))
    blockers = [item for item in findings if item["severity"] in {"P0", "P1"}]
    return {
        "round": round_id,
        "agent": "metro_compatibility",
        "status": "fail" if blockers else "pass",
        "evidence": evidence,
        "findings": findings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review alignment/Metro seam evidence")
    parser.add_argument("--round", type=int, default=1, dest="round_id")
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = run(args.round_id)
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    if args.out:
        write_json_atomic(args.out, payload)
    print(text)
    raise SystemExit(0 if payload["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
