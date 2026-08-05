from __future__ import annotations

import json

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
