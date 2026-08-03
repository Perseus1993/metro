from __future__ import annotations

from ..agents.passenger import PassengerAgent
from ..agents.transit import TrainAgent
from ..facilities.runtime import FacilityProcessAgent
from ..facilities.service_events import FacilityServiceEvent


class FacilityEventRuntimeMixin:
    """Record service events and coordinate disruption-triggered replanning."""

    def next_facility_service_event_id(self) -> int:
        self._facility_service_event_id += 1
        return self._facility_service_event_id

    def record_facility_service_event(self, event: FacilityServiceEvent) -> None:
        self.facility_service_events.append(event)
        self.observe_facility_service_completed(
            event.facility_id,
            event.passenger_ids,
            event.end_time,
        )

    def record_pending_facility_service_event(self, event: FacilityServiceEvent) -> None:
        self.facility_service_events.append(event)

    def observe_facility_service_completed(
        self,
        facility_id: str,
        passenger_ids: tuple[int, ...],
        time_seconds: float,
    ) -> None:
        for passenger_id in passenger_ids:
            passenger = next(
                (
                    item
                    for item in self.passengers
                    if int(item.unique_id) == int(passenger_id)
                ),
                None,
            )
            if passenger is None:
                continue
            self.goal_parity.record(
                passenger,
                stream="physical",
                kind="service_completed",
                time_seconds=max(float(time_seconds), float(self.current_time_seconds)),
                stage=passenger.current_goal.stage,
                facility_id=facility_id,
            )
            if passenger.evacuation_pending:
                self._activate_passenger_evacuation(
                    passenger,
                    completed_facility_id=facility_id,
                )
                continue
            self.goal_coordinator.service_completed(
                passenger,
                facility_id,
                time_seconds,
            )

    def passenger_has_active_facility_service(self, passenger: PassengerAgent) -> bool:
        facility_id = passenger.assigned_facility_id or passenger.current_goal.facility_id
        if facility_id is None:
            return False
        facility = self.facilities_by_id.get(facility_id)
        return bool(facility is not None and facility.has_active_service(passenger))

    def is_facility_disabled(self, facility_id: str) -> bool:
        controller = getattr(self, "disruption_controller", None)
        if controller is None:
            return facility_id in self.scenario.disabled_facility_ids
        return controller.is_disabled(facility_id)

    def is_train_service_suspended(self, platform_id: str) -> bool:
        controller = getattr(self, "train_disruption_controller", None)
        return bool(controller is not None and controller.is_suspended(platform_id))

    def train_capacity_for_platform(self, platform_id: str) -> int:
        controller = getattr(self, "train_disruption_controller", None)
        default = int(self.scenario.train_capacity_persons)
        return default if controller is None else controller.capacity_for(platform_id, default)

    def record_train_arrival(self, train: TrainAgent) -> None:
        self.train_disruption_controller.record_arrival(self, train)

    def record_train_arrival_cancelled(self, train: TrainAgent) -> None:
        self.train_disruption_controller.record_cancelled_arrival(self, train)

    def mark_facility_enabled(self, facility_id: str) -> None:
        self._facility_service_start_floors[facility_id] = self.current_time_seconds

    def facility_service_start_floor(self, facility_id: str) -> float:
        return float(self._facility_service_start_floors.get(facility_id, 0.0))

    def replan_queued_passengers_for_disruption(
        self,
        facility: FacilityProcessAgent,
    ) -> int:
        replanned = 0
        for passenger in list(facility.queue):
            changed = self.progress_monitor.replan_policy.replan(
                self,
                passenger,
                reason=f"facility_disabled:{facility.facility_id}",
                stalled_seconds=0.0,
            )
            replanned += int(changed)
        return replanned
