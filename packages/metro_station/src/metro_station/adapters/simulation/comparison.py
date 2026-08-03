"""Mesa adapter for the reproducible analysis-comparison use case."""

from __future__ import annotations

from typing import Any

from metro_station.application.analysis_cases import AnalysisCase
from metro_station.application.comparisons import (
    ComparisonRunSpec,
    RunSummary,
    build_run_summary,
)
from metro_station.application.control_plans import ControlPlan
from metro_station.application.simulation import SimulationRequest, run_simulation

from .design.schema import StationDesignDocument
from .design.validation import validate_design
from .executor import MesaSimulationExecutor
from .runtime.clearance_detection import build_clearance_debug
from .runtime.snapshots import FrameSnapshot
from .station.scenario import StationSandboxScenario
from .station.evacuation import EVACUATION_MODE, EvacuationScenarioConfig


_OPERATION_FIELDS = frozenset(
    {
        "boarding_persons_per_min",
        "elevator_boarding_seconds",
        "elevator_cabin_capacity_persons",
        "elevator_cycle_seconds",
        "elevator_max_dispatch_wait_seconds",
        "elevator_min_dispatch_persons",
        "elevator_speed_units_per_tick",
        "elevator_speed_m_s",
        "escalator_speed_units_per_tick",
        "escalator_speed_m_s",
        "stopped_escalator_walk_speed_m_s",
        "gate_service_persons_per_min",
        "stairs_speed_units_per_tick",
        "stairs_speed_m_s",
        "train_capacity_persons",
        "train_dwell_seconds",
        "train_headway_seconds",
        "walk_units_per_tick",
    }
)


class MesaComparisonExecutor:
    """Execute one frozen case without exposing Mesa to the application layer."""

    def execute(
        self,
        case: AnalysisCase,
        *,
        seed: int,
        role: str,
        spec: ComparisonRunSpec,
    ) -> RunSummary:
        document = StationDesignDocument.from_dict(case.design)
        raise_for_invalid_design(document)
        scenario = station_scenario_from_case(case, document)
        result = run_simulation(
            SimulationRequest(scenario=scenario, seed=seed),
            MesaSimulationExecutor(),
        )
        frames = [FrameSnapshot.from_any(frame).to_dict() for frame in result.frames]
        clearance = clearance_summary(build_clearance_debug(result.runtime))
        return build_run_summary(
            role=role,
            case_id=case.case_id,
            seed=seed,
            frames=frames,
            clearance=clearance,
            density_radius_m=spec.density_radius_m,
            density_threshold_persons_m2=spec.density_threshold_persons_m2,
        )


def station_scenario_from_case(
    case: AnalysisCase,
    document: StationDesignDocument,
) -> StationSandboxScenario:
    simulation = case.simulation
    operations = case.operations
    values: dict[str, Any] = {
        key: value for key, value in operations.items() if key in _OPERATION_FIELDS
    }
    values.update(
        {
            "station_name": str(case.metadata.get("station_name") or case.name),
            "hour": int(operations.get("hour", 18)),
            "minutes": int(simulation["horizon_minutes"]),
            "demand_minutes": int(simulation["demand_minutes"]),
            "tick_seconds": int(simulation["tick_seconds"]),
            "group_size": int(simulation.get("group_size", 1)),
            "entry_count_hour": max(0, int(operations.get("entry_count_hour", 0))),
            "exit_count_hour": max(0, int(operations.get("exit_count_hour", 0))),
            "transfer_count_hour": max(0, int(operations.get("transfer_count_hour", 0))),
            "source_label": "analysis_comparison",
            "sample_hours": 1,
            "station_design": document,
            "movement_backend_name": str(simulation.get("movement_backend", "batched_jupedsim")),
            "jupedsim_operational_model": str(
                simulation.get("jupedsim_model", "collision_free_speed")
            ),
            "simulation_clock_mode": "physical",
            "goal_graph_mode": "active",
            "audit_enabled": False,
            "audit_print_events": False,
            "control_plan": _control_plan(simulation.get("control_plan")),
            "scenario_mode": str(simulation.get("scenario_mode", "operations")),
            "evacuation": _evacuation_config(simulation),
        }
    )
    return StationSandboxScenario(**values)


def _evacuation_config(simulation: dict[str, Any]) -> EvacuationScenarioConfig | None:
    if str(simulation.get("scenario_mode", "operations")) != EVACUATION_MODE:
        return None
    payload = simulation.get("evacuation")
    if not isinstance(payload, dict):
        raise ValueError("evacuation analysis case requires simulation.evacuation")
    return EvacuationScenarioConfig(
        initial_platform_persons=int(payload.get("initial_platform_persons", 0)),
        alarm_delay_seconds=float(payload.get("alarm_delay_seconds", 0.0)),
        stop_train_service=bool(payload.get("stop_train_service", True)),
    )


def _control_plan(payload: Any) -> ControlPlan | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("analysis case simulation.control_plan must be an object")
    return ControlPlan.from_dict(payload)


def raise_for_invalid_design(document: StationDesignDocument) -> None:
    errors = [issue for issue in validate_design(document) if issue.severity == "error"]
    if not errors:
        return
    preview = "; ".join(f"{issue.code}: {issue.message}" for issue in errors[:3])
    raise ValueError(f"analysis case design is invalid: {preview}")


def clearance_summary(debug: dict[str, Any]) -> dict[str, Any]:
    counts = debug.get("counts", {})
    cleared = bool(debug.get("cleared"))
    return {
        "cleared": cleared,
        "right_censored": not cleared,
        "clearance_time_s": debug.get("clearance_time_s"),
        "remaining_agents": int(counts.get("active_persons", 0) or 0),
        "total_agents": int(counts.get("spawned_persons", 0) or 0),
    }
