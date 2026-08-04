from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metro_station_experiments.timestep_validation import (  # noqa: E402
    TimestepValidationPolicy,
    validate_timestep_candidate,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare JuPedSim timestep evidence.")
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def load_rows(path: Path):
    return json.loads(path.read_text(encoding="utf-8")).get("runs", [])


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = validate_timestep_candidate(
        load_rows(args.reference),
        load_rows(args.candidate),
        TimestepValidationPolicy(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"[TIMESTEP] status={report['status']} speedup={report['elapsed_speedup']}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
