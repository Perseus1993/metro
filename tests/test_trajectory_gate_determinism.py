from __future__ import annotations

from copy import deepcopy
import json

from metro_station_acceptance.blind_trajectory_gate import analyze_blind_trajectory
from metro_station_acceptance.composite_trajectory_gate import (
    analyze_composite_trajectory,
)
from metro_station_acceptance.trajectory_kinematics_gate import (
    analyze_trajectory_kinematics,
)
from metro_station_acceptance.trajectory_truth_gate import analyze_trajectory_truth


def _authoritative_payload() -> dict[str, object]:
    points = [
        {
            "passenger_id": 1,
            "time_seconds": sample_index * 0.2,
            "x": sample_index * 0.2,
            "y": 0.0,
            "level_id": "b1",
            "episode_id": "1:1",
            "sample_index": sample_index,
            "authority": "jupedsim_committed_walk",
            "phase": "walking",
        }
        for sample_index in range(21)
    ]
    snapshots = [
        {
            "time_seconds": sample_index * 0.2,
            "passengers": [
                {
                    "id": 1,
                    "x": sample_index * 0.2,
                    "y": 0.0,
                    "state": "walking_to_platform",
                }
            ],
        }
        for sample_index in range(0, 21, 5)
    ]
    return {
        "simulation_trace": {
            "snapshots": snapshots,
            "facility_events": [],
            "movement_trace": {
                "schema_version": "movement_trace.v1",
                "metadata": {
                    "authority": "jupedsim_committed_walk",
                    "coverage": ["walking"],
                    "coordinates": "station_model_meters",
                    "sample_interval_seconds": 0.2,
                    "integration_dt_seconds": 0.01,
                    "visual_only": False,
                },
                "points": points,
            },
        }
    }


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_all_scientific_trajectory_gates_are_report_deterministic() -> None:
    payload = _authoritative_payload()
    original = deepcopy(payload)
    blind_points = [
        {
            "id": "anonymous-1",
            "t": sample_index * 0.2,
            "x": sample_index * 0.2,
            "y": 0.0,
            "level_id": "anonymous-level-1",
        }
        for sample_index in range(21)
    ]
    analyzers = (
        (analyze_trajectory_truth, payload),
        (analyze_trajectory_kinematics, payload),
        (analyze_composite_trajectory, payload),
        (analyze_blind_trajectory, blind_points),
    )

    for analyzer, gate_input in analyzers:
        first = analyzer(deepcopy(gate_input))
        second = analyzer(deepcopy(gate_input))
        assert _canonical(first) == _canonical(second)

    assert payload == original
