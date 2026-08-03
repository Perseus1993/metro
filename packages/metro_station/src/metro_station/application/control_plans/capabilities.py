"""Supported control-measure kinds and their lifecycle actions."""

from __future__ import annotations

from typing import Any, Mapping


WATER_BARRIER = "water_barrier"
ISOLATION_BARRIER = "isolation_barrier"
CLOSURE_ZONE = "closure_zone"
ONE_WAY_CHANNEL = "one_way_channel"
ACCESS_CLOSURE = "access_closure"
ESCALATOR_DIRECTION = "escalator_direction"
STAFF_GUIDANCE = "staff_guidance"

DEPLOY = "deploy"
REMOVE = "remove"
CLOSE = "close"
OPEN = "open"
SET_DIRECTION = "set_direction"
RESTORE_DIRECTION = "restore_direction"
START_GUIDANCE = "start_guidance"
STOP_GUIDANCE = "stop_guidance"

MEASURE_ACTIONS: dict[str, frozenset[str]] = {
    WATER_BARRIER: frozenset({DEPLOY, REMOVE}),
    ISOLATION_BARRIER: frozenset({DEPLOY, REMOVE}),
    CLOSURE_ZONE: frozenset({DEPLOY, REMOVE}),
    ONE_WAY_CHANNEL: frozenset({SET_DIRECTION, RESTORE_DIRECTION}),
    ACCESS_CLOSURE: frozenset({CLOSE, OPEN}),
    ESCALATOR_DIRECTION: frozenset({SET_DIRECTION, RESTORE_DIRECTION}),
    STAFF_GUIDANCE: frozenset({START_GUIDANCE, STOP_GUIDANCE}),
}
ACTIVATING_ACTIONS = frozenset({DEPLOY, CLOSE, SET_DIRECTION, START_GUIDANCE})
DEACTIVATING_ACTIONS = frozenset({REMOVE, OPEN, RESTORE_DIRECTION, STOP_GUIDANCE})
GEOMETRY_MEASURES = frozenset({WATER_BARRIER, ISOLATION_BARRIER, CLOSURE_ZONE, ONE_WAY_CHANNEL})
TARGETED_MEASURES = frozenset({ACCESS_CLOSURE, ESCALATOR_DIRECTION})


def validate_measure_capability(
    *,
    kind: str,
    target_id: str | None,
    level_id: str | None,
    parameters: Mapping[str, Any],
) -> None:
    if kind not in MEASURE_ACTIONS:
        raise ValueError(f"unsupported control measure kind: {kind!r}")
    if kind in GEOMETRY_MEASURES:
        if not str(level_id or "").strip():
            raise ValueError(f"control measure {kind!r} requires level_id")
        if not isinstance(parameters.get("geometry"), Mapping):
            raise ValueError(f"control measure {kind!r} requires geometry parameters")
    if kind in TARGETED_MEASURES and not str(target_id or "").strip():
        raise ValueError(f"control measure {kind!r} requires target_id")
    if kind == STAFF_GUIDANCE and not (str(target_id or "").strip() or str(level_id or "").strip()):
        raise ValueError("staff_guidance requires target_id or level_id")


def validate_event_capability(kind: str, action: str, parameters: Mapping[str, Any]) -> None:
    allowed = MEASURE_ACTIONS[kind]
    if action not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"control action for {kind!r} must be one of {choices}; got {action!r}")
    if action == SET_DIRECTION:
        direction = str(parameters.get("direction") or "").strip()
        allowed_directions = {
            ESCALATOR_DIRECTION: {"up", "down"},
            ONE_WAY_CHANNEL: {"forward", "reverse"},
        }[kind]
        if direction not in allowed_directions:
            choices = ", ".join(sorted(allowed_directions))
            raise ValueError(
                f"set_direction for {kind!r} requires one of {choices}; got {direction!r}"
            )
