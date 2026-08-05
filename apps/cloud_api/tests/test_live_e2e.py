from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import httpx

from metro_cloud import Client
from metro_cloud_api.worker import Worker


def test_live_http_sdk_worker_round_trip(settings, monkeypatch) -> None:
    port = _unused_port()
    env = os.environ.copy()
    env.update(
        METRO_DATA_DIR=str(settings.data_dir),
        METRO_DATABASE_PATH=str(settings.database_path),
        METRO_CATALOG_PATH=str(settings.catalog_path),
        METRO_RUNNER="fake",
        METRO_MAX_AGENTS="200",
    )
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "metro_cloud_api.api:app",
         "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_health(port, server)
        with Client(f"http://127.0.0.1:{port}", cache_dir=settings.data_dir / "cache") as client:
            job = client.submit(
                {"spec_version": "0.1", "horizon_minutes": 1, "demand_minutes": 1,
                 "entry_count_hour": 60, "exit_count_hour": 0,
                 "transfer_count_hour": 0, "trajectory_sample_seconds": 10}
            )
            for key, value in env.items():
                if key.startswith("METRO_"):
                    monkeypatch.setenv(key, value)
            assert Worker(type(settings).from_env()).run_once()
            job.wait(timeout=30, poll_seconds=0.05)
            assert job.status == "succeeded"
            assert list(job.trajectories().columns)[0] == "agent_id"
            response = client._http.get(
                f"/v1/jobs/{job.id}/artifacts/trajectories.parquet",
                headers={"Range": "bytes=0-9"},
            )
            assert response.status_code == 206
            assert len(response.content) == 10
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def _unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, server: subprocess.Popen[bytes]) -> None:
    for _ in range(100):
        if server.poll() is not None:
            raise RuntimeError("uvicorn exited before becoming ready")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.05)
    raise TimeoutError("uvicorn did not become ready")
