from __future__ import annotations

from metro_alignment.metro_runtime import metro_source_fingerprint


def test_metro_source_fingerprint_is_stable_and_path_free() -> None:
    first = metro_source_fingerprint()
    second = metro_source_fingerprint()
    assert first == second
    assert first["python_file_count"] > 0
    assert len(first["source_tree_sha256"]) == 64
    assert set(first) == {
        "package_version",
        "python",
        "dependency_versions",
        "python_file_count",
        "source_tree_sha256",
    }
    assert first["dependency_versions"]["jupedsim"] != "missing"
