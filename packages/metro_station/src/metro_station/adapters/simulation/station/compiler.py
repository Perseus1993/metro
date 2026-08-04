from __future__ import annotations

from ..compilation.validation import validate_compiled_station_design
from ..design.schema import StationDesignDocument
from .geometry import document_walkable_geometry
from .layout_graph import LayoutGraph
from .runtime_layout import RuntimeStationLayout
from .scenario import StationSandboxScenario


class DesignCompiler:
    """Compile a station design document into runtime layout services."""

    @staticmethod
    def compile(
        document: StationDesignDocument,
        scenario: StationSandboxScenario,
    ) -> RuntimeStationLayout:
        compiled = validate_compiled_station_design(document, scenario)
        issues = compiled.issues
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            summary = "; ".join(f"{issue.code}: {issue.message}" for issue in errors[:5])
            raise ValueError(f"Station design validation failed: {summary}")

        if compiled.station_graph is None:
            raise ValueError("Station design compilation did not produce a graph")
        layout_graph = LayoutGraph.from_station_graph(
            compiled.station_graph,
            scenario,
            compiled_facilities=compiled.facilities,
            compiled_portal_bindings=compiled.facility_portal_bindings,
            compiled_portal_binding_variants=compiled.facility_portal_binding_variants,
            compiled_decision_holding_regions=compiled.decision_holding_regions,
            compiled_spatial_capacity_certificates=compiled.spatial_capacity_certificates,
            compiled_spatial_demand_contracts=compiled.spatial_demand_contracts,
        )
        return RuntimeStationLayout.from_layout_graph(
            layout_graph,
            walkable_geometry=document_walkable_geometry(document),
        )
