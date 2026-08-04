from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping


@dataclass(frozen=True)
class PerformanceAcceptancePolicy:
    min_real_time_factor: float = 20.0
    max_wall_seconds: float = 120.0
    max_peak_memory_mb: float = 512.0
    require_scenario_acceptance: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("min_real_time_factor", self.min_real_time_factor),
            ("max_wall_seconds", self.max_wall_seconds),
            ("max_peak_memory_mb", self.max_peak_memory_mb),
        ):
            if not isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be finite and > 0")


def assess_performance(
    evidence: Mapping[str, Any],
    policy: PerformanceAcceptancePolicy,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if evidence.get("status") != "ok":
        issues.append(_issue("performance.execution_failed", "soak execution failed"))
    if policy.require_scenario_acceptance and evidence.get("acceptance_status") != "pass":
        issues.append(_issue("performance.scenario_failed", "scenario acceptance failed"))
    if int(evidence.get("population_accounting_error_persons") or 0) != 0:
        issues.append(_issue("performance.accounting_error", "population accounting is not zero"))

    expected_frames = int(evidence.get("expected_frame_count") or 0)
    actual_frames = int(evidence.get("frame_count") or 0)
    if expected_frames <= 0 or actual_frames != expected_frames:
        issues.append(
            _issue(
                "performance.incomplete_horizon",
                f"frame count {actual_frames} != expected {expected_frames}",
            )
        )
    memory_frames = int(evidence.get("memory_profile_frame_count") or 0)
    if evidence.get("memory_profile_status") != "ok" or memory_frames != expected_frames:
        issues.append(
            _issue(
                "performance.incomplete_memory_profile",
                f"memory profile frame count {memory_frames} != expected {expected_frames}",
            )
        )
    if int(evidence.get("memory_profile_population_accounting_error_persons") or 0) != 0:
        issues.append(
            _issue(
                "performance.memory_profile_accounting_error",
                "memory profile population accounting is not zero",
            )
        )

    _maximum_issue(issues, evidence, "wall_seconds", policy.max_wall_seconds)
    _maximum_issue(issues, evidence, "peak_traced_memory_mb", policy.max_peak_memory_mb)
    real_time_factor = _number(evidence.get("real_time_factor"))
    if real_time_factor is None or real_time_factor < policy.min_real_time_factor:
        issues.append(
            _issue(
                "performance.real_time_factor",
                f"real_time_factor {real_time_factor} < {policy.min_real_time_factor}",
            )
        )
    return {
        "status": "fail" if issues else "pass",
        "issues": issues,
        "policy": {
            "min_real_time_factor": policy.min_real_time_factor,
            "max_wall_seconds": policy.max_wall_seconds,
            "max_peak_memory_mb": policy.max_peak_memory_mb,
            "require_scenario_acceptance": policy.require_scenario_acceptance,
        },
    }


def _maximum_issue(
    issues: list[dict[str, Any]],
    evidence: Mapping[str, Any],
    metric: str,
    maximum: float,
) -> None:
    value = _number(evidence.get(metric))
    if value is None or value > maximum:
        issues.append(_issue(f"performance.{metric}", f"{metric} {value} > {maximum}"))


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
