from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from metro_alignment.evidence_split import build_split_manifest, freeze_split


def _write_input(path: Path, *, times: list[int], ids: list[int]) -> None:
    pd.DataFrame(
        {
            "time_ms": times,
            "object_identifier": ids,
            "x_position_mm": [100] * len(times),
            "y_position_mm": [200] * len(times),
        }
    ).to_parquet(path, index=False)


def test_split_full_scan_proves_zero_overlap_and_freezes_hashes(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration.parquet"
    holdout = tmp_path / "holdout.parquet"
    output = tmp_path / "split.json"
    _write_input(calibration, times=[0, 10, 20], ids=[1, 1, 2])
    _write_input(holdout, times=[30, 40, 50], ids=[3, 3, 4])

    payload = build_split_manifest(
        calibration,
        holdout,
        calibration_dataset_id="calibration-v1",
        holdout_dataset_id="holdout-v1",
    )
    freeze_split(output, payload)
    freeze_split(output, payload)

    frozen = json.loads(output.read_text(encoding="utf-8"))
    assert frozen["status"] == "frozen"
    assert frozen["zero_overlap_proof"]["zero_overlap_proven"] is True
    assert frozen["zero_overlap_proof"]["effective_object_identifier_overlap_n"] == 0
    assert len(frozen["calibration"]["sha256"]) == 64
    assert len(frozen["holdout"]["sha256"]) == 64


def test_split_quarantines_cross_boundary_agent_overlap(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration.parquet"
    holdout = tmp_path / "holdout.parquet"
    _write_input(calibration, times=[0, 10], ids=[1, 2])
    _write_input(holdout, times=[20, 30], ids=[2, 3])
    payload = build_split_manifest(
        calibration,
        holdout,
        calibration_dataset_id="calibration-v1",
        holdout_dataset_id="holdout-v1",
    )
    proof = payload["zero_overlap_proof"]
    assert proof["raw_object_identifier_overlap_n"] == 1
    assert proof["holdout_excluded_object_identifiers"] == [2]
    assert proof["effective_object_identifier_overlap_n"] == 0
    assert proof["zero_overlap_proven"] is True


def test_split_rejects_overlapping_time_ranges(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration.parquet"
    holdout = tmp_path / "holdout.parquet"
    _write_input(calibration, times=[0, 20], ids=[1, 2])
    _write_input(holdout, times=[10, 30], ids=[3, 4])
    with pytest.raises(ValueError, match="not independent"):
        build_split_manifest(
            calibration,
            holdout,
            calibration_dataset_id="calibration-v1",
            holdout_dataset_id="holdout-v1",
        )


def test_frozen_split_rejects_mutation(tmp_path: Path) -> None:
    output = tmp_path / "split.json"
    freeze_split(output, {"schema_version": "v1", "value": 1})
    with pytest.raises(FileExistsError, match="requires a new schema/ADR"):
        freeze_split(output, {"schema_version": "v1", "value": 2})
