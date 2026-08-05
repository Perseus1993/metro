from __future__ import annotations

from pathlib import Path

from metro_alignment.metro_runtime import (
    _normalized_python_bytes,
    metro_source_fingerprint,
)


def test_metro_source_fingerprint_is_stable_and_path_free() -> None:
    first = metro_source_fingerprint()
    second = metro_source_fingerprint()
    assert first == second
    assert first["python_file_count"] > 0
    assert len(first["source_tree_sha256"]) == 64
    assert set(first) == {
        "schema_version",
        "package_version",
        "python",
        "dependency_versions",
        "python_file_count",
        "source_tree_sha256",
    }
    assert first["dependency_versions"]["jupedsim"] != "missing"


def test_metro_fingerprint_normalizes_worktree_line_endings(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_bytes(b"first\r\nsecond\rthird\n")

    assert _normalized_python_bytes(source) == b"first\nsecond\nthird\n"
