from __future__ import annotations

import json

import pandas as pd
import pytest

from metro_alignment.canonical import (
    CANONICAL_COLUMNS,
    build_metadata,
    canonicalize,
    validate,
    write_metadata,
)


def _raw() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "object_identifier": [1, 1, 2, 2],
            "frame": [10, 11, 10, 11],
            "time_ms": [0.0, 1000.0, 0.0, 1000.0],
            "x_position_mm": [0.0, 1000.0, 2000.0, 3000.0],
            "y_position_mm": [0.0, 0.0, 1000.0, 1000.0],
        }
    )


def _canonical(raw: pd.DataFrame | None = None) -> pd.DataFrame:
    return canonicalize(
        _raw() if raw is None else raw,
        dataset_id="demo",
        source_time_col="time_ms",
        source_x_col="x_position_mm",
        source_y_col="y_position_mm",
        source_agent_col="object_identifier",
        source_frame_col="frame",
        x_to_m_scale=0.001,
        t_to_s_scale=0.001,
        agent_id_offset=1000,
    )


def test_canonicalize_enforces_exact_contract() -> None:
    canonical = _canonical()
    assert validate(canonical) == []
    assert list(canonical.columns) == list(CANONICAL_COLUMNS)
    assert canonical["dataset_id"].isna().sum() == 0
    assert canonical["dataset_id"].unique().tolist() == ["demo"]
    assert canonical["frame"].min() == 0


@pytest.mark.parametrize(
    ("mutation", "issue"),
    [
        (lambda frame: frame.assign(extra=1), "columns must exactly equal"),
        (lambda frame: frame.drop(columns="x_m"), "columns must exactly equal"),
        (
            lambda frame: frame.assign(
                t_s=frame["t_s"].mask((frame["agent_id"] == 1001) & (frame["t_s"] == 1.0), 0.0)
            ),
            "strictly increasing",
        ),
        (
            lambda frame: frame.assign(
                dataset_id=pd.Series(["demo", None, "demo", "demo"], dtype="string")
            ),
            "must not contain null",
        ),
        (lambda frame: frame.assign(dataset_id=frame["dataset_id"].astype(object)), "not string"),
    ],
)
def test_validate_rejects_counterexamples(mutation, issue: str) -> None:
    assert any(issue in item for item in validate(mutation(_canonical())))


def test_canonicalize_rejects_bad_ids_and_empty_input() -> None:
    bad = _raw()
    bad["object_identifier"] = bad["object_identifier"].astype(object)
    bad.loc[0, "object_identifier"] = "not-an-id"
    with pytest.raises(ValueError, match="agent ids"):
        _canonical(bad)
    with pytest.raises(ValueError, match="trajectory is empty"):
        _canonical(_raw().iloc[0:0])
    with pytest.raises(ValueError, match="dataset_id must be non-empty"):
        canonicalize(
            _raw(),
            dataset_id=None,  # type: ignore[arg-type]
            source_time_col="time_ms",
            source_x_col="x_position_mm",
            source_y_col="y_position_mm",
            source_agent_col="object_identifier",
            source_frame_col="frame",
            x_to_m_scale=0.001,
            t_to_s_scale=0.001,
            agent_id_offset=1000,
        )


@pytest.mark.parametrize(
    "dtype",
    [object, "category"],
)
def test_validate_requires_pandas_string_dtype(dtype: object) -> None:
    mutated = _canonical()
    mutated["dataset_id"] = mutated["dataset_id"].astype(dtype)
    assert "dataset_id not string" in validate(mutated)


def test_metadata_is_strict_json(tmp_path) -> None:
    canonical = _canonical()
    metadata = build_metadata(
        canonical,
        dataset_id="demo",
        source_url="https://example.test",
        license="CC-BY-4.0",
        citation="Example citation",
        frame_rate_hz=1.0,
    )
    output = tmp_path / "demo.meta.json"
    write_metadata(metadata, output)
    parsed = json.loads(
        output.read_text(encoding="utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )
    assert parsed["row_count"] == 4
