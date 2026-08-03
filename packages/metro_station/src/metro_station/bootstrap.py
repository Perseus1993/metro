"""Composition root for the metro-station command-line interfaces.

Concrete adapters are imported lazily here so importing the public package and its
interfaces does not initialize Mesa, JuPedSim, the designer, or data-warehouse code.
The legacy adapter calls are temporary migration seams; production interfaces must
not import the legacy package directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

if TYPE_CHECKING:
    from metro_station.application.comparisons import (
        ComparisonProgress,
        ComparisonReport,
        ComparisonRunSpec,
    )
    from metro_station.application.comparisons import ExperimentPlan
    from metro_station.application.routing_plugins import EvacuationRoutingPort


def run_simulation(arguments: Sequence[str]) -> None:
    """Run the current concrete simulation adapter."""

    from metro_station.adapters.simulation.cli import main

    main(arguments)


def run_designer(arguments: Sequence[str]) -> None:
    """Run the optional designer application plugin."""

    applications = entry_points(group="metro_station.applications")
    designer = next((entry for entry in applications if entry.name == "designer"), None)
    if designer is None:
        raise SystemExit("Install metro-station-designer to use the designer command.")
    main = cast(Callable[[Sequence[str] | None], None], designer.load())
    main(arguments)


def validate_design_template(template_id: str) -> dict[str, Any]:
    """Validate a built-in station design through the concrete design adapter."""

    from metro_station.adapters.simulation.design import create_design, validate_design

    issues = validate_design(create_design(template_id))
    return {
        "design_template": template_id,
        "valid": not any(issue.severity == "error" for issue in issues),
        "issues": [issue.as_dict() for issue in issues],
    }


def validate_routing_plugin(
    manifest_path: str | Path,
    *,
    parameters: dict[str, Any] | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    """Run the ten-case routing SDK contract suite in isolated processes."""

    from metro_station.adapters.routing_plugins import validate_plugin_file

    report = validate_plugin_file(
        manifest_path,
        parameters=parameters,
        timeout_seconds=timeout_seconds,
    )
    return report.as_dict()


def execute_analysis_comparison(
    spec: ComparisonRunSpec,
    *,
    progress_callback: Callable[[ComparisonProgress], None] | None = None,
) -> ComparisonReport:
    """Run a frozen paired comparison through the concrete Mesa adapter."""

    from metro_station.adapters.simulation.comparison import MesaComparisonExecutor
    from metro_station.application.comparisons import run_comparison

    return run_comparison(
        spec,
        MesaComparisonExecutor(),
        progress_callback=progress_callback,
    )


def execute_algorithm_experiment(
    plan: ExperimentPlan,
    algorithms: dict[str, EvacuationRoutingPort],
    *,
    progress_callback: Callable[[ComparisonProgress], None] | None = None,
) -> ComparisonReport:
    """Run a routing-algorithm axis through the existing paired engine."""

    from metro_station.adapters.simulation.algorithm_comparison import (
        MesaAlgorithmComparisonExecutor,
    )
    from metro_station.application.comparisons import run_algorithm_experiment

    return run_algorithm_experiment(
        plan,
        MesaAlgorithmComparisonExecutor(plan, algorithms),
        progress_callback=progress_callback,
    )
