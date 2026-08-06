from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LADDER_MANIFEST_SCHEMA_VERSION = "alignment_ladder_manifest.v1"
CONTROL_ARTIFACT_SCHEMA_VERSION = "alignment_control_run.v1"


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ArtifactRecord(StrictContract):
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def require_portable_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("artifact path must be a portable relative POSIX path")
        return value

    @field_validator("sha256")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("artifact sha256 must be lowercase hexadecimal")
        return value


class RuntimeCohort(StrictContract):
    scene_id: str
    base_scene_config_sha256: str
    design_sha256: str
    metro_runtime_fingerprint: dict[str, Any]
    analysis_runtime_fingerprint: dict[str, Any]
    cohort_sha256: str

    @classmethod
    def create(
        cls,
        *,
        scene_id: str,
        base_scene_config_sha256: str,
        design_sha256: str,
        metro_runtime_fingerprint: dict[str, Any],
        analysis_runtime_fingerprint: dict[str, Any],
    ) -> RuntimeCohort:
        values = {
            "scene_id": scene_id,
            "base_scene_config_sha256": base_scene_config_sha256,
            "design_sha256": design_sha256,
            "metro_runtime_fingerprint": metro_runtime_fingerprint,
            "analysis_runtime_fingerprint": analysis_runtime_fingerprint,
        }
        return cls(**values, cohort_sha256=canonical_sha256(values))

    @model_validator(mode="after")
    def require_self_consistent_hash(self) -> RuntimeCohort:
        values = self.model_dump(exclude={"cohort_sha256"})
        if canonical_sha256(values) != self.cohort_sha256:
            raise ValueError("runtime cohort hash does not match its frozen inputs")
        return self


class ControlEvidence(StrictContract):
    control_id: str
    role: Literal["ladder_rung", "qualification_control"]
    order_index: int = Field(ge=0)
    status: Literal["pass", "qualification_pass"]
    control_spec_sha256: str
    scene_config_sha256: str
    control_artifact: ArtifactRecord
    simulation_manifest: ArtifactRecord
    saturated_flow_artifact: ArtifactRecord | None = None

    @model_validator(mode="after")
    def require_qualifier_artifact(self) -> ControlEvidence:
        has_saturated = self.saturated_flow_artifact is not None
        if (self.role == "qualification_control") != has_saturated:
            raise ValueError("only a qualification control carries saturated-flow evidence")
        expected_status = (
            "qualification_pass" if self.role == "qualification_control" else "pass"
        )
        if self.status != expected_status:
            raise ValueError(f"{self.role} status must be {expected_status!r}")
        return self


class ControlRunArtifact(StrictContract):
    schema_version: Literal["alignment_control_run.v1"]
    run_id: str
    profile_id: str
    profile_sha256: str
    control_id: str
    control_spec_sha256: str
    role: Literal["ladder_rung", "qualification_control"]
    order_index: int = Field(ge=0)
    status: Literal["pass", "qualification_pass"]
    runtime_cohort: RuntimeCohort
    scene_config_sha256: str
    simulation_manifest: ArtifactRecord
    saturated_flow_artifact: ArtifactRecord | None = None
    runner_provenance: dict[str, Any]

    @model_validator(mode="after")
    def require_qualifier_artifact(self) -> ControlRunArtifact:
        has_saturated = self.saturated_flow_artifact is not None
        if (self.role == "qualification_control") != has_saturated:
            raise ValueError("only a qualification control carries saturated-flow evidence")
        expected_status = (
            "qualification_pass" if self.role == "qualification_control" else "pass"
        )
        if self.status != expected_status:
            raise ValueError(f"{self.role} status must be {expected_status!r}")
        return self


class LadderManifest(StrictContract):
    schema_version: Literal["alignment_ladder_manifest.v1"]
    ladder_id: str
    run_id: str
    scene_id: str
    profile_id: str
    profile_sha256: str
    runtime_cohort: RuntimeCohort
    controls: tuple[ControlEvidence, ...]
    publication_control_id: str
    runner_provenance: dict[str, Any]
    step5_implementation_gate: Literal["pass"]
    release_eligible: Literal[False] = False

    @model_validator(mode="after")
    def require_complete_ordered_ladder(self) -> LadderManifest:
        if not self.controls:
            raise ValueError("ladder manifest requires control evidence")
        ids = [control.control_id for control in self.controls]
        if len(ids) != len(set(ids)):
            raise ValueError("ladder control ids must be unique")
        if [control.order_index for control in self.controls] != list(range(len(ids))):
            raise ValueError("ladder controls must be contiguous and ordered")
        publication = self.controls[-1]
        if publication.control_id != self.publication_control_id:
            raise ValueError("publication control must be the final control")
        if publication.role != "ladder_rung":
            raise ValueError("qualification controls cannot publish simulation v5")
        if self.scene_id != self.runtime_cohort.scene_id:
            raise ValueError("ladder scene differs from its runtime cohort")
        return self


def ladder_manifest_json_schema() -> dict[str, Any]:
    return LadderManifest.model_json_schema()
