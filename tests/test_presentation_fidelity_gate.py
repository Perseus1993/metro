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
    return {
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
            "snapshots": [
                {
                    "time_seconds": time_s,
                    "passengers": [{"id": 1, "x": time_s, "y": 0.0}],
                }
                for time_s in (0.0, 1.0)
            ],
        },
        "replay_package": {"metadata": {"visual_tracks_policy": "presentation_only"}},
        "agents": [
            {
                "id": 1,
                "points": [_point(0.0), _point(1.0)],
                "presentation_points": [_point(0.0), _point(0.5, visual_only=True), _point(1.0)],
            }
        ],
    }


def test_isolated_presentation_layer_passes() -> None:
    report = analyze_presentation_fidelity(_payload())

    assert report["passed"]
    assert report["source"]["visual_only_presentation_point_count"] == 1
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


def test_presentation_only_coordinate_mutation_does_not_change_truth_verdict() -> None:
    payload = _payload()
    payload["agents"][0]["presentation_points"][1][1] = 0.75

    report = analyze_presentation_fidelity(payload)

    assert report["passed"]


def test_contract_cannot_claim_visual_authority() -> None:
    payload = deepcopy(_payload())
    payload["simulation_trace"]["metadata"]["replay_fidelity"][
        "visual_tracks_authoritative"
    ] = True

    report = analyze_presentation_fidelity(payload)

    assert report["checks"]["authority_contract_is_explicit"]["status"] == "fail"
