from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.design.schema import (
    DesignElement,
    ElementGeometry,
    LevelSpec,
    StationDesignDocument,
)
from metro_station_testkit.layout_recipe import LayoutRecipe
from metro_station_testkit.layout_scenario_generator import generate_layout

from .boundary_trial_baseline import boundary_baseline, design_validation_result


def run_constraint_boundary_probe(variant: str) -> tuple[bool, tuple[str, ...]]:
    return design_validation_result(_constraint_design(variant))


def _constraint_design(variant: str) -> StationDesignDocument:
    document = boundary_baseline()
    if variant == "LEVELS_0":
        return replace(document, levels=(), elements=(), queues=(), connections=())
    if variant == "LEVELS_1":
        return _single_level()
    controls = {"LEVELS_3", "GRID_ALIGNED", "GRID_OFFSET_1MM", "UNITS_METERS", "SCHEMA_CURRENT", "KIND_ALLOWED"}
    if variant in controls:
        return document
    if variant == "LEVELS_4":
        return _four_level(document)
    if variant.startswith("FLOOR_HEIGHT_"):
        return _level_value(document, "floor_to_floor_height_m", _tag_number(variant))
    if variant.startswith("DEPTH_"):
        return _level_value(document, "elevation_m", -_tag_number(variant))
    if variant.startswith("CANVAS_"):
        return _canvas_point(document, variant)
    if variant.startswith("UNITS_"):
        return replace(document, units="feet" if variant == "UNITS_UNKNOWN" else "")
    if variant.startswith("SCHEMA_"):
        return replace(document, schema_version="future/v99" if variant == "SCHEMA_UNKNOWN" else "")
    if variant == "KIND_UNKNOWN":
        return _unknown_kind(document)
    levels = list(document.levels)
    levels[1] = (
        replace(levels[1], order=levels[0].order)
        if variant == "DUPLICATE_ORDER"
        else replace(levels[1], elevation_m=levels[0].elevation_m)
    )
    return replace(document, levels=tuple(levels))


def _single_level() -> StationDesignDocument:
    return generate_layout(
        LayoutRecipe(
            "boundary-single-level",
            42,
            "single_terminal",
            1,
            1,
            0,
            0,
            0,
            False,
            "sparse",
            4,
        )
    )


def _four_level(document: StationDesignDocument) -> StationDesignDocument:
    prototype = document.levels[-1]
    new_level = LevelSpec("b4_probe", "B4 Probe", -24.0, 6.0, 3, prototype.footprint)
    floor = next(item for item in document.elements if item.role == "floor")
    new_floor = replace(floor, id="b4_probe_floor", level_id=new_level.id, ports=())
    return replace(document, levels=(*document.levels, new_level), elements=(*document.elements, new_floor))


def _level_value(document, field, value):
    levels = list(document.levels)
    levels[-1] = replace(levels[-1], **{field: value})
    return replace(document, levels=tuple(levels))


def _canvas_point(document: StationDesignDocument, variant: str) -> StationDesignDocument:
    x_m = {"CANVAS_WITHIN": 119.999, "CANVAS_EDGE": 120.0, "CANVAS_OUT": 120.001}[variant]
    points = ((2.0, 2.0), (120.0, 2.0), (120.0, 72.0), (2.0, 72.0))
    marker = DesignElement(
        f"canvas_{variant.lower()}",
        "obstacle",
        document.levels[0].id,
        ElementGeometry("point", x_m=x_m, y_m=70.0),
        variant,
    )
    return replace(
        document,
        levels=tuple(replace(level, footprint=points) for level in document.levels),
        elements=(*document.elements, marker),
    )


def _unknown_kind(document: StationDesignDocument) -> StationDesignDocument:
    item = next(element for element in document.elements if element.kind == "shop")
    return replace(
        document,
        elements=tuple(
            replace(element, kind="mystery") if element.id == item.id else element
            for element in document.elements
        ),
    )


def _tag_number(variant: str) -> float:
    tag = variant.rsplit("_", 1)[-1]
    if tag == "999":
        return 2.999 if "FLOOR" in variant else 27.999
    if tag == "001":
        return 12.001 if "FLOOR" in variant else 28.001
    return float(tag)
