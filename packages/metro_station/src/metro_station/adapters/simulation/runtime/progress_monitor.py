from __future__ import annotations

import json
from dataclasses import dataclass
from math import hypot
from typing import TYPE_CHECKING, ClassVar

from ..facilities.process import FacilityKind
from ..facilities.runtime import FacilityProcessAgent
from ..planning.goal_state import FacilityInteractionState
from ..planning.plan import (
    SERVICE_STATES as PLAN_SERVICE_STATES,
)
from ..planning.plan import (
    WALKING_STATES as PLAN_WALKING_STATES,
)
from ..planning.plan import (
    AgentState,
)
from .physical_waypoint_routing import PhysicalRouteUnreachableError

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


@dataclass
class PassengerLivenessRecord:
    position: Point
    started_step: int
    strategic_revision: tuple[object, ...]


class PassengerLivenessViolation(RuntimeError):
    """A candidate-evaluation passenger has no actionable physical owner."""


class ExplicitReplanPolicy:
    """Forward audited progress stalls to the sole Goal Runtime authority."""

    FACILITY_REPLAN_STATES: ClassVar[frozenset[str]] = frozenset(
        {
        AgentState.QUEUEING_GATE.value,
        AgentState.QUEUEING_VERTICAL.value,
        AgentState.QUEUEING_DOOR.value,
        AgentState.QUEUEING_EXIT_GATE.value,
        }
    )
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
        self.liveness_records: dict[int, PassengerLivenessRecord] = {}
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
            self._observe_liveness(model, passenger)
            if self._should_reset(model, passenger):
                passenger.progress_age_seconds = 0.0
                self.records.pop(passenger.unique_id, None)
                continue
            self._observe_passenger(model, passenger)

        for passenger_id in tuple(self.records):
            if passenger_id not in live_ids:
                self.records.pop(passenger_id, None)
        for passenger_id in tuple(self.liveness_records):
            if passenger_id not in live_ids:
                self.liveness_records.pop(passenger_id, None)

    def _observe_liveness(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
    ) -> None:
        state = passenger.goal_runtime.state
        evaluating = (
            state.interaction_state
            == FacilityInteractionState.EVALUATE_CANDIDATES.value
        )
        walking = passenger.state in self.WALKING_STATES
        passenger_id = int(passenger.unique_id)
        if not (walking or evaluating):
            self.liveness_records.pop(passenger_id, None)
            return
        if (
            not evaluating
            and self._is_at_owned_decision_holding(model, passenger)
        ):
            # A closed facility bank may intentionally keep a passenger at a
            # finite, compiler-certified holding cell until capacity or
            # control state changes.  Remaining inside the tactical target
            # radius is an owned wait, not an unowned movement deadlock.
            self.liveness_records.pop(passenger_id, None)
            return

        structurally_unowned = evaluating and self._has_no_actionable_ownership(passenger)
        record = self.liveness_records.get(passenger_id)
        strategic_revision = self._strategic_revision(passenger)
        if record is None:
            self.liveness_records[passenger_id] = PassengerLivenessRecord(
                position=tuple(passenger.pos),
                started_step=int(model.step_index),
                strategic_revision=strategic_revision,
            )
            return

        displacement = hypot(
            passenger.pos[0] - record.position[0],
            passenger.pos[1] - record.position[1],
        )
        epsilon = float(model.scenario.liveness_min_displacement_units)
        if not structurally_unowned and (
            displacement >= epsilon
            or strategic_revision != record.strategic_revision
        ):
            self.liveness_records[passenger_id] = PassengerLivenessRecord(
                position=tuple(passenger.pos),
                started_step=int(model.step_index),
                strategic_revision=strategic_revision,
            )
            return

        stalled_seconds = (
            int(model.step_index) - int(record.started_step)
        ) * float(model.scenario.tick_seconds)
        threshold = float(model.scenario.liveness_fail_fast_seconds)
        if stalled_seconds < threshold:
            return

        if walking and not structurally_unowned and self.replan_policy.replan(
            model,
            passenger,
            reason="movement_stalled",
            stalled_seconds=stalled_seconds,
        ):
            self.liveness_records[passenger_id] = PassengerLivenessRecord(
                position=tuple(passenger.pos),
                started_step=int(model.step_index),
                strategic_revision=self._strategic_revision(passenger),
            )
            return

        context = self._liveness_context(
            passenger,
            record,
            stalled_seconds=stalled_seconds,
            displacement=displacement,
            epsilon=epsilon,
            structurally_unowned=structurally_unowned,
        )
        model.audit.record(
            "passenger_liveness_violation",
            source="progress_monitor",
            severity="error",
            step=int(model.step_index),
            context=context,
        )
        raise PassengerLivenessViolation(
            "passenger liveness violation: "
            + json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
        )

    @staticmethod
    def _has_no_actionable_ownership(passenger: PassengerAgent) -> bool:
        state = passenger.goal_runtime.state
        return (
            state.commitment is None
            and passenger.assigned_facility_id is None
            and not passenger.decision_holding_target_by_region
            and not passenger.facility_approach_facility_ids_by_stage
        )

    @staticmethod
    def _is_at_owned_decision_holding(
        model: MetroStationModel,
        passenger: PassengerAgent,
    ) -> bool:
        targets = tuple(passenger.decision_holding_target_by_region.values())
        if not targets:
            return False
        active_target = passenger.current_goal.target
        if active_target is not None:
            targets = (*targets, active_target)
        radius = float(model.scenario.jupedsim_target_radius_units)
        return any(
            hypot(passenger.pos[0] - target[0], passenger.pos[1] - target[1])
            <= radius
            for target in targets
        )

    @staticmethod
    def _strategic_revision(passenger: PassengerAgent) -> tuple[object, ...]:
        """Identify fresh Goal Runtime work without mistaking stale goals for ownership."""

        state = passenger.goal_runtime.state
        return (
            float(state.last_event_time_seconds),
            int(state.transition_count),
            int(state.retry_count),
            len(state.processed_event_ids),
            state.current_node_id,
            state.interaction_state,
        )

    @staticmethod
    def _liveness_context(
        passenger: PassengerAgent,
        record: PassengerLivenessRecord,
        *,
        stalled_seconds: float,
        displacement: float,
        epsilon: float,
        structurally_unowned: bool,
    ) -> dict[str, object]:
        state = passenger.goal_runtime.state
        return {
            "passenger_id": int(passenger.unique_id),
            "intent": str(passenger.intent),
            "passenger_state": str(passenger.state),
            "position": [float(passenger.pos[0]), float(passenger.pos[1])],
            "anchor_position": [float(record.position[0]), float(record.position[1])],
            "displacement_units": float(displacement),
            "minimum_displacement_units": float(epsilon),
            "stalled_seconds": float(stalled_seconds),
            "goal_kind": str(passenger.current_goal.kind),
            "goal_label": str(passenger.current_goal.label),
            "goal_target": None
            if passenger.current_goal.target is None
            else [
                float(passenger.current_goal.target[0]),
                float(passenger.current_goal.target[1]),
            ],
            "goal_node_id": state.current_node_id,
            "goal_stage": state.current_stage,
            "goal_interaction_state": state.interaction_state,
            "committed_facility_id": None
            if state.commitment is None
            else state.commitment.facility_id,
            "assigned_facility_id": passenger.assigned_facility_id,
            "decision_holding_regions": sorted(
                passenger.decision_holding_target_by_region
            ),
            "approach_facilities": dict(
                sorted(passenger.facility_approach_facility_ids_by_stage.items())
            ),
            "structurally_unowned": bool(structurally_unowned),
        }

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
        distance = self._distance_to_target(model, passenger)
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
                self._distance_to_target(model, passenger),
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
        delta = model.scenario.progress_min_delta_units
        # Lateral crowd motion and back-and-forth jitter are not progress
        # toward the active tactical target.  Resetting the stall clock for
        # any displacement lets a blocked body oscillate forever while a FIFO
        # reservation keeps the whole facility unavailable.  ``distance`` is
        # the remaining navmesh path length below, so legitimate detours still
        # count whenever they advance along the physical route.
        return distance < record.distance_to_target - delta

    def _queue_wait_is_expected(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
    ) -> bool:
        facility = _current_facility(model, passenger)
        if facility is None:
            return False
        if facility.spec.kind == FacilityKind.ELEVATOR.value:
            # The cabin runtime may lengthen boarding to satisfy its physical
            # speed/acceleration profile, and a queued passenger can also be
            # waiting for the return leg.  Monitor the runtime contract rather
            # than the configured lower bounds, otherwise a feasible slow
            # cycle is falsely diagnosed as a stalled queue.
            expected_cycle_seconds = float(
                getattr(facility, "effective_cycle_seconds", 0.0)
            ) + max(
                0.0,
                float(getattr(facility, "max_dispatch_wait_seconds", 0.0)),
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

    def _distance_to_target(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
    ) -> float:
        try:
            waypoints = model._physical_route_for_points(
                passenger,
                (tuple(passenger.target),),
                include_navigation_waypoints=True,
            )
        except PhysicalRouteUnreachableError:
            waypoints = ()
        if not waypoints:
            return hypot(
                passenger.target[0] - passenger.pos[0],
                passenger.target[1] - passenger.pos[1],
            )
        distance = 0.0
        previous = tuple(passenger.pos)
        for waypoint in waypoints:
            distance += hypot(
                waypoint[0] - previous[0],
                waypoint[1] - previous[1],
            )
            previous = waypoint
        return distance


def _current_facility(
    model: MetroStationModel,
    passenger: PassengerAgent,
) -> FacilityProcessAgent | None:
    facility_id = passenger.assigned_facility_id or passenger.current_goal.facility_id
    facility = None if facility_id is None else model.facilities_by_id.get(facility_id)
    return facility if isinstance(facility, FacilityProcessAgent) else None


__all__ = [
    "ExplicitReplanPolicy",
    "PassengerLivenessRecord",
    "PassengerLivenessViolation",
    "PassengerProgressRecord",
    "ProgressMonitor",
]
