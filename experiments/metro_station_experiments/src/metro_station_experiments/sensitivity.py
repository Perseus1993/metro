from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_METRICS = (
    "clearance_time_seconds",
    "peak_local_density_persons_m2",
    "completion_rate",
)


def sensitivity_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    metrics: Sequence[str] = DEFAULT_METRICS,
    min_relative_span: float = 0.001,
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("sensitivity_parameter", "unknown"))].append(row)
    parameters = [
        _parameter_report(parameter, grouped[parameter], metrics)
        for parameter in sorted(grouped)
    ]
    failed_variants = [
        item
        for parameter in parameters
        for item in parameter["failed_variants"]
    ]
    inert_parameters = [
        {
            "parameter": parameter["parameter"],
            "issue": "sensitivity.no_observable_effect",
            "max_relative_span": max(
                (
                    metric["relative_span"] or 0.0
                    for metric in parameter["metrics"].values()
                ),
                default=0.0,
            ),
        }
        for parameter in parameters
        if all(
            (metric["relative_span"] or 0.0) < min_relative_span
            for metric in parameter["metrics"].values()
        )
    ]
    ranking = sorted(
        (
            {
                "parameter": parameter["parameter"],
                "max_relative_span": max(
                    (
                        metric["relative_span"] or 0.0
                        for metric in parameter["metrics"].values()
                    ),
                    default=0.0,
                ),
            }
            for parameter in parameters
        ),
        key=lambda item: (-item["max_relative_span"], item["parameter"]),
    )
    return {
        "status": "fail" if failed_variants or inert_parameters else "pass",
        "min_relative_span": min_relative_span,
        "parameters": parameters,
        "ranking": ranking,
        "failed_variants": failed_variants,
        "inert_parameters": inert_parameters,
    }


def _parameter_report(
    parameter: str,
    rows: list[Mapping[str, Any]],
    metrics: Sequence[str],
) -> dict[str, Any]:
    baselines = [row for row in rows if bool(row.get("sensitivity_baseline"))]
    if len(baselines) != 1:
        raise ValueError(f"parameter {parameter!r} requires exactly one baseline row")
    baseline = baselines[0]
    failed = [
        {
            "parameter": parameter,
            "value": float(row.get("sensitivity_value", 0.0)),
            "status": row.get("status"),
            "acceptance_status": row.get("acceptance_status"),
        }
        for row in rows
        if row.get("status") != "ok" or row.get("acceptance_status") == "fail"
    ]
    return {
        "parameter": parameter,
        "baseline_value": float(baseline.get("sensitivity_value", 0.0)),
        "variant_count": len(rows),
        "metrics": {
            metric: _metric_report(rows, baseline, metric)
            for metric in metrics
        },
        "failed_variants": failed,
    }


def _metric_report(
    rows: list[Mapping[str, Any]],
    baseline: Mapping[str, Any],
    metric: str,
) -> dict[str, Any]:
    baseline_value = _number(baseline.get(metric))
    variants = []
    values: list[float] = []
    for row in sorted(rows, key=lambda item: float(item.get("sensitivity_value", 0.0))):
        value = _number(row.get(metric))
        if value is not None:
            values.append(value)
        variants.append(
            {
                "value": float(row.get("sensitivity_value", 0.0)),
                "metric_value": value,
                "relative_change": _relative_change(value, baseline_value),
                "acceptance_status": row.get("acceptance_status"),
            }
        )
    relative_span = None
    if baseline_value not in {None, 0.0} and values:
        relative_span = (max(values) - min(values)) / abs(baseline_value)
    return {
        "baseline": baseline_value,
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
        "relative_span": None if relative_span is None else round(relative_span, 6),
        "variants": variants,
    }


def _number(value: Any) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    return parsed if isfinite(parsed) else None


def _relative_change(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline in {None, 0.0}:
        return None
    return round((value - baseline) / abs(baseline), 6)
