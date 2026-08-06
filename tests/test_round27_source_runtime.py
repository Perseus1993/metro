from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.external_demand_reservoir import DemandSourceKind
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station_testkit.alighting_backpressure_scenario import (
    alighting_backpressure_scenario,
)
from metro_station_testkit.instant_movement_backend import InstantMovementBackend


def _run_steps(model: MetroStationModel, limit: int) -> None:
    for _ in range(limit):
        if not model.running and model.step_index > 0:
            return
        model.step()


def test_alighting_manifest_completes_before_successful_departure() -> None:
    scenario = replace(
        alighting_backpressure_scenario(disable_exit_gates=False),
        exit_count_hour=60,
    )
    model = MetroStationModel(
        scenario,
        seed=42,
        movement_backend=InstantMovementBackend(),
    )

    _run_steps(model, 50)

    [row] = model.train_exchange_result_rows()
    assert model.run_outcome_code is None
    assert row["departure_status"] == "departed"
    assert row["planned_alight_persons"] == row["released_alight_persons"] == 2
    assert row["not_alighted_persons"] == 0
    assert row["alighting_release_complete_step"] <= row["actual_departure_step"]
    assert model.external_demand_reservoir.pending_persons() == 0


def test_blocked_alighting_fails_capacity_without_departure_or_cross_train_pool() -> None:
    scenario = replace(alighting_backpressure_scenario(), exit_count_hour=60)
    model = MetroStationModel(
        scenario,
        seed=42,
        movement_backend=InstantMovementBackend(),
    )

    _run_steps(model, 50)

    [row] = model.train_exchange_result_rows()
    assert model.run_outcome_code == "train_alighting_capacity_insufficient"
    assert row["departure_status"] == "failed"
    assert row["actual_departure_step"] is None
    assert row["released_alight_persons"] == 0
    assert row["not_alighted_persons"] == 2
    assert model.external_demand_reservoir.pending_persons() == 0
    assert model.train.departed_trains == 0


def test_blocked_entry_is_owned_by_external_reservoir_not_station() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(
            disable_exit_gates=False,
            disable_entry_gates=True,
        ),
        seed=46,
        movement_backend=InstantMovementBackend(),
    )
    model.pending_spawn_groups[AgentIntent.ENTER_AND_BOARD.value] = 1

    model.spawn_passengers()

    tickets = model.external_demand_reservoir.pending_tickets(DemandSourceKind.ENTRY)
    assert len(tickets) == 1
    assert tickets[0].intent == AgentIntent.ENTER_AND_BOARD.value
    assert not model.passengers
    assert model.spawned_persons == 0


def test_snapshot_keeps_entry_and_train_wait_semantics_separate() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(
            disable_exit_gates=False,
            disable_entry_gates=True,
        ),
        seed=46,
        movement_backend=InstantMovementBackend(),
    )
    model.pending_spawn_groups[AgentIntent.ENTER_AND_BOARD.value] = 1
    model.spawn_passengers()

    boundaries = model.snapshot()["source_boundaries"]

    assert boundaries["pooling_prohibited"] is True
    assert boundaries["pooled_source_wait_duration"] is None
    assert boundaries["entry_sources"][0]["source_waiting_persons"] == 1
    assert "wait_steps" not in boundaries["train_alighting_manifests"]
