from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ...facilities.service_events import FacilityServiceEvent
from ...facilities.process import FacilityKind
from ...station.scenario import StationSandboxScenario
from ..config import H, W


def vertical_service_events_payload(
    events: Iterable[FacilityServiceEvent],
    scenario: StationSandboxScenario,
) -> list[dict[str, object]]:
    vertical_kinds = {
        FacilityKind.ESCALATOR.value,
        FacilityKind.ELEVATOR.value,
        FacilityKind.STAIRS.value,
    }
    return [_event_payload(event, scenario) for event in events if event.facility_kind in vertical_kinds]


def gate_events_payload(
    events: Iterable[FacilityServiceEvent],
    scenario: StationSandboxScenario,
) -> list[dict[str, object]]:
    return [
        _event_payload(event, scenario)
        for event in events
        if event.facility_kind == FacilityKind.GATE.value
    ]


def elevator_events_payload(
    events: Iterable[FacilityServiceEvent],
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for index, event in enumerate(events, start=1):
        if event.facility_kind != FacilityKind.ELEVATOR.value:
            continue
        payloads.append(
            {
                "id": event.event_id or index,
                "facility": event.facility_id,
                "direction": event.direction or "both",
                "from_level": event.from_level,
                "to_level": event.to_level,
                "start": round(event.start_time, 2),
                "board_end": round(event.board_end_time or event.start_time, 2),
                "arrive": round(event.arrive_time or event.end_time, 2),
                "end": round(event.end_time, 2),
                "count": event.count,
                "track_ids": list(event.passenger_ids),
            }
        )
    return payloads


def conveyor_events_payload(
    events: Iterable[FacilityServiceEvent],
    scenario: StationSandboxScenario,
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for index, event in enumerate(events, start=1):
        if event.facility_kind not in {FacilityKind.ESCALATOR.value, FacilityKind.STAIRS.value}:
            continue
        start = _normalized_position(event.start_position, scenario)
        end = _normalized_position(event.end_position, scenario)
        payloads.append(
            {
                "id": event.event_id or index,
                "facility": event.facility_id,
                "kind": event.facility_kind,
                "mode": event.mode,
                "direction": event.direction or "both",
                "start": round(event.start_time, 2),
                "end": round(event.end_time, 2),
                "count": event.count,
                "track_ids": list(event.passenger_ids),
                "line": [list(start), list(end)],
            }
        )
    return payloads


def _event_payload(
    event: FacilityServiceEvent,
    scenario: StationSandboxScenario,
) -> dict[str, object]:
    payload: dict[str, Any] = event.as_dict()
    payload["start_canvas"] = list(_canvas_position(event.start_position, scenario))
    payload["end_canvas"] = list(_canvas_position(event.end_position, scenario))
    return payload


def _canvas_position(
    position: tuple[float, float],
    scenario: StationSandboxScenario,
) -> tuple[float, float]:
    normalized = _normalized_position(position, scenario)
    return (normalized[0] * W, normalized[1] * H)


def _normalized_position(
    position: tuple[float, float],
    scenario: StationSandboxScenario,
) -> tuple[float, float]:
    design = scenario.station_design
    width = float(
        design.constraints.canvas_width_m if design is not None else scenario.geometry.width
    )
    height = float(
        design.constraints.canvas_height_m if design is not None else scenario.geometry.height
    )
    return (
        max(0.0, min(1.0, position[0] / width)),
        max(0.0, min(1.0, position[1] / height)),
    )
