from __future__ import annotations

import json

import pyarrow.parquet as pq

from metro_cloud_api.output_schema import EVENT_SCHEMA, TRAJECTORY_SCHEMA
from metro_cloud_api.runners.fake import FakeRunner


def test_fake_runner_contract_and_progress_boundary(tmp_path) -> None:
    spec = {
        "scenario_mode": "evacuation", "horizon_minutes": 1, "demand_minutes": 1,
        "entry_count_hour": 0, "exit_count_hour": 0, "transfer_count_hour": 0,
        "initial_platform_persons": 50, "group_size": 5, "admins": 2,
        "seed": 42, "trajectory_sample_seconds": 7,
    }
    progress = []
    FakeRunner().run(spec, tmp_path, lambda current, total: progress.append((current, total)))
    trajectories = pq.read_table(tmp_path / "trajectories.parquet")
    events = pq.read_table(tmp_path / "events.parquet")
    assert trajectories.schema == TRAJECTORY_SCHEMA
    assert events.schema == EVENT_SCHEMA
    assert progress[-1] == (60, 60)
    assert set(trajectories.column("intent").to_pylist()) == {"evacuate_station"}
    result = json.loads((tmp_path / "_result.json").read_text("utf-8"))
    assert result["passenger_agent_count"] == 10
    assert result["total_agent_count"] == 12
    assert result["person_count"] == 50
