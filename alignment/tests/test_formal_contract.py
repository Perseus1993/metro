from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from metro_alignment.formal_contract import (
    ArtifactRecord,
    ControlEvidence,
    LadderManifest,
    RuntimeCohort,
    ladder_manifest_json_schema,
)


def _record(name: str) -> ArtifactRecord:
    return ArtifactRecord(path=name, sha256="a" * 64, size_bytes=1)


def _cohort() -> RuntimeCohort:
    return RuntimeCohort.create(
        scene_id="platform_boarding",
        base_scene_config_sha256="b" * 64,
        design_sha256="c" * 64,
        metro_runtime_fingerprint={"source_tree_sha256": "metro"},
        analysis_runtime_fingerprint={"content_sha256": "analysis"},
    )


def _manifest() -> LadderManifest:
    controls = (
        ControlEvidence(
            control_id="exit-only-350",
            role="ladder_rung",
            order_index=0,
            status="pass",
            control_spec_sha256="1" * 64,
            scene_config_sha256="2" * 64,
            control_artifact=_record("control-exit.json"),
            simulation_manifest=_record("exit.json"),
        ),
        ControlEvidence(
            control_id="entry-tail-saturated-flow",
            role="qualification_control",
            order_index=1,
            status="qualification_pass",
            control_spec_sha256="3" * 64,
            scene_config_sha256="4" * 64,
            control_artifact=_record("control-saturated.json"),
            simulation_manifest=_record("saturated.json"),
            saturated_flow_artifact=_record("saturated-flow.json"),
        ),
        ControlEvidence(
            control_id="mixed-600",
            role="ladder_rung",
            order_index=2,
            status="pass",
            control_spec_sha256="5" * 64,
            scene_config_sha256="6" * 64,
            control_artifact=_record("control-mixed.json"),
            simulation_manifest=_record("mixed.json"),
        ),
    )
    return LadderManifest(
        schema_version="alignment_ladder_manifest.v1",
        ladder_id="ladder",
        run_id="run",
        scene_id="platform_boarding",
        profile_id="alignment_step5_final.v1",
        profile_sha256="7" * 64,
        runtime_cohort=_cohort(),
        controls=controls,
        publication_control_id="mixed-600",
        runner_provenance={"mode": "formal_control_profile"},
        step5_implementation_gate="pass",
        release_eligible=False,
    )


def test_ladder_schema_is_strict_and_exportable() -> None:
    manifest = _manifest()
    schema = ladder_manifest_json_schema()
    assert schema["additionalProperties"] is False
    assert "runtime_cohort" in schema["required"]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        LadderManifest.model_validate({**manifest.model_dump(), "unexpected": True})


def test_checked_in_ladder_schema_matches_runtime_model() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "schemas"
        / "alignment_ladder_manifest.v1.schema.json"
    )
    assert json.loads(path.read_text(encoding="utf-8")) == ladder_manifest_json_schema()


def test_ladder_rejects_wrong_order_or_nonfinal_publication() -> None:
    payload = _manifest().model_dump()
    payload["controls"][1]["order_index"] = 4
    with pytest.raises(ValidationError, match="contiguous and ordered"):
        LadderManifest.model_validate(payload)

    payload = _manifest().model_dump()
    payload["publication_control_id"] = "exit-only-350"
    with pytest.raises(ValidationError, match="final control"):
        LadderManifest.model_validate(payload)


def test_ladder_rejects_mutated_runtime_cohort() -> None:
    payload = _manifest().model_dump()
    mutated = deepcopy(payload)
    mutated["runtime_cohort"]["design_sha256"] = "d" * 64
    with pytest.raises(ValidationError, match="cohort hash"):
        LadderManifest.model_validate(mutated)


@pytest.mark.parametrize("path", ["/absolute.json", "../escape.json", "a\\b.json"])
def test_artifact_records_require_portable_relative_paths(path: str) -> None:
    with pytest.raises(ValidationError, match="portable relative"):
        ArtifactRecord(path=path, sha256="a" * 64, size_bytes=1)
