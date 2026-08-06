from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from metro_station.application.simulation import SimulationRequest, run_simulation

from metro_alignment.analysis_runtime import analysis_runtime_fingerprint
from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.metro_executor import AlignmentMesaSimulationExecutor
from metro_alignment.metro_runtime import metro_source_fingerprint
from metro_alignment.metro_scene import build_metro_request
from metro_alignment.round27_acceptance import (
    ThroughputFloor,
    evaluate_dynamic_gate,
    evaluate_stress_gate,
    validate_dynamic_floor_qualification,
)
from metro_alignment.scenes import build_scene_config


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a frozen Round 27 source-boundary or Round 26 regression probe."
    )
    parser.add_argument("--seed", type=int, required=True, choices=range(41, 51))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--horizon", type=int, choices=(240, 480), default=240)
    parser.add_argument(
        "--floor-artifact",
        type=Path,
        default=Path("alignment/output/round27/T7_dynamic_floor_qualification.json"),
    )
    parser.add_argument("--entry-capacity", type=int)
    parser.add_argument("--exit-capacity", type=int)
    return parser.parse_args()


def _git_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
        encoding="utf-8",
    ).strip()


def _floors(path: Path) -> tuple[ThroughputFloor, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_dynamic_floor_qualification(payload)


def _audit_counts(runtime: Any) -> Counter[str]:
    counts: Counter[str] = Counter()
    for event in runtime.audit.events:
        counts[str(event.code)] += int(event.count)
    return counts


def _replan_contexts(runtime: Any) -> list[dict[str, Any]]:
    return [
        {
            "step": int(event.step),
            "count": int(event.count),
            "context": dict(event.context),
        }
        for event in runtime.audit.events
        if event.code == "passenger_replanned_stalled_region_approach"
    ]


def _flow_rows(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = snapshot["source_boundaries"]["flows"]
    return {flow: dict(rows[flow]) for flow in ("entry", "exit")}


def _stress_metrics(
    flows: dict[str, dict[str, Any]],
    admission: dict[str, object],
    audit_counts: Counter[str],
    run_outcome_code: str | None,
) -> dict[str, Any]:
    return {
        "scheduled_demand_persons": sum(
            int(row["scheduled_persons"]) for row in flows.values()
        ),
        "eligible_service_opportunities": sum(
            int(admission[f"alignment_{flow}_admission_attempts"]) for flow in flows
        ),
        "completed_persons": sum(int(row["completed_persons"]) for row in flows.values()),
        "source_waiting_persons": sum(
            int(row["source_waiting_persons"]) for row in flows.values()
        ),
        "active_inside_persons": sum(
            int(row["active_inside_persons"]) for row in flows.values()
        ),
        "not_alighted_persons": sum(
            int(row["not_alighted_persons"]) for row in flows.values()
        ),
        "admission_exhausted_attempts": sum(
            int(admission[f"alignment_{flow}_admission_exhausted_attempts"])
            for flow in flows
        ),
        "dropped_persons": sum(int(row["dropped_persons"]) for row in flows.values()),
        "run_outcome_code": run_outcome_code,
        "unhandled_expected_capacity_exceptions": audit_counts[
            "unhandled_expected_capacity_exception"
        ],
    }


def main() -> int:
    args = _parse_args()
    revision = _git_revision()
    metro_fingerprint = metro_source_fingerprint()
    analysis_fingerprint = analysis_runtime_fingerprint()
    config = replace(
        build_scene_config("platform_boarding"),
        seed=int(args.seed),
        entry_admission_token_capacity=args.entry_capacity,
        exit_admission_token_capacity=args.exit_capacity,
    )
    request, design_sha256 = build_metro_request(config)
    request = SimulationRequest(
        scenario=replace(request.scenario, audit_print_events=False),
        seed=int(args.seed),
    )
    execution = run_simulation(
        request,
        AlignmentMesaSimulationExecutor(formal_horizon_steps=int(args.horizon)),
    )
    runtime = execution.runtime
    if _git_revision() != revision:
        raise RuntimeError("Git revision changed during the source probe")
    if metro_source_fingerprint() != metro_fingerprint:
        raise RuntimeError("Metro runtime changed during the source probe")
    if analysis_runtime_fingerprint() != analysis_fingerprint:
        raise RuntimeError("Alignment runtime changed during the source probe")
    snapshot = runtime.snapshot()
    flows = _flow_rows(snapshot)
    admission = runtime.alignment_source_admission_metrics()
    audit_counts = _audit_counts(runtime)
    replan_contexts = _replan_contexts(runtime)
    if int(args.horizon) == 240:
        floors = _floors(args.floor_artifact)
        dynamic_gate = evaluate_dynamic_gate(
            flows,
            floors,
            run_outcome_code=snapshot.get("run_outcome_code"),
            liveness_violations=audit_counts["passenger_liveness_violation"],
            round26_replan_ratio=(
                audit_counts["passenger_replanned_stalled_region_approach"]
                / max(1, sum(int(row["admitted_persons"]) for row in flows.values()))
            ),
            round26_placement_retry_ratio=float(
                admission["alignment_placement_retry_ratio"]
            ),
        )
    else:
        dynamic_gate = {
            "schema_version": "alignment_round27_dynamic_gate.v1",
            "status": "not_evaluated",
            "reason": "240-step dynamic floors do not apply to a 480-step regression probe",
            "throughput_floors": [],
            "checks": [],
        }
    stress_metrics = _stress_metrics(
        flows,
        admission,
        audit_counts,
        snapshot.get("run_outcome_code"),
    )
    payload = {
        "schema_version": "alignment_round27_source_probe.v1",
        "revision": revision,
        "runtime_cohort": {
            "metro_runtime_fingerprint": metro_fingerprint,
            "analysis_runtime_fingerprint": analysis_fingerprint,
        },
        "seed": int(args.seed),
        "control": {
            "scene_id": config.scene_id,
            "minutes": config.minutes,
            "demand_minutes": config.demand_minutes,
            "formal_horizon_steps": int(args.horizon),
            "entry_count_hour": config.entry_count_hour,
            "exit_count_hour": config.exit_count_hour,
            "entry_admission_token_capacity": args.entry_capacity,
            "exit_admission_token_capacity": args.exit_capacity,
            "design_sha256": design_sha256,
        },
        "run_outcome_code": snapshot.get("run_outcome_code"),
        "step": int(runtime.step_index),
        "flows": flows,
        "admission": {
            flow: {
                "attempts": int(admission[f"alignment_{flow}_admission_attempts"]),
                "exhausted_attempts": int(
                    admission[f"alignment_{flow}_admission_exhausted_attempts"]
                ),
                "exhausted_ratio": float(
                    admission[f"alignment_{flow}_admission_exhausted_ratio"]
                ),
            }
            for flow in flows
        },
        "round26_regression": {
            "placement_retry_attempts": int(
                admission["alignment_placement_retry_attempts"]
            ),
            "placement_retry_ratio": float(admission["alignment_placement_retry_ratio"]),
            "stalled_region_replan_attempts": audit_counts[
                "passenger_replanned_stalled_region_approach"
            ],
            "stalled_region_replan_ratio": (
                audit_counts["passenger_replanned_stalled_region_approach"]
                / max(1, sum(int(row["admitted_persons"]) for row in flows.values()))
            ),
            "liveness_violations": audit_counts["passenger_liveness_violation"],
        },
        "round28_replan_diagnostics": {
            "schema_version": "alignment_round28_replan_diagnostics.v1",
            "event_count": len(replan_contexts),
            "events": replan_contexts,
        },
        "train_manifests": runtime.train_exchange_result_rows(),
        "dynamic_gate": dynamic_gate,
        "stress_metrics": stress_metrics,
        "stress_gate": evaluate_stress_gate(stress_metrics),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(args.output, payload)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "dynamic_gate": dynamic_gate["status"],
                "stress_gate": payload["stress_gate"]["status"],
                "run_outcome_code": payload["run_outcome_code"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
