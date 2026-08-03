from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent


@dataclass
class ActiveVerticalRide:
    passenger: PassengerAgent
    event_id: int
    remaining_steps: int
    total_steps: int
    start_position: tuple[float, float]
    progress_steps: float = 0.0
    lateral_offset: float = 0.0
    duration_seconds: float | None = None
    elapsed_seconds: float = 0.0
    remaining_seconds: float | None = None


@dataclass
class VerticalPhysicalResource:
    source_element_id: str
    active_facility_id: str | None = None
    retained_facility_id: str | None = None
    passenger_ids: set[int] = field(default_factory=set)
    waiting_facility_ids: list[str] = field(default_factory=list)

    def request(self, facility_id: str) -> None:
        """Register one directional facade in FIFO dispatch order."""

        if facility_id not in self.waiting_facility_ids:
            self.waiting_facility_ids.append(facility_id)

    def withdraw_request(self, facility_id: str) -> None:
        self.waiting_facility_ids = [
            item for item in self.waiting_facility_ids if item != facility_id
        ]

    def can_acquire(self, facility_id: str) -> bool:
        if self.active_facility_id not in {None, facility_id}:
            return False
        if self.retained_facility_id not in {None, facility_id}:
            return False
        return not self.waiting_facility_ids or self.waiting_facility_ids[0] == facility_id

    def acquire(self, facility_id: str, passenger_ids: tuple[int, ...]) -> bool:
        self.request(facility_id)
        if not self.can_acquire(facility_id):
            return False
        self.withdraw_request(facility_id)
        self.active_facility_id = facility_id
        self.passenger_ids.update(int(passenger_id) for passenger_id in passenger_ids)
        return True

    def release(self, facility_id: str, passenger_ids: tuple[int, ...]) -> None:
        if self.active_facility_id != facility_id:
            return
        self.passenger_ids.difference_update(int(item) for item in passenger_ids)
        if not self.passenger_ids and self.retained_facility_id is None:
            self.active_facility_id = None

    def retain(self, facility_id: str) -> bool:
        """Keep an exclusive connector occupied between passenger phases."""

        if self.active_facility_id not in {None, facility_id}:
            return False
        if self.retained_facility_id not in {None, facility_id}:
            return False
        self.active_facility_id = facility_id
        self.retained_facility_id = facility_id
        return True

    def release_retention(self, facility_id: str) -> None:
        if self.retained_facility_id != facility_id:
            return
        self.retained_facility_id = None
        if not self.passenger_ids:
            self.active_facility_id = None
