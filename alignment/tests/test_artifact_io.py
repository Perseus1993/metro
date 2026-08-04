from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from metro_alignment.artifact_io import write_json_atomic


def test_atomic_json_failure_preserves_previous_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "artifact.json"
    output.write_text('{"old": true}', encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError(f"injected replace failure: {source} -> {destination}")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        write_json_atomic(output, {"new": True})

    assert json.loads(output.read_text(encoding="utf-8")) == {"old": True}
    assert list(tmp_path.glob("*.staging")) == []


def test_atomic_json_success_replaces_manifest(tmp_path: Path) -> None:
    output = tmp_path / "artifact.json"
    output.write_text('{"old": true}', encoding="utf-8")
    write_json_atomic(output, {"new": True})
    assert json.loads(output.read_text(encoding="utf-8")) == {"new": True}
