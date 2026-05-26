from __future__ import annotations

from ..design.schema import StationDesignDocument
from ..design.validation import validate_design
from .geometry import document_walkable_geometry
from .layout_graph import LayoutGraph
from .runtime_layout import RuntimeStationLayout
from .scenario import StationSandboxScenario
from .graph import StationGraph


class DesignCompiler:
    """Compile a station design document into runtime layout services."""

    @staticmethod
    def compile(
        document: StationDesignDocument,
        scenario: StationSandboxScenario,
    ) -> RuntimeStationLayout:
        issues = validate_design(document)
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            summary = "; ".join(f"{issue.code}: {issue.message}" for issue in errors[:5])
            raise ValueError(f"Station design validation failed: {summary}")

        station_graph = StationGraph.from_design(document)
        layout_graph = LayoutGraph.from_station_graph(station_graph, scenario)
        return RuntimeStationLayout.from_layout_graph(
            layout_graph,
            walkable_geometry=document_walkable_geometry(document),
        )
