from __future__ import annotations

import unittest
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

from sandbox.metro_station_sandbox.design import create_design
from sandbox.metro_station_sandbox.migration import migrate_legacy_scenario_options
from sandbox.metro_station_sandbox.movement.backend import MovementBackend, MovementResult
from sandbox.metro_station_sandbox.planning.goal_events import (
    DecisionObservation,
    FacilityObservation,
    GoalEvent,
    GoalEventKind,
)
from sandbox.metro_station_sandbox.planning.goal_state import FacilityInteractionState
from sandbox.metro_station_sandbox.planning.journeys import (
    station_entry_to_boarding_journey_graph,
)
from sandbox.metro_station_sandbox.runtime.passenger_goal_runtime import PassengerGoalRuntime
from sandbox.metro_station_sandbox.planning.plan import AgentIntent
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.runtime.passenger_goal_observation import (
    WalkingCostConfigurationError,
    _walking_distance,
)
from metro_station.adapters.simulation.runtime.physical_waypoint_routing import (
    PhysicalRouteUnreachableError,
)
from metro_station.adapters.simulation.runtime.walking_cost_accounting import (
    record_walking_cost_source,
)
from sandbox.metro_station_sandbox.station.scenario import StationSandboxScenario


class NoMovementBackend(MovementBackend):
    def move(self, passenger) -> MovementResult:
        return MovementResult(passenger.unique_id, passenger.pos, reached=False)


class InstantMovementBackend(MovementBackend):
    def move(self, passenger) -> MovementResult:
        return MovementResult(passenger.unique_id, passenger.target, reached=True)


def _scenario() -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="goal_runtime_test",
        hour=8,
        minutes=1,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="unit",
        sample_hours=1,
        station_design=create_design("two_level_island_platform"),
        goal_graph_mode="active",
        audit_enabled=False,
        audit_print_events=False,
    )


def _candidate_event(
    runtime: PassengerGoalRuntime,
    facility_id: str,
    time_seconds: float,
) -> GoalEvent:
    node = runtime.graph.node(runtime.state.current_node_id)
    return GoalEvent(
        kind=GoalEventKind.CANDIDATES_UPDATED.value,
        time_seconds=time_seconds,
        observation=DecisionObservation(
            time_seconds=time_seconds,
            current_region_id=node.decision_region_id,
            entered_region_ids=(str(node.decision_region_id),),
            candidates=(
                FacilityObservation(
                    facility_id=facility_id,
                    stage=str(node.facility_stage),
                    available=True,
                    reachable=True,
                    walking_time_seconds=0.0,
                    queue_persons=0,
                    estimated_wait_seconds=0.0,
                ),
            ),
        ),
    )


def _facility_event(
    kind: GoalEventKind,
    facility_id: str,
    time_seconds: float,
) -> GoalEvent:
    return GoalEvent(
        kind=kind.value,
        time_seconds=time_seconds,
        facility_id=facility_id,
    )


def _reach_current_goal_region(model: MetroStationModel, passenger) -> None:
    """Publish the physical arrival fact before asking the graph to choose."""

    assert passenger.current_goal.kind == "goal_region"
    passenger.pos = passenger.target
    model.goal_coordinator.movement_reached(passenger)
    model.goal_coordinator.poll(passenger)


class PassengerGoalRuntimeTests(unittest.TestCase):
    def test_new_scenario_defaults_to_active_goal_graph(self) -> None:
        scenario = StationSandboxScenario(
            station_name="new_default",
            hour=8,
            minutes=1,
            tick_seconds=5,
            group_size=1,
            entry_count_hour=0,
            exit_count_hour=0,
            source_label="unit",
            sample_hours=1,
            station_design=create_design("two_level_island_platform"),
        )

        self.assertEqual("active", scenario.goal_graph_mode)

    def test_legacy_scenario_migration_makes_mode_explicit(self) -> None:
        migrated = migrate_legacy_scenario_options({"station_name": "old_model"})

        self.assertEqual("active", migrated["goal_graph_mode"])

    def test_decision_region_selects_only_after_physical_arrival(self) -> None:
        scenario = replace(_scenario(), goal_graph_mode="active")
        model = MetroStationModel(scenario, movement_backend=NoMovementBackend())
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)

        self.assertEqual(
            "approach_entry_gate_decision",
            passenger.goal_runtime.state.current_node_id,
        )
        self.assertIsNone(passenger.goal_runtime.state.commitment)
        self.assertEqual("goal_region", passenger.current_goal.kind)

        _reach_current_goal_region(model, passenger)

        self.assertEqual("use_entry_gate", passenger.goal_runtime.state.current_node_id)
        self.assertIsNotNone(passenger.goal_runtime.state.commitment)
        # The compiled decision target is the reserved portal-side queue
        # capture point. Physical arrival can therefore commit and join in one
        # event loop without an artificial out-and-back approach segment.
        self.assertEqual("queued", passenger.current_goal.kind)
        self.assertIn(
            passenger,
            model.facilities_by_id[
                passenger.goal_runtime.state.commitment.facility_id
            ].queue,
        )
        self.assertFalse(hasattr(passenger.plan, "chosen_facilities"))

        self.assertFalse(hasattr(model, "request_facility_choice"))

    def test_active_graph_choice_responds_to_targeting_congestion(self) -> None:
        scenario = replace(_scenario(), goal_graph_mode="active")
        model = MetroStationModel(scenario, movement_backend=NoMovementBackend())
        congested = model.gates[0]
        model._facility_targeting_reservations[congested.facility_id] = {
            passenger_id: 1 for passenger_id in range(100)
        }
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        _reach_current_goal_region(model, passenger)

        self.assertNotEqual(
            congested.facility_id,
            passenger.goal_runtime.state.commitment.facility_id,
        )

    def test_active_passengers_create_endogenous_gate_distribution(self) -> None:
        scenario = replace(_scenario(), goal_graph_mode="active")
        model = MetroStationModel(scenario, movement_backend=NoMovementBackend())
        passengers = [
            model._spawn_passenger(AgentIntent.ENTER_AND_BOARD) for _ in range(30)
        ]
        for passenger in passengers:
            _reach_current_goal_region(model, passenger)

        distribution = Counter(
            passenger.goal_runtime.state.commitment.facility_id
            for passenger in passengers
        )

        self.assertEqual(30, sum(distribution.values()))
        self.assertGreaterEqual(len(distribution), 2)
        self.assertTrue(all(passenger.goal_runtime is not None for passenger in passengers))

    def test_active_mode_drives_all_completed_production_journeys(self) -> None:
        scenario = replace(
            _scenario(),
            minutes=5,
            demand_minutes=1,
            entry_count_hour=120,
            initial_train_offset_seconds=5,
            train_dwell_seconds=60,
            goal_graph_mode="active",
        )
        model = MetroStationModel(scenario, movement_backend=InstantMovementBackend())
        model.run()

        self.assertEqual(2, model.spawned_persons)
        self.assertEqual(2, model.boarded_persons)
        self.assertEqual(6, len(model.facility_service_events))
        self.assertTrue(
            all(
                runtime.state.current_node_id == "complete"
                for runtime in model.passenger_goal_runtimes.values()
            )
        )

    def test_active_mode_completes_entry_exit_and_transfer_population(self) -> None:
        scenario = replace(
            _scenario(),
            minutes=10,
            demand_minutes=2,
            entry_count_hour=120,
            exit_count_hour=120,
            transfer_count_hour=120,
            initial_train_offset_seconds=5,
            # This test exercises goal-graph completion, not the default
            # 35-second door-throughput limit.  A full minute gives the
            # physically spaced boarding queue time to clear each train.
            train_dwell_seconds=60,
            goal_graph_mode="active",
        )
        model = MetroStationModel(scenario, movement_backend=InstantMovementBackend())
        model.run()

        completed_by_intent = Counter(
            event.intent for event in model.passenger_terminal_events
        )
        self.assertEqual(4, completed_by_intent[AgentIntent.ENTER_AND_BOARD.value])
        self.assertEqual(4, completed_by_intent[AgentIntent.EXIT_STATION.value])
        self.assertEqual(4, completed_by_intent[AgentIntent.TRANSFER.value])
        self.assertFalse(model.passengers)
        self.assertTrue(
            all(
                runtime.state.current_node_id == "complete"
                for runtime in model.passenger_goal_runtimes.values()
            )
        )

    def test_event_protocol_advances_facility_lifecycle(self) -> None:
        runtime = PassengerGoalRuntime(station_entry_to_boarding_journey_graph())
        runtime.handle(
            GoalEvent(
                kind=GoalEventKind.ENTERED_REGION.value,
                time_seconds=1.0,
                region_id="entry_gate_decision",
            )
        )
        runtime.handle(_candidate_event(runtime, "gate:A", 1.0))
        self.assertEqual("use_entry_gate", runtime.state.current_node_id)
        self.assertEqual("gate:A", runtime.state.commitment.facility_id)

        runtime.handle(_facility_event(GoalEventKind.REACHED_QUEUE_CAPTURE, "gate:A", 2.0))
        runtime.handle(_facility_event(GoalEventKind.QUEUE_JOINED, "gate:A", 2.0))
        self.assertEqual(FacilityInteractionState.QUEUEING.value, runtime.state.interaction_state)
        runtime.handle(_facility_event(GoalEventKind.SERVICE_STARTED, "gate:A", 3.0))
        runtime.handle(_facility_event(GoalEventKind.SERVICE_COMPLETED, "gate:A", 4.0))
        self.assertEqual("enter_paid_hall", runtime.state.current_node_id)

        runtime.handle(
            GoalEvent(
                kind=GoalEventKind.ENTERED_REGION.value,
                time_seconds=5.0,
                region_id="paid_hall",
            )
        )
        runtime.handle(
            GoalEvent(
                kind=GoalEventKind.ENTERED_REGION.value,
                time_seconds=6.0,
                region_id="vertical_decision",
            )
        )
        runtime.handle(_candidate_event(runtime, "stairs:A", 6.0))
        self.assertEqual("use_vertical_transfer", runtime.state.current_node_id)
        self.assertEqual("stairs:A", runtime.state.commitment.facility_id)

    def test_every_passenger_attaches_graph_runtime(self) -> None:
        model = MetroStationModel(_scenario(), movement_backend=NoMovementBackend())
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        self.assertIsNotNone(passenger.goal_runtime)

    def test_active_mode_attaches_independent_graph_state_to_each_passenger(self) -> None:
        model = MetroStationModel(_scenario(), movement_backend=NoMovementBackend())
        first = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        second = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)

        self.assertIsNotNone(first.goal_runtime)
        self.assertIsNot(first.goal_runtime, second.goal_runtime)
        self.assertEqual("station_entry_to_boarding", first.goal_runtime.graph.graph_id)
        self.assertEqual(
            "approach_entry_gate_decision",
            first.goal_runtime.state.current_node_id,
        )
        self.assertIsNone(first.goal_runtime.state.commitment)
        self.assertEqual("goal_region", first.current_goal.kind)

        _reach_current_goal_region(model, first)

        self.assertEqual("use_entry_gate", first.goal_runtime.state.current_node_id)
        self.assertIsNotNone(first.goal_runtime.state.commitment)
        self.assertEqual(
            ("wait_for_service",),
            tuple(
                command.kind
                for command in first.goal_runtime.take_pending_commands()
            ),
        )
        self.assertEqual("queued", first.current_goal.kind)
        self.assertEqual(
            "approach_entry_gate_decision",
            second.goal_runtime.state.current_node_id,
        )
        self.assertIsNone(second.goal_runtime.state.commitment)

    def test_graph_state_is_exported_in_passenger_snapshot(self) -> None:
        model = MetroStationModel(_scenario(), movement_backend=NoMovementBackend())
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)

        payload = model.snapshot()["passengers"][0]
        self.assertEqual("station_entry_to_boarding", payload["goal_graph"]["graph_id"])
        self.assertEqual(
            "approach_entry_gate_decision",
            payload["goal_graph"]["state"]["current_node_id"],
        )

        _reach_current_goal_region(model, passenger)
        payload = model.snapshot()["passengers"][0]
        self.assertEqual("use_entry_gate", payload["goal_graph"]["state"]["current_node_id"])
        self.assertIsNotNone(payload["goal_graph"]["state"]["commitment"])
        self.assertIn("goal_graph_parity", model.snapshot())

    def test_scenario_rejects_removed_goal_graph_modes(self) -> None:
        for mode in ("legacy", "shadow", "unknown"):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError, "goal_graph_mode"):
                    replace(_scenario(), goal_graph_mode=mode)

    def test_missing_physical_route_provider_is_a_typed_configuration_error(self) -> None:
        model = SimpleNamespace(
            walking_cost_source_counts=Counter(),
            walking_cost_evaluation_count=0,
        )

        with self.assertRaises(WalkingCostConfigurationError):
            _walking_distance(model, _walking_passenger(), _walking_facility())

        self.assertEqual({"provider_missing": 1}, dict(model.walking_cost_source_counts))
        self.assertEqual(1, model.walking_cost_evaluation_count)

    def test_only_typed_physical_unreachable_becomes_an_ineligible_cost(self) -> None:
        def unreachable(_passenger, _facility):
            raise PhysicalRouteUnreachableError("sealed")

        model = _walking_model(unreachable)

        distance, reachable, source = _walking_distance(
            model,
            _walking_passenger(),
            _walking_facility(),
        )

        self.assertEqual(0.0, distance)
        self.assertFalse(reachable)
        self.assertEqual("physical_route_unreachable", source)
        self.assertEqual(1, model.walking_cost_evaluation_count)

    def test_generic_route_errors_are_not_disguised_as_unreachable(self) -> None:
        def programming_error(_passenger, _facility):
            raise ValueError("bad portal object")

        model = _walking_model(programming_error)

        with self.assertRaisesRegex(ValueError, "bad portal object"):
            _walking_distance(model, _walking_passenger(), _walking_facility())

        self.assertEqual(
            {"physical_route_error": 1},
            dict(model.walking_cost_source_counts),
        )
        self.assertEqual(1, model.walking_cost_evaluation_count)

    def test_physical_cost_source_count_is_conserved(self) -> None:
        model = _walking_model(lambda _passenger, _facility: ((3.0, 4.0),))

        distance, reachable, source = _walking_distance(
            model,
            _walking_passenger(),
            _walking_facility(),
        )

        self.assertEqual(5.0, distance)
        self.assertTrue(reachable)
        self.assertEqual("physical_waypoint_geodesic", source)
        self.assertEqual(
            model.walking_cost_evaluation_count,
            sum(model.walking_cost_source_counts.values()),
        )

    def test_unknown_walking_cost_source_fails_closed(self) -> None:
        model = SimpleNamespace(
            walking_cost_source_counts=Counter(),
            walking_cost_evaluation_count=0,
        )

        with self.assertRaisesRegex(
            WalkingCostConfigurationError,
            "unknown walking-cost source",
        ):
            record_walking_cost_source(model, "euclidean_fallback_v2")

        self.assertEqual({}, dict(model.walking_cost_source_counts))
        self.assertEqual(0, model.walking_cost_evaluation_count)


def _walking_model(route_provider):
    return SimpleNamespace(
        facility_walking_route=route_provider,
        walking_cost_source_counts=Counter(),
        walking_cost_evaluation_count=0,
    )


def _walking_passenger():
    return SimpleNamespace(pos=(0.0, 0.0))


def _walking_facility():
    return SimpleNamespace(spec=SimpleNamespace(queue_anchor=(3.0, 4.0)))


if __name__ == "__main__":
    unittest.main()
