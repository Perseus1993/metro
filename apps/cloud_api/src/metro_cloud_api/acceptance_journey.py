from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from metro_cloud import Client


def run_submitted_journey(
    client: Client,
    *,
    runner: str,
    agents: int,
    horizon: int,
    demand: int,
    timeout_seconds: float,
    after_submit: Callable[[], None] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    job = client.submit(
        {"spec_version": "0.1", "horizon_minutes": horizon, "demand_minutes": demand,
         "entry_count_hour": round(agents * 60 / demand), "exit_count_hour": 0,
         "transfer_count_hour": 0, "trajectory_sample_seconds": 10}
    )
    if after_submit is not None:
        after_submit()
    job.wait(timeout=timeout_seconds, poll_seconds=0.05)
    trajectories = job.trajectories()
    events = job.events()
    summary = job.summary()
    artifact_list = job.artifacts()
    range_response = client._http.get(
        f"/v1/jobs/{job.id}/artifacts/trajectories.parquet",
        headers={"Range": "bytes=0-9"},
    )
    checks = {
        "job_succeeded": job.status == "succeeded",
        "summary_succeeded": summary["status"] == "succeeded",
        "runner_matches": summary["runner"]["kind"] == runner,
        "agent_count_matches": summary["result"]["passenger_agent_count"] == agents,
        "trajectory_rows_match": len(trajectories) == summary["result"]["trajectory_rows"],
        "event_rows_match": len(events) == summary["result"]["event_rows"],
        "six_public_artifacts": len(artifact_list) == 6,
        "all_artifacts_have_sha256": all(len(item["sha256"]) == 64 for item in artifact_list),
        "range_download": range_response.status_code == 206 and len(range_response.content) == 10,
    }
    return {
        "runner": runner,
        "agents": agents,
        "horizon_minutes": horizon,
        "demand_minutes": demand,
        "wall_seconds": round(time.monotonic() - started, 3),
        "checks": checks,
        "passed": all(checks.values()),
    }
