from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metro_station_experiments.reliability import reliability_report  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize emergency matrix reliability.")
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--min-samples", type=int, default=30)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260712)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    report = reliability_report(
        payload.get("runs", []),
        min_samples=args.min_samples,
        bootstrap_samples=args.bootstrap_samples,
        bootstrap_seed=args.bootstrap_seed,
    )
    report["model_evidence_version"] = payload.get("metadata", {}).get(
        "model_evidence_version"
    )
    report["source_configuration_fingerprint"] = payload.get("metadata", {}).get(
        "configuration_fingerprint"
    )
    output = args.output or args.input_json.with_name(
        args.input_json.stem + "_reliability.json"
    )
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"[RELIABILITY] status={report['status']} output={output}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
