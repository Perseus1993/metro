from __future__ import annotations

import pyarrow as pa


SCHEMA_VERSION = "0.1"

TRAJECTORY_SCHEMA = pa.schema(
    [
        pa.field("agent_id", pa.int32(), nullable=False),
        pa.field("t_seconds", pa.float32(), nullable=False),
        pa.field("x", pa.float32(), nullable=False),
        pa.field("y", pa.float32(), nullable=False),
        pa.field("group_size", pa.int32(), nullable=False),
        pa.field("state", pa.dictionary(pa.int32(), pa.string()), nullable=False),
        pa.field("intent", pa.dictionary(pa.int32(), pa.string()), nullable=False),
        pa.field("goal_kind", pa.dictionary(pa.int32(), pa.string()), nullable=True),
        pa.field("goal_stage", pa.dictionary(pa.int32(), pa.string()), nullable=True),
        pa.field("goal_facility_id", pa.dictionary(pa.int32(), pa.string()), nullable=True),
        pa.field("level_id", pa.dictionary(pa.int32(), pa.string()), nullable=True),
        pa.field("platform_id", pa.dictionary(pa.int32(), pa.string()), nullable=True),
    ]
)

EVENT_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("agent_id", pa.int32(), nullable=True),
        pa.field("t_seconds", pa.float32(), nullable=False),
        pa.field("end_seconds", pa.float32(), nullable=True),
        pa.field("event_type", pa.dictionary(pa.int32(), pa.string()), nullable=False),
        pa.field("facility_id", pa.dictionary(pa.int32(), pa.string()), nullable=True),
        pa.field("facility_kind", pa.dictionary(pa.int32(), pa.string()), nullable=True),
        pa.field("party_size", pa.int32(), nullable=True),
        pa.field("detail_json", pa.string(), nullable=True),
    ]
)


def dictionary_array(values: list[str | None]) -> pa.DictionaryArray:
    return pa.array(values, type=pa.string()).dictionary_encode()
