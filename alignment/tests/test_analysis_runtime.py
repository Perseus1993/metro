from __future__ import annotations

from metro_alignment.analysis_runtime import analysis_runtime_fingerprint


def test_analysis_runtime_fingerprint_is_stable_and_path_free() -> None:
    first = analysis_runtime_fingerprint()
    assert first == analysis_runtime_fingerprint()
    assert first["schema_version"] == "alignment_analysis_runtime.v1"
    assert first["file_count"] > 10
    assert len(first["content_sha256"]) == 64
    assert "D:\\" not in str(first)
