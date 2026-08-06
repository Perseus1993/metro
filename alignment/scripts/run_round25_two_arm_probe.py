from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from random import Random
from typing import Any

from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.demand_scheduler import DemandScheduler
from metro_station.application.simulation import run_simulation
from metro_station_testkit.two_arm_probe import build_two_arm_report

from metro_alignment.analysis_runtime import analysis_runtime_fingerprint
from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.formal_contract import canonical_sha256
from metro_alignment.metro_contract import scene_config_payload, scene_config_sha256
from metro_alignment.metro_executor import (
    AlignmentMesaSimulationExecutor,
    alignment_entry_admission_preflight,
)
from metro_alignment.metro_runtime import metro_source_fingerprint
from metro_alignment.metro_scene import build_metro_request
from metro_alignment.scenes import build_scene_config
from metro_alignment.source_integrity_gate import evaluate_source_integrity_gate


def _runtime_cohort() -> dict[str, Any]:
    return {
        "metro_runtime_fingerprint": metro_source_fingerprint(),
        "analysis_runtime_fingerprint": analysis_runtime_fingerprint(),
    }


def _terminal_admission_owner_diagnostics(runtime) -> dict[str, list[dict[str, Any]]]:
    passengers = {int(passenger.unique_id): passenger for passenger in runtime.passengers}
    result: dict[str, list[dict[str, Any]]] = {}
    for flow, resource in sorted(runtime.alignment_admission_resources.items()):
        diagnostics = []
        for owner_id in sorted(resource.owners, key=str):
            passenger = passengers.get(owner_id) if isinstance(owner_id, int) else None
            if passenger is None:
                diagnostics.append({"owner_id": owner_id, "passenger_present": False})
                continue
            goal_state = passenger.goal_runtime.state
            commitment = goal_state.commitment
            diagnostics.append(
                {
                    "owner_id": owner_id,
                    "passenger_present": True,
                    "intent": str(passenger.intent),
                    "state": str(passenger.state),
                    "position": [float(passenger.pos[0]), float(passenger.pos[1])],
                    "target": [float(passenger.target[0]), float(passenger.target[1])],
                    "route": [[float(point[0]), float(point[1])] for point in passenger.route],
                    "velocity_mps": [
                        float(passenger.last_walk_velocity_mps[0]),
                        float(passenger.last_walk_velocity_mps[1]),
                    ],
                    "progress_age_seconds": float(passenger.progress_age_seconds),
                    "last_replan_reason": passenger.last_replan_reason,
                    "goal": {
                        "kind": str(passenger.current_goal.kind),
                        "label": str(passenger.current_goal.label),
                        "stage": passenger.current_goal.stage,
                    },
                    "goal_runtime": {
                        "node_id": goal_state.current_node_id,
                        "stage": goal_state.current_stage,
                        "interaction_state": goal_state.interaction_state,
                        "retry_count": int(goal_state.retry_count),
                        "commitment_facility_id": (
                            None if commitment is None else commitment.facility_id
                        ),
                    },
                    "decision_holding_targets": {
                        region: [float(point[0]), float(point[1])]
                        for region, point in sorted(
                            passenger.decision_holding_target_by_region.items()
                        )
                    },
                    "approach_facilities": dict(
                        sorted(passenger.facility_approach_facility_ids_by_stage.items())
                    ),
                }
            )
        result[str(flow)] = diagnostics
    return result


def _require_runtime_cohort(expected: dict[str, Any], *, phase: str) -> None:
    actual = _runtime_cohort()
    if actual != expected:
        raise RuntimeError(
            f"runtime source changed during two-arm probe ({phase}); refusing mixed-cohort evidence"
        )


def _round24_historical_baseline() -> dict[str, Any]:
    source = (
        Path(__file__).parents[1] / "docs" / "reviews" / "round_24_step5_conservation_handoff.md"
    )
    normalized_source = source.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    source_sha256 = hashlib.sha256(normalized_source).hexdigest()
    expected_sha256 = "bc634d85ffc6b0e7418dcba3b17ccd504629adb37c86a3984f3f631a0a3cf496"
    if source_sha256 != expected_sha256:
        raise RuntimeError("Round 24 handoff source changed; refusing historical T0 claim")
    return {
        "schema_version": "alignment_round24_handoff_baseline.v1",
        "provenance_status": "committed_handoff_claim",
        "source": {
            "path": "alignment/docs/reviews/round_24_step5_conservation_handoff.md",
            "commit": "0b938dcdea9a117d7d3fe96cbb30c8f9520d811f",
            "git_blob_sha1": "801735a1ae5299b2fa5bebd9a38179ee3abac179",
            "file_sha256": source_sha256,
        },
        "frozen_inputs": {
            "seed": 42,
            "entry_count_hour": 2500,
            "exit_count_hour": 2200,
            "demand_steps": 120,
            "horizon_steps": 120,
            "design": "fixed-direction gates and seven train doors",
        },
        "controlled_difference": (
            "downstream finite-admission evidence reported effectively unbounded capacity"
        ),
        "arms": {
            "finite_admission": {
                "scheduled_entry": 83,
                "spawned_entry": 75,
                "pending_entry": 8,
                "dropped": 0,
                "conserved": True,
                "admission_exhausted": 90,
                "deferred_downstream": 89,
                "dynamic_blocked": 12,
                "passenger_liveness_violation": 0,
            },
            "unbounded_admission_probe": {
                "scheduled_entry": 83,
                "spawned_entry": 83,
                "pending_entry": 0,
                "dropped": 0,
                "conserved": True,
                "admission_exhausted": 0,
                "deferred_downstream": 0,
                "dynamic_blocked": 16,
                "passenger_liveness_violation": 0,
            },
        },
        "interpretation": (
            "Historical pre-refactor observation anchored to the committed Round 24 "
            "handoff; current replay results are stored separately in this T0 artifact."
        ),
    }


def _arm(
    config,
    *,
    steps: int,
    mode: str,
    expected_runtime_cohort: dict[str, Any],
    measurement_bypass_preflight: bool = False,
) -> dict[str, Any]:
    _require_runtime_cohort(expected_runtime_cohort, phase=f"{mode}:start")
    request, design_sha256 = build_metro_request(config)
    scheduler = DemandScheduler.from_scenario(
        request.scenario,
        Random(int(request.scenario.admission_residence_evidence_seed or 0)),
    )
    entry_schedule = {
        int(step): int(counter.get(AgentIntent.ENTER_AND_BOARD.value, 0))
        for step, counter in scheduler.spawn_schedule.items()
    }
    exit_schedule = {int(step): int(count) for step, count in scheduler.alighting_schedule.items()}
    executor = AlignmentMesaSimulationExecutor(formal_horizon_steps=steps)
    if measurement_bypass_preflight:
        runtime = executor.build_model(request)
        frames = runtime.run()
    else:
        execution = run_simulation(request, executor)
        runtime = execution.runtime
        frames = execution.frames
    _require_runtime_cohort(expected_runtime_cohort, phase=f"{mode}:end")
    frame_metrics = dict(frames[-1].get("metrics", {}))
    metrics = {**frame_metrics, **runtime.alignment_source_admission_metrics()}
    spatial = dict(metrics.get("spatial_capacity_event_counts", {}))
    audits = dict(metrics.get("audit_counts", {}))
    replan_by_passenger: Counter[str] = Counter()
    blocked_regions: Counter[str] = Counter()
    blocked_codes: Counter[str] = Counter()
    for event in runtime.audit.events:
        if event.code == "passenger_replanned_stalled_region_approach":
            replan_by_passenger[str(event.context.get("passenger_id", "unknown"))] += int(
                event.count
            )
        if event.code not in {"placement.dynamic_blocked", "spawn.dynamic_blocked"}:
            continue
        context = event.context
        region_key = "|".join(
            (
                str(context.get("certificate_id", "unknown_certificate")),
                str(context.get("resource_kind", "unknown_resource")),
                str(context.get("owner_id", "unknown_owner")),
            )
        )
        blocked_regions[region_key] += int(event.count)
        blocked_codes[event.code] += int(event.count)
    residence_evidence_artifacts = {}
    for flow in ("entry", "exit"):
        reference = str(getattr(config, f"{flow}_admission_residence_evidence_ref") or "")
        reference_path, _separator, _pointer = reference.partition("#")
        evidence_payload = json.loads(Path(reference_path).read_text(encoding="utf-8"))
        residence_evidence_artifacts[flow] = {
            "reference": reference,
            "artifact_sha256": evidence_payload["artifact_sha256"],
        }
    return {
        "mode": mode,
        "seed": config.seed,
        "design_sha256": design_sha256,
        "scene_config_sha256": scene_config_sha256(config),
        "scene_config": scene_config_payload(config),
        "entry_count_hour": config.entry_count_hour,
        "exit_count_hour": config.exit_count_hour,
        "horizon_steps": steps,
        "demand_steps": config.demand_minutes * 60,
        "movement_model": {
            "backend": request.scenario.movement_backend_name,
            "dt_seconds": request.scenario.jupedsim_dt_seconds,
            "iterations_per_tick": request.scenario.jupedsim_iterations_per_tick,
            "desired_speed_mps": request.scenario.jupedsim_desired_speed_mps,
        },
        "admission_evidence_scope": {
            "seed": config.seed,
            "entry_count_hour": request.scenario.entry_count_hour,
            "exit_count_hour": request.scenario.exit_count_hour,
            "demand_minutes": request.scenario.demand_duration_minutes,
            "entry_scheduled_persons": sum(entry_schedule.values()) * request.scenario.group_size,
            "exit_scheduled_persons": sum(exit_schedule.values()) * request.scenario.group_size,
            "entry_last_scheduled_step": max(entry_schedule, default=-1),
            "exit_last_scheduled_step": max(exit_schedule, default=-1),
            "measurement_horizon_steps": steps,
            "group_size": request.scenario.group_size,
            "gate_service_persons_per_min": (request.scenario.gate_service_persons_per_min),
            "train_dwell_seconds": request.scenario.train_dwell_seconds,
            "train_headway_seconds": request.scenario.train_headway_seconds,
            "initial_train_offset_seconds": (request.scenario.initial_train_offset_seconds),
            "jupedsim_dt_seconds": request.scenario.jupedsim_dt_seconds,
            "jupedsim_iterations_per_tick": (request.scenario.jupedsim_iterations_per_tick),
            "jupedsim_desired_speed_mps": (request.scenario.jupedsim_desired_speed_mps),
            "jupedsim_free_speed_min_mps": (request.scenario.jupedsim_free_speed_min_mps),
            "jupedsim_free_speed_max_mps": (request.scenario.jupedsim_free_speed_max_mps),
            "jupedsim_agent_radius_units": (request.scenario.jupedsim_agent_radius_units),
            "jupedsim_clearance_multiplier": (request.scenario.jupedsim_clearance_multiplier),
            "movement_backend_name": request.scenario.movement_backend_name,
            "jupedsim_operational_model": (request.scenario.jupedsim_operational_model),
        },
        "metro_runtime_fingerprint": expected_runtime_cohort["metro_runtime_fingerprint"],
        "analysis_runtime_fingerprint": expected_runtime_cohort["analysis_runtime_fingerprint"],
        "residence_evidence_artifacts": residence_evidence_artifacts,
        "metrics": {
            "scheduled_entry": metrics.get("alignment_scheduled_entry_persons"),
            "spawned_entry": metrics.get("spawned_entry_persons"),
            "pending_entry": metrics.get("alignment_pending_entry_persons"),
            "scheduled_exit": metrics.get("alignment_scheduled_exit_persons"),
            "spawned_exit": metrics.get("spawned_exit_persons"),
            "pending_exit": metrics.get("alignment_pending_exit_persons"),
            "admission_exhausted": spatial.get("capacity.admission_exhausted", 0),
            "deferred_downstream": spatial.get(
                "passenger_demand_deferred_without_downstream_admission", 0
            ),
            "dynamic_blocked": spatial.get("placement.dynamic_blocked", 0)
            + spatial.get("spawn.dynamic_blocked", 0),
            "dropped": metrics.get("alignment_source_dropped_persons"),
            "conserved": metrics.get("alignment_source_demand_conserved"),
            "passenger_liveness_violation": audits.get("passenger_liveness_violation", 0),
            "entry_admission_attempts": metrics.get("alignment_entry_admission_attempts"),
            "entry_admission_exhausted_ratio": metrics.get(
                "alignment_entry_admission_exhausted_ratio"
            ),
            "exit_admission_attempts": metrics.get("alignment_exit_admission_attempts"),
            "exit_admission_exhausted_ratio": metrics.get(
                "alignment_exit_admission_exhausted_ratio"
            ),
            "placement_retry_attempts": metrics.get("alignment_placement_retry_attempts"),
            "placement_retry_ratio": metrics.get("alignment_placement_retry_ratio"),
            "waiting_capacity_retry_attempts": metrics.get(
                "alignment_waiting_capacity_retry_attempts"
            ),
            "waiting_capacity_retry_ratio": metrics.get("alignment_waiting_capacity_retry_ratio"),
            "stalled_platform_parking_attempts": metrics.get(
                "alignment_stalled_platform_parking_attempts"
            ),
            "stalled_platform_parking_ratio": metrics.get(
                "alignment_stalled_platform_parking_ratio"
            ),
            "replanned_stalled_region_approach_attempts": audits.get(
                "passenger_replanned_stalled_region_approach", 0
            ),
            "replanned_stalled_region_approach_ratio": (
                audits.get("passenger_replanned_stalled_region_approach", 0)
                / max(
                    1,
                    int(metrics.get("spawned_entry_persons", 0) or 0)
                    + int(metrics.get("spawned_exit_persons", 0) or 0),
                )
            ),
            "service_time_attribution": metrics.get("alignment_service_time_attribution"),
        },
        "stalled_replan_attribution": {
            "total": sum(replan_by_passenger.values()),
            "by_passenger": dict(
                sorted(replan_by_passenger.items(), key=lambda item: (-item[1], item[0]))
            ),
        },
        "terminal_admission_owners": _terminal_admission_owner_diagnostics(runtime),
        "source_integrity_gate": evaluate_source_integrity_gate(metrics),
        "dynamic_blocked_attribution": {
            "total": sum(blocked_regions.values()),
            "by_code": dict(sorted(blocked_codes.items())),
            "by_region": dict(
                sorted(blocked_regions.items(), key=lambda item: (-item[1], item[0]))
            ),
            "top3_regions": [
                {"region": region, "count": count}
                for region, count in blocked_regions.most_common(3)
            ],
        },
        "residence": {
            flow: {
                "n": metrics.get(f"alignment_{flow}_token_residence_n"),
                "p50_steps": metrics.get(
                    f"alignment_{flow}_token_residence_censor_aware_p50_steps"
                ),
                "p90_steps": metrics.get(
                    f"alignment_{flow}_token_residence_censor_aware_p90_steps"
                ),
                "p99_steps": metrics.get(
                    f"alignment_{flow}_token_residence_censor_aware_p99_steps"
                ),
                "lower_bound_p99_steps": metrics.get(
                    f"alignment_{flow}_token_residence_lower_bound_p99_steps"
                ),
                "samples_steps": metrics.get(f"alignment_{flow}_token_residence_steps"),
                "completed_samples_steps": metrics.get(
                    f"alignment_{flow}_token_completed_residence_steps"
                ),
                "censored_samples_steps": metrics.get(
                    f"alignment_{flow}_token_censored_residence_steps"
                ),
                "completed_n": metrics.get(f"alignment_{flow}_token_completed_residence_n"),
                "censored_n": metrics.get(f"alignment_{flow}_token_censored_residence_n"),
                "abnormal_residences": metrics.get(f"alignment_{flow}_token_abnormal_residences"),
            }
            for flow in ("entry", "exit")
        },
    }


def _residence_artifact(control_arm: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "alignment_round25_residence_time.v1",
        "status": "measured",
        "arm": "enlarged_capacity_control",
        "definition": {
            "start": "source group publication after admission credit acquisition",
            "end": "first downstream gate stage completion releases the admission credit",
            "unit": "simulation_steps",
            "tick_seconds": 1,
        },
        "right_censoring": (
            "owners still active at the horizon are lifecycle-right-censored; a requested "
            "nearest-rank percentile is null unless at least that rank completed, while "
            "lower_bound_p99_steps separately reports the mixed completed/active-age bound"
        ),
        "entry": control_arm["residence"]["entry"],
        "exit": control_arm["residence"]["exit"],
        "service_time_attribution": control_arm["metrics"].get("service_time_attribution"),
        "design_sha256": control_arm["design_sha256"],
        "scene_config_sha256": control_arm["scene_config_sha256"],
        "metro_runtime_fingerprint": control_arm["metro_runtime_fingerprint"],
        "analysis_runtime_fingerprint": control_arm["analysis_runtime_fingerprint"],
        "evidence_scope": control_arm["admission_evidence_scope"],
    }
    payload["artifact_sha256"] = canonical_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--residence-output", type=Path)
    parser.add_argument("--steps", type=int, default=120)
    parser.add_argument("--enlarged-capacity", type=int, default=100_000)
    parser.add_argument("--entry-capacity", type=int)
    parser.add_argument("--exit-capacity", type=int)
    parser.add_argument("--require-tripwire", action="store_true")
    parser.add_argument("--demand-minutes", type=int)
    parser.add_argument("--control-only", action="store_true")
    parser.add_argument("--include-round24-baseline", action="store_true")
    args = parser.parse_args()

    demand_minutes = (
        int(args.demand_minutes)
        if args.demand_minutes is not None
        else min(2, max(1, (args.steps + 59) // 60))
    )
    base = replace(
        build_scene_config("platform_boarding"),
        minutes=max(demand_minutes + 1, (args.steps + 59) // 60),
        demand_minutes=demand_minutes,
    )
    runtime_cohort = _runtime_cohort()
    runtime_cohort_sha256 = canonical_sha256(runtime_cohort)
    if args.control_only:
        entry_capacity = (
            int(args.entry_capacity)
            if args.entry_capacity is not None
            else int(args.enlarged_capacity)
        )
        exit_capacity = (
            int(args.exit_capacity)
            if args.exit_capacity is not None
            else int(args.enlarged_capacity)
        )
        control = _arm(
            replace(
                base,
                entry_admission_token_capacity=entry_capacity,
                exit_admission_token_capacity=exit_capacity,
            ),
            steps=args.steps,
            mode=(
                "enlarged_capacity_control"
                if entry_capacity == args.enlarged_capacity
                and exit_capacity == args.enlarged_capacity
                else "configured_capacity_probe"
            ),
            expected_runtime_cohort=runtime_cohort,
            measurement_bypass_preflight=True,
        )
        report = {
            "schema_version": "alignment_round25_residence_probe.v1",
            "status": control["source_integrity_gate"]["status"],
            "runtime_cohort": runtime_cohort,
            "runtime_cohort_sha256": runtime_cohort_sha256,
            "arm": control,
        }
        _require_runtime_cohort(runtime_cohort, phase="control-only:pre-write")
        report["artifact_sha256"] = canonical_sha256(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(args.output, report)
        if args.residence_output is not None:
            _require_runtime_cohort(runtime_cohort, phase="control-only:residence-write")
            args.residence_output.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(args.residence_output, _residence_artifact(control))
        print(json.dumps({"status": report["status"], "output": str(args.output)}))
        return 0 if report["status"] == "pass" else 1
    base_request, _ = build_metro_request(base)
    sizing = alignment_entry_admission_preflight(base_request.scenario)
    required = {str(flow["flow_id"]): int(flow["required_capacity"]) for flow in sizing["flows"]}
    finite_config = replace(
        base,
        entry_admission_token_capacity=required["entry"],
        exit_admission_token_capacity=required["exit"],
    )
    finite = _arm(
        finite_config,
        steps=args.steps,
        mode="finite",
        expected_runtime_cohort=runtime_cohort,
    )
    control = _arm(
        replace(
            base,
            entry_admission_token_capacity=args.enlarged_capacity,
            exit_admission_token_capacity=args.enlarged_capacity,
        ),
        steps=args.steps,
        mode="enlarged_capacity_control",
        expected_runtime_cohort=runtime_cohort,
    )
    report = build_two_arm_report(
        finite=finite,
        enlarged=control,
        controlled_fields=(
            "entry_admission_token_capacity",
            "exit_admission_token_capacity",
        ),
    )
    if args.require_tripwire:
        report["status"] = (
            "pass"
            if all(
                arm["source_integrity_gate"]["status"] == "pass" for arm in report["arms"].values()
            )
            else "fail"
        )
    report["runtime_cohort"] = runtime_cohort
    report["runtime_cohort_sha256"] = runtime_cohort_sha256
    if args.include_round24_baseline:
        report["historical_round24_baseline"] = _round24_historical_baseline()
    _require_runtime_cohort(runtime_cohort, phase="two-arm:pre-write")
    report["artifact_sha256"] = canonical_sha256(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(args.output, report)
    if args.residence_output is not None:
        _require_runtime_cohort(runtime_cohort, phase="two-arm:residence-write")
        args.residence_output.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(args.residence_output, _residence_artifact(control))
    print(json.dumps({"status": report["status"], "output": str(args.output)}))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
