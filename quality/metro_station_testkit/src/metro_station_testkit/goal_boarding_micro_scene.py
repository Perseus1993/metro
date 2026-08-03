"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

import warnings
from math import hypot
from types import SimpleNamespace

import mesa
from shapely.geometry import Polygon

from metro_station.adapters.simulation.agents.transit import TrainAgent
from metro_station.adapters.simulation.facilities.runtime_base import BoardingDoorProcessAgent
from metro_station.adapters.simulation.facilities.service_events import FacilityServiceEvent
from metro_station.adapters.simulation.movement.backend import BatchedJuPedSimMovementBackend, MovementBackend
from metro_station.adapters.simulation.movement.jps_adapter import JuPedSimAdapter
from metro_station.adapters.simulation.planning.plan import AgentState
from .goal_boarding_fixture import (
    PLATFORM_ID,
    GoalBoardingMicroScenario,
    make_boarding_door,
)
from .goal_boarding_micro_passenger import GoalBoardingMicroPassenger
from metro_station.adapters.simulation.runtime.simulation_clock import SimulationClock


class ControllableBoardingDoorProcessAgent(BoardingDoorProcessAgent):
    def _sync_state(self, train: TrainAgent | None = None) -> None:
        super()._sync_state(train)
        if self.facility_id in self.model.disabled_door_ids:
            self.state = "closed"
        if self.facility_id in self.model.service_blocked_door_ids:
            self.state = "blocked"


class GoalBoardingMicroScene(mesa.Model):
    width = 30.0
    height = 10.0
    source_position = (2.0, 5.0)
    decision_position = (10.5, 5.0)
    decision_radius = 0.65
    queue_capture_radius = 0.5

    @property
    def scenario(self) -> GoalBoardingMicroScenario:
        return self._scenario

    @scenario.setter
    def scenario(self, value: GoalBoardingMicroScenario) -> None:
        self._scenario = value

    def __init__(self, *, seed: int = 42) -> None:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning)
            super().__init__(seed=seed)
        self._scenario = GoalBoardingMicroScenario()
        self.simulation_clock = SimulationClock.from_scenario(self.scenario)
        self.step_index = 0
        self.disabled_door_ids: set[str] = set()
        self.service_blocked_door_ids: set[str] = set()
        self.facility_service_events: list[FacilityServiceEvent] = []
        self._event_id = 0
        self._next_passenger_id = 1
        self.boarded_persons = 0
        self._walkable_area = Polygon(
            [(0, 0), (self.width, 0), (self.width, self.height), (0, self.height)]
        )
        self.layout_graph = SimpleNamespace(
            geometry=SimpleNamespace(width=self.width, height=self.height)
        )
        self.jupedsim = JuPedSimAdapter()
        if not self.jupedsim.status.available:
            raise RuntimeError(self.jupedsim.status.message)
        self.movement_backend: MovementBackend = BatchedJuPedSimMovementBackend(
            self.jupedsim,
            strict=True,
        )
        self.train = TrainAgent(
            self,
            line_id="probe_line",
            direction="down",
            platform_id=PLATFORM_ID,
        )
        self.doors = [
            make_boarding_door(self, "door_1", 3.4),
            make_boarding_door(self, "door_2", 6.6),
        ]
        self.doors_by_id = {door.facility_id: door for door in self.doors}
        self.facilities_by_id = dict(self.doors_by_id)
        self.subject = self._new_passenger(self.source_position)
        self.passengers = [self.subject]
        self.blockers: list[GoalBoardingMicroPassenger] = []
        self.subject_history = [
            (self.current_time_seconds, self.subject.pos, self.subject.state)
        ]

    @property
    def current_time_seconds(self) -> float:
        return self.step_index * self.scenario.tick_seconds

    def clamp_position(self, position: tuple[float, float]) -> tuple[float, float]:
        return (
            max(0.0, min(self.width, float(position[0]))),
            max(0.0, min(self.height, float(position[1]))),
        )

    def jupedsim_walkable_area(self, level_id: str | None = None):
        del level_id
        return self._walkable_area

    def nearby_passengers(self, passenger, radius: float):
        nearby = []
        for other in self.passengers:
            if other is passenger:
                continue
            dx, dy = other.pos[0] - passenger.pos[0], other.pos[1] - passenger.pos[1]
            distance = hypot(dx, dy)
            if distance <= radius:
                nearby.append((other, dx, dy, distance))
        return sorted(nearby, key=lambda item: item[3])

    def next_facility_service_event_id(self) -> int:
        self._event_id += 1
        return self._event_id

    def record_facility_service_event(self, event: FacilityServiceEvent) -> None:
        self.facility_service_events.append(event)

    def train_capacity_for_platform(self, platform_id: str) -> int:
        del platform_id
        return int(self.scenario.train_capacity_persons)

    def complete_departure(
        self,
        passenger: GoalBoardingMicroPassenger,
        *,
        boarded: bool = True,
    ) -> None:
        if passenger.state == AgentState.DEPARTED.value:
            return
        self.movement_backend.remove_passenger(passenger)
        passenger.state = AgentState.DEPARTED.value
        if boarded:
            self.boarded_persons += passenger.group_size
        if passenger in self.passengers:
            self.passengers.remove(passenger)

    def tick(self) -> None:
        self.train.step()
        for door in self.doors:
            door.step(self.train)
        for passenger, result in self.movement_backend.step_all(self.passengers):
            passenger.apply_movement_result(result)
        self.step_index += 1
        self.subject_history.append(
            (self.current_time_seconds, self.subject.pos, self.subject.state)
        )

    def add_blocker_cluster(
        self,
        center: tuple[float, float],
        *,
        rows: int = 3,
        columns: int = 4,
        spacing: float = 0.48,
    ) -> None:
        for row in range(rows):
            for column in range(columns):
                position = (
                    center[0] + (column - (columns - 1) / 2) * spacing,
                    center[1] + (row - (rows - 1) / 2) * spacing,
                )
                blocker = self._new_passenger(position, blocker=True)
                self.blockers.append(blocker)
                self.passengers.append(blocker)

    def clear_blockers(self) -> None:
        for blocker in self.blockers:
            self.movement_backend.remove_passenger(blocker)
            if blocker in self.passengers:
                self.passengers.remove(blocker)
        self.blockers.clear()

    def blocker_count_near(self, position: tuple[float, float], radius: float) -> int:
        return sum(
            hypot(item.pos[0] - position[0], item.pos[1] - position[1]) <= radius
            for item in self.blockers
        )

    def _new_passenger(
        self,
        position: tuple[float, float],
        *,
        blocker: bool = False,
    ) -> GoalBoardingMicroPassenger:
        passenger = GoalBoardingMicroPassenger(
            self,
            unique_id=self._next_passenger_id,
            position=position,
            blocker=blocker,
        )
        self._next_passenger_id += 1
        return passenger
