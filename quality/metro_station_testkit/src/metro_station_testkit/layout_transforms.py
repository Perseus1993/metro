from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.design.schema import (
    ElementGeometry,
    LevelSpec,
    StationDesignDocument,
)


def mirror_design_horizontally(document: StationDesignDocument) -> StationDesignDocument:
    width = document.constraints.canvas_width_m
    return replace(
        document,
        levels=tuple(_mirror_level(level, width) for level in document.levels),
        elements=tuple(
            replace(element, geometry=_mirror_geometry(element.geometry, width), ports=())
            for element in document.elements
        ),
        queues=(),
        metadata={**document.metadata, "mirrored_horizontally": True},
    )


def _mirror_level(level: LevelSpec, width: float) -> LevelSpec:
    return replace(
        level,
        footprint=tuple((width - x, y) for x, y in reversed(level.footprint)),
    )


def _mirror_geometry(geometry: ElementGeometry, width: float) -> ElementGeometry:
    if geometry.shape in {"polygon", "polyline"}:
        return replace(
            geometry,
            x_m=width - geometry.x_m,
            points_m=tuple((width - x, y) for x, y in geometry.points_m),
            rotation_deg=(-geometry.rotation_deg) % 360.0,
        )
    return replace(
        geometry,
        x_m=width - geometry.x_m - geometry.width_m,
        rotation_deg=(-geometry.rotation_deg) % 360.0,
    )
