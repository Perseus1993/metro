from __future__ import annotations

import mesa

from metro_station.domain.time_boundaries import (
    first_step_not_before,
    positive_steps_to_cover,
)

from ..planning.plan import AgentState
from .base import StationAgent
from .passenger import PassengerAgent


class TrainAgent(StationAgent):
    """A periodic train event with dwell and capacity constraints."""

    def __init__(
        self,
        model: mesa.Model,
        *,
        line_id: str = "default",
        direction: str = "down",
        platform_id: str = "platform:default:down",
    ) -> None:
        super().__init__(model)
        scenario = self.model.scenario
        self.line_id = line_id
        self.direction = direction
        self.platform_id = platform_id
        self.state = "away"
        self.next_arrival_step = first_step_not_before(
            scenario.initial_train_offset_seconds,
            scenario.tick_seconds,
        )
        self.close_step: int | None = None
        self.arrival_step: int | None = None
        self._legacy_current_load_persons = 0
        self._legacy_reserved_boarding_persons = 0
        self.last_departed_load_persons = 0
        self.departed_trains = 0
        self.cancelled_trains = 0
        self.last_cancelled_arrival_step: int | None = None
        self.last_departure_step: int | None = None
        self.arrival_sequence = 0
        self.departure_safety_hold_steps = 0

    @property
    def is_boarding(self) -> bool:
        return self.state == "boarding"

    @property
    def current_load_persons(self) -> int:
        lookup = getattr(self.model, "train_exchange_current_onboard_persons", None)
        if self.is_boarding and callable(lookup):
            current = lookup(self)
            if current is not None:
                return int(current)
        return int(self._legacy_current_load_persons)

    @current_load_persons.setter
    def current_load_persons(self, persons: int) -> None:
        self._legacy_current_load_persons = int(persons)

    @property
    def reserved_boarding_persons(self) -> int:
        lookup = getattr(self.model, "train_exchange_reserved_boarding_persons", None)
        if self.is_boarding and callable(lookup):
            reserved = lookup(self)
            if reserved is not None:
                return int(reserved)
        return int(self._legacy_reserved_boarding_persons)

    @reserved_boarding_persons.setter
    def reserved_boarding_persons(self, persons: int) -> None:
        self._legacy_reserved_boarding_persons = int(persons)

    @property
    def capacity_remaining(self) -> int:
        lookup = getattr(self.model, "train_boarding_capacity_remaining", None)
        if self.is_boarding and callable(lookup):
            remaining = lookup(self)
            if remaining is not None:
                return int(remaining)
        capacity = self.model.train_capacity_for_platform(self.platform_id)
        return max(
            0,
            capacity - self.current_load_persons - self.reserved_boarding_persons,
        )

    def reserve_boarding_capacity(self, persons: int) -> None:
        reserve = getattr(self.model, "reserve_train_boarding_capacity", None)
        if not callable(reserve):
            raise RuntimeError("train boarding requires a capacity-ledger reservation")
        reserve(self, int(persons))

    def commit_boarding_capacity(self, persons: int) -> None:
        commit = getattr(self.model, "commit_train_boarding", None)
        if not callable(commit):
            raise RuntimeError("train boarding requires a capacity-ledger commit")
        commit(self, int(persons))

    def step(self) -> None:
        step = self.model.step_index

        if self.state == "away" and step >= self.next_arrival_step:
            if self.next_arrival_step > self.model.scenario.demand_steps:
                return
            if self._service_suspended():
                self.cancelled_trains += 1
                self.last_cancelled_arrival_step = step
                self.next_arrival_step = step + self._headway_steps()
                self._record_train_event("record_train_arrival_cancelled")
                return
            self.state = "boarding"
            self.current_load_persons = 0
            if self.reserved_boarding_persons:
                raise RuntimeError("new train arrived with stale boarding reservations")
            self.arrival_sequence += 1
            self.arrival_step = step
            self.close_step = step + self._dwell_steps()
            self._record_train_event("record_train_arrival")
            return

        if self.state == "boarding" and self.close_step is not None and step >= self.close_step:
            if self._has_active_door_crossing():
                # A body already committed to the doorway is a train-safety
                # boundary, not extra scheduled dwell. Keep the train berthed
                # and account the explicit overrun until the physical crossing
                # completes; no new boarding can pass the close-time preflight.
                self.departure_safety_hold_steps += 1
                return
            close_exchange = getattr(self.model, "close_train_exchange_for_departure", None)
            if callable(close_exchange) and not close_exchange(self, step=step):
                return
            self.state = "away"
            self.last_departed_load_persons = self.current_load_persons
            self.current_load_persons = 0
            self.departed_trains += 1
            self.last_departure_step = step
            self.next_arrival_step = step + self._layover_steps()
            self.close_step = None
            self.arrival_step = None

    def _has_active_door_crossing(self) -> bool:
        doors_for_train = getattr(self.model, "boarding_doors_for_train", None)
        if not callable(doors_for_train):
            return False
        return any(
            active.train is self and active.train_arrival_sequence == self.arrival_sequence
            for door in doors_for_train(self)
            for active in getattr(door, "active_boardings", ())
        )

    def _service_suspended(self) -> bool:
        check = getattr(self.model, "is_train_service_suspended", None)
        return bool(callable(check) and check(self.platform_id))

    def _record_train_event(self, method_name: str) -> None:
        recorder = getattr(self.model, method_name, None)
        if callable(recorder):
            recorder(self)

    def _dwell_steps(self) -> int:
        scenario = self.model.scenario
        return positive_steps_to_cover(
            scenario.train_dwell_seconds,
            scenario.tick_seconds,
        )

    def _headway_steps(self) -> int:
        scenario = self.model.scenario
        return positive_steps_to_cover(
            scenario.train_headway_seconds,
            scenario.tick_seconds,
        )

    def _layover_steps(self) -> int:
        return max(1, self._headway_steps() - self._dwell_steps())


class PlatformAgent(StationAgent):
    """Station platform resource agent that owns waiting and boarding."""

    def __init__(
        self,
        model: mesa.Model,
        *,
        platform_id: str = "platform:default:down",
        line_id: str = "default",
        direction: str = "down",
    ) -> None:
        super().__init__(model)
        self.platform_id = platform_id
        self.line_id = line_id
        self.direction = direction
        self.state = "normal"
        self.waiting: list[PassengerAgent] = []

    @property
    def waiting_persons(self) -> int:
        return sum(passenger.group_size for passenger in self.waiting)

    @property
    def capacity_remaining(self) -> int:
        capacity = self.model.scenario.platform_capacity_persons
        door_queue = sum(
            door.queue_persons for door in self.model.boarding_doors_for_platform(self)
        )
        return max(0, capacity - self.waiting_persons - door_queue)

    def join_waiting(self, passenger: PassengerAgent) -> None:
        self._assign_passenger_platform(passenger)
        if passenger in self.waiting:
            self.waiting.remove(passenger)

        self._set_waiting_state(passenger)
        self.waiting.append(passenger)
        self._notify_graph_train_available(passenger)
        if passenger.state != AgentState.WAITING_PLATFORM.value and passenger in self.waiting:
            self.waiting.remove(passenger)

    def _set_waiting_state(self, passenger: PassengerAgent) -> None:
        passenger.state = AgentState.WAITING_PLATFORM.value
        passenger.plan.set_goal(
            kind="waiting",
            label="platform waiting area",
            target=passenger.pos,
        )

    def _assign_passenger_platform(self, passenger: PassengerAgent) -> None:
        passenger.assigned_platform_id = self.platform_id
        passenger.assigned_line_id = self.line_id
        passenger.assigned_direction = self.direction

    def _sync_passenger_level_to_platform(
        self,
        passenger: PassengerAgent,
        doors,
    ) -> None:
        for door in doors:
            if door.spec.entry_level_id is not None:
                passenger.current_level_id = door.spec.entry_level_id
                return

    def _layout_waiting(self) -> None:
        speed = self._waiting_layout_speed_units_per_tick()
        occupied_positions: list[tuple[float, float]] = []
        for passenger in self.waiting:
            target = self.model._reserve_platform_waiting_slot(passenger, self)
            passenger.set_passive_layout_target(
                target,
                goal_kind="waiting",
                goal_label="platform waiting slot",
            )
            passenger.move_directly_toward_target(
                speed,
                occupied_positions=occupied_positions,
            )
            occupied_positions.append(passenger.pos)

    def _waiting_layout_speed_units_per_tick(self) -> float:
        scenario = self.model.scenario
        configured = float(scenario.walk_units_per_tick)
        physical = float(scenario.jupedsim_desired_speed_mps) * float(scenario.tick_seconds)
        if not self.model.simulation_clock.research_valid:
            return max(0.1, configured)
        return max(0.1, min(configured, physical))

    def step(self) -> None:
        self._notify_queued_graph_train_available()
        self._retry_boarding_door_assignment()
        self._layout_waiting()

    def _retry_boarding_door_assignment(self) -> None:
        if not self.waiting:
            return
        if not self.model.boarding_doors_for_platform(self):
            return

        for passenger in tuple(self.waiting):
            if passenger.state != AgentState.WAITING_PLATFORM.value:
                self.waiting.remove(passenger)
                self.model._clear_platform_waiting_reservation(passenger)
                continue

            self._assign_passenger_platform(passenger)
            self._sync_passenger_level_to_platform(
                passenger,
                self.model.boarding_doors_for_platform(self),
            )
            self._notify_graph_train_available(passenger)
            if (
                passenger.state != AgentState.WAITING_PLATFORM.value
                and passenger in self.waiting
            ):
                self.waiting.remove(passenger)

    def _notify_graph_train_available(self, passenger: PassengerAgent) -> None:
        if self.model.boarding_train_for_platform(self) is None:
            return
        self.model.goal_coordinator.poll(passenger)

    def _notify_queued_graph_train_available(self) -> None:
        if self.model.boarding_train_for_platform(self) is None:
            return
        for door in self.model.boarding_doors_for_platform(self):
            for passenger in door.queue:
                self.model.goal_coordinator.poll(passenger)
