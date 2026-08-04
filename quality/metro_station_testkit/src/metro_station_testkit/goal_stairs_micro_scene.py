"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

import warnings
from math import hypot
from types import SimpleNamespace

import mesa
from shapely.geometry import Polygon

from metro_station.adapters.simulation.facilities.service_events import FacilityServiceEvent
from metro_station.adapters.simulation.facilities.vertical_runtime import StairsProcessAgent
from metro_station.adapters.simulation.movement.backend import BatchedJuPedSimMovementBackend, MovementBackend
from metro_station.adapters.simulation.movement.jps_adapter import JuPedSimAdapter
from metro_station.adapters.simulation.movement.facility_motion_trace import (
    FacilityMotionTraceRecorder,
)
from .goal_stairs_fixture import (
    CONCOURSE_LEVEL,
    GoalStairsMicroScenario,
    make_stairs,
)
from .goal_stairs_micro_passenger import GoalStairsMicroPassenger
from metro_station.adapters.simulation.runtime.simulation_clock import SimulationClock
from metro_station.adapters.simulation.station.facility_portal_binding import (
    FacilityPortalBinding,
)
from .goal_journey_fixture import (
    compile_micro_facility_portal_binding,
    install_micro_spatial_capacity_contract,
)


class ControllableStairsProcessAgent(StairsProcessAgent):
    def _active_state(self) -> str:
        return "closed" if self.facility_id in self.model.disabled_stair_ids else "running"


class GoalStairsMicroScene(mesa.Model):
    width = 32.0
    height = 10.0
    source_position = (2.0, 5.0)
    decision_position = (10.5, 5.0)
    platform_landing_position = (27.5, 5.0)
    decision_radius = 0.65
    landing_radius = 0.75
    queue_capture_radius = 0.5

    @property
    def scenario(self) -> GoalStairsMicroScenario:
        return self._scenario

    @scenario.setter
    def scenario(self, value: GoalStairsMicroScenario) -> None:
        self._scenario = value

    def __init__(self, *, seed: int = 42) -> None:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning)
            super().__init__(seed=seed)
        self._scenario = GoalStairsMicroScenario()
        self.simulation_clock = SimulationClock.from_scenario(self.scenario)
        self.step_index = 0
        self.disabled_stair_ids: set[str] = set()
        self.facility_service_events: list[FacilityServiceEvent] = []
        self.facility_motion_trace_recorder = FacilityMotionTraceRecorder(
            sample_interval_seconds=0.2
        )
        self.goal_coordinator = SimpleNamespace(poll=lambda _passenger: None)
        self.goal_parity = SimpleNamespace(
            record=lambda _passenger, **_event: None,
        )
        self._event_id = 0
        self._next_passenger_id = 1
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
        self.stairs = [make_stairs(self, "stairs_1", 3.4), make_stairs(self, "stairs_2", 6.6)]
        self.stairs_by_id = {stairs.facility_id: stairs for stairs in self.stairs}
        self.facilities_by_id = dict(self.stairs_by_id)
        self._facility_portal_bindings = {
            stairs.facility_id: compile_micro_facility_portal_binding(stairs.spec)
            for stairs in self.stairs
        }
        install_micro_spatial_capacity_contract(
            self.layout_graph,
            (stairs.spec for stairs in self.stairs),
            self._facility_portal_bindings.values(),
            self.scenario,
        )
        self.subject = self._new_passenger(self.source_position, CONCOURSE_LEVEL)
        self.passengers = [self.subject]
        self.blockers: list[GoalStairsMicroPassenger] = []
        self.subject_history = [
            (self.current_time_seconds, self.subject.pos, self.subject.current_level_id)
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

    def facility_portal_binding(self, facility_id: str) -> FacilityPortalBinding:
        return self._facility_portal_bindings[facility_id]

    def tick(self) -> None:
        for stairs in self.stairs:
            stairs.step()
        for passenger, result in self.movement_backend.step_all(self.passengers):
            passenger.apply_movement_result(result)
        self.step_index += 1
        self.subject_history.append(
            (self.current_time_seconds, self.subject.pos, self.subject.current_level_id)
        )

    def add_blocker_cluster(
        self,
        center: tuple[float, float],
        *,
        level_id: str,
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
                blocker = self._new_passenger(position, level_id, blocker=True)
                self.blockers.append(blocker)
                self.passengers.append(blocker)

    def clear_blockers(self) -> None:
        for blocker in self.blockers:
            self.movement_backend.remove_passenger(blocker)
            if blocker in self.passengers:
                self.passengers.remove(blocker)
        self.blockers.clear()

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
        level_id: str,
        *,
        blocker: bool = False,
    ) -> GoalStairsMicroPassenger:
        passenger = GoalStairsMicroPassenger(
            self,
            unique_id=self._next_passenger_id,
            position=position,
            level_id=level_id,
            blocker=blocker,
        )
        self._next_passenger_id += 1
        return passenger
