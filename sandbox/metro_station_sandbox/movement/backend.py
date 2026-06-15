from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import cos, hypot, sin
from typing import TYPE_CHECKING

from shapely.geometry import Point as ShapelyPoint

from ..planning.plan import CROWD_INTERACTION_STATES, WALKING_STATES

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
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
            if passenger.state not in WALKING_STATES or passenger.passive_facility_service:
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

    def remove_passenger(self, passenger: PassengerAgent) -> None:
        """Remove a passenger from any movement-engine state."""


class JuPedSimMovementBackend(MovementBackend):
    """Persistent JuPedSim movement backend.

    Mesa still owns queues, train events, and plan transitions. JuPedSim owns
    continuous walking physics for active walking agents. Each walkable level is
    represented by a long-lived JuPedSim simulation so agent state survives
    across Mesa ticks.
    """

    MOVEMENT_STATES = WALKING_STATES

    def __init__(self, adapter: JuPedSimAdapter, *, strict: bool = True) -> None:
        self.adapter = adapter
        self.strict = strict
        self.jps_step_count = 0
        self.jps_batch_count = 0
        self._sessions = {}
        self._session_keys_by_passenger: dict[int, str | None] = {}
        self._model_identity: int | None = None

    def move(self, passenger: PassengerAgent) -> MovementResult:
        results = self._move_passengers([passenger], sync_sessions=False)
        if not results:
            raise RuntimeError(f"JuPedSim produced no result for passenger {passenger.unique_id}.")
        return results[0][1]

    def step_all(self, passengers: list[PassengerAgent]) -> list[tuple[PassengerAgent, MovementResult]]:
        eligible = [
            passenger
            for passenger in list(passengers)
            if passenger.state in self.MOVEMENT_STATES and not passenger.passive_facility_service
        ]
        return self._move_passengers(eligible, sync_sessions=True)

    def place_passenger(
        self,
        passenger: PassengerAgent,
        position: tuple[float, float],
        *,
        target: tuple[float, float] | None = None,
        level_id: str | None = None,
    ) -> tuple[float, float]:
        if not self.adapter.status.available:
            raise RuntimeError(
                f"JuPedSim placement requested but unavailable: {self.adapter.status.message}"
            )

        model = passenger.model
        placement_target = target or passenger.target or position
        session_key = self._session_key_for_position(
            model,
            position,
            placement_target,
            level_id if level_id is not None else passenger.current_level_id,
        )
        passenger_id = int(passenger.unique_id)
        previous_key = self._session_keys_by_passenger.get(passenger_id)
        if previous_key != session_key:
            self._remove_from_session_key(passenger_id, previous_key)

        try:
            session = self._session_for_key(model, session_key)
            placed = session.place_agent(
                passenger_id=passenger_id,
                position=position,
                target=placement_target,
            )
        except Exception:
            if self.strict:
                raise
            return super().place_passenger(
                passenger,
                position,
                target=target,
                level_id=level_id,
            )

        self._session_keys_by_passenger[passenger_id] = session_key
        return model.clamp_position(placed)

    def remove_passenger(self, passenger: PassengerAgent) -> None:
        passenger_id = int(passenger.unique_id)
        session_key = self._session_keys_by_passenger.pop(passenger_id, None)
        self._remove_from_session_key(passenger_id, session_key)

    def _move_passengers(
        self,
        passengers: list[PassengerAgent],
        *,
        sync_sessions: bool,
    ) -> list[tuple[PassengerAgent, MovementResult]]:
        if not self.adapter.status.available:
            raise RuntimeError(
                f"JuPedSim movement requested but unavailable: {self.adapter.status.message}"
            )

        if sync_sessions:
            self._sync_session_membership(passengers)

        result_by_id: dict[int, MovementResult] = {}
        tracked: list[tuple[PassengerAgent, str | None]] = []
        sessions_to_iterate: set[str | None] = set()
        for passenger in passengers:
            if passenger.state not in self.MOVEMENT_STATES:
                raise RuntimeError(
                    f"JuPedSim cannot move passenger {passenger.unique_id} in state "
                    f"{passenger.state!r}."
                )
            request = MovementRequest.from_passenger(passenger)
            reached = self._finish_if_already_at_target(passenger)
            if reached is not None:
                result_by_id[request.passenger_id] = reached
                continue

            session_key = self._session_key_for(passenger)
            previous_key = self._session_keys_by_passenger.get(request.passenger_id)
            if previous_key != session_key:
                self._remove_from_session_key(request.passenger_id, previous_key)

            try:
                session = self._session_for_key(passenger.model, session_key)
                session.ensure_agent(
                    passenger_id=request.passenger_id,
                    position=request.position,
                    target=request.target,
                )
            except Exception as exc:
                if self.strict:
                    raise RuntimeError(
                        "JuPedSim persistent tick failed for passenger "
                        f"{passenger.unique_id} target=({request.target[0]:.3f}, "
                        f"{request.target[1]:.3f})"
                    ) from exc
                result_by_id[request.passenger_id] = self._fallback_move(passenger)
                continue

            self._session_keys_by_passenger[request.passenger_id] = session_key
            sessions_to_iterate.add(session_key)
            tracked.append((passenger, session_key))

        if tracked:
            scenario = tracked[0][0].model.scenario
            for session_key in sessions_to_iterate:
                self._sessions[session_key].iterate(scenario.jupedsim_iterations_per_tick)
                self.jps_batch_count += 1

        for passenger, session_key in tracked:
            request = MovementRequest.from_passenger(passenger)
            session = self._sessions.get(session_key)
            position = session.position_for(request.passenger_id) if session is not None else None
            if position is None:
                self._session_keys_by_passenger.pop(request.passenger_id, None)
                next_position = request.target
            else:
                next_position = passenger.model.clamp_position(position)
            self.jps_step_count += 1
            reached = (
                hypot(request.target[0] - next_position[0], request.target[1] - next_position[1])
                <= request.radius
            )
            result_by_id[request.passenger_id] = MovementResult(
                request.passenger_id,
                next_position,
                reached=reached,
            )

        return [
            (passenger, result_by_id[int(passenger.unique_id)])
            for passenger in passengers
            if int(passenger.unique_id) in result_by_id
        ]

    def _sync_session_membership(self, passengers: list[PassengerAgent]) -> None:
        desired_keys = {
            int(passenger.unique_id): self._session_key_for(passenger) for passenger in passengers
        }
        for session_key, session in list(self._sessions.items()):
            keep = {
                passenger_id
                for passenger_id, desired_key in desired_keys.items()
                if desired_key == session_key
            }
            session.sync_passengers(keep)

        for passenger_id, session_key in list(self._session_keys_by_passenger.items()):
            if passenger_id not in desired_keys:
                self._remove_from_session_key(passenger_id, session_key)
                self._session_keys_by_passenger.pop(passenger_id, None)

    def _session_for_key(self, model, session_key: str | None):
        self._reset_sessions_if_model_changed(model)
        if session_key not in self._sessions:
            scenario = model.scenario
            self._sessions[session_key] = self.adapter.create_walking_session(
                width=model.layout_graph.geometry.width,
                height=model.layout_graph.geometry.height,
                walkable_area=model.jupedsim_walkable_area(session_key),
                operational_model=scenario.jupedsim_operational_model,
                agent_radius=scenario.jupedsim_agent_radius_units,
                target_radius=scenario.jupedsim_target_radius_units,
            )
        return self._sessions[session_key]

    def _reset_sessions_if_model_changed(self, model) -> None:
        model_identity = id(model)
        if self._model_identity is None:
            self._model_identity = model_identity
            return
        if self._model_identity == model_identity:
            return
        self._sessions.clear()
        self._session_keys_by_passenger.clear()
        self._model_identity = model_identity

    def _session_key_for(self, passenger: PassengerAgent) -> str | None:
        return self._session_key_for_position(
            passenger.model,
            passenger.pos,
            passenger.target,
            self._movement_level_key(passenger),
        )

    def _session_key_for_position(
        self,
        model,
        position: tuple[float, float],
        target: tuple[float, float],
        level_id: str | None,
    ) -> str | None:
        if level_id is None:
            return None
        level_area = model.jupedsim_walkable_area(level_id)
        if level_area.covers(ShapelyPoint(position)) and level_area.covers(ShapelyPoint(target)):
            return level_id
        return None

    def _remove_from_session_key(self, passenger_id: int, session_key: str | None) -> None:
        if session_key not in self._sessions:
            return
        self._sessions[session_key].remove_passenger(int(passenger_id))

    def _fallback_move(self, passenger: PassengerAgent) -> MovementResult:
        request = MovementRequest.from_passenger(passenger)
        x, y = request.position
        tx, ty = request.target
        distance = hypot(tx - x, ty - y)
        step = float(passenger.model.scenario.walk_units_per_tick)
        if distance <= 0.001 or distance <= max(step, request.radius):
            return MovementResult(request.passenger_id, request.target, reached=True)
        ratio = step / distance
        return MovementResult(
            request.passenger_id,
            (x + (tx - x) * ratio, y + (ty - y) * ratio),
            reached=False,
        )

    def _finish_if_already_at_target(self, passenger: PassengerAgent) -> MovementResult | None:
        x, y = passenger.pos
        tx, ty = passenger.target
        if hypot(tx - x, ty - y) <= 0.001:
            return MovementResult(int(passenger.unique_id), passenger.pos, reached=True)
        return None

    def _local_starts(self, passenger: PassengerAgent) -> list[tuple[float, float]]:
        model = passenger.model
        scenario = model.scenario
        starts = [passenger.pos]
        walkable_area = self._walkable_area_for(passenger)
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
            adjusted = self._clearance_adjusted_position(
                candidate,
                starts,
                scenario.jupedsim_agent_radius_units,
                scenario.jupedsim_clearance_multiplier,
                walkable_area=walkable_area,
                seed=int(getattr(other, "unique_id", 0) or 0),
            )
            if adjusted is not None:
                starts.append(adjusted)
        return starts

    def _movement_level_key(self, passenger: PassengerAgent) -> str | None:
        return passenger.current_level_id

    def _walkable_area_for(self, passenger: PassengerAgent):
        return self._walkable_area_for_segment(
            passenger.model,
            self._movement_level_key(passenger),
            [passenger.pos],
            passenger.target,
        )

    def _walkable_area_for_segment(
        self,
        model,
        level_id: str | None,
        starts: list[tuple[float, float]],
        target: tuple[float, float],
    ):
        if level_id is None:
            return model.jupedsim_walkable_area()
        level_area = model.jupedsim_walkable_area(level_id)
        if level_area.covers(ShapelyPoint(target)) and all(
            level_area.covers(ShapelyPoint(start)) for start in starts
        ):
            return level_area
        return model.jupedsim_walkable_area()

    @staticmethod
    def _has_initialization_clearance(
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

    @staticmethod
    def _can_share_initialization_batch(
        candidate: tuple[float, float],
        starts: list[tuple[float, float]],
        radius: float,
        clearance_multiplier: float,
    ) -> bool:
        return JuPedSimMovementBackend._has_initialization_clearance(
            candidate,
            starts,
            radius,
            clearance_multiplier,
        )

    def _clearance_adjusted_position(
        self,
        candidate: tuple[float, float],
        starts: list[tuple[float, float]],
        radius: float,
        clearance_multiplier: float,
        *,
        walkable_area,
        seed: int,
    ) -> tuple[float, float] | None:
        if self._can_share_initialization_batch(candidate, starts, radius, clearance_multiplier):
            return candidate

        min_distance = max(0.05, radius * clearance_multiplier)
        for attempt in range(12):
            angle_seed = seed * 1103515245 + attempt * 12345
            angle = (angle_seed % 6283) / 1000.0
            distance = min_distance * (1.0 + 0.25 * (attempt // 4))
            adjusted = (
                candidate[0] + cos(angle) * distance,
                candidate[1] + sin(angle) * distance,
            )
            if not walkable_area.covers(ShapelyPoint(adjusted)):
                continue
            if self._has_initialization_clearance(adjusted, starts, radius, clearance_multiplier):
                return adjusted
        return None


class BatchedJuPedSimMovementBackend(JuPedSimMovementBackend):
    """Backward-compatible name for the shared persistent JuPedSim backend."""
