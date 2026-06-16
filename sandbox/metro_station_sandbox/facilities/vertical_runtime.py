from __future__ import annotations

from dataclasses import dataclass
from math import ceil, hypot
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
    total_steps: int
    progress_steps: float = 0.0


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

    def _finish_vertical_service(
        self,
        passenger: PassengerAgent,
        *,
        release_index: int = 0,
    ) -> None:
        release_position = self._vertical_release_position(passenger, release_index)
        passenger.passive_facility_service = False
        passenger.set_target(
            release_position,
            goal_kind="being_served",
            goal_label=self.spec.label,
            facility_id=self.spec.facility_id,
            stage=self.spec.stage,
        )
        passenger.pos = release_position
        passenger.advance_after_movement(True)
        self.served_persons += passenger.group_size

    def _vertical_release_position(
        self,
        passenger: PassengerAgent,
        release_index: int,
    ) -> tuple[float, float]:
        try:
            return self._release_position(passenger, release_index)
        except RuntimeError:
            return self._fallback_vertical_release_position(release_index)

    def _fallback_vertical_release_position(self, release_index: int) -> tuple[float, float]:
        base = self.spec.exit_position
        forward, lateral = self._release_axes()
        spacing = self._release_spacing()
        column_order = (0, -1, 1)[release_index % 3]
        row = release_index // 3
        min_distance = self._release_min_distance()
        for candidate in self._release_candidates(
            base,
            forward,
            lateral,
            spacing,
            column_order,
            row,
        ):
            projected = self._project_release_position(candidate)
            if not self._has_release_clearance(projected, min_distance):
                continue
            self._service_release_positions_this_tick.append(projected)
            return projected

        fallback = self._project_release_position(base)
        self._service_release_positions_this_tick.append(fallback)
        return fallback

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return any(ride.passenger is passenger for ride in self.active_rides)

    @property
    def active_ride_persons(self) -> int:
        return sum(ride.passenger.group_size for ride in self.active_rides)

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
                total_steps=ride_steps,
            )
        )

    def _advance_active_rides(self) -> None:
        remaining: list[ActiveVerticalRide] = []
        finished: list[ActiveVerticalRide] = []
        for ride in self.active_rides:
            ride.progress_steps = min(
                float(ride.total_steps),
                ride.progress_steps + self._ride_progress_steps_per_tick(ride),
            )
            ride.remaining_steps = max(0, ceil(ride.total_steps - ride.progress_steps))
            if ride.remaining_steps > 0:
                self._update_active_ride_position(ride)
                remaining.append(ride)
                continue
            finished.append(ride)
        self._service_release_positions_this_tick = []
        for release_index, ride in enumerate(finished):
            self._finish_vertical_service(ride.passenger, release_index=release_index)
        self.active_rides = remaining

    def _ride_progress_steps_per_tick(self, ride: ActiveVerticalRide) -> float:
        return 1.0

    def _update_active_ride_position(self, ride: ActiveVerticalRide) -> None:
        ride.passenger.pos = self.model.clamp_position(
            self._interpolated_vertical_position(ride.progress_steps, ride.total_steps)
        )

    def _interpolated_vertical_position(
        self,
        progress_steps: float,
        total_steps: int,
    ) -> tuple[float, float]:
        ratio = 1.0 if total_steps <= 0 else max(0.0, min(1.0, progress_steps / total_steps))
        sx, sy = self.spec.position
        ex, ey = self.spec.exit_position
        return (sx + (ex - sx) * ratio, sy + (ey - sy) * ratio)

    def finalize(self) -> None:
        self._service_release_positions_this_tick = []
        for release_index, ride in enumerate(list(self.active_rides)):
            self._finish_vertical_service(ride.passenger, release_index=release_index)
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
        ride_steps = self._ride_steps_for_mode()
        self._start_passive_ride(
            passenger,
            mode=self.mode.value,
            ride_steps=ride_steps,
        )

    def _ride_steps_for_mode(self) -> int:
        seconds = self._escalator_config.ride_time_seconds
        if seconds is None:
            return self._ride_steps_from_seconds(None)
        factor = ESCALATOR_SPEED_FACTOR_BY_MODE.get(self.mode, 1.0)
        return self._ride_steps_from_seconds(float(seconds) / max(0.001, factor))


class ElevatorProcessAgent(VerticalTransportProcessAgent):
    """Batch elevator process with cabin capacity, doors, travel, and unloading."""

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model, spec=spec)
        self.cabin_state = "idle"
        self.boarding_remaining_steps = 0
        self.boarding_wait_remaining_steps = 0
        self.travel_remaining_steps = 0
        self.unload_remaining_steps = 0
        self.return_remaining_steps = 0
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
    def return_steps(self) -> int:
        seconds = self._elevator_config.return_trip_seconds
        if seconds <= 0.0:
            return 0
        return max(1, round(seconds / self.model.scenario.tick_seconds))

    @property
    def boarding_wait_steps(self) -> int:
        return self.boarding_steps

    @property
    def cycle_steps(self) -> int:
        return self.travel_steps + self.unload_steps + self.return_steps

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._layout_queue()
        self._advance_cabin()
        if self.cabin_state in {"idle", "waiting"} and self.queue:
            self._start_boarding(
                force=self.cabin_state == "waiting" and self.boarding_wait_remaining_steps <= 0
            )
        elif self.cabin_state == "waiting" and not self.queue:
            self._finish_returning()

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return passenger in self.cabin_passengers

    def _advance_cabin(self) -> None:
        if self.cabin_state == "waiting":
            self.boarding_wait_remaining_steps -= 1
            self.cycle_remaining_steps = max(
                0,
                self.boarding_wait_remaining_steps + self.cycle_steps,
            )
            return

        if self.cabin_state == "boarding":
            self.boarding_remaining_steps -= 1
            if self.boarding_remaining_steps <= 0:
                self._depart_cabin()
            return

        if self.cabin_state == "moving":
            self.travel_remaining_steps -= 1
            self.cycle_remaining_steps = max(
                0,
                self.travel_remaining_steps
                + self.unload_remaining_steps
                + self.return_remaining_steps,
            )
            self._update_cabin_positions()
            if self.travel_remaining_steps <= 0:
                self._arrive_cabin()
            return

        if self.cabin_state == "unloading":
            self.unload_remaining_steps -= 1
            self.cycle_remaining_steps = max(
                0,
                self.unload_remaining_steps + self.return_remaining_steps,
            )
            if self.unload_remaining_steps <= 0:
                self._finish_unloading()
            return

        if self.cabin_state == "returning":
            self.return_remaining_steps -= 1
            self.cycle_remaining_steps = max(0, self.return_remaining_steps)
            if self.return_remaining_steps <= 0:
                self._finish_returning()

    def _start_boarding(self, *, force: bool = False) -> None:
        boarded, loaded_persons, blocked_by_unready = self._ready_boarding_batch()
        if not boarded:
            if force:
                self._finish_returning()
            return

        if (
            not force
            and blocked_by_unready
            and loaded_persons < self.cabin_capacity_persons
            and self.boarding_wait_steps > 0
        ):
            self._start_waiting_for_boarders()
            return

        self._begin_boarding(boarded, loaded_persons)

    def _ready_boarding_batch(self) -> tuple[list[PassengerAgent], int, bool]:
        loaded_persons = 0
        boarded: list[PassengerAgent] = []
        blocked_by_unready = False
        for passenger in self.queue:
            if not self._passenger_ready_for_service(passenger, release_index=len(boarded)):
                blocked_by_unready = True
                break
            would_exceed_capacity = (
                loaded_persons + passenger.group_size > self.cabin_capacity_persons
            )
            if would_exceed_capacity and boarded:
                break
            boarded.append(passenger)
            loaded_persons += passenger.group_size
            if loaded_persons >= self.cabin_capacity_persons:
                break
        return boarded, loaded_persons, blocked_by_unready

    def _start_waiting_for_boarders(self) -> None:
        if self.cabin_state != "waiting":
            self.boarding_wait_remaining_steps = self.boarding_wait_steps
            self.cabin_state = "waiting"
        self.cycle_remaining_steps = max(
            0,
            self.boarding_wait_remaining_steps + self.cycle_steps,
        )

    def _begin_boarding(
        self,
        boarded: list[PassengerAgent],
        loaded_persons: int,
    ) -> None:
        for _ in boarded:
            self.queue.pop(0)
        self.cabin_passengers = boarded
        self.cabin_load_persons = loaded_persons
        self.boarding_remaining_steps = self.boarding_steps
        self.boarding_wait_remaining_steps = 0
        self.travel_remaining_steps = self.travel_steps
        self.unload_remaining_steps = self.unload_steps
        self.return_remaining_steps = self.return_steps
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
        self._update_cabin_positions()

    def _arrive_cabin(self) -> None:
        self._set_cabin_positions(self.spec.exit_position)
        if self.unload_steps <= 0:
            self._finish_unloading()
            return
        self.cabin_state = "unloading"

    def _finish_unloading(self) -> None:
        self._service_release_positions_this_tick = []
        for release_index, passenger in enumerate(list(self.cabin_passengers)):
            self._finish_vertical_service(passenger, release_index=release_index)
        self.cabin_state = "returning" if self.return_steps > 0 else "idle"
        self.boarding_remaining_steps = 0
        self.travel_remaining_steps = 0
        self.unload_remaining_steps = 0
        self.return_remaining_steps = self.return_steps if self.cabin_state == "returning" else 0
        self.cycle_remaining_steps = self.return_remaining_steps
        self.cabin_passengers = []
        self.cabin_load_persons = 0
        self.active_event_id = None

    def _finish_returning(self) -> None:
        self.cabin_state = "idle"
        self.boarding_wait_remaining_steps = 0
        self.return_remaining_steps = 0
        self.cycle_remaining_steps = 0

    def _update_cabin_positions(self) -> None:
        if not self.cabin_passengers:
            return
        progress = self.travel_steps - max(0, self.travel_remaining_steps)
        self._set_cabin_positions(self._interpolated_vertical_position(progress, self.travel_steps))

    def _set_cabin_positions(self, position: tuple[float, float]) -> None:
        clamped = self.model.clamp_position(position)
        for passenger in self.cabin_passengers:
            passenger.pos = clamped

    def finalize(self) -> None:
        if self.cabin_passengers:
            self._finish_unloading()
        if self.cabin_state in {"waiting", "returning"}:
            self._finish_returning()


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

    def _serve_queue(self, train: TrainAgent | None = None) -> None:
        if not self.is_open:
            return

        self.service_credit += self._service_groups_per_tick()
        release_count = min(len(self.queue), int(self.service_credit))
        released = 0
        while self.queue and self.service_credit >= 1.0 and released < release_count:
            queue_index = self._next_ready_stairs_queue_index(release_count)
            if queue_index is None:
                break

            passenger = self.queue.pop(queue_index)
            try:
                self._start_service(
                    passenger,
                    train,
                    release_index=released,
                    release_count=max(1, release_count),
                )
            except RuntimeError:
                passenger.enter_facility_queue(self.spec)
                self.queue.insert(min(queue_index, len(self.queue)), passenger)
                break
            self.service_credit -= 1.0
            released += 1

    def _next_ready_stairs_queue_index(self, release_count: int) -> int | None:
        scan_limit = self._stairs_ready_scan_limit(release_count)
        for index, passenger in enumerate(self.queue[:scan_limit]):
            if self._stairs_passenger_ready_for_service(passenger, queue_index=index):
                return index
        return None

    def _stairs_ready_scan_limit(self, release_count: int) -> int:
        frontage = max(1, int(self.spec.queue_layout.per_row))
        credit_window = max(1, int(release_count) * 2)
        return min(len(self.queue), max(frontage, credit_window))

    def _stairs_passenger_ready_for_service(
        self,
        passenger: PassengerAgent,
        *,
        queue_index: int,
    ) -> bool:
        slot = self.spec.queue_layout.slot(queue_index)
        if hypot(passenger.pos[0] - slot[0], passenger.pos[1] - slot[1]) <= self._service_ready_radius():
            return True

        target = passenger.current_goal.target
        if target is None:
            return False
        return hypot(passenger.pos[0] - target[0], passenger.pos[1] - target[1]) <= self._service_ready_radius()

    @property
    def travel_speed_units_per_tick(self) -> float:
        return max(0.001, super().travel_speed_units_per_tick * self._fatigue_speed_factor())

    def _fatigue_speed_factor(self) -> float:
        return 1.0 / (1.0 + self.fatigue_cost)

    def _ride_progress_steps_per_tick(self, ride: ActiveVerticalRide) -> float:
        return self._stairs_conflict_speed_factor()

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
        if self.spec.direction == "up":
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
