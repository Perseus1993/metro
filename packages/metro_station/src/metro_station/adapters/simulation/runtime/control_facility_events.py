"""Translate access-closure controls to the existing facility event contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from metro_station.application.control_plans import (
    ACCESS_CLOSURE,
    CLOSE,
    ControlEvent,
    ControlMeasure,
)

from ..station.disruptions import (
    DISABLE_FACILITY,
    ENABLE_FACILITY,
    FacilityAvailabilityEvent,
)


def facility_control_key(event: ControlEvent, measure: ControlMeasure) -> tuple[int, str, str]:
    action = DISABLE_FACILITY if event.action == CLOSE else ENABLE_FACILITY
    return event.at_seconds, str(measure.target_id), action


def build_facility_availability_events(
    measures: Iterable[ControlMeasure],
    scheduled: Mapping[tuple[int, str, str], ControlEvent],
) -> tuple[FacilityAvailabilityEvent, ...]:
    events = [
        FacilityAvailabilityEvent(0, DISABLE_FACILITY, str(measure.target_id))
        for measure in measures
        if measure.kind == ACCESS_CLOSURE and measure.initially_active
    ]
    events.extend(
        FacilityAvailabilityEvent(at_seconds, action, facility_id)
        for at_seconds, facility_id, action in scheduled
    )
    return tuple(sorted(events))
