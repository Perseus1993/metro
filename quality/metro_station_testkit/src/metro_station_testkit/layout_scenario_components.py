from __future__ import annotations

from dataclasses import dataclass, replace

from metro_station.adapters.simulation.design.schema import (
    DesignElement,
    StationDesignDocument,
)

from .layout_recipe import LayoutRecipe
from .layout_scenario_assets import generated_assets, top_footprint_bounds


DECORATIVE_KINDS = {"shop", "service_room", "equipment", "obstacle"}


@dataclass(frozen=True)
class GeneratedComponents:
    elements: tuple[DesignElement, ...]
    entrances: tuple[DesignElement, ...]
    gates: tuple[DesignElement, ...]
    elevators: tuple[DesignElement, ...]


def build_generated_components(
    document: StationDesignDocument,
    recipe: LayoutRecipe,
) -> GeneratedComponents:
    prototypes = _prototypes(document)
    entrances = _entrances(document, prototypes["entrance"], recipe)
    gates = _gates(document, prototypes["gate"], recipe)
    elevators = _elevators(document, prototypes.get("elevator"), recipe)
    elements = (
        *_retained_elements(document, recipe),
        *entrances,
        *gates,
        *elevators,
        *generated_assets(document, recipe),
    )
    return GeneratedComponents(
        elements=tuple(replace(element, ports=()) for element in elements),
        entrances=entrances,
        gates=gates,
        elevators=elevators,
    )


def _prototypes(document: StationDesignDocument) -> dict[str, DesignElement]:
    result: dict[str, DesignElement] = {}
    for element in document.elements:
        if element.kind in {"entrance", "gate", "elevator"}:
            result.setdefault(element.kind, element)
    return result


def _retained_elements(
    document: StationDesignDocument,
    recipe: LayoutRecipe,
) -> tuple[DesignElement, ...]:
    result: list[DesignElement] = []
    for element in document.elements:
        if element.kind in DECORATIVE_KINDS | {"entrance", "gate", "elevator"}:
            continue
        if element.id == "stairs_a" and recipe.stairs_count == 0:
            continue
        if (
            element.id in {"down_escalator_a", "up_escalator_a"}
            and recipe.escalator_pair_count == 0
        ):
            continue
        result.append(element)
    return tuple(result)


def _entrances(
    document: StationDesignDocument,
    prototype: DesignElement,
    recipe: LayoutRecipe,
) -> tuple[DesignElement, ...]:
    min_x, min_y, max_x, max_y = top_footprint_bounds(document)
    width = prototype.geometry.width_m
    height = prototype.geometry.height_m
    center_y = (min_y + max_y - height) / 2.0
    slots = (
        (min_x + 1.0, center_y),
        (max_x - width - 1.0, center_y),
        (min_x + 1.0, min_y + 2.0),
        (max_x - width - 1.0, max_y - height - 2.0),
    )
    ids = (prototype.id, "entrance_b", "entrance_c", "entrance_d")
    return tuple(
        replace(
            prototype,
            id=ids[index],
            label=f"Entrance {chr(65 + index)}",
            geometry=prototype.geometry.moved_to(*slots[index]),
            ports=(),
        )
        for index in range(recipe.entrance_count)
    )


def _gates(
    document: StationDesignDocument,
    prototype: DesignElement,
    recipe: LayoutRecipe,
) -> tuple[DesignElement, ...]:
    min_x, min_y, _, _ = top_footprint_bounds(document)
    delta_y = ((recipe.geometry_variant // 3) - 1) * 0.5
    slots = (
        (min_x + 14.0, min_y + 16.0 + delta_y),
        (min_x + 38.0, min_y + 16.0 - delta_y),
    )
    ids = (prototype.id, "gate_bank_b")
    return tuple(
        replace(
            prototype,
            id=ids[index],
            label=f"Gate bank {chr(65 + index)}",
            geometry=prototype.geometry.moved_to(*slots[index]),
            ports=(),
        )
        for index in range(recipe.gate_count)
    )


def _elevators(
    document: StationDesignDocument,
    prototype: DesignElement | None,
    recipe: LayoutRecipe,
) -> tuple[DesignElement, ...]:
    if recipe.elevator_count == 0 or prototype is None:
        return ()
    min_x, min_y, _, max_y = top_footprint_bounds(document)
    dx = ((recipe.geometry_variant % 3) - 1) * 0.5
    dy = (((recipe.geometry_variant // 3) % 3) - 1) * 0.5
    high_y = max_y - prototype.geometry.height_m - 7.0 + dy
    low_y = min_y + 2.0 - dy
    xs = (min_x + 52.0 + dx, min_x + 66.0, min_x + 80.0 - dx)
    slots = (
        (xs[1], high_y),
        (xs[0], high_y),
        (xs[2], high_y),
        (xs[0], low_y),
        (xs[1], low_y),
        (xs[2], low_y),
    )
    ids = (
        prototype.id,
        "elevator_b",
        "elevator_c",
        "elevator_d",
        "elevator_e",
        "elevator_f",
    )
    return tuple(
        replace(
            prototype,
            id=ids[index],
            label=f"Elevator {chr(65 + index)}",
            geometry=prototype.geometry.moved_to(*slots[index]),
            ports=(),
        )
        for index in range(recipe.elevator_count)
    )
