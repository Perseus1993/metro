from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .store import utc_now


RESULT_DEFAULTS: dict[str, Any] = {
    "schema_version": "0.1",
    "passenger_agent_count": None,
    "admin_agent_count": None,
    "total_agent_count": None,
    "person_count": None,
    "simulated_seconds": None,
    "trajectory_rows": None,
    "event_rows": None,
    "clearance_seconds": None,
    "coordinate_transform": None,
    "peak_rss_bytes": None,
}


def build_summary(
    job: dict[str, Any],
    job_dir: Path,
    *,
    peak_rss_bytes: int | None = None,
) -> dict[str, Any]:
    result = dict(RESULT_DEFAULTS)
    result_path = job_dir / "_result.json"
    if result_path.is_file():
        try:
            loaded = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                result.update(loaded)
        except (OSError, UnicodeError, json.JSONDecodeError):
            # Artifact validation reports malformed runner output. Summary generation
            # must remain the final durable operation and therefore cannot re-raise.
            pass
    if peak_rss_bytes is not None:
        result["peak_rss_bytes"] = peak_rss_bytes

    finished_at = job["finished_at"] or utc_now()
    return {
        "schema_version": "0.1",
        "job_id": job["id"],
        "status": job["status"],
        "submitted_spec": job["submitted_spec"],
        "resolved_spec": job["resolved_spec"],
        "runner": {"kind": job["runner_kind"], "version": job["runner_version"]},
        "timing": {
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "finished_at": finished_at,
            "wall_seconds": _wall_seconds(job["started_at"], finished_at),
        },
        "error": job["error"],
        "result": result,
    }


def _wall_seconds(started_at: str | None, finished_at: str | None) -> float | None:
    if started_at is None or finished_at is None:
        return None
    try:
        seconds = (datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)).total_seconds()
    except (TypeError, ValueError):
        return None
    return round(max(0.0, seconds), 6)
