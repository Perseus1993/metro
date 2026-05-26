from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import TYPE_CHECKING

from .plan import AgentIntent, AgentState, RouteKey

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..facilities.runtime import FacilityProcessAgent
    from ..runtime.mesa_model import MetroStationModel


Point = tuple[float, float]


@dataclass
class PassengerProgressRecord:
    signature: tuple[object, ...]
    position: Point
    distance_to_target: float
    last_progress_step: int


class ExplicitReplanPolicy:
    """Audited same-stage replanning for passengers with no progress."""

    FACILITY_REPLAN_STATES = {
        AgentState.QUEUEING_GATE.value,
        AgentState.QUEUEING_VERTICAL.value,
        AgentState.QUEUEING_DOOR.value,
        AgentState.QUEUEING_EXIT_GATE.value,
    }

    ROUTE_REPLAN_KEYS = {
        AgentState.ENTERING_STATION.value: RouteKey.ENTRY_GATE_DECISION.value,
        AgentState.WALKING_TO_PLATFORM.value: RouteKey.AFTER_VERTICAL.value,
        AgentState.WALKING_TO_EXIT_GATE.value: RouteKey.AFTER_EXIT_VERTICAL.value,
    }

    def replan(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        *,
        reason: str,
        stalled_seconds: float,
    ) -> bool:
        if passenger.state in self.FACILITY_REPLAN_STATES:
            return self._replan_facility(
                model,
                passenger,
                reason=reason,
                stalled_seconds=stalled_seconds,
            )
        return self._replan_route(
            model,
            passenger,
            reason=reason,
            stalled_seconds=stalled_seconds,
        )

    def _replan_facility(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        *,
        reason: str,
        stalled_seconds: float,
    ) -> bool:
        current_facility = self._current_facility(model, passenger)
        stage = self._current_stage(passenger, current_facility)
        if stage is None:
            return False

        attempts = passenger.replan_attempts_by_stage.get(stage, 0)
        if attempts >= model.scenario.replan_max_attempts_per_stage:
            self._record_replan_skipped(
                model,
                passenger,
                reason=reason,
                stage=stage,
                skipped_reason="max_attempts",
                stalled_seconds=stalled_seconds,
            )
            return False

        candidates = model._facilities_for_stage(stage)
        if current_facility is not None:
            alternatives = [
                candidate
                for candidate in candidates
                if candidate.facility_id != current_facility.facility_id
            ]
            if not alternatives:
                self._record_replan_skipped(
                    model,
                    passenger,
                    reason=reason,
                    stage=stage,
                    skipped_reason="no_alternative_facility",
                    stalled_seconds=stalled_seconds,
                )
                return False
            self._remove_from_queue(model, passenger, current_facility)
            passenger.avoided_facility_ids_by_stage.setdefault(stage, set()).add(
                current_facility.facility_id
            )

        passenger.replan_attempts_by_stage[stage] = attempts + 1
        previous_facility_id = passenger.assigned_facility_id
        passenger.assigned_facility_id = None
        passenger.last_replan_reason = reason
        passenger.progress_age_seconds = 0.0
        model.request_facility_choice(passenger, stage)
        model.audit.record(
            "passenger_replanned_facility",
            source="progress_monitor",
            severity="info",
            step=model.step_index,
            context={
                "passenger_id": passenger.unique_id,
                "intent": passenger.intent,
                "stage": stage,
                "from_facility_id": previous_facility_id,
                "to_facility_id": passenger.assigned_facility_id,
                "reason": reason,
                "stalled_seconds": round(stalled_seconds, 2),
                "attempt": passenger.replan_attempts_by_stage[stage],
            },
        )
        return passenger.assigned_facility_id != previous_facility_id

    def _replan_route(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        *,
        reason: str,
        stalled_seconds: float,
    ) -> bool:
        route_key = self._route_key_for_state(passenger)
        if route_key is None:
            return False
        route = model.route_for_key(route_key, passenger)
        if not route:
            self._record_replan_skipped(
                model,
                passenger,
                reason=reason,
                stage=passenger.current_goal.stage,
                skipped_reason="route_not_found",
                stalled_seconds=stalled_seconds,
            )
            return False
        passenger.set_route(
            route,
            goal_kind="walk",
            goal_label=passenger.current_goal.label,
            facility_id=passenger.current_goal.facility_id,
            stage=passenger.current_goal.stage,
        )
        passenger.last_replan_reason = reason
        passenger.progress_age_seconds = 0.0
        model.audit.record(
            "passenger_replanned_route",
            source="progress_monitor",
            severity="info",
            step=model.step_index,
            context={
                "passenger_id": passenger.unique_id,
                "intent": passenger.intent,
                "state": passenger.state,
                "route_key": route_key,
                "reason": reason,
                "stalled_seconds": round(stalled_seconds, 2),
            },
        )
        return True

    def _route_key_for_state(self, passenger: PassengerAgent) -> str | None:
        if passenger.state == AgentState.WALKING_TO_VERTICAL.value:
            if passenger.intent in {
                AgentIntent.EXIT_STATION.value,
                AgentIntent.TRANSFER.value,
            }:
                return RouteKey.PLATFORM_TO_VERTICAL.value
            return RouteKey.AFTER_GATE.value
        return self.ROUTE_REPLAN_KEYS.get(passenger.state)

    def _current_facility(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
    ) -> FacilityProcessAgent | None:
        facility_id = passenger.assigned_facility_id or passenger.current_goal.facility_id
        if facility_id is None:
            return None
        return model.facilities_by_id.get(facility_id)

    def _current_stage(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent | None,
    ) -> str | None:
        if passenger.current_goal.stage is not None:
            return passenger.current_goal.stage
        if facility is not None:
            return facility.spec.stage
        return None

    def _remove_from_queue(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> None:
        try:
            facility.queue.remove(passenger)
        except ValueError:
            model.audit.record(
                "replan_queue_remove_missing",
                source="progress_monitor",
                severity="warning",
                step=model.step_index,
                context={
                    "passenger_id": passenger.unique_id,
                    "facility_id": facility.facility_id,
                    "state": passenger.state,
                },
            )

    def _record_replan_skipped(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        *,
        reason: str,
        stage: str | None,
        skipped_reason: str,
        stalled_seconds: float,
    ) -> None:
        passenger.last_replan_reason = f"skipped:{skipped_reason}"
        model.audit.record(
            "passenger_replan_skipped",
            source="progress_monitor",
            severity="debug",
            step=model.step_index,
            context={
                "passenger_id": passenger.unique_id,
                "intent": passenger.intent,
                "state": passenger.state,
                "stage": stage,
                "reason": reason,
                "skipped_reason": skipped_reason,
                "stalled_seconds": round(stalled_seconds, 2),
            },
        )


class ProgressMonitor:
    """Track per-passenger progress and trigger explicit replans."""

    QUEUE_STATES = ExplicitReplanPolicy.FACILITY_REPLAN_STATES
    WALKING_STATES = {
        AgentState.ENTERING_STATION.value,
        AgentState.WALKING_TO_VERTICAL.value,
        AgentState.WALKING_TO_PLATFORM.value,
        AgentState.WALKING_TO_EXIT_GATE.value,
        AgentState.WALKING_TO_TRANSFER.value,
    }

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
            if passenger.state == AgentState.DEPARTED.value:
                self.records.pop(passenger.unique_id, None)
                continue
            if (
                passenger.state not in self.WALKING_STATES
                and passenger.state not in self.QUEUE_STATES
            ):
                passenger.progress_age_seconds = 0.0
                self.records.pop(passenger.unique_id, None)
                continue
            self._observe_passenger(model, passenger)

        for passenger_id in list(self.records):
            if passenger_id not in live_ids:
                self.records.pop(passenger_id, None)

    def _observe_passenger(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
    ) -> None:
        signature = self._signature(passenger)
        distance = self._distance_to_target(passenger)
        record = self.records.get(passenger.unique_id)
        if record is None or record.signature != signature:
            self.records[passenger.unique_id] = PassengerProgressRecord(
                signature=signature,
                position=passenger.pos,
                distance_to_target=distance,
                last_progress_step=model.step_index,
            )
            passenger.progress_age_seconds = 0.0
            return

        displacement = hypot(
            passenger.pos[0] - record.position[0],
            passenger.pos[1] - record.position[1],
        )
        improved = distance < record.distance_to_target - model.scenario.progress_min_delta_units
        moved = displacement > model.scenario.progress_min_delta_units
        if improved or moved:
            self.records[passenger.unique_id] = PassengerProgressRecord(
                signature=signature,
                position=passenger.pos,
                distance_to_target=distance,
                last_progress_step=model.step_index,
            )
            passenger.progress_age_seconds = 0.0
            return

        stalled_seconds = (
            model.step_index - record.last_progress_step
        ) * model.scenario.tick_seconds
        passenger.progress_age_seconds = round(stalled_seconds, 2)
        threshold = self._threshold_for_state(model, passenger.state)
        if stalled_seconds < threshold:
            return

        reason = (
            "queue_wait_timeout" if passenger.state in self.QUEUE_STATES else "movement_stalled"
        )
        if self.replan_policy.replan(
            model,
            passenger,
            reason=reason,
            stalled_seconds=stalled_seconds,
        ):
            self.records[passenger.unique_id] = PassengerProgressRecord(
                signature=self._signature(passenger),
                position=passenger.pos,
                distance_to_target=self._distance_to_target(passenger),
                last_progress_step=model.step_index,
            )

    def _threshold_for_state(self, model: MetroStationModel, state: str) -> float:
        if state in self.QUEUE_STATES:
            return model.scenario.queue_replan_wait_seconds
        return model.scenario.progress_stall_seconds

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
