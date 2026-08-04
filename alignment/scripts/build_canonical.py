from __future__ import annotations

import argparse
import json
from pathlib import Path

from metro_alignment.canonical import build_metadata, validate, write_canonical, write_metadata
from metro_alignment.datasets.registry import get_dataset_spec, resolve_reference


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build canonical trajectory files.")
    parser.add_argument("--alignment-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--source", type=Path, required=True, help="raw source path")
    parser.add_argument("--output", type=Path, default=None, help="output directory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    spec = get_dataset_spec(args.dataset_id)
    out_root = args.output or (args.alignment_root / "data" / "canonical")
    out_root.mkdir(parents=True, exist_ok=True)

    if spec.status != "active":
        raise RuntimeError(f"dataset {spec.dataset_id} is pending data preparation: {spec.notes}")

    raw_loader = resolve_reference(spec.raw_loader_ref)
    to_canonical = resolve_reference(spec.to_canonical_ref)
    raw_df = raw_loader(args.source)
    canonical = to_canonical(
        raw_df,
        dataset_id=spec.dataset_id,
        agent_offset=spec.agent_id_offset,
    )
    errors = validate(canonical)
    if errors:
        raise ValueError("loader produced invalid canonical data: " + "; ".join(errors))

    output = out_root / f"{spec.dataset_id}.parquet"
    meta_output = out_root / f"{spec.dataset_id}.meta.json"
    meta = build_metadata(
        canonical,
        dataset_id=spec.dataset_id,
        source_url=spec.source_url,
        license=spec.license,
        citation=spec.citation,
        frame_rate_hz=spec.frame_rate_hz,
    )
    write_canonical(canonical, output)
    write_metadata(meta, meta_output)

    print(json.dumps({"parquet": str(output), "meta": str(meta_output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
