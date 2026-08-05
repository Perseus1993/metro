from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from metro_cloud import Client

from .acceptance_journey import run_submitted_journey


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify an already-running API and worker")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--runner", choices=("fake", "real"), default="real")
    parser.add_argument("--agents", type=int, default=50)
    parser.add_argument("--horizon-minutes", type=int, default=15)
    parser.add_argument("--demand-minutes", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=14_400)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    token = os.environ.get("METRO_API_TOKEN") or None
    with tempfile.TemporaryDirectory(prefix="metro-cloud-remote-e2e-") as cache:
        with Client(args.url, token=token, timeout=60, cache_dir=cache) as client:
            report = run_submitted_journey(
                client,
                runner=args.runner,
                agents=args.agents,
                horizon=args.horizon_minutes,
                demand=args.demand_minutes,
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
