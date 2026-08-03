from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..planning.goal_commands import GoalCommand
from ..planning.goal_events import GoalEvent
from ..planning.goal_graph import JourneyGraph
from ..planning.goal_state import AgentGoalState


@runtime_checkable
class RuntimeObservationAdapter(Protocol):
    """Read runtime state and return facts without mutating Goal state."""

    def observe(
        self,
        context: Any,
        graph: JourneyGraph,
        state: AgentGoalState,
    ) -> GoalEvent | None: ...


@runtime_checkable
class CommandExecutor(Protocol):
    """Consume Goal commands without choosing the next strategic goal."""

    def execute(
        self,
        context: Any,
        commands: tuple[GoalCommand, ...],
        *,
        current_stage: str | None = None,
    ) -> tuple[GoalEvent, ...]: ...


@runtime_checkable
class ServiceEventObserver(Protocol):
    """Translate facility lifecycle facts into a Goal event."""

    def observe(self, context: Any, state: AgentGoalState) -> GoalEvent | None: ...
