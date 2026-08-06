from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.formal_contract import canonical_sha256

ROUND25_REQUIRED_ARTIFACTS = (
    "T0_two_arm_baseline.json",
    "T1_measurement_900.json",
    "T1_residence_time.json",
    "T2_diff_summary.json",
    "T3_preflight_sizing.json",
    "T4_gate_definition.json",
    "T5_tripwire_120.json",
    "T6_dynamic_blocked_hist.json",
    "T8_ladder_240.json",
    "T9_debt_triage.json",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"evidence artifact must be a JSON object: {path}")
    return payload


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_artifact_self_hash(path: Path) -> tuple[dict[str, Any], str]:
    payload = _read_json(path)
    claimed = str(payload.get("artifact_sha256", ""))
    unsigned = dict(payload)
    unsigned.pop("artifact_sha256", None)
    actual = canonical_sha256(unsigned)
    if not claimed or claimed != actual:
        raise ValueError(
            f"artifact canonical hash mismatch for {path}: claimed={claimed!r}, actual={actual}"
        )
    return payload, actual


def write_round25_evidence_manifest(
    output_dir: Path,
    *,
    required_artifacts: tuple[str, ...] = ROUND25_REQUIRED_ARTIFACTS,
) -> Path:
    output_dir = output_dir.resolve()
    immutable_dir = output_dir / "immutable"
    immutable_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for alias in required_artifacts:
        alias_path = output_dir / alias
        payload, artifact_sha256 = verify_artifact_self_hash(alias_path)
        immutable_name = f"{alias_path.stem}.{artifact_sha256}.json"
        immutable_path = immutable_dir / immutable_name
        write_json_atomic(immutable_path, payload)
        entries.append(
            {
                "alias": alias,
                "immutable_path": immutable_path.relative_to(output_dir).as_posix(),
                "schema_version": payload.get("schema_version"),
                "status": payload.get("status"),
                "artifact_sha256": artifact_sha256,
                "file_sha256": _file_sha256(immutable_path),
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": "alignment_round25_evidence_manifest.v1",
        "round": 25,
        "status": "pass",
        "trust_model": (
            "Aliases and canonical artifact hashes are anchored by immutable, "
            "content-addressed copies. Verification against an explicit Git revision "
            "provides the external trust root for the coordinated-rewrite threat."
        ),
        "required_artifacts": list(required_artifacts),
        "entries": entries,
    }
    manifest["artifact_sha256"] = canonical_sha256(manifest)
    path = output_dir / "round25_evidence_manifest.json"
    write_json_atomic(path, manifest)
    verify_round25_evidence_manifest(path)
    return path


def verify_round25_evidence_manifest(path: Path) -> dict[str, Any]:
    manifest, _manifest_hash = verify_artifact_self_hash(path)
    output_dir = path.resolve().parent
    aliases = tuple(str(name) for name in manifest.get("required_artifacts", []))
    entries = list(manifest.get("entries", []))
    if len(entries) != len(aliases) or tuple(
        str(entry.get("alias")) for entry in entries
    ) != aliases:
        raise ValueError("round25 evidence manifest entries do not match required aliases")
    for entry in entries:
        alias_path = output_dir / str(entry["alias"])
        immutable_relative = Path(str(entry["immutable_path"]))
        immutable_path = (output_dir / immutable_relative).resolve()
        if immutable_relative.is_absolute() or not immutable_path.is_relative_to(output_dir):
            raise ValueError("round25 evidence manifest contains a non-portable path")
        alias_payload, alias_hash = verify_artifact_self_hash(alias_path)
        immutable_payload, immutable_hash = verify_artifact_self_hash(immutable_path)
        if alias_hash != entry["artifact_sha256"] or immutable_hash != alias_hash:
            raise ValueError(f"round25 evidence alias/immutable hash mismatch: {alias_path}")
        if alias_payload != immutable_payload:
            raise ValueError(f"round25 evidence alias differs from immutable copy: {alias_path}")
        if _file_sha256(immutable_path) != entry["file_sha256"]:
            raise ValueError(f"round25 immutable evidence byte hash mismatch: {immutable_path}")
    return manifest


def verify_round25_evidence_git_anchor(
    path: Path,
    *,
    revision: str = "HEAD",
) -> tuple[dict[str, Any], str]:
    """Verify the evidence set byte-for-byte against a reviewed Git revision."""

    manifest = verify_round25_evidence_manifest(path)
    resolved_path = path.resolve()
    root_result = subprocess.run(
        ["git", "-C", str(resolved_path.parent), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if root_result.returncode != 0:
        raise ValueError("round25 evidence is not inside a Git worktree")
    repo_root = Path(root_result.stdout.strip()).resolve()
    revision_result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", f"{revision}^{{commit}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if revision_result.returncode != 0:
        raise ValueError(f"round25 evidence Git revision is invalid: {revision}")
    resolved_revision = revision_result.stdout.strip()
    output_dir = resolved_path.parent
    targets = [resolved_path]
    for entry in manifest["entries"]:
        targets.extend(
            (
                output_dir / str(entry["alias"]),
                output_dir / str(entry["immutable_path"]),
            )
        )
    for target in targets:
        resolved_target = target.resolve()
        if not resolved_target.is_relative_to(repo_root):
            raise ValueError(f"round25 evidence target escapes Git worktree: {target}")
        relative = resolved_target.relative_to(repo_root).as_posix()
        blob_result = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{resolved_revision}:{relative}"],
            check=False,
            capture_output=True,
        )
        if blob_result.returncode != 0:
            raise ValueError(
                f"round25 evidence target is absent from Git revision "
                f"{resolved_revision}: {relative}"
            )
        if resolved_target.read_bytes() != blob_result.stdout:
            raise ValueError(
                f"round25 evidence differs from Git revision "
                f"{resolved_revision}: {relative}"
            )
    return manifest, resolved_revision


__all__ = [
    "ROUND25_REQUIRED_ARTIFACTS",
    "verify_artifact_self_hash",
    "verify_round25_evidence_git_anchor",
    "verify_round25_evidence_manifest",
    "write_round25_evidence_manifest",
]
