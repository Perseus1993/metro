"""Directional movement constraints for scheduled one-way channels."""

from __future__ import annotations

from math import cos, radians, sin
from typing import Any, Mapping

from shapely.geometry import LineString

from metro_station.application.control_plans import (
    ONE_WAY_CHANNEL,
    SET_DIRECTION,
    ControlEvent,
    ControlMeasure,
)

from ..movement.backend import MovementResult
from .control_geometry import validate_control_shape


class OneWayControlRuntime:
    """Reject movement segments that oppose an active channel direction."""

    def __init__(self) -> None:
        self.shape_by_measure_id: dict[str, Any] = {}
        self.direction_by_measure_id: dict[str, str] = {}

    def validate_model(
        self,
        model: Any,
        measures: Mapping[str, ControlMeasure],
    ) -> None:
        for measure in measures.values():
            if measure.kind != ONE_WAY_CHANNEL:
                continue
            if measure.initially_active:
                raise ValueError("one_way_channel requires an explicit t=0 set_direction event")
            self.shape_by_measure_id[measure.measure_id] = validate_control_shape(
                model,
                measure,
            )

    def apply(
        self,
        measure: ControlMeasure,
        event: ControlEvent,
    ) -> tuple[str, dict[str, Any]]:
        if event.action == SET_DIRECTION:
            direction = str(event.parameters["direction"])
            self.direction_by_measure_id[measure.measure_id] = direction
            return "applied", {"direction": direction}
        self.direction_by_measure_id.pop(measure.measure_id, None)
        return "applied", {}

    def constrain(
        self,
        model: Any,
        passenger: Any,
        result: MovementResult,
        active_measure_ids: set[str],
        measures: Mapping[str, ControlMeasure],
    ) -> MovementResult:
        violation = self._first_violation(passenger, result, active_measure_ids, measures)
        if violation is None:
            return result
        measure_id, direction = violation
        model.movement_backend.remove_passenger(passenger)
        passenger.last_replan_reason = f"one_way_direction:{measure_id}"
        model.audit.record(
            "one_way_direction_blocked",
            source="control_timeline",
            severity="info",
            step=model.step_index,
            context={"measure_id": measure_id, "direction": direction},
        )
        return MovementResult(int(passenger.unique_id), passenger.pos, reached=False)

    def _first_violation(self, passenger, result, active_ids, measures):
        dx = result.position[0] - passenger.pos[0]
        dy = result.position[1] - passenger.pos[1]
        if abs(dx) + abs(dy) <= 1e-9:
            return None
        segment = LineString((passenger.pos, result.position))
        for measure_id in sorted(active_ids):
            measure = measures[measure_id]
            if measure.kind != ONE_WAY_CHANNEL or measure.level_id != passenger.current_level_id:
                continue
            shape = self.shape_by_measure_id[measure_id]
            if not shape.intersects(segment):
                continue
            direction = self.direction_by_measure_id.get(measure_id)
            if direction and self._opposes(measure, direction, dx, dy):
                return measure_id, direction
        return None

    @staticmethod
    def _opposes(measure: ControlMeasure, direction: str, dx: float, dy: float) -> bool:
        rotation = float(measure.parameters["geometry"].get("rotation_deg", 0.0))
        axis = (cos(radians(rotation)), sin(radians(rotation)))
        sign = 1.0 if direction == "forward" else -1.0
        return (dx * axis[0] + dy * axis[1]) * sign < -1e-9
