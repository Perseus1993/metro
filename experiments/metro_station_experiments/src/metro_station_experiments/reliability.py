from __future__ import annotations

from collections import defaultdict
from math import ceil, floor, isfinite
from random import Random
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence


def reliability_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    min_samples: int = 30,
    bootstrap_samples: int = 2000,
    bootstrap_seed: int = 20260712,
) -> dict[str, Any]:
    if min_samples <= 0:
        raise ValueError("min_samples must be > 0")
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be > 0")
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row.get("initial_persons", 0) or 0)].append(row)
    groups = [
        _group_report(
            population,
            grouped[population],
            min_samples=min_samples,
            bootstrap_samples=bootstrap_samples,
            bootstrap_seed=bootstrap_seed + population,
        )
        for population in sorted(grouped)
    ]
    return {
        "status": _overall_status(groups),
        "min_samples": min_samples,
        "bootstrap_samples": bootstrap_samples,
        "groups": groups,
        "blockers": [
            blocker
            for group in groups
            for blocker in group["blockers"]
        ],
    }


def percentile(values: Sequence[float], probability: float) -> float | None:
    finite = sorted(float(value) for value in values if isfinite(float(value)))
    if not finite:
        return None
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between 0 and 1")
    position = (len(finite) - 1) * probability
    lower = floor(position)
    upper = ceil(position)
    if lower == upper:
        return finite[lower]
    fraction = position - lower
    return finite[lower] * (1.0 - fraction) + finite[upper] * fraction


def bootstrap_mean_interval(
    values: Sequence[float],
    *,
    samples: int,
    seed: int,
    confidence: float = 0.95,
) -> tuple[float | None, float | None]:
    finite = [float(value) for value in values if isfinite(float(value))]
    if not finite:
        return None, None
    if samples <= 0:
        raise ValueError("samples must be > 0")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    rng = Random(seed)
    means = [
        fmean(finite[rng.randrange(len(finite))] for _ in finite)
        for _ in range(samples)
    ]
    tail = (1.0 - confidence) / 2.0
    return percentile(means, tail), percentile(means, 1.0 - tail)


def _group_report(
    population: int,
    rows: list[Mapping[str, Any]],
    *,
    min_samples: int,
    bootstrap_samples: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    clearance = _numbers(rows, "clearance_time_seconds")
    density = _numbers(rows, "peak_local_density_persons_m2")
    execution_failures = sum(row.get("status") != "ok" for row in rows)
    acceptance_failures = sum(row.get("acceptance_status") == "fail" for row in rows)
    blockers: list[dict[str, Any]] = []
    if len(rows) < min_samples:
        blockers.append(
            {
                "code": "reliability.insufficient_samples",
                "population": population,
                "actual": len(rows),
                "required": min_samples,
            }
        )
    if execution_failures or acceptance_failures:
        blockers.append(
            {
                "code": "reliability.failed_runs",
                "population": population,
                "execution_failures": execution_failures,
                "acceptance_failures": acceptance_failures,
            }
        )
    clearance_ci = bootstrap_mean_interval(
        clearance,
        samples=bootstrap_samples,
        seed=bootstrap_seed,
    )
    density_ci = bootstrap_mean_interval(
        density,
        samples=bootstrap_samples,
        seed=bootstrap_seed + 1,
    )
    return {
        "population": population,
        "sample_count": len(rows),
        "execution_failures": execution_failures,
        "acceptance_failures": acceptance_failures,
        "failure_rate": round((execution_failures + acceptance_failures) / len(rows), 6)
        if rows
        else None,
        "clearance_seconds": _distribution(clearance, clearance_ci),
        "peak_density_persons_m2": _distribution(density, density_ci),
        "status": "pass" if not blockers else "fail" if execution_failures or acceptance_failures else "insufficient",
        "blockers": blockers,
    }


def _numbers(rows: Iterable[Mapping[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        parsed = float(value)
        if isfinite(parsed):
            values.append(parsed)
    return values


def _distribution(
    values: Sequence[float],
    mean_ci: tuple[float | None, float | None],
) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean": round(fmean(values), 6) if values else None,
        "mean_ci95_low": None if mean_ci[0] is None else round(mean_ci[0], 6),
        "mean_ci95_high": None if mean_ci[1] is None else round(mean_ci[1], 6),
        "p50": _round(percentile(values, 0.50)),
        "p95": _round(percentile(values, 0.95)),
        "p99": _round(percentile(values, 0.99)),
        "maximum": round(max(values), 6) if values else None,
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _overall_status(groups: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(group.get("status")) for group in groups}
    if "fail" in statuses:
        return "fail"
    if "insufficient" in statuses or not groups:
        return "insufficient"
    return "pass"
