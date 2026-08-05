from __future__ import annotations

import json
from pathlib import Path

import pytest

from metro_alignment.evidence_manifest import (
    verify_round25_evidence_manifest,
    write_round25_evidence_manifest,
)
from metro_alignment.formal_contract import canonical_sha256


def _artifact(path: Path, *, status: str = "pass") -> None:
    payload = {"schema_version": "test.v1", "status": status, "value": 1}
    payload["artifact_sha256"] = canonical_sha256(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_manifest_anchors_alias_to_content_addressed_copy(tmp_path: Path) -> None:
    _artifact(tmp_path / "T0.json")

    manifest_path = write_round25_evidence_manifest(
        tmp_path, required_artifacts=("T0.json",)
    )
    manifest = verify_round25_evidence_manifest(manifest_path)

    immutable = tmp_path / manifest["entries"][0]["immutable_path"]
    assert immutable.name == f"T0.{manifest['entries'][0]['artifact_sha256']}.json"
    assert immutable.is_file()


def test_manifest_rejects_alias_rewrite_even_with_new_self_hash(tmp_path: Path) -> None:
    _artifact(tmp_path / "T0.json")
    manifest_path = write_round25_evidence_manifest(
        tmp_path, required_artifacts=("T0.json",)
    )
    _artifact(tmp_path / "T0.json", status="fail")

    with pytest.raises(ValueError, match="alias/immutable hash mismatch"):
        verify_round25_evidence_manifest(manifest_path)
