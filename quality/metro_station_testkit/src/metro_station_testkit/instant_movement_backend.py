from __future__ import annotations

from metro_station.adapters.simulation.movement.backend import MovementBackend, MovementResult


class InstantMovementBackend(MovementBackend):
    """Deterministic non-physical backend for contract and orchestration acceptance."""

    def move(self, passenger) -> MovementResult:
        return MovementResult(int(passenger.unique_id), passenger.target, reached=True)
