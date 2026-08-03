from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import TYPE_CHECKING

from ..facilities.process import FacilityKind
from ..facilities.runtime import FacilityProcessAgent
from ..planning.plan import (
    SERVICE_STATES as PLAN_SERVICE_STATES,
    WALKING_STATES as PLAN_WALKING_STATES,
    AgentState,
)

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from .mesa_model import MetroStationModel


Point = tuple[float, float]


@dataclass
class PassengerProgressRecord:
    signature: tuple[object, ...]
    position: Point
    distance_to_target: float
    last_progress_step: int


class ExplicitReplanPolicy:
    """Forward audited progress stalls to the sole Goal Runtime authority."""

    FACILITY_REPLAN_STATES = {
        AgentState.QUEUEING_GATE.value,
        AgentState.QUEUEING_VERTICAL.value,
        AgentState.QUEUEING_DOOR.value,
        AgentState.QUEUEING_EXIT_GATE.value,
    }
    SERVICE_REPLAN_STATES = PLAN_SERVICE_STATES

    def replan(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        *,
        reason: str,
        stalled_seconds: float,
    ) -> bool:
        del stalled_seconds
        return model.goal_coordinator.replan(passenger, reason)


class ProgressMonitor:
    """Track physical progress and report stalls as GoalEvents."""

    QUEUE_STATES = ExplicitReplanPolicy.FACILITY_REPLAN_STATES
    SERVICE_STATES = ExplicitReplanPolicy.SERVICE_REPLAN_STATES
    WALKING_STATES = PLAN_WALKING_STATES

    def __init__(self, replan_policy: ExplicitReplanPolicy | None = None) -> None:
        self.records: dict[int, PassengerProgressRecord] = {}
        self.replan_policy = replan_policy or ExplicitReplanPolicy()

    def observe(
        self,
        model: MetroStationModel,
        passengers: list[PassengerAgent],
    ) -> None:
        if not model.scenario.progress_monitor_enabled:
            return

        live_ids: set[int] = set()
        for passenger in passengers:
            live_ids.add(passenger.unique_id)
            if self._should_reset(model, passenger):
                passenger.progress_age_seconds = 0.0
                self.records.pop(passenger.unique_id, None)
                continue
            self._observe_passenger(model, passenger)

        for passenger_id in tuple(self.records):
            if passenger_id not in live_ids:
                self.records.pop(passenger_id, None)

    def _should_reset(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
    ) -> bool:
        if passenger.state == AgentState.DEPARTED.value:
            return True
        if model.passenger_has_active_facility_service(passenger):
            return True
        return passenger.state not in (
            self.WALKING_STATES | self.QUEUE_STATES | self.SERVICE_STATES
        )

    def _observe_passenger(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
    ) -> None:
        signature = self._signature(passenger)
        distance = self._distance_to_target(passenger)
        record = self.records.get(passenger.unique_id)
        if record is None or record.signature != signature:
            self._record_progress(model, passenger, signature, distance)
            return
        if self._made_progress(model, passenger, record, distance):
            self._record_progress(model, passenger, signature, distance)
            return

        stalled_seconds = (
            model.step_index - record.last_progress_step
        ) * model.scenario.tick_seconds
        passenger.progress_age_seconds = round(stalled_seconds, 2)
        if stalled_seconds < self._threshold(model, passenger.state):
            return
        if passenger.state in self.QUEUE_STATES and self._queue_wait_is_expected(
            model,
            passenger,
        ):
            return
        if self.replan_policy.replan(
            model,
            passenger,
            reason=self._stall_reason(passenger.state),
            stalled_seconds=stalled_seconds,
        ):
            self._record_progress(
                model,
                passenger,
                self._signature(passenger),
                self._distance_to_target(passenger),
            )

    def _record_progress(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        signature: tuple[object, ...],
        distance: float,
    ) -> None:
        self.records[passenger.unique_id] = PassengerProgressRecord(
            signature=signature,
            position=passenger.pos,
            distance_to_target=distance,
            last_progress_step=model.step_index,
        )
        passenger.progress_age_seconds = 0.0

    def _made_progress(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        record: PassengerProgressRecord,
        distance: float,
    ) -> bool:
        displacement = hypot(
            passenger.pos[0] - record.position[0],
            passenger.pos[1] - record.position[1],
        )
        delta = model.scenario.progress_min_delta_units
        return distance < record.distance_to_target - delta or displacement > delta

    def _queue_wait_is_expected(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
    ) -> bool:
        facility = _current_facility(model, passenger)
        if facility is None:
            return False
        if facility.spec.kind == FacilityKind.ELEVATOR.value:
            expected_cycle_seconds = (
                float(model.scenario.elevator_max_dispatch_wait_seconds)
                + float(model.scenario.elevator_boarding_seconds)
                + float(model.scenario.elevator_cycle_seconds)
                + float(model.scenario.elevator_unload_seconds)
            )
            return passenger.progress_age_seconds < expected_cycle_seconds
        if facility.spec.kind != FacilityKind.TRAIN_DOOR.value:
            return False
        train = model.train_for_facility(facility)
        return (
            train is None
            or not train.is_boarding
            or train.capacity_remaining < passenger.group_size
        )

    def _threshold(self, model: MetroStationModel, state: str) -> float:
        if state in self.QUEUE_STATES:
            return model.scenario.queue_replan_wait_seconds
        return model.scenario.progress_stall_seconds

    def _stall_reason(self, state: str) -> str:
        if state in self.QUEUE_STATES:
            return "queue_wait_timeout"
        if state in self.SERVICE_STATES:
            return "service_transition_stalled"
        return "movement_stalled"

    def _signature(self, passenger: PassengerAgent) -> tuple[object, ...]:
        return (
            passenger.state,
            passenger.current_goal.stage,
            passenger.assigned_facility_id,
            round(passenger.target[0], 2),
            round(passenger.target[1], 2),
        )

    def _distance_to_target(self, passenger: PassengerAgent) -> float:
        return hypot(
            passenger.target[0] - passenger.pos[0],
            passenger.target[1] - passenger.pos[1],
        )


def _current_facility(
    model: MetroStationModel,
    passenger: PassengerAgent,
) -> FacilityProcessAgent | None:
    facility_id = passenger.assigned_facility_id or passenger.current_goal.facility_id
    facility = None if facility_id is None else model.facilities_by_id.get(facility_id)
    return facility if isinstance(facility, FacilityProcessAgent) else None


__all__ = [
    "ExplicitReplanPolicy",
    "PassengerProgressRecord",
    "ProgressMonitor",
]
