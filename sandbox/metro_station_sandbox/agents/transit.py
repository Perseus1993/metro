from __future__ import annotations

import mesa

from .base import StationAgent
from .passenger import PassengerAgent
from ..planning.plan import AgentState, FacilityStage


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
        self.next_arrival_step = max(
            1, round(scenario.initial_train_offset_seconds / scenario.tick_seconds)
        )
        self.close_step: int | None = None
        self.current_load_persons = 0
        self.last_departed_load_persons = 0
        self.departed_trains = 0
        self.last_departure_step: int | None = None

    @property
    def is_boarding(self) -> bool:
        return self.state == "boarding"

    @property
    def capacity_remaining(self) -> int:
        return max(0, self.model.scenario.train_capacity_persons - self.current_load_persons)

    def step(self) -> None:
        step = self.model.step_index

        if self.state == "away" and step >= self.next_arrival_step:
            self.state = "boarding"
            self.current_load_persons = 0
            self.close_step = step + self._dwell_steps()
            return

        if self.state == "boarding" and self.close_step is not None and step >= self.close_step:
            self.state = "away"
            self.last_departed_load_persons = self.current_load_persons
            self.departed_trains += 1
            self.last_departure_step = step
            self.next_arrival_step = step + self._layover_steps()
            self.close_step = None

    def _dwell_steps(self) -> int:
        scenario = self.model.scenario
        return max(1, round(scenario.train_dwell_seconds / scenario.tick_seconds))

    def _headway_steps(self) -> int:
        scenario = self.model.scenario
        return max(1, round(scenario.train_headway_seconds / scenario.tick_seconds))

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

        doors = self.model.boarding_doors_for_platform(self)
        if doors:
            self._sync_passenger_level_to_platform(passenger, doors)
            passenger.assigned_facility_id = None
            facility = self.model.request_facility_choice(
                passenger,
                FacilityStage.BOARDING_DOOR,
            )
            if facility is not None and passenger.state == AgentState.QUEUEING_DOOR.value:
                return

        passenger.state = AgentState.WAITING_PLATFORM.value
        passenger.plan.set_goal(
            kind="waiting",
            label="platform waiting area",
            target=passenger.pos,
        )
        if passenger not in self.waiting:
            self.waiting.append(passenger)

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
        for index, passenger in enumerate(self.waiting):
            passenger.set_target(
                self.model.layout_graph.platform_waiting_position(index),
                goal_kind="waiting",
                goal_label="platform waiting slot",
            )
            passenger.move_directly_toward_target(
                speed,
                occupied_positions=occupied_positions,
            )
            occupied_positions.append(passenger.pos)

    def _waiting_layout_speed_units_per_tick(self) -> float:
        return max(0.1, float(self.model.scenario.walk_units_per_tick))

    def step(self) -> None:
        self._retry_boarding_door_assignment()
        self._rebalance_closed_boarding_door_queues()
        self._layout_waiting()

    def _retry_boarding_door_assignment(self) -> None:
        if not self.waiting:
            return
        if not self.model.boarding_doors_for_platform(self):
            return

        for passenger in tuple(self.waiting):
            if passenger.state != AgentState.WAITING_PLATFORM.value:
                self.waiting.remove(passenger)
                continue

            self._assign_passenger_platform(passenger)
            self._sync_passenger_level_to_platform(passenger, self.model.boarding_doors_for_platform(self))
            passenger.assigned_facility_id = None
            facility = self.model.request_facility_choice(passenger, FacilityStage.BOARDING_DOOR)
            if facility is None or passenger.state != AgentState.QUEUEING_DOOR.value:
                continue
            if passenger in self.waiting:
                self.waiting.remove(passenger)

    def _rebalance_closed_boarding_door_queues(self) -> None:
        doors = self.model.boarding_doors_for_platform(self)
        if len(doors) < 2:
            return
        if self.model.boarding_train_for_platform(self) is not None:
            return

        max_moves = sum(len(door.queue) for door in doors)
        for _ in range(max_moves):
            donor = max(doors, key=lambda door: len(door.queue))
            receiver = min(doors, key=lambda door: len(door.queue))
            if len(donor.queue) - len(receiver.queue) <= 1:
                return

            passenger = donor.queue.pop()
            receiver.join_queue(passenger)
            passenger.last_replan_reason = "boarding_door_closed_rebalance"
            self.model.audit.record(
                "passenger_rebalanced_boarding_door",
                source="platform",
                severity="info",
                step=self.model.step_index,
                context={
                    "passenger_id": passenger.unique_id,
                    "platform_id": self.platform_id,
                    "from_facility_id": donor.facility_id,
                    "to_facility_id": receiver.facility_id,
                },
            )
