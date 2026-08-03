from __future__ import annotations

from dataclasses import replace
from random import Random

import pytest

from metro_station.adapters.simulation.agents.transit import TrainAgent
from metro_station.adapters.simulation.design import create_design
from metro_station.adapters.simulation.runtime.demand_scheduler import DemandScheduler
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.demand import DemandSegment
from metro_station.adapters.simulation.station.evacuation import EvacuationScenarioConfig
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.domain.time_boundaries import first_step_not_before


def _scenario(**changes) -> StationSandboxScenario:
    base = StationSandboxScenario(
        station_name="time-boundary-test",
        hour=8,
        minutes=1,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="unit",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        audit_enabled=False,
        audit_print_events=False,
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    ("seconds", "expected_step"),
    ((0.0, 0), (2.0, 1), (2.5, 1), (2.500001, 1), (7.5, 2), (10.0, 2)),
)
def test_fixed_step_events_use_the_first_boundary_not_before_physical_time(
    seconds: float,
    expected_step: int,
) -> None:
    step = first_step_not_before(seconds, 5.0)

    assert step == expected_step
    assert step * 5.0 >= seconds
    assert step * 5.0 < seconds + 5.0 or seconds == 0.0


def test_alarm_and_segmented_demand_never_fire_before_configured_time() -> None:
    evacuation = EvacuationScenarioConfig(
        initial_platform_persons=1,
        alarm_delay_seconds=2.0,
    )
    assert evacuation.alarm_step(5.0) == 1

    scenario = _scenario(
        demand_segments=(DemandSegment(2, 7, entry_count_hour=3600),),
    )
    scheduler = DemandScheduler.from_scenario(scenario, Random(42))

    assert scheduler.spawn_schedule
    assert set(scheduler.spawn_schedule) == {1}
    assert scenario.demand_steps == 2


def test_train_boundaries_may_be_late_by_less_than_one_tick_but_never_early() -> None:
    scenario = _scenario(
        initial_train_offset_seconds=7,
        train_dwell_seconds=3,
        train_headway_seconds=7,
    )
    model = MetroStationModel(scenario, seed=42)
    train = TrainAgent(model)
    arrivals: list[float] = []
    departures: list[float] = []
    previous = train.state

    for step in range(6):
        model.step_index = step
        train.step()
        if train.state == "boarding" and previous == "away":
            arrivals.append(model.current_time_seconds)
        if train.state == "away" and previous == "boarding":
            departures.append(model.current_time_seconds)
        previous = train.state

    assert arrivals[:2] == [10.0, 20.0]
    assert departures[:2] == [15.0, 25.0]
    assert arrivals[0] >= scenario.initial_train_offset_seconds
    assert departures[0] - arrivals[0] >= scenario.train_dwell_seconds
    assert arrivals[1] - arrivals[0] >= scenario.train_headway_seconds


def test_non_integral_fixed_step_horizon_is_rejected_instead_of_truncated() -> None:
    with pytest.raises(ValueError, match="integer number of fixed process ticks"):
        _scenario(tick_seconds=7)
    with pytest.raises(ValueError, match="tick_seconds must be an integer"):
        _scenario(tick_seconds=2.3)
