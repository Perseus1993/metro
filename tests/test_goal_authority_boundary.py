from __future__ import annotations

import unittest
from dataclasses import replace

from sandbox.metro_station_sandbox.design import create_design
from sandbox.metro_station_sandbox.movement.backend import MovementBackend, MovementResult
from sandbox.metro_station_sandbox.planning.goal_commands import GoalCommandKind
from sandbox.metro_station_sandbox.planning.goal_events import GoalEvent, GoalEventKind
from sandbox.metro_station_sandbox.planning.plan import AgentIntent
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel
from sandbox.metro_station_sandbox.station.evacuation import (
    EVACUATION_MODE,
    EvacuationScenarioConfig,
)
from sandbox.metro_station_sandbox.station.scenario import StationSandboxScenario


class NoMovementBackend(MovementBackend):
    def move(self, passenger) -> MovementResult:
        return MovementResult(passenger.unique_id, passenger.pos, reached=False)


class InstantMovementBackend(MovementBackend):
    def move(self, passenger) -> MovementResult:
        return MovementResult(passenger.unique_id, passenger.target, reached=True)


def scenario(**changes) -> StationSandboxScenario:
    base = StationSandboxScenario(
        station_name="goal_authority",
        hour=8,
        minutes=5,
        demand_minutes=1,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="unit",
        sample_hours=1,
        station_design=create_design("two_level_island_platform"),
        goal_graph_mode="active",
        initial_train_offset_seconds=5,
        audit_enabled=False,
        audit_print_events=False,
    )
    return replace(base, **changes)


class GoalAuthorityBoundaryTests(unittest.TestCase):
    def test_active_choice_requires_physical_decision_region_fact(self) -> None:
        model = MetroStationModel(scenario(), movement_backend=NoMovementBackend())
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)

        self.assertIsNone(passenger.goal_runtime.state.commitment)
        self.assertFalse(hasattr(model, "request_facility_choice"))

        passenger.pos = passenger.target
        passenger.route = []
        passenger.advance_after_movement(True)

        self.assertIsNotNone(passenger.goal_runtime.state.commitment)
        self.assertFalse(hasattr(passenger.plan, "action_index"))
        self.assertFalse(hasattr(passenger.plan, "chosen_facilities"))
        self.assertFalse(hasattr(passenger, "assigned_gate_id"))

    def test_active_facility_rejects_uncommitted_queue_entry(self) -> None:
        model = MetroStationModel(scenario(), movement_backend=NoMovementBackend())
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)

        self.assertFalse(model.gates[0].join_queue(passenger))
        self.assertNotIn(passenger, model.gates[0].queue)

    def test_stale_queue_reached_fact_requires_current_spatial_proof(self) -> None:
        model = MetroStationModel(scenario(), movement_backend=NoMovementBackend())
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        passenger.pos = passenger.target
        passenger.route = []
        passenger.advance_after_movement(True)
        facility = model.facilities_by_id[passenger.current_goal.facility_id]
        self.assertEqual("queue_approach", passenger.current_goal.kind)

        passenger.pos = (1.0, 1.0)
        model.goal_coordinator.movement_reached(passenger)

        self.assertEqual("queue_approach", passenger.current_goal.kind)
        self.assertNotIn(passenger, facility.queue)

    def test_active_terminal_requires_goal_command_authorization(self) -> None:
        model = MetroStationModel(scenario(), movement_backend=NoMovementBackend())
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)

        model.complete_departure(passenger, boarded=True)

        self.assertIn(passenger, model.passengers)
        self.assertFalse(model.passenger_terminal_events)

    def test_active_run_has_physical_graph_parity(self) -> None:
        model = MetroStationModel(
            scenario(entry_count_hour=120),
            movement_backend=InstantMovementBackend(),
        )
        model.run()

        report = model.goal_parity.report(model)
        self.assertTrue(all(report["checks"].values()))
        self.assertFalse(report["commitment_mismatches"])

    def test_transfer_population_has_explicit_target(self) -> None:
        model = MetroStationModel(scenario(), movement_backend=NoMovementBackend())
        passenger = model._spawn_passenger(AgentIntent.TRANSFER)

        self.assertIsNotNone(passenger.target_line_id)
        self.assertIsNotNone(passenger.target_direction)

    def test_evacuation_alarm_switches_existing_passenger_graph(self) -> None:
        evacuation = scenario(
            scenario_mode=EVACUATION_MODE,
            evacuation=EvacuationScenarioConfig(
                initial_platform_persons=0,
                alarm_delay_seconds=5,
            ),
            tick_seconds=1,
        )
        model = MetroStationModel(evacuation, movement_backend=NoMovementBackend())
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)

        for _ in range(6):
            model.step()

        self.assertEqual(AgentIntent.EVACUATE_STATION.value, passenger.intent)
        self.assertEqual("station_evacuation", passenger.goal_runtime.graph.graph_id)
        self.assertFalse(
            any(node.facility_stage for node in passenger.goal_runtime.graph.nodes),
            "an alarm must not route a passenger who has not entered the paid area "
            "through station facilities",
        )

    def test_alarm_waits_for_active_gate_then_reroots_from_physical_release(self) -> None:
        evacuation = scenario(
            scenario_mode=EVACUATION_MODE,
            evacuation=EvacuationScenarioConfig(
                initial_platform_persons=0,
                alarm_delay_seconds=0,
            ),
            tick_seconds=1,
        )
        model = MetroStationModel(evacuation, movement_backend=NoMovementBackend())
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        gate = model.gates[0]
        passenger.pos = gate._service_entry_position(0)
        gate.queue.join(passenger)
        self.assertIs(passenger, gate.queue.pop(0))
        gate._start_service(passenger, None)
        original_runtime = passenger.goal_runtime

        model._activate_evacuation_if_due()

        self.assertTrue(passenger.evacuation_pending)
        self.assertIs(original_runtime, passenger.goal_runtime)
        self.assertEqual(AgentIntent.ENTER_AND_BOARD.value, passenger.intent)

        for _ in range(20):
            gate._advance_active_passes()
            if not gate.active_passes:
                break

        self.assertFalse(passenger.evacuation_pending)
        self.assertEqual(AgentIntent.EVACUATE_STATION.value, passenger.intent)
        self.assertEqual("station_evacuation", passenger.goal_runtime.graph.graph_id)
        self.assertNotEqual("complete", passenger.goal_runtime.state.current_node_id)
        self.assertEqual(0, model.evacuated_persons)
        self.assertEqual(
            ["exit_gate"],
            [
                node.facility_stage
                for node in passenger.goal_runtime.graph.nodes
                if node.facility_stage
            ],
        )

    def test_protocol_exposes_canonical_command_and_event_vocabulary(self) -> None:
        self.assertEqual("observe_candidates", GoalCommandKind.OBSERVE_CANDIDATES.value)
        self.assertEqual("select_facility", GoalCommandKind.SELECT_FACILITY.value)
        self.assertEqual("complete_journey", GoalCommandKind.COMPLETE_JOURNEY.value)
        self.assertEqual("facility_selected", GoalEventKind.FACILITY_SELECTED.value)
        self.assertEqual("train_full", GoalEventKind.TRAIN_FULL.value)
        self.assertEqual("terminal_reached", GoalEventKind.TERMINAL_REACHED.value)

    def test_duplicate_event_id_is_idempotent(self) -> None:
        model = MetroStationModel(scenario(), movement_backend=NoMovementBackend())
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        runtime = passenger.goal_runtime
        event = GoalEvent(
            kind=GoalEventKind.ENTERED_REGION.value,
            time_seconds=1,
            event_id="entered-once",
            region_id="entry_gate_decision",
        )

        runtime.handle(event)
        once = runtime.state
        runtime.handle(event)

        self.assertEqual(once, runtime.state)


if __name__ == "__main__":
    unittest.main()
