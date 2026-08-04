from __future__ import annotations

from math import hypot
from typing import TYPE_CHECKING

from .vertical import (
    StairsConfig,
    default_stairs_config,
)
from .vertical_transport_base import ActiveVerticalRide, VerticalTransportProcessAgent

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.transit import TrainAgent


class StairsProcessAgent(VerticalTransportProcessAgent):
    """Directed stairs process with fatigue cost and bidirectional conflict."""

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._advance_active_rides()
        # Queue compaction must observe the authoritative end-of-interval ride
        # poses.  Laying out first lets a rider subsequently sweep back toward
        # a waiting body in the same tick.
        self._layout_queue()
        self._serve_queue(train)

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> None:
        ride_duration_seconds = self._ride_duration_seconds(None)
        self._start_passive_ride(
            passenger,
            mode="walk",
            ride_steps=self._ride_steps_from_seconds(ride_duration_seconds),
            ride_duration_seconds=ride_duration_seconds,
            release_index=release_index,
            release_count=release_count,
        )

    def _serve_queue(self, train: TrainAgent | None = None) -> None:
        if not self.is_open:
            return

        self.service_credit += self._service_groups_per_tick()
        release_count = min(
            len(self.queue),
            int(self.service_credit),
            self._physical_lane_capacity(),
        )
        released = 0
        while self.queue and self.service_credit >= 1.0 and released < release_count:
            passenger = self.queue[0]
            if not self._stairs_passenger_ready_for_service(
                passenger,
                release_index=released,
            ):
                break

            passenger = self.queue.pop(0)
            try:
                self._start_service(
                    passenger,
                    train,
                    release_index=released,
                    release_count=max(1, release_count),
                )
            except RuntimeError:
                passenger.enter_facility_queue(self.spec)
                self.queue.insert(0, passenger)
                break
            self.service_credit -= 1.0
            released += 1

    def _stairs_passenger_ready_for_service(
        self,
        passenger: PassengerAgent,
        *,
        release_index: int,
    ) -> bool:
        slot = self._service_entry_position(release_index)
        return (
            hypot(passenger.pos[0] - slot[0], passenger.pos[1] - slot[1])
            <= self._service_ready_radius()
            and self._connector_entry_has_clearance(passenger)
        )

    @property
    def travel_speed_m_s(self) -> float:
        return max(0.001, super().travel_speed_m_s * self._fatigue_speed_factor())

    def _fatigue_speed_factor(self) -> float:
        return 1.0 / (1.0 + self.fatigue_cost)

    def _ride_progress_steps_per_tick(self, ride: ActiveVerticalRide) -> float:
        return self._stairs_conflict_speed_factor()

    @property
    def routing_traversal_seconds(self) -> float:
        """Match actual ride progress under current opposing stair flow."""

        return super().routing_traversal_seconds / self._stairs_conflict_speed_factor()

    @property
    def _stairs_config(self) -> StairsConfig:
        configured = self.spec.vertical_config.stairs if self.spec.vertical_config else None
        if configured is not None:
            return configured
        scenario = self.model.scenario
        return default_stairs_config(
            base_capacity_ppm=self.spec.service_persons_per_min,
            fatigue_cost_up=scenario.stair_fatigue_cost_up,
            fatigue_cost_down=scenario.stair_fatigue_cost_down,
            bidirectional_conflict_factor=scenario.stair_bidirectional_conflict_factor,
        )

    @property
    def effective_service_persons_per_min(self) -> float:
        base = float(self._stairs_config.base_capacity_ppm)
        return max(1.0, base * self._stairs_conflict_speed_factor())

    @property
    def fatigue_cost(self) -> float:
        if self.portal_direction == "up":
            return self._stairs_config.fatigue_cost_up
        return self._stairs_config.fatigue_cost_down

    def _stairs_conflict_speed_factor(self) -> float:
        sibling = self._opposing_stairs()
        if sibling is None:
            return 1.0
        opposing = sibling.queue_persons + sibling.active_ride_persons
        own = self.queue_persons + self.active_ride_persons
        opposing_ratio = opposing / max(1.0, opposing + own + 1.0)
        factor = 1.0 - opposing_ratio * self._stairs_config.bidirectional_conflict_factor
        return max(0.1, factor)

    def _opposing_stairs(self) -> StairsProcessAgent | None:
        sibling_id = self._stairs_config.sibling_facility_id
        if sibling_id is None:
            return None
        sibling = self.model.facilities_by_id.get(sibling_id)
        if isinstance(sibling, StairsProcessAgent):
            return sibling
        return None
