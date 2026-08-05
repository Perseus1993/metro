from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from .output_schema import EVENT_SCHEMA, TRAJECTORY_SCHEMA


def validate_runner_artifacts(output: Path) -> dict[str, Any]:
    result_path = output / "_result.json"
    trajectory_path = output / "trajectories.parquet"
    event_path = output / "events.parquet"
    if not result_path.exists():
        return {"valid": False, "errors": ["missing _result.json"]}
    if not trajectory_path.exists() or not event_path.exists():
        return {"valid": False, "errors": ["missing parquet artifact"]}
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        trajectories = pq.read_table(trajectory_path)
        events = pq.read_table(event_path)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        return {"valid": False, "errors": [f"unreadable artifact: {type(exc).__name__}"]}
    errors = _schema_and_count_errors(trajectories, events, result)
    errors.extend(_trajectory_content_errors(trajectories, result))
    return {"valid": not errors, "errors": errors}


def _schema_and_count_errors(trajectories: Any, events: Any, result: dict) -> list[str]:
    errors = []
    if trajectories.schema != TRAJECTORY_SCHEMA:
        errors.append("trajectory schema mismatch")
    if events.schema != EVENT_SCHEMA:
        errors.append("event schema mismatch")
    if trajectories.num_rows != result.get("trajectory_rows"):
        errors.append("trajectory row count mismatch")
    if events.num_rows != result.get("event_rows"):
        errors.append("event row count mismatch")
    return errors


def _trajectory_content_errors(trajectories: Any, result: dict) -> list[str]:
    if trajectories.schema != TRAJECTORY_SCHEMA:
        return []
    agent_ids = trajectories.column("agent_id").to_pylist()
    times = trajectories.column("t_seconds").to_pylist()
    pairs = list(zip(agent_ids, times, strict=True))
    errors = []
    if pairs != sorted(pairs):
        errors.append("trajectory sort order mismatch")
    groups: dict[int, int] = {}
    for agent_id, group_size in zip(
        agent_ids, trajectories.column("group_size").to_pylist(), strict=True
    ):
        groups.setdefault(int(agent_id), int(group_size))
    if len(groups) != result.get("passenger_agent_count"):
        errors.append("passenger agent count mismatch")
    if sum(groups.values()) != result.get("person_count"):
        errors.append("person count mismatch")
    return errors
