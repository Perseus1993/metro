from __future__ import annotations

from metro_cloud_api.soak import run_soak


def test_two_job_fake_soak_passes() -> None:
    report = run_soak(
        jobs=2,
        agents=1,
        runner_kind="fake",
        horizon_minutes=1,
        demand_minutes=1,
        timeout_seconds=30,
    )
    assert report["passed"]
    assert report["completed_jobs"] == 2
    assert all(item["artifact_count"] == 6 for item in report["records"])
    assert all(item["private_result_removed"] for item in report["records"])
