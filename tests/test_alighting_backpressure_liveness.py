from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.planning.goal_state import (
    FacilityInteractionState,
)
from metro_station.adapters.simulation.planning.plan import (
    AgentGoal,
    AgentIntent,
    AgentState,
    FacilityStage,
)
from metro_station.adapters.simulation.planning.goal_commands import (
    GoalCommand,
    GoalCommandKind,
)
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.runtime.passenger_goal_command_executor import (
    ProductionGoalCommandContext,
)
from metro_station.adapters.simulation.runtime.progress_monitor import (
    PassengerLivenessViolation,
)
from metro_station_testkit.alighting_backpressure_scenario import (
    alighting_backpressure_scenario,
)
from metro_station_testkit.instant_movement_backend import InstantMovementBackend


class DeferredPassiveLayoutBackend(InstantMovementBackend):
    def owns_passive_layout_motion(self) -> bool:
        return True


def test_alighting_stays_pending_without_downstream_approach_ownership() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(),
        seed=42,
        movement_backend=InstantMovementBackend(),
    )

    model._spawn_alighting_passengers_for_train(model.train, 4)

    assert model.pending_alighting_groups == 4
    assert not model.passengers
    assert model.spawned_persons_by_intent[AgentIntent.EXIT_STATION.value] == 0
    assert (
        model.audit.counts[
            "alighting_demand_deferred_without_downstream_admission"
        ]
        == 4
    )


def test_entry_stays_pending_without_downstream_ownership() -> None:
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

    assert not model.passengers
    assert model.pending_spawn_groups[AgentIntent.ENTER_AND_BOARD.value] == 1
    assert (
        model.audit.counts[
            "passenger_demand_deferred_without_downstream_admission"
        ]
        == 1
    )


def test_entry_with_only_holding_capacity_stays_upstream_pending() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(disable_exit_gates=False),
        seed=49,
        movement_backend=InstantMovementBackend(),
    )
    owners: list[PassengerAgent] = []
    with patch.object(model.goal_coordinator, "initialize"):
        for gate in model.gates:
            for _slot_index in model._facility_approach_slot_indices(gate):
                owner = PassengerAgent(
                    model,
                    group_size=1,
                    created_step=0,
                    intent=AgentIntent.ENTER_AND_BOARD,
                    initial_position=gate.portal_entry_position,
                    initial_level_id=gate.portal_entry_level_id,
                )
                model._reserve_facility_approach_slot(owner, gate)
                owners.append(owner)

    entrance = model.layout_graph.station_graph.nodes_matching(kind="entrance")[0]
    evidence = model._downstream_admission_evidence(
        AgentIntent.ENTER_AND_BOARD.value,
        release_levels={entrance.level_id},
    )
    holding_position = evidence["available_holding_position"]
    assert evidence["available_approach_slots"] == 0
    assert holding_position is not None
    assert not evidence["available"]

    model.pending_spawn_groups[AgentIntent.ENTER_AND_BOARD.value] = 1
    model.spawn_passengers()

    assert model.pending_spawn_groups[AgentIntent.ENTER_AND_BOARD.value] == 1
    assert not model.passengers


def test_alighting_with_only_platform_staging_gets_finite_ownership() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(disable_exit_gates=False),
        seed=50,
        movement_backend=InstantMovementBackend(),
    )
    with patch.object(model.goal_coordinator, "initialize"):
        for gate in model.exit_gates:
            for _slot_index in model._facility_approach_slot_indices(gate):
                owner = PassengerAgent(
                    model,
                    group_size=1,
                    created_step=0,
                    intent=AgentIntent.EXIT_STATION,
                    initial_position=gate.portal_entry_position,
                    initial_level_id=gate.portal_entry_level_id,
                )
                model._reserve_facility_approach_slot(owner, gate)

    doors = model.boarding_doors_for_train(model.train)
    evidence = model._alighting_downstream_admission_evidence(doors)
    assert evidence["available_approach_slots"] == 0
    assert evidence["available_platform_staging_slots"] > 0
    assert evidence["available"]

    door = doors[0]
    level_id = door.spec.exit_level_id or door.spec.entry_level_id
    passenger = model._spawn_passenger(
        AgentIntent.EXIT_STATION,
        initial_position=door.portal_exit_position,
        initial_level_id=level_id,
    )

    assert model.pending_alighting_groups == 0
    assert len(model.passengers) == 1
    assert len(model._platform_waiting_reservations) == 1
    assert passenger.current_goal.target is not None


def test_unowned_evaluate_candidate_body_fails_fast_with_context() -> None:
    scenario = replace(
        alighting_backpressure_scenario(disable_exit_gates=False),
        liveness_fail_fast_seconds=2.0,
        liveness_min_displacement_units=0.01,
    )
    model = MetroStationModel(
        scenario,
        seed=43,
        movement_backend=InstantMovementBackend(),
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    model._clear_all_facility_targeting_reservations(passenger)
    model._clear_all_decision_holding_reservations(passenger)
    passenger.assigned_facility_id = None
    passenger.plan.current_goal = AgentGoal(kind="idle", label="not_started")
    passenger.state = AgentState.WALKING_TO_EXIT_GATE.value
    passenger.target = tuple(passenger.pos)
    passenger.goal_runtime.state = replace(
        passenger.goal_runtime.state,
        current_node_id="use_exit_gate",
        interaction_state=FacilityInteractionState.EVALUATE_CANDIDATES.value,
        current_stage="exit_gate",
        commitment=None,
        queued_facility_id=None,
    )
    model.passengers.append(passenger)

    model.progress_monitor.observe(model, [passenger])
    model.step_index = 1
    model.progress_monitor.observe(model, [passenger])
    model.step_index = 2
    with pytest.raises(PassengerLivenessViolation) as exc_info:
        model.progress_monitor.observe(model, [passenger])

    message = str(exc_info.value)
    assert '"structurally_unowned": true' in message
    assert f'"passenger_id": {passenger.unique_id}' in message
    assert model.audit.counts["passenger_liveness_violation"] == 1


def test_owned_evaluate_candidate_stall_also_fails_fast() -> None:
    scenario = replace(
        alighting_backpressure_scenario(disable_exit_gates=False),
        liveness_fail_fast_seconds=2.0,
        liveness_min_displacement_units=0.01,
    )
    model = MetroStationModel(
        scenario,
        seed=45,
        movement_backend=InstantMovementBackend(),
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    passenger.decision_holding_target_by_region["exit_gate_decision"] = tuple(
        passenger.pos
    )
    passenger.goal_runtime.state = replace(
        passenger.goal_runtime.state,
        current_node_id="use_exit_gate",
        interaction_state=FacilityInteractionState.EVALUATE_CANDIDATES.value,
        current_stage="exit_gate",
        commitment=None,
        queued_facility_id=None,
    )

    for step in range(2):
        model.step_index = step
        model.progress_monitor.observe(model, [passenger])
    model.step_index = 2
    with pytest.raises(PassengerLivenessViolation) as exc_info:
        model.progress_monitor.observe(model, [passenger])

    assert '"structurally_unowned": false' in str(exc_info.value)
    assert model.audit.counts["passenger_liveness_violation"] == 1


def test_no_eligible_exit_facility_wait_claims_finite_platform_staging() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(),
        seed=47,
        movement_backend=InstantMovementBackend(),
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )

    model.goal_coordinator.executor.execute(
        ProductionGoalCommandContext(model=model, passenger=passenger),
        (
            GoalCommand(
                kind=GoalCommandKind.WAIT_FOR_EVENT.value,
                goal_node_id="use_exit_gate",
                stage=FacilityStage.EXIT_GATE.value,
                reason="no_eligible_facility",
            ),
        ),
    )

    assert passenger.assigned_facility_id is None
    reservation = model._platform_waiting_reservations[int(passenger.unique_id)]
    assert passenger.current_goal.kind == "waiting"
    assert passenger.current_goal.label == "platform waiting slot"
    assert passenger.current_goal.target == reservation.point


def test_gate_queue_head_block_reason_transitions_are_observable() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(disable_exit_gates=False),
        seed=44,
        movement_backend=InstantMovementBackend(),
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    gate = model.exit_gates[0]
    model._clear_all_facility_targeting_reservations(passenger)
    model._clear_all_decision_holding_reservations(passenger)
    passenger.pos = (gate.portal_entry_position[0] + 20.0, gate.portal_entry_position[1])
    passenger.target = tuple(passenger.pos)
    assert gate.join_queue(
        passenger,
        authority="goal_graph",
        settle_after_walking=True,
    )
    gate.service_credit = 1.0

    gate._serve_queue()
    assert gate.service_blocked_reason == "queue_head_settling"

    model.step_index = 2
    gate._serve_queue()
    assert gate.service_blocked_reason == "queue_head_not_service_ready"
    assert gate.service_blocked_reason_counts["queue_head_settling"] == 1
    assert gate.service_blocked_reason_counts["queue_head_not_service_ready"] == 1
    assert model.audit.counts["facility_service_queue_head_blocked"] == 2


def test_gate_retargets_next_head_during_the_active_service_interval() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(disable_exit_gates=False),
        seed=51,
        movement_backend=DeferredPassiveLayoutBackend(),
    )
    gate = model.exit_gates[0]
    passengers = [
        PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EXIT_STATION,
        )
        for _ in range(2)
    ]
    model.passengers.extend(passengers)
    for index, passenger in enumerate(passengers):
        passenger.pos = gate.queue.layout.slot(index)
        assert gate.join_queue(passenger, authority="goal_graph")
    gate.service_credit = 2.0

    gate.step()

    assert [active.passenger for active in gate.active_passes] == [passengers[0]]
    assert list(gate.queue) == [passengers[1]]
    assert passengers[1].target == gate.queue.layout.slot(0)
    assert passengers[1].passive_layout_motion_target == gate.queue.layout.slot(0)
    assert gate.service_blocked_reason_counts["queue_head_not_service_ready"] == 0

    gate.active_passes[0].remaining_seconds = 10.0
    gate.step()

    assert list(gate.queue) == [passengers[1]]
    assert gate.service_blocked_reason_counts["queue_head_not_service_ready"] == 0


def test_gate_queue_layout_compacts_a_remote_head_to_its_fifo_slot() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(disable_exit_gates=False),
        seed=52,
        movement_backend=DeferredPassiveLayoutBackend(),
    )
    gate = model.exit_gates[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    model.passengers.append(passenger)
    passenger.pos = gate.queue.layout.slot(4)
    assert gate.join_queue(
        passenger,
        authority="goal_graph",
        preferred_slot_index=4,
    )

    gate.step()

    assert list(gate.queue) == [passenger]
    assert passenger.target == gate.queue.layout.slot(0)


def test_gate_compacts_approaching_successor_during_active_service() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(disable_exit_gates=False),
        seed=53,
        movement_backend=DeferredPassiveLayoutBackend(),
    )
    gate = model.exit_gates[0]
    serving = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    approaching = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    model.passengers.extend((serving, approaching))
    serving.pos = gate.queue.layout.slot(0)
    assert gate.join_queue(serving, authority="goal_graph")
    reserved_index = model._reserve_facility_approach_slot(approaching, gate)
    assert reserved_index == 1
    reserved_target = model._facility_approach_slot_position(gate, reserved_index)
    approaching.set_target(
        reserved_target,
        goal_kind="walk",
        goal_label="gate approach",
        facility_id=gate.facility_id,
        stage=gate.spec.stage,
    )
    gate.service_credit = 1.0

    gate.step()

    assert [active.passenger for active in gate.active_passes] == [serving]
    assert model._facility_targeting_slot_indices[gate.facility_id][
        int(approaching.unique_id)
    ] == 0
    assert approaching.facility_approach_slots_by_stage[gate.spec.stage] == 0
    assert gate.queue.approach_slot_reservation(int(approaching.unique_id)) == 0
    assert (approaching.target, *approaching.route)[-1] == (
        model._facility_approach_slot_position(gate, 0)
    )


def test_flat_entry_gate_reports_downstream_boarding_backpressure() -> None:
    model = MetroStationModel(
        alighting_backpressure_scenario(disable_exit_gates=False),
        seed=48,
        movement_backend=InstantMovementBackend(),
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    gate = model.gates[0]
    boarding = model._facilities_for_stage(FacilityStage.BOARDING_DOOR.value)[0]
    model._clear_all_facility_targeting_reservations(passenger)
    model._clear_all_decision_holding_reservations(passenger)
    passenger.pos = gate._service_entry_position()

    with (
        patch.object(gate, "_direct_boarding_candidates", return_value=(boarding,)),
        patch.object(
            model,
            "_available_platform_waiting_slot_count",
            return_value=0,
        ),
    ):
        assert not gate._can_start_service(passenger, None)
        assert (
            gate._service_start_block_reason(
                passenger,
                None,
                release_index=0,
            )
            == "downstream_boarding_capacity_unavailable"
        )
