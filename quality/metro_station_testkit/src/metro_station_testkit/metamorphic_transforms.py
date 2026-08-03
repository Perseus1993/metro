from __future__ import annotations

from dataclasses import replace
from random import Random

from metro_station.adapters.simulation.design.schema import (
    ElementGeometry,
    LevelSpec,
    StationDesignDocument,
)
from metro_station.adapters.simulation.design.station_generation import generate_station

from .layout_transforms import mirror_design_horizontally
from .metamorphic_bases import generate_metamorphic_base


def apply_metamorphic_transform(
    document: StationDesignDocument,
    transform: str,
    *,
    seed: int,
) -> StationDesignDocument:
    if transform == "M1-REORDER":
        return reorder_design_collections(document, seed=seed)
    if transform == "M2-MIRROR":
        return generate_station(replace(mirror_design_horizontally(document), queues=()))
    if transform == "M3-REMOVE-DECOR":
        return remove_presentation_only_elements(document)
    if transform == "M4-ADD-ELEVATOR":
        return add_redundant_elevator(document)
    if transform == "M5-TRANSLATE":
        return translate_design(document, dx_m=2.0, dy_m=2.0)
    raise ValueError(f"unknown metamorphic transform {transform!r}")


def reorder_design_collections(
    document: StationDesignDocument,
    *,
    seed: int,
) -> StationDesignDocument:
    rng = Random(seed)

    def shuffled(items):
        values = list(items)
        rng.shuffle(values)
        return tuple(values)

    return replace(
        document,
        levels=shuffled(document.levels),
        elements=shuffled(
            tuple(replace(element, ports=shuffled(element.ports)) for element in document.elements)
        ),
        queues=shuffled(document.queues),
        connections=shuffled(document.connections),
    )


def remove_presentation_only_elements(
    document: StationDesignDocument,
) -> StationDesignDocument:
    removed = {
        element.id
        for element in document.elements
        if element.metadata.get("presentation_only") is True
        and element.metadata.get("blocking") is False
    }
    return replace(
        document,
        elements=tuple(element for element in document.elements if element.id not in removed),
        queues=tuple(queue for queue in document.queues if queue.owner_element_id not in removed),
        connections=tuple(
            connection
            for connection in document.connections
            if connection.source_id not in removed and connection.target_id not in removed
        ),
        metadata={**document.metadata, "removed_presentation_only_ids": sorted(removed)},
    )


def add_redundant_elevator(document: StationDesignDocument) -> StationDesignDocument:
    base_index = int(document.metadata["metamorphic_base_index"])
    recipe = document.metadata["layout_recipe"]
    level_count = int(recipe["level_count"])
    elevator_count = int(recipe["elevator_count"])
    if level_count == 1 or elevator_count >= 6:
        return replace(
            document,
            metadata={
                **document.metadata,
                "metamorphic_not_applicable": "single_level_or_elevator_contract_max",
            },
        )
    transformed = generate_metamorphic_base(
        base_index,
        elevator_count_override=elevator_count + 1,
    )
    return replace(
        transformed,
        id=document.id,
        metadata={
            **transformed.metadata,
            "metamorphic_added_elevator": True,
            "metamorphic_baseline_elevator_count": elevator_count,
        },
    )


def translate_design(
    document: StationDesignDocument,
    *,
    dx_m: float,
    dy_m: float,
) -> StationDesignDocument:
    levels = tuple(_translate_level(level, dx_m, dy_m) for level in document.levels)
    elements = tuple(
        replace(element, geometry=_translate_geometry(element.geometry, dx_m, dy_m), ports=())
        for element in document.elements
    )
    translated = replace(
        document,
        levels=levels,
        elements=elements,
        queues=(),
        metadata={**document.metadata, "translation_m": [dx_m, dy_m]},
    )
    return generate_station(translated)


def _translate_level(level: LevelSpec, dx_m: float, dy_m: float) -> LevelSpec:
    return replace(
        level,
        footprint=tuple((x + dx_m, y + dy_m) for x, y in level.footprint),
    )


def _translate_geometry(
    geometry: ElementGeometry,
    dx_m: float,
    dy_m: float,
) -> ElementGeometry:
    return replace(
        geometry,
        x_m=geometry.x_m + dx_m,
        y_m=geometry.y_m + dy_m,
        points_m=tuple((x + dx_m, y + dy_m) for x, y in geometry.points_m),
    )
