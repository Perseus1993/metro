from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

import mesa

from .agent_base import ServiceAgent
from .agent_plan import FacilityStage
from .facility_process import FacilityKind, FacilitySpec

if TYPE_CHECKING:
    from .agents import PassengerAgent, TrainAgent


class FacilityProcessAgent(ServiceAgent):
    """Abstract queue/service/release process for a station facility."""

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model)
        self.spec = spec
        self.facility_id = spec.facility_id
        self.state = self._initial_state()
        self.queue: list[PassengerAgent] = []
        self.service_credit = 0.0
        self.served_persons = 0

    @property
    def queue_persons(self) -> int:
        return sum(passenger.group_size for passenger in self.queue)

    @property
    def is_open(self) -> bool:
        return self.state in {"open", "running"}

    @property
    def is_running(self) -> bool:
        return self.is_open

    def join_queue(self, passenger: PassengerAgent) -> None:
        passenger.enter_facility_queue(self.spec)
        if passenger not in self.queue:
            self.queue.append(passenger)

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._layout_queue()
        self._serve_queue(train)

    def _initial_state(self) -> str:
        return self._active_state()

    @abstractmethod
    def _active_state(self) -> str:
        """State used when the facility can accept service."""

    def _sync_state(self, train: TrainAgent | None = None) -> None:
        self.state = self._active_state()

    def _layout_queue(self) -> None:
        for index, passenger in enumerate(self.queue):
            passenger.set_target(
                self.spec.queue_layout.slot(index),
                goal_kind="queued",
                goal_label=f"{self.spec.label} queue slot",
                facility_id=self.spec.facility_id,
                stage=self.spec.stage,
            )
            passenger.move_toward_target()

    def _serve_queue(self, train: TrainAgent | None = None) -> None:
        if not self.is_open:
            return

        self.service_credit += self._service_groups_per_tick()
        while self.queue and self.service_credit >= 1.0:
            passenger = self.queue[0]
            if not self._can_start_service(passenger, train):
                break
            passenger = self.queue.pop(0)
            self._start_service(passenger, train)
            self.service_credit -= 1.0

    def _service_groups_per_tick(self) -> float:
        scenario = self.model.scenario
        return (
            self.spec.service_persons_per_min
            / scenario.group_size
            * scenario.tick_seconds
            / 60.0
        )

    def _can_start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
    ) -> bool:
        return True

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
    ) -> None:
        passenger.begin_facility_service(self.spec)
        self.served_persons += passenger.group_size


class GateProcessAgent(FacilityProcessAgent):
    """Entry or exit fare-gate process."""

    def _active_state(self) -> str:
        return "open"


class VerticalTransportProcessAgent(FacilityProcessAgent):
    """Base process for vertical passenger movers."""

    def _active_state(self) -> str:
        return "running"

    @property
    def travel_speed_units_per_tick(self) -> float:
        return self.spec.speed_units_per_tick or self.model.scenario.walk_units_per_tick


class EscalatorProcessAgent(VerticalTransportProcessAgent):
    """Continuous-flow escalator process."""


class ElevatorProcessAgent(VerticalTransportProcessAgent):
    """Batch elevator process with cabin capacity and cycle time.

    Passengers wait in the queue until a cabin is available. A cabin then boards
    a capacity-limited batch and releases the batch into the vertical ride route.
    """

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model, spec=spec)
        self.cabin_state = "idle"
        self.boarding_remaining_steps = 0
        self.cycle_remaining_steps = 0
        self.cabin_passengers: list[PassengerAgent] = []
        self.cabin_load_persons = 0
        self.departed_cabins = 0
        self.last_departure_step: int | None = None
        self.last_departure_load_persons = 0

    @property
    def cabin_capacity_persons(self) -> int:
        return max(1, int(self.model.scenario.elevator_cabin_capacity_persons))

    @property
    def cycle_steps(self) -> int:
        scenario = self.model.scenario
        return max(1, round(float(scenario.elevator_cycle_seconds) / scenario.tick_seconds))

    @property
    def boarding_steps(self) -> int:
        scenario = self.model.scenario
        return max(1, round(float(scenario.elevator_boarding_seconds) / scenario.tick_seconds))

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._layout_queue()
        self._advance_cabin()
        if self.cabin_state == "idle" and self.queue:
            self._start_boarding()

    def _advance_cabin(self) -> None:
        if self.cabin_state == "boarding":
            self.boarding_remaining_steps -= 1
            if self.boarding_remaining_steps <= 0:
                self._depart_cabin()
            return

        if self.cabin_state == "moving":
            self.cycle_remaining_steps -= 1
            if self.cycle_remaining_steps <= 0:
                self.cabin_state = "idle"
                self.cycle_remaining_steps = 0

    def _start_boarding(self) -> None:
        loaded_persons = 0
        boarded: list[PassengerAgent] = []
        while self.queue:
            passenger = self.queue[0]
            would_exceed_capacity = (
                loaded_persons + passenger.group_size > self.cabin_capacity_persons
            )
            if would_exceed_capacity and boarded:
                break
            boarded.append(self.queue.pop(0))
            loaded_persons += passenger.group_size
            if loaded_persons >= self.cabin_capacity_persons:
                break

        self.cabin_passengers = boarded
        self.cabin_load_persons = loaded_persons
        self.boarding_remaining_steps = self.boarding_steps
        self.cabin_state = "boarding"

    def _depart_cabin(self) -> None:
        for passenger in self.cabin_passengers:
            self._start_service(passenger, None)

        self.last_departure_load_persons = self.cabin_load_persons
        self.last_departure_step = self.model.step_index
        self.departed_cabins += 1
        self.cycle_remaining_steps = self.cycle_steps
        self.cabin_state = "moving"
        self.cabin_passengers = []
        self.cabin_load_persons = 0


class StairsProcessAgent(VerticalTransportProcessAgent):
    """Bidirectional or directed stairs process."""


class BoardingDoorProcessAgent(FacilityProcessAgent):
    """Train-door process gated by train dwell and remaining capacity."""

    def _initial_state(self) -> str:
        return "closed"

    def _active_state(self) -> str:
        return "open"

    def _sync_state(self, train: TrainAgent | None = None) -> None:
        self.state = "open" if train is not None and train.is_boarding else "closed"

    def _can_start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
    ) -> bool:
        return train is not None and train.capacity_remaining >= passenger.group_size

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
    ) -> None:
        if train is None:
            return
        train.current_load_persons += passenger.group_size
        super()._start_service(passenger, train)


def facility_agent_for_spec(model: mesa.Model, spec: FacilitySpec) -> FacilityProcessAgent:
    """Instantiate the concrete facility runtime class for a compiled spec."""

    if spec.stage == FacilityStage.BOARDING_DOOR.value or spec.kind == FacilityKind.TRAIN_DOOR.value:
        return BoardingDoorProcessAgent(model, spec=spec)
    if spec.kind == FacilityKind.GATE.value:
        return GateProcessAgent(model, spec=spec)
    if spec.kind == FacilityKind.ELEVATOR.value:
        return ElevatorProcessAgent(model, spec=spec)
    if spec.kind == FacilityKind.STAIRS.value:
        return StairsProcessAgent(model, spec=spec)
    if spec.kind == FacilityKind.ESCALATOR.value:
        return EscalatorProcessAgent(model, spec=spec)
    raise ValueError(f"Unsupported facility kind {spec.kind!r} for {spec.facility_id!r}.")
