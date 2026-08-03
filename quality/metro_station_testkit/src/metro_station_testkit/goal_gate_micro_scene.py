"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from math import hypot
from types import SimpleNamespace

import mesa
from shapely.geometry import Polygon

from metro_station.adapters.simulation.facilities.process import FacilityKind, FacilitySpec, QueueLayout
from metro_station.adapters.simulation.facilities.runtime import GateProcessAgent
from metro_station.adapters.simulation.facilities.service_events import FacilityServiceEvent
from metro_station.adapters.simulation.movement.backend import BatchedJuPedSimMovementBackend, MovementBackend
from metro_station.adapters.simulation.movement.jps_adapter import JuPedSimAdapter
from metro_station.adapters.simulation.planning.plan import AgentState, FacilityStage
from .goal_gate_micro_passenger import GoalGateMicroPassenger
from metro_station.adapters.simulation.runtime.simulation_clock import PHYSICAL_CLOCK, SimulationClock


@dataclass(frozen=True)
class GoalGateMicroScenario:
    tick_seconds: float = 0.25
    group_size: int = 1
    walk_units_per_tick: float = 0.3
    jupedsim_dt_seconds: float = 0.01
    jupedsim_iterations_per_tick: int = 25
    jupedsim_agent_radius_units: float = 0.22
    jupedsim_target_radius_units: float = 0.38
    jupedsim_clearance_multiplier: float = 2.0
    jupedsim_neighbor_radius_units: float = 2.5
    jupedsim_neighbor_sample_limit: int = 12
    jupedsim_operational_model: str = "collision_free_speed"
    jupedsim_strict: bool = True
    simulation_clock_mode: str = PHYSICAL_CLOCK
    personal_space_units: float = 0.8


class ControllableGateProcessAgent(GateProcessAgent):
    def _active_state(self) -> str:
        return "closed" if self.facility_id in self.model.disabled_gate_ids else "open"


class GoalGateMicroScene(mesa.Model):
    width = 30.0
    height = 10.0
    source_position = (2.0, 5.0)
    decision_position = (11.5, 5.0)
    paid_hall_position = (25.0, 5.0)
    decision_radius = 0.65
    paid_hall_radius = 0.75
    queue_capture_radius = 0.5

    @property
    def scenario(self) -> GoalGateMicroScenario:
        return self._scenario

    @scenario.setter
    def scenario(self, value: GoalGateMicroScenario) -> None:
        self._scenario = value

    def __init__(self, *, seed: int = 42) -> None:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning)
            super().__init__(seed=seed)
        self._scenario = GoalGateMicroScenario()
        self.simulation_clock = SimulationClock.from_scenario(self.scenario)
        self.step_index = 0
        self.disabled_gate_ids: set[str] = set()
        self.facility_service_events: list[FacilityServiceEvent] = []
        self.goal_coordinator = SimpleNamespace(poll=lambda _passenger: None)
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
        self.gates = [self._make_gate("gate_1", 3.4), self._make_gate("gate_2", 6.6)]
        self.gates_by_id = {gate.facility_id: gate for gate in self.gates}
        self.subject = GoalGateMicroPassenger(
            self,
            unique_id=self._new_passenger_id(),
            position=self.source_position,
        )
        self.passengers = [self.subject]
        self.blockers: list[GoalGateMicroPassenger] = []

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

    def tick(self) -> None:
        for gate in self.gates:
            gate.step()
        for passenger, result in self.movement_backend.step_all(self.passengers):
            passenger.apply_movement_result(result)
        self.step_index += 1

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
                blocker = GoalGateMicroPassenger(
                    self,
                    unique_id=self._new_passenger_id(),
                    position=position,
                    blocker=True,
                )
                self.blockers.append(blocker)
                self.passengers.append(blocker)

    def clear_blockers(self) -> None:
        for blocker in self.blockers:
            self.movement_backend.remove_passenger(blocker)
            if blocker in self.passengers:
                self.passengers.remove(blocker)
        self.blockers.clear()

    def blocker_count_near(self, position: tuple[float, float], radius: float) -> int:
        return sum(hypot(item.pos[0] - position[0], item.pos[1] - position[1]) <= radius for item in self.blockers)

    def _new_passenger_id(self) -> int:
        passenger_id = self._next_passenger_id
        self._next_passenger_id += 1
        return passenger_id

    def _make_gate(self, short_id: str, y: float) -> ControllableGateProcessAgent:
        queue_anchor = (17.0, y)
        slots = tuple((17.0 - index * 0.65, y) for index in range(12))
        spec = FacilitySpec(
            facility_id=short_id,
            stage=FacilityStage.ENTRY_GATE.value,
            label=short_id,
            kind=FacilityKind.GATE.value,
            direction="entry",
            position=(18.0, y),
            queue_layout=QueueLayout(
                anchor=queue_anchor,
                per_row=1,
                col_step=(0.0, 0.0),
                row_step=(-0.65, 0.0),
                slots=slots,
            ),
            exit_position=(20.0, y),
            service_persons_per_min=120,
            queue_state=AgentState.QUEUEING_GATE.value,
            service_state=AgentState.PASSING_GATE.value,
            release_route=(),
            entry_level_id="concourse",
            exit_level_id="concourse",
        )
        return ControllableGateProcessAgent(self, spec=spec)
