from __future__ import annotations

from math import isclose, isfinite
from typing import Any

from metro_alignment.metrics.fundamental import (
    WALKING_SPEED_PROXY_KEY,
    MetricConfig,
    compute_metric_bundle,
)
from metro_alignment.metro_trace import TraceConversionResult
from metro_alignment.scenes import SceneConfig


def compute_simulated_metrics(
    conversion: TraceConversionResult,
    *,
    config: SceneConfig,
) -> dict[str, Any]:
    sample_interval = conversion.provenance.get("sample_interval_seconds")
    if (
        not isinstance(sample_interval, (int, float))
        or isinstance(sample_interval, bool)
        or not isfinite(sample_interval)
        or not isclose(
            float(sample_interval),
            float(config.movement_trace_sample_seconds),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError(
            "movement trace sample interval differs from the trusted SceneConfig"
        )
    analysis_end_s = float(config.demand_minutes * 60)
    canonical = conversion.trajectory.loc[
        conversion.trajectory["t_s"] <= analysis_end_s + 1e-12
    ].copy()
    if canonical.empty:
        raise ValueError("simulation trace has no points in the declared demand window")
    computation = compute_metric_bundle(
        canonical,
        config=MetricConfig(
            frame_rate_hz=1.0 / float(config.movement_trace_sample_seconds),
            measurement_bounds_m=config.measurement_bounds_m,
            measurement_area_id=config.measurement_area_id,
            comparison_frame_id=config.comparison_frame_id,
            coordinate_transform_id=config.coordinate_transform_id,
            coordinate_translation_m=config.coordinate_translation_m,
        ),
    )
    metrics = computation.table
    metrics["analysis_window"] = {
        "start_s": 0.0,
        "end_s": analysis_end_s,
        "basis": "scene_config.demand_minutes",
        "clearance_tail_excluded": config.minutes > config.demand_minutes,
    }
    contributor_agents = {
        WALKING_SPEED_PROXY_KEY: computation.contributors.walking_proxy_agent_ids,
        "fundamental_diagram": computation.contributors.fundamental_agent_ids,
    }
    for metric_key, agent_ids in contributor_agents.items():
        identities = [conversion.identity_by_agent[agent_id] for agent_id in agent_ids]
        support = metrics["metric_support"][metric_key]
        episode_n = int(support.pop("agent_n"))
        support.update(
            {
                "episode_n": episode_n,
                "passenger_n": len({passenger for passenger, _ in identities}),
                "seed_n": 1,
                "seed_values": [int(config.seed)],
                "unit": "correlated_simulated_metric_contributors",
            }
        )
    return metrics


def simulated_trajectory_summary(conversion: TraceConversionResult) -> dict[str, Any]:
    canonical = conversion.trajectory
    return {
        "point_count": len(canonical),
        "agent_count": int(canonical["agent_id"].nunique()),
        "duration_s": float(canonical["t_s"].max() - canonical["t_s"].min()),
    }
