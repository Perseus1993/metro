"""JSON boundary for control-plan contracts."""

from __future__ import annotations

import json

from .contracts import ControlPlan


def control_plan_to_json(plan: ControlPlan, *, indent: int | None = 2) -> str:
    return json.dumps(plan.as_dict(), ensure_ascii=False, indent=indent, sort_keys=True)


def control_plan_from_json(payload: str | bytes) -> ControlPlan:
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError("control-plan JSON must contain an object")
    return ControlPlan.from_dict(decoded)
