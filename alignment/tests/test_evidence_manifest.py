from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from metro_alignment.evidence_manifest import (
    verify_round25_evidence_git_anchor,
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


def test_git_anchor_rejects_coordinated_manifest_rewrite(tmp_path: Path) -> None:
    output_dir = tmp_path / "alignment" / "output" / "round25"
    output_dir.mkdir(parents=True)
    _artifact(output_dir / "T0.json")
    manifest_path = write_round25_evidence_manifest(
        output_dir, required_artifacts=("T0.json",)
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "round25@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Round 25 test"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "anchor evidence"],
        cwd=tmp_path,
        check=True,
    )
    _manifest, revision = verify_round25_evidence_git_anchor(manifest_path)

    _artifact(output_dir / "T0.json", status="forged")
    write_round25_evidence_manifest(output_dir, required_artifacts=("T0.json",))
    verify_round25_evidence_manifest(manifest_path)
    with pytest.raises(ValueError, match="Git revision"):
        verify_round25_evidence_git_anchor(manifest_path, revision=revision)
