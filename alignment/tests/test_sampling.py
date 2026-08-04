from __future__ import annotations

import pandas as pd
import pytest

from metro_alignment.canonical import canonicalize, validate
from metro_alignment.metrics.fundamental import MetricConfig, compute_metric_table
from metro_alignment.sampling import sample_complete_frame_windows


def _many_frames() -> pd.DataFrame:
    rows = [
        {"id": agent, "frame": frame, "t": frame / 10.0, "x": frame / 10.0, "y": float(agent)}
        for frame in range(100)
        for agent in (1, 2)
    ]
    return canonicalize(
        pd.DataFrame(rows),
        dataset_id="sample",
        source_time_col="t",
        source_x_col="x",
        source_y_col="y",
        source_agent_col="id",
        source_frame_col="frame",
        x_to_m_scale=1.0,
        t_to_s_scale=1.0,
        agent_id_offset=0,
    )


def test_sampling_keeps_complete_frames_and_is_order_invariant() -> None:
    source = _many_frames()
    sampled, metadata = sample_complete_frame_windows(source, max_rows=40, window_count=2)
    shuffled, shuffled_metadata = sample_complete_frame_windows(
        source.sample(frac=1.0, random_state=7),
        max_rows=40,
        window_count=2,
    )
    assert validate(sampled) == []
    assert sampled.groupby("frame").size().eq(2).all()
    assert sampled["frame"].max() - sampled["frame"].min() + 1 == sampled["frame"].nunique()
    assert sampled["t_s"].max() < 10.0
    assert metadata["time_rebased"] is True
    metrics = compute_metric_table(
        sampled,
        config=MetricConfig(
            frame_rate_hz=10.0,
            measurement_bounds_m=(0.0, 0.0, 20.0, 3.0),
            measurement_area_id="sampling-test",
            comparison_frame_id="sampling-shared",
            coordinate_transform_id="identity",
            coordinate_translation_m=(0.0, 0.0),
        ),
    )
    binned_frames = sum(row["n"] for row in metrics["fundamental_diagram"]["bins"])
    assert binned_frames == sampled["frame"].nunique()
    pd.testing.assert_frame_equal(sampled, shuffled)
    assert metadata == shuffled_metadata


def test_sampling_never_stitches_sparse_source_frames() -> None:
    source = _many_frames()
    source["frame"] = source["frame"] * 1000
    source["t_s"] = source["frame"].astype("float64") / 10.0
    assert validate(source) == []
    sampled, metadata = sample_complete_frame_windows(
        source,
        max_rows=40,
        window_count=2,
        frame_rate_hz=10.0,
    )
    assert metadata["source_continuity_verified"] is True
    assert sampled.groupby("agent_id").size().max() == 1


def test_full_sampling_rejects_frame_times_that_disagree_with_trusted_rate() -> None:
    source = _many_frames()
    source["t_s"] = source["frame"].astype("float64") * 0.4
    with pytest.raises(ValueError, match="not contiguous at the trusted rate"):
        sample_complete_frame_windows(
            source,
            max_rows=len(source),
            window_count=5,
            frame_rate_hz=10.0,
        )
