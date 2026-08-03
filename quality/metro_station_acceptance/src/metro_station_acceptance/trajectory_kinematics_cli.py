from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from .trajectory_kinematics_gate import analyze_trajectory_kinematics
from .trajectory_truth_inputs import TrajectoryTruthInputError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gate high-rate JuPedSim walking truth; presentation tracks are rejected."
    )
    parser.add_argument("input", type=Path, help="Replay, simulation trace, or movement trace JSON.")
    parser.add_argument("--output", type=Path, help="Write the versioned report here.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
        report = analyze_trajectory_kinematics(payload)
        encoded = json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
    except (OSError, json.JSONDecodeError, TrajectoryTruthInputError, ValueError) as exc:
        print(f"[TRAJECTORY KINEMATICS GATE] error: {exc}", file=sys.stderr)
        return 2

    if args.output is None:
        print(encoded, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(
            f"[TRAJECTORY KINEMATICS GATE] status={report['status']} output={args.output}",
            file=sys.stderr,
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
