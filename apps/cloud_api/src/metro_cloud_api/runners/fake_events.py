from __future__ import annotations

import json
from typing import Any

import pyarrow as pa

from metro_cloud_api.output_schema import EVENT_SCHEMA, dictionary_array


def build_fake_events(agents: list[dict[str, Any]], total: int) -> pa.Table:
    rows: list[dict[str, Any]] = []
    for agent in agents:
        rows.append(_terminal_event(agent, "created", agent["birth"]))
        if agent["end"] <= total:
            rows.append(_terminal_event(agent, "completed", agent["end"]))
    for group_index in range(0, len(agents), 4):
        members = agents[group_index:group_index + 4]
        event_time = members[0]["birth"] + 20
        if event_time > total:
            continue
        event_id = f"facility:esc_1:{group_index // 4}"
        for agent in members:
            rows.append(
                {"event_id": event_id, "agent_id": agent["id"], "t_seconds": event_time,
                 "end_seconds": min(event_time + 12, total), "event_type": "facility_service",
                 "facility_id": "esc_1", "facility_kind": "escalator",
                 "party_size": len(members), "detail_json": "{}"}
            )
    rows.sort(key=lambda row: (row["t_seconds"], row["event_id"], row["agent_id"] or -1))
    if not rows:
        return EVENT_SCHEMA.empty_table()
    arrays = []
    for field in EVENT_SCHEMA:
        values = [row[field.name] for row in rows]
        arrays.append(
            dictionary_array(values) if pa.types.is_dictionary(field.type)
            else pa.array(values, type=field.type)
        )
    return pa.Table.from_arrays(arrays, schema=EVENT_SCHEMA)


def _terminal_event(agent: dict[str, Any], event: str, at: float) -> dict[str, Any]:
    return {
        "event_id": f"terminal:{agent['id']}:{event}", "agent_id": agent["id"],
        "t_seconds": at, "end_seconds": None, "event_type": "passenger_terminal",
        "facility_id": None, "facility_kind": None, "party_size": agent["group_size"],
        "detail_json": json.dumps({"event": event, "intent": agent["intent"]}, sort_keys=True),
    }
