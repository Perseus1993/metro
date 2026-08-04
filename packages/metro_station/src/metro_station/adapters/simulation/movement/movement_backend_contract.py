from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from math import hypot

from ..planning.plan import WALKING_STATES
from .contracts import MovementResult, _movement_suppressed_this_step
from .trajectory_trace import empty_movement_trace

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from .native_facility_motion import NativeFacilityMotion


class MovementBackend(ABC):
    """Movement engine interface for movable station agents."""

    @abstractmethod
    def move(self, passenger: PassengerAgent) -> MovementResult:
        """Return one passenger's next physical position and target reach state."""

    def step_all(
        self,
        passengers: list[PassengerAgent],
    ) -> list[tuple[PassengerAgent, MovementResult]]:
        """Compute movement results for all active passenger agents."""

        results: list[tuple[PassengerAgent, MovementResult]] = []
        for passenger in list(passengers):
            if (
                passenger.state not in WALKING_STATES
                or passenger.passive_facility_service
                or _movement_suppressed_this_step(passenger)
            ):
                continue
            results.append((passenger, self.move(passenger)))
        return results

    def place_passenger(
        self,
        passenger: PassengerAgent,
        position: tuple[float, float],
        *,
        target: tuple[float, float] | None = None,
        level_id: str | None = None,
    ) -> tuple[float, float]:
        """Place a passenger at a legal movement-engine position."""

        return passenger.model.clamp_position(position)

    def resolve_placement(
        self,
        passenger: PassengerAgent,
        position: tuple[float, float],
        *,
        level_id: str | None = None,
    ) -> tuple[float, float]:
        """Resolve a legal future position without mutating backend state."""

        del level_id
        return passenger.model.clamp_position(position)

    def resolve_certified_placement(
        self,
        passenger: PassengerAgent,
        position: tuple[float, float],
        *,
        level_id: str | None = None,
    ) -> tuple[float, float]:
        """Check one compiler-certified coordinate without nearby relocation."""

        resolved = self.resolve_placement(
            passenger,
            position,
            level_id=level_id,
        )
        if hypot(resolved[0] - position[0], resolved[1] - position[1]) > 1e-6:
            raise RuntimeError(
                f"certified placement {position!r} was relocated to {resolved!r}"
            )
        return resolved

    def remove_passenger(self, passenger: PassengerAgent) -> None:
        """Remove a passenger from any movement-engine state."""

    def active_passenger_ids(self) -> set[int]:
        """Return passengers still retained by the physical movement engine."""

        return set()

    def owns_passive_layout_motion(self) -> bool:
        """Whether queue/waiting compaction is advanced by this backend.

        Passive layouts still contain physical bodies.  A persistent crowd
        backend must own their motion as well as ordinary walking; otherwise
        the process model and the collision model publish two different
        positions for the same passenger.
        """

        return False

    def owns_continuous_facility_service_motion(
        self,
        *,
        facility_kind: str,
        entry_level_id: str | None,
        exit_level_id: str | None,
    ) -> bool:
        """Whether one native body remains authoritative during service.

        This is deliberately separate from passive queue compaction.  A
        backend may own same-floor mechanical traversal while cross-level
        connectors, train boarding, or cabin processes retain their own
        physical-motion authority.
        """

        del facility_kind, entry_level_id, exit_level_id
        return False

    def retains_native_body_at_facility_admission(
        self,
        *,
        facility_kind: str,
        entry_level_id: str | None,
    ) -> bool:
        """Whether service admission keeps the landing's existing native body."""

        del facility_kind, entry_level_id
        return False

    def command_native_facility_motion(
        self,
        passenger: PassengerAgent,
        motion: NativeFacilityMotion,
    ) -> bool:
        """Create or update one collision-authoritative landing motion."""

        del passenger, motion
        return False

    def native_facility_motion_position(
        self,
        passenger: PassengerAgent,
    ) -> tuple[float, float] | None:
        """Return the current authoritative coordinate for a native episode."""

        del passenger
        return None

    def finish_native_facility_motion(
        self,
        passenger: PassengerAgent,
        *,
        remove_native_body: bool,
    ) -> None:
        """End a landing episode, optionally transferring into a connector."""

        if remove_native_body:
            self.remove_passenger(passenger)

    def on_walkable_geometry_changed(self, model: object) -> None:
        """Refresh geometry-dependent state after a scheduled control event."""

    def movement_trace(self) -> dict[str, object]:
        """Return walking samples owned by the movement backend."""

        return empty_movement_trace(reason="movement_backend_has_no_trace")

    def record_facility_motion_boundary(
        self,
        passenger: PassengerAgent,
        *,
        time_seconds: float,
        phase: str,
    ) -> None:
        """Record an exact process hand-off point when this backend owns it."""

        del passenger, time_seconds, phase

    def commit_movement_result(
        self,
        passenger: PassengerAgent,
        result: MovementResult,
    ) -> None:
        """Commit the coordinate that Mesa will publish for this movement step."""


__all__ = ["MovementBackend"]
