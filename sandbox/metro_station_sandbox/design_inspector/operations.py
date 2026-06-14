from __future__ import annotations

from typing import Any


OPERATION_GROUPS = (
    {
        "id": "demand",
        "label": "Demand",
        "fields": (
            {
                "id": "entry_count_hour",
                "label": "Entry arrivals",
                "unit": "p/h",
                "kind": "integer",
                "default": 8683,
                "min": 0,
                "max": 120000,
                "step": 100,
            },
            {
                "id": "exit_count_hour",
                "label": "Exit arrivals",
                "unit": "p/h",
                "kind": "integer",
                "default": 7253,
                "min": 0,
                "max": 120000,
                "step": 100,
            },
            {
                "id": "group_size",
                "label": "Group size",
                "unit": "p/dot",
                "kind": "integer",
                "default": 1,
                "min": 1,
                "max": 50,
                "step": 1,
            },
        ),
    },
    {
        "id": "movement",
        "label": "Movement",
        "fields": (
            {
                "id": "walk_units_per_tick",
                "label": "Walk speed",
                "unit": "u/tick",
                "kind": "number",
                "default": 2.0,
                "min": 0.1,
                "max": 12.0,
                "step": 0.1,
            },
            {
                "id": "escalator_speed_units_per_tick",
                "label": "Escalator speed",
                "unit": "u/tick",
                "kind": "number",
                "default": 2.3,
                "min": 0.1,
                "max": 16.0,
                "step": 0.1,
            },
            {
                "id": "stairs_speed_units_per_tick",
                "label": "Stairs speed",
                "unit": "u/tick",
                "kind": "number",
                "default": 1.55,
                "min": 0.1,
                "max": 12.0,
                "step": 0.05,
            },
            {
                "id": "elevator_speed_units_per_tick",
                "label": "Elevator ride speed",
                "unit": "u/tick",
                "kind": "number",
                "default": 4.2,
                "min": 0.1,
                "max": 30.0,
                "step": 0.1,
            },
        ),
    },
    {
        "id": "service",
        "label": "Service",
        "fields": (
            {
                "id": "gate_service_persons_per_min",
                "label": "Gate service",
                "unit": "p/min",
                "kind": "integer",
                "default": 55,
                "min": 1,
                "max": 300,
                "step": 1,
            },
            {
                "id": "boarding_persons_per_min",
                "label": "Boarding service",
                "unit": "p/min",
                "kind": "integer",
                "default": 900,
                "min": 1,
                "max": 5000,
                "step": 10,
            },
            {
                "id": "elevator_cabin_capacity_persons",
                "label": "Elevator cabin",
                "unit": "p",
                "kind": "integer",
                "default": 12,
                "min": 1,
                "max": 80,
                "step": 1,
            },
            {
                "id": "elevator_boarding_seconds",
                "label": "Elevator boarding",
                "unit": "s",
                "kind": "number",
                "default": 5.0,
                "min": 1.0,
                "max": 90.0,
                "step": 0.5,
            },
            {
                "id": "elevator_cycle_seconds",
                "label": "Elevator cycle",
                "unit": "s",
                "kind": "number",
                "default": 35.0,
                "min": 1.0,
                "max": 240.0,
                "step": 1.0,
            },
        ),
    },
    {
        "id": "train",
        "label": "Train",
        "fields": (
            {
                "id": "train_headway_seconds",
                "label": "Headway",
                "unit": "s",
                "kind": "integer",
                "default": 240,
                "min": 30,
                "max": 1800,
                "step": 10,
            },
            {
                "id": "train_dwell_seconds",
                "label": "Dwell",
                "unit": "s",
                "kind": "integer",
                "default": 35,
                "min": 5,
                "max": 240,
                "step": 5,
            },
            {
                "id": "train_capacity_persons",
                "label": "Train capacity",
                "unit": "p",
                "kind": "integer",
                "default": 1200,
                "min": 1,
                "max": 4000,
                "step": 50,
            },
        ),
    },
)


def operation_schema_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": group["id"],
            "label": group["label"],
            "fields": [dict(field) for field in group["fields"]],
        }
        for group in OPERATION_GROUPS
    ]


def default_operations() -> dict[str, int | float]:
    return {
        field["id"]: field["default"]
        for group in OPERATION_GROUPS
        for field in group["fields"]
    }


def normalize_operations(payload: Any) -> dict[str, int | float]:
    values = default_operations()
    if not isinstance(payload, dict):
        return values
    fields = {
        field["id"]: field
        for group in OPERATION_GROUPS
        for field in group["fields"]
    }
    for field_id, field in fields.items():
        values[field_id] = _normalize_operation_value(field, payload.get(field_id))
    return values


def _normalize_operation_value(field: dict[str, Any], raw: Any) -> int | float:
    if raw is None or raw == "":
        raw = field["default"]
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float(field["default"])

    minimum = float(field["min"])
    maximum = float(field["max"])
    value = max(minimum, min(value, maximum))
    if field["kind"] == "integer":
        return int(round(value))
    return round(value, 3)
