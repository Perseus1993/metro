from __future__ import annotations

import hashlib
import platform
from pathlib import Path
from typing import Any

import pedpy

ROOT = Path(__file__).resolve().parents[2]


def _normalized_text_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def analysis_runtime_fingerprint() -> dict[str, Any]:
    """Content-address the code and lock inputs that define alignment metrics."""

    files = sorted((ROOT / "src" / "metro_alignment").rglob("*.py"))
    files.extend(
        ROOT / "scripts" / name
        for name in ("compute_observed_metrics.py", "run_alignment_scene.py")
    )
    files.extend((ROOT / "pyproject.toml", ROOT / "uv.lock"))
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(ROOT).as_posix()):
        relative = path.relative_to(ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_normalized_text_bytes(path))
        digest.update(b"\0")
    return {
        "schema_version": "alignment_analysis_runtime.v2",
        "python": f"{platform.python_implementation()} {platform.python_version()}",
        "pedpy_version": str(getattr(pedpy, "__version__", "unknown")),
        "file_count": len(files),
        "content_sha256": digest.hexdigest(),
    }
