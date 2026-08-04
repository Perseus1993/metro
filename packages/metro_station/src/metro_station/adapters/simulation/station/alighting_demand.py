from __future__ import annotations

from collections import defaultdict
from typing import Any

from metro_station.domain.time_boundaries import (
    first_step_not_before,
    positive_steps_to_cover,
)

from .evacuation import EVACUATION_MODE


def build_alighting_schedule(scenario: Any) -> dict[int, int]:
    """Return the deterministic train-dwell release schedule for exit demand."""

    if scenario.scenario_mode == EVACUATION_MODE:
        return {}
    release_steps = _train_dwell_release_steps(scenario)
    if not release_steps:
        return {}

    schedule: dict[int, int] = defaultdict(int)
    for index in range(int(scenario.exit_groups)):
        step = release_steps[index * len(release_steps) // int(scenario.exit_groups)]
        schedule[step] += 1
    return dict(schedule)


def peak_alighting_batch(scenario: Any) -> int:
    """Largest number of alighting bodies released in one simulation tick."""

    return max(build_alighting_schedule(scenario).values(), default=0)


def _train_dwell_release_steps(scenario: Any) -> list[int]:
    if int(scenario.exit_groups) <= 0:
        return []

    arrivals = _train_arrival_steps_for_exit_demand(scenario)
    dwell_steps = positive_steps_to_cover(
        scenario.train_dwell_seconds,
        scenario.tick_seconds,
    )
    release_steps: list[int] = []
    for arrival_step in arrivals:
        for offset in range(dwell_steps):
            step = arrival_step + offset
            if step >= scenario.horizon_steps:
                break
            release_steps.append(step)
    return release_steps


def _train_arrival_steps_for_exit_demand(scenario: Any) -> list[int]:
    first_arrival_step = first_step_not_before(
        scenario.initial_train_offset_seconds,
        scenario.tick_seconds,
    )
    if first_arrival_step >= scenario.horizon_steps:
        return []

    headway_steps = positive_steps_to_cover(
        scenario.train_headway_seconds,
        scenario.tick_seconds,
    )
    arrivals: list[int] = []
    step = first_arrival_step
    while step < scenario.horizon_steps:
        if step <= scenario.demand_steps:
            arrivals.append(step)
        step += headway_steps
    return arrivals or [first_arrival_step]


__all__ = ["build_alighting_schedule", "peak_alighting_batch"]
