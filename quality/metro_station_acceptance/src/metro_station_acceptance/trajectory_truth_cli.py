from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from .trajectory_truth_gate import TrajectoryTruthGateConfig, analyze_trajectory_truth
from .trajectory_truth_inputs import TrajectoryTruthInputError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run structural trajectory gates on simulation_trace.snapshots or "
            "normalized id/t/x/y JSON. Presentation tracks are rejected."
        )
    )
    parser.add_argument("input", type=Path, help="Input JSON path.")
    parser.add_argument("--output", type=Path, help="Write versioned JSON report to this path.")
    parser.add_argument(
        "--coordinate-unit",
        choices=("m", "unknown"),
        help="Override the input coordinate unit. Speed is gated only for 'm'.",
    )
    parser.add_argument(
        "--max-average-speed-m-s",
        type=float,
        default=3.5,
        help="Gross structural speed ceiling; fine walking gates require <=0.2 s samples.",
    )
    parser.add_argument(
        "--same-time-position-epsilon",
        type=float,
        default=0.001,
        help="Distance above which duplicate id/time observations conflict.",
    )
    parser.add_argument(
        "--min-exact-colocation-duration-s",
        type=float,
        default=2.0,
        help="Minimum duration of consecutive exact co-location that fails the gate.",
    )
    parser.add_argument(
        "--min-exact-colocation-samples",
        type=int,
        default=2,
        help="Minimum consecutive co-located samples that can fail the gate.",
    )
    parser.add_argument(
        "--max-issue-examples",
        type=int,
        default=20,
        help="Maximum examples retained per check.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
        report = analyze_trajectory_truth(
            payload,
            config=TrajectoryTruthGateConfig(
                max_average_speed_m_s=args.max_average_speed_m_s,
                same_time_position_epsilon=args.same_time_position_epsilon,
                min_exact_colocation_duration_s=args.min_exact_colocation_duration_s,
                min_exact_colocation_samples=args.min_exact_colocation_samples,
                max_issue_examples=args.max_issue_examples,
                coordinate_unit=args.coordinate_unit,
            ),
        )
        encoded = json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
    except (OSError, json.JSONDecodeError, TrajectoryTruthInputError, ValueError) as exc:
        print(f"[TRAJECTORY TRUTH GATE] error: {exc}", file=sys.stderr)
        return 2

    if args.output is None:
        print(encoded, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(
            f"[TRAJECTORY TRUTH GATE] status={report['status']} output={args.output}",
            file=sys.stderr,
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
