from __future__ import annotations

from typing import TYPE_CHECKING

from .process import FacilityKind
from .runtime_base import FacilityProcessAgent
from .service_events import FacilityServiceEvent

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.transit import TrainAgent


class BoardingDoorProcessAgent(FacilityProcessAgent):
    """Train-door process gated by train dwell and remaining capacity."""

    def _initial_state(self) -> str:
        return "closed"

    def _active_state(self) -> str:
        return "open"

    @property
    def is_available_for_queue(self) -> bool:
        return not self.is_forced_disabled

    def _sync_state(self, train: TrainAgent | None = None) -> None:
        self.state = "open" if train is not None and train.is_boarding else "closed"

    def _can_start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> bool:
        return (
            super()._can_start_service(
                passenger,
                train,
                release_index=release_index,
                release_count=release_count,
            )
            and train is not None
            and train.capacity_remaining >= passenger.group_size
        )

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> None:
        if train is None:
            return
        start_time, board_end_time, end_time = _instant_service_window(
            self.model,
            self.facility_id,
            self.effective_service_persons_per_min,
            release_index,
            release_count,
            passenger.group_size,
        )
        train.current_load_persons += passenger.group_size
        passenger.begin_facility_service(self.spec)
        passenger.passive_facility_service = False
        self._instant_pass_service(
            passenger,
            self.model.clamp_position(self.spec.position),
        )
        self.served_persons += passenger.group_size
        self.model.record_facility_service_event(
            FacilityServiceEvent(
                event_id=self.model.next_facility_service_event_id(),
                facility_id=self.facility_id,
                facility_kind=FacilityKind.TRAIN_DOOR.value,
                mode=self.spec.stage,
                passenger_ids=(int(passenger.unique_id),),
                start_time=start_time,
                board_end_time=board_end_time,
                arrive_time=end_time,
                end_time=end_time,
                start_position=self.spec.queue_anchor,
                end_position=self.spec.position,
                direction=self.spec.direction,
                from_level=self.spec.entry_level_id,
                to_level=self.spec.exit_level_id,
            )
        )


def _instant_service_window(
    model,
    facility_id: str,
    persons_per_min: float,
    release_index: int,
    release_count: int,
    group_size: int,
) -> tuple[float, float, float]:
    window_end = float(model.current_time_seconds)
    window_start = max(
        0.0,
        window_end - float(model.scenario.tick_seconds),
        _facility_service_start_floor(model, facility_id),
    )
    slot_count = max(1, int(release_count))
    slot_time = window_start + (window_end - window_start) * (
        (max(0, int(release_index)) + 1) / (slot_count + 1)
    )
    service_seconds = 60.0 * max(1, int(group_size)) / max(0.001, persons_per_min)
    slot_span = (window_end - window_start) / (slot_count + 1)
    duration = max(0.05, min(service_seconds, slot_span * 0.9))
    start_time = max(window_start, slot_time - duration)
    board_end_time = start_time + (slot_time - start_time) * 0.55
    return start_time, board_end_time, slot_time


def _facility_service_start_floor(model, facility_id: str) -> float:
    floor = getattr(model, "facility_service_start_floor", None)
    if not callable(floor):
        return 0.0
    return float(floor(facility_id))
