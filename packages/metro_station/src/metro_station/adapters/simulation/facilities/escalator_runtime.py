from __future__ import annotations

from math import hypot
from typing import TYPE_CHECKING

import mesa
from .process import FacilitySpec
from .vertical import (
    ESCALATOR_SPEED_FACTOR_BY_MODE,
    EscalatorConfig,
    EscalatorMode,
    default_escalator_config,
)
from .vertical_transport_base import ActiveVerticalRide, VerticalTransportProcessAgent

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.transit import TrainAgent


class EscalatorProcessAgent(VerticalTransportProcessAgent):
    """Continuous-flow escalator process with explicit operating mode."""

    requires_exclusive_direction = True

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model, spec=spec)
        self.mode = self._escalator_config.default_mode

    @property
    def _escalator_config(self) -> EscalatorConfig:
        configured = self.spec.vertical_config.escalator if self.spec.vertical_config else None
        return configured or default_escalator_config(self.spec.service_persons_per_min)

    @property
    def is_open(self) -> bool:
        return super().is_open and self.mode != EscalatorMode.BLOCKED

    @property
    def is_available_for_choice(self) -> bool:
        return self.is_open and self.effective_service_persons_per_min > 0

    @property
    def effective_service_persons_per_min(self) -> float:
        return float(self._escalator_config.capacity_for_mode(self.mode))

    @property
    def travel_speed_m_s(self) -> float:
        factor = ESCALATOR_SPEED_FACTOR_BY_MODE.get(self.mode, 1.0)
        return max(0.001, super().travel_speed_m_s * factor)

    @property
    def routing_traversal_seconds(self) -> float:
        """Use the same configured/mode-adjusted duration as actual service."""

        return self._ride_duration_seconds_for_mode()

    def set_mode(self, new_mode: EscalatorMode | str) -> None:
        self.mode = (
            new_mode if isinstance(new_mode, EscalatorMode) else EscalatorMode(str(new_mode))
        )
        if self.mode == EscalatorMode.BLOCKED:
            self._withdraw_physical_resource_request()
            self.service_credit = 0.0

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        if self.is_forced_disabled:
            self.outage_person_seconds += (
                self.active_ride_persons * self._process_interval_seconds()
            )
        self._advance_active_rides()
        # Publish final ride poses before moving the landing queue so the two
        # physical domains share one same-tick body-clearance invariant.
        self._layout_queue()
        self._serve_queue(train)

    def _ride_progress_steps_per_tick(self, ride: ActiveVerticalRide) -> float:
        if not self.is_forced_disabled:
            return 1.0
        normal_speed = max(0.001, self.travel_speed_m_s)
        walking_speed = max(
            0.001,
            float(self.model.scenario.stopped_escalator_walk_speed_m_s),
        )
        return max(0.1, min(1.0, walking_speed / normal_speed))

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> None:
        ride_steps = self._ride_steps_for_mode()
        self._start_passive_ride(
            passenger,
            mode=self.mode.value,
            ride_steps=ride_steps,
            ride_duration_seconds=self._ride_duration_seconds_for_mode(),
            # One mechanical lane has one longitudinal entry portal.  Service
            # credit may exceed one group in a one-second process interval,
            # but a follower must first compact to that same portal rather
            # than boarding directly from queue slot 1.
            release_index=0,
            release_count=1,
        )

    def _start_passive_ride(
        self,
        passenger: PassengerAgent,
        *,
        mode: str | None,
        ride_steps: int,
        ride_duration_seconds: float | None = None,
        release_index: int = 0,
        release_count: int = 1,
        board_end_time: float | None = None,
        arrive_time: float | None = None,
    ) -> None:
        if not self.queue.consume_service_handoff(passenger):
            raise RuntimeError(
                f"passenger {passenger.unique_id} does not own the queue-head "
                f"handoff for escalator {self.facility_id!r}"
            )
        if not self._passenger_at_mechanical_entry(passenger):
            raise RuntimeError(
                f"passenger {passenger.unique_id} cannot start escalator "
                f"{self.facility_id!r} away from its service portal"
            )
        super()._start_passive_ride(
            passenger,
            mode=mode,
            ride_steps=ride_steps,
            ride_duration_seconds=ride_duration_seconds,
            release_index=release_index,
            release_count=release_count,
            board_end_time=board_end_time,
            arrive_time=arrive_time,
        )

    def _can_start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> bool:
        if not self._passenger_at_mechanical_entry(passenger):
            self._withdraw_physical_resource_request()
            return False
        return super()._can_start_service(
            passenger,
            train,
            release_index=release_index,
            release_count=release_count,
        )

    def _passenger_at_mechanical_entry(self, passenger: PassengerAgent) -> bool:
        target = self._service_entry_position(0)
        return hypot(
            passenger.pos[0] - target[0],
            passenger.pos[1] - target[1],
        ) <= 0.12

    def _ride_steps_for_mode(self) -> int:
        return self._ride_steps_from_seconds(self._ride_duration_seconds_for_mode())

    def _ride_duration_seconds_for_mode(self) -> float:
        seconds = self._escalator_config.ride_time_seconds
        if seconds is None:
            return self._ride_duration_seconds(None)
        factor = ESCALATOR_SPEED_FACTOR_BY_MODE.get(self.mode, 1.0)
        return float(seconds) / max(0.001, factor)
