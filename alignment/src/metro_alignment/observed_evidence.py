from __future__ import annotations

from typing import Any

import pandas as pd

from metro_alignment.datasets.registry import DatasetSpec
from metro_alignment.metrics.fundamental import (
    WALKING_SPEED_PROXY_KEY,
    MetricConfig,
    compute_metric_bundle,
)
from metro_alignment.sampling import sample_complete_frame_windows


def trusted_observed_metric_config(spec: DatasetSpec) -> MetricConfig:
    analysis = spec.observed_analysis
    if spec.status != "active" or analysis is None:
        raise ValueError(f"dataset {spec.dataset_id} has no active observed analysis contract")
    return MetricConfig(
        frame_rate_hz=spec.frame_rate_hz,
        measurement_bounds_m=analysis.measurement_bounds_m,
        measurement_area_id=analysis.measurement_area_id,
        comparison_frame_id=analysis.comparison_frame_id,
        coordinate_transform_id=analysis.coordinate_transform_id,
        coordinate_translation_m=analysis.coordinate_translation_m,
    )


def compute_observed_evidence(
    canonical: pd.DataFrame,
    *,
    spec: DatasetSpec,
) -> tuple[dict[str, Any], dict[str, Any]]:
    analysis = spec.observed_analysis
    if analysis is None:
        raise ValueError(f"dataset {spec.dataset_id} lacks observed analysis config")
    sampled, sampling = sample_complete_frame_windows(
        canonical,
        max_rows=analysis.max_rows,
        window_count=analysis.window_count,
        frame_rate_hz=spec.frame_rate_hz,
    )
    sampling = {
        **sampling,
        "requested_max_rows": analysis.max_rows,
        "requested_window_count": analysis.window_count,
    }
    computation = compute_metric_bundle(
        sampled,
        config=trusted_observed_metric_config(spec),
    )
    metrics = computation.table
    packed_windows = sampling.get("packed_window_frame_ranges", [])

    def contributing_window_count(frame_ids: tuple[int, ...]) -> int:
        frame_set = set(frame_ids)
        return sum(
            any(int(start) <= frame <= int(end) for frame in frame_set)
            for start, end in packed_windows
        )

    support_specs = {
        WALKING_SPEED_PROXY_KEY: computation.contributors.walking_proxy_frame_ids,
        "fundamental_diagram": computation.contributors.fundamental_frame_ids,
    }
    for metric_key, frame_ids in support_specs.items():
        metrics["metric_support"][metric_key].update(
            {
                "window_n": contributing_window_count(frame_ids),
                "source_canonical_row_n": len(canonical),
                "unit": "correlated_observed_metric_contributors",
            }
        )
    metadata = {
        "n": len(sampled),
        "agent_count": int(sampled["agent_id"].nunique()),
        "duration_s": float(sampled["t_s"].max() - sampled["t_s"].min()),
        "sampling": sampling,
    }
    return metrics, metadata
