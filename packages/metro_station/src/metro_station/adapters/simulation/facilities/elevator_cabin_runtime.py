from __future__ import annotations

from math import ceil, sqrt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent


class ElevatorCabinCompletionMixin:
    """Cabin release ownership, return transition, and individual poses."""

    def _depart_cabin(self) -> None:
        self.boarding_remaining_seconds = 0.0
        self.last_departure_load_persons = self.cabin_load_persons
        self.last_departure_step = self.model.step_index
        self.departed_cabins += 1
        self.cabin_state = "moving"
        self._update_cabin_positions()

    def _arrive_cabin(self) -> bool:
        self.travel_remaining_seconds = 0.0
        self._set_cabin_positions(self.spec.exit_position)
        if self.unload_remaining_seconds <= 1e-9:
            return self._finish_unloading()
        self.cabin_state = "unloading"
        return True

    def _finish_unloading(self) -> bool:
        self._service_release_positions_this_tick = []
        remaining_passengers: list[PassengerAgent] = []
        for release_index, passenger in enumerate(list(self.cabin_passengers)):
            if self._finish_vertical_service(
                passenger,
                release_index=release_index,
                event_id=self.active_event_id,
                preferred_release_position=(
                    float(passenger.pos[0]),
                    float(passenger.pos[1]),
                ),
                prefer_forward_clearance=True,
            ):
                continue
            remaining_passengers.append(passenger)
        if remaining_passengers:
            remaining_ids = {
                int(passenger.unique_id) for passenger in remaining_passengers
            }
            self.cabin_passengers = remaining_passengers
            self.cabin_load_persons = sum(
                passenger.group_size for passenger in remaining_passengers
            )
            self._cabin_offsets_by_passenger = {
                passenger_id: offset
                for passenger_id, offset in self._cabin_offsets_by_passenger.items()
                if passenger_id in remaining_ids
            }
            self._boarding_start_positions = {
                passenger_id: position
                for passenger_id, position in self._boarding_start_positions.items()
                if passenger_id in remaining_ids
            }
            self.boarding_remaining_seconds = 0.0
            self.travel_remaining_seconds = 0.0
            self.unload_remaining_seconds = 0.0
            self.cabin_state = "unloading"
            self._sync_legacy_step_counters()
            return False
        self.unload_remaining_seconds = 0.0
        self.cabin_state = (
            "returning" if self.return_remaining_seconds > 1e-9 else "idle"
        )
        if self.cabin_state == "idle":
            self.physical_resource.release_retention(self.facility_id)
        self.boarding_remaining_seconds = 0.0
        self.travel_remaining_seconds = 0.0
        if self.cabin_state != "returning":
            self.return_remaining_seconds = 0.0
        self.cabin_passengers = []
        self._cabin_offsets_by_passenger = {}
        self._boarding_start_positions = {}
        self.cabin_load_persons = 0
        self.active_event_id = None
        self._sync_legacy_step_counters()
        return True

    def _finish_returning(self) -> None:
        self.physical_resource.release_retention(self.facility_id)
        self.cabin_state = "idle"
        self.boarding_wait_remaining_seconds = 0.0
        self.return_remaining_seconds = 0.0
        self._sync_legacy_step_counters()

    def _update_cabin_positions(self) -> None:
        if not self.cabin_passengers:
            return
        duration = max(0.0, float(self._elevator_config.travel_seconds))
        ratio = (
            1.0
            if duration <= 1e-9
            else max(0.0, min(1.0, 1.0 - self.travel_remaining_seconds / duration))
        )
        self._set_cabin_positions(self._interpolated_vertical_position(ratio, 1))

    def _update_boarding_positions(self) -> None:
        if not self.cabin_passengers:
            return
        if self.boarding_remaining_steps <= 0:
            self.boarding_remaining_seconds = 0.0
        duration = max(0.0, float(self._elevator_config.boarding_seconds))
        ratio = (
            1.0
            if duration <= 1e-9
            else max(0.0, min(1.0, 1.0 - self.boarding_remaining_seconds / duration))
        )
        center = self.model.clamp_position(self.spec.position)
        for passenger in self.cabin_passengers:
            passenger_id = int(passenger.unique_id)
            start = self._boarding_start_positions[passenger_id]
            offset = self._cabin_offsets_by_passenger[passenger_id]
            destination = (center[0] + offset[0], center[1] + offset[1])
            passenger.pos = self.model.clamp_position(
                (
                    start[0] + (destination[0] - start[0]) * ratio,
                    start[1] + (destination[1] - start[1]) * ratio,
                )
            )

    def _set_cabin_positions(self, position: tuple[float, float]) -> None:
        if len(self._cabin_offsets_by_passenger) != len(self.cabin_passengers):
            self._assign_cabin_offsets()
        center = self.model.clamp_position(position)
        for passenger in self.cabin_passengers:
            offset = self._cabin_offsets_by_passenger[int(passenger.unique_id)]
            passenger.pos = self.model.clamp_position(
                (center[0] + offset[0], center[1] + offset[1])
            )

    def _assign_cabin_offsets(self) -> None:
        passenger_count = len(self.cabin_passengers)
        if passenger_count <= 0:
            self._cabin_offsets_by_passenger = {}
            return
        scenario = self.model.scenario
        spacing = max(
            0.4,
            float(scenario.jupedsim_agent_radius_units) * 2.2,
            float(getattr(scenario, "personal_space_units", 0.8)) * 0.5,
        )
        column_count = max(1, ceil(sqrt(passenger_count)))
        row_count = max(1, ceil(passenger_count / column_count))
        forward, lateral = self._release_axes()
        offsets: dict[int, tuple[float, float]] = {}
        for index, passenger in enumerate(self.cabin_passengers):
            row = index // column_count
            column = index % column_count
            forward_offset = (row - (row_count - 1) / 2.0) * spacing
            lateral_offset = (column - (column_count - 1) / 2.0) * spacing
            offsets[int(passenger.unique_id)] = (
                forward[0] * forward_offset + lateral[0] * lateral_offset,
                forward[1] * forward_offset + lateral[1] * lateral_offset,
            )
        self._cabin_offsets_by_passenger = offsets

