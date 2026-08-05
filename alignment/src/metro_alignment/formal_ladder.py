from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from .formal_contract import (
    CONTROL_ARTIFACT_SCHEMA_VERSION,
    LADDER_MANIFEST_SCHEMA_VERSION,
    ArtifactRecord,
    ControlEvidence,
    ControlRunArtifact,
    LadderManifest,
    RuntimeCohort,
)
from .formal_profiles import FormalControlProfile, FormalControlSpec
from .formal_publication import (
    artifact_record,
    publish_active_manifest,
    write_content_addressed_json,
)
from .saturated_flow import build_saturated_flow_artifact


@dataclass(frozen=True)
class FormalControlExecution:
    control: FormalControlSpec
    canonical_path: Path
    manifest_path: Path
    trace_path: Path
    scene_config_sha256: str
    design_sha256: str
    metro_runtime_fingerprint: dict[str, Any]
    analysis_runtime_fingerprint: dict[str, Any]


@dataclass(frozen=True)
class FormalLadderResult:
    active_manifest_path: Path
    ladder_manifest_path: Path
    ladder_manifest: LadderManifest


def execute_final_ladder(
    *,
    profile: FormalControlProfile,
    output: Path,
    base_scene_config_sha256: str,
    design_sha256: str,
    metro_runtime_fingerprint: dict[str, Any],
    analysis_runtime_fingerprint: dict[str, Any],
    run_control: Callable[[FormalControlSpec, Path], FormalControlExecution],
    current_fingerprints: Callable[[], tuple[dict[str, Any], dict[str, Any]]],
) -> FormalLadderResult:
    if profile.publication_scope != "active_simulation_v5":
        raise ValueError("final ladder executor requires an active-publication profile")
    if profile.publication_control_id is None:
        raise ValueError("final ladder profile is missing its publication control")

    active_manifest = output.parent / f"{profile.scene_id}_simulated.json"
    run_id = uuid4().hex
    # Bound path length so content-addressed trace names remain portable on
    # Windows hosts that still enforce MAX_PATH.
    run_root = output.parent / "ladder" / run_id
    evidence_root = run_root / "evidence"
    cohort = RuntimeCohort.create(
        scene_id=profile.scene_id,
        base_scene_config_sha256=base_scene_config_sha256,
        design_sha256=design_sha256,
        metro_runtime_fingerprint=metro_runtime_fingerprint,
        analysis_runtime_fingerprint=analysis_runtime_fingerprint,
    )
    provenance = {
        "mode": "formal_control_profile",
        "runner": "scripts/run_alignment_scene.py",
        "profile_id": profile.profile_id,
        "profile_sha256": profile.sha256,
        "trace_replay": False,
        "manual_model_step": False,
        "diagnostic_input_reused": False,
    }
    evidence: list[ControlEvidence] = []
    executions: dict[str, FormalControlExecution] = {}
    saturated_record: ArtifactRecord | None = None

    for index, control in enumerate(profile.controls):
        control_output = run_root / f"{index:02d}-{control.control_id}" / "run.parquet"
        execution = run_control(control, control_output)
        _require_execution_cohort(execution, cohort)
        executions[control.control_id] = execution
        simulation_record = artifact_record(
            execution.manifest_path,
            record_parent=active_manifest.parent,
        )
        qualifier_record = None
        if control.saturated_flow is not None:
            trajectory = pd.read_parquet(execution.canonical_path)
            trace_record = artifact_record(
                execution.trace_path,
                record_parent=active_manifest.parent,
            )
            saturated = build_saturated_flow_artifact(
                scene_id=profile.scene_id,
                control_id=control.control_id,
                trajectory=trajectory,
                registration=control.saturated_flow,
                runtime_cohort=cohort,
                source_movement_trace=trace_record,
            )
            _, qualifier_record = write_content_addressed_json(
                evidence_root,
                stem="saturated-flow",
                payload=saturated.model_dump(mode="json"),
                record_parent=active_manifest.parent,
            )
            saturated_record = qualifier_record
            if saturated.gate_status != "pass":
                raise RuntimeError(
                    "preregistered saturated-flow gate failed; refusing remaining ladder controls"
                )

        control_status = (
            "pass" if control.require_final_acceptance else "qualification_pass"
        )
        control_artifact = ControlRunArtifact(
            schema_version=CONTROL_ARTIFACT_SCHEMA_VERSION,
            run_id=run_id,
            profile_id=profile.profile_id,
            profile_sha256=profile.sha256,
            control_id=control.control_id,
            control_spec_sha256=control.sha256,
            role=control.role,
            order_index=index,
            status=control_status,
            runtime_cohort=cohort,
            scene_config_sha256=execution.scene_config_sha256,
            simulation_manifest=simulation_record,
            saturated_flow_artifact=qualifier_record,
            runner_provenance=provenance,
        )
        _, control_record = write_content_addressed_json(
            evidence_root,
            stem=f"control-{control.control_id}",
            payload=control_artifact.model_dump(mode="json"),
            record_parent=active_manifest.parent,
        )
        evidence.append(
            ControlEvidence(
                control_id=control.control_id,
                role=control.role,
                order_index=index,
                status=control_status,
                control_spec_sha256=control.sha256,
                scene_config_sha256=execution.scene_config_sha256,
                control_artifact=control_record,
                simulation_manifest=simulation_record,
                saturated_flow_artifact=qualifier_record,
            )
        )

    ladder = LadderManifest(
        schema_version=LADDER_MANIFEST_SCHEMA_VERSION,
        ladder_id=f"{profile.scene_id}:{profile.profile_id}:{run_id}",
        run_id=run_id,
        scene_id=profile.scene_id,
        profile_id=profile.profile_id,
        profile_sha256=profile.sha256,
        runtime_cohort=cohort,
        controls=tuple(evidence),
        publication_control_id=profile.publication_control_id,
        runner_provenance=provenance,
        step5_implementation_gate="pass",
        release_eligible=False,
    )
    ladder_path, ladder_record = write_content_addressed_json(
        evidence_root,
        stem="ladder-manifest",
        payload=ladder.model_dump(mode="json"),
        record_parent=active_manifest.parent,
    )
    publication_execution = executions[profile.publication_control_id]
    active_payload, mixed_artifacts = _active_mixed_payload(
        publication_execution,
        active_parent=active_manifest.parent,
    )
    if saturated_record is None:
        raise RuntimeError("final ladder completed without saturated-flow evidence")
    active_payload.update(
        {
            "runner_provenance": provenance,
            "formal_control_id": profile.publication_control_id,
            "ladder_manifest": ladder_record.model_dump(mode="json"),
            "saturated_flow_artifact": saturated_record.model_dump(mode="json"),
        }
    )
    all_records = [ladder_record, saturated_record, *mixed_artifacts]
    for item in evidence:
        all_records.extend((item.control_artifact, item.simulation_manifest))
    publish_active_manifest(
        active_manifest=active_manifest,
        payload=active_payload,
        referenced_artifacts=all_records,
        fingerprints_match=lambda: current_fingerprints()
        == (cohort.metro_runtime_fingerprint, cohort.analysis_runtime_fingerprint),
    )
    return FormalLadderResult(active_manifest, ladder_path, ladder)


def _require_execution_cohort(
    execution: FormalControlExecution,
    cohort: RuntimeCohort,
) -> None:
    if execution.design_sha256 != cohort.design_sha256:
        raise RuntimeError("formal control changed the frozen station design")
    if execution.metro_runtime_fingerprint != cohort.metro_runtime_fingerprint:
        raise RuntimeError("Metro runtime changed during the formal ladder")
    if execution.analysis_runtime_fingerprint != cohort.analysis_runtime_fingerprint:
        raise RuntimeError("alignment runtime changed during the formal ladder")


def _active_mixed_payload(
    execution: FormalControlExecution,
    *,
    active_parent: Path,
) -> tuple[dict[str, Any], tuple[ArtifactRecord, ...]]:
    payload = json.loads(execution.manifest_path.read_bytes())
    records = []
    for name, raw in payload.get("artifacts", {}).items():
        source = (execution.manifest_path.parent / str(raw.get("path", ""))).resolve()
        record = artifact_record(source, record_parent=active_parent)
        payload["artifacts"][name] = record.model_dump(mode="json")
        records.append(record)
    return payload, tuple(records)
