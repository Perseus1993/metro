from __future__ import annotations

import json

import pytest

from metro_station_acceptance.blind_trajectory_export import (
    anonymized_xy_observations,
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
                        "metadata": {
                            "authority": "jupedsim_committed_walk",
                            "visual_only": False,
                        },
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

    assert count == 5
    assert observations == [
        {"id": "p0001", "t": 2.0, "x": 1.0, "y": 2.0},
        {"id": "p0002", "t": 2.0, "x": 3.0, "y": 4.0},
        {"id": "p0001", "t": 2.2, "x": 1.1, "y": 2.1},
        {"id": "p0001", "t": 3.0, "x": 1.5, "y": 2.5},
        {"id": "p0001", "t": 3.0, "x": 999.0, "y": 999.0},
    ]
    assert all(set(item) == {"id", "t", "x", "y"} for item in observations)


def test_export_rejects_non_authoritative_input(tmp_path) -> None:
    source = tmp_path / "visual.json"
    source.write_text(json.dumps({"agents": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="simulation_trace.v1"):
        export_anonymized_xy_observations(source, tmp_path / "blind.json")


def test_export_preserves_only_an_anonymous_level_token() -> None:
    observations = anonymized_xy_observations(
        {
            "simulation_trace": {
                "schema_version": "simulation_trace.v1",
                "snapshots": [
                    {
                        "time_seconds": 0.0,
                        "passengers": [
                            {
                                "id": 1,
                                "x": 3.0,
                                "y": 4.0,
                                "current_level_id": "secret-concourse-name",
                            },
                            {
                                "id": 2,
                                "x": 3.0,
                                "y": 4.0,
                                "current_level_id": "secret-platform-name",
                            },
                        ],
                    }
                ],
            }
        }
    )

    assert [item["level"] for item in observations] == ["l0001", "l0002"]
    assert "secret" not in json.dumps(observations)


@pytest.mark.parametrize(
    "movement_metadata, passenger_extra, message",
    [
        (
            {"authority": "presentation", "visual_only": False},
            {},
            "not JuPedSim truth",
        ),
        (
            {"authority": "jupedsim_committed_walk", "visual_only": False},
            {"visual_only": True},
            "visual_only",
        ),
    ],
)
def test_export_rejects_non_truth_authority(
    tmp_path,
    movement_metadata,
    passenger_extra,
    message,
) -> None:
    source = tmp_path / "spoofed.json"
    source.write_text(
        json.dumps(
            {
                "simulation_trace": {
                    "schema_version": "simulation_trace.v1",
                    "snapshots": [
                        {
                            "time_seconds": 0.0,
                            "passengers": [
                                {"id": 1, "x": 0.0, "y": 0.0, **passenger_extra}
                            ],
                        }
                    ],
                    "movement_trace": {
                        "metadata": movement_metadata,
                        "points": [
                            {
                                "passenger_id": 1,
                                "time_seconds": 0.2,
                                "x": 0.2,
                                "y": 0.0,
                            }
                        ],
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        export_anonymized_xy_observations(source, tmp_path / "blind.json")


def test_export_rejects_point_authority_spoof(tmp_path) -> None:
    source = tmp_path / "spoofed-point.json"
    source.write_text(
        json.dumps(
            {
                "simulation_trace": {
                    "schema_version": "simulation_trace.v1",
                    "snapshots": [],
                    "movement_trace": {
                        "metadata": {
                            "authority": "jupedsim_committed_walk",
                            "visual_only": False,
                        },
                        "points": [
                            {
                                "passenger_id": 1,
                                "time_seconds": 0.2,
                                "x": 0.2,
                                "y": 0.0,
                                "authority": "presentation",
                            }
                        ],
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="point authority.*not JuPedSim truth"):
        export_anonymized_xy_observations(source, tmp_path / "blind.json")


def test_export_includes_authoritative_facility_motion() -> None:
    observations = anonymized_xy_observations(
        {
            "simulation_trace": {
                "schema_version": "simulation_trace.v1",
                "snapshots": [],
                "facility_motion_trace": {
                    "schema_version": "facility_motion_trace.v1",
                    "metadata": {
                        "authority": "facility_process_model",
                        "visual_only": False,
                    },
                    "points": [
                        {
                            "passenger_id": 7,
                            "time_seconds": 1.2,
                            "x": 3.0,
                            "y": 4.0,
                            "level_id": "connector:secret-elevator",
                            "authority": "facility_process_model",
                            "visual_only": False,
                        }
                    ],
                },
            }
        }
    )

    assert observations == [
        {"id": "p0001", "t": 1.2, "x": 3.0, "y": 4.0, "level": "l0001"}
    ]


def test_export_reconciles_submillimetre_authority_handoff_copies() -> None:
    observations = anonymized_xy_observations(
        {
            "simulation_trace": {
                "schema_version": "simulation_trace.v1",
                "snapshots": [
                    {
                        "time_seconds": 5.0,
                        "passengers": [
                            {
                                "id": 7,
                                "x": 3.0004,
                                "y": 4.0003,
                                "physical_layer_id": "connector:lift",
                            }
                        ],
                    }
                ],
                "movement_trace": {
                    "metadata": {
                        "authority": "jupedsim_committed_walk",
                        "visual_only": False,
                    },
                    "points": [
                        {
                            "passenger_id": 7,
                            "time_seconds": 5.0,
                            "x": 3.0,
                            "y": 4.0,
                            "level_id": "platform",
                        }
                    ],
                },
                "facility_motion_trace": {
                    "metadata": {
                        "authority": "facility_process_model",
                        "visual_only": False,
                    },
                    "points": [
                        {
                            "passenger_id": 7,
                            "time_seconds": 5.0,
                            "x": 3.0002,
                            "y": 4.0001,
                            "level_id": "connector:lift",
                        }
                    ],
                },
            }
        }
    )

    assert observations == [
        {"id": "p0001", "t": 5.0, "x": 3.0, "y": 4.0, "level": "l0002"}
    ]


def test_export_rejects_visual_only_facility_motion() -> None:
    with pytest.raises(ValueError, match="visual_only facility_motion_trace"):
        anonymized_xy_observations(
            {
                "simulation_trace": {
                    "schema_version": "simulation_trace.v1",
                    "snapshots": [],
                    "facility_motion_trace": {
                        "schema_version": "facility_motion_trace.v1",
                        "metadata": {
                            "authority": "facility_process_model",
                            "visual_only": True,
                        },
                        "points": [
                            {
                                "passenger_id": 7,
                                "time_seconds": 1.2,
                                "x": 3.0,
                                "y": 4.0,
                            }
                        ],
                    },
                }
            }
        )
