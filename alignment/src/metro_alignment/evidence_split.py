from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.compute as pc
import pyarrow.parquet as pq

from metro_alignment.artifact_io import write_json_atomic

SPLIT_SCHEMA_VERSION = "alignment_calibration_holdout_split.v1"
ROOT = Path(__file__).resolve().parents[2]
REQUIRED_COLUMNS = {
    "time_ms",
    "object_identifier",
    "x_position_mm",
    "y_position_mm",
}


def _file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _id_set_sha256(values: set[int]) -> str:
    digest = hashlib.sha256()
    for value in sorted(values):
        digest.update(f"{value}\n".encode("ascii"))
    return digest.hexdigest()


def _portable_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def inspect_parquet(path: Path, *, expected_md5: str | None = None) -> tuple[dict[str, Any], set[int]]:
    path = path.resolve()
    parquet = pq.ParquetFile(path)
    columns = set(parquet.schema_arrow.names)
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise ValueError(f"{path} lacks required columns: {missing}")

    object_ids: set[int] = set()
    time_min: int | None = None
    time_max: int | None = None
    row_n = 0
    for batch in parquet.iter_batches(
        batch_size=1_000_000,
        columns=["time_ms", "object_identifier"],
    ):
        row_n += batch.num_rows
        times = batch.column(0)
        batch_min = int(pc.min(times).as_py())
        batch_max = int(pc.max(times).as_py())
        time_min = batch_min if time_min is None else min(time_min, batch_min)
        time_max = batch_max if time_max is None else max(time_max, batch_max)
        object_ids.update(int(value) for value in np.unique(batch.column(1).to_numpy()))

    if row_n != parquet.metadata.num_rows or time_min is None or time_max is None:
        raise ValueError(f"invalid or empty parquet input: {path}")
    md5 = _file_hash(path, "md5")
    if expected_md5 is not None and md5 != expected_md5:
        raise ValueError(f"MD5 mismatch for {path}: {md5} != {expected_md5}")
    record = {
        "path": _portable_path(path),
        "size_bytes": path.stat().st_size,
        "sha256": _file_hash(path, "sha256"),
        "md5": md5,
        "expected_md5": expected_md5,
        "row_n": row_n,
        "object_identifier_n": len(object_ids),
        "object_identifier_set_sha256": _id_set_sha256(object_ids),
        "time_ms": {"min": time_min, "max": time_max},
        "columns": parquet.schema_arrow.names,
    }
    return record, object_ids


def build_split_manifest(
    calibration_path: Path,
    holdout_path: Path,
    *,
    calibration_dataset_id: str,
    holdout_dataset_id: str,
    calibration_expected_md5: str | None = None,
    holdout_expected_md5: str | None = None,
) -> dict[str, Any]:
    if calibration_dataset_id == holdout_dataset_id:
        raise ValueError("calibration and holdout dataset IDs must differ")
    calibration, calibration_ids = inspect_parquet(
        calibration_path, expected_md5=calibration_expected_md5
    )
    holdout, holdout_ids = inspect_parquet(holdout_path, expected_md5=holdout_expected_md5)
    raw_overlap = calibration_ids & holdout_ids
    effective_holdout_ids = holdout_ids - calibration_ids
    effective_overlap = calibration_ids & effective_holdout_ids
    time_disjoint = (
        calibration["time_ms"]["max"] < holdout["time_ms"]["min"]
        or holdout["time_ms"]["max"] < calibration["time_ms"]["min"]
    )
    proof = {
        "source_file_sha256_distinct": calibration["sha256"] != holdout["sha256"],
        "time_ranges_disjoint": time_disjoint,
        "raw_object_identifier_overlap_n": len(raw_overlap),
        "holdout_excluded_object_identifiers": sorted(raw_overlap),
        "effective_object_identifier_overlap_n": len(effective_overlap),
        "row_overlap_n": 0 if time_disjoint else None,
        "zero_overlap_proven": time_disjoint and not effective_overlap,
        "method": (
            "full Parquet scan of time_ms and object_identifier; holdout excludes every "
            "identifier present in calibration; row overlap is impossible when time ranges "
            "are disjoint"
        ),
    }
    if not proof["source_file_sha256_distinct"] or not proof["zero_overlap_proven"]:
        raise ValueError(f"calibration/holdout split is not independent: {proof}")
    payload: dict[str, Any] = {
        "schema_version": SPLIT_SCHEMA_VERSION,
        "status": "frozen",
        "frozen_on": "2026-08-05",
        "source": {
            "record": "https://zenodo.org/records/13784588",
            "doi": "10.5281/zenodo.13784588",
            "license": "CC-BY-4.0",
        },
        "generator": {
            "module": "metro_alignment.evidence_split",
            "source_sha256": _file_hash(Path(__file__).resolve(), "sha256"),
        },
        "policy": {
            "calibration_use": "days 01-10 only; parameter/candidate selection permitted",
            "holdout_use": (
                "days 11-20 only, excluding every object_identifier present in calibration; "
                "outcome metrics quarantined until candidate freeze"
            ),
            "holdout_filter": "object_identifier NOT IN calibration.object_identifier",
            "holdout_content_inspected": "schema, hashes, row count, time range and IDs only",
            "refreeze_requires_new_schema_or_explicit ADR": True,
        },
        "calibration": {"dataset_id": calibration_dataset_id, **calibration},
        "holdout": {
            "dataset_id": holdout_dataset_id,
            **holdout,
            "effective_object_identifier_n": len(effective_holdout_ids),
        },
        "zero_overlap_proof": proof,
    }
    contract = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    payload["split_contract_sha256"] = hashlib.sha256(contract.encode("utf-8")).hexdigest()
    return payload


def freeze_split(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if current != payload:
            raise FileExistsError(
                f"frozen split differs at {path}; changing it requires a new schema/ADR"
            )
        return
    write_json_atomic(path, payload)
