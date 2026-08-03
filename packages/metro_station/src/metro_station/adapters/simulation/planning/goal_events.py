"""Compatibility imports for the official Goal domain."""

from metro_station.domain.goals.events import (
    DecisionObservation,
    FacilityObservation,
    GoalEvent,
    GoalEventKind,
)

__all__ = ["DecisionObservation", "FacilityObservation", "GoalEvent", "GoalEventKind"]
