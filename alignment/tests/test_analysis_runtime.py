from __future__ import annotations

from pathlib import Path

from metro_alignment.analysis_runtime import (
    _normalized_text_bytes,
    analysis_runtime_fingerprint,
)


def test_analysis_runtime_fingerprint_is_stable_and_path_free() -> None:
    first = analysis_runtime_fingerprint()
    assert first == analysis_runtime_fingerprint()
    assert first["schema_version"] == "alignment_analysis_runtime.v2"
    assert first["file_count"] > 10
    assert len(first["content_sha256"]) == 64
    assert "D:\\" not in str(first)


def test_analysis_fingerprint_normalizes_worktree_line_endings(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_bytes(b"first\r\nsecond\rthird\n")

    assert _normalized_text_bytes(source) == b"first\nsecond\nthird\n"
