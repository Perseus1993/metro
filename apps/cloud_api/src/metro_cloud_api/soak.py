from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .catalog import Catalog
from .config import Settings
from .spec import resolve_spec
from .store import JobStore
from .worker import Worker


def run_soak(
    *,
    jobs: int,
    agents: int,
    runner_kind: str,
    horizon_minutes: int,
    demand_minutes: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    catalog_path = Path(__file__).parent / "data" / "catalog.json"
    with tempfile.TemporaryDirectory(prefix="metro-cloud-soak-") as folder:
        root = Path(folder)
        settings = Settings(
            data_dir=root,
            database_path=root / "jobs.db",
            catalog_path=catalog_path,
            runner_kind=runner_kind,
            job_timeout_seconds=timeout_seconds,
            max_rss_bytes=3 * 1024**3,
            max_agents=agents,
            poll_seconds=0.01,
            api_token=None,
        )
        worker = Worker(settings)
        catalog = Catalog.load(catalog_path)
        artifacts = ArtifactStore(settings.jobs_dir)
        records = []
        started = time.monotonic()
        for index in range(jobs):
            job_id = f"soak-{index + 1:03d}"
            payload = _payload(agents, horizon_minutes, demand_minutes, index)
            resolved = resolve_spec(payload, catalog, agents)
            artifacts.prepare(job_id)
            artifacts.write_specs(job_id, payload, resolved)
            worker.store.create(job_id, payload, resolved)
            job_started = time.monotonic()
            worker.run_once()
            job = worker.store.get(job_id)
            records.append(
                _record(job, artifacts, round(time.monotonic() - job_started, 3))
            )
            if job["status"] != "succeeded":
                break
        statuses = JobStore(settings.database_path).list(limit=jobs)
        return {
            "runner": runner_kind,
            "requested_jobs": jobs,
            "completed_jobs": len(records),
            "agents_per_job": agents,
            "horizon_minutes": horizon_minutes,
            "demand_minutes": demand_minutes,
            "wall_seconds": round(time.monotonic() - started, 3),
            "passed": len(records) == jobs and all(item["status"] == "succeeded" for item in records),
            "records": records,
            "sqlite_statuses": {item["id"]: item["status"] for item in statuses},
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run consecutive jobs through the serial worker")
    parser.add_argument("--jobs", type=int, default=10)
    parser.add_argument("--agents", type=int, default=50)
    parser.add_argument("--runner", choices=("fake", "real"), default="real")
    parser.add_argument("--horizon-minutes", type=int, default=15)
    parser.add_argument("--demand-minutes", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=14_400)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_soak(
        jobs=args.jobs,
        agents=args.agents,
        runner_kind=args.runner,
        horizon_minutes=args.horizon_minutes,
        demand_minutes=args.demand_minutes,
        timeout_seconds=args.timeout_seconds,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not report["passed"]:
        raise SystemExit(1)


def _payload(agents: int, horizon: int, demand: int, index: int) -> dict[str, Any]:
    return {
        "spec_version": "0.1",
        "horizon_minutes": horizon,
        "demand_minutes": demand,
        "entry_count_hour": round(agents * 60 / demand),
        "exit_count_hour": 0,
        "transfer_count_hour": 0,
        "trajectory_sample_seconds": 10,
        "seed": 42 + index,
        "label": f"soak-{index + 1:03d}",
    }


def _record(job: dict[str, Any], artifacts: ArtifactStore, wall_seconds: float) -> dict[str, Any]:
    files = artifacts.list(job["id"])
    summary_path = artifacts.job_dir(job["id"]) / "summary.json"
    summary = json.loads(summary_path.read_text("utf-8")) if summary_path.exists() else None
    return {
        "job_id": job["id"],
        "status": job["status"],
        "wall_seconds": wall_seconds,
        "peak_rss_bytes": None if summary is None else summary["result"].get("peak_rss_bytes"),
        "artifact_count": len(files),
        "artifacts": {item["name"]: item["sha256"] for item in files},
        "private_result_removed": not (artifacts.job_dir(job["id"]) / "_result.json").exists(),
        "error": job["error"],
    }


if __name__ == "__main__":
    main()
