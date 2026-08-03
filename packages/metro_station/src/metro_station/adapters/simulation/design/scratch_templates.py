from __future__ import annotations

from .schema import (
    DesignConstraints,
    DesignElement,
    DesignPort,
    ElementGeometry,
    LevelSpec,
    StationDesignDocument,
)


SCRATCH_TEMPLATE_LEVELS: dict[str, int] = {
    "scratch_single_level": 1,
    "scratch_two_level": 2,
    "scratch_three_level": 3,
}


def create_scratch_design(template_id: str) -> StationDesignDocument:
    level_count = SCRATCH_TEMPLATE_LEVELS[template_id]
    levels = tuple(_scratch_level(index, level_count) for index in range(level_count))
    elements = tuple(_floor_element(level) for level in levels)
    return StationDesignDocument(
        id=template_id,
        label=f"Scratch {level_count}-level station",
        template_id=template_id,
        constraints=DesignConstraints(
            max_levels=level_count,
            max_depth_m=max(8.0, float(level_count * 8)),
        ),
        levels=levels,
        elements=elements,
        metadata={
            "editor_scratch": True,
            "generation_state": "empty_shell",
        },
    )


def _scratch_level(index: int, level_count: int) -> LevelSpec:
    level_number = index + 1
    if level_count == 1:
        level_id = "l1_station"
        label = "L1 Station"
        elevation_m = 0.0
    else:
        level_id = f"b{level_number}_{_level_role(index, level_count)}"
        label = f"B{level_number} {_level_role(index, level_count).replace('_', ' ').title()}"
        elevation_m = -6.0 * level_number
    return LevelSpec(
        id=level_id,
        label=label,
        elevation_m=elevation_m,
        floor_to_floor_height_m=6.0,
        order=index,
        footprint=((4.0, 4.0), (116.0, 4.0), (116.0, 76.0), (4.0, 76.0)),
    )


def _level_role(index: int, level_count: int) -> str:
    if index == 0:
        return "concourse"
    if index == level_count - 1:
        return "platform"
    return "transfer"


def _floor_element(level: LevelSpec) -> DesignElement:
    geometry = ElementGeometry(
        "rect",
        x_m=4.0,
        y_m=4.0,
        width_m=112.0,
        height_m=72.0,
    )
    return DesignElement(
        id=f"floor_{level.id}",
        kind="walkable_area",
        level_id=level.id,
        geometry=geometry,
        label=f"{level.label} walkable floor",
        role="floor",
        movable=False,
        resizable=False,
        ports=(
            DesignPort(
                "walk",
                "walk",
                level_id=level.id,
                position_m=geometry.center(),
            ),
        ),
        metadata={"graph_node": True, "scratch_floor": True},
    )
