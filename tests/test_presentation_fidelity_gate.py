from __future__ import annotations

from copy import deepcopy

from metro_station_acceptance.presentation_fidelity_gate import (
    analyze_presentation_fidelity,
)


def _point(time_s: float, *, visual_only: bool = False) -> list[object]:
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
            "source": "interpolation" if visual_only else "simulation",
            "visual_only": visual_only,
            **(
                {}
                if visual_only
                else {
                    "authority": "simulation_trace.snapshots",
                    "coordinate_transform": "station_meters_to_canvas_pixels.v1",
                }
            ),
        },
    ]


def _payload() -> dict[str, object]:
    payload = {
        "simulation_trace": {
            "metadata": {
                "replay_fidelity": {
                    "position_authority": "simulation_trace.snapshots",
                    "walking_position_authority": "simulation_trace.movement_trace",
                    "visual_tracks_authoritative": False,
                    "visual_track_source_points_field": "points",
                    "presentation_position_source": "canonical_composite_points",
                    "facility_overlays_modify_source_points": False,
                    "facility_overlays_control_passenger_bodies": False,
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
            "snapshots": [
                {
                    "time_seconds": time_s,
                    "passengers": [{"id": 1, "x": time_s, "y": 0.0}],
                }
                for time_s in (0.0, 1.0)
            ],
        },
        "replay_package": {
            "metadata": {"visual_tracks_policy": "authoritative_trace_projection"}
        },
        "agents": [
            {
                "id": 1,
                "points": [_point(0.0), _point(1.0)],
            }
        ],
    }
    payload["visualization_bundle"] = {"visual_tracks": payload["agents"]}
    return payload


def test_canonical_renderer_track_passes_without_second_position_stream() -> None:
    report = analyze_presentation_fidelity(_payload())

    assert report["passed"]
    assert report["source"]["visual_only_presentation_point_count"] == 0
    assert report["source"]["visual_points_used_as_truth"] == 0


def test_visual_only_source_point_fails() -> None:
    payload = _payload()
    payload["agents"][0]["points"][1] = _point(1.0, visual_only=True)

    report = analyze_presentation_fidelity(payload)

    assert report["checks"]["source_points_are_simulation_only"]["status"] == "fail"


def test_source_ledger_must_match_authoritative_snapshots() -> None:
    payload = _payload()
    payload["agents"][0]["points"].pop()

    report = analyze_presentation_fidelity(payload)

    assert (
        report["checks"]["source_point_ledger_matches_authoritative_trace"]["status"]
        == "fail"
    )


def test_source_coordinate_mutation_fails_even_when_id_and_time_match() -> None:
    payload = _payload()
    payload["agents"][0]["points"][1][1] = 0.75

    report = analyze_presentation_fidelity(payload)

    assert (
        report["checks"]["source_point_ledger_matches_authoritative_trace"]["status"]
        == "fail"
    )


def test_exact_duplicate_movement_sample_at_episode_boundary_is_one_ledger_point() -> None:
    payload = _payload()
    payload["simulation_trace"]["snapshots"][1]["passengers"][0]["state"] = (
        "walking_to_platform"
    )
    movement_point = {
        "passenger_id": 1,
        "time_seconds": 1.0,
        "x": 1.0,
        "y": 0.0,
    }
    payload["simulation_trace"]["movement_trace"] = {
        "points": [
            {**movement_point, "episode_id": "1:1", "sample_index": 20},
            {**movement_point, "episode_id": "1:2", "sample_index": 0},
        ]
    }
    payload["agents"][0]["points"][1][9]["authority"] = (
        "simulation_trace.movement_trace"
    )

    report = analyze_presentation_fidelity(payload)

    assert report["passed"]


def test_different_movement_positions_at_same_episode_boundary_fail_ledger() -> None:
    payload = _payload()
    payload["simulation_trace"]["snapshots"][1]["passengers"][0]["state"] = (
        "walking_to_platform"
    )
    payload["simulation_trace"]["movement_trace"] = {
        "points": [
            {"passenger_id": 1, "time_seconds": 1.0, "x": 1.0, "y": 0.0},
            {"passenger_id": 1, "time_seconds": 1.0, "x": 0.75, "y": 0.0},
        ]
    }
    payload["agents"][0]["points"][1][9]["authority"] = (
        "simulation_trace.movement_trace"
    )

    report = analyze_presentation_fidelity(payload)

    assert (
        report["checks"]["source_point_ledger_matches_authoritative_trace"]["status"]
        == "fail"
    )


def test_position_bearing_presentation_track_is_forbidden() -> None:
    payload = _payload()
    payload["agents"][0]["presentation_points"] = [
        _point(0.0),
        _point(0.5, visual_only=True),
        _point(1.0),
    ]

    report = analyze_presentation_fidelity(payload)

    assert report["checks"]["no_position_bearing_presentation_track"]["status"] == "fail"


def test_contract_cannot_claim_visual_authority() -> None:
    payload = deepcopy(_payload())
    payload["simulation_trace"]["metadata"]["replay_fidelity"][
        "visual_tracks_authoritative"
    ] = True

    report = analyze_presentation_fidelity(payload)

    assert report["checks"]["authority_contract_is_explicit"]["status"] == "fail"
