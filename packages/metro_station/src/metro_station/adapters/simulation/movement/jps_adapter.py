from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import cos, hypot, sin, tau
from typing import Any

from ..station.geometry import project_to_safe_point
from .jps_one_shot import simulate_walk_segment, simulate_walk_tick


@dataclass(frozen=True)
class JuPedSimStatus:
    available: bool
    message: str
    version: str | None = None


@dataclass(frozen=True)
class JuPedSimRemovalRecord:
    """Authoritative evidence for an agent that left a walking session."""

    passenger_id: int
    reason: str
    last_authoritative_position: tuple[float, float]
    reached: bool
    occurred_after_seconds: float
    last_position_after_seconds: float
    episode_id: str


class JuPedSimPlacementBlocked(RuntimeError):
    """The requested coordinate cannot be inserted without moving the person."""


@dataclass(frozen=True)
class _JourneyTarget:
    stage_id: int
    journey_id: int
    position: tuple[float, float]


class JuPedSimWalkingSession:
    """Long-lived JuPedSim simulation for one physical walking domain."""

    def __init__(
        self,
        adapter: "JuPedSimAdapter",
        *,
        width: float,
        height: float,
        walkable_area,
        operational_model: str,
        agent_radius: float,
        target_radius: float,
        dt_seconds: float,
    ) -> None:
        if adapter._jps is None:
            raise RuntimeError(adapter.status.message)
        self._adapter = adapter
        self._jps = adapter._jps
        self.geometry = adapter.build_walkable_area(width, height, walkable_area)
        self.operational_model = operational_model
        self.agent_radius = float(agent_radius)
        self.target_radius = float(target_radius)
        self.dt_seconds = float(dt_seconds)
        self._simulation = self._jps.Simulation(
            model=adapter._model_for_name(operational_model),
            geometry=self.geometry,
            dt=self.dt_seconds,
        )
        self._targets: dict[tuple[float, float, float], _JourneyTarget] = {}
        self._agent_ids: dict[int, int] = {}
        self._passenger_ids: dict[int, int] = {}
        self._agent_targets: dict[int, tuple[float, float, float]] = {}
        self._agent_target_positions: dict[int, tuple[float, float]] = {}
        self._agent_desired_speeds: dict[int, float] = {}
        self._last_positions: dict[int, tuple[float, float]] = {}
        self._episode_numbers: dict[int, int] = {}
        self._active_episode_ids: dict[int, str] = {}
        self._removal_records: dict[int, JuPedSimRemovalRecord] = {}

    @property
    def agent_count(self) -> int:
        return int(self._simulation.agent_count())

    def active_passenger_ids(self) -> set[int]:
        return set(self._agent_ids)

    def sync_passengers(self, keep_passenger_ids: set[int]) -> None:
        for passenger_id in list(self._agent_ids):
            if passenger_id not in keep_passenger_ids:
                self.remove_passenger(passenger_id)

    def remove_passenger(self, passenger_id: int) -> None:
        passenger_key = int(passenger_id)
        sim_id = self._agent_ids.pop(passenger_key, None)
        self._agent_targets.pop(passenger_key, None)
        self._agent_target_positions.pop(passenger_key, None)
        self._agent_desired_speeds.pop(passenger_key, None)
        self._last_positions.pop(passenger_key, None)
        self._active_episode_ids.pop(passenger_key, None)
        self._removal_records.pop(passenger_key, None)
        if sim_id is None:
            return
        self._passenger_ids.pop(int(sim_id), None)
        try:
            self._simulation.mark_agent_for_removal(int(sim_id))
        except Exception:
            return

    def place_agent(
        self,
        *,
        passenger_id: int,
        position: tuple[float, float],
        target: tuple[float, float],
        desired_speed_mps: float = 1.2,
    ) -> tuple[float, float]:
        current_position = self.position_for(passenger_id)
        if current_position is not None:
            distance = hypot(current_position[0] - position[0], current_position[1] - position[1])
            if distance <= max(0.01, self.agent_radius):
                self.ensure_agent(
                    passenger_id=passenger_id,
                    position=position,
                    target=target,
                    desired_speed_mps=desired_speed_mps,
                )
                return current_position
            self.remove_passenger(passenger_id)
        return self._add_agent(
            passenger_id=passenger_id,
            position=position,
            target=target,
            desired_speed_mps=desired_speed_mps,
            allow_relocation=True,
        )

    def resolve_placement(
        self,
        *,
        passenger_id: int,
        position: tuple[float, float],
        allow_relocation: bool = True,
    ) -> tuple[float, float]:
        """Resolve a legal coordinate without creating JuPedSim agent state."""

        candidates = (
            self._placement_candidates(position, int(passenger_id))
            if allow_relocation
            else (position,)
        )
        for candidate in candidates:
            safe_position = self._safe_agent_candidate(candidate)
            if safe_position is None:
                continue
            if not allow_relocation and hypot(
                safe_position[0] - position[0],
                safe_position[1] - position[1],
            ) > 1e-6:
                break
            if self._candidate_has_agent_clearance(
                safe_position,
                exclude_passenger_id=int(passenger_id),
            ):
                return safe_position
        qualifier = "near" if allow_relocation else "at"
        raise JuPedSimPlacementBlocked(
            f"JuPedSim could not resolve passenger {passenger_id} {qualifier} {position!r}."
        )

    def ensure_agent(
        self,
        *,
        passenger_id: int,
        position: tuple[float, float],
        target: tuple[float, float],
        desired_speed_mps: float = 1.2,
    ) -> tuple[float, float]:
        passenger_key = int(passenger_id)
        target_key = self._target_key(target)
        target_info = self._journey_for_target(target)
        sim_id = self._agent_ids.get(passenger_key)
        agent = self._agent_for_id(sim_id) if sim_id is not None else None
        if agent is None:
            if sim_id is not None:
                self._forget_agent(passenger_key, int(sim_id))
            return self._add_agent(
                passenger_id=passenger_key,
                position=position,
                target=target,
                desired_speed_mps=desired_speed_mps,
                allow_relocation=False,
            )

        agent_position = (float(agent.position[0]), float(agent.position[1]))
        drift = hypot(agent_position[0] - position[0], agent_position[1] - position[1])
        if drift > max(2.0, self.target_radius * 4.0):
            self.remove_passenger(passenger_key)
            return self._add_agent(
                passenger_id=passenger_key,
                position=position,
                target=target,
                desired_speed_mps=desired_speed_mps,
                allow_relocation=False,
            )

        self._set_desired_speed(agent, desired_speed_mps)
        self._agent_desired_speeds[passenger_key] = float(desired_speed_mps)
        self._last_positions[passenger_key] = agent_position

        if self._agent_targets.get(passenger_key) != target_key:
            self._simulation.switch_agent_journey(
                int(sim_id),
                target_info.journey_id,
                target_info.stage_id,
            )
            self._agent_targets[passenger_key] = target_key
            self._agent_target_positions[passenger_key] = target_info.position
        return agent_position

    def iterate(
        self,
        iterations: int,
        *,
        sample_every_nth_iteration: int | None = None,
        sample_observer: Callable[[int, Mapping[int, tuple[float, float]]], None] | None = None,
    ) -> None:
        sample_every = max(1, int(sample_every_nth_iteration or 1))
        for iteration in range(1, max(1, int(iterations)) + 1):
            if self._simulation.agent_count() <= 0:
                break
            positions_before = self.positions_by_passenger()
            self._simulation.iterate()
            self._capture_removed_agents(positions_before, iteration)
            if sample_observer is not None and iteration % sample_every == 0:
                sample_observer(iteration, self.positions_by_passenger())

    def positions_by_passenger(self) -> dict[int, tuple[float, float]]:
        positions: dict[int, tuple[float, float]] = {}
        for passenger_id in sorted(self._agent_ids):
            position = self.position_for(passenger_id)
            if position is not None:
                positions[int(passenger_id)] = position
        return positions

    def position_for(self, passenger_id: int) -> tuple[float, float] | None:
        passenger_key = int(passenger_id)
        sim_id = self._agent_ids.get(passenger_key)
        agent = self._agent_for_id(sim_id) if sim_id is not None else None
        if agent is None:
            if sim_id is not None:
                self._record_unobserved_removal(passenger_key, int(sim_id))
            return None
        position = (float(agent.position[0]), float(agent.position[1]))
        self._last_positions[passenger_key] = position
        return position

    def episode_ids_by_passenger(self) -> dict[int, str]:
        return dict(self._active_episode_ids)

    def episode_id_for(self, passenger_id: int) -> str | None:
        return self._active_episode_ids.get(int(passenger_id))

    def set_episode_id(self, passenger_id: int, episode_id: str) -> None:
        passenger_key = int(passenger_id)
        if passenger_key not in self._agent_ids:
            raise KeyError(f"passenger {passenger_key} is not active in this walking session")
        if not episode_id:
            raise ValueError("episode_id must be non-empty")
        self._active_episode_ids[passenger_key] = str(episode_id)

    def removal_record_for(
        self,
        passenger_id: int,
        *,
        consume: bool = False,
    ) -> JuPedSimRemovalRecord | None:
        passenger_key = int(passenger_id)
        if consume:
            return self._removal_records.pop(passenger_key, None)
        return self._removal_records.get(passenger_key)

    def _add_agent(
        self,
        *,
        passenger_id: int,
        position: tuple[float, float],
        target: tuple[float, float],
        desired_speed_mps: float = 1.2,
        allow_relocation: bool,
    ) -> tuple[float, float]:
        passenger_key = int(passenger_id)
        target_key = self._target_key(target)
        target_info = self._journey_for_target(target)
        last_error: Exception | None = None
        tried_positions: set[tuple[float, float]] = set()
        candidates = (
            self._placement_candidates(position, passenger_key)
            if allow_relocation
            else (position,)
        )
        for candidate in candidates:
            safe_position = self._safe_agent_candidate(candidate)
            if safe_position is None:
                continue
            if not allow_relocation and hypot(
                safe_position[0] - position[0],
                safe_position[1] - position[1],
            ) > 1e-6:
                raise JuPedSimPlacementBlocked(
                    f"passenger {passenger_key} requires projection from {position!r} "
                    f"to {safe_position!r}"
                )
            candidate_key = (round(safe_position[0], 4), round(safe_position[1], 4))
            if candidate_key in tried_positions:
                continue
            tried_positions.add(candidate_key)
            if not self._candidate_has_agent_clearance(
                safe_position,
                exclude_passenger_id=passenger_key,
            ):
                continue
            try:
                sim_id = int(
                    self._simulation.add_agent(
                        self._adapter._agent_parameters_for_name(
                            self.operational_model,
                            journey_id=target_info.journey_id,
                            stage_id=target_info.stage_id,
                            position=safe_position,
                            target=target_info.position,
                            radius=self.agent_radius,
                            desired_speed=desired_speed_mps,
                        )
                    )
                )
            except Exception as exc:
                last_error = exc
                continue
            self._agent_ids[passenger_key] = sim_id
            self._passenger_ids[sim_id] = passenger_key
            self._agent_targets[passenger_key] = target_key
            self._agent_target_positions[passenger_key] = target_info.position
            self._agent_desired_speeds[passenger_key] = float(desired_speed_mps)
            self._last_positions[passenger_key] = safe_position
            episode_number = self._episode_numbers.get(passenger_key, 0) + 1
            self._episode_numbers[passenger_key] = episode_number
            self._active_episode_ids[passenger_key] = f"{passenger_key}:{episode_number}"
            self._removal_records.pop(passenger_key, None)
            return safe_position

        error_type = RuntimeError if allow_relocation else JuPedSimPlacementBlocked
        qualifier = "near" if allow_relocation else "at"
        raise error_type(
            f"JuPedSim could not place passenger {passenger_key} {qualifier} {position!r}."
        ) from last_error

    @staticmethod
    def _set_desired_speed(agent, desired_speed_mps: float) -> None:
        model = agent.model
        if hasattr(model, "desired_speed"):
            model.desired_speed = float(desired_speed_mps)
            return
        if hasattr(model, "desiredSpeed"):
            model.desiredSpeed = float(desired_speed_mps)

    def _journey_for_target(self, target: tuple[float, float]) -> _JourneyTarget:
        target_key = self._target_key(target)
        existing = self._targets.get(target_key)
        if existing is not None:
            return existing
        stage_position = self._safe_waypoint_position(target)
        stage_id = int(self._simulation.add_waypoint_stage(stage_position, self.target_radius))
        journey_id = int(self._simulation.add_journey(self._jps.JourneyDescription([stage_id])))
        target_info = _JourneyTarget(stage_id=stage_id, journey_id=journey_id, position=stage_position)
        self._targets[target_key] = target_info
        return target_info

    def _target_key(self, target: tuple[float, float]) -> tuple[float, float, float]:
        return (round(float(target[0]), 3), round(float(target[1]), 3), round(self.target_radius, 3))

    def _safe_waypoint_position(self, target: tuple[float, float]) -> tuple[float, float]:
        from shapely import Point

        if not self.geometry.covers(Point(target)):
            raise RuntimeError(f"JuPedSim waypoint target {target!r} is outside the walkable area.")
        return project_to_safe_point(
            self.geometry,
            target,
            clearance=max(0.02, min(self.agent_radius, self.target_radius * 0.25)),
            require_inside=False,
        )

    def _safe_agent_candidate(
        self,
        candidate: tuple[float, float],
    ) -> tuple[float, float] | None:
        from shapely import Point

        safe_position = project_to_safe_point(
            self.geometry,
            candidate,
            clearance=max(0.02, self.agent_radius * 1.05),
            require_inside=False,
        )
        if not self.geometry.covers(Point(safe_position)):
            return None
        return safe_position

    def _candidate_has_agent_clearance(
        self,
        candidate: tuple[float, float],
        *,
        exclude_passenger_id: int | None = None,
    ) -> bool:
        min_distance = max(0.01, self.agent_radius * 2.05)
        return all(
            hypot(
                position[0] - candidate[0],
                position[1] - candidate[1],
            )
            >= min_distance
            for passenger_id, position in self.positions_by_passenger().items()
            if passenger_id != exclude_passenger_id
        )

    def _placement_candidates(
        self,
        position: tuple[float, float],
        passenger_id: int,
    ):
        yield position
        spacing = max(0.35, self.agent_radius * 2.4)
        angle_offset = ((passenger_id * 1103515245) % 6283) / 1000.0
        for ring in range(1, 33):
            count = 8 if ring <= 3 else 16 if ring <= 12 else 24
            distance = spacing * (1.0 + 0.45 * (ring - 1))
            for index in range(count):
                angle = angle_offset + tau * (index / count) + ring * 0.19
                yield (
                    position[0] + cos(angle) * distance,
                    position[1] + sin(angle) * distance,
                )

    def _agent_for_id(self, sim_id: int | None):
        if sim_id is None:
            return None
        try:
            return self._simulation.agent(int(sim_id))
        except Exception:
            return None

    def _forget_agent(self, passenger_id: int, sim_id: int) -> None:
        self._agent_ids.pop(int(passenger_id), None)
        self._agent_targets.pop(int(passenger_id), None)
        self._agent_target_positions.pop(int(passenger_id), None)
        self._agent_desired_speeds.pop(int(passenger_id), None)
        self._last_positions.pop(int(passenger_id), None)
        self._active_episode_ids.pop(int(passenger_id), None)
        self._passenger_ids.pop(int(sim_id), None)

    def _capture_removed_agents(
        self,
        positions_before: Mapping[int, tuple[float, float]],
        iteration: int,
    ) -> None:
        live_sim_ids = {int(agent.id) for agent in self._simulation.agents()}
        for passenger_id, sim_id in list(self._agent_ids.items()):
            if int(sim_id) in live_sim_ids:
                continue
            last_position = positions_before.get(
                passenger_id,
                self._last_positions.get(passenger_id),
            )
            self._record_simulation_removal(
                passenger_id,
                int(sim_id),
                last_position=last_position,
                iteration=iteration,
            )

    def _record_simulation_removal(
        self,
        passenger_id: int,
        sim_id: int,
        *,
        last_position: tuple[float, float] | None,
        iteration: int,
    ) -> None:
        target = self._agent_target_positions.get(passenger_id)
        desired_speed = self._agent_desired_speeds.get(passenger_id, 0.0)
        episode_id = self._active_episode_ids.get(passenger_id, f"{passenger_id}:unknown")
        position = last_position or self._last_positions.get(passenger_id)
        if position is None:
            position = target or (0.0, 0.0)
        can_reach_stage = target is not None and hypot(
            target[0] - position[0],
            target[1] - position[1],
        ) <= self.target_radius + desired_speed * self.dt_seconds + 1e-7
        self._removal_records[passenger_id] = JuPedSimRemovalRecord(
            passenger_id=passenger_id,
            reason="completed_final_waypoint" if can_reach_stage else "unexpected_disappearance",
            last_authoritative_position=position,
            reached=bool(can_reach_stage),
            occurred_after_seconds=float(iteration) * self.dt_seconds,
            last_position_after_seconds=float(max(0, iteration - 1)) * self.dt_seconds,
            episode_id=episode_id,
        )
        self._forget_agent(passenger_id, sim_id)

    def _record_unobserved_removal(self, passenger_id: int, sim_id: int) -> None:
        episode_id = self._active_episode_ids.get(passenger_id, f"{passenger_id}:unknown")
        position = self._last_positions.get(passenger_id, (0.0, 0.0))
        self._removal_records[passenger_id] = JuPedSimRemovalRecord(
            passenger_id=passenger_id,
            reason="unobserved_disappearance",
            last_authoritative_position=position,
            reached=False,
            occurred_after_seconds=0.0,
            last_position_after_seconds=0.0,
            episode_id=episode_id,
        )
        self._forget_agent(passenger_id, sim_id)


class JuPedSimAdapter:
    """Optional bridge for JuPedSim-based continuous pedestrian motion.

    The Mesa model owns the station process and event state. This adapter is the
    boundary where local walking segments can be delegated to JuPedSim once the
    package is installed in the runtime.
    """

    def __init__(self) -> None:
        self._jps: Any | None = None
        self._error: Exception | None = None
        try:
            import jupedsim as jps  # type: ignore

            self._jps = jps
        except Exception as exc:  # pragma: no cover - depends on optional install
            self._error = exc

    @property
    def status(self) -> JuPedSimStatus:
        if self._jps is None:
            reason = (
                f"{type(self._error).__name__}: {self._error}" if self._error else "not imported"
            )
            return JuPedSimStatus(False, f"JuPedSim unavailable ({reason}).")
        version = getattr(self._jps, "__version__", None)
        return JuPedSimStatus(True, "JuPedSim available for local walking segments.", version)

    def build_walkable_area(self, width: float, height: float, walkable_area=None):
        if self._jps is None:
            raise RuntimeError(self.status.message)
        if walkable_area is not None:
            return walkable_area
        from shapely import Polygon

        return Polygon([(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)])

    def create_walking_session(
        self,
        *,
        width: float,
        height: float,
        walkable_area,
        operational_model: str,
        agent_radius: float,
        target_radius: float,
        dt_seconds: float = 0.01,
    ) -> JuPedSimWalkingSession:
        return JuPedSimWalkingSession(
            self,
            width=width,
            height=height,
            walkable_area=walkable_area,
            operational_model=operational_model,
            agent_radius=agent_radius,
            target_radius=target_radius,
            dt_seconds=dt_seconds,
        )

    simulate_walk_segment = simulate_walk_segment
    simulate_walk_tick = simulate_walk_tick

    def _exit_stage_polygon(self, geometry, target: tuple[float, float], radius: float):
        from shapely import Point

        target_point = Point(target)
        if not geometry.covers(target_point):
            raise RuntimeError(f"JuPedSim target point {target!r} is outside the walkable area.")
        for candidate_radius in (radius, radius * 0.7, radius * 0.45, radius * 0.25, 0.05):
            exit_polygon = target_point.buffer(candidate_radius, resolution=8)
            if geometry.covers(exit_polygon):
                return exit_polygon
        return target_point.buffer(0.02, resolution=8)

    def _safe_agent_position(self, geometry, position: tuple[float, float], radius: float):
        from shapely import Point

        point = Point(position)
        if not geometry.covers(point):
            raise RuntimeError(
                f"JuPedSim agent position {position!r} is outside the walkable area."
            )

        return project_to_safe_point(
            geometry,
            position,
            clearance=max(0.02, radius * 1.05),
            require_inside=True,
        )

    def _model_for_name(self, operational_model: str):
        if self._jps is None:
            raise RuntimeError(self.status.message)
        jps = self._jps
        if operational_model == "collision_free_speed":
            return jps.CollisionFreeSpeedModel()
        if operational_model == "social_force":
            return jps.SocialForceModel()
        raise ValueError(
            f"Unsupported JuPedSim operational model {operational_model!r}. "
            "Use 'collision_free_speed' or 'social_force'."
        )

    def _agent_parameters_for_name(
        self,
        operational_model: str,
        *,
        journey_id: int,
        stage_id: int,
        position: tuple[float, float],
        target: tuple[float, float],
        radius: float,
        desired_speed: float = 1.2,
    ):
        if self._jps is None:
            raise RuntimeError(self.status.message)
        jps = self._jps
        if operational_model == "collision_free_speed":
            return jps.CollisionFreeSpeedModelAgentParameters(
                journey_id=journey_id,
                stage_id=stage_id,
                position=position,
                radius=radius,
                desired_speed=desired_speed,
            )
        if operational_model == "social_force":
            return jps.SocialForceModelAgentParameters(
                journey_id=journey_id,
                stage_id=stage_id,
                position=position,
                orientation=_unit_vector(position, target),
                radius=radius,
                desired_speed=desired_speed,
            )
        raise ValueError(
            f"Unsupported JuPedSim operational model {operational_model!r}. "
            "Use 'collision_free_speed' or 'social_force'."
        )


def _unit_vector(
    source: tuple[float, float],
    target: tuple[float, float],
) -> tuple[float, float]:
    dx = target[0] - source[0]
    dy = target[1] - source[1]
    length = hypot(dx, dy)
    if length <= 1e-9:
        return (1.0, 0.0)
    return (dx / length, dy / length)
