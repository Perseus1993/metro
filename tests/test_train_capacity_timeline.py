from __future__ import annotations

from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.train_disruptions import TrainCapacityEvent
from metro_station_testkit.demand_fault_catalog import demand_fault_cases
from metro_station_testkit.demand_fault_scenarios import demand_fault_scenario
from metro_station_testkit.instant_movement_backend import InstantMovementBackend


def test_train_capacity_fault_applies_and_restores_on_tick_boundaries() -> None:
    case = next(
        item
        for item in demand_fault_cases()
        if item.factors["topology"] == "TB1"
        and item.factors["demand"] == "D1-SKEW"
        and item.factors["fault"] == "F5A-TRAIN-FULL"
        and item.seed == 41
    )
    scenario = demand_fault_scenario(case)
    model = MetroStationModel(scenario, seed=case.seed, movement_backend=InstantMovementBackend())
    platform_id = model.platform.platform_id

    assert scenario.train_capacity_events == (
        TrainCapacityEvent(300, platform_id, 1),
        TrainCapacityEvent(540, platform_id, 1200),
    )
    for _ in range(61):
        model.step()
    assert model.train_capacity_for_platform(platform_id) == 1
    for _ in range(48):
        model.step()
    assert model.train_capacity_for_platform(platform_id) == 1200
    assert [
        event.applied_seconds for event in model.train_disruption_controller.applied_capacity_events
    ] == [300.0, 540.0]
