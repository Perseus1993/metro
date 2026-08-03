from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from .presentation_fidelity_gate import analyze_presentation_fidelity
from .trajectory_truth_inputs import TrajectoryTruthInputError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify display decoration is isolated from simulation source points."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
        report = analyze_presentation_fidelity(payload)
        encoded = json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
    except (OSError, json.JSONDecodeError, TrajectoryTruthInputError, ValueError) as exc:
        print(f"[PRESENTATION FIDELITY GATE] error: {exc}", file=sys.stderr)
        return 2
    if args.output is None:
        print(encoded, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(
            f"[PRESENTATION FIDELITY GATE] status={report['status']} output={args.output}",
            file=sys.stderr,
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
