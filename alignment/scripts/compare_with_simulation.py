from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.metrics.comparison import (
    build_comparison_payload,
)
from metro_alignment.scenes import build_scene_config


def _read_json_snapshot(path: Path) -> tuple[dict, str]:
    content = path.read_bytes()
    return json.loads(content), hashlib.sha256(content).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare observed metrics and simulated metrics.")
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--simulation", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    observed, observed_sha256 = _read_json_snapshot(args.observed)
    simulation, simulation_sha256 = _read_json_snapshot(args.simulation)
    trusted_scene = build_scene_config(args.scene_id)
    payload = build_comparison_payload(
        scene_id=args.scene_id,
        observed_artifact=observed,
        simulation_artifact=simulation,
        trusted_observed_dataset_id=trusted_scene.observed_dataset_id,
        trusted_desired_speed_mps=trusted_scene.jupedsim_desired_speed_mps,
        trusted_geometry_status=trusted_scene.geometry_evidence_status,
        trusted_evidence_sha256=trusted_scene.geometry_evidence_sha256,
        observed_input={"path": args.observed.name, "sha256": observed_sha256},
        simulation_input={"path": args.simulation.name, "sha256": simulation_sha256},
    )
    write_json_atomic(args.out, payload)
    print(
        json.dumps(
            {"status": "ok", "output": str(args.out), "verdict": payload["overall_verdict"]}
        )
    )


if __name__ == "__main__":
    main()
