from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from metro_cloud import Client


def run_remote_soak(
    *,
    base_url: str,
    token: str | None,
    jobs: int,
    agents: int,
    horizon_minutes: int,
    demand_minutes: int,
    timeout_seconds: float,
    after_submit: Callable[[], None] | None = None,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="metro-cloud-remote-soak-") as cache:
        with Client(base_url, token=token, cache_dir=cache) as client:
            for index in range(jobs):
                job_started = time.monotonic()
                job = client.submit(
                    {
                        "spec_version": "0.1",
                        "horizon_minutes": horizon_minutes,
                        "demand_minutes": demand_minutes,
                        "entry_count_hour": round(agents * 60 / demand_minutes),
                        "exit_count_hour": 0,
                        "transfer_count_hour": 0,
                        "trajectory_sample_seconds": 10,
                        "seed": 42 + index,
                        "label": f"target-soak-{index + 1:03d}",
                    }
                )
                if after_submit is not None:
                    after_submit()
                job.wait(timeout=timeout_seconds, poll_seconds=1)
                artifacts = job.artifacts()
                summary = job.summary()
                checks = {
                    "job_succeeded": job.status == "succeeded",
                    "summary_succeeded": summary["status"] == "succeeded",
                    "agent_count_matches": (
                        summary["result"]["passenger_agent_count"] == agents
                    ),
                    "six_public_artifacts": len(artifacts) == 6,
                    "all_artifacts_have_sha256": all(
                        len(item["sha256"]) == 64 for item in artifacts
                    ),
                }
                records.append(
                    {
                        "job_id": job.id,
                        "status": job.status,
                        "wall_seconds": round(time.monotonic() - job_started, 3),
                        "peak_rss_bytes": summary["result"]["peak_rss_bytes"],
                        "checks": checks,
                    }
                )
                if not all(checks.values()):
                    break
    return {
        "base_url": base_url,
        "requested_jobs": jobs,
        "completed_jobs": len(records),
        "agents_per_job": agents,
        "horizon_minutes": horizon_minutes,
        "demand_minutes": demand_minutes,
        "wall_seconds": round(time.monotonic() - started, 3),
        "records": records,
        "passed": len(records) == jobs
        and all(all(record["checks"].values()) for record in records),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run consecutive jobs through an already-deployed API and worker"
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--token")
    parser.add_argument("--jobs", type=int, default=10)
    parser.add_argument("--agents", type=int, default=50)
    parser.add_argument("--horizon-minutes", type=int, default=15)
    parser.add_argument("--demand-minutes", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=14_400)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_remote_soak(
        base_url=args.url,
        token=args.token or os.environ.get("METRO_API_TOKEN") or None,
        jobs=args.jobs,
        agents=args.agents,
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


if __name__ == "__main__":
    main()
