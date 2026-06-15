from __future__ import annotations

import mesa

from .base import StationAgent
from .passenger import PassengerAgent
from ..facilities.runtime import FacilityProcessAgent
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
        passenger.state = AgentState.WAITING_PLATFORM.value
        passenger.assigned_platform_id = self.platform_id
        passenger.assigned_line_id = self.line_id
        passenger.assigned_direction = self.direction
        passenger.plan.set_goal(
            kind="waiting",
            label="platform waiting area",
            target=passenger.pos,
        )
        if passenger not in self.waiting:
            self.waiting.append(passenger)

    def _layout_waiting(self) -> None:
        speed = self._waiting_layout_speed_units_per_tick()
        for index, passenger in enumerate(self.waiting):
            passenger.set_target(
                self.model.layout_graph.platform_waiting_position(index),
                goal_kind="waiting",
                goal_label="platform waiting slot",
            )
            passenger.move_directly_toward_target(speed)

    def _waiting_layout_speed_units_per_tick(self) -> float:
        return max(0.1, float(self.model.scenario.walk_units_per_tick))

    def _route_to_boarding_doors(self) -> None:
        for _ in range(self._boarding_release_limit()):
            if not self.waiting:
                break
            passenger = self.waiting.pop(0)
            self.model.request_facility_choice(passenger, FacilityStage.BOARDING_DOOR)

    def _boarding_release_limit(self) -> int:
        doors = self.model.boarding_doors_for_platform(self)
        if not doors:
            return 0

        per_door = max(
            1,
            int(self.model.scenario.platform_boarding_release_groups_per_door_tick),
        )
        frontage_limit = len(doors) * per_door
        available_slots = sum(
            max(0, self._door_queue_capacity(door) - len(door.queue)) for door in doors
        )
        if available_slots <= 0:
            return 0
        return min(len(self.waiting), frontage_limit, available_slots)

    def _door_queue_capacity(self, door: FacilityProcessAgent) -> int:
        slots = door.spec.queue_layout.slots
        if slots:
            return len(slots)
        return max(1, self.model.scenario.boarding_queue_slots_per_row * 2)

    def step(self) -> None:
        self._layout_waiting()
        self._route_to_boarding_doors()
