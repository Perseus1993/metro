from __future__ import annotations

from metro_cloud_api.local_e2e import run_local_e2e


def test_fake_local_e2e_acceptance_journey() -> None:
    report = run_local_e2e(runner="fake", agents=1, horizon=1, demand=1)
    assert report["passed"]
