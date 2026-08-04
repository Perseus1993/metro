from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from metro_alignment.analysis_runtime import analysis_runtime_fingerprint
from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.canonical import CANONICAL_SCHEMA_VERSION, read_canonical
from metro_alignment.datasets.registry import get_dataset_spec
from metro_alignment.metrics.fundamental import METRIC_SCHEMA_VERSION
from metro_alignment.observed_evidence import compute_observed_evidence

OBSERVED_ARTIFACT_SCHEMA_VERSION = "alignment_observed_metrics.v5"


def _artifact_record(path: Path, *, manifest_path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return {
        "path": Path(os.path.relpath(path.resolve(), manifest_path.parent.resolve())).as_posix(),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _parse_bounds(value: str | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    parts = tuple(float(part.strip()) for part in value.split(","))
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("measurement bounds require min_x,min_y,max_x,max_y")
    return parts


def _parse_translation(value: str | None) -> tuple[float, float] | None:
    if value is None:
        return None
    parts = tuple(float(part.strip()) for part in value.split(","))
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("translation requires dx_m,dy_m")
    return parts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute observed metrics from canonical trajectory."
    )
    parser.add_argument("--alignment-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--input", type=Path, required=True, help="canonical parquet path")
    parser.add_argument("--frame-rate-hz", type=float, default=None)
    parser.add_argument(
        "--measurement-bounds",
        default=None,
        help="explicit PedPy measurement rectangle: min_x,min_y,max_x,max_y",
    )
    parser.add_argument("--measurement-area-id", default=None)
    parser.add_argument("--comparison-frame-id", default=None)
    parser.add_argument("--coordinate-transform-id", default=None)
    parser.add_argument(
        "--coordinate-translation-m",
        default=None,
        help="translation from source coordinates into the declared comparison frame: dx,dy",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="optional assertion of the trusted registry sample limit",
    )
    parser.add_argument(
        "--sample-windows",
        type=int,
        default=None,
        help="optional assertion of the trusted registry window count",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_spec = get_dataset_spec(args.dataset_id)
    if dataset_spec.status != "active":
        raise RuntimeError(f"dataset {args.dataset_id} is not active")
    analysis = dataset_spec.observed_analysis
    if analysis is None:
        raise RuntimeError(f"dataset {args.dataset_id} lacks an observed analysis contract")
    requested_contract = {
        "frame_rate_hz": args.frame_rate_hz,
        "measurement_bounds_m": _parse_bounds(args.measurement_bounds),
        "measurement_area_id": args.measurement_area_id,
        "comparison_frame_id": args.comparison_frame_id,
        "coordinate_transform_id": args.coordinate_transform_id,
        "coordinate_translation_m": _parse_translation(args.coordinate_translation_m),
        "max_rows": args.max_rows,
        "window_count": args.sample_windows,
    }
    trusted_contract = {
        "frame_rate_hz": dataset_spec.frame_rate_hz,
        "measurement_bounds_m": analysis.measurement_bounds_m,
        "measurement_area_id": analysis.measurement_area_id,
        "comparison_frame_id": analysis.comparison_frame_id,
        "coordinate_transform_id": analysis.coordinate_transform_id,
        "coordinate_translation_m": analysis.coordinate_translation_m,
        "max_rows": analysis.max_rows,
        "window_count": analysis.window_count,
    }
    mismatches = {
        key: (requested, trusted_contract[key])
        for key, requested in requested_contract.items()
        if requested is not None and requested != trusted_contract[key]
    }
    if mismatches:
        raise ValueError(f"CLI observed-analysis settings contradict registry: {mismatches}")
    runtime_fingerprint = analysis_runtime_fingerprint()
    out_root = args.alignment_root / "data" / "metrics"
    out = out_root / f"{args.dataset_id}_observed.json"
    canonical_meta = args.input.with_suffix(".meta.json")
    if not canonical_meta.exists():
        raise FileNotFoundError(f"canonical metadata is required: {canonical_meta}")
    input_artifacts = {
        "canonical": _artifact_record(args.input, manifest_path=out),
        "canonical_metadata": _artifact_record(canonical_meta, manifest_path=out),
    }
    canonical = read_canonical(args.input)
    actual_dataset_ids = canonical["dataset_id"].drop_duplicates().tolist()
    if actual_dataset_ids != [args.dataset_id]:
        raise ValueError(
            f"--dataset-id {args.dataset_id!r} does not match canonical data {actual_dataset_ids!r}"
        )
    metrics, metadata = compute_observed_evidence(canonical, spec=dataset_spec)
    payload = {
        "schema_version": OBSERVED_ARTIFACT_SCHEMA_VERSION,
        "dataset_id": args.dataset_id,
        "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
        "metric_schema_version": METRIC_SCHEMA_VERSION,
        "analysis_runtime_fingerprint": runtime_fingerprint,
        "input_artifacts": input_artifacts,
        "metrics": metrics,
        "metadata": metadata,
    }
    if analysis_runtime_fingerprint() != runtime_fingerprint:
        raise RuntimeError("alignment analysis source changed during observed metric computation")
    current_inputs = {
        "canonical": _artifact_record(args.input, manifest_path=out),
        "canonical_metadata": _artifact_record(canonical_meta, manifest_path=out),
    }
    if current_inputs != input_artifacts:
        raise RuntimeError("canonical input changed during observed metric computation")
    out_root.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out, payload)
    print(
        json.dumps(
            {"status": "ok", "output": str(out), "sampling": metadata["sampling"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
