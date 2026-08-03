from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Iterable

from ..station.disruptions import DISABLE_FACILITY, FacilityAvailabilityEvent

if TYPE_CHECKING:
    from .mesa_model import MetroStationModel


@dataclass(frozen=True)
class AppliedFacilityAvailabilityEvent:
    scheduled_seconds: int
    applied_seconds: float
    action: str
    facility_id: str
    queue_persons_before: int
    passengers_replanned: int
    served_persons_at_apply: int
    active_service_persons_before: int
    effective_disabled: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class FacilityDisruptionController:
    """Own dynamic availability state and auditable step-boundary transitions."""

    def __init__(
        self,
        events: tuple[FacilityAvailabilityEvent, ...],
        *,
        statically_disabled_ids: Iterable[str] = (),
    ) -> None:
        self.events = events
        self.static_disabled_ids = frozenset(statically_disabled_ids)
        self.dynamic_disabled_ids: set[str] = set()
        self.applied_events: list[AppliedFacilityAvailabilityEvent] = []
        self._next_event_index = 0

    def validate_facility_ids(self, available_ids: Iterable[str]) -> None:
        available = set(available_ids)
        scheduled = {event.facility_id for event in self.events}
        unknown = sorted(scheduled - available)
        if unknown:
            raise ValueError(
                "facility_availability_events contains unknown facilities: "
                + ", ".join(unknown)
            )

    def is_disabled(self, facility_id: str) -> bool:
        return (
            facility_id in self.static_disabled_ids
            or facility_id in self.dynamic_disabled_ids
        )

    @property
    def has_pending_events(self) -> bool:
        return self._next_event_index < len(self.events)

    def apply_due(self, model: MetroStationModel) -> None:
        while self._next_event_index < len(self.events):
            first = self.events[self._next_event_index]
            if first.at_seconds > model.current_time_seconds:
                return
            batch: list[FacilityAvailabilityEvent] = []
            while self._next_event_index < len(self.events):
                event = self.events[self._next_event_index]
                if event.at_seconds != first.at_seconds:
                    break
                batch.append(event)
                self._next_event_index += 1
            self._apply_batch(model, batch)

    def _apply_batch(
        self,
        model: MetroStationModel,
        events: list[FacilityAvailabilityEvent],
    ) -> None:
        queue_persons = {
            event.facility_id: int(model.facilities_by_id[event.facility_id].queue_persons)
            for event in events
        }
        active_persons = {
            event.facility_id: _active_service_persons(
                model.facilities_by_id[event.facility_id]
            )
            for event in events
        }
        for event in events:
            if event.action == DISABLE_FACILITY:
                self.dynamic_disabled_ids.add(event.facility_id)
                continue
            self.dynamic_disabled_ids.discard(event.facility_id)
            model.mark_facility_enabled(event.facility_id)

        for event in events:
            facility = model.facilities_by_id[event.facility_id]
            facility.on_availability_changed(
                disabled=event.action == DISABLE_FACILITY,
                time_seconds=model.current_time_seconds,
            )
            replanned = (
                model.replan_queued_passengers_for_disruption(facility)
                if event.action == DISABLE_FACILITY
                else 0
            )
            applied = AppliedFacilityAvailabilityEvent(
                scheduled_seconds=int(event.at_seconds),
                applied_seconds=float(model.current_time_seconds),
                action=event.action,
                facility_id=event.facility_id,
                queue_persons_before=queue_persons[event.facility_id],
                passengers_replanned=replanned,
                served_persons_at_apply=int(facility.served_persons),
                active_service_persons_before=active_persons[event.facility_id],
                effective_disabled=self.is_disabled(event.facility_id),
            )
            self.applied_events.append(applied)
            model.audit.record(
                "facility_availability_changed",
                source="disruption_controller",
                severity=(
                    "warning" if event.action == DISABLE_FACILITY else "info"
                ),
                step=model.step_index,
                context=applied.as_dict(),
            )
        # Exact evacuation connector paths are physical commitments, not a
        # permanent pin.  Recompute once after the whole same-time batch so an
        # atomic closure cannot leave valid alternatives marked unreachable.
        model.refresh_evacuation_routes_for_availability_change(
            {event.facility_id for event in events}
        )

    def applied_event_dicts(self) -> list[dict[str, object]]:
        return [event.as_dict() for event in self.applied_events]

    def service_start_violations(self, service_events: Iterable[object]) -> int:
        intervals = self._disabled_intervals()
        violations = 0
        for service_event in service_events:
            facility_id = str(getattr(service_event, "facility_id", ""))
            commit_time = getattr(service_event, "commit_time", None)
            service_commit_time = float(
                getattr(service_event, "start_time", -1.0)
                if commit_time is None
                else commit_time
            )
            if any(
                start <= service_commit_time < end
                for start, end in intervals.get(facility_id, ())
            ):
                violations += 1
        return violations

    def _disabled_intervals(self) -> dict[str, list[tuple[float, float]]]:
        intervals: dict[str, list[tuple[float, float]]] = {}
        open_intervals: dict[str, float] = {}
        for event in self.applied_events:
            if event.action == DISABLE_FACILITY:
                open_intervals[event.facility_id] = event.applied_seconds
                continue
            start = open_intervals.pop(event.facility_id, None)
            if start is not None:
                intervals.setdefault(event.facility_id, []).append(
                    (start, event.applied_seconds)
                )
        for facility_id, start in open_intervals.items():
            intervals.setdefault(facility_id, []).append((start, float("inf")))
        return intervals


def _active_service_persons(facility: object) -> int:
    cabin_load = getattr(facility, "cabin_load_persons", None)
    if cabin_load is not None:
        return int(cabin_load or 0)
    active_passes = getattr(facility, "active_passes", None)
    if active_passes is not None:
        return sum(
            int(getattr(active.passenger, "group_size", 0) or 0)
            for active in active_passes
        )
    return int(getattr(facility, "active_ride_persons", 0) or 0)
