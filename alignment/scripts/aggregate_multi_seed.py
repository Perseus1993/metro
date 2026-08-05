from __future__ import annotations

import argparse
import json
from pathlib import Path

from metro_alignment.multi_seed import (
    aggregate_formal_manifests,
    aggregate_legacy_smoke,
    write_aggregate,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate fixed seeds 41-50 and compute a 95% CI.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, nargs="+")
    source.add_argument("--input-dir", type=Path)
    source.add_argument("--legacy-smoke", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.legacy_smoke:
        payload = aggregate_legacy_smoke(args.legacy_smoke)
    else:
        inputs = args.input
        if args.input_dir:
            inputs = sorted(args.input_dir.rglob("*_simulated.json"))
        payload = aggregate_formal_manifests(inputs or [])
    write_aggregate(args.out, payload)
    print(json.dumps({"status": payload["gate_status"], "output": str(args.out)}))


if __name__ == "__main__":
    main()
