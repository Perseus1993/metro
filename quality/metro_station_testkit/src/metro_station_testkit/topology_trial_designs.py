from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.design.schema import (
    DesignConnection,
    ElementGeometry,
    StationDesignDocument,
)
from metro_station.adapters.simulation.design.station_generation import generate_station

from .layout_exploration_case import LayoutExplorationCase
from .layout_recipe import LayoutRecipe
from .layout_scenario_generator import generate_layout
from .layout_transforms import mirror_design_horizontally


FOOTPRINT_POINTS: dict[str, tuple[tuple[float, float], ...]] = {
    "RECT": ((2, 2), (118, 2), (118, 72), (2, 72)),
    "L": ((2, 2), (118, 2), (118, 72), (18, 72), (18, 50), (2, 50)),
    "T": ((2, 2), (118, 2), (118, 50), (76, 50), (76, 72), (44, 72), (44, 50), (2, 50)),
    "NECK": ((2, 2), (118, 2), (118, 72), (72, 72), (72, 50), (48, 50), (48, 72), (2, 72)),
    "U": ((2, 2), (118, 2), (118, 72), (82, 72), (82, 50), (38, 50), (38, 72), (2, 72)),
}


def generate_topology_trial_design(case: LayoutExplorationCase) -> StationDesignDocument:
    vertical = str(case.factors["vertical"])
    recipe = LayoutRecipe(
        recipe_id=case.case_id.lower(),
        seed=case.seed,
        archetype="three_level_transfer",
        entrance_count=2,
        gate_count=2,
        elevator_count=4 if vertical == "DUAL_CLUSTER" else 2,
        stairs_count=1,
        escalator_pair_count=1,
        mirror=False,
        asset_density="standard",
        geometry_variant=4,
    )
    document = generate_layout(recipe)
    document = _apply_footprint(document, str(case.factors["footprint"]))
    if vertical == "CHAIN":
        document = _apply_adjacent_elevator_chain(document)
    if str(case.factors["fare"]) == "SPLIT_ENTRY_EXIT":
        document = _apply_split_fare_gates(document)
    if bool(case.factors["mirror"]):
        document = mirror_design_horizontally(document)
    document = replace(
        document,
        id=f"topology_{case.case_id.lower()}",
        label=case.case_id,
        template_id="generated:topology_trial",
        metadata={
            **document.metadata,
            "layout_exploration_case": case.as_dict(),
        },
        queues=(),
    )
    return generate_station(document)


def _apply_footprint(
    document: StationDesignDocument,
    footprint_name: str,
) -> StationDesignDocument:
    points = FOOTPRINT_POINTS[footprint_name]
    levels = tuple(replace(level, footprint=points) for level in document.levels)
    elements = tuple(
        replace(element, geometry=ElementGeometry("polygon", points_m=points), ports=())
        if element.role == "floor"
        else replace(element, ports=())
        for element in document.elements
    )
    return replace(document, levels=levels, elements=elements, queues=())


def _apply_adjacent_elevator_chain(
    document: StationDesignDocument,
) -> StationDesignDocument:
    levels = tuple(level.id for level in sorted(document.levels, key=lambda item: item.order))
    floor_by_level = _primary_floor_by_level(document)
    elevators = tuple(element for element in document.elements if element.kind == "elevator")
    chain = {
        elevators[0].id: (levels[0], levels[1]),
        elevators[1].id: (levels[1], levels[2]),
    }
    elements = []
    for element in document.elements:
        connected = chain.get(element.id)
        if connected is None:
            elements.append(replace(element, ports=()))
            continue
        geometry = element.geometry
        if element.id == elevators[1].id:
            geometry = geometry.moved_to(78.0, 34.0)
        elements.append(
            replace(
                element,
                level_id=connected[0],
                connects_levels=connected,
                geometry=geometry,
                ports=(),
            )
        )
    chain_ids = set(chain)
    connections = [
        connection
        for connection in document.connections
        if connection.source_id not in chain_ids and connection.target_id not in chain_ids
    ]
    for elevator_id, (lower, upper) in chain.items():
        connections.extend(
            (
                DesignConnection(
                    f"conn_chain_{elevator_id}_{lower}",
                    elevator_id,
                    floor_by_level[lower],
                    "walk",
                    True,
                ),
                DesignConnection(
                    f"conn_chain_{elevator_id}_{upper}",
                    elevator_id,
                    floor_by_level[upper],
                    "vertical",
                    True,
                ),
            )
        )
    return replace(document, elements=tuple(elements), connections=tuple(connections), queues=())


def _apply_split_fare_gates(document: StationDesignDocument) -> StationDesignDocument:
    gates = tuple(element for element in document.elements if element.kind == "gate")
    entry_gate, exit_gate = gates[:2]
    gate_ids = {entry_gate.id, exit_gate.id}
    top_level = min(document.levels, key=lambda item: item.order).id
    top_floor = _primary_floor_by_level(document)[top_level]
    entrance_ids = tuple(element.id for element in document.elements if element.kind == "entrance")
    connectors = tuple(
        element.id
        for element in document.elements
        if element.role == "vertical_connector" and top_level in element.connects_levels
    )
    elements = tuple(
        replace(
            element,
            gate_direction=(
                "entry"
                if element.id == entry_gate.id
                else "exit" if element.id == exit_gate.id else element.gate_direction
            ),
            ports=(),
        )
        for element in document.elements
    )
    connections = [
        connection
        for connection in document.connections
        if connection.source_id not in gate_ids and connection.target_id not in gate_ids
    ]
    for entrance_id in entrance_ids:
        connections.append(
            DesignConnection(
                f"conn_split_{entrance_id}_entry",
                entrance_id,
                entry_gate.id,
                "walk",
                False,
                source_port_id="walk",
                target_port_id="service",
            )
        )
    for connector_id in connectors:
        connections.extend(
            (
                DesignConnection(
                    f"conn_split_entry_{connector_id}",
                    entry_gate.id,
                    connector_id,
                    "walk",
                    False,
                    source_port_id="release",
                    target_port_id=f"level:{top_level}",
                ),
                DesignConnection(
                    f"conn_split_{connector_id}_exit",
                    connector_id,
                    exit_gate.id,
                    "walk",
                    False,
                    source_port_id=f"level:{top_level}",
                    target_port_id="service",
                ),
            )
        )
    connections.append(
        DesignConnection(
            "conn_split_exit_to_floor",
            exit_gate.id,
            top_floor,
            "walk",
            False,
            source_port_id="release",
            target_port_id="walk",
        )
    )
    return replace(document, elements=elements, connections=tuple(connections), queues=())


def _primary_floor_by_level(document: StationDesignDocument) -> dict[str, str]:
    floors: dict[str, str] = {}
    for element in document.elements:
        if element.role == "floor":
            floors.setdefault(element.level_id, element.id)
    return floors
