from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metro_station_experiments.release_gate import assess_release  # noqa: E402
from scripts.run_metro_emergency_matrix import MODEL_EVIDENCE_VERSION  # noqa: E402


def int_list(value: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in value.split(",") if part.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate production release evidence.")
    parser.add_argument("--emergency", type=Path, required=True)
    parser.add_argument("--reliability", type=Path, action="append", required=True)
    parser.add_argument("--sensitivity", type=Path, required=True)
    parser.add_argument("--performance", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--required-populations", type=int_list, default=(60, 120, 240))
    parser.add_argument("--minimum-reliability-samples", type=int, default=30)
    parser.add_argument("--density-threshold-authority-approved", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "metro_release_gate.json")
    return parser


def load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Metro simulation production release gate",
        "",
        f"- Status: **{report['status']}**",
        f"- Production ready: **{report['production_ready']}**",
        f"- Blockers: **{report['blocker_count']}**",
        "",
        "## Checks",
        "",
    ]
    lines.extend(
        f"- {check['component']}"
        + (f" population={check['population']}" if "population" in check else "")
        + f": {check['status']}"
        for check in report["checks"]
    )
    lines.extend(["", "## Blockers", ""])
    lines.extend(
        f"- `{item.get('code', 'unknown')}`: {item.get('message', json.dumps(item, ensure_ascii=False))}"
        for item in report["blockers"]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    report = assess_release(
        emergency=load(args.emergency),
        reliability_reports=[load(path) for path in args.reliability],
        sensitivity=load(args.sensitivity),
        performance=load(args.performance),
        calibration=load(args.calibration),
        required_populations=args.required_populations,
        minimum_reliability_samples=args.minimum_reliability_samples,
        density_threshold_authority_approved=args.density_threshold_authority_approved,
        expected_model_evidence_version=MODEL_EVIDENCE_VERSION,
    )
    report["evidence_files"] = {
        "emergency": str(args.emergency.resolve()),
        "reliability": [str(path.resolve()) for path in args.reliability],
        "sensitivity": str(args.sensitivity.resolve()),
        "performance": str(args.performance.resolve()),
        "calibration": str(args.calibration.resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(args)
    print(f"[RELEASE] status={report['status']} blockers={report['blocker_count']}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
