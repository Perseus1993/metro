from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CANONICAL_SCHEMA_VERSION = "alignment_trajectory.v1"

CANONICAL_COLUMNS = {
    "dataset_id": "string",
    "agent_id": "int64",
    "frame": "int64",
    "t_s": "float64",
    "x_m": "float64",
    "y_m": "float64",
}


def _required_source_columns(
    *,
    source_time_col: str,
    source_x_col: str,
    source_y_col: str,
    source_agent_col: str,
) -> tuple[str, ...]:
    return (source_time_col, source_x_col, source_y_col, source_agent_col)


def _require_finite_positive(name: str, value: float) -> None:
    if not np.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and > 0")


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return an exact, sorted canonical frame without mutating the caller."""

    normalized = df.loc[:, list(CANONICAL_COLUMNS)].copy()
    normalized["dataset_id"] = normalized["dataset_id"].astype("string")
    normalized["agent_id"] = pd.to_numeric(normalized["agent_id"], errors="raise").astype("int64")
    normalized["frame"] = pd.to_numeric(normalized["frame"], errors="raise").astype("int64")
    for column in ("t_s", "x_m", "y_m"):
        normalized[column] = pd.to_numeric(normalized[column], errors="raise").astype("float64")
    return normalized.sort_values(["agent_id", "t_s"], kind="mergesort").reset_index(drop=True)


def canonicalize(
    raw_df: pd.DataFrame,
    *,
    dataset_id: str,
    source_time_col: str,
    source_x_col: str,
    source_y_col: str,
    source_agent_col: str,
    source_frame_col: str,
    x_to_m_scale: float,
    t_to_s_scale: float,
    agent_id_offset: int,
) -> pd.DataFrame:
    """Convert a registered source table to the strict six-column contract."""

    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ValueError("dataset_id must be non-empty")
    _require_finite_positive("x_to_m_scale", float(x_to_m_scale))
    _require_finite_positive("t_to_s_scale", float(t_to_s_scale))
    if agent_id_offset < 0:
        raise ValueError("agent_id_offset must be >= 0")
    if raw_df.empty:
        raise ValueError("trajectory is empty")

    required = _required_source_columns(
        source_time_col=source_time_col,
        source_x_col=source_x_col,
        source_y_col=source_y_col,
        source_agent_col=source_agent_col,
    )
    missing = [column for column in required if column not in raw_df.columns]
    if missing:
        raise ValueError(f"raw trajectory missing columns: {missing}")

    agent_values = pd.to_numeric(raw_df[source_agent_col], errors="coerce")
    if agent_values.isna().any() or not np.isfinite(agent_values.to_numpy(dtype=float)).all():
        raise ValueError("source agent ids must be finite numbers")
    if not np.equal(agent_values, np.floor(agent_values)).all():
        raise ValueError("source agent ids must be integers")

    frame = pd.DataFrame(index=raw_df.index)
    frame["dataset_id"] = dataset_id
    frame["agent_id"] = agent_values.astype("int64") + int(agent_id_offset)
    frame["t_s"] = pd.to_numeric(raw_df[source_time_col], errors="coerce") * float(t_to_s_scale)
    frame["x_m"] = pd.to_numeric(raw_df[source_x_col], errors="coerce") * float(x_to_m_scale)
    frame["y_m"] = pd.to_numeric(raw_df[source_y_col], errors="coerce") * float(x_to_m_scale)

    if frame["t_s"].notna().any():
        frame["t_s"] = frame["t_s"] - frame["t_s"].min()

    if source_frame_col and source_frame_col in raw_df.columns:
        source_frame = pd.to_numeric(raw_df[source_frame_col], errors="coerce")
        if source_frame.isna().any() or not np.isfinite(source_frame.to_numpy(dtype=float)).all():
            raise ValueError("source frames must be finite numbers")
        if not np.equal(source_frame, np.floor(source_frame)).all():
            raise ValueError("source frames must be integers")
        frame["frame"] = source_frame.astype("int64") - int(source_frame.min())
    else:
        frame["frame"] = frame["t_s"].rank(method="dense").sub(1).astype("int64")

    canonical = normalize_frame(frame)
    errors = validate(canonical)
    if errors:
        raise ValueError("invalid canonical trajectory: " + "; ".join(errors))
    return canonical


def validate(df: pd.DataFrame) -> list[str]:
    """Return all canonical-contract violations; valid trajectories return []."""

    errors: list[str] = []
    expected_columns = list(CANONICAL_COLUMNS)
    if list(df.columns) != expected_columns:
        errors.append(f"columns must exactly equal {expected_columns}")
        if not set(expected_columns).issubset(df.columns):
            return errors
    if df.empty:
        errors.append("trajectory is empty")
        return errors

    for column, expected in CANONICAL_COLUMNS.items():
        if expected == "string" and not isinstance(df[column].dtype, pd.StringDtype):
            errors.append(f"{column} not string")
        elif expected == "int64" and df[column].dtype != np.dtype("int64"):
            errors.append(f"{column} not int64")
        elif expected == "float64" and df[column].dtype != np.dtype("float64"):
            errors.append(f"{column} not float64")

    if df["dataset_id"].isna().any():
        errors.append("dataset_id must not contain null")
    dataset_ids = df["dataset_id"].dropna().astype(str)
    if dataset_ids.empty or dataset_ids.str.strip().eq("").any():
        errors.append("dataset_id must be non-empty")
    if dataset_ids.nunique() != 1:
        errors.append("trajectory must contain exactly one dataset_id")
    if (df["agent_id"] < 0).any():
        errors.append("agent_id must be >= 0")
    if (df["frame"] < 0).any():
        errors.append("frame must be >= 0")

    numeric = df[["t_s", "x_m", "y_m"]]
    if numeric.isna().any().any():
        errors.append("contains nan in t_s x_m y_m")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        errors.append("contains inf in t_s x_m y_m")
    if (df["t_s"] < 0.0).any():
        errors.append("t_s must be >= 0")
    if (df["x_m"].abs() > 1000).any() or (df["y_m"].abs() > 1000).any():
        errors.append("coordinate out of expected range")

    ordered = df.sort_values(["agent_id", "t_s"], kind="mergesort")
    time_delta = ordered.groupby("agent_id", sort=False)["t_s"].diff().dropna()
    if (time_delta <= 0.0).any():
        errors.append("t_s must be strictly increasing per agent")

    speed = _estimate_speed(ordered)
    if not speed.empty and float(speed.quantile(0.99)) > 3.0:
        errors.append("speed p99 may be wrong (likely unit issue)")
    return errors


def build_metadata(
    df: pd.DataFrame,
    dataset_id: str,
    source_url: str,
    license: str,
    citation: str,
    frame_rate_hz: float,
) -> dict[str, Any]:
    errors = validate(df)
    if errors:
        raise ValueError(
            "cannot build metadata for invalid canonical trajectory: " + "; ".join(errors)
        )
    if dataset_id != str(df["dataset_id"].iloc[0]):
        raise ValueError("metadata dataset_id does not match trajectory")
    if not license.strip() or not citation.strip():
        raise ValueError("license and citation must be non-empty")
    _require_finite_positive("frame_rate_hz", float(frame_rate_hz))

    speed = _estimate_speed(df)
    return {
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "source_url": source_url,
        "license": license,
        "citation": citation,
        "row_count": len(df),
        "agent_count": int(df["agent_id"].nunique()),
        "duration_s": float(df["t_s"].max() - df["t_s"].min()),
        "frame_rate_hz": float(frame_rate_hz),
        "x_range_m": [float(df["x_m"].min()), float(df["x_m"].max())],
        "y_range_m": [float(df["y_m"].min()), float(df["y_m"].max())],
        "speed_p50_m_s": float(speed.quantile(0.5)) if not speed.empty else 0.0,
        "speed_p99_m_s": float(speed.quantile(0.99)) if not speed.empty else 0.0,
        "validation": {
            "checked_rows": len(df),
            "exact_schema": True,
            "finite_time_and_coordinates": True,
            "strict_time_per_agent": True,
            "speed_p99_lte_3_m_s": True,
        },
        "built_at": datetime.now(UTC).isoformat(),
    }


def _estimate_speed(df: pd.DataFrame) -> pd.Series:
    ordered = df.sort_values(["agent_id", "t_s"], kind="mergesort")
    dt = ordered.groupby("agent_id", sort=False)["t_s"].diff()
    dx = ordered.groupby("agent_id", sort=False)["x_m"].diff()
    dy = ordered.groupby("agent_id", sort=False)["y_m"].diff()
    valid = dt > 0.0
    speed = np.sqrt((dx[valid] / dt[valid]) ** 2 + (dy[valid] / dt[valid]) ** 2)
    return pd.Series(speed).replace([np.inf, -np.inf], np.nan).dropna()


def write_canonical(df: pd.DataFrame, out_path: Path) -> None:
    normalized = normalize_frame(df)
    errors = validate(normalized)
    if errors:
        raise ValueError("refusing to write invalid canonical trajectory: " + "; ".join(errors))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_parquet(out_path, index=False)


def write_metadata(meta: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def read_canonical(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    errors = validate(frame)
    if errors:
        raise ValueError(f"invalid canonical trajectory {path}: " + "; ".join(errors))
    return frame
