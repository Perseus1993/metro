from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..canonical import canonicalize


def detect_columns(df: pd.DataFrame) -> tuple[str, str, str, str, str]:
    expected = {
        "frame": ["frame", "id", "x", "y", "traj_id", "agent", "agent_id"],
        "agent": ["agent_id", "id", "pid", "person", "traj_id", "track_id"],
        "x": ["x", "x_m", "pos_x", "X", "px"],
        "y": ["y", "y_m", "pos_y", "Y", "py"],
        "time": ["time", "t", "frame", "timestamp"],
    }
    rename_map = {}
    cols_lower = {c.lower(): c for c in df.columns}
    for target, candidates in expected.items():
        found = next((c for c in candidates if c.lower() in cols_lower), None)
        if not found:
            raise ValueError(f"missing expected column for {target}")
        rename_map[target] = cols_lower[found.lower()]
    return (
        rename_map["time"],
        rename_map["x"],
        rename_map["y"],
        rename_map["agent"],
        rename_map["frame"],
    )


def load_julich(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, delim_whitespace=True, comment="#")


def to_canonical(raw_df: pd.DataFrame, dataset_id: str, *, agent_offset: int) -> pd.DataFrame:
    src_time, src_x, src_y, src_agent, src_frame = detect_columns(raw_df)
    return canonicalize(
        raw_df,
        dataset_id=dataset_id,
        source_time_col=src_time,
        source_x_col=src_x,
        source_y_col=src_y,
        source_agent_col=src_agent,
        source_frame_col=src_frame,
        x_to_m_scale=1.0,
        t_to_s_scale=1 / 25.0,
        agent_id_offset=agent_offset,
    )
