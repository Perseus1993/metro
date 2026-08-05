from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from metro_alignment.formal_contract import ArtifactRecord
from metro_alignment.formal_publication import publish_active_manifest


def _record(path: Path) -> ArtifactRecord:
    content = path.read_bytes()
    return ArtifactRecord(
        path=path.name,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )


@pytest.mark.parametrize("answers", [(False,), (True, False), (True, True, False)])
def test_atomic_publication_preserves_previous_pointer_on_fingerprint_change(
    tmp_path: Path,
    answers: tuple[bool, ...],
) -> None:
    active = tmp_path / "platform_boarding_simulated.json"
    active.write_bytes(b'{"old":true}')
    old = active.read_bytes()
    artifact = tmp_path / "immutable.json"
    artifact.write_bytes(b"immutable")
    sequence = iter(answers)

    with pytest.raises(RuntimeError, match="runtime cohort changed"):
        publish_active_manifest(
            active_manifest=active,
            payload={"new": True},
            referenced_artifacts=(_record(artifact),),
            fingerprints_match=lambda: next(sequence),
        )

    assert active.read_bytes() == old


def test_atomic_publication_preserves_previous_pointer_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = tmp_path / "platform_boarding_simulated.json"
    active.write_bytes(b'{"old":true}')
    artifact = tmp_path / "immutable.json"
    artifact.write_bytes(b"immutable")
    real_replace = os.replace

    def fail_switch(source, destination):
        if Path(destination) == active:
            raise OSError("injected pointer failure")
        return real_replace(source, destination)

    monkeypatch.setattr("metro_alignment.formal_publication.os.replace", fail_switch)
    with pytest.raises(OSError, match="pointer failure"):
        publish_active_manifest(
            active_manifest=active,
            payload={"new": True},
            referenced_artifacts=(_record(artifact),),
            fingerprints_match=lambda: True,
        )
    assert active.read_bytes() == b'{"old":true}'


def test_atomic_publication_switches_one_pointer_after_hash_verification(tmp_path: Path) -> None:
    active = tmp_path / "platform_boarding_simulated.json"
    active.write_bytes(b'{"old":true}')
    artifact = tmp_path / "immutable.json"
    artifact.write_bytes(b"immutable")

    publish_active_manifest(
        active_manifest=active,
        payload={"new": True},
        referenced_artifacts=(_record(artifact),),
        fingerprints_match=lambda: True,
    )
    assert b'"new": true' in active.read_bytes()


def test_atomic_publication_rejects_mutated_immutable_artifact(tmp_path: Path) -> None:
    active = tmp_path / "platform_boarding_simulated.json"
    active.write_bytes(b'{"old":true}')
    artifact = tmp_path / "immutable.json"
    artifact.write_bytes(b"immutable")
    record = _record(artifact)
    artifact.write_bytes(b"mutated")
    with pytest.raises(ValueError, match="hash mismatch"):
        publish_active_manifest(
            active_manifest=active,
            payload={"new": True},
            referenced_artifacts=(record,),
            fingerprints_match=lambda: True,
        )
    assert active.read_bytes() == b'{"old":true}'
