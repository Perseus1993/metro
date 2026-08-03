from __future__ import annotations

import argparse
import json
from pathlib import Path

from metro_station_acceptance.trajectory_acceptance import run_trajectory_acceptance
from metro_station_acceptance.trajectory_truth_inputs import TrajectoryTruthInputError


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run structural truth, high-rate walking, all-state composite, "
            "and presentation-isolation gates."
        )
    )
    parser.add_argument("--replay", type=Path, required=True, help="Compact scientific replay JSON.")
    parser.add_argument("--bundle", type=Path, required=True, help="Full presentation bundle JSON.")
    parser.add_argument("--output", type=Path, required=True, help="Combined report JSON.")
    args = parser.parse_args()
    try:
        scientific = json.loads(args.replay.read_text(encoding="utf-8-sig"))
        presentation = json.loads(args.bundle.read_text(encoding="utf-8-sig"))
        report = run_trajectory_acceptance(
            scientific_payload=scientific,
            presentation_payload=presentation,
        )
    except (OSError, json.JSONDecodeError, TrajectoryTruthInputError, ValueError) as exc:
        print(f"[TRAJECTORY ACCEPTANCE] error: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    print(f"[TRAJECTORY ACCEPTANCE] status={report['status']} output={args.output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
