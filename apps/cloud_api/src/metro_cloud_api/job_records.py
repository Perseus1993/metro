from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def deserialize_job(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["submitted_spec"] = json.loads(result.pop("submitted_spec"))
    result["resolved_spec"] = json.loads(result.pop("resolved_spec"))
    error_json = result.pop("error_json")
    result["error"] = None if error_json is None else json.loads(error_json)
    result["cancel_requested"] = bool(result["cancel_requested"])
    return result
