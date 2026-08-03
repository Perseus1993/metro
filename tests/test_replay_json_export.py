from __future__ import annotations

import json

from metro_station.adapters.simulation.simulation_outputs import (
    unity_replay_payload,
    write_replay_payload_json,
    write_unity_replay_payload_json,
)


def test_plain_json_replay_export_has_no_browser_wrapper(tmp_path) -> None:
    payload = {
        "schema_version": "visualization_bundle.v1",
        "simulation_trace": {"schema_version": "simulation_trace.v1"},
        "visualization_bundle": {"schema_version": "visualization_bundle.v1"},
        "replay_package": {
            "schema_version": "replay_package.v2",
            "simulation_trace_ref": "#/simulation_trace",
            "visualization_bundle_ref": "#/visualization_bundle",
        },
    }
    output_path = tmp_path / "two_level_station.replay.json"

    written_path = write_replay_payload_json(payload=payload, output_path=output_path)

    assert written_path == output_path
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
    assert not output_path.read_text(encoding="utf-8").startswith("window.JPS_TRACKS")


def test_unity_replay_export_excludes_presentation_only_tracks(tmp_path) -> None:
    payload = {
        "schema_version": "visualization_bundle.v1",
        "source_run_id": "run-42",
        "simulation_trace": {
            "schema_version": "simulation_trace.v1",
            "snapshots": [],
            "facility_events": [],
        },
        "visualization_bundle": {"visual_tracks": [{"id": 1, "points": []}]},
        "replay_package": {
            "schema_version": "replay_package.v2",
            "station_scene": {"schema_version": "station_scene.v1"},
        },
        "clearance_audit": {"cleared": True},
        "agents": [{"id": 1, "points": []}],
    }
    output_path = tmp_path / "truth.replay.json"

    compact = unity_replay_payload(payload)
    write_unity_replay_payload_json(payload=payload, output_path=output_path)

    assert set(compact) == {
        "schema_version",
        "source_run_id",
        "simulation_trace",
        "replay_package",
        "clearance_audit",
    }
    assert "visualization_bundle" not in compact
    assert "agents" not in compact
    assert json.loads(output_path.read_text(encoding="utf-8")) == compact
