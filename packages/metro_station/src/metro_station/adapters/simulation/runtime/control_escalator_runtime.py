"""Safe runtime direction changes for escalator facilities."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from metro_station.application.control_plans import (
    ESCALATOR_DIRECTION,
    SET_DIRECTION,
    ControlEvent,
    ControlMeasure,
)

from ..facilities.process import QueueLayout
from ..facilities.runtime import EscalatorProcessAgent
from ..planning.plan import AgentIntent


class EscalatorDirectionRuntime:
    """Reverse idle escalators while preserving their facility identity."""

    def __init__(self) -> None:
        self.original_spec_by_measure_id: dict[str, Any] = {}

    def validate_model(
        self,
        model: Any,
        measures: Mapping[str, ControlMeasure],
    ) -> None:
        for measure in measures.values():
            if measure.kind != ESCALATOR_DIRECTION:
                continue
            if measure.initially_active:
                raise ValueError("escalator_direction requires an explicit t=0 set_direction event")
            facility = model.facilities_by_id.get(measure.target_id)
            if not isinstance(facility, EscalatorProcessAgent):
                raise ValueError(
                    f"control measure targets a non-escalator facility {measure.target_id!r}"
                )
            self.original_spec_by_measure_id[measure.measure_id] = facility.spec
            opposite = _opposite(facility.spec.direction)
            model.layout_graph.facility_portal_binding_variant(
                facility.facility_id,
                opposite,
            )

    def apply(
        self,
        model: Any,
        measure: ControlMeasure,
        event: ControlEvent,
    ) -> tuple[str, dict[str, Any]]:
        facility = model.facilities_by_id[measure.target_id]
        occupied = facility.queue_persons + facility.active_ride_persons
        if occupied:
            # Direction changes are safe-drain transactions.  The scheduled
            # timestamp is the earliest commit boundary; an in-flight body is
            # a temporary resource conflict, not a terminally invalid plan.
            return "deferred", {
                "reason": "escalator_not_idle",
                "queue_persons": facility.queue_persons,
                "active_ride_persons": facility.active_ride_persons,
            }
        original = self.original_spec_by_measure_id[measure.measure_id]
        desired = (
            str(event.parameters["direction"])
            if event.action == SET_DIRECTION
            else original.direction
        )
        previous = model.facility_portal_binding(facility.facility_id).direction
        desired_spec = (
            original
            if desired == original.direction
            else _spec_for_compiled_binding(
                original,
                model.layout_graph.facility_portal_binding_variant(
                    facility.facility_id,
                    desired,
                ),
            )
        )
        binding = model.activate_facility_portal_binding(
            facility,
            direction=desired,
            spec=desired_spec,
        )
        replanned = self._replan_targeting_passengers(model, facility.facility_id)
        return "applied", {
            "direction_before": previous,
            "direction_after": binding.direction,
            "passengers_replanned": replanned,
        }

    @staticmethod
    def _replan_targeting_passengers(model: Any, facility_id: str) -> int:
        replanned = model.refresh_evacuation_routes_for_topology_change(
            {facility_id},
            force_all=True,
        )
        for passenger in tuple(model.active_passengers()):
            if passenger.intent == AgentIntent.EVACUATE_STATION.value:
                continue
            current_id = passenger.assigned_facility_id or passenger.current_goal.facility_id
            if current_id != facility_id:
                continue
            changed = model.progress_monitor.replan_policy.replan(
                model,
                passenger,
                reason=f"facility_disabled:direction_changed:{facility_id}",
                stalled_seconds=0.0,
            )
            replanned += int(changed)
        return replanned


def _spec_for_compiled_binding(spec, binding):
    compiled_layout = QueueLayout(
        anchor=binding.queue_slots[0],
        per_row=1,
        col_step=(0.0, 0.0),
        row_step=(
            binding.queue_slots[1][0] - binding.queue_slots[0][0],
            binding.queue_slots[1][1] - binding.queue_slots[0][1],
        ),
        slots=binding.queue_slots,
    )
    return replace(
        spec,
        direction=binding.direction,
        position=binding.entry_point,
        exit_position=binding.exit_point,
        entry_level_id=binding.entry_level_id,
        exit_level_id=binding.exit_level_id,
        queue_layout=compiled_layout,
        release_route=tuple(reversed(spec.release_route)),
    )


def _opposite(direction: str) -> str:
    if direction == "up":
        return "down"
    if direction == "down":
        return "up"
    raise ValueError(f"escalator direction must be 'up' or 'down'; got {direction!r}")
