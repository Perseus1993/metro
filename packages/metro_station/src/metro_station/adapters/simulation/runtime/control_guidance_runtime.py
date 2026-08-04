"""Staff-guidance runtime and facility-choice influence."""

from __future__ import annotations

from typing import Any, Mapping

from metro_station.application.control_plans import (
    STAFF_GUIDANCE,
    START_GUIDANCE,
    ControlEvent,
    ControlMeasure,
)

from ..agents.staff import AdminAgent
from ..facilities.runtime_base import FacilityProcessAgent


DEFAULT_GUIDANCE_INFLUENCE_SECONDS = 120.0


class StaffGuidanceRuntime:
    """Assign staff to a facility and bias passenger choices toward it."""

    def __init__(self) -> None:
        self.admin_by_measure_id: dict[str, AdminAgent] = {}
        self.guided_passenger_ids: dict[str, set[int]] = {}

    def validate_model(
        self,
        model: Any,
        measures: Mapping[str, ControlMeasure],
    ) -> None:
        for measure in measures.values():
            if measure.kind != STAFF_GUIDANCE:
                continue
            if measure.initially_active:
                raise ValueError("staff_guidance requires an explicit t=0 start_guidance event")
            target = model.facilities_by_id.get(measure.target_id)
            if not isinstance(target, FacilityProcessAgent):
                raise ValueError(
                    f"staff guidance targets an unknown facility {measure.target_id!r}"
                )

    def apply(
        self,
        model: Any,
        measure: ControlMeasure,
        event: ControlEvent,
    ) -> tuple[str, dict[str, Any]]:
        if event.action == START_GUIDANCE:
            admin = self._available_admin(model)
            facility = model.facilities_by_id[measure.target_id]
            admin.start_guidance(
                target_position=facility.spec.queue_anchor,
                target_id=facility.facility_id,
                level_id=model.facility_portal_binding(facility.facility_id).entry_level_id,
            )
            self.admin_by_measure_id[measure.measure_id] = admin
            self.guided_passenger_ids[measure.measure_id] = set()
            return "applied", {"admin_id": _admin_id(admin)}
        admin = self.admin_by_measure_id.pop(measure.measure_id, None)
        if admin is not None:
            admin.stop_guidance()
        guided = len(self.guided_passenger_ids.pop(measure.measure_id, set()))
        return "applied", {
            "admin_id": None if admin is None else _admin_id(admin),
            "guided": guided,
        }

    def cost_adjustment(
        self,
        passenger: Any,
        facility: Any,
        active_measure_ids: set[str],
        measures: Mapping[str, ControlMeasure],
    ) -> float:
        adjustments = [
            -float(measure.parameters.get("influence_seconds", DEFAULT_GUIDANCE_INFLUENCE_SECONDS))
            for measure_id, measure in measures.items()
            if measure_id in active_measure_ids
            and measure.kind == STAFF_GUIDANCE
            and measure.target_id == facility.facility_id
            and passenger.model.facility_portal_binding(
                facility.facility_id
            ).entry_level_id
            == passenger.current_level_id
        ]
        return min(adjustments, default=0.0)

    def record_selection(
        self,
        passenger: Any,
        facility: Any,
        active_measure_ids: set[str],
        measures: Mapping[str, ControlMeasure],
    ) -> None:
        for measure_id in active_measure_ids:
            measure = measures[measure_id]
            if measure.kind != STAFF_GUIDANCE or measure.target_id != facility.facility_id:
                continue
            seen = self.guided_passenger_ids.setdefault(measure_id, set())
            passenger_id = int(passenger.unique_id)
            if passenger_id in seen:
                continue
            seen.add(passenger_id)
            admin = self.admin_by_measure_id.get(measure_id)
            if admin is not None:
                admin.guided_count += int(passenger.group_size)

    @staticmethod
    def _available_admin(model: Any) -> AdminAgent:
        admin = next(
            (item for item in model.admin_agents if item.guidance_target_id is None),
            None,
        )
        if admin is not None:
            return admin
        admin = AdminAgent(
            model,
            patrol_route=[model.layout_graph.geometry.paid_hall_center],
            guide_radius=model.scenario.admin_guide_radius_units,
        )
        model.admin_agents.append(admin)
        return admin


def _admin_id(admin: AdminAgent) -> int:
    if admin.unique_id is None:
        raise RuntimeError("guidance admin must be registered with the model")
    return int(admin.unique_id)
