from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.design.schema import (
    DesignConnection,
    DesignElement,
    StationDesignDocument,
)
from metro_station.adapters.simulation.design.station_generation import generate_station
from metro_station.adapters.simulation.design.templates import create_design

from .layout_recipe import LayoutRecipe
from .layout_scenario_components import build_generated_components
from .layout_transforms import mirror_design_horizontally


BASE_TEMPLATES = {
    "single_terminal": "single_level_terminal",
    "two_level_island": "two_level_island_platform",
    "two_level_multi_access": "two_level_island_platform",
    "three_level_transfer": "three_level_transfer",
}


def generate_layout(recipe: LayoutRecipe) -> StationDesignDocument:
    base = create_design(BASE_TEMPLATES[recipe.archetype])
    components = build_generated_components(base, recipe)
    connections = _connections(
        base,
        components.elements,
        components.entrances,
        components.gates,
        components.elevators,
    )
    document = replace(
        base,
        id=f"generated_{recipe.recipe_id}",
        label=f"Generated {recipe.archetype} {recipe.recipe_id}",
        template_id=f"generated:{recipe.archetype}",
        elements=components.elements,
        queues=(),
        connections=connections,
        metadata={
            **base.metadata,
            "generation_state": "recipe_generated",
            "generated_by": "metro_station_testkit",
            "layout_recipe": recipe.as_dict(),
        },
    )
    if recipe.topology_footprint != "RECT":
        from .topology_trial_designs import _apply_footprint

        document = _apply_footprint(document, recipe.topology_footprint)
    if recipe.vertical_topology == "CHAIN":
        from .topology_trial_designs import _apply_adjacent_elevator_chain

        document = _apply_adjacent_elevator_chain(document)
    if recipe.fare_topology == "SPLIT_ENTRY_EXIT":
        from .topology_trial_designs import _apply_split_fare_gates

        document = _apply_split_fare_gates(document)
    if recipe.mirror:
        document = mirror_design_horizontally(document)
    return generate_station(document)


def _connections(
    base: StationDesignDocument,
    elements: tuple[DesignElement, ...],
    entrances: tuple[DesignElement, ...],
    gates: tuple[DesignElement, ...],
    elevators: tuple[DesignElement, ...],
) -> tuple[DesignConnection, ...]:
    known_ids = {element.id for element in elements}
    connections = list(base.connections)
    connections.extend(_cloned_connections(base.connections, entrances[0].id, entrances[1:]))
    connections.extend(_cloned_connections(base.connections, gates[0].id, gates[1:]))
    if elevators:
        connections.extend(_cloned_connections(base.connections, elevators[0].id, elevators[1:]))
    return tuple(
        connection
        for connection in connections
        if connection.source_id in known_ids and connection.target_id in known_ids
    )


def _cloned_connections(
    connections: tuple[DesignConnection, ...],
    prototype_id: str,
    clones: tuple[DesignElement, ...],
) -> tuple[DesignConnection, ...]:
    relevant = tuple(
        connection
        for connection in connections
        if prototype_id in {connection.source_id, connection.target_id}
    )
    return tuple(
        replace(
            connection,
            id=f"conn_generated_{clone.id}_{connection.id}",
            source_id=(clone.id if connection.source_id == prototype_id else connection.source_id),
            target_id=(clone.id if connection.target_id == prototype_id else connection.target_id),
        )
        for clone in clones
        for connection in relevant
    )
