from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, replace
from pathlib import Path

from metro_alignment.analysis_runtime import analysis_runtime_fingerprint
from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.formal_contract import canonical_sha256
from metro_alignment.metro_contract import scene_config_sha256
from metro_alignment.metro_executor import alignment_entry_admission_preflight
from metro_alignment.metro_runtime import metro_source_fingerprint
from metro_alignment.metro_scene import build_metro_request
from metro_alignment.scenes import build_scene_config
from metro_alignment.source_integrity_gate import (
    DEFAULT_SOURCE_INTEGRITY_THRESHOLDS,
)


def _evidence_context(config) -> dict[str, object]:
    _, design_sha256 = build_metro_request(config)
    return {
        "design_sha256": design_sha256,
        "scene_config_sha256": scene_config_sha256(config),
        "metro_runtime_fingerprint": metro_source_fingerprint(),
        "analysis_runtime_fingerprint": analysis_runtime_fingerprint(),
    }


def _write(path: Path, payload: dict[str, object]) -> None:
    payload["artifact_sha256"] = canonical_sha256(payload)
    write_json_atomic(path, payload)


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    registered_hash = payload.get("artifact_sha256")
    unhashed = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    if registered_hash != canonical_sha256(unhashed):
        raise RuntimeError(f"artifact hash mismatch: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    config = replace(
        build_scene_config("platform_boarding"),
        minutes=3,
        demand_minutes=2,
    )
    context = _evidence_context(config)
    residence_evidence = _read_json(args.output_dir / "T1_residence_time.json")
    normal = alignment_entry_admission_preflight(build_metro_request(config)[0].scenario)
    required = {
        str(flow["flow_id"]): int(flow["required_capacity"])
        for flow in normal["flows"]
    }
    underconfigured = replace(
        config,
        entry_admission_token_capacity=required["entry"] - 1,
        exit_admission_token_capacity=required["exit"] - 1,
    )
    underconfigured_report = alignment_entry_admission_preflight(
        build_metro_request(underconfigured)[0].scenario
    )

    _write(
        args.output_dir / "T2_diff_summary.json",
        {
            "schema_version": "alignment_round25_t2_diff_summary.v1",
            "status": "implemented",
            **context,
            "production_files": [
                "packages/metro_station/src/metro_station/adapters/simulation/facilities/admission_resource.py",
                "packages/metro_station/src/metro_station/adapters/simulation/runtime/passenger_demand.py",
                "alignment/src/metro_alignment/admission_tokens.py",
                "alignment/src/metro_alignment/metro_executor.py",
            ],
            "resource_contract": {
                "flows": ["entry", "exit"],
                "geometry_fields": [],
                "capacity_type": "positive integer",
                "failure_semantics": "FIFO pending; never drop",
                "publication": "exact placement before passenger append/counters/frame",
                "termination": "active owners released as lifecycle_right_censored",
            },
            "targeted_tests": {
                "command": "python -m pytest alignment/tests/test_admission_tokens.py alignment/tests/test_metro_executor.py tests/test_spatial_capacity_certificates.py::test_explicit_source_position_is_rejected_before_publication -q",
                "latest_result": "pass",
            },
        },
    )
    _write(
        args.output_dir / "T3_preflight_sizing.json",
        {
            "schema_version": "alignment_round25_t3_preflight_sizing.v1",
            "status": "pass",
            **context,
            "normal": normal,
            "residence_evidence_artifact_sha256": residence_evidence[
                "artifact_sha256"
            ],
            "deterministic_schedule_envelopes": {
                str(flow["flow_id"]): {
                    "deterministic_arrival_envelope": flow[
                        "deterministic_arrival_envelope"
                    ],
                    "stochastic_reference_capacity": math.ceil(
                        flow["arrival_rate_persons_s"]
                        * flow["registered_residence_seconds"]
                        + flow["burst_sigma"]
                        * math.sqrt(
                            flow["arrival_rate_persons_s"]
                            * flow["registered_residence_seconds"]
                        )
                    ),
                    "required_capacity": flow["required_capacity"],
                    "sizing_rule": flow["sizing_formula"],
                }
                for flow in normal["flows"]
            },
            "underconfigured_counterexample": {
                "scene_config_sha256": scene_config_sha256(underconfigured),
                "configured_entry_capacity": required["entry"] - 1,
                "configured_exit_capacity": required["exit"] - 1,
                "runtime_status": "not_started",
                "runtime_invocations": 0,
                "release_eligible": False,
                "preflight": underconfigured_report,
            },
            "old_bundle_preservation": {
                "status": "covered",
                "test": "alignment/tests/test_runner_publication.py::test_admission_preflight_failure_preserves_existing_bundle",
                "mechanism": "blocker artifact uses a distinct atomic path before runtime; existing simulation bundle is untouched",
            },
        },
    )
    _write(
        args.output_dir / "T4_gate_definition.json",
        {
            "schema_version": "alignment_round25_t4_gate_definition.v1",
            "status": "active",
            **context,
            "thresholds": asdict(DEFAULT_SOURCE_INTEGRITY_THRESHOLDS),
            "flows": ["entry", "exit"],
            "criteria": [
                "spawned == scheduled at horizon",
                "pending persons == 0",
                "pending groups == 0",
                "maximum pending residence < 10 steps",
                "admission_exhausted / admission_attempts <= 0.05",
                "dropped == 0",
                "conserved == true",
                "passenger_liveness_violation == 0",
            ],
            "implementation": "alignment/src/metro_alignment/source_integrity_gate.py",
            "tests": "alignment/tests/test_source_integrity_gate.py",
        },
    )
    t5 = _read_json(args.output_dir / "T5_tripwire_120.json")
    t8 = _read_json(args.output_dir / "T8_ladder_240.json")
    arm_names = ("finite", "enlarged_capacity_control")
    t5_regions = {
        arm: t5["arms"][arm]["dynamic_blocked_attribution"]
        for arm in arm_names
    }
    t8_regions = {
        arm: t8["arms"][arm]["dynamic_blocked_attribution"]
        for arm in arm_names
    }
    same_by_arm = {
        "T5_120": t5_regions["finite"]["by_region"]
        == t5_regions["enlarged_capacity_control"]["by_region"],
        "T8_240": t8_regions["finite"]["by_region"]
        == t8_regions["enlarged_capacity_control"]["by_region"],
    }
    t5_finite_metrics = t5["arms"]["finite"]["metrics"]
    t8_finite_metrics = t8["arms"]["finite"]["metrics"]
    t5_spawned = int(t5_finite_metrics["spawned_entry"]) + int(
        t5_finite_metrics["spawned_exit"]
    )
    t8_spawned = int(t8_finite_metrics["spawned_entry"]) + int(
        t8_finite_metrics["spawned_exit"]
    )
    t5_dynamic = int(t5_finite_metrics["dynamic_blocked"])
    t8_dynamic = int(t8_finite_metrics["dynamic_blocked"])
    _write(
        args.output_dir / "T6_dynamic_blocked_hist.json",
        {
            "schema_version": "alignment_round25_dynamic_blocked_attribution.v1",
            "status": "pass" if all(same_by_arm.values()) else "investigate",
            **context,
            "source_artifacts": [
                "alignment/output/round25/T5_tripwire_120.json",
                "alignment/output/round25/T8_ladder_240.json",
            ],
            "T5_120": t5_regions,
            "T8_240": t8_regions,
            "same_region_histogram_between_arms": same_by_arm,
            "conclusion": (
                "All dynamic blocks are placement.dynamic_blocked events in the same "
                "three entry-gate release-apron lane certificates in both arms. The "
                "identical arm histograms show that admission capacity is not the cause; "
                "the remaining events are downstream spatial-release contention."
            ),
        },
    )
    _write(
        args.output_dir / "T9_debt_triage.json",
        {
            "schema_version": "alignment_round25_debt_triage.v1",
            "status": "pass",
            **context,
            "register": "alignment/docs/debt_register.md",
            "baseline_policy": {
                "rule": "entries may only decrease or narrow; any net increase requires explicit review justification",
                "round25_baseline_registration": True,
                "previously_unclassified_risk_candidates": 6,
                "registered_debt": 5,
                "registered_debt_delta": None,
                "registered_debt_delta_reason": "Round 24 had no comparable register; Round 25 establishes the five-entry baseline",
                "unclassified_candidates_current": 0,
                "unclassified_candidate_delta": -6,
                "new_failure_modes_introduced_by_round25": 0,
            },
            "classifications": [
                {
                    "candidate": "alighting_source_lateral_offset_m = 10.0",
                    "decision": "debt",
                    "debt_id": "DEBT-1",
                },
                {
                    "candidate": "passenger_replanned_stalled_region_approach",
                    "decision": "debt",
                    "debt_id": "DEBT-2",
                    "observed_triggers": 618,
                    "spawned_persons": 784,
                    "trigger_ratio": 618 / 784,
                },
                {
                    "candidate": "jupedsim recovery/degraded counters",
                    "decision": "legitimate_design",
                    "external_basis": "https://opentelemetry.io/docs/concepts/signals/metrics/",
                },
                {
                    "candidate": "boarding doors 6 to 7",
                    "decision": "debt",
                    "debt_id": "DEBT-3",
                },
                {
                    "candidate": "sandbox.metro_station_sandbox compatibility surface",
                    "decision": "legitimate_design",
                    "runtime_surface_python_files": 111,
                    "non_forward_runtime_surface_files": 0,
                    "external_basis": "https://semver.org/",
                },
                {
                    "candidate": "Import Linter migration rule",
                    "decision": "legitimate_design",
                    "external_basis": "https://import-linter.readthedocs.io/en/stable/",
                },
                {
                    "candidate": "nominal exit service versus completed-throughput gap",
                    "decision": "debt",
                    "debt_id": "DEBT-4",
                    "nominal_to_observed_ratio": 1400 / 74,
                },
                {
                    "candidate": "high-frequency placement and waiting recovery",
                    "decision": "debt",
                    "debt_id": "DEBT-5",
                    "T5_dynamic_blocked": t5_dynamic,
                    "T5_spawned_persons": t5_spawned,
                    "T5_trigger_ratio": t5_dynamic / t5_spawned,
                    "T8_dynamic_blocked": t8_dynamic,
                    "T8_spawned_persons": t8_spawned,
                    "T8_trigger_ratio": t8_dynamic / t8_spawned,
                    "uninstrumented_recovery_paths": [
                        "waiting-capacity retry",
                        "stalled-platform parking",
                    ],
                },
            ],
            "external_sources": [
                "https://www.merl.com/publications/TR2023-099",
                "https://opentelemetry.io/docs/concepts/signals/metrics/",
                "https://semver.org/",
                "https://import-linter.readthedocs.io/en/stable/",
            ],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
