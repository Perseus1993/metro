from __future__ import annotations

import numpy as np
import pandas as pd

from metro_alignment.canonical import validate


def sample_complete_frame_windows(
    df: pd.DataFrame,
    *,
    max_rows: int | None,
    window_count: int = 5,
    frame_rate_hz: float | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Deterministically sample complete, contiguous frame windows.

    Individual-row sampling corrupts both PedPy speed windows and density. Each
    selected window therefore contains whole frames, and identities are separated
    between windows so PedPy never differentiates across a temporal gap.
    """

    if not isinstance(window_count, int) or isinstance(window_count, bool) or window_count < 1:
        raise ValueError("window_count must be >= 1")
    if max_rows is not None and (
        not isinstance(max_rows, int) or isinstance(max_rows, bool)
    ):
        raise ValueError("max_rows must be an integer or None")
    if frame_rate_hz is not None and (
        not isinstance(frame_rate_hz, (int, float))
        or isinstance(frame_rate_hz, bool)
        or not np.isfinite(frame_rate_hz)
        or frame_rate_hz <= 0.0
    ):
        raise ValueError("frame_rate_hz must be finite and > 0")

    frame_counts = df.groupby("frame", sort=True).size()
    frame_times = df.groupby("frame", sort=True)["t_s"].agg(["min", "max", "median"])
    frame_values = frame_counts.index.to_numpy(dtype=np.int64)
    if frame_values.size == 0:
        raise ValueError("cannot sample a trajectory without frames")
    if frame_rate_hz is not None:
        seconds_per_frame = 1.0 / frame_rate_hz
        time_basis = "explicit_frame_rate"
    else:
        adjacent = frame_times.index.to_series().diff().eq(1)
        ratios = frame_times["median"].diff()[adjacent].to_numpy(dtype=float)
        ratios = ratios[np.isfinite(ratios) & (ratios > 0.0)]
        seconds_per_frame = float(np.median(ratios)) if ratios.size else 1.0
        time_basis = (
            "inferred_from_adjacent_source_frames" if ratios.size else "single_frame_fallback"
        )
    time_tolerance = max(1e-9, seconds_per_frame * 1e-6)
    non_unique_times = (frame_times["max"] - frame_times["min"]) > time_tolerance
    if non_unique_times.any():
        first = int(frame_times.index[non_unique_times][0])
        raise ValueError(f"source frame {first} has non-unique timestamps")
    frame_deltas = np.diff(frame_values)
    time_deltas = np.diff(frame_times["median"].to_numpy(dtype=float))
    source_is_contiguous = bool(
        frame_values.size == 1
        or (
            np.equal(frame_deltas, 1).all()
            and np.less_equal(np.abs(time_deltas - seconds_per_frame), time_tolerance).all()
        )
    )
    if max_rows is None or max_rows <= 0 or len(df) <= max_rows:
        if not source_is_contiguous:
            raise ValueError(
                "full trajectory source frames/timestamps are not contiguous at the trusted rate"
            )
        min_frame = int(frame_values[0])
        max_frame = int(frame_values[-1])
        return df.copy(), {
            "strategy": "full",
            "source_rows": len(df),
            "sampled_rows": len(df),
            "window_count": 1,
            "packed_frame_count": len(frame_values),
            "time_rebased": False,
            "source_continuity_verified": True,
            "seconds_per_frame": seconds_per_frame,
            "time_basis": time_basis,
            "selected_frame_ranges": [[min_frame, max_frame]],
            "packed_window_frame_ranges": [[min_frame, max_frame]],
        }
    actual_windows = min(window_count, len(frame_values))
    target_rows = max(1, max_rows // actual_windows)
    anchor_positions = np.linspace(0, len(frame_values) - 1, actual_windows + 2, dtype=int)[1:-1]
    selected_by_window: dict[int, list[int]] = {}
    claimed: set[int] = set()
    for window_id, anchor in enumerate(anchor_positions):
        selected: list[int] = []
        row_count = 0
        for position in range(int(anchor), len(frame_values)):
            frame = int(frame_values[position])
            if frame in claimed:
                break
            if selected:
                previous = selected[-1]
                source_dt = float(
                    frame_times.loc[frame, "median"] - frame_times.loc[previous, "median"]
                )
                if frame != previous + 1 or abs(source_dt - seconds_per_frame) > time_tolerance:
                    break
            next_count = int(frame_counts.loc[frame])
            if selected and row_count + next_count > target_rows:
                break
            selected.append(frame)
            claimed.add(frame)
            row_count += next_count
            if row_count >= target_rows:
                break
        if selected:
            selected_by_window[window_id] = selected

    frame_to_window = {
        frame: window_id for window_id, frames in selected_by_window.items() for frame in frames
    }
    sampled = df[df["frame"].isin(frame_to_window)].copy()
    sampled["window_id"] = sampled["frame"].map(frame_to_window).astype("int64")

    packed_frame: dict[int, int] = {}
    packed_window_frame_ranges: list[list[int]] = []
    next_frame = 0
    for frames in selected_by_window.values():
        packed_start = next_frame
        for source_frame in frames:
            packed_frame[source_frame] = next_frame
            next_frame += 1
        packed_window_frame_ranges.append([packed_start, next_frame - 1])
    sampled["frame"] = sampled["frame"].map(packed_frame).astype("int64")
    sampled["t_s"] = sampled["frame"].astype("float64") * seconds_per_frame

    identities = (
        sampled[["window_id", "agent_id"]]
        .drop_duplicates()
        .sort_values(["window_id", "agent_id"], kind="mergesort")
    )
    identity_to_agent = {
        (int(row.window_id), int(row.agent_id)): index
        for index, row in enumerate(identities.itertuples(index=False))
    }
    sampled["agent_id"] = [
        identity_to_agent[(int(window), int(agent))]
        for window, agent in zip(sampled["window_id"], sampled["agent_id"], strict=True)
    ]
    sampled = sampled.drop(columns="window_id").sort_values(["agent_id", "t_s"], kind="mergesort")
    sampled["agent_id"] = sampled["agent_id"].astype("int64")
    errors = validate(sampled)
    if errors:
        raise ValueError("sampled canonical trajectory is invalid: " + "; ".join(errors))
    return sampled.reset_index(drop=True), {
        "strategy": "complete_contiguous_frame_windows",
        "source_rows": len(df),
        "sampled_rows": len(sampled),
        "window_count": len(selected_by_window),
        "packed_frame_count": len(packed_frame),
        "time_rebased": True,
        "source_continuity_verified": True,
        "seconds_per_frame": seconds_per_frame,
        "time_basis": time_basis,
        "selected_frame_ranges": [
            [min(frames), max(frames)] for frames in selected_by_window.values()
        ],
        "packed_window_frame_ranges": packed_window_frame_ranges,
    }
