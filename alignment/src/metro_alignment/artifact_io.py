from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Validate JSON, durably stage it, then atomically replace one manifest."""

    content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid4().hex}.staging")
    try:
        with staged.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        if staged.exists():
            staged.unlink()
