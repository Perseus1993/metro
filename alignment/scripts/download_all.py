from __future__ import annotations

import argparse
from pathlib import Path

from metro_alignment.datasets.download import download_all
from metro_alignment.datasets.registry import list_dataset_specs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download alignment datasets.")
    parser.add_argument("--alignment-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dataset-id", action="append", dest="dataset_ids")
    parser.add_argument("--all", action="store_true", help="download all datasets in registry")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_root = args.alignment_root / "data" / "raw"
    if args.all:
        dataset_ids = [s.dataset_id for s in list_dataset_specs()]
    else:
        dataset_ids = args.dataset_ids or []
    results = download_all(dataset_ids, raw_root)
    for r in results:
        state = "skip" if r.skipped else "ok"
        print(f"[{state}] {r.dataset_id}/{r.file_name} -> {r.path}")


if __name__ == "__main__":
    main()
