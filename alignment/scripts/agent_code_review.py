from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from metro_alignment.analysis_runtime import analysis_runtime_fingerprint
from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.canonical import CANONICAL_COLUMNS, CANONICAL_SCHEMA_VERSION, read_canonical
from metro_alignment.datasets.registry import get_dataset_spec, list_dataset_specs
from metro_alignment.metrics.comparison import metric_support_errors
from metro_alignment.metrics.fundamental import (
    METRIC_SCHEMA_VERSION,
    WALKING_SPEED_PROXY_KEY,
    analysis_contract_consistency_errors,
)
from metro_alignment.observed_evidence import compute_observed_evidence

ROOT = Path(__file__).resolve().parents[1]
OBSERVED_SCHEMA_VERSION = "alignment_observed_metrics.v5"

METHOD_SOURCES = [
    "https://pedpy.readthedocs.io/stable/user_guide.html",
    "https://pedpy.readthedocs.io/stable/fundamental_diagram_at_measurement_line.html",
    "https://arxiv.org/abs/2409.11857",
    "https://doi.org/10.1016/j.trpro.2014.09.081",
    "https://doi.org/10.1016/j.simpat.2017.05.002",
]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("JSON artifact root must be an object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finding(severity: str, message: str, evidence: str) -> dict[str, str]:
    return {"severity": severity, "message": message, "evidence": evidence}


def _ordered_finite(values: list[Any]) -> bool:
    try:
        numbers = [float(value) for value in values]
    except (TypeError, ValueError):
        return False
    return all(math.isfinite(value) for value in numbers) and numbers == sorted(numbers)


def _review_canonical(dataset_id: str, findings: list[dict[str, str]]) -> list[str]:
    evidence: list[str] = []
    path = ROOT / "data" / "canonical" / f"{dataset_id}.parquet"
    meta_path = path.with_suffix(".meta.json")
    if not path.exists() or not meta_path.exists():
        findings.append(_finding("P1", "canonical real-data evidence is missing", str(path)))
        return evidence
    try:
        parquet = pq.ParquetFile(path)
        meta = _read_json(meta_path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        findings.append(_finding("P1", "canonical evidence is unreadable", f"{path}: {exc}"))
        return evidence
    if parquet.schema_arrow.names != list(CANONICAL_COLUMNS):
        findings.append(
            _finding("P1", "canonical Parquet schema/order is not exact", str(parquet.schema_arrow))
        )
    if meta.get("schema_version") != CANONICAL_SCHEMA_VERSION:
        findings.append(_finding("P1", "canonical metadata schema is stale", str(meta_path)))
    if int(meta.get("row_count", -1)) != parquet.metadata.num_rows:
        findings.append(_finding("P1", "metadata row_count disagrees with Parquet", str(meta_path)))
    validation = meta.get("validation", {})
    if validation.get("checked_rows") != parquet.metadata.num_rows or not all(
        validation.get(key) is True
        for key in (
            "exact_schema",
            "finite_time_and_coordinates",
            "strict_time_per_agent",
            "speed_p99_lte_3_m_s",
        )
    ):
        findings.append(
            _finding("P1", "full canonical validation evidence is incomplete", str(meta_path))
        )
    evidence.append(f"{dataset_id}: canonical rows={parquet.metadata.num_rows:,}")
    return evidence


def _review_observed(dataset_id: str, findings: list[dict[str, str]]) -> list[str]:
    evidence: list[str] = []
    path = ROOT / "data" / "metrics" / f"{dataset_id}_observed.json"
    if not path.exists():
        findings.append(_finding("P1", "observed metric evidence is missing", str(path)))
        return evidence
    try:
        payload = _read_json(path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        findings.append(_finding("P1", "observed metric evidence is unreadable", f"{path}: {exc}"))
        return evidence
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        findings.append(_finding("P1", "observed metrics must be an object", str(path)))
        metrics = {}
    method = metrics.get("method", {})
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        findings.append(_finding("P1", "observed metadata must be an object", str(path)))
        metadata = {}
    sampling = metadata.get("sampling")
    if not isinstance(sampling, dict):
        findings.append(_finding("P1", "observed sampling must be an object", str(path)))
        sampling = {}
    input_artifacts = payload.get("input_artifacts")
    if not isinstance(input_artifacts, dict):
        findings.append(_finding("P1", "input_artifacts must be an object", str(path)))
        input_artifacts = {}
    if payload.get("schema_version") != OBSERVED_SCHEMA_VERSION:
        findings.append(_finding("P1", "observed artifact schema is stale", str(path)))
    if metrics.get("schema_version") != METRIC_SCHEMA_VERSION:
        findings.append(_finding("P1", "metric schema is stale", str(path)))
    if payload.get("analysis_runtime_fingerprint") != analysis_runtime_fingerprint():
        findings.append(_finding("P1", "observed analysis runtime fingerprint is stale", str(path)))
    expected_inputs = {
        "canonical": ROOT / "data" / "canonical" / f"{dataset_id}.parquet",
        "canonical_metadata": ROOT / "data" / "canonical" / f"{dataset_id}.meta.json",
    }
    for name, expected in expected_inputs.items():
        record = input_artifacts.get(name, {})
        if not isinstance(record, dict):
            findings.append(
                _finding("P1", "input artifact record must be an object", f"{path}: {name}")
            )
            record = {}
        resolved = (path.parent / Path(str(record.get("path", "")))).resolve()
        if not (
            expected.exists()
            and resolved == expected.resolve()
            and expected.stat().st_size == int(record.get("size_bytes", -1))
            and _sha256(expected) == record.get("sha256")
        ):
            findings.append(
                _finding("P1", "observed input artifact is stale or misbound", f"{path}: {name}")
            )
    try:
        rebuilt_metrics, rebuilt_metadata = compute_observed_evidence(
            read_canonical(expected_inputs["canonical"]),
            spec=get_dataset_spec(dataset_id),
        )
        if metrics != rebuilt_metrics or payload.get("metadata") != rebuilt_metadata:
            findings.append(
                _finding(
                    "P1",
                    "observed metrics/metadata differ from canonical recomputation",
                    str(path),
                )
            )
        else:
            evidence.append(f"{dataset_id}: observed metrics exactly recomputed from canonical")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        findings.append(
            _finding("P1", "observed deterministic recomputation failed", f"{path}: {exc}")
        )
    consistency_errors = analysis_contract_consistency_errors(metrics)
    if consistency_errors:
        findings.append(
            _finding(
                "P1",
                "analysis contract contradicts its method payload",
                f"{path}: {consistency_errors}",
            )
        )
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
            findings.append(
                _finding(
                    "P1",
                    "metric contributor support contract failed",
                    f"{path}: {metric_key}: {support_errors}",
                )
            )
    expected_methods = {
        "library": "PedPy",
        "speed": "compute_individual_speed:BORDER_SINGLE_SIDED",
        "density": "compute_classic_density",
        "frame_mean_speed": "compute_mean_speed_per_frame",
    }
    if any(method.get(key) != value for key, value in expected_methods.items()):
        findings.append(
            _finding("P1", "recorded PedPy method provenance is incomplete", str(method))
        )
    area = method.get("measurement_area", {})
    if area.get("source") != "explicit" or area.get("comparable") is not True or not area.get("id"):
        findings.append(
            _finding("P1", "measurement geometry is not explicit/comparable", str(area))
        )
    contract = metrics.get("analysis_contract", {})
    if (
        contract.get("schema_version") != "alignment_analysis_contract.v1"
        or contract.get("library", {}).get("name") != "PedPy"
        or contract.get("speed", {}).get("physical_window_s") != 0.4
        or contract.get("density", {}).get("method") != "compute_classic_density"
        or not contract.get("measurement", {}).get("comparison_polygon_sha256")
    ):
        findings.append(_finding("P1", "normalized analysis contract is incomplete", str(contract)))
    proxy_contract = contract.get("walking_speed_proxy", {})
    if (
        proxy_contract.get("semantics") == "low_global_density_speed_truncated_proxy"
        and proxy_contract.get("desired_speed_release_eligible") is False
    ):
        findings.append(
            _finding(
                "P2",
                "speed evidence is a declared non-release proxy, not isolated free-flow speed",
                str(proxy_contract),
            )
        )

    free_flow = metrics.get(WALKING_SPEED_PROXY_KEY, {})
    percentiles = [free_flow.get(key) for key in ("p5", "p25", "p50", "p75", "p95")]
    if int(free_flow.get("n", 0)) < 30 or not _ordered_finite(percentiles):
        findings.append(
            _finding(
                "P1", "walking-speed proxy sample/percentiles fail method gate", str(free_flow)
            )
        )
    else:
        p50 = float(free_flow["p50"])
        if not 0.5 <= p50 <= 2.5:
            findings.append(
                _finding("P1", "walking-speed proxy median fails sanity gate", f"p50={p50}")
            )
        evidence.append(f"{dataset_id}: walking-speed proxy n={free_flow['n']}, p50={p50:.3f} m/s")

    bins = metrics.get("fundamental_diagram", {}).get("bins", [])
    if not bins:
        findings.append(_finding("P1", "fundamental-diagram bins are empty", str(path)))
    elif len(bins) < 3 or max(float(row.get("density_high_p_m2", 0.0)) for row in bins) <= 0.3:
        findings.append(
            _finding(
                "P2",
                "observed sample does not cover a congested fundamental-diagram branch",
                f"populated_bins={len(bins)}, max_density_high={max(float(row.get('density_high_p_m2', 0.0)) for row in bins)}",
            )
        )
    if sampling.get("strategy") == "complete_contiguous_frame_windows":
        if sampling.get("time_rebased") is not True:
            findings.append(
                _finding(
                    "P1",
                    "sample windows retain gaps that can create fake zero-density frames",
                    str(sampling),
                )
            )
        packed_frames = int(sampling.get("packed_frame_count", 0))
        binned_frames = sum(int(item.get("n", 0)) for item in bins)
        if packed_frames <= 0 or binned_frames > packed_frames:
            findings.append(
                _finding(
                    "P1",
                    "PedPy FD evidence exceeds sampled frame support",
                    f"binned_frames={binned_frames}, packed_frames={packed_frames}",
                )
            )
        evidence.append(
            f"{dataset_id}: complete-window sample rows={sampling.get('sampled_rows')}, "
            f"packed_frames={packed_frames}"
        )
    else:
        evidence.append(f"{dataset_id}: full trajectory metric evaluation")
    return evidence


def run(round_id: int) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    evidence: list[str] = []
    active = [spec for spec in list_dataset_specs() if spec.status == "active"]
    if not active:
        findings.append(_finding("P0", "registry has no active real dataset", "dataset registry"))
    for spec in active:
        evidence.extend(_review_canonical(spec.dataset_id, findings))
        evidence.extend(_review_observed(spec.dataset_id, findings))
    blockers = [item for item in findings if item["severity"] in {"P0", "P1"}]
    return {
        "round": round_id,
        "agent": "industry_paper_methodology",
        "status": "fail" if blockers else "pass",
        "method_sources": METHOD_SOURCES,
        "evidence": evidence,
        "findings": findings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review PedPy/paper methodology evidence")
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
