"""Designer catalog for versioned station-control measures and targets."""

from __future__ import annotations

from typing import Any

from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.station.layout_graph import LayoutGraph
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.application.control_plans import (
    ACCESS_CLOSURE,
    CLOSE,
    CLOSURE_ZONE,
    DEPLOY,
    ESCALATOR_DIRECTION,
    ISOLATION_BARRIER,
    ONE_WAY_CHANNEL,
    OPEN,
    REMOVE,
    RESTORE_DIRECTION,
    SET_DIRECTION,
    STAFF_GUIDANCE,
    START_GUIDANCE,
    STOP_GUIDANCE,
    WATER_BARRIER,
)


_MEASURE_DEFINITIONS = (
    (WATER_BARRIER, "水马", DEPLOY, REMOVE, "geometry", True),
    (ISOLATION_BARRIER, "隔离栏", DEPLOY, REMOVE, "geometry", True),
    (CLOSURE_ZONE, "封闭区", DEPLOY, REMOVE, "geometry", True),
    (ONE_WAY_CHANNEL, "单向通道", SET_DIRECTION, RESTORE_DIRECTION, "geometry", True),
    (ACCESS_CLOSURE, "出入口关闭", CLOSE, OPEN, "facility", True),
    (ESCALATOR_DIRECTION, "扶梯方向调整", SET_DIRECTION, RESTORE_DIRECTION, "escalator", True),
    (STAFF_GUIDANCE, "人员引导", START_GUIDANCE, STOP_GUIDANCE, "facility", True),
)


def build_control_plan_catalog(
    document: StationDesignDocument,
    operations: dict[str, int | float],
) -> dict[str, Any]:
    return {
        "schema_version": "control-catalog/v1",
        "measure_types": [
            {
                "kind": kind,
                "label": label,
                "start_action": start,
                "end_action": end,
                "placement": placement,
                "runtime_status": "available" if available else "planned",
                "directions": _directions(kind),
            }
            for kind, label, start, end, placement, available in _MEASURE_DEFINITIONS
        ],
        "levels": [_level_payload(document, level.id, level.label) for level in document.levels],
        "facility_targets": _facility_targets(document, operations),
    }


def _facility_targets(
    document: StationDesignDocument,
    operations: dict[str, int | float],
) -> list[dict[str, Any]]:
    try:
        layout = LayoutGraph.from_design_document(document, _catalog_scenario(document, operations))
    except ValueError:
        return []
    return [
        {
            "id": facility.facility_id,
            "label": facility.label,
            "kind": facility.kind,
            "stage": facility.stage,
            "level_id": facility.entry_level_id,
            "direction": facility.direction,
        }
        for facility in layout.facilities
    ]


def _catalog_scenario(
    document: StationDesignDocument,
    operations: dict[str, int | float],
) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="control catalog",
        hour=int(operations.get("hour", 0)),
        minutes=1,
        tick_seconds=5,
        group_size=1,
        source_label="designer_control_catalog",
        sample_hours=1,
        station_design=document,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
    )


def _level_payload(
    document: StationDesignDocument,
    level_id: str,
    label: str,
) -> dict[str, Any]:
    walkable = next(
        (
            element
            for element in document.elements
            if element.level_id == level_id and element.kind == "walkable_area"
        ),
        None,
    )
    geometry = _default_geometry(None if walkable is None else walkable.geometry.bounds())
    return {"id": level_id, "label": label, "default_geometry": geometry}


def _default_geometry(bounds: tuple[float, float, float, float] | None) -> dict[str, Any]:
    min_x, min_y, max_x, max_y = bounds or (0.0, 0.0, 10.0, 10.0)
    width = min(2.0, max(0.5, (max_x - min_x) / 4.0))
    height = min(1.0, max(0.5, (max_y - min_y) / 4.0))
    return {
        "shape": "rect",
        "x_m": round((min_x + max_x - width) / 2.0, 3),
        "y_m": round((min_y + max_y - height) / 2.0, 3),
        "width_m": width,
        "height_m": height,
        "rotation_deg": 0.0,
        "points_m": [],
    }


def _directions(kind: str) -> list[str]:
    if kind == ESCALATOR_DIRECTION:
        return ["up", "down"]
    if kind == ONE_WAY_CHANNEL:
        return ["forward", "reverse"]
    return []
