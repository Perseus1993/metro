from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .commands import GoalCommand
from .events import GoalEvent
from .graph import JourneyGraph
from .state import AgentGoalState


@dataclass(frozen=True)
class GoalEngineResult:
    """Pure state-machine result; adapters execute the returned commands."""

    state: AgentGoalState
    commands: tuple[GoalCommand, ...] = ()
    handled: bool = True


@runtime_checkable
class GoalStateMachine(Protocol):
    """Event-driven journey executor independent of Mesa and movement engines."""

    def start(
        self,
        graph: JourneyGraph,
        *,
        at_time_seconds: float = 0.0,
    ) -> GoalEngineResult: ...

    def handle(
        self,
        graph: JourneyGraph,
        state: AgentGoalState,
        event: GoalEvent,
    ) -> GoalEngineResult: ...
