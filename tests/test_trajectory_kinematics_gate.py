from __future__ import annotations

import math

import pytest

from metro_station_acceptance.trajectory_kinematics_gate import (
    TrajectoryKinematicsGateConfig,
    analyze_trajectory_kinematics,
)
from metro_station_acceptance.trajectory_truth_inputs import TrajectoryTruthInputError


def _trace(points: list[dict[str, object]], *, interval: float = 0.2) -> dict[str, object]:
    return {
        "schema_version": "movement_trace.v1",
        "metadata": {
            "authority": "jupedsim",
            "coverage": ["walking"],
            "coordinates": "station_model_meters",
            "sample_interval_seconds": interval,
            "integration_dt_seconds": 0.01,
            "visual_only": False,
        },
        "points": points,
    }


def _point(
    agent_id: int,
    time_s: float,
    x: float,
    y: float,
    *,
    episode: int = 1,
    sample_index: int | None = None,
) -> dict[str, object]:
    return {
        "passenger_id": agent_id,
        "time_seconds": time_s,
        "x": x,
        "y": y,
        "level_id": "b1",
        "episode_id": f"{agent_id}:{episode}",
        "sample_index": (
            round(time_s / 0.2) if sample_index is None else sample_index
        ),
        "authority": "jupedsim",
        "phase": "walking",
    }


def test_constant_realistic_motion_passes_fine_gate() -> None:
    payload = _trace([_point(1, index * 0.2, index * 0.2, 0.0) for index in range(8)])

    report = analyze_trajectory_kinematics(payload)

    assert report["passed"]
    assert report["observations"]["speed_p99_m_s"] == pytest.approx(1.0)
    assert report["observations"]["acceleration_p99_m_s2"] == pytest.approx(0.0)
    assert report["trace_contract"]["acceleration_window_s"] == pytest.approx(0.4)


def test_production_committed_jupedsim_authority_is_accepted() -> None:
    payload = _trace(
        [_point(1, index * 0.2, index * 0.2, 0.0) for index in range(8)]
    )
    payload["metadata"]["authority"] = "jupedsim_committed_walk"
    for point in payload["points"]:
        point["authority"] = "jupedsim_committed_walk"

    assert analyze_trajectory_kinematics(payload)["passed"]


def test_coarse_declared_sampling_is_a_hard_failure() -> None:
    payload = _trace(
        [_point(1, index * 0.5, index * 0.5, 0.0) for index in range(5)],
        interval=0.5,
    )

    report = analyze_trajectory_kinematics(payload)

    assert report["checks"]["high_rate_sampling"]["status"] == "fail"


def test_speed_and_acceleration_percentiles_are_gated() -> None:
    payload = _trace(
        [
            _point(1, 0.0, 0.0, 0.0),
            _point(1, 0.2, 0.0, 0.0),
            _point(1, 0.4, 0.6, 0.0),
            _point(1, 0.6, 1.2, 0.0),
        ]
    )

    report = analyze_trajectory_kinematics(payload)

    assert report["checks"]["speed_p99_within_bound"]["status"] == "fail"
    assert report["checks"]["acceleration_p99_within_bound"]["status"] == "fail"


def test_large_turn_fraction_excludes_stationary_vectors() -> None:
    payload = _trace(
        [
            _point(1, 0.0, 0.0, 0.0),
            _point(1, 0.2, 0.2, 0.0),
            _point(1, 0.4, 0.0, 0.0),
            _point(2, 0.0, 0.0, 0.0),
            _point(2, 0.2, 0.0, 0.0),
            _point(2, 0.4, 0.2, 0.0),
        ]
    )

    report = analyze_trajectory_kinematics(payload)

    assert report["observations"]["moving_turn_sample_count"] == 1
    assert report["observations"]["large_moving_turn_fraction"] == pytest.approx(1.0)
    assert report["checks"]["large_moving_turn_fraction_within_bound"]["status"] == "fail"


def test_facility_evidenced_episode_gap_is_not_turned_into_a_teleport_segment() -> None:
    movement = _trace(
        [
            _point(1, 0.0, 0.0, 0.0, sample_index=0),
            _point(1, 0.2, 0.2, 0.0, sample_index=1),
            _point(1, 0.4, 0.4, 0.0, sample_index=2),
            _point(1, 0.6, 0.6, 0.0, sample_index=3),
            _point(1, 10.0, 100.0, 0.0, episode=2, sample_index=0),
            _point(1, 10.2, 100.2, 0.0, episode=2, sample_index=1),
            _point(1, 10.4, 100.4, 0.0, episode=2, sample_index=2),
            _point(1, 10.6, 100.6, 0.0, episode=2, sample_index=3),
        ]
    )
    payload = {
        "simulation_trace": {
            "movement_trace": movement,
            "facility_events": [
                {
                    "passenger_ids": [1],
                    "start_time": 0.6,
                    "end_time": 10.0,
                }
            ],
            "snapshots": [],
        }
    }

    report = analyze_trajectory_kinematics(payload)

    assert report["passed"]
    assert report["trace_contract"]["discontinuity_count"] == 1
    assert report["observations"]["speed_max_m_s"] == pytest.approx(1.0)


def test_deleted_point_inside_episode_is_a_hard_failure() -> None:
    points = [_point(1, index * 0.2, index * 0.2, 0.0) for index in range(8)]
    points.pop(3)

    report = analyze_trajectory_kinematics(_trace(points))

    assert report["checks"]["walking_episodes_are_contiguous"]["status"] == "fail"


def test_unexplained_episode_gap_is_a_hard_failure() -> None:
    payload = _trace(
        [
            _point(1, 0.0, 0.0, 0.0, sample_index=0),
            _point(1, 0.2, 0.2, 0.0, sample_index=1),
            _point(1, 1.0, 1.0, 0.0, episode=2, sample_index=0),
            _point(1, 1.2, 1.2, 0.0, episode=2, sample_index=1),
        ]
    )

    report = analyze_trajectory_kinematics(payload)

    assert report["checks"]["episode_gaps_have_simulation_evidence"]["status"] == "fail"


def test_back_to_back_episode_boundary_needs_no_gap_evidence() -> None:
    payload = _trace(
        [
            _point(1, 0.0, 0.0, 0.0, sample_index=0),
            _point(1, 0.2, 0.2, 0.0, sample_index=1),
            _point(1, 0.2, 0.2, 0.0, episode=2, sample_index=0),
            _point(1, 0.4, 0.4, 0.0, episode=2, sample_index=1),
        ]
    )

    report = analyze_trajectory_kinematics(payload)

    assert report["checks"]["episode_gaps_have_simulation_evidence"]["status"] == "pass"


def test_one_cadence_cross_episode_teleport_still_needs_gap_evidence() -> None:
    payload = _trace(
        [
            _point(1, 0.0, 0.0, 0.0, sample_index=0),
            _point(1, 0.2, 0.2, 0.0, sample_index=1),
            _point(1, 0.4, 5.0, 0.0, episode=2, sample_index=0),
            _point(1, 0.6, 5.2, 0.0, episode=2, sample_index=1),
        ]
    )

    report = analyze_trajectory_kinematics(payload)

    assert report["checks"]["episode_gaps_have_simulation_evidence"]["status"] == "fail"


def test_queue_capture_snapshot_explains_walking_episode_gap() -> None:
    movement = _trace(
        [
            _point(1, 0.0, 0.0, 0.0, sample_index=0),
            _point(1, 0.2, 0.2, 0.0, sample_index=1),
            _point(1, 1.0, 0.2, 0.0, episode=2, sample_index=0),
            _point(1, 1.2, 0.4, 0.0, episode=2, sample_index=1),
        ]
    )
    payload = {
        "simulation_trace": {
            "movement_trace": movement,
            "facility_events": [],
            "snapshots": [
                {
                    "time_seconds": 0.6,
                    "passengers": [
                        {
                            "id": 1,
                            "state": "walking_to_vertical",
                            "goal_graph": {
                                "state": {"interaction_state": "capture_queue"}
                            },
                        }
                    ],
                }
            ],
        }
    }

    report = analyze_trajectory_kinematics(payload)

    assert report["checks"]["episode_gaps_have_simulation_evidence"]["status"] == "pass"


def test_queue_approach_snapshot_does_not_explain_walking_episode_gap() -> None:
    movement = _trace(
        [
            _point(1, 0.0, 0.0, 0.0, sample_index=0),
            _point(1, 0.2, 0.2, 0.0, sample_index=1),
            _point(1, 1.0, 1.0, 0.0, episode=2, sample_index=0),
            _point(1, 1.2, 1.2, 0.0, episode=2, sample_index=1),
        ]
    )
    payload = {
        "simulation_trace": {
            "movement_trace": movement,
            "facility_events": [],
            "snapshots": [
                {
                    "time_seconds": 0.6,
                    "passengers": [
                        {
                            "id": 1,
                            "state": "walking_to_vertical",
                            "goal_graph": {
                                "state": {"interaction_state": "approach_queue"}
                            },
                        }
                    ],
                }
            ],
        }
    }

    report = analyze_trajectory_kinematics(payload)

    assert report["checks"]["episode_gaps_have_simulation_evidence"]["status"] == "fail"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["metadata"].update(visual_only=True),
        lambda payload: payload["metadata"].update(authority="presentation"),
        lambda payload: payload["points"][0].update(visual_only=True),
    ],
)
def test_presentation_or_non_authoritative_samples_are_rejected(mutation) -> None:
    payload = _trace([_point(1, 0.0, 0.0, 0.0), _point(1, 0.2, 0.2, 0.0)])
    mutation(payload)

    with pytest.raises(TrajectoryTruthInputError):
        analyze_trajectory_kinematics(payload)


def test_replay_nesting_is_supported() -> None:
    movement = _trace([_point(1, 0.0, 0.0, 0.0), _point(1, 0.2, 0.2, 0.0)])

    report = analyze_trajectory_kinematics(
        {"simulation_trace": {"movement_trace": movement}}
    )

    assert report["source"]["kind"] == "replay.simulation_trace.movement_trace"


def test_native_train_door_points_are_known_nonwalking_authority() -> None:
    train_door = _point(1, 0.1, 0.1, 0.0)
    train_door["phase"] = "train_door_boarding"
    payload = _trace(
        [
            _point(1, 0.0, 0.0, 0.0),
            train_door,
            _point(1, 0.2, 0.2, 0.0, sample_index=1),
        ]
    )

    report = analyze_trajectory_kinematics(payload)

    assert report["source"]["point_count"] == 2
    assert report["source"]["kind"] == "movement_trace"


def test_non_finite_points_are_rejected() -> None:
    payload = _trace([_point(1, 0.0, math.nan, 0.0)])

    with pytest.raises(TrajectoryTruthInputError, match="not finite"):
        analyze_trajectory_kinematics(payload)


def test_empty_derivative_series_fails_instead_of_claiming_evidence() -> None:
    payload = _trace([_point(1, 0.0, 0.0, 0.0)])

    report = analyze_trajectory_kinematics(
        payload,
        config=TrajectoryKinematicsGateConfig(),
    )

    assert not report["passed"]
    assert report["checks"]["speed_p99_within_bound"]["observed"] is None
