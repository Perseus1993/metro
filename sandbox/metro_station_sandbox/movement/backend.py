from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import hypot
from typing import TYPE_CHECKING
from collections import defaultdict

from ..planning.plan import CROWD_INTERACTION_STATES, PASSIVE_STATES, AgentState

if TYPE_CHECKING:
    from ..agents import PassengerAgent
    from .jps_adapter import JuPedSimAdapter


@dataclass(frozen=True)
class MovementRequest:
    passenger_id: int
    position: tuple[float, float]
    target: tuple[float, float]
    radius: float
    level: str | None

    @classmethod
    def from_passenger(cls, passenger: PassengerAgent) -> "MovementRequest":
        return cls(
            passenger_id=int(passenger.unique_id),
            position=passenger.pos,
            target=passenger.target,
            radius=float(passenger.model.scenario.jupedsim_target_radius_units),
            level=passenger.current_level_id,
        )


@dataclass(frozen=True)
class MovementResult:
    passenger_id: int
    position: tuple[float, float]
    reached: bool = False


class MovementBackend(ABC):
    """Movement engine interface for movable station agents."""

    @abstractmethod
    def move(self, passenger: PassengerAgent) -> MovementResult:
        """Return one passenger's next physical position and target reach state."""

    def step_all(self, passengers: list[PassengerAgent]) -> list[tuple[PassengerAgent, MovementResult]]:
        """Compute movement results for all active passenger agents."""
        results: list[tuple[PassengerAgent, MovementResult]] = []
        for passenger in list(passengers):
            if passenger.state in PASSIVE_STATES:
                continue
            results.append((passenger, self.move(passenger)))
        return results


class JuPedSimMovementBackend(MovementBackend):
    """Local JuPedSim micro-step movement backend.

    Mesa still owns queues, train events, and plan transitions. JuPedSim only
    advances physical movement for one model tick. The per-agent backend lets
    nearby passengers influence avoidance but does not update them symmetrically
    inside the same JuPedSim simulation.
    """

    MOVEMENT_STATES = {state.value for state in AgentState if state != AgentState.DEPARTED}

    def __init__(self, adapter: JuPedSimAdapter, *, strict: bool = True) -> None:
        self.adapter = adapter
        self.strict = True
        self.jps_step_count = 0
        self.jps_batch_count = 0

    def move(self, passenger: PassengerAgent) -> MovementResult:
        if not self.adapter.status.available:
            raise RuntimeError(
                f"JuPedSim movement requested but unavailable: {self.adapter.status.message}"
            )
        if passenger.state not in self.MOVEMENT_STATES:
            raise RuntimeError(
                f"JuPedSim cannot move passenger {passenger.unique_id} in state "
                f"{passenger.state!r}."
            )

        request = MovementRequest.from_passenger(passenger)
        x, y = request.position
        tx, ty = request.target
        if hypot(tx - x, ty - y) <= 0.001:
            return MovementResult(request.passenger_id, request.position, reached=True)

        model = passenger.model
        starts = self._local_starts(passenger)
        positions = self._simulate_walk_tick_with_audit(
            model=model,
            starts=starts,
            target=request.target,
        )

        if not positions:
            raise RuntimeError(
                f"JuPedSim returned no position for passenger {passenger.unique_id} "
                f"target=({tx:.3f}, {ty:.3f})."
            )

        position = model.clamp_position(positions[0])
        self.jps_step_count += 1
        reached = hypot(tx - position[0], ty - position[1]) <= request.radius
        return MovementResult(request.passenger_id, position, reached=reached)

    def _simulate_walk_tick_with_audit(
        self,
        *,
        model,
        starts: list[tuple[float, float]],
        target: tuple[float, float],
    ) -> list[tuple[float, float]]:
        scenario = model.scenario
        try:
            return self.adapter.simulate_walk_tick(
                starts=starts,
                target=target,
                width=model.layout_graph.geometry.width,
                height=model.layout_graph.geometry.height,
                iterations=scenario.jupedsim_iterations_per_tick,
                radius=scenario.jupedsim_agent_radius_units,
                target_radius=scenario.jupedsim_target_radius_units,
                walkable_area=model.jupedsim_walkable_area(),
                operational_model=scenario.jupedsim_operational_model,
            )
        except Exception as exc:
            raise RuntimeError(
                f"JuPedSim tick failed for target=({target[0]:.3f}, {target[1]:.3f})"
            ) from exc

    def _local_starts(self, passenger: PassengerAgent) -> list[tuple[float, float]]:
        model = passenger.model
        scenario = model.scenario
        starts = [passenger.pos]
        try:
            nearby = model.nearby_passengers(passenger, scenario.jupedsim_neighbor_radius_units)
        except Exception as exc:
            raise RuntimeError(
                f"Nearby passenger lookup failed for passenger {passenger.unique_id}."
            ) from exc
        for other, _dx, _dy, _dist in nearby[: scenario.jupedsim_neighbor_sample_limit]:
            if other.state not in CROWD_INTERACTION_STATES:
                continue
            candidate = other.pos
            if self._has_clearance(
                candidate,
                starts,
                scenario.jupedsim_agent_radius_units,
                scenario.jupedsim_clearance_multiplier,
            ):
                starts.append(candidate)
        return starts

    @staticmethod
    def _has_clearance(
        candidate: tuple[float, float],
        starts: list[tuple[float, float]],
        radius: float,
        clearance_multiplier: float,
    ) -> bool:
        min_distance = max(0.05, radius * clearance_multiplier)
        for existing in starts:
            if hypot(candidate[0] - existing[0], candidate[1] - existing[1]) < min_distance:
                return False
        return True


class BatchedJuPedSimMovementBackend(JuPedSimMovementBackend):
    """Batch eligible walking passengers by target for shared JuPedSim ticks.

    This removes the expensive per-passenger Simulation construction for common
    waypoint targets. Queue layout, facility release motion, and train/platform
    state transitions remain under Mesa's explicit process agents.
    """

    def step_all(self, passengers: list[PassengerAgent]) -> list[tuple[PassengerAgent, MovementResult]]:
        return self.batch_move(passengers)

    def batch_move(self, passengers: list[PassengerAgent]) -> list[tuple[PassengerAgent, MovementResult]]:
        if not self.adapter.status.available:
            raise RuntimeError(
                f"JuPedSim movement requested but unavailable: {self.adapter.status.message}"
            )

        groups: dict[tuple[float, float], list[PassengerAgent]] = defaultdict(list)
        results: list[tuple[PassengerAgent, MovementResult]] = []
        for passenger in list(passengers):
            if passenger.state in PASSIVE_STATES:
                continue
            if passenger.state not in self.MOVEMENT_STATES:
                raise RuntimeError(
                    f"JuPedSim cannot move passenger {passenger.unique_id} in state "
                    f"{passenger.state!r}."
                )
            reached = self._finish_if_already_at_target(passenger)
            if reached is not None:
                results.append((passenger, reached))
                continue
            tx, ty = passenger.target
            groups[(round(tx, 3), round(ty, 3))].append(passenger)

        for target_key, group in groups.items():
            results.extend(self._step_group(target_key, group))
        return results

    def _finish_if_already_at_target(self, passenger: PassengerAgent) -> MovementResult | None:
        x, y = passenger.pos
        tx, ty = passenger.target
        if hypot(tx - x, ty - y) <= 0.001:
            return MovementResult(int(passenger.unique_id), passenger.pos, reached=True)
        return None

    def _step_group(
        self,
        target_key: tuple[float, float],
        group: list[PassengerAgent],
    ) -> list[tuple[PassengerAgent, MovementResult]]:
        if not group:
            return []

        scenario = group[0].model.scenario
        starts: list[tuple[float, float]] = []
        batched: list[PassengerAgent] = []
        single_agent: list[PassengerAgent] = []
        for passenger in group:
            if self._has_clearance(
                passenger.pos,
                starts,
                scenario.jupedsim_agent_radius_units,
                scenario.jupedsim_clearance_multiplier,
            ):
                starts.append(passenger.pos)
                batched.append(passenger)
            else:
                single_agent.append(passenger)

        results: list[tuple[PassengerAgent, MovementResult]] = []
        for passenger in single_agent:
            results.append((passenger, JuPedSimMovementBackend.move(self, passenger)))

        if not batched:
            return results

        model = batched[0].model
        positions = self._simulate_walk_tick_with_audit(
            model=model,
            starts=starts,
            target=target_key,
        )

        if len(positions) != len(batched):
            raise RuntimeError(
                "JuPedSim batch result size mismatch: "
                f"positions={len(positions)} agents={len(batched)} target={target_key}"
            )

        self.jps_batch_count += 1
        for passenger, position in zip(batched, positions):
            next_position = passenger.model.clamp_position(position)
            self.jps_step_count += 1
            reached = (
                hypot(
                    passenger.target[0] - next_position[0],
                    passenger.target[1] - next_position[1],
                )
                <= scenario.jupedsim_target_radius_units
            )
            results.append(
                (
                    passenger,
                    MovementResult(int(passenger.unique_id), next_position, reached=reached),
                )
            )
        return results
