from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from metro_alignment.canonical import validate
from metro_alignment.metro_trace import movement_trace_to_canonical
from metro_alignment.scenes import build_scene_config
from metro_alignment.simulation_evidence import compute_simulated_metrics


def _trace() -> dict:
    return {
        "schema_version": "movement_trace.v1",
        "metadata": {
            "authority": "jupedsim_committed_walk",
            "coverage": ["walking", "passive_layout", "same_floor_facility"],
            "coordinates": "station_model_meters",
            "sample_interval_seconds": 0.2,
            "visual_only": False,
        },
        "points": [
            {
                "passenger_id": 7,
                "episode_id": "7:1",
                "time_seconds": 0.0,
                "x": 0.0,
                "y": 0.0,
                "phase": "walking",
                "authority": "jupedsim_committed_walk",
            },
            {
                "passenger_id": 7,
                "episode_id": "7:1",
                "time_seconds": 0.2,
                "x": 0.2,
                "y": 0.0,
                "phase": "walking",
                "authority": "jupedsim_committed_walk",
            },
            {
                "passenger_id": 7,
                "episode_id": "7:1",
                "time_seconds": 0.2,
                "x": 0.2,
                "y": 0.0,
                "phase": "walking",
                "authority": "jupedsim_committed_walk",
            },
            {
                "passenger_id": 7,
                "episode_id": "7:2",
                "time_seconds": 0.2,
                "x": 1.0,
                "y": 0.0,
                "phase": "walking",
                "authority": "jupedsim_committed_walk",
            },
            {
                "passenger_id": 7,
                "episode_id": "7:2",
                "time_seconds": 0.4,
                "x": 1.2,
                "y": 0.0,
                "phase": "walking",
                "authority": "jupedsim_committed_walk",
            },
            {
                "passenger_id": 7,
                "episode_id": "7:p",
                "time_seconds": 0.4,
                "x": 1.2,
                "y": 0.0,
                "phase": "passive_layout",
                "authority": "jupedsim_committed_walk",
            },
        ],
    }


def test_trace_adapter_preserves_episode_contract_and_wrapper_parity() -> None:
    direct = movement_trace_to_canonical(_trace(), dataset_id="simulation:test")
    wrapped = movement_trace_to_canonical(
        {"schema_version": "simulation_trace.v1", "movement_trace": _trace()},
        dataset_id="simulation:test",
    )
    pd.testing.assert_frame_equal(direct.trajectory, wrapped.trajectory)
    assert validate(direct.trajectory) == []
    assert direct.trajectory["agent_id"].min() >= 90_000_000
    assert direct.trajectory["agent_id"].nunique() == 2
    assert direct.provenance["excluded_phase_point_count"] == 1


def test_trace_adapter_rejects_conflicting_duplicates() -> None:
    trace = _trace()
    trace["points"][2]["x"] = 9.0
    with pytest.raises(ValueError, match="conflicting duplicate"):
        movement_trace_to_canonical(trace, dataset_id="simulation:test")


def test_trace_adapter_rejects_visual_or_wrong_schema() -> None:
    trace = _trace()
    trace["metadata"]["visual_only"] = True
    with pytest.raises(ValueError, match="visual_only"):
        movement_trace_to_canonical(trace, dataset_id="simulation:test")
    with pytest.raises(ValueError, match="expected movement_trace"):
        movement_trace_to_canonical({"schema_version": "unknown"}, dataset_id="simulation:test")


def test_trace_adapter_never_assumes_a_missing_phase_is_walking() -> None:
    trace = _trace()
    del trace["points"][0]["phase"]
    with pytest.raises(ValueError, match="declare phase explicitly"):
        movement_trace_to_canonical(trace, dataset_id="simulation:test")


def test_trace_adapter_rejects_off_grid_times_before_pedpy() -> None:
    trace = _trace()
    trace["points"][1]["time_seconds"] = 0.09
    with pytest.raises(ValueError, match="sampling grid"):
        movement_trace_to_canonical(trace, dataset_id="simulation:test")


def test_episode_agent_ids_are_stable_across_full_and_subset_replays() -> None:
    full = movement_trace_to_canonical(_trace(), dataset_id="simulation:test").trajectory
    trace = _trace()
    trace["points"] = [point for point in trace["points"] if point.get("episode_id") == "7:2"]
    subset = movement_trace_to_canonical(trace, dataset_id="simulation:test").trajectory
    full_id = full.loc[full["t_s"].eq(0.4), "agent_id"].iloc[0]
    assert subset["agent_id"].unique().tolist() == [full_id]


@pytest.mark.parametrize("passenger_id", [True, 1.9, "1"])
def test_trace_adapter_rejects_coerced_passenger_ids(passenger_id) -> None:
    trace = _trace()
    trace["points"][0]["passenger_id"] = passenger_id
    with pytest.raises(ValueError, match="passenger/episode identity"):
        movement_trace_to_canonical(trace, dataset_id="simulation:test")


def test_trace_adapter_rejects_non_string_episode_id() -> None:
    trace = _trace()
    trace["points"][0]["episode_id"] = None
    with pytest.raises(ValueError, match="passenger/episode identity"):
        movement_trace_to_canonical(trace, dataset_id="simulation:test")


def test_simulation_metrics_bind_trace_interval_to_scene_config() -> None:
    trace = _trace()
    trace["metadata"]["sample_interval_seconds"] = 0.4
    trace["points"] = [
        {**point, "time_seconds": float(index) * 0.4}
        for index, point in enumerate(trace["points"][:2])
    ]
    conversion = movement_trace_to_canonical(trace, dataset_id="simulation:test")
    with pytest.raises(ValueError, match="sample interval differs"):
        compute_simulated_metrics(conversion, config=build_scene_config("platform_boarding"))


def test_simulation_metrics_declare_demand_window_and_exclude_clearance_tail() -> None:
    conversion = movement_trace_to_canonical(_trace(), dataset_id="simulation:test")

    metrics = compute_simulated_metrics(
        conversion,
        config=replace(build_scene_config("platform_boarding"), minutes=14),
    )

    assert metrics["analysis_window"] == {
        "start_s": 0.0,
        "end_s": 600.0,
        "basis": "scene_config.demand_minutes",
        "clearance_tail_excluded": True,
    }
