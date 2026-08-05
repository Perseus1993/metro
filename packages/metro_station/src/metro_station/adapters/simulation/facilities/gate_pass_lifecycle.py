from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .service_events import FacilityServiceEvent

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent


@dataclass
class ActiveGatePass:
    passenger: PassengerAgent
    event_id: int
    start_position: tuple[float, float]
    end_position: tuple[float, float]
    end_time: float
    total_steps: int
    progress_steps: float = 0.0
    duration_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    remaining_seconds: float = 0.0
    last_motion_request_time: float | None = None
    release_slot_index: int | None = None


def elapsed_from_committed_gate_position(active: ActiveGatePass) -> float:
    dx = active.end_position[0] - active.start_position[0]
    dy = active.end_position[1] - active.start_position[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-18:
        return active.duration_seconds
    progress = (
        (active.passenger.pos[0] - active.start_position[0]) * dx
        + (active.passenger.pos[1] - active.start_position[1]) * dy
    ) / length_squared
    return max(0.0, min(active.duration_seconds, progress * active.duration_seconds))


def delay_gate_event(
    active: ActiveGatePass,
    events: list[FacilityServiceEvent],
    delay_seconds: float,
) -> None:
    if delay_seconds <= 0.0:
        return
    active.end_time += delay_seconds
    for index, event in enumerate(events):
        if event.event_id != active.event_id:
            continue
        events[index] = replace(
            event,
            end_time=event.end_time + delay_seconds,
            arrive_time=(
                None if event.arrive_time is None else event.arrive_time + delay_seconds
            ),
        )
        return


def set_gate_event_completion_time(
    active: ActiveGatePass,
    events: list[FacilityServiceEvent],
    completion_time: float,
) -> None:
    actual_end = max(0.0, float(completion_time))
    active.end_time = actual_end
    for index, event in enumerate(events):
        if event.event_id != active.event_id:
            continue
        events[index] = replace(
            event,
            end_time=actual_end,
            arrive_time=actual_end,
            end_position=tuple(active.passenger.pos),
            board_end_time=(
                None
                if event.board_end_time is None
                else min(float(event.board_end_time), actual_end)
            ),
        )
        return
