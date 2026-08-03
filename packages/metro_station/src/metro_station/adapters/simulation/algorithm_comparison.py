"""Mesa execution adapter for the paired evacuation-routing algorithm axis."""

from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import Any, Mapping

from metro_station.application.analysis_cases import AnalysisCase
from metro_station.application.comparisons import (
    ALGORITHM_ROLES,
    ComparisonRunSpec,
    ExperimentPlan,
    RunSummary,
    build_run_summary,
)
from metro_station.application.routing_plugins import EvacuationRoutingPort
from metro_station.application.simulation import SimulationRequest

from .comparison import (
    clearance_summary,
    raise_for_invalid_design,
    station_scenario_from_case,
)
from .design.schema import StationDesignDocument
from .executor import MesaSimulationExecutor
from .runtime.clearance_detection import build_clearance_debug
from .runtime.snapshots import FrameSnapshot


class MesaAlgorithmComparisonExecutor:
    """Bind the two comparison roles to two registered routing algorithms."""

    def __init__(
        self,
        plan: ExperimentPlan,
        algorithms: Mapping[str, EvacuationRoutingPort],
    ) -> None:
        if set(algorithms) != set(ALGORITHM_ROLES):
            raise ValueError("algorithm experiment requires baseline and candidate bindings")
        self.plan = plan
        self.algorithms = dict(algorithms)

    def execute(
        self,
        case: AnalysisCase,
        *,
        seed: int,
        role: str,
        spec: ComparisonRunSpec,
    ) -> RunSummary:
        selection = self._selection(role)
        input_fingerprint = self.plan.paired_input_fingerprint(seed)
        started = perf_counter()
        model = None
        try:
            self._validate_frozen_input(case, spec)
            document = StationDesignDocument.from_dict(case.design)
            raise_for_invalid_design(document)
            scenario = station_scenario_from_case(case, document)
            simulation = MesaSimulationExecutor(
                routing_algorithm=self.algorithms[role],
                routing_parameters=selection.parameters,
            )
            model = simulation.build_model(SimulationRequest(scenario=scenario, seed=seed))
            frames = model.run()
            _raise_for_routing_failure(model)
            summary = build_run_summary(
                role=role,
                case_id=case.case_id,
                seed=seed,
                frames=[FrameSnapshot.from_any(frame).to_dict() for frame in frames],
                clearance=clearance_summary(build_clearance_debug(model)),
                density_radius_m=spec.density_radius_m,
                density_threshold_persons_m2=spec.density_threshold_persons_m2,
            )
        except Exception as exc:
            return self._failed_summary(
                case,
                seed,
                role,
                selection,
                input_fingerprint,
                started,
                model,
                exc,
            )
        duration = (perf_counter() - started) * 1_000.0
        logs = _decision_logs(model)
        return replace(
            summary,
            algorithm_id=selection.plugin_id,
            algorithm_version=selection.plugin_version,
            algorithm_parameters=selection.parameters,
            paired_input_fingerprint=input_fingerprint,
            simulation_duration_ms=duration,
            routing_compute_duration_ms=_routing_duration(logs),
            routing_decision_logs=logs,
        )

    def _selection(self, role: str):
        try:
            index = ALGORITHM_ROLES.index(role)
        except ValueError as exc:
            raise ValueError(f"unsupported algorithm role: {role!r}") from exc
        return self.plan.algorithms[index]

    def _validate_frozen_input(self, case: AnalysisCase, spec: ComparisonRunSpec) -> None:
        if spec.experiment_id != self.plan.plan_id:
            raise ValueError("comparison spec does not belong to experiment plan")
        if case.semantic_fingerprint != self.plan.analysis_case.semantic_fingerprint:
            raise ValueError("algorithm paired input drifted from frozen analysis case")

    def _failed_summary(
        self, case, seed, role, selection, fingerprint, started, model, exc
    ) -> RunSummary:
        logs = _decision_logs(model)
        return RunSummary.failed(
            role=role,
            case_id=case.case_id,
            seed=seed,
            error=f"{type(exc).__name__}: {exc}",
            algorithm_id=selection.plugin_id,
            algorithm_version=selection.plugin_version,
            algorithm_parameters=selection.parameters,
            paired_input_fingerprint=fingerprint,
            simulation_duration_ms=(perf_counter() - started) * 1_000.0,
            routing_compute_duration_ms=_routing_duration(logs),
            routing_decision_logs=logs,
        )


def _decision_logs(model: Any) -> tuple[dict[str, Any], ...]:
    if model is None:
        return ()
    return tuple(log.as_dict() for log in getattr(model, "routing_decision_logs", ()))


def _raise_for_routing_failure(model: Any) -> None:
    getattr(model, "evacuation_routing").raise_if_failed()


def _routing_duration(logs: tuple[dict[str, Any], ...]) -> float:
    return sum(float(log.get("compute_duration_ms", 0.0)) for log in logs)
