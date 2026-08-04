"""Product-facing analysis-case construction and validation."""

from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from metro_station.application.analysis_cases import (
    AnalysisCase,
    EvidenceStatus,
    clone_analysis_case,
    create_analysis_case,
    diff_analysis_cases,
    revise_case,
)
from metro_station.application.control_plans import ControlPlan, validate_control_plan_schedule


def build_baseline_case(
    request: Mapping[str, Any],
    compiled: Mapping[str, Any],
) -> AnalysisCase:
    _require_compiled_design(compiled)
    return create_analysis_case(
        name=str(request.get("case_name") or "Baseline"),
        design=_object(compiled, "document"),
        operations=_numeric_object(compiled.get("operations")),
        simulation=_simulation_controls(request),
        seeds=_seeds(request.get("seeds", (42,))),
        evidence=_evidence(request.get("evidence")),
        metadata={
            "template_id": str(request.get("template_id") or ""),
            "station_name": str(request.get("station_name") or "Station analysis"),
        },
    )


def build_candidate_case(
    request: Mapping[str, Any],
    compiled: Mapping[str, Any],
) -> AnalysisCase:
    baseline = AnalysisCase.from_dict(_object(request, "baseline"))
    _require_compiled_design(compiled)
    candidate = clone_analysis_case(
        baseline,
        name=str(request.get("case_name") or "Candidate"),
    )
    return revise_case(
        candidate,
        design=_object(compiled, "document"),
        operations=_numeric_object(compiled.get("operations")),
    )


def import_case(request: Mapping[str, Any]) -> AnalysisCase:
    payload = request.get("case", request)
    if not isinstance(payload, Mapping):
        raise ValueError("case must be an object")
    return AnalysisCase.from_dict(payload)


def case_differences(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    baseline = AnalysisCase.from_dict(_object(request, "baseline"))
    candidate = AnalysisCase.from_dict(_object(request, "candidate"))
    return [item.as_dict() for item in diff_analysis_cases(baseline, candidate)]


def _simulation_controls(request: Mapping[str, Any]) -> dict[str, Any]:
    horizon_minutes = _integer(request, "horizon_minutes", 5, minimum=2)
    tick_seconds = _integer(request, "tick_seconds", 1, minimum=1)
    controls: dict[str, Any] = {
        "demand_minutes": _integer(request, "demand_minutes", 1, minimum=1),
        "horizon_minutes": horizon_minutes,
        "tick_seconds": tick_seconds,
        "group_size": _integer(request, "group_size", 1, minimum=1),
        "movement_backend": str(request.get("movement_backend") or "batched_jupedsim"),
        "jupedsim_model": str(request.get("jupedsim_model") or "collision_free_speed"),
        "scenario_mode": _scenario_mode(request),
    }
    if controls["scenario_mode"] == "evacuation":
        controls["evacuation"] = _evacuation_controls(request, controls["group_size"])
    control_plan = _control_plan(request.get("control_plan"), horizon_minutes, tick_seconds)
    if control_plan is not None:
        controls["control_plan"] = control_plan.as_dict()
    return controls


def _scenario_mode(request: Mapping[str, Any]) -> str:
    result = str(request.get("scenario_mode") or "operations")
    if result not in {"operations", "evacuation"}:
        raise ValueError("scenario_mode must be operations or evacuation")
    return result


def _evacuation_controls(request: Mapping[str, Any], group_size: int) -> dict[str, Any]:
    persons = _integer(request, "initial_platform_persons", 6, minimum=1)
    if persons % group_size:
        raise ValueError("initial_platform_persons must be divisible by group_size")
    try:
        delay = float(request.get("alarm_delay_seconds", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("alarm_delay_seconds must be a number") from exc
    if not isfinite(delay) or delay < 0:
        raise ValueError("alarm_delay_seconds must be finite and >= 0")
    return {
        "initial_platform_persons": persons,
        "alarm_delay_seconds": delay,
        "stop_train_service": bool(request.get("stop_train_service", True)),
    }


def _control_plan(
    value: Any,
    horizon_minutes: int,
    tick_seconds: int,
) -> ControlPlan | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("control_plan must be an object")
    plan = ControlPlan.from_dict(value)
    validate_control_plan_schedule(
        plan,
        horizon_seconds=horizon_minutes * 60,
        tick_seconds=tick_seconds,
    )
    return plan


def _evidence(value: Any) -> EvidenceStatus:
    if value is None:
        return EvidenceStatus()
    if not isinstance(value, Mapping):
        raise ValueError("evidence must be an object")
    return EvidenceStatus.from_dict(value)


def _seeds(value: Any) -> tuple[int, ...]:
    source = value.split(",") if isinstance(value, str) else value
    if not isinstance(source, (list, tuple)):
        raise ValueError("seeds must be an array or comma-separated string")
    try:
        return tuple(int(seed) for seed in source)
    except (TypeError, ValueError) as exc:
        raise ValueError("every seed must be an integer") from exc


def _integer(
    source: Mapping[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
) -> int:
    try:
        result = int(source.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if result < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    return result


def _object(source: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return dict(value)


def _numeric_object(value: Any) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        raise ValueError("compiled operations must be an object")
    if not all(
        isinstance(item, int | float) and not isinstance(item, bool) for item in value.values()
    ):
        raise ValueError("compiled operations must contain only numbers")
    return dict(value)


def _require_compiled_design(compiled: Mapping[str, Any]) -> None:
    if compiled.get("summary", {}).get("status") == "error":
        raise ValueError("analysis case blocked: fix design validation errors first")
