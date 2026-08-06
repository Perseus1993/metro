from __future__ import annotations

from types import SimpleNamespace

from metro_station.adapters.simulation.station.alighting_demand import (
    build_alighting_schedule,
    planned_train_alightings,
)


def _scenario(**updates):
    values = {
        "scenario_mode": "operations",
        "exit_groups": 17,
        "initial_train_offset_seconds": 5,
        "tick_seconds": 1,
        "train_headway_seconds": 10,
        "train_dwell_seconds": 3,
        "horizon_steps": 30,
        "demand_steps": 25,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def test_every_alighting_group_is_bound_to_exactly_one_nominal_train() -> None:
    scenario = _scenario()

    manifests = planned_train_alightings(scenario)
    flattened = {
        step: count
        for manifest in manifests
        for step, count in manifest.release_schedule
    }

    assert [item.arrival_step for item in manifests] == [5, 15, 25]
    assert [item.scheduled_close_step for item in manifests] == [8, 18, 28]
    assert sum(item.planned_groups for item in manifests) == scenario.exit_groups
    assert flattened == build_alighting_schedule(scenario)


def test_zero_exit_demand_has_no_nominal_train_manifest() -> None:
    assert planned_train_alightings(_scenario(exit_groups=0)) == ()
