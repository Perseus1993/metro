from __future__ import annotations

from metro_station_acceptance.trajectory_acceptance import run_trajectory_acceptance


def _source_point(
    time_s: float,
    *,
    authority: str = "simulation_trace.snapshots",
) -> list[object]:
    return [
        time_s,
        time_s,
        0.0,
        0.0,
        1.0,
        None,
        None,
        "walk",
        "",
        {
            "source": "simulation",
            "visual_only": False,
            "authority": authority,
            "coordinate_transform": "station_meters_to_canvas_pixels.v1",
        },
    ]


def test_four_gates_keep_explicit_evidence_boundaries() -> None:
    snapshots = [
        {
            "time_seconds": time_s,
            "passengers": [
                {
                    "id": 1,
                    "x": time_s,
                    "y": 0.0,
                    "state": "walking_to_platform",
                }
            ],
        }
        for time_s in (0.0, 1.0)
    ]
    movement_points = [
        {
            "passenger_id": 1,
            "time_seconds": index * 0.2,
            "x": index * 0.2,
            "y": 0.0,
            "level_id": "b1",
            "authority": "jupedsim",
            "phase": "walking",
            "episode_id": "1:1",
            "sample_index": index,
        }
        for index in range(5)
    ]
    movement_trace = {
        "schema_version": "movement_trace.v1",
        "metadata": {
            "authority": "jupedsim",
            "coverage": ["walking"],
            "sample_interval_seconds": 0.2,
            "integration_dt_seconds": 0.01,
            "visual_only": False,
        },
        "points": movement_points,
    }
    scientific = {
        "simulation_trace": {
            "metadata": {},
            "snapshots": snapshots,
            "movement_trace": movement_trace,
        }
    }
    full_bundle = {
        "simulation_trace": {
            "metadata": {
                "replay_fidelity": {
                    "position_authority": "simulation_trace.snapshots",
                    "walking_position_authority": "simulation_trace.movement_trace",
                    "visual_tracks_authoritative": False,
                    "visual_track_source_points_field": "points",
                    "visual_track_presentation_points_field": "presentation_points",
                    "facility_overlays_modify_source_points": False,
                    "renderer_track_field": "points",
                    "visual_track_coordinate_transform": {
                        "id": "station_meters_to_canvas_pixels.v1",
                        "source_coordinates": "station_model_meters",
                        "target_coordinates": "animation_canvas_pixels",
                        "source_width_m": 1.0,
                        "source_height_m": 1.0,
                        "canvas_width_px": 1.0,
                        "canvas_height_px": 1.0,
                        "clamp_to_canvas": True,
                        "round_output_decimals": 2,
                    },
                }
            },
            "snapshots": snapshots,
            "movement_trace": movement_trace,
        },
        "replay_package": {"metadata": {"visual_tracks_policy": "presentation_only"}},
        "agents": [
            {
                "id": 1,
                "points": [
                    *[
                        _source_point(
                            index * 0.2,
                            authority="simulation_trace.movement_trace",
                        )
                        for index in range(5)
                    ],
                    _source_point(1.0),
                ],
            }
        ],
    }

    report = run_trajectory_acceptance(
        scientific_payload=scientific,
        presentation_payload=full_bundle,
    )

    assert report["passed"]
    assert not report["evidence_boundaries"]["presentation_data_used_for_scientific_checks"]
    assert set(report["reports"]) == {
        "simulation_truth",
        "walking_kinematics",
        "all_state_composite_trajectory",
        "presentation_fidelity",
    }
