from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from metro_cloud import Client

from .acceptance_journey import run_submitted_journey
from .config import Settings
from .worker import Worker


def run_local_e2e(*, runner: str, agents: int, horizon: int, demand: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="metro-cloud-e2e-") as folder:
        root = Path(folder)
        port = _unused_port()
        settings = _settings(root, runner, agents)
        env = _server_environment(settings)
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "metro_cloud_api.api:app",
             "--host", "127.0.0.1", "--port", str(port)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for_health(port, server)
            return _run_journey(settings, port, agents, horizon, demand)
        finally:
            _stop(server)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local API/SDK/worker acceptance journey")
    parser.add_argument("--runner", choices=("fake", "real"), default="real")
    parser.add_argument("--agents", type=int, default=50)
    parser.add_argument("--horizon-minutes", type=int, default=15)
    parser.add_argument("--demand-minutes", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_local_e2e(
        runner=args.runner,
        agents=args.agents,
        horizon=args.horizon_minutes,
        demand=args.demand_minutes,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not report["passed"]:
        raise SystemExit(1)


def _run_journey(
    settings: Settings, port: int, agents: int, horizon: int, demand: int
) -> dict[str, Any]:
    with Client(f"http://127.0.0.1:{port}", cache_dir=settings.data_dir / "cache") as client:
        worker = Worker(settings)
        worker.recover_interrupted()

        def run_worker_once() -> None:
            worker.run_once()

        return run_submitted_journey(
            client,
            runner=settings.runner_kind,
            agents=agents,
            horizon=horizon,
            demand=demand,
            timeout_seconds=settings.job_timeout_seconds,
            after_submit=run_worker_once,
        )


def _settings(root: Path, runner: str, agents: int) -> Settings:
    return Settings(
        data_dir=root,
        database_path=root / "jobs.db",
        catalog_path=Path(__file__).parent / "data" / "catalog.json",
        runner_kind=runner,
        job_timeout_seconds=600,
        max_rss_bytes=3 * 1024**3,
        max_agents=agents,
        poll_seconds=0.01,
        api_token=None,
    )


def _server_environment(settings: Settings) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        METRO_DATA_DIR=str(settings.data_dir),
        METRO_DATABASE_PATH=str(settings.database_path),
        METRO_CATALOG_PATH=str(settings.catalog_path),
        METRO_RUNNER=settings.runner_kind,
        METRO_MAX_AGENTS=str(settings.max_agents),
    )
    return env


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


def _stop(server: subprocess.Popen[bytes]) -> None:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)


if __name__ == "__main__":
    main()
