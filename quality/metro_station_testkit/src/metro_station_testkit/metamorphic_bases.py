from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.design.schema import (
    DesignElement,
    ElementGeometry,
    StationDesignDocument,
)
from metro_station.adapters.simulation.design.station_generation import generate_station

from .layout_corpus import generate_scenario_corpus
from .layout_recipe import LayoutRecipe
from .layout_scenario_generator import generate_layout
from .topology_trial_designs import (
    _apply_adjacent_elevator_chain,
    _apply_footprint,
    _apply_split_fare_gates,
)


BASE_COUNT = 20
BASE_FOOTPRINTS = ("RECT", "L", "T", "NECK")


def generate_metamorphic_base(
    base_index: int,
    *,
    elevator_count_override: int | None = None,
) -> StationDesignDocument:
    base_recipe = metamorphic_base_recipes()[base_index]
    recipe = base_recipe
    if elevator_count_override is not None:
        recipe = replace(recipe, elevator_count=elevator_count_override)
    footprint = BASE_FOOTPRINTS[base_index % len(BASE_FOOTPRINTS)]
    use_chain = base_recipe.archetype == "three_level_transfer" and base_recipe.elevator_count >= 2
    document = _apply_footprint(generate_layout(recipe), footprint)
    if use_chain:
        document = _apply_adjacent_elevator_chain(document)
    if recipe.gate_count == 2 and base_index % 2:
        document = _apply_split_fare_gates(document)
    document = _add_presentation_only_marker(document)
    document = replace(
        document,
        id=f"pm028_e4_base_{base_index:02d}",
        label=f"PM-028 E4 base {base_index:02d}",
        queues=(),
        metadata={
            **document.metadata,
            "metamorphic_base_index": base_index,
            "metamorphic_footprint": footprint,
            "metamorphic_vertical": ("CHAIN" if use_chain else "FULL"),
            "presentation_only_contract": "explicit_metadata.v1",
        },
    )
    return generate_station(document)


def metamorphic_base_recipes() -> tuple[LayoutRecipe, ...]:
    recipes = list(generate_scenario_corpus(count=BASE_COUNT, seed=20260718).recipes)
    recipes[-1] = replace(recipes[-1], elevator_count=6)
    return tuple(
        replace(recipe, recipe_id=f"pm028-e4-base-{index:02d}")
        for index, recipe in enumerate(recipes)
    )


def _add_presentation_only_marker(document: StationDesignDocument) -> StationDesignDocument:
    level = min(document.levels, key=lambda item: item.order)
    min_x = min(point[0] for point in level.footprint)
    min_y = min(point[1] for point in level.footprint)
    marker = DesignElement(
        id="presentation_marker",
        kind="obstacle",
        level_id=level.id,
        geometry=ElementGeometry(
            "rect",
            x_m=min_x + 0.4,
            y_m=min_y + 0.4,
            width_m=0.5,
            height_m=0.5,
        ),
        label="Presentation-only orientation marker",
        role="decoration",
        movable=False,
        resizable=False,
        metadata={"presentation_only": True, "blocking": False},
    )
    return replace(document, elements=(*document.elements, marker))


def footprint_coverage() -> dict[str, int]:
    return {
        name: sum(index % len(BASE_FOOTPRINTS) == position for index in range(BASE_COUNT))
        for position, name in enumerate(BASE_FOOTPRINTS)
    }
