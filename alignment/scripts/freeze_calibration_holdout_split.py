from __future__ import annotations

import argparse
import json
from pathlib import Path

from metro_alignment.evidence_split import build_split_manifest, freeze_split


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Freeze an independent calibration/holdout split.")
    parser.add_argument(
        "--calibration",
        type=Path,
        default=root / "data/raw/eindhoven_platform_v1/Eindhoven_centraal_trajectories_days_01_10.parquet",
    )
    parser.add_argument(
        "--holdout",
        type=Path,
        default=root / "data/holdout_raw/eindhoven_platform_holdout_days11_20_v1/Eindhoven_centraal_trajectories_days_11_20.parquet",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=root / "data/metrics/calibration_holdout_split_eindhoven_platform_v1.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_split_manifest(
        args.calibration,
        args.holdout,
        calibration_dataset_id="eindhoven_platform_calibration_days01_10_v1",
        holdout_dataset_id="eindhoven_platform_holdout_days11_20_v1",
        calibration_expected_md5="34f1b0c41d93184f0ae30a45246f82dc",
        holdout_expected_md5="48dfb09889cca222252ad9fb47913b0e",
    )
    freeze_split(args.out, payload)
    print(json.dumps({"status": "frozen", "output": str(args.out), "proof": payload["zero_overlap_proof"]}))


if __name__ == "__main__":
    main()
