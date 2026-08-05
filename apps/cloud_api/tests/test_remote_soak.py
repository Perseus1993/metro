from __future__ import annotations

import subprocess
import sys

from metro_cloud_api.local_e2e import (
    _server_environment,
    _settings,
    _stop,
    _unused_port,
    _wait_for_health,
)
from metro_cloud_api.remote_soak import run_remote_soak
from metro_cloud_api.worker import Worker


def test_remote_soak_uses_running_api_and_worker(tmp_path) -> None:
    port = _unused_port()
    settings = _settings(tmp_path, "fake", 1)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "metro_cloud_api.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=_server_environment(settings),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_health(port, server)
        worker = Worker(settings)

        def run_worker_once() -> None:
            worker.run_once()

        report = run_remote_soak(
            base_url=f"http://127.0.0.1:{port}",
            token=None,
            jobs=2,
            agents=1,
            horizon_minutes=1,
            demand_minutes=1,
            timeout_seconds=30,
            after_submit=run_worker_once,
        )
    finally:
        _stop(server)

    assert report["passed"]
    assert report["completed_jobs"] == 2
    assert all(record["checks"]["six_public_artifacts"] for record in report["records"])
