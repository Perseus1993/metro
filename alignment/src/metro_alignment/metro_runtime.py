from __future__ import annotations

import hashlib
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import metro_station

RUNTIME_DISTRIBUTIONS = ("jupedsim", "mesa", "numpy", "pandas", "pedpy", "shapely")


def _normalized_python_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def metro_source_fingerprint() -> dict[str, Any]:
    """Fingerprint all imported Metro Python sources without embedding local paths."""

    package_root = Path(metro_station.__file__).resolve().parent
    source_files = sorted(package_root.rglob("*.py"))
    digest = hashlib.sha256()
    for source_file in source_files:
        relative = source_file.relative_to(package_root).as_posix().encode("utf-8")
        content = _normalized_python_bytes(source_file)
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    dependency_versions = {}
    for distribution in RUNTIME_DISTRIBUTIONS:
        try:
            dependency_versions[distribution] = version(distribution)
        except PackageNotFoundError:
            dependency_versions[distribution] = "missing"
    return {
        "schema_version": "metro_source_fingerprint.v2",
        "package_version": str(metro_station.__version__),
        "python": f"{platform.python_implementation()} {platform.python_version()}",
        "dependency_versions": dependency_versions,
        "python_file_count": len(source_files),
        "source_tree_sha256": digest.hexdigest(),
    }
