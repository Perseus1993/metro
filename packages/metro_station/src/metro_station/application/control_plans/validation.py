"""Schedule validation for control plans."""

from __future__ import annotations

from .capabilities import ACTIVATING_ACTIONS, DEACTIVATING_ACTIONS
from .contracts import ControlPlan


def validate_control_plan_schedule(
    plan: ControlPlan,
    *,
    horizon_seconds: float,
    tick_seconds: int,
) -> None:
    if horizon_seconds <= 0:
        raise ValueError("horizon_seconds must be > 0")
    if tick_seconds < 1:
        raise ValueError("tick_seconds must be >= 1")
    measure_by_id = {measure.measure_id: measure for measure in plan.measures}
    active = {measure.measure_id: measure.initially_active for measure in plan.measures}
    previous_time = -1
    seen: set[tuple[int, str]] = set()
    for event in plan.events:
        if event.at_seconds < previous_time:
            raise ValueError("control events must be ordered by at_seconds")
        previous_time = event.at_seconds
        if event.at_seconds >= horizon_seconds:
            raise ValueError("control event at_seconds must be before the simulation horizon")
        if event.at_seconds % tick_seconds != 0:
            raise ValueError("control event at_seconds must align with tick_seconds")
        key = (event.at_seconds, event.measure_id)
        if key in seen:
            raise ValueError("a control measure may change at most once per simulation time")
        seen.add(key)
        _apply_lifecycle(event.action, event.measure_id, active)
        if event.measure_id not in measure_by_id:  # Defensive for non-constructor callers.
            raise ValueError(f"control event references unknown measure {event.measure_id!r}")


def _apply_lifecycle(action: str, measure_id: str, active: dict[str, bool]) -> None:
    is_active = active[measure_id]
    if action in ACTIVATING_ACTIONS:
        if is_active:
            raise ValueError(f"control measure {measure_id!r} is already active")
        active[measure_id] = True
        return
    if action in DEACTIVATING_ACTIONS:
        if not is_active:
            raise ValueError(f"control measure {measure_id!r} is not active")
        active[measure_id] = False
        return
    raise ValueError(f"unsupported control action: {action!r}")
