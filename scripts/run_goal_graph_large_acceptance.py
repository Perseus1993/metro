from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from metro_station_acceptance.goal_graph_acceptance import (
    run_goal_graph_acceptance,
)
from metro_station_acceptance.layout_acceptance_contract import LAYOUT_IDS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = (
    ROOT / "sandbox" / "metro_station_sandbox" / "config" / "goal_graph_catalog.json"
)
DEFAULT_OUTPUT = ROOT / "output" / "goal_graph_acceptance" / "report.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run large active Goal Graph acceptance")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--layout", choices=LAYOUT_IDS, default="visual_demo_station")
    parser.add_argument("--entry-count-hour", type=int, default=1800)
    parser.add_argument("--exit-count-hour", type=int, default=900)
    parser.add_argument("--transfer-count-hour", type=int, default=900)
    parser.add_argument("--demand-minutes", type=int, default=5)
    parser.add_argument("--clearance-minutes", type=int, default=25)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_goal_graph_acceptance(
        layout_id=args.layout,
        seed=args.seed,
        entry_count_hour=args.entry_count_hour,
        exit_count_hour=args.exit_count_hour,
        transfer_count_hour=args.transfer_count_hour,
        demand_minutes=args.demand_minutes,
        clearance_minutes=args.clearance_minutes,
        catalog_path=str(args.catalog),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False))
    return 0 if report.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
