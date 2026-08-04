from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping


@dataclass(frozen=True)
class EmergencyAcceptancePolicy:
    min_completion_rate: float | None = None
    max_clearance_seconds: float | None = None
    max_final_station_persons: int | None = None
    max_local_density_persons_m2: float | None = None

    def __post_init__(self) -> None:
        if self.min_completion_rate is not None:
            value = float(self.min_completion_rate)
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("min_completion_rate must be finite and between 0 and 1")
        for name, value in (
            ("max_clearance_seconds", self.max_clearance_seconds),
            ("max_local_density_persons_m2", self.max_local_density_persons_m2),
        ):
            if value is not None and (not isfinite(float(value)) or float(value) <= 0.0):
                raise ValueError(f"{name} must be finite and > 0")
        if self.max_final_station_persons is not None and int(
            self.max_final_station_persons
        ) < 0:
            raise ValueError("max_final_station_persons must be >= 0")

    @property
    def has_result_threshold(self) -> bool:
        return any(
            value is not None
            for value in (
                self.min_completion_rate,
                self.max_clearance_seconds,
                self.max_final_station_persons,
                self.max_local_density_persons_m2,
            )
        )


def assess_emergency_row(
    row: Mapping[str, Any],
    policy: EmergencyAcceptancePolicy,
) -> dict[str, Any]:
    if row.get("status") != "ok":
        return {
            "acceptance_status": "fail",
            "acceptance_issues": [str(row.get("error") or "emergency run failed")],
        }

    issues = _invariant_issues(row)
    completion = _optional_float(row.get("completion_rate"))
    if policy.min_completion_rate is not None:
        if completion is None:
            issues.append("evacuation completion rate is missing")
        elif completion < policy.min_completion_rate:
            issues.append(
                f"completion rate {completion:.1%} < {policy.min_completion_rate:.1%}"
            )

    if policy.max_clearance_seconds is not None:
        clearance = _optional_float(row.get("clearance_time_seconds"))
        if clearance is None:
            issues.append("clearance time is unavailable because evacuation is incomplete")
        elif clearance > policy.max_clearance_seconds:
            issues.append(
                f"clearance time {clearance:.1f}s > {policy.max_clearance_seconds:.1f}s"
            )

    if policy.max_final_station_persons is not None:
        remaining = _int(row.get("remaining_persons"))
        if remaining > policy.max_final_station_persons:
            issues.append(
                f"final station persons {remaining} > {policy.max_final_station_persons}"
            )

    if policy.max_local_density_persons_m2 is not None:
        density = _optional_float(row.get("peak_local_density_persons_m2"))
        if density is None:
            issues.append("peak local density is missing")
        elif density > policy.max_local_density_persons_m2:
            issues.append(
                f"peak local density {density:.3f} > "
                f"{policy.max_local_density_persons_m2:.3f} persons/m2"
            )

    status = "fail" if issues else "pass" if policy.has_result_threshold else "not_evaluated"
    return {"acceptance_status": status, "acceptance_issues": issues}


def _invariant_issues(row: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    accounting_error = _int(row.get("population_accounting_error_persons"))
    if accounting_error != 0:
        issues.append(f"evacuation population accounting error is {accounting_error}")
    stranded = _int(row.get("active_service_stranded_persons_final"))
    if stranded > 0:
        issues.append(f"{stranded} passengers remain stranded in disabled equipment")
    service_violations = _int(row.get("facility_service_start_violations"))
    if service_violations > 0:
        issues.append(f"{service_violations} services started in disabled intervals")
    arrival_violations = _int(row.get("train_arrival_during_suspension_violations"))
    if arrival_violations > 0:
        issues.append(f"{arrival_violations} trains arrived during suspension")
    return issues


def _int(value: Any) -> int:
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None
