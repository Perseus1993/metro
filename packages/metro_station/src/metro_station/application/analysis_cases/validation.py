"""Input validation shared by analysis-case contracts."""

from __future__ import annotations

from typing import Any, Mapping


def validate_seeds(seeds: tuple[int, ...]) -> None:
    if not seeds:
        raise ValueError("analysis case requires at least one seed")
    if any(seed < 0 for seed in seeds):
        raise ValueError("seeds must be >= 0")
    if len(set(seeds)) != len(seeds):
        raise ValueError("seeds must not contain duplicates")


def validate_simulation(simulation: Mapping[str, Any]) -> None:
    demand = int(simulation.get("demand_minutes", 0) or 0)
    horizon = int(simulation.get("horizon_minutes", 0) or 0)
    if demand < 1 or horizon < 1 or demand >= horizon:
        raise ValueError("simulation requires 1 <= demand_minutes < horizon_minutes")
    tick_seconds = int(simulation.get("tick_seconds", 0) or 0)
    if tick_seconds < 1:
        raise ValueError("tick_seconds must be >= 1")
