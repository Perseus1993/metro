from __future__ import annotations

import argparse
import json
from pathlib import Path

from metro_alignment.evidence_manifest import (
    verify_round25_evidence_manifest,
    write_round25_evidence_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("alignment/output/round25"),
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    manifest_path = args.output_dir / "round25_evidence_manifest.json"
    if args.verify_only:
        manifest = verify_round25_evidence_manifest(manifest_path)
    else:
        manifest_path = write_round25_evidence_manifest(args.output_dir)
        manifest = verify_round25_evidence_manifest(manifest_path)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "artifact_count": len(manifest["entries"]),
                "manifest": str(manifest_path),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
