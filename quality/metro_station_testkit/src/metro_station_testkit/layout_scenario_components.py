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
    retained = _retained_elements(document, recipe)
    entrances = _entrances(document, prototypes["entrance"], recipe)
    gates = _gates(document, prototypes["gate"], recipe)
    elevators = _elevators(
        document,
        prototypes.get("elevator"),
        recipe,
        gates=gates,
    )
    assets = generated_assets(
        document,
        recipe,
        occupied=(*retained, *entrances, *gates, *elevators),
    )
    elements = (
        *retained,
        *entrances,
        *gates,
        *elevators,
        *assets,
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
        (min_x + 14.0, min_y + 11.0 + delta_y),
        (min_x + 38.0, min_y + 11.0 - delta_y),
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
    *,
    gates: tuple[DesignElement, ...],
) -> tuple[DesignElement, ...]:
    if recipe.elevator_count == 0 or prototype is None:
        return ()
    min_x, min_y, max_x, _ = top_footprint_bounds(document)
    level_footprints = {
        level.id: level.footprint
        for level in document.levels
        if level.footprint
    }
    connected_min_x = max(
        (
            min(point[0] for point in level_footprints[level_id])
            for level_id in prototype.connects_levels
            if level_id in level_footprints
        ),
        default=min_x,
    )
    connected_max_x = min(
        (
            max(point[0] for point in level_footprints[level_id])
            for level_id in prototype.connects_levels
            if level_id in level_footprints
        ),
        default=max_x,
    )
    connected_min_y = max(
        (
            min(point[1] for point in level_footprints[level_id])
            for level_id in prototype.connects_levels
            if level_id in level_footprints
        ),
        default=min_y,
    )
    dx = ((recipe.geometry_variant % 3) - 1) * 0.35
    dy = (((recipe.geometry_variant // 3) % 3) - 1) * 0.35
    # Allocate the bank in the intersection of all connected levels.  The old
    # two-row hard-coded coordinates put the upper row through the platform
    # edge on every generated island station.  A single distributed bank keeps
    # the same cross-level XY contract while leaving a full queue-depth apron
    # before the fare line and platform edge.
    margin = max(2.0, prototype.geometry.width_m * 0.25)
    gate_right = max(
        (gate.geometry.bounds()[2] for gate in gates),
        default=connected_min_x,
    )
    # Fare queues are generated below their banks.  Put the shared lift bank
    # beyond the fare line so no compiled gate slot can occupy a lift body.
    left = max(connected_min_x + margin, gate_right + 2.0)
    right = connected_max_x - prototype.geometry.width_m - margin
    if right < left:
        left = connected_min_x + 1.0
        right = max(left, connected_max_x - prototype.geometry.width_m - 1.0)
    step = 0.0 if recipe.elevator_count <= 1 else (right - left) / (recipe.elevator_count - 1)
    if recipe.elevator_count > 1:
        # A lift body fitting inside the footprint is insufficient: every
        # facade also materializes an 8 m waiting apron.  Dense banks whose
        # centres are only the body width apart compile visually but produce
        # overlapping physical queue slots.  Expand the bank symmetrically
        # within the connected-level envelope before queue generation.
        minimum_step = max(prototype.geometry.width_m + 0.5, 8.01)
        if step < minimum_step:
            required_span = minimum_step * (recipe.elevator_count - 1)
            minimum_left = max(connected_min_x + 1.0, gate_right + 0.5)
            maximum_right = connected_max_x - prototype.geometry.width_m - 1.0
            if maximum_right - minimum_left < required_span - 1e-9:
                raise ValueError(
                    "connected levels cannot fit non-overlapping elevator queue aprons"
                )
            centered_left = (left + right - required_span) / 2.0
            left = min(
                max(centered_left, minimum_left),
                maximum_right - required_span,
            )
            right = left + required_span
            step = minimum_step
    low_y = connected_min_y + 2.0 - dy
    slots = tuple(
        (
            left + step * index + dx,
            low_y,
        )
        for index in range(recipe.elevator_count)
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
