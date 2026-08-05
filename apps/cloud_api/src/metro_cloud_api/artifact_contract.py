from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from .output_schema import EVENT_SCHEMA, TRAJECTORY_SCHEMA


RESULT_KEYS = frozenset(
    {
        "schema_version",
        "passenger_agent_count",
        "admin_agent_count",
        "total_agent_count",
        "person_count",
        "simulated_seconds",
        "trajectory_rows",
        "event_rows",
        "clearance_seconds",
        "coordinate_transform",
    }
)


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
    if not isinstance(result, dict):
        return {"valid": False, "errors": ["result must be a JSON object"]}
    errors = _result_errors(result)
    errors.extend(_schema_and_count_errors(trajectories, events, result))
    errors.extend(_trajectory_content_errors(trajectories, result))
    errors.extend(_event_content_errors(events))
    return {"valid": not errors, "errors": errors}


def _result_errors(result: dict[str, Any]) -> list[str]:
    errors = []
    missing = sorted(RESULT_KEYS - result.keys())
    if missing:
        errors.append(f"result keys missing: {', '.join(missing)}")
    if result.get("schema_version") != "0.1":
        errors.append("result schema version mismatch")
    return errors


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
    inconsistent_groups = set()
    for agent_id, group_size in zip(
        agent_ids, trajectories.column("group_size").to_pylist(), strict=True
    ):
        normalized_id = int(agent_id)
        normalized_size = int(group_size)
        previous = groups.setdefault(normalized_id, normalized_size)
        if previous != normalized_size:
            inconsistent_groups.add(normalized_id)
    if inconsistent_groups:
        errors.append("group size changes within agent trajectory")
    if len(groups) != result.get("passenger_agent_count"):
        errors.append("passenger agent count mismatch")
    if sum(groups.values()) != result.get("person_count"):
        errors.append("person count mismatch")
    return errors


def _event_content_errors(events: Any) -> list[str]:
    if events.schema != EVENT_SCHEMA:
        return []
    event_ids = events.column("event_id").to_pylist()
    times = events.column("t_seconds").to_pylist()
    pairs = list(zip(times, event_ids, strict=True))
    errors = []
    if pairs != sorted(pairs):
        errors.append("event sort order mismatch")
    if any(
        not isinstance(event_id, str)
        or not event_id.startswith(("facility:", "terminal:"))
        for event_id in event_ids
    ):
        errors.append("event id namespace mismatch")
    return errors
