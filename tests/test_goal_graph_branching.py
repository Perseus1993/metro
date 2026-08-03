from __future__ import annotations

import unittest

from sandbox.metro_station_sandbox.planning.default_goal_state_machine import (
    EventDrivenGoalStateMachine,
)
from sandbox.metro_station_sandbox.planning.goal_events import GoalEvent, GoalEventKind
from sandbox.metro_station_sandbox.planning.goal_graph import (
    GoalNodeKind,
    JourneyGoalNode,
    JourneyGraph,
    JourneyTransition,
)


def _waiting_graph(*transitions: JourneyTransition) -> JourneyGraph:
    targets = {transition.target_node_id for transition in transitions}
    return JourneyGraph(
        graph_id="train_wait_branch",
        entry_node_id="wait_train",
        nodes=(
            JourneyGoalNode(
                node_id="wait_train",
                kind=GoalNodeKind.WAIT_FOR_EVENT.value,
                label="wait for train",
                wait_event_kind=GoalEventKind.TRAIN_AVAILABLE.value,
            ),
            *(
                JourneyGoalNode(
                    node_id=node_id,
                    kind=GoalNodeKind.COMPLETE.value,
                    label=node_id.replace("_", " "),
                )
                for node_id in sorted(targets)
            ),
        ),
        transitions=transitions,
    )


class GoalGraphBranchingTests(unittest.TestCase):
    def test_wait_event_uses_guarded_branch(self) -> None:
        graph = _waiting_graph(
            JourneyTransition(
                "board_with_capacity",
                "wait_train",
                "board",
                GoalEventKind.TRAIN_AVAILABLE.value,
                guard_id="has_capacity",
            ),
            JourneyTransition(
                "wait_without_capacity",
                "wait_train",
                "wait_next",
                GoalEventKind.TRAIN_AVAILABLE.value,
                guard_id="no_capacity",
            ),
        )
        machine = EventDrivenGoalStateMachine(
            guards={
                "has_capacity": lambda _state, event: event.reason == "capacity",
                "no_capacity": lambda _state, event: event.reason != "capacity",
            }
        )
        started = machine.start(graph)
        result = machine.handle(
            graph,
            started.state,
            GoalEvent(GoalEventKind.TRAIN_AVAILABLE.value, 10.0, reason="capacity"),
        )
        self.assertEqual("board", result.state.current_node_id)

    def test_wait_timeout_takes_explicit_fallback(self) -> None:
        graph = _waiting_graph(
            JourneyTransition(
                "board",
                "wait_train",
                "board",
                GoalEventKind.TRAIN_AVAILABLE.value,
            ),
            JourneyTransition(
                "timeout",
                "wait_train",
                "wait_next",
                GoalEventKind.WAIT_TIMEOUT.value,
            ),
        )
        machine = EventDrivenGoalStateMachine()
        started = machine.start(graph)
        result = machine.handle(
            graph,
            started.state,
            GoalEvent(GoalEventKind.WAIT_TIMEOUT.value, 30.0, reason="headway_timeout"),
        )
        self.assertEqual("wait_next", result.state.current_node_id)

    def test_generic_completion_edge_remains_backward_compatible(self) -> None:
        graph = _waiting_graph(
            JourneyTransition(
                "legacy_complete",
                "wait_train",
                "board",
                GoalEventKind.GOAL_COMPLETED.value,
            ),
        )
        machine = EventDrivenGoalStateMachine()
        started = machine.start(graph)
        result = machine.handle(
            graph,
            started.state,
            GoalEvent(GoalEventKind.TRAIN_AVAILABLE.value, 10.0),
        )
        self.assertEqual("board", result.state.current_node_id)

    def test_unknown_guard_fails_explicitly(self) -> None:
        graph = _waiting_graph(
            JourneyTransition(
                "guarded",
                "wait_train",
                "board",
                GoalEventKind.TRAIN_AVAILABLE.value,
                guard_id="missing",
            ),
        )
        machine = EventDrivenGoalStateMachine()
        started = machine.start(graph)
        with self.assertRaisesRegex(ValueError, "unknown goal transition guard"):
            machine.handle(
                graph,
                started.state,
                GoalEvent(GoalEventKind.TRAIN_AVAILABLE.value, 10.0),
            )


if __name__ == "__main__":
    unittest.main()
