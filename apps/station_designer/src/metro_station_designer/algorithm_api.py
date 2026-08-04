"""Designer-facing registry, preflight, and experiment-plan composition."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from metro_station.adapters.routing_plugins import (
    RoutingAlgorithmRegistry,
    validate_plugin_file,
)
from metro_station.application.analysis_cases import AnalysisCase
from metro_station.application.comparisons import ExperimentPlan
from metro_station.application.experiment_templates import (
    experiment_template_catalog,
    validate_template_report,
)
from metro_station.bootstrap import execute_algorithm_experiment
from dataclasses import replace


ALGORITHM_CATALOG_SCHEMA_VERSION = "algorithm-catalog/v1"
_WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
_EXAMPLE_MANIFEST = _WORKSPACE_ROOT / "examples/evacuation_routing_plugin/manifest.json"
_LOCK = Lock()
_REGISTRY = RoutingAlgorithmRegistry.with_baseline()
if _EXAMPLE_MANIFEST.is_file():
    _REGISTRY.register_manifest_file(_EXAMPLE_MANIFEST)


def algorithm_catalog() -> dict[str, Any]:
    with _LOCK:
        algorithms = _REGISTRY.catalog()
    return {
        "schema_version": ALGORITHM_CATALOG_SCHEMA_VERSION,
        "algorithms": algorithms,
        "security_boundary": (
            "Reviewed local code in a separate process; this is not a security sandbox."
        ),
    }


def template_catalog() -> dict[str, Any]:
    return {
        "schema_version": "experiment-template-catalog/v1",
        "templates": [template.as_dict() for template in experiment_template_catalog()],
    }


def register_algorithm(request: Mapping[str, Any]) -> dict[str, Any]:
    raw_path = str(request.get("manifest_path", "")).strip()
    if not raw_path:
        raise ValueError("manifest_path must not be blank")
    path = Path(raw_path).expanduser()
    timeout = float(request.get("timeout_seconds", 2.0))
    report = validate_plugin_file(path, timeout_seconds=timeout)
    if not report.passed:
        raise ValueError("routing plugin failed the 10-case compatibility suite")
    with _LOCK:
        registration = _REGISTRY.register_manifest_file(path, timeout_seconds=timeout)
    return {"registration": registration.catalog_payload(), "contract_report": report.as_dict()}


def preflight_algorithm(request: Mapping[str, Any]) -> dict[str, Any]:
    with _LOCK:
        selection = _REGISTRY.preflight(request)
    return {
        "compatible": True,
        "selection": selection.as_dict(),
        "message": "manifest, API version, and parameters are compatible",
    }


def experiment_plan_from_request(request: Mapping[str, Any]) -> ExperimentPlan:
    if request.get("schema_version") == "experiment-plan/v1":
        plan = ExperimentPlan.from_dict(request)
        _preflight_plan(plan)
        return plan
    case_payload = request.get("analysis_case")
    algorithms = request.get("algorithms")
    if not isinstance(case_payload, Mapping) or not isinstance(algorithms, (list, tuple)):
        raise ValueError("algorithm experiment requires analysis_case and algorithms")
    with _LOCK:
        selections = tuple(_REGISTRY.preflight(item) for item in algorithms)
    if len(selections) != 2:
        raise ValueError("algorithm experiment requires exactly two selections")
    plan = ExperimentPlan.create(
        AnalysisCase.from_dict(case_payload),
        (selections[0], selections[1]),
        template_id=str(request.get("template_id", "evacuation-routing-comparison")),
    )
    _template(plan.template_id).validate_plan(plan)
    return plan


def import_experiment_plan(request: Mapping[str, Any]) -> dict[str, Any]:
    payload = request.get("plan", request)
    if not isinstance(payload, Mapping):
        raise ValueError("plan must be an object")
    return experiment_plan_from_request(payload).as_dict()


def execute_registered_experiment(plan, *, progress_callback=None):
    with _LOCK:
        context = _REGISTRY.open_plan(plan)
    with context as algorithms:
        report = execute_algorithm_experiment(
            plan,
            algorithms,
            progress_callback=progress_callback,
        )
    check = validate_template_report(_template(plan.template_id), report)
    return replace(report, aggregate={**report.aggregate, "template_check": check.as_dict()})


def _preflight_plan(plan: ExperimentPlan) -> None:
    with _LOCK:
        for selection in plan.algorithms:
            _REGISTRY.preflight(selection.as_dict())
    _template(plan.template_id).validate_plan(plan)


def _template(template_id: str):
    match = next(
        (item for item in experiment_template_catalog() if item.template_id == template_id),
        None,
    )
    if match is None:
        raise ValueError(f"unknown experiment template: {template_id!r}")
    return match
