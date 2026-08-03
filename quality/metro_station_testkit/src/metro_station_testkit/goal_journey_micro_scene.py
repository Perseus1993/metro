"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

import warnings
from math import hypot
from types import SimpleNamespace

import mesa
from shapely.geometry import Polygon

from metro_station.adapters.simulation.agents.transit import TrainAgent
from metro_station.adapters.simulation.facilities.service_events import FacilityServiceEvent
from metro_station.adapters.simulation.movement.backend import BatchedJuPedSimMovementBackend, MovementBackend
from metro_station.adapters.simulation.movement.jps_adapter import JuPedSimAdapter
from metro_station.adapters.simulation.planning.plan import AgentState
from .goal_journey_fixture import (
    CONCOURSE_LEVEL,
    PLATFORM_ID,
    GoalJourneyMicroScenario,
    make_door,
    make_gate,
    make_stairs,
)
from .goal_journey_passenger import GoalJourneyPassenger
from metro_station.adapters.simulation.runtime.simulation_clock import SimulationClock


class GoalJourneyMicroScene(mesa.Model):
    width = 65.0
    height = 14.0
    source_position = (2.0, 7.0)
    region_positions = {
        "entry_gate_decision": (10.0, 7.0),
        "paid_hall": (23.0, 7.0),
        "vertical_decision": (29.0, 7.0),
        "platform_landing": (45.0, 7.0),
        "boarding_decision": (50.0, 7.0),
    }
    region_radius = 0.7
    queue_capture_radius = 0.5

    @property
    def scenario(self) -> GoalJourneyMicroScenario:
        return self._scenario

    @scenario.setter
    def scenario(self, value: GoalJourneyMicroScenario) -> None:
        self._scenario = value

    def __init__(self, *, seed: int = 42) -> None:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning)
            super().__init__(seed=seed)
        self._scenario = GoalJourneyMicroScenario()
        self.simulation_clock = SimulationClock.from_scenario(self.scenario)
        self.step_index = 0
        self.disabled_gate_ids: set[str] = set()
        self.disabled_stair_ids: set[str] = set()
        self.disabled_door_ids: set[str] = set()
        self.service_blocked_door_ids: set[str] = set()
        self.facility_service_events: list[FacilityServiceEvent] = []
        self.goal_coordinator = SimpleNamespace(poll=lambda _passenger: None)
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
            line_id="journey_line",
            direction="down",
            platform_id=PLATFORM_ID,
        )
        self.gates = [make_gate(self, "gate_1", 5.0), make_gate(self, "gate_2", 9.0)]
        self.stairs = [
            make_stairs(self, "stairs_1", 5.0),
            make_stairs(self, "stairs_2", 9.0),
        ]
        self.doors = [make_door(self, "door_1", 5.0), make_door(self, "door_2", 9.0)]
        self.facilities = [*self.gates, *self.stairs, *self.doors]
        self.facilities_by_id = {item.facility_id: item for item in self.facilities}
        self.subject = self._new_passenger(self.source_position)
        self.passengers = [self.subject]
        self.crowd: list[GoalJourneyPassenger] = []
        self.blockers: list[GoalJourneyPassenger] = []

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
            if other is passenger or other.current_level_id != passenger.current_level_id:
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

    def record_pending_facility_service_event(self, event: FacilityServiceEvent) -> None:
        self.facility_service_events.append(event)

    def observe_facility_service_completed(
        self,
        facility_id: str,
        passenger_ids: tuple[int, ...],
        time_seconds: float,
    ) -> None:
        del facility_id, passenger_ids, time_seconds

    def train_capacity_for_platform(self, platform_id: str) -> int:
        del platform_id
        return int(self.scenario.train_capacity_persons)

    def complete_departure(self, passenger: GoalJourneyPassenger, *, boarded: bool = True) -> None:
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
        for gate in self.gates:
            gate.step()
        for stairs in self.stairs:
            stairs.step()
        for door in self.doors:
            door.step(self.train)
        for passenger, result in self.movement_backend.step_all(self.passengers):
            passenger.apply_movement_result(result)
        self.step_index += 1

    def add_blocker_cluster(
        self,
        center: tuple[float, float],
        *,
        level_id: str,
        rows: int = 3,
        columns: int = 4,
    ) -> None:
        for row in range(rows):
            for column in range(columns):
                position = (
                    center[0] + (column - (columns - 1) / 2) * 0.48,
                    center[1] + (row - (rows - 1) / 2) * 0.48,
                )
                blocker = self._new_passenger(position, level_id=level_id, blocker=True)
                self.blockers.append(blocker)
                self.passengers.append(blocker)

    def blocker_count_near(
        self,
        position: tuple[float, float],
        radius: float,
        *,
        level_id: str,
    ) -> int:
        return sum(
            item.current_level_id == level_id
            and hypot(item.pos[0] - position[0], item.pos[1] - position[1]) <= radius
            for item in self.blockers
        )

    def _new_passenger(
        self,
        position: tuple[float, float],
        *,
        level_id: str = CONCOURSE_LEVEL,
        blocker: bool = False,
    ) -> GoalJourneyPassenger:
        passenger = GoalJourneyPassenger(
            self,
            unique_id=self.allocate_passenger_id(),
            position=position,
            level_id=level_id,
            blocker=blocker,
        )
        return passenger

    def allocate_passenger_id(self) -> int:
        passenger_id = self._next_passenger_id
        self._next_passenger_id += 1
        return passenger_id
