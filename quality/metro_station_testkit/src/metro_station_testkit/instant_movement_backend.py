from __future__ import annotations

from math import hypot

from metro_station.adapters.simulation.movement.backend import MovementBackend, MovementResult


class InstantMovementBackend(MovementBackend):
    """Deterministic non-physical backend for contract and orchestration acceptance."""

    def move(self, passenger) -> MovementResult:
        return MovementResult(int(passenger.unique_id), passenger.target, reached=True)


class EndpointClearInstantMovementBackend(MovementBackend):
    """Fast orchestration double that refuses an already occupied endpoint.

    It is still non-physical and therefore never qualifies as trajectory
    evidence.  Its only additional contract is to avoid manufacturing an
    exact body overlap that can deadlock queue/process ownership tests.
    """

    def move(self, passenger) -> MovementResult:
        target = tuple(passenger.target)
        minimum = (
            passenger.model.scenario.jupedsim_agent_radius_units
            * passenger.model.scenario.jupedsim_clearance_multiplier
        )
        blocked = any(
            other is not passenger
            and other.current_level_id == passenger.current_level_id
            and hypot(other.pos[0] - target[0], other.pos[1] - target[1])
            < minimum - 1e-9
            for other in passenger.model.passengers
        )
        return MovementResult(
            int(passenger.unique_id),
            tuple(passenger.pos) if blocked else target,
            reached=not blocked,
        )
