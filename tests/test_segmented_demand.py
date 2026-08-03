from __future__ import annotations

from dataclasses import replace
from random import Random

import pytest

from metro_station.adapters.simulation.movement.backend import MovementBackend, MovementResult
from metro_station.adapters.simulation.runtime.demand_scheduler import DemandScheduler
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.demand import DemandSegment
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_testkit.topology_trial_catalog import topology_core_cases
from metro_station_testkit.topology_trial_designs import generate_topology_trial_design


class InstantMovementBackend(MovementBackend):
    def move(self, passenger) -> MovementResult:
        return MovementResult(int(passenger.unique_id), passenger.target, reached=True)


def _design():
    return generate_topology_trial_design(topology_core_cases()[0])


def _scenario(**changes) -> StationSandboxScenario:
    scenario = StationSandboxScenario(
        station_name="segmented-demand-test",
        hour=8,
        minutes=15,
        tick_seconds=5,
        group_size=10,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="unit_test",
        sample_hours=1,
        station_design=_design(),
        audit_enabled=False,
        audit_print_events=False,
    )
    return replace(scenario, **changes)


def test_segmented_demand_preserves_segment_counts_and_windows() -> None:
    scenario = _scenario(
        demand_segments=(
            DemandSegment(0, 300, entry_count_hour=720),
            DemandSegment(300, 420, transfer_count_hour=3600),
            DemandSegment(420, 900, entry_count_hour=450),
        )
    )
    scheduler = DemandScheduler.from_scenario(scenario, Random(42))

    assert scenario.entry_groups == 12
    assert scenario.transfer_groups == 12
    assert scenario.demand_steps == 180
    entry_steps = [
        step
        for step, due in scheduler.spawn_schedule.items()
        for _ in range(due["enter_and_board"])
    ]
    transfer_steps = [
        step
        for step, due in scheduler.spawn_schedule.items()
        for _ in range(due["transfer"])
    ]
    assert len(entry_steps) == 12
    assert len(transfer_steps) == 12
    assert all(step < 60 or 84 <= step < 180 for step in entry_steps)
    assert all(60 <= step < 84 for step in transfer_steps)


@pytest.mark.parametrize(
    ("segments", "message"),
    [
        ((DemandSegment(20, 40), DemandSegment(30, 50)), "ordered and non-overlapping"),
        ((DemandSegment(0, 901),), "exceeds scenario horizon"),
    ],
)
def test_segmented_demand_rejects_invalid_windows(segments, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _scenario(demand_segments=segments)


@pytest.mark.parametrize(
    "weights",
    [
        (("entrance_a", 1.0), ("entrance_a", 2.0)),
        (("entrance_a", -0.1),),
        (("entrance_a", 0.0),),
    ],
)
def test_entrance_weights_reject_ambiguous_or_non_positive_contracts(weights) -> None:
    with pytest.raises(ValueError):
        _scenario(entry_entrance_weights=weights)


def test_weighted_entrance_selection_is_recorded_by_source_element() -> None:
    scenario = _scenario(
        minutes=1,
        entry_count_hour=600,
        entry_entrance_weights=(("entrance_a", 1.0), ("entrance_b", 0.0)),
    )
    model = MetroStationModel(scenario, seed=7, movement_backend=InstantMovementBackend())

    for _ in range(25):
        passenger = model._spawn_passenger("enter_and_board")
        assert passenger.spawn_source_element_id == "entrance_a"

    assert model.spawned_persons_by_entrance == {"entrance_a": 250}


def test_unknown_weighted_entrance_is_rejected_after_design_compilation() -> None:
    scenario = _scenario(entry_entrance_weights=(("missing_entrance", 1.0),))

    with pytest.raises(ValueError, match="unknown entrances: missing_entrance"):
        MetroStationModel(scenario, seed=7, movement_backend=InstantMovementBackend())
