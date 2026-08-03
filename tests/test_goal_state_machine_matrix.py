from __future__ import annotations

import unittest
from dataclasses import replace

from sandbox.metro_station_sandbox.planning.default_goal_state_machine import (
    EventDrivenGoalStateMachine,
)
from sandbox.metro_station_sandbox.planning.goal_commands import GoalCommandKind
from sandbox.metro_station_sandbox.planning.goal_events import (
    DecisionObservation,
    FacilityObservation,
    GoalEvent,
    GoalEventKind,
)
from sandbox.metro_station_sandbox.planning.goal_graph import (
    GoalNodeKind,
    JourneyGoalNode,
    JourneyGraph,
    JourneyTransition,
)
from sandbox.metro_station_sandbox.planning.goal_state import FacilityInteractionState
from sandbox.metro_station_sandbox.planning.journeys import entry_gate_journey_graph


class GoalStateMachineMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = entry_gate_journey_graph()
        self.machine = EventDrivenGoalStateMachine()

    def observation(self, time_seconds: float = 2.0) -> DecisionObservation:
        return DecisionObservation(
            time_seconds=time_seconds,
            current_region_id="entry_gate_decision",
            candidates=(
                FacilityObservation(
                    facility_id="gate_1",
                    stage="entry_gate",
                    available=True,
                    reachable=True,
                    walking_time_seconds=2,
                    queue_persons=1,
                    estimated_wait_seconds=3,
                ),
            ),
        )

    def decision_state(self):
        started = self.machine.start(self.graph)
        return self.machine.handle(
            self.graph,
            started.state,
            GoalEvent(
                kind=GoalEventKind.ENTERED_REGION.value,
                time_seconds=1,
                region_id="entry_gate_decision",
            ),
        ).state

    def selected_state(self):
        return self.machine.handle(
            self.graph,
            self.decision_state(),
            GoalEvent(
                kind=GoalEventKind.CANDIDATES_UPDATED.value,
                time_seconds=2,
                observation=self.observation(),
            ),
        ).state

    def serving_state(self):
        state = self.selected_state()
        for time_seconds, kind in (
            (3, GoalEventKind.REACHED_QUEUE_CAPTURE),
            (4, GoalEventKind.QUEUE_JOINED),
            (5, GoalEventKind.SERVICE_STARTED),
        ):
            state = self.machine.handle(
                self.graph,
                state,
                GoalEvent(kind=kind.value, time_seconds=time_seconds, facility_id="gate_1"),
            ).state
        return state

    def test_start_rejects_negative_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            self.machine.start(self.graph, at_time_seconds=-0.01)

    def test_state_must_match_graph_identity_and_version(self) -> None:
        state = self.machine.start(self.graph).state
        event = GoalEvent(
            kind=GoalEventKind.ENTERED_REGION.value,
            time_seconds=1,
            region_id="entry_gate_decision",
        )
        cases = (
            (replace(state, journey_graph_id="other"), "different journey graph"),
            (replace(state, journey_graph_version=99), "version mismatch"),
        )
        for invalid, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(ValueError, pattern):
                    self.machine.handle(self.graph, invalid, event)

    def test_handled_event_time_cannot_move_backwards(self) -> None:
        state = self.selected_state()
        with self.assertRaisesRegex(ValueError, "cannot move backwards"):
            self.machine.handle(
                self.graph,
                state,
                GoalEvent(
                    kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
                    time_seconds=1.5,
                    facility_id="gate_1",
                ),
            )

    def test_out_of_order_events_do_not_mutate_decision_state(self) -> None:
        state = self.decision_state()
        events = (
            GoalEvent(
                kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
                time_seconds=2,
                facility_id="gate_1",
            ),
            GoalEvent(
                kind=GoalEventKind.QUEUE_JOINED.value,
                time_seconds=2,
                facility_id="gate_1",
            ),
            GoalEvent(
                kind=GoalEventKind.SERVICE_STARTED.value,
                time_seconds=2,
                facility_id="gate_1",
            ),
            GoalEvent(
                kind=GoalEventKind.SERVICE_COMPLETED.value,
                time_seconds=2,
                facility_id="gate_1",
            ),
        )
        for event in events:
            with self.subTest(event=event.kind):
                result = self.machine.handle(self.graph, state, event)
                self.assertFalse(result.handled)
                self.assertEqual(state, result.state)

    def test_events_for_wrong_facility_never_progress_commitment(self) -> None:
        state = self.selected_state()
        for kind in (
            GoalEventKind.REACHED_QUEUE_CAPTURE,
            GoalEventKind.QUEUE_JOINED,
            GoalEventKind.SERVICE_STARTED,
            GoalEventKind.SERVICE_COMPLETED,
            GoalEventKind.FACILITY_UNAVAILABLE,
        ):
            with self.subTest(kind=kind.value):
                result = self.machine.handle(
                    self.graph,
                    state,
                    GoalEvent(kind=kind.value, time_seconds=3, facility_id="gate_99"),
                )
                self.assertFalse(result.handled)
                self.assertEqual(state, result.state)

    def test_in_service_state_cannot_replan(self) -> None:
        state = self.serving_state()
        events = (
            GoalEvent(
                kind=GoalEventKind.PROGRESS_STALLED.value,
                time_seconds=6,
                reason="service_is_slow",
            ),
            GoalEvent(
                kind=GoalEventKind.FACILITY_UNAVAILABLE.value,
                time_seconds=6,
                facility_id="gate_1",
                reason="late_fault",
            ),
        )
        for event in events:
            result = self.machine.handle(self.graph, state, event)
            self.assertFalse(result.handled)
            self.assertEqual(FacilityInteractionState.IN_SERVICE.value, result.state.interaction_state)

    def test_progress_stall_before_service_requests_replan(self) -> None:
        state = self.selected_state()
        result = self.machine.handle(
            self.graph,
            state,
            GoalEvent(
                kind=GoalEventKind.PROGRESS_STALLED.value,
                time_seconds=3,
                reason="no_position_progress",
            ),
        )
        self.assertTrue(result.handled)
        self.assertEqual(FacilityInteractionState.REPLAN_PENDING.value, result.state.interaction_state)
        self.assertEqual("gate_1", result.commands[0].facility_id)

    def test_facility_goal_can_be_graph_entry(self) -> None:
        graph = JourneyGraph(
            graph_id="facility_entry",
            entry_node_id="gate",
            nodes=(
                JourneyGoalNode(
                    node_id="gate",
                    kind=GoalNodeKind.USE_FACILITY_STAGE.value,
                    label="gate",
                    facility_stage="entry_gate",
                    decision_region_id="decision",
                ),
                JourneyGoalNode("complete", GoalNodeKind.COMPLETE.value, "complete"),
            ),
            transitions=(
                JourneyTransition("done", "gate", "complete", GoalEventKind.GOAL_COMPLETED.value),
            ),
        )
        result = self.machine.start(graph)
        self.assertEqual(FacilityInteractionState.APPROACH_DECISION_REGION.value, result.state.interaction_state)
        self.assertEqual(GoalCommandKind.WALK_TO_REGION.value, result.commands[0].kind)

    def test_full_train_is_recorded_without_leaving_wait_node(self) -> None:
        graph = JourneyGraph(
            graph_id="wait_for_train",
            entry_node_id="wait",
            nodes=(
                JourneyGoalNode(
                    node_id="wait",
                    kind=GoalNodeKind.WAIT_FOR_EVENT.value,
                    label="wait for train",
                    wait_event_kind=GoalEventKind.TRAIN_AVAILABLE.value,
                ),
                JourneyGoalNode("complete", GoalNodeKind.COMPLETE.value, "complete"),
            ),
            transitions=(
                JourneyTransition(
                    "train_arrived",
                    "wait",
                    "complete",
                    GoalEventKind.TRAIN_AVAILABLE.value,
                ),
            ),
        )
        state = self.machine.start(graph).state

        full = self.machine.handle(
            graph,
            state,
            GoalEvent(
                kind=GoalEventKind.TRAIN_FULL.value,
                time_seconds=10.0,
                event_id="train-full-10",
            ),
        )

        self.assertTrue(full.handled)
        self.assertEqual("wait", full.state.current_node_id)
        self.assertEqual(10.0, full.state.last_event_time_seconds)
        self.assertIn("train-full-10", full.state.processed_event_ids)

        available = self.machine.handle(
            graph,
            full.state,
            GoalEvent(
                kind=GoalEventKind.TRAIN_AVAILABLE.value,
                time_seconds=20.0,
            ),
        )
        self.assertEqual("complete", available.state.current_node_id)


if __name__ == "__main__":
    unittest.main()
