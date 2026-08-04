from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sandbox.metro_station_sandbox.calibration.validation import (  # noqa: E402
    CalibrationValidationPolicy,
    missing_calibration_evidence,
    validate_calibration,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate simulation against observed cases.")
    parser.add_argument("--simulated", type=Path)
    parser.add_argument("--observed", type=Path)
    parser.add_argument("--calibration-dataset-id", default="")
    parser.add_argument("--validation-dataset-id", default="")
    parser.add_argument("--min-matched-cases", type=int, default=10)
    parser.add_argument("--max-clearance-mae-seconds", type=float, default=30.0)
    parser.add_argument("--max-clearance-mape", type=float, default=0.15)
    parser.add_argument("--max-density-mae-persons-m2", type=float, default=0.5)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "calibration_validation.json")
    return parser


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    for key in ("runs", "rows", "observations"):
        if isinstance(payload.get(key), list):
            return payload[key]
    raise ValueError(f"{path} does not contain a row list")


def run(args: argparse.Namespace) -> dict[str, Any]:
    missing = [str(path) for path in (args.simulated, args.observed) if path is None or not path.is_file()]
    if missing:
        report = missing_calibration_evidence(
            "real independent simulated/observed evidence files are missing: " + ", ".join(missing)
        )
    else:
        report = validate_calibration(
            load_rows(args.simulated),
            load_rows(args.observed),
            calibration_dataset_id=args.calibration_dataset_id,
            validation_dataset_id=args.validation_dataset_id,
            policy=CalibrationValidationPolicy(
                min_matched_cases=args.min_matched_cases,
                max_clearance_mae_seconds=args.max_clearance_mae_seconds,
                max_clearance_mape=args.max_clearance_mape,
                max_density_mae_persons_m2=args.max_density_mae_persons_m2,
            ),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(args)
    print(f"[CALIBRATION] status={report['status']} output={args.output}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
