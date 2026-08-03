"""Dynamic geometry operations for scheduled station controls."""

from __future__ import annotations

from typing import Any, Mapping

from shapely.geometry import Point as ShapelyPoint
from shapely.ops import unary_union

from metro_station.application.control_plans import ControlMeasure

from ..design.geometry import element_shape
from ..design.schema import ElementGeometry
from ..station.geometry import level_walkable_geometry


def validate_control_shape(model: Any, measure: ControlMeasure):
    document = model.scenario.station_design
    assert document is not None
    if measure.level_id not in document.level_by_id():
        raise ValueError(f"control measure references unknown level {measure.level_id!r}")
    geometry = ElementGeometry.from_dict(dict(measure.parameters["geometry"]))
    shape = element_shape(geometry)
    base = level_walkable_geometry(
        document,
        str(measure.level_id),
        model.layout_graph.walkable_geometry,
    )
    if shape.is_empty or not shape.is_valid:
        raise ValueError(f"control measure {measure.measure_id!r} has invalid geometry")
    if not base.covers(shape):
        raise ValueError(
            f"control measure {measure.measure_id!r} must stay inside its level walkable area"
        )
    if base.difference(shape).is_empty:
        raise ValueError(f"control measure {measure.measure_id!r} blocks its entire level")
    return shape


def passenger_occupies_shape(model: Any, measure: ControlMeasure, shape: Any) -> bool:
    clearance = float(model.scenario.jupedsim_agent_radius_units)
    blocked = shape.buffer(clearance)
    return any(
        passenger.current_level_id == measure.level_id
        and blocked.covers(ShapelyPoint(passenger.pos))
        for passenger in model.active_passengers()
    )


def combined_active_obstacles(
    shapes: Mapping[str, Any],
    active_measure_ids: set[str],
    measures: Mapping[str, ControlMeasure],
    level_id: str | None,
):
    selected = [
        shape
        for measure_id, shape in shapes.items()
        if measure_id in active_measure_ids
        and (level_id is None or measures[measure_id].level_id == level_id)
    ]
    return None if not selected else unary_union(selected)
