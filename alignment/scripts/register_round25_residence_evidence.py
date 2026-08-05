from __future__ import annotations

import argparse
import json
from pathlib import Path

from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.formal_contract import canonical_sha256
from metro_alignment.metro_scene import build_metro_request
from metro_alignment.scenes import build_scene_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.path.read_text(encoding="utf-8"))
    config = build_scene_config("platform_boarding")
    _request, design_sha256 = build_metro_request(config)
    if payload.get("design_sha256") != design_sha256:
        raise RuntimeError("residence evidence design does not match registered scene")
    for flow in ("entry", "exit"):
        residence = payload[flow]
        completed = sorted(int(value) for value in residence["completed_samples_steps"])
        censored = sorted(int(value) for value in residence["censored_samples_steps"])
        total = len(completed) + len(censored)
        for label, percentile in (("p50", 0.50), ("p90", 0.90), ("p99", 0.99)):
            rank = int(total * percentile + 0.999999)
            residence[f"{label}_steps"] = (
                completed[rank - 1] if rank > 0 and len(completed) >= rank else None
            )
        lower_bound = sorted(completed + censored)
        lower_bound_rank = int(total * 0.99 + 0.999999)
        residence["lower_bound_p99_steps"] = (
            lower_bound[lower_bound_rank - 1] if lower_bound_rank else None
        )
        residence["n"] = total
        residence["completed_n"] = len(completed)
        residence["censored_n"] = len(censored)
    payload["right_censoring"] = (
        "owners still active at the horizon are lifecycle-right-censored; a requested "
        "nearest-rank percentile is null unless at least that rank completed, while "
        "lower_bound_p99_steps separately reports the mixed completed/active-age bound"
    )
    scope = payload.get("evidence_scope")
    required_scope_fields = {
        "demand_minutes",
        "entry_scheduled_persons",
        "exit_scheduled_persons",
        "entry_last_scheduled_step",
        "exit_last_scheduled_step",
        "measurement_horizon_steps",
    }
    if not isinstance(scope, dict) or not required_scope_fields <= set(scope):
        raise RuntimeError(
            "residence evidence lacks the registered demand and clearance-tail scope"
        )
    payload.pop("artifact_sha256", None)
    payload["artifact_sha256"] = canonical_sha256(payload)
    write_json_atomic(args.path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
