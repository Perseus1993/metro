from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import TYPE_CHECKING

import mesa
from .process import FacilitySpec
from .runtime_base import FacilityProcessAgent
from .service_events import FacilityServiceEvent
from .vertical import (
    ESCALATOR_SPEED_FACTOR_BY_MODE,
    ElevatorConfig,
    EscalatorConfig,
    EscalatorMode,
    StairsConfig,
    default_elevator_config,
    default_escalator_config,
    default_stairs_config,
)

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.transit import TrainAgent


@dataclass
class ActiveVerticalRide:
    passenger: PassengerAgent
    event_id: int
    remaining_steps: int


class VerticalTransportProcessAgent(FacilityProcessAgent):
    """Base process for vertical passenger movers."""

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model, spec=spec)
        self.active_rides: list[ActiveVerticalRide] = []

    def _active_state(self) -> str:
        return "running"

    @property
    def travel_speed_units_per_tick(self) -> float:
        return self.spec.speed_units_per_tick or self.model.scenario.walk_units_per_tick

    def _ride_steps_from_seconds(self, seconds: float | None) -> int:
        if seconds is not None:
            return max(1, round(float(seconds) / self.model.scenario.tick_seconds))
        distance = hypot(
            self.spec.exit_position[0] - self.spec.position[0],
            self.spec.exit_position[1] - self.spec.position[1],
        )
        return max(1, round(distance / max(0.001, self.travel_speed_units_per_tick)))

    def _begin_passive_vertical_service(self, passenger: PassengerAgent) -> None:
        passenger.begin_facility_service(self.spec)
        passenger.passive_facility_service = True
        passenger.set_target(
            self.spec.exit_position,
            goal_kind="being_served",
            goal_label=self.spec.label,
            facility_id=self.spec.facility_id,
            stage=self.spec.stage,
        )
        passenger.pos = self.model.clamp_position(self.spec.position)

    def _finish_vertical_service(self, passenger: PassengerAgent) -> None:
        passenger.passive_facility_service = False
        passenger.set_target(
            self.spec.exit_position,
            goal_kind="being_served",
            goal_label=self.spec.label,
            facility_id=self.spec.facility_id,
            stage=self.spec.stage,
        )
        passenger.pos = self.model.clamp_position(self.spec.exit_position)
        passenger.advance_after_movement(True)
        self.served_persons += passenger.group_size

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return any(ride.passenger is passenger for ride in self.active_rides)

    def _start_passive_ride(
        self,
        passenger: PassengerAgent,
        *,
        mode: str | None,
        ride_steps: int,
        board_end_time: float | None = None,
        arrive_time: float | None = None,
    ) -> None:
        self._begin_passive_vertical_service(passenger)
        start_time = self.model.current_time_seconds
        end_time = start_time + ride_steps * self.model.scenario.tick_seconds
        event_id = self._record_vertical_event(
            passengers=[passenger],
            mode=mode,
            start_time=start_time,
            board_end_time=board_end_time,
            arrive_time=arrive_time,
            end_time=end_time,
        )
        self.active_rides.append(
            ActiveVerticalRide(
                passenger=passenger,
                event_id=event_id,
                remaining_steps=ride_steps,
            )
        )

    def _advance_active_rides(self) -> None:
        remaining: list[ActiveVerticalRide] = []
        for ride in self.active_rides:
            ride.remaining_steps -= 1
            if ride.remaining_steps > 0:
                remaining.append(ride)
                continue
            self._finish_vertical_service(ride.passenger)
        self.active_rides = remaining

    def finalize(self) -> None:
        for ride in list(self.active_rides):
            self._finish_vertical_service(ride.passenger)
        self.active_rides = []

    def _record_vertical_event(
        self,
        *,
        passengers: list[PassengerAgent],
        mode: str | None,
        start_time: float,
        end_time: float,
        board_end_time: float | None = None,
        arrive_time: float | None = None,
    ) -> int:
        event = FacilityServiceEvent(
            event_id=self.model.next_facility_service_event_id(),
            facility_id=self.facility_id,
            facility_kind=self.spec.kind,
            mode=mode,
            passenger_ids=tuple(int(passenger.unique_id) for passenger in passengers),
            start_time=start_time,
            board_end_time=board_end_time,
            arrive_time=arrive_time,
            end_time=end_time,
            start_position=self.spec.position,
            end_position=self.spec.exit_position,
            direction=self.spec.direction,
            from_level=self.spec.entry_level_id,
            to_level=self.spec.exit_level_id,
        )
        self.model.record_facility_service_event(event)
        return event.event_id


class EscalatorProcessAgent(VerticalTransportProcessAgent):
    """Continuous-flow escalator process with explicit operating mode."""

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
    def travel_speed_units_per_tick(self) -> float:
        factor = ESCALATOR_SPEED_FACTOR_BY_MODE.get(self.mode, 1.0)
        return max(0.001, super().travel_speed_units_per_tick * factor)

    def set_mode(self, new_mode: EscalatorMode | str) -> None:
        self.mode = new_mode if isinstance(new_mode, EscalatorMode) else EscalatorMode(str(new_mode))
        if self.mode == EscalatorMode.BLOCKED:
            self.service_credit = 0.0

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._layout_queue()
        self._advance_active_rides()
        self._serve_queue(train)

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> None:
        ride_steps = self._ride_steps_from_seconds(self._escalator_config.ride_time_seconds)
        self._start_passive_ride(
            passenger,
            mode=self.mode.value,
            ride_steps=ride_steps,
        )


class ElevatorProcessAgent(VerticalTransportProcessAgent):
    """Batch elevator process with cabin capacity, doors, travel, and unloading."""

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model, spec=spec)
        self.cabin_state = "idle"
        self.boarding_remaining_steps = 0
        self.travel_remaining_steps = 0
        self.unload_remaining_steps = 0
        self.cycle_remaining_steps = 0
        self.cabin_passengers: list[PassengerAgent] = []
        self.cabin_load_persons = 0
        self.departed_cabins = 0
        self.last_departure_step: int | None = None
        self.last_departure_load_persons = 0
        self.active_event_id: int | None = None

    @property
    def _elevator_config(self) -> ElevatorConfig:
        configured = self.spec.vertical_config.elevator if self.spec.vertical_config else None
        if configured is not None:
            return configured
        scenario = self.model.scenario
        unload_seconds = getattr(scenario, "elevator_unload_seconds", 0.0)
        return default_elevator_config(
            batch_capacity=scenario.elevator_cabin_capacity_persons,
            boarding_seconds=scenario.elevator_boarding_seconds,
            travel_seconds=scenario.elevator_cycle_seconds,
            unload_seconds=unload_seconds,
        )

    @property
    def effective_service_persons_per_min(self) -> float:
        cycle = max(0.001, self._elevator_config.cycle_seconds)
        return self.cabin_capacity_persons * 60.0 / cycle

    @property
    def cabin_capacity_persons(self) -> int:
        return max(1, int(self._elevator_config.batch_capacity))

    @property
    def boarding_steps(self) -> int:
        return max(1, round(self._elevator_config.boarding_seconds / self.model.scenario.tick_seconds))

    @property
    def travel_steps(self) -> int:
        return max(1, round(self._elevator_config.travel_seconds / self.model.scenario.tick_seconds))

    @property
    def unload_steps(self) -> int:
        seconds = self._elevator_config.unload_seconds
        if seconds <= 0.0:
            return 0
        return max(1, round(seconds / self.model.scenario.tick_seconds))

    @property
    def cycle_steps(self) -> int:
        return self.travel_steps + self.unload_steps

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._layout_queue()
        self._advance_cabin()
        if self.cabin_state == "idle" and self.queue:
            self._start_boarding()

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return passenger in self.cabin_passengers

    def _advance_cabin(self) -> None:
        if self.cabin_state == "boarding":
            self.boarding_remaining_steps -= 1
            if self.boarding_remaining_steps <= 0:
                self._depart_cabin()
            return

        if self.cabin_state == "moving":
            self.travel_remaining_steps -= 1
            self.cycle_remaining_steps = max(0, self.travel_remaining_steps + self.unload_remaining_steps)
            if self.travel_remaining_steps <= 0:
                self._arrive_cabin()
            return

        if self.cabin_state == "unloading":
            self.unload_remaining_steps -= 1
            self.cycle_remaining_steps = max(0, self.unload_remaining_steps)
            if self.unload_remaining_steps <= 0:
                self._finish_unloading()

    def _start_boarding(self) -> None:
        loaded_persons = 0
        boarded: list[PassengerAgent] = []
        while self.queue:
            passenger = self.queue[0]
            if not self._passenger_ready_for_service(passenger, release_index=len(boarded)):
                break
            would_exceed_capacity = (
                loaded_persons + passenger.group_size > self.cabin_capacity_persons
            )
            if would_exceed_capacity and boarded:
                break
            boarded.append(self.queue.pop(0))
            loaded_persons += passenger.group_size
            if loaded_persons >= self.cabin_capacity_persons:
                break

        if not boarded:
            return

        self.cabin_passengers = boarded
        self.cabin_load_persons = loaded_persons
        self.boarding_remaining_steps = self.boarding_steps
        self.travel_remaining_steps = self.travel_steps
        self.unload_remaining_steps = self.unload_steps
        self.cycle_remaining_steps = self.cycle_steps
        self.cabin_state = "boarding"

        for passenger in self.cabin_passengers:
            self._begin_passive_vertical_service(passenger)

        start_time = self.model.current_time_seconds
        board_end = start_time + self.boarding_steps * self.model.scenario.tick_seconds
        arrive = board_end + self.travel_steps * self.model.scenario.tick_seconds
        end = arrive + self.unload_steps * self.model.scenario.tick_seconds
        self.active_event_id = self._record_vertical_event(
            passengers=self.cabin_passengers,
            mode="batch",
            start_time=start_time,
            board_end_time=board_end,
            arrive_time=arrive,
            end_time=end,
        )

    def _depart_cabin(self) -> None:
        self.last_departure_load_persons = self.cabin_load_persons
        self.last_departure_step = self.model.step_index
        self.departed_cabins += 1
        self.cabin_state = "moving"

    def _arrive_cabin(self) -> None:
        if self.unload_steps <= 0:
            self._finish_unloading()
            return
        self.cabin_state = "unloading"

    def _finish_unloading(self) -> None:
        for passenger in list(self.cabin_passengers):
            self._finish_vertical_service(passenger)
        self.cabin_state = "idle"
        self.boarding_remaining_steps = 0
        self.travel_remaining_steps = 0
        self.unload_remaining_steps = 0
        self.cycle_remaining_steps = 0
        self.cabin_passengers = []
        self.cabin_load_persons = 0
        self.active_event_id = None

    def finalize(self) -> None:
        if self.cabin_passengers:
            self._finish_unloading()


class StairsProcessAgent(VerticalTransportProcessAgent):
    """Directed stairs process with fatigue cost and bidirectional conflict."""

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._layout_queue()
        self._advance_active_rides()
        self._serve_queue(train)

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> None:
        self._start_passive_ride(
            passenger,
            mode="walk",
            ride_steps=self._ride_steps_from_seconds(None),
        )

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
        sibling = self._opposing_stairs()
        if sibling is None:
            return base
        opposing = sibling.queue_persons
        own = self.queue_persons
        opposing_ratio = opposing / max(1.0, opposing + own + 1.0)
        factor = 1.0 - opposing_ratio * self._stairs_config.bidirectional_conflict_factor
        return max(1.0, base * factor)

    @property
    def fatigue_cost(self) -> float:
        if self.spec.direction == "up":
            return self._stairs_config.fatigue_cost_up
        return self._stairs_config.fatigue_cost_down

    def _opposing_stairs(self) -> StairsProcessAgent | None:
        sibling_id = self._stairs_config.sibling_facility_id
        if sibling_id is None:
            return None
        sibling = self.model.facilities_by_id.get(sibling_id)
        if isinstance(sibling, StairsProcessAgent):
            return sibling
        return None
