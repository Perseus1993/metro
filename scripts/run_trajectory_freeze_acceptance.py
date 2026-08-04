from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metro_station_acceptance.trajectory_freeze_acceptance import (  # noqa: E402
    DEFAULT_TRAJECTORY_FREEZE_SPECS,
    run_trajectory_freeze_acceptance,
)


DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "acceptance" / "trajectory_freeze"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the P11 trajectory freeze acceptance")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--case-id",
        action="append",
        choices=tuple(spec.case_id for spec in DEFAULT_TRAJECTORY_FREEZE_SPECS),
        help="run only the selected frozen case; repeat to select multiple cases",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selected = set(args.case_id or ())
    specs = tuple(
        spec
        for spec in DEFAULT_TRAJECTORY_FREEZE_SPECS
        if not selected or spec.case_id in selected
    )
    report = run_trajectory_freeze_acceptance(args.output_dir, specs=specs)
    print(
        json.dumps(
            {
                "status": report["status"],
                "case_count": report["case_count"],
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
