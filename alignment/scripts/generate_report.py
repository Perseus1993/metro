from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from metro_alignment.report import walking_speed_proxy_recommendation, write_report


def _read_json_snapshot(path: Path) -> tuple[dict, str]:
    content = path.read_bytes()
    return json.loads(content), hashlib.sha256(content).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an evidence-linked parameter report.")
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--current-desired-speed-mps", type=float, default=None)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    comparison, comparison_sha256 = _read_json_snapshot(args.comparison)
    scene_id = str(comparison.get("scene_id", ""))
    expected_name = f"parameter_report_{scene_id}.json"
    if (
        args.out.name != expected_name
        or args.out.parent.resolve() != args.comparison.parent.resolve()
    ):
        raise ValueError(
            f"--out must be {args.comparison.parent / expected_name} beside its comparison"
        )
    trusted_current = float(
        comparison["trusted_parameters"]["jupedsim_desired_speed_mps"]
    )
    if (
        args.current_desired_speed_mps is not None
        and args.current_desired_speed_mps != trusted_current
    ):
        raise ValueError(
            "--current-desired-speed-mps must exactly match the trusted SceneConfig value"
        )
    recommendation = walking_speed_proxy_recommendation(
        comparison,
        source=args.comparison.name,
    )
    decision = (
        "pass" if recommendation.evidence.get("parameter_change_authorized") is True else "hold"
    )
    write_report(
        args.out,
        [recommendation],
        release_decision=decision,
        source_artifacts={
            "comparison": {"path": args.comparison.name, "sha256": comparison_sha256}
        },
        comparison=comparison,
    )
    print(json.dumps({"status": "ok", "output": str(args.out), "decision": decision}))


if __name__ == "__main__":
    main()
