from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..canonical import canonicalize


def load_eindhoven(path: Path) -> pd.DataFrame:
    """Load one Eindhoven parquet file."""
    return pd.read_parquet(path)


def to_canonical(
    raw_df: pd.DataFrame,
    dataset_id: str,
    *,
    agent_offset: int,
) -> pd.DataFrame:
    return canonicalize(
        raw_df,
        dataset_id=dataset_id,
        source_time_col="time_ms",
        source_x_col="x_position_mm",
        source_y_col="y_position_mm",
        source_agent_col="object_identifier",
        source_frame_col="frame",
        x_to_m_scale=0.001,
        t_to_s_scale=0.001,
        agent_id_offset=agent_offset,
    )


def load_all_from_dir(directory: Path) -> pd.DataFrame:
    if not directory.is_dir():
        raise FileNotFoundError(f"Eindhoven source directory does not exist: {directory}")
    frames = []
    for path in sorted(directory.glob("*.parquet")):
        if "trajectories" in path.name:
            frames.append(load_eindhoven(path))
    if not frames:
        raise FileNotFoundError(
            f"no Eindhoven trajectory parquet matching '*trajectories*.parquet' in {directory}"
        )
    return pd.concat(frames, axis=0, ignore_index=True)
