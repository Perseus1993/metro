from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from uuid import uuid4

from .formal_contract import ArtifactRecord


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_record(path: Path, *, record_parent: Path) -> ArtifactRecord:
    resolved = path.resolve()
    parent = record_parent.resolve()
    if not resolved.is_relative_to(parent):
        raise ValueError("formal artifacts must stay below the active manifest directory")
    return ArtifactRecord(
        path=resolved.relative_to(parent).as_posix(),
        sha256=file_sha256(resolved),
        size_bytes=resolved.stat().st_size,
    )


def write_content_addressed_json(
    directory: Path,
    *,
    stem: str,
    payload: dict,
    record_parent: Path,
) -> tuple[Path, ArtifactRecord]:
    content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    sha256 = hashlib.sha256(content).hexdigest()
    final = directory / f"{stem}.sha256-{sha256}.json"
    directory.mkdir(parents=True, exist_ok=True)
    if final.exists():
        if final.read_bytes() != content:
            raise RuntimeError(f"content-addressed JSON target disagrees with its hash: {final}")
        return final, artifact_record(final, record_parent=record_parent)
    staged = directory / f".{stem}.{uuid4().hex}.staging.json"
    try:
        with staged.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, final)
    finally:
        if staged.exists():
            staged.unlink()
    return final, artifact_record(final, record_parent=record_parent)


def verify_artifact_records(records: Iterable[ArtifactRecord], *, parent: Path) -> None:
    root = parent.resolve()
    for record in records:
        path = (root / record.path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"formal publication artifact is missing: {record.path}")
        if path.stat().st_size != record.size_bytes or file_sha256(path) != record.sha256:
            raise ValueError(f"formal publication artifact hash mismatch: {record.path}")


def publish_active_manifest(
    *,
    active_manifest: Path,
    payload: dict,
    referenced_artifacts: Iterable[ArtifactRecord],
    fingerprints_match: Callable[[], bool],
) -> None:
    """Atomically switch the only mutable pointer after all immutable evidence exists."""

    verify_artifact_records(referenced_artifacts, parent=active_manifest.parent)
    if not fingerprints_match():
        raise RuntimeError("runtime cohort changed before formal publication")
    content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    token = uuid4().hex
    staged = active_manifest.with_name(f".{active_manifest.name}.{token}.staging.json")
    backup = active_manifest.with_name(f".{active_manifest.name}.{token}.previous.json")
    had_manifest = active_manifest.exists()
    published = False
    preserve_backup = False
    try:
        active_manifest.parent.mkdir(parents=True, exist_ok=True)
        with staged.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if not fingerprints_match():
            raise RuntimeError("runtime cohort changed before active manifest switch")
        if had_manifest:
            shutil.copy2(active_manifest, backup)
        os.replace(staged, active_manifest)
        published = True
        if not fingerprints_match():
            raise RuntimeError("runtime cohort changed during active manifest switch")
        if backup.exists():
            backup.unlink()
    except BaseException:
        if published:
            try:
                if had_manifest and backup.exists():
                    os.replace(backup, active_manifest)
                elif active_manifest.exists():
                    active_manifest.unlink()
            except OSError as rollback_error:
                preserve_backup = True
                raise RuntimeError(
                    "formal publication failed and rollback failed; recovery manifest retained "
                    f"at {backup}"
                ) from rollback_error
        raise
    finally:
        if staged.exists():
            staged.unlink()
        if backup.exists() and not preserve_backup:
            backup.unlink()
