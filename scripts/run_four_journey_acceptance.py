from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metro_station_acceptance.goal_journey_acceptance import (  # noqa: E402
    run_four_journey_acceptance,
)
from metro_station_acceptance.layout_acceptance_contract import (  # noqa: E402
    LAYOUT_IDS,
)


DEFAULT_OUTPUT = ROOT / "output" / "goal_graph_acceptance" / "four_journey_report.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run active Goal Graph acceptance for all four journey types"
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[41, 42, 43])
    parser.add_argument("--layout", choices=LAYOUT_IDS, default="visual_demo_station")
    parser.add_argument("--entry-count-hour", type=int, default=1800)
    parser.add_argument("--exit-count-hour", type=int, default=900)
    parser.add_argument("--transfer-count-hour", type=int, default=900)
    parser.add_argument("--demand-minutes", type=int, default=5)
    parser.add_argument("--clearance-minutes", type=int, default=25)
    parser.add_argument("--evacuation-persons", type=int, default=30)
    parser.add_argument("--evacuation-minutes", type=int, default=8)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_four_journey_acceptance(
        layout_id=args.layout,
        seeds=tuple(args.seeds),
        normal_options={
            "entry_count_hour": args.entry_count_hour,
            "exit_count_hour": args.exit_count_hour,
            "transfer_count_hour": args.transfer_count_hour,
            "demand_minutes": args.demand_minutes,
            "clearance_minutes": args.clearance_minutes,
        },
        evacuation_persons=args.evacuation_persons,
        evacuation_minutes=args.evacuation_minutes,
    )
    payload = report.as_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if report.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
