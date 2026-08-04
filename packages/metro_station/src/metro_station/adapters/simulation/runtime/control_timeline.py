"""Apply versioned control plans to the Mesa runtime."""

from __future__ import annotations

from typing import Any

from metro_station.application.control_plans import (
    ACCESS_CLOSURE,
    ACTIVATING_ACTIONS,
    DEACTIVATING_ACTIONS,
    ESCALATOR_DIRECTION,
    ONE_WAY_CHANNEL,
    STAFF_GUIDANCE,
    ControlEvent,
    ControlMeasure,
    ControlPlan,
)

from ..movement.backend import MovementResult
from ..station.disruptions import FacilityAvailabilityEvent
from .control_blocking_runtime import BLOCKING_MEASURE_KINDS, BlockingControlRuntime
from .control_escalator_runtime import EscalatorDirectionRuntime
from .control_event_evidence import AppliedControlEvent, record_control_event
from .control_facility_events import (
    build_facility_availability_events,
    facility_control_key,
)
from .control_guidance_runtime import StaffGuidanceRuntime
from .control_one_way_runtime import OneWayControlRuntime


class ControlTimelineController:
    """Coordinate measure-specific runtimes at scheduled tick boundaries."""

    def __init__(self, plan: ControlPlan | None) -> None:
        self.plan = plan
        self.measure_by_id = (
            {} if plan is None else {item.measure_id: item for item in plan.measures}
        )
        self.applied_events: list[AppliedControlEvent] = []
        self._active_measure_ids = {
            item.measure_id for item in self.measure_by_id.values() if item.initially_active
        }
        all_events = () if plan is None else plan.events
        self._runtime_events = tuple(
            event
            for event in all_events
            if self.measure_by_id[event.measure_id].kind != ACCESS_CLOSURE
        )
        self._facility_control_by_key = {
            facility_control_key(event, self.measure_by_id[event.measure_id]): event
            for event in all_events
            if self.measure_by_id[event.measure_id].kind == ACCESS_CLOSURE
        }
        self._next_runtime_event_index = 0
        self._pending_runtime_events: list[ControlEvent] = []
        self._captured_facility_event_count = 0
        self.blocking = BlockingControlRuntime()
        self.one_way = OneWayControlRuntime()
        self.escalators = EscalatorDirectionRuntime()
        self.guidance = StaffGuidanceRuntime()

    @property
    def has_pending_events(self) -> bool:
        return bool(self._pending_runtime_events) or (
            self._next_runtime_event_index < len(self._runtime_events)
        )

    def validate_model(self, model: Any) -> None:
        self._validate_facility_targets(model.facilities_by_id)
        self.blocking.validate_model(model, self.measure_by_id)
        self.one_way.validate_model(model, self.measure_by_id)
        self.escalators.validate_model(model, self.measure_by_id)
        self.guidance.validate_model(model, self.measure_by_id)

    def facility_availability_events(self) -> tuple[FacilityAvailabilityEvent, ...]:
        return build_facility_availability_events(
            self.measure_by_id.values(),
            self._facility_control_by_key,
        )

    def apply_due(self, model: Any) -> None:
        blocked_measure_ids: set[str] = set()
        pending = self._pending_runtime_events
        self._pending_runtime_events = []
        for event in pending:
            if event.measure_id in blocked_measure_ids or not self._apply_event(model, event):
                self._pending_runtime_events.append(event)
                blocked_measure_ids.add(event.measure_id)
        while self._next_runtime_event_index < len(self._runtime_events):
            event = self._runtime_events[self._next_runtime_event_index]
            if event.at_seconds > model.current_time_seconds:
                return
            self._next_runtime_event_index += 1
            if event.measure_id in blocked_measure_ids or not self._apply_event(model, event):
                self._pending_runtime_events.append(event)
                blocked_measure_ids.add(event.measure_id)

    def capture_facility_results(self, model: Any) -> None:
        new_events = model.disruption_controller.applied_events[
            self._captured_facility_event_count :
        ]
        self._captured_facility_event_count += len(new_events)
        for applied in new_events:
            key = (applied.scheduled_seconds, applied.facility_id, applied.action)
            event = self._facility_control_by_key.get(key)
            if event is None:
                continue
            measure = self.measure_by_id[event.measure_id]
            self._set_active(event, measure)
            self._record(
                model,
                event,
                measure,
                "applied",
                {
                    "queue_persons_before": applied.queue_persons_before,
                    "passengers_replanned": applied.passengers_replanned,
                    "active_service_persons_before": applied.active_service_persons_before,
                    "effective_disabled": applied.effective_disabled,
                },
            )

    def constrain_movement(
        self,
        model: Any,
        passenger: Any,
        result: MovementResult,
    ) -> MovementResult:
        return self.one_way.constrain(
            model, passenger, result, self._active_measure_ids, self.measure_by_id
        )

    def guidance_cost_adjustment(self, passenger: Any, facility: Any) -> float:
        return self.guidance.cost_adjustment(
            passenger, facility, self._active_measure_ids, self.measure_by_id
        )

    def record_guided_selection(self, passenger: Any, facility: Any) -> None:
        self.guidance.record_selection(
            passenger, facility, self._active_measure_ids, self.measure_by_id
        )

    def active_obstacle_geometry(self, level_id: str | None = None):
        return self.blocking.active_obstacles(
            self._active_measure_ids, self.measure_by_id, level_id
        )

    def events_at(self, time_seconds: float) -> tuple[dict[str, Any], ...]:
        return tuple(
            event.as_dict()
            for event in self.applied_events
            if event.applied_seconds == float(time_seconds)
        )

    def active_controls(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            self.measure_by_id[measure_id].as_dict()
            for measure_id in sorted(self._active_measure_ids)
        )

    def _apply_event(self, model: Any, event: ControlEvent) -> bool:
        measure = self.measure_by_id[event.measure_id]
        if (
            event.action in DEACTIVATING_ACTIONS
            and measure.measure_id not in self._active_measure_ids
        ):
            self._record(model, event, measure, "rejected", {"reason": "measure_not_active"})
            return True
        status, details = self._dispatch(model, measure, event)
        if status == "deferred":
            return False
        if status == "applied":
            self._set_active(event, measure)
            if measure.kind in BLOCKING_MEASURE_KINDS:
                approach_replans = int(model.invalidate_walkable_area_cache() or 0)
                model.movement_backend.on_walkable_geometry_changed(model)
                evacuation_replans = int(
                    model.refresh_evacuation_routes_for_topology_change(
                        force_all=True,
                    )
                )
                details["passengers_replanned"] = (
                    approach_replans + evacuation_replans
                )
        self._record(model, event, measure, status, details)
        return True

    def _dispatch(self, model, measure, event):
        if measure.kind in BLOCKING_MEASURE_KINDS:
            return self.blocking.apply(model, measure, event.action)
        if measure.kind == ONE_WAY_CHANNEL:
            return self.one_way.apply(measure, event)
        if measure.kind == ESCALATOR_DIRECTION:
            return self.escalators.apply(model, measure, event)
        if measure.kind == STAFF_GUIDANCE:
            return self.guidance.apply(model, measure, event)
        raise ValueError(f"unsupported runtime control measure: {measure.kind!r}")

    def _set_active(self, event: ControlEvent, measure: ControlMeasure) -> None:
        if event.action in ACTIVATING_ACTIONS:
            self._active_measure_ids.add(measure.measure_id)
        else:
            self._active_measure_ids.discard(measure.measure_id)

    def _validate_facility_targets(self, facilities_by_id: dict[str, Any]) -> None:
        unknown = sorted(
            str(measure.target_id)
            for measure in self.measure_by_id.values()
            if measure.kind == ACCESS_CLOSURE and measure.target_id not in facilities_by_id
        )
        if unknown:
            raise ValueError(
                "control plan contains unknown facility targets: " + ", ".join(unknown)
            )

    def _record(self, model, event, measure, status, details) -> None:
        self.applied_events.append(
            record_control_event(model, event, measure, status=status, details=details)
        )
