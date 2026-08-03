from __future__ import annotations

import json

import pytest

from metro_station_acceptance.blind_trajectory_export import (
    export_anonymized_xy_observations,
)


def test_export_contains_only_anonymized_xy_observations(tmp_path) -> None:
    source = tmp_path / "replay.json"
    target = tmp_path / "blind.json"
    source.write_text(
        json.dumps(
            {
                "simulation_trace": {
                    "schema_version": "simulation_trace.v1",
                    "snapshots": [
                        {
                            "time_seconds": 2.0,
                            "passengers": [
                                {"id": 91, "x": 1.0, "y": 2.0, "state": "walking"},
                                {"id": 15, "x": 3.0, "y": 4.0, "state": "queueing"},
                            ],
                        },
                        {
                            "time_seconds": 3.0,
                            "passengers": [
                                {
                                    "id": 91,
                                    "x": 1.5,
                                    "y": 2.5,
                                    "state": "walking_to_platform",
                                },
                            ],
                        },
                    ],
                    "movement_trace": {
                        "points": [
                            {
                                "passenger_id": 91,
                                "time_seconds": 2.2,
                                "x": 1.1,
                                "y": 2.1,
                            },
                            {
                                "passenger_id": 91,
                                "time_seconds": 3.0,
                                "x": 999.0,
                                "y": 999.0,
                            },
                        ]
                    },
                },
                "visualization_bundle": {"agents": [{"id": 91, "x": 999.0}]},
            }
        ),
        encoding="utf-8",
    )

    count = export_anonymized_xy_observations(source, target)
    observations = json.loads(target.read_text(encoding="utf-8"))

    assert count == 4
    assert observations == [
        {"id": "p0001", "t": 2.0, "x": 1.0, "y": 2.0},
        {"id": "p0002", "t": 2.0, "x": 3.0, "y": 4.0},
        {"id": "p0001", "t": 2.2, "x": 1.1, "y": 2.1},
        {"id": "p0001", "t": 3.0, "x": 999.0, "y": 999.0},
    ]
    assert all(set(item) == {"id", "t", "x", "y"} for item in observations)


def test_export_rejects_non_authoritative_input(tmp_path) -> None:
    source = tmp_path / "visual.json"
    source.write_text(json.dumps({"agents": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="simulation_trace.v1"):
        export_anonymized_xy_observations(source, tmp_path / "blind.json")
