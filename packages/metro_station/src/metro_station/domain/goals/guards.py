from __future__ import annotations

from typing import Protocol, runtime_checkable

from .events import GoalEvent
from .state import AgentGoalState


@runtime_checkable
class GoalTransitionGuard(Protocol):
    def __call__(self, state: AgentGoalState, event: GoalEvent) -> bool: ...


GoalGuardRegistry = dict[str, GoalTransitionGuard]
