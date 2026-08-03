"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from metro_station.adapters.simulation.compilation.validation import validate_station_design
from metro_station.adapters.simulation.design import create_design, topology_templates
from metro_station.adapters.simulation.planning.goal_graph import GoalNodeKind
from metro_station.adapters.simulation.planning.journey_catalog_compiler import compile_journey_graph_catalog
from metro_station.adapters.simulation.planning.plan import AgentIntent, FacilityStage
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.graph import StationGraph
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario


LAYOUT_IDS = tuple(template.id for template in topology_templates())
REQUIRED_INTENTS = tuple(intent.value for intent in AgentIntent)
REQUIRED_FACILITY_STAGES = (
    FacilityStage.ENTRY_GATE.value,
    FacilityStage.EXIT_GATE.value,
    FacilityStage.BOARDING_DOOR.value,
)


@dataclass(frozen=True)
class LayoutContractReport:
    layout_id: str
    level_count: int
    graph_node_count: int
    graph_edge_count: int
    facility_counts: dict[str, int]
    vertical_stages_by_intent: dict[str, int]
    journey_stages_by_intent: dict[str, tuple[str, ...]]
    platform_ids: tuple[str, ...]
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, **asdict(self)}


def inspect_layout_contract(layout_id: str) -> LayoutContractReport:
    _require_layout_id(layout_id)
    document = create_design(layout_id)
    validation_issues = validate_station_design(document)
    station_graph = StationGraph.from_design(document)
    scenario = _contract_scenario(layout_id)
    layout = DesignCompiler.compile(document, scenario)
    catalog = compile_journey_graph_catalog(station_graph)
    facility_counts = Counter(spec.stage for spec in layout.facilities)
    journey_stages = {
        intent: tuple(
            node.facility_stage
            for node in catalog.graph_for_intent(intent).nodes
            if node.kind == GoalNodeKind.USE_FACILITY_STAGE.value
            and node.facility_stage is not None
        )
        for intent in REQUIRED_INTENTS
    }
    vertical_counts = {
        intent: station_graph.vertical_transfer_count_for_intent(intent)
        for intent in REQUIRED_INTENTS
    }
    platform_ids = tuple(item[0] for item in layout.platform_descriptors())
    all_journey_stages = {
        stage for stages in journey_stages.values() for stage in stages
    }
    checks = {
        "design_valid": not validation_issues,
        "station_graph_has_nodes": bool(station_graph.nodes),
        "station_graph_has_edges": bool(station_graph.edges),
        "no_compile_diagnostics": not station_graph.compile_diagnostics,
        "no_walkable_access_fallback": not any(
            edge.origin == "walkable_access_fallback" for edge in station_graph.edges
        ),
        "all_intents_compiled": all(
            catalog.graph_for_intent(intent) is not None for intent in REQUIRED_INTENTS
        ),
        "required_facilities_present": all(
            facility_counts[stage] > 0 for stage in REQUIRED_FACILITY_STAGES
        ),
        "journey_stages_have_facilities": all(
            facility_counts[stage] > 0 for stage in all_journey_stages
        ),
        "vertical_chain_matches_topology": all(
            journey_stages[intent].count(FacilityStage.VERTICAL_TRANSFER.value)
            == vertical_counts[intent]
            for intent in REQUIRED_INTENTS
        ),
        "platform_descriptor_present": bool(platform_ids),
        "facility_ids_unique": len({spec.facility_id for spec in layout.facilities})
        == len(layout.facilities),
        "facility_directions_valid": all(
            _facility_direction_valid(spec.stage, spec.direction)
            for spec in layout.facilities
        ),
    }
    return LayoutContractReport(
        layout_id=layout_id,
        level_count=len(document.levels),
        graph_node_count=len(station_graph.nodes),
        graph_edge_count=len(station_graph.edges),
        facility_counts=dict(sorted(facility_counts.items())),
        vertical_stages_by_intent=vertical_counts,
        journey_stages_by_intent=journey_stages,
        platform_ids=platform_ids,
        checks=checks,
    )


def _contract_scenario(layout_id: str) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name=f"layout_contract_{layout_id}",
        hour=18,
        minutes=1,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="layout_acceptance_contract",
        sample_hours=1,
        station_design=create_design(layout_id),
        simulation_clock_mode="physical",
        goal_graph_mode="active",
        audit_enabled=False,
        audit_print_events=False,
    )


def _facility_direction_valid(stage: str, direction: str) -> bool:
    allowed = {
        FacilityStage.ENTRY_GATE.value: {"in"},
        FacilityStage.EXIT_GATE.value: {"out"},
        FacilityStage.VERTICAL_TRANSFER.value: {"up", "down"},
        FacilityStage.BOARDING_DOOR.value: {"up", "down"},
    }
    return direction in allowed.get(stage, {direction})


def _require_layout_id(layout_id: str) -> None:
    if layout_id in LAYOUT_IDS:
        return
    raise ValueError(
        f"unknown layout acceptance template {layout_id!r}; "
        f"choose one of: {', '.join(LAYOUT_IDS)}"
    )
