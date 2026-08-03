"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel


def facility_stage_order_valid(model: MetroStationModel) -> bool:
    stages_by_passenger: dict[int, list[str]] = {}
    for event in model.goal_parity.events:
        if event.stream != "physical" or event.kind != "service_completed":
            continue
        if event.stage is None:
            continue
        stages_by_passenger.setdefault(event.passenger_id, []).append(event.stage)

    intent_by_passenger = {
        event.passenger_id: event.intent for event in model.passenger_terminal_events
    }
    return all(
        _passenger_stage_order_valid(intent_by_passenger.get(passenger_id), stages)
        for passenger_id, stages in stages_by_passenger.items()
    )


def replan_during_service_violations(model: MetroStationModel) -> int:
    replans = [
        event
        for event in model.goal_parity.events
        if event.stream == "graph" and event.kind == "progress_stalled"
    ]
    return sum(
        1
        for replan in replans
        if any(
            replan.passenger_id in service.passenger_ids
            and float(
                service.start_time
                if getattr(service, "commit_time", None) is None
                else service.commit_time
            )
            <= replan.time_seconds
            < float(service.end_time)
            for service in model.facility_service_events
        )
    )


def _passenger_stage_order_valid(intent: str | None, stages: list[str]) -> bool:
    if intent in {"enter_and_board", "transfer"}:
        if not stages or stages[-1] != "boarding_door":
            return False
    if intent in {"exit_station", "evacuate_station"}:
        if not stages or stages[-1] != "exit_gate":
            return False
    vertical_indexes = [
        index for index, stage in enumerate(stages) if stage == "vertical_transfer"
    ]
    if not vertical_indexes:
        return True
    return vertical_indexes == list(
        range(vertical_indexes[0], vertical_indexes[-1] + 1)
    )
