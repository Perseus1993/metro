from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any, Iterable, Mapping


METRICS = (
    "clearance_time_seconds",
    "peak_local_density_persons_m2",
)


@dataclass(frozen=True)
class CalibrationValidationPolicy:
    min_matched_cases: int = 10
    max_clearance_mae_seconds: float = 30.0
    max_clearance_mape: float = 0.15
    max_density_mae_persons_m2: float = 0.5

    def __post_init__(self) -> None:
        if self.min_matched_cases <= 0:
            raise ValueError("min_matched_cases must be > 0")
        for name, value in (
            ("max_clearance_mae_seconds", self.max_clearance_mae_seconds),
            ("max_clearance_mape", self.max_clearance_mape),
            ("max_density_mae_persons_m2", self.max_density_mae_persons_m2),
        ):
            if not isfinite(float(value)) or float(value) < 0:
                raise ValueError(f"{name} must be finite and >= 0")


def missing_calibration_evidence(reason: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "matched_cases": 0,
        "metrics": {},
        "issues": [
            {
                "code": "calibration.observed_data_missing",
                "message": reason,
            }
        ],
    }


def validate_calibration(
    simulated_rows: Iterable[Mapping[str, Any]],
    observed_rows: Iterable[Mapping[str, Any]],
    *,
    calibration_dataset_id: str,
    validation_dataset_id: str,
    policy: CalibrationValidationPolicy | None = None,
) -> dict[str, Any]:
    active_policy = policy or CalibrationValidationPolicy()
    issues: list[dict[str, str]] = []
    if not calibration_dataset_id.strip() or not validation_dataset_id.strip():
        issues.append(_issue("calibration.dataset_id_missing", "dataset IDs must be non-empty"))
    elif calibration_dataset_id == validation_dataset_id:
        issues.append(
            _issue(
                "calibration.datasets_not_independent",
                "calibration and validation dataset IDs must differ",
            )
        )

    simulated = _by_run_id(simulated_rows, "simulated")
    observed = _by_run_id(observed_rows, "observed")
    matched_ids = sorted(simulated.keys() & observed.keys())
    if len(matched_ids) < active_policy.min_matched_cases:
        issues.append(
            _issue(
                "calibration.insufficient_matched_cases",
                f"matched cases {len(matched_ids)} < {active_policy.min_matched_cases}",
            )
        )

    metrics = {
        metric: _metric_errors(simulated, observed, matched_ids, metric)
        for metric in METRICS
    }
    clearance = metrics["clearance_time_seconds"]
    density = metrics["peak_local_density_persons_m2"]
    _limit(
        issues,
        "calibration.clearance_mae",
        clearance["mae"],
        active_policy.max_clearance_mae_seconds,
    )
    _limit(
        issues,
        "calibration.clearance_mape",
        clearance["mape"],
        active_policy.max_clearance_mape,
    )
    _limit(
        issues,
        "calibration.density_mae",
        density["mae"],
        active_policy.max_density_mae_persons_m2,
    )
    return {
        "status": "fail" if issues else "pass",
        "calibration_dataset_id": calibration_dataset_id,
        "validation_dataset_id": validation_dataset_id,
        "matched_cases": len(matched_ids),
        "matched_run_ids": matched_ids,
        "metrics": metrics,
        "issues": issues,
        "policy": {
            "min_matched_cases": active_policy.min_matched_cases,
            "max_clearance_mae_seconds": active_policy.max_clearance_mae_seconds,
            "max_clearance_mape": active_policy.max_clearance_mape,
            "max_density_mae_persons_m2": active_policy.max_density_mae_persons_m2,
        },
    }


def _by_run_id(rows: Iterable[Mapping[str, Any]], label: str) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        run_id = str(row.get("run_id", "")).strip()
        if not run_id:
            raise ValueError(f"{label} row is missing run_id")
        if run_id in indexed:
            raise ValueError(f"duplicate {label} run_id: {run_id}")
        indexed[run_id] = row
    return indexed


def _metric_errors(
    simulated: Mapping[str, Mapping[str, Any]],
    observed: Mapping[str, Mapping[str, Any]],
    matched_ids: list[str],
    metric: str,
) -> dict[str, Any]:
    pairs = []
    for run_id in matched_ids:
        predicted = _number(simulated[run_id].get(metric))
        actual = _number(observed[run_id].get(metric))
        if predicted is not None and actual is not None:
            pairs.append((predicted, actual))
    if not pairs:
        return {"pair_count": 0, "mae": None, "rmse": None, "mape": None}
    errors = [predicted - actual for predicted, actual in pairs]
    percentage_errors = [abs(error / actual) for error, (_, actual) in zip(errors, pairs) if actual]
    return {
        "pair_count": len(pairs),
        "mae": round(sum(abs(error) for error in errors) / len(errors), 6),
        "rmse": round(sqrt(sum(error * error for error in errors) / len(errors)), 6),
        "mape": (
            round(sum(percentage_errors) / len(percentage_errors), 6)
            if percentage_errors
            else None
        ),
    }


def _limit(
    issues: list[dict[str, str]],
    code: str,
    value: float | None,
    maximum: float,
) -> None:
    if value is None:
        issues.append(_issue(code, "metric is unavailable"))
    elif value > maximum:
        issues.append(_issue(code, f"{value} > {maximum}"))


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
