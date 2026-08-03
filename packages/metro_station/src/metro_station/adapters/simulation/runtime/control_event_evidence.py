"""Applied control-event evidence emitted by the simulation adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from metro_station.application.control_plans import ControlEvent, ControlMeasure


@dataclass(frozen=True)
class AppliedControlEvent:
    event_id: str
    measure_id: str
    measure_kind: str
    action: str
    scheduled_seconds: int
    applied_seconds: float
    status: str
    target_id: str | None
    level_id: str | None
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def record_control_event(
    model: Any,
    event: ControlEvent,
    measure: ControlMeasure,
    *,
    status: str,
    details: dict[str, Any],
) -> AppliedControlEvent:
    applied = AppliedControlEvent(
        event_id=event.event_id,
        measure_id=measure.measure_id,
        measure_kind=measure.kind,
        action=event.action,
        scheduled_seconds=event.at_seconds,
        applied_seconds=float(model.current_time_seconds),
        status=status,
        target_id=measure.target_id,
        level_id=measure.level_id,
        details=details,
    )
    model.audit.record(
        "control_event_applied" if status == "applied" else "control_event_rejected",
        source="control_timeline",
        severity="info" if status == "applied" else "warning",
        step=model.step_index,
        context=applied.as_dict(),
    )
    return applied
