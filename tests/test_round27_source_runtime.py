from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.external_demand_reservoir import (
    DemandSourceKind,
    DemandTicket,
    DemandTicketState,
)
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.runtime.source_boundary_metrics import (
    aggregate_source_counts,
)
from metro_station_testkit.alighting_backpressure_scenario import (
    alighting_backpressure_scenario,
)
from metro_station_testkit.instant_movement_backend import InstantMovementBackend


class RejectCertifiedPlacementBackend(InstantMovementBackend):
    def resolve_certified_placement(self, passenger, position, *, level_id=None):
        del passenger, position, level_id
        raise RuntimeError("forced certified placement failure")


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
    assert model.snapshot()["source_boundaries"]["flows"]["exit"] == {
        "scheduled_persons": 2,
        "admitted_persons": 2,
        "source_waiting_persons": 0,
        "active_inside_persons": 0,
        "completed_persons": 2,
        "not_alighted_persons": 0,
        "right_censored_persons": 0,
        "dropped_persons": 0,
        "conserved": True,
    }


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
    assert model.snapshot()["source_boundaries"]["flows"]["exit"]["conserved"] is True


def test_train_manifest_is_live_authority_for_boarding_reserve_and_commit() -> None:
    scenario = replace(
        alighting_backpressure_scenario(disable_exit_gates=False),
        exit_count_hour=60,
        train_capacity_persons=3,
    )
    model = MetroStationModel(
        scenario,
        seed=42,
        movement_backend=InstantMovementBackend(),
    )
    train = model.train
    train.step()
    assert model.sync_train_exchange_manifests() is True
    manifest = model.train_exchange_manifests[model._train_run_ref(train)]

    assert train.current_load_persons == manifest.current_onboard_persons == 2
    assert train.capacity_remaining == manifest.capacity_remaining == 1
    manifest.release_alighting_group(1, at_step=0)
    assert train.current_load_persons == manifest.current_onboard_persons == 1
    assert train.capacity_remaining == manifest.capacity_remaining == 2

    train.reserve_boarding_capacity(2)
    assert train.reserved_boarding_persons == manifest.reserved_boarding_persons == 2
    assert train.capacity_remaining == manifest.capacity_remaining == 0
    train.commit_boarding_capacity(2)
    assert train.reserved_boarding_persons == manifest.reserved_boarding_persons == 0
    assert train.current_load_persons == manifest.current_onboard_persons == 3
    assert manifest.boarded_persons == 2


@pytest.mark.parametrize("failure_point", ["manifest_release", "reservoir_commit"])
def test_alighting_publication_compensates_all_ledgers_on_commit_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    scenario = replace(
        alighting_backpressure_scenario(disable_exit_gates=False),
        exit_count_hour=60,
    )
    model = MetroStationModel(
        scenario,
        seed=42,
        movement_backend=InstantMovementBackend(),
    )
    train = model.train
    train.step()
    assert model.sync_train_exchange_manifests() is True
    manifest = model.train_exchange_manifests[model._train_run_ref(train)]

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(f"forced {failure_point}")

    if failure_point == "manifest_release":
        monkeypatch.setattr(manifest, "release_alighting_group", fail)
    else:
        monkeypatch.setattr(model.external_demand_reservoir, "commit", fail)

    with pytest.raises(RuntimeError, match=f"forced {failure_point}"):
        model.spawn_alighting_passengers()

    assert manifest.released_alight_persons == 0
    assert manifest.not_alighted_persons == manifest.planned_alight_persons
    assert not model.passengers
    assert model.spawned_persons == 0
    assert model.external_demand_reservoir.pending_persons(
        DemandSourceKind.TRAIN_ALIGHTING
    ) == 1


def test_planned_alighting_above_train_capacity_is_structured_run_outcome() -> None:
    scenario = replace(
        alighting_backpressure_scenario(disable_exit_gates=False),
        exit_count_hour=60,
        train_capacity_persons=1,
    )
    model = MetroStationModel(
        scenario,
        seed=42,
        movement_backend=InstantMovementBackend(),
    )

    _run_steps(model, 2)

    assert model.run_outcome_code == "train_alighting_capacity_insufficient"
    assert model.train.departed_trains == 0
    assert not model.train_exchange_manifests
    [failure] = model.train_exchange_failure_rows
    assert failure["failure_code"] == "train_alighting_capacity_insufficient"
    assert failure["capacity_persons"] == 1
    assert failure["planned_alight_persons"] == 2
    assert failure["not_alighted_persons"] == 2
    assert failure["actual_departure_step"] is None
    boundaries = model.snapshot()["source_boundaries"]
    assert boundaries["train_alighting_unbound_failures"] == [failure]
    assert boundaries["flows"]["exit"]["not_alighted_persons"] == 2
    assert boundaries["flows"]["exit"]["conserved"] is True


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


def _model_with_owned_entry_ticket() -> tuple[MetroStationModel, DemandTicket]:
    model = MetroStationModel(
        alighting_backpressure_scenario(
            disable_exit_gates=False,
            disable_entry_gates=True,
        ),
        seed=46,
        movement_backend=InstantMovementBackend(),
    )
    ticket = model.external_demand_reservoir.enqueue(
        scheduled_step=int(model.step_index),
        intent=AgentIntent.ENTER_AND_BOARD.value,
        group_size=1,
        source_kind=DemandSourceKind.ENTRY,
        source_ref="entrance:horizon",
    )
    return model, ticket


def _assert_entry_ticket_right_censored(
    model: MetroStationModel,
    ticket: DemandTicket,
) -> None:
    assert model.external_demand_reservoir.state_of(ticket) == (DemandTicketState.RIGHT_CENSORED)
    assert model.external_demand_reservoir.pending_persons() == 0
    boundaries = model.snapshot()["source_boundaries"]
    [row] = boundaries["entry_sources"]
    assert row["scheduled_persons"] == 1
    assert row["admitted_persons"] == 0
    assert row["source_waiting_persons"] == 1
    assert row["right_censored_persons"] == 1
    assert row["right_censored_wait_steps"]["n"] == 1
    assert row["conserved"] is True
    assert boundaries["flows"]["entry"]["right_censored_persons"] == 1
    assert boundaries["flows"]["entry"]["conserved"] is True
    assert aggregate_source_counts(boundaries)["right_censored_persons"] == 1


def test_horizon_exit_closes_reservoir_before_final_snapshot() -> None:
    model, ticket = _model_with_owned_entry_ticket()
    model.step_index = model.scenario.horizon_steps - 1

    model.run()

    _assert_entry_ticket_right_censored(model, ticket)
    assert model.frames[-1]["source_boundaries"]["entry_sources"][0]["right_censored_persons"] == 1


def test_active_stop_closes_reservoir() -> None:
    model, ticket = _model_with_owned_entry_ticket()

    def stop_run(_step: int, _total_steps: int) -> None:
        model.running = False

    model.run(progress_callback=stop_run)

    _assert_entry_ticket_right_censored(model, ticket)


def test_exception_exit_closes_reservoir() -> None:
    model, ticket = _model_with_owned_entry_ticket()

    def fail_step(_model: MetroStationModel) -> None:
        raise RuntimeError("forced step failure")

    model.step_orchestrator.step = fail_step

    with pytest.raises(RuntimeError, match="forced step failure"):
        model.run()

    _assert_entry_ticket_right_censored(model, ticket)


def test_pending_alighting_groups_is_a_read_only_reservoir_view() -> None:
    model, _ticket = _model_with_owned_entry_ticket()
    model.external_demand_reservoir.enqueue(
        scheduled_step=0,
        intent=AgentIntent.EXIT_STATION.value,
        group_size=1,
        source_kind=DemandSourceKind.TRAIN_ALIGHTING,
        source_ref="arrival:compatibility-view",
        departure_deadline_step=10,
    )

    assert model.pending_alighting_groups == 1
    with pytest.raises(AttributeError):
        model.pending_alighting_groups = 1


def test_right_censored_train_ticket_remains_in_waiting_partition() -> None:
    model, _entry_ticket = _model_with_owned_entry_ticket()
    ticket = model.external_demand_reservoir.enqueue(
        scheduled_step=0,
        intent=AgentIntent.EXIT_STATION.value,
        group_size=1,
        source_kind=DemandSourceKind.TRAIN_ALIGHTING,
        source_ref="arrival:right-censored",
        departure_deadline_step=10,
    )

    def stop_run(_step: int, _total_steps: int) -> None:
        model.running = False

    model.run(progress_callback=stop_run)

    assert model.external_demand_reservoir.state_of(ticket) == (DemandTicketState.RIGHT_CENSORED)
    exit_flow = model.snapshot()["source_boundaries"]["flows"]["exit"]
    assert exit_flow["scheduled_persons"] == 1
    assert exit_flow["source_waiting_persons"] == 1
    assert exit_flow["right_censored_persons"] == 1
    assert exit_flow["conserved"] is True


def test_entry_placement_failure_rolls_back_mesa_agent_and_approach_owner() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(disable_exit_gates=False),
        seed=46,
        movement_backend=RejectCertifiedPlacementBackend(),
    )
    model.demand_scheduler.due_by_intent = lambda step: Counter()
    model.pending_spawn_groups[AgentIntent.ENTER_AND_BOARD.value] = 1
    before_agents = tuple(model.agents)
    before_agent_id_counter = model.agent_id_counter

    model.spawn_passengers()

    [ticket] = model.external_demand_reservoir.pending_tickets(DemandSourceKind.ENTRY)
    assert model.external_demand_reservoir.state_of(ticket) == DemandTicketState.PENDING
    assert tuple(model.agents) == before_agents
    assert model.agent_id_counter == before_agent_id_counter
    assert not model.passengers
    assert not model.passenger_goal_runtimes
    assert model.spawned_persons == 0
    assert model._facility_approach_reservation_registry == {}
    assert all(
        not facility.queue.approach_reservation_state().slots for facility in model.facilities
    )
    assert before_agent_id_counter not in model.goal_coordinator._command_sequences
    assert model.spatial_capacity_event_counts["spawn.dynamic_blocked"] == 1

    model.movement_backend = InstantMovementBackend()
    model.spawn_passengers()

    [passenger] = model.passengers
    assert passenger.unique_id == before_agent_id_counter
    assert model.external_demand_reservoir.pending_groups(DemandSourceKind.ENTRY) == 0
    assert model.external_demand_reservoir.state_of(ticket) == DemandTicketState.PUBLISHED


def test_entry_constructor_failure_rolls_back_goal_initialization_reservations(
    monkeypatch,
) -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(disable_exit_gates=False),
        seed=46,
        movement_backend=InstantMovementBackend(),
    )
    model.demand_scheduler.due_by_intent = lambda step: Counter()
    model.pending_spawn_groups[AgentIntent.ENTER_AND_BOARD.value] = 1
    before_agents = tuple(model.agents)
    before_agent_id_counter = model.agent_id_counter
    initialize = model.goal_coordinator.initialize

    def fail_after_goal_initialization(passenger) -> None:
        initialize(passenger)
        raise RuntimeError("constructor goal initialization failed")

    monkeypatch.setattr(model.goal_coordinator, "initialize", fail_after_goal_initialization)

    with pytest.raises(RuntimeError, match="constructor goal initialization failed"):
        model.spawn_passengers()

    [ticket] = model.external_demand_reservoir.pending_tickets(DemandSourceKind.ENTRY)
    assert model.external_demand_reservoir.state_of(ticket) == DemandTicketState.PENDING
    assert tuple(model.agents) == before_agents
    assert model.agent_id_counter == before_agent_id_counter
    assert not model.passengers
    assert not model.passenger_goal_runtimes
    assert model.spawned_persons == 0
    assert model._facility_approach_reservation_registry == {}
    assert all(
        not facility.queue.approach_reservation_state().slots for facility in model.facilities
    )
    assert before_agent_id_counter not in model.goal_coordinator._command_sequences
