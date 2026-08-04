from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class TimestepValidationPolicy:
    max_clearance_relative_error: float = 0.05
    max_density_absolute_error: float = 0.25
    max_completion_absolute_error: float = 0.001
    min_elapsed_speedup: float = 1.5


def validate_timestep_candidate(
    reference_rows: Iterable[Mapping[str, Any]],
    candidate_rows: Iterable[Mapping[str, Any]],
    policy: TimestepValidationPolicy | None = None,
) -> dict[str, Any]:
    active_policy = policy or TimestepValidationPolicy()
    reference = _index(reference_rows)
    candidate = _index(candidate_rows)
    issues: list[dict[str, Any]] = []
    if reference.keys() != candidate.keys():
        issues.append(
            {
                "code": "timestep.case_mismatch",
                "reference": sorted(reference),
                "candidate": sorted(candidate),
            }
        )
    case_ids = sorted(reference.keys() & candidate.keys())
    comparisons = [_compare(run_id, reference[run_id], candidate[run_id]) for run_id in case_ids]
    for comparison in comparisons:
        _check_case(comparison, active_policy, issues)
    reference_elapsed = sum(_number(reference[run_id].get("elapsed_seconds")) for run_id in case_ids)
    candidate_elapsed = sum(_number(candidate[run_id].get("elapsed_seconds")) for run_id in case_ids)
    speedup = reference_elapsed / candidate_elapsed if candidate_elapsed > 0 else 0.0
    if speedup < active_policy.min_elapsed_speedup:
        issues.append(
            {
                "code": "timestep.insufficient_speedup",
                "actual": round(speedup, 6),
                "required": active_policy.min_elapsed_speedup,
            }
        )
    return {
        "status": "fail" if issues else "pass",
        "case_count": len(comparisons),
        "elapsed_speedup": round(speedup, 6),
        "comparisons": comparisons,
        "issues": issues,
    }


def _index(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        run_id = str(row.get("run_id", ""))
        if not run_id or run_id in result:
            raise ValueError("rows require unique non-empty run_id values")
        result[run_id] = row
    return result


def _compare(
    run_id: str,
    reference: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    reference_clearance = _number(reference.get("clearance_time_seconds"))
    candidate_clearance = _number(candidate.get("clearance_time_seconds"))
    clearance_error = (
        abs(candidate_clearance - reference_clearance) / abs(reference_clearance)
        if reference_clearance
        else abs(candidate_clearance - reference_clearance)
    )
    return {
        "run_id": run_id,
        "clearance_relative_error": round(clearance_error, 6),
        "density_absolute_error": round(
            abs(
                _number(candidate.get("peak_local_density_persons_m2"))
                - _number(reference.get("peak_local_density_persons_m2"))
            ),
            6,
        ),
        "completion_absolute_error": round(
            abs(
                _number(candidate.get("completion_rate"))
                - _number(reference.get("completion_rate"))
            ),
            6,
        ),
    }


def _check_case(
    comparison: Mapping[str, Any],
    policy: TimestepValidationPolicy,
    issues: list[dict[str, Any]],
) -> None:
    limits = (
        ("clearance_relative_error", policy.max_clearance_relative_error),
        ("density_absolute_error", policy.max_density_absolute_error),
        ("completion_absolute_error", policy.max_completion_absolute_error),
    )
    for metric, limit in limits:
        if float(comparison[metric]) > limit:
            issues.append(
                {
                    "code": f"timestep.{metric}",
                    "run_id": comparison["run_id"],
                    "actual": comparison[metric],
                    "maximum": limit,
                }
            )


def _number(value: Any) -> float:
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError("comparison metrics must be finite")
    return parsed
