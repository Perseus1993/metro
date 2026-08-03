"""Compatibility imports for the official Goal domain."""

from metro_station.domain.goals.graph import (
    GoalNodeKind,
    JourneyGoalNode,
    JourneyGraph,
    JourneyTransition,
)

__all__ = ["GoalNodeKind", "JourneyGoalNode", "JourneyGraph", "JourneyTransition"]
