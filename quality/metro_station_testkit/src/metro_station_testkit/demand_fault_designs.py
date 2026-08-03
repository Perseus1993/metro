from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.design.station_generation import generate_station

from .layout_exploration_case import LayoutExplorationCase
from .layout_recipe import LayoutRecipe
from .layout_scenario_generator import generate_layout
from .topology_trial_designs import (
    _apply_footprint,
    _apply_split_fare_gates,
    generate_topology_trial_design,
)


TOPOLOGY_BASES = ("TB1", "TB2", "TB3", "TB4")


def generate_demand_fault_design(topology_id: str) -> StationDesignDocument:
    if topology_id not in TOPOLOGY_BASES:
        raise ValueError(f"unknown demand/fault topology {topology_id!r}")
    if topology_id in {"TB3", "TB4"}:
        document = generate_topology_trial_design(_three_level_case(topology_id))
    else:
        document = _two_level_design(topology_id)
    return replace(
        document,
        id=f"pm028_e3_{topology_id.lower()}",
        label=f"PM-028 E3 {topology_id}",
        template_id="generated:demand_fault_trial",
        metadata={
            **document.metadata,
            "demand_fault_topology_id": topology_id,
        },
    )


def _two_level_design(topology_id: str) -> StationDesignDocument:
    document = generate_layout(
        LayoutRecipe(
            recipe_id=f"pm028_e3_{topology_id.lower()}",
            seed=20260731 if topology_id == "TB1" else 20260732,
            archetype=("two_level_island" if topology_id == "TB1" else "two_level_multi_access"),
            entrance_count=2,
            gate_count=2,
            elevator_count=2 if topology_id == "TB1" else 4,
            stairs_count=1,
            escalator_pair_count=1,
            mirror=False,
            asset_density="standard",
            geometry_variant=3 if topology_id == "TB1" else 4,
        )
    )
    document = _apply_footprint(document, "RECT" if topology_id == "TB1" else "L")
    if topology_id == "TB2":
        document = _apply_split_fare_gates(document)
    return generate_station(replace(document, queues=()))


def _three_level_case(topology_id: str) -> LayoutExplorationCase:
    return LayoutExplorationCase(
        suite_id="PM028-E3-DESIGN",
        case_id=f"E3-DESIGN-{topology_id}",
        generator_version="demand_fault_designs.v1",
        expected_class="VALID",
        factors={
            "footprint": "T" if topology_id == "TB3" else "NECK",
            "vertical": "CHAIN" if topology_id == "TB3" else "DUAL_CLUSTER",
            "fare": "SPLIT_ENTRY_EXIT" if topology_id == "TB3" else "BIDIRECTIONAL",
            "mirror": False,
            "level_count": 3,
        },
        seed=20260733 if topology_id == "TB3" else 20260734,
    )
