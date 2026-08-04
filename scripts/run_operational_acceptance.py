from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metro_station_acceptance.operational_acceptance_matrix import (  # noqa: E402
    run_operational_acceptance_matrix,
)
from metro_station_acceptance.operational_acceptance_scenarios import (  # noqa: E402
    OPERATIONAL_SCENARIOS,
)
from metro_station_acceptance.layout_acceptance_contract import (  # noqa: E402
    LAYOUT_IDS,
)


DEFAULT_OUTPUT = ROOT / "output" / "goal_graph_acceptance" / "operational_report.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Goal Graph operational recovery acceptance"
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[41, 42, 43])
    parser.add_argument("--layout", choices=LAYOUT_IDS, default="visual_demo_station")
    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=OPERATIONAL_SCENARIOS,
        default=list(OPERATIONAL_SCENARIOS),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_operational_acceptance_matrix(
        layout_id=args.layout,
        seeds=tuple(args.seeds),
        scenario_ids=tuple(args.scenarios),
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
