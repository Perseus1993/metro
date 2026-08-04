from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..canonical import canonicalize


def load_atc(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def to_canonical(
    raw_df: pd.DataFrame,
    dataset_id: str,
    *,
    agent_offset: int,
    time_col: str = "timestamp_ms",
    x_col: str = "x_mm",
    y_col: str = "y_mm",
    agent_col: str = "agent_id",
    frame_col: str = "frame",
) -> pd.DataFrame:
    return canonicalize(
        raw_df,
        dataset_id=dataset_id,
        source_time_col=time_col,
        source_x_col=x_col,
        source_y_col=y_col,
        source_agent_col=agent_col,
        source_frame_col=frame_col,
        x_to_m_scale=0.001,
        t_to_s_scale=0.001,
        agent_id_offset=agent_offset,
    )
