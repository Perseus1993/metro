from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq

from metro_cloud_api.artifact_contract import validate_runner_artifacts
from metro_cloud_api.runners.fake import FakeRunner


def test_capacity_output_validation_accepts_contract_artifacts(tmp_path) -> None:
    spec = {
        "scenario_mode": "operations", "horizon_minutes": 1, "demand_minutes": 1,
        "entry_count_hour": 60, "exit_count_hour": 0, "transfer_count_hour": 0,
        "initial_platform_persons": 0, "group_size": 1, "admins": 0,
        "seed": 42, "trajectory_sample_seconds": 1,
    }
    FakeRunner().run(spec, tmp_path, lambda *_: None)
    result = json.loads((tmp_path / "_result.json").read_text("utf-8"))
    assert result["passenger_agent_count"] == 1
    assert validate_runner_artifacts(tmp_path) == {"valid": True, "errors": []}


def test_capacity_validation_rejects_bad_event_namespace(tmp_path) -> None:
    spec = {
        "scenario_mode": "operations", "horizon_minutes": 1, "demand_minutes": 1,
        "entry_count_hour": 60, "exit_count_hour": 0, "transfer_count_hour": 0,
        "initial_platform_persons": 0, "group_size": 1, "admins": 0,
        "seed": 42, "trajectory_sample_seconds": 1,
    }
    FakeRunner().run(spec, tmp_path, lambda *_: None)
    events = pq.read_table(tmp_path / "events.parquet")
    bad_ids = pa.array(["bad"] * events.num_rows, type=pa.string())
    event_id_index = events.schema.get_field_index("event_id")
    events = events.set_column(event_id_index, events.schema.field(event_id_index), bad_ids)
    pq.write_table(events, tmp_path / "events.parquet")

    contract = validate_runner_artifacts(tmp_path)
    assert not contract["valid"]
    assert "event id namespace mismatch" in contract["errors"]


def test_capacity_validation_rejects_missing_result_key(tmp_path) -> None:
    spec = {
        "scenario_mode": "operations", "horizon_minutes": 1, "demand_minutes": 1,
        "entry_count_hour": 60, "exit_count_hour": 0, "transfer_count_hour": 0,
        "initial_platform_persons": 0, "group_size": 1, "admins": 0,
        "seed": 42, "trajectory_sample_seconds": 1,
    }
    FakeRunner().run(spec, tmp_path, lambda *_: None)
    path = tmp_path / "_result.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result.pop("person_count")
    path.write_text(json.dumps(result), encoding="utf-8")

    contract = validate_runner_artifacts(tmp_path)
    assert not contract["valid"]
    assert any(error.startswith("result keys missing") for error in contract["errors"])
