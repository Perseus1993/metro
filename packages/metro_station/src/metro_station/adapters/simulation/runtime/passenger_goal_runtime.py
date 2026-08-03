from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..planning.default_goal_state_machine import EventDrivenGoalStateMachine
from ..planning.goal_commands import GoalCommand
from ..planning.goal_events import GoalEvent
from ..planning.goal_graph import JourneyGraph


@dataclass(frozen=True)
class PassengerGoalTransition:
    event_kind: str
    before_node_id: str
    after_node_id: str
    command_kinds: tuple[str, ...]


class PassengerGoalRuntime:
    """Per-passenger Graph state holder used by the production Mesa runtime."""

    def __init__(self, graph: JourneyGraph) -> None:
        self.graph = graph
        self.machine = EventDrivenGoalStateMachine()
        started = self.machine.start(graph)
        self.state = started.state
        self.pending_commands = started.commands
        self.transitions: list[PassengerGoalTransition] = []

    def handle(self, event: GoalEvent) -> tuple[GoalCommand, ...]:
        before = self.state
        result = self.machine.handle(self.graph, before, event)
        if not result.handled:
            return ()
        self.state = result.state
        commands = result.commands
        self.pending_commands = commands
        transition = PassengerGoalTransition(
            event_kind=event.kind,
            before_node_id=before.current_node_id,
            after_node_id=result.state.current_node_id,
            command_kinds=tuple(command.kind for command in commands),
        )
        if not self.transitions or self.transitions[-1] != transition:
            self.transitions.append(transition)
        return commands

    def take_pending_commands(self) -> tuple[GoalCommand, ...]:
        commands = self.pending_commands
        self.pending_commands = ()
        return commands

    def snapshot(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph.graph_id,
            "graph_version": self.graph.version,
            "state": self.state.as_dict(),
            "pending_commands": [command.as_dict() for command in self.pending_commands],
            "transition_count": len(self.transitions),
        }
