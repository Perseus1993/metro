from __future__ import annotations

from copy import deepcopy

from metro_station_acceptance.composite_trajectory_gate import (
    CompositeTrajectoryGateConfig,
    analyze_composite_trajectory,
)


def _payload(*, agent_count: int = 1) -> dict[str, object]:
    snapshots = []
    movement_points = []
    for sample_index in range(21):
        time_s = sample_index * 0.2
        if sample_index % 5 == 0:
            snapshots.append(
                {
                    "time_seconds": time_s,
                    "passengers": [
                        {
                            "id": agent_id,
                            "x": sample_index * 0.2 + agent_id * 0.01,
                            "y": agent_id * 0.2,
                            "state": "walking_to_platform",
                        }
                        for agent_id in range(1, agent_count + 1)
                    ],
                }
            )
        for agent_id in range(1, agent_count + 1):
            movement_points.append(
                {
                    "passenger_id": agent_id,
                    "time_seconds": time_s,
                    "x": sample_index * 0.2 + agent_id * 0.01,
                    "y": agent_id * 0.2,
                    "episode_id": f"{agent_id}:1",
                    "sample_index": sample_index,
                }
            )
    return {
        "simulation_trace": {
            "snapshots": snapshots,
            "movement_trace": {"points": movement_points},
        }
    }


def test_composite_gate_accepts_continuous_all_state_trace() -> None:
    report = analyze_composite_trajectory(_payload())

    assert report["passed"]
    assert report["source"]["presentation_samples_accepted"] == 0


def test_same_time_snapshot_and_movement_disagreement_is_hard_failure() -> None:
    payload = _payload()
    payload["simulation_trace"]["movement_trace"]["points"][5]["x"] += 0.5

    report = analyze_composite_trajectory(payload)

    check = report["checks"]["authority_boundaries_are_position_continuous"]
    assert check["status"] == "fail"
    assert check["examples"][0]["reason"] == "same_time_authorities_disagree"


def test_high_speed_aba_return_and_hard_reversal_are_rejected() -> None:
    payload = _payload()
    points = payload["simulation_trace"]["movement_trace"]["points"]
    points[5]["x"] = points[4]["x"] + 0.4
    points[6]["x"] = points[4]["x"]
    payload["simulation_trace"]["snapshots"][1]["passengers"][0]["x"] = points[5]["x"]

    report = analyze_composite_trajectory(payload)

    assert report["checks"]["no_hard_high_speed_reversal"]["status"] == "fail"
    assert report["checks"]["no_high_speed_aba_return"]["status"] == "fail"


def test_short_avoidance_sidestep_with_forward_progress_is_not_an_aba_return() -> None:
    payload = _payload()
    points = payload["simulation_trace"]["movement_trace"]["points"]
    points[4]["x"], points[4]["y"] = 0.0, 0.0
    points[5]["x"], points[5]["y"] = 0.027, -0.126
    points[6]["x"], points[6]["y"] = 0.069, -0.003
    payload["simulation_trace"]["snapshots"][1]["passengers"][0]["x"] = points[5]["x"]
    payload["simulation_trace"]["snapshots"][1]["passengers"][0]["y"] = points[5]["y"]

    report = analyze_composite_trajectory(payload)

    assert report["checks"]["no_high_speed_aba_return"]["status"] == "pass"


def test_exact_copied_moving_path_between_agents_is_rejected() -> None:
    payload = _payload(agent_count=2)
    points = payload["simulation_trace"]["movement_trace"]["points"]
    by_time = {}
    for point in points:
        by_time.setdefault(point["time_seconds"], {})[point["passenger_id"]] = point
    for pair in by_time.values():
        pair[2]["x"] = pair[1]["x"]
        pair[2]["y"] = pair[1]["y"]
    for snapshot in payload["simulation_trace"]["snapshots"]:
        snapshot["passengers"][1]["x"] = snapshot["passengers"][0]["x"]
        snapshot["passengers"][1]["y"] = snapshot["passengers"][0]["y"]

    report = analyze_composite_trajectory(payload)

    assert report["checks"]["no_exact_copied_multi_point_paths"]["status"] == "fail"


def test_duplicate_detector_does_not_reject_parallel_translated_paths() -> None:
    payload = deepcopy(_payload(agent_count=2))
    report = analyze_composite_trajectory(
        payload,
        config=CompositeTrajectoryGateConfig(duplicate_window_points=10),
    )

    assert report["checks"]["no_exact_copied_multi_point_paths"]["status"] == "pass"


def test_duplicate_detector_allows_same_facility_centerline_at_different_times() -> None:
    payload = deepcopy(_payload(agent_count=2))
    points = payload["simulation_trace"]["movement_trace"]["points"]
    first_path = [
        (point["x"], point["y"])
        for point in points
        if point["passenger_id"] == 1
    ]
    for index, point in enumerate(
        point for point in points if point["passenger_id"] == 2
    ):
        source_index = max(0, index - 2)
        point["x"], point["y"] = first_path[source_index]

    report = analyze_composite_trajectory(
        payload,
        config=CompositeTrajectoryGateConfig(duplicate_window_points=10),
    )

    assert report["checks"]["no_exact_copied_multi_point_paths"]["status"] == "pass"
