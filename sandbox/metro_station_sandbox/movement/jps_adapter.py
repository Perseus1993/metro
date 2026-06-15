from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, sin, tau
from typing import Any

from ..station.geometry import project_to_safe_point


@dataclass(frozen=True)
class JuPedSimStatus:
    available: bool
    message: str
    version: str | None = None


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
    ) -> None:
        if adapter._jps is None:
            raise RuntimeError(adapter.status.message)
        self._adapter = adapter
        self._jps = adapter._jps
        self.geometry = adapter.build_walkable_area(width, height, walkable_area)
        self.operational_model = operational_model
        self.agent_radius = float(agent_radius)
        self.target_radius = float(target_radius)
        self._simulation = self._jps.Simulation(
            model=adapter._model_for_name(operational_model),
            geometry=self.geometry,
        )
        self._targets: dict[tuple[float, float, float], _JourneyTarget] = {}
        self._agent_ids: dict[int, int] = {}
        self._passenger_ids: dict[int, int] = {}
        self._agent_targets: dict[int, tuple[float, float, float]] = {}

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
    ) -> tuple[float, float]:
        current_position = self.position_for(passenger_id)
        if current_position is not None:
            distance = hypot(current_position[0] - position[0], current_position[1] - position[1])
            if distance <= max(0.01, self.agent_radius):
                self.ensure_agent(passenger_id=passenger_id, position=position, target=target)
                return current_position
            self.remove_passenger(passenger_id)
        return self._add_agent(passenger_id=passenger_id, position=position, target=target)

    def ensure_agent(
        self,
        *,
        passenger_id: int,
        position: tuple[float, float],
        target: tuple[float, float],
    ) -> tuple[float, float]:
        passenger_key = int(passenger_id)
        target_key = self._target_key(target)
        target_info = self._journey_for_target(target)
        sim_id = self._agent_ids.get(passenger_key)
        agent = self._agent_for_id(sim_id) if sim_id is not None else None
        if agent is None:
            if sim_id is not None:
                self._forget_agent(passenger_key, int(sim_id))
            return self._add_agent(passenger_id=passenger_key, position=position, target=target)

        agent_position = (float(agent.position[0]), float(agent.position[1]))
        drift = hypot(agent_position[0] - position[0], agent_position[1] - position[1])
        if drift > max(2.0, self.target_radius * 4.0):
            self.remove_passenger(passenger_key)
            return self._add_agent(passenger_id=passenger_key, position=position, target=target)

        if self._agent_targets.get(passenger_key) != target_key:
            self._simulation.switch_agent_journey(
                int(sim_id),
                target_info.journey_id,
                target_info.stage_id,
            )
            self._agent_targets[passenger_key] = target_key
        return agent_position

    def iterate(self, iterations: int) -> None:
        for _ in range(max(1, int(iterations))):
            if self._simulation.agent_count() <= 0:
                break
            self._simulation.iterate()
        self._drop_missing_agents()

    def position_for(self, passenger_id: int) -> tuple[float, float] | None:
        passenger_key = int(passenger_id)
        sim_id = self._agent_ids.get(passenger_key)
        agent = self._agent_for_id(sim_id) if sim_id is not None else None
        if agent is None:
            if sim_id is not None:
                self._forget_agent(passenger_key, int(sim_id))
            return None
        return (float(agent.position[0]), float(agent.position[1]))

    def _add_agent(
        self,
        *,
        passenger_id: int,
        position: tuple[float, float],
        target: tuple[float, float],
    ) -> tuple[float, float]:
        passenger_key = int(passenger_id)
        target_key = self._target_key(target)
        target_info = self._journey_for_target(target)
        last_error: Exception | None = None
        for candidate in self._placement_candidates(position, passenger_key):
            safe_position = self._safe_agent_candidate(candidate)
            if safe_position is None:
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
                        )
                    )
                )
            except Exception as exc:
                last_error = exc
                continue
            self._agent_ids[passenger_key] = sim_id
            self._passenger_ids[sim_id] = passenger_key
            self._agent_targets[passenger_key] = target_key
            return safe_position

        raise RuntimeError(
            f"JuPedSim could not place passenger {passenger_key} near {position!r}."
        ) from last_error

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

    def _placement_candidates(
        self,
        position: tuple[float, float],
        passenger_id: int,
    ):
        yield position
        spacing = max(0.35, self.agent_radius * 2.4)
        angle_offset = ((passenger_id * 1103515245) % 6283) / 1000.0
        for ring in range(1, 13):
            count = 8 if ring <= 3 else 16
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
        self._passenger_ids.pop(int(sim_id), None)

    def _drop_missing_agents(self) -> None:
        live_sim_ids = {int(agent.id) for agent in self._simulation.agents()}
        for passenger_id, sim_id in list(self._agent_ids.items()):
            if int(sim_id) not in live_sim_ids:
                self._forget_agent(passenger_id, int(sim_id))


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
    ) -> JuPedSimWalkingSession:
        return JuPedSimWalkingSession(
            self,
            width=width,
            height=height,
            walkable_area=walkable_area,
            operational_model=operational_model,
            agent_radius=agent_radius,
            target_radius=target_radius,
        )

    def simulate_walk_segment(
        self,
        *,
        starts: list[tuple[float, float]],
        target: tuple[float, float],
        width: float,
        height: float,
        max_iterations: int = 300,
        walkable_area=None,
        operational_model: str = "collision_free_speed",
    ) -> list[tuple[float, float]]:
        """Run a small JuPedSim segment and return final positions.

        This is intentionally narrow: it lets the sandbox swap the hand-written
        movement of one local segment for JuPedSim without moving train events,
        queues, or data loading out of Mesa.
        """

        if self._jps is None:
            raise RuntimeError(self.status.message)

        jps = self._jps
        geometry = self.build_walkable_area(width, height, walkable_area)
        exit_polygon = self._exit_stage_polygon(geometry, target, 0.4)
        simulation = jps.Simulation(
            model=self._model_for_name(operational_model),
            geometry=geometry,
        )
        exit_id = simulation.add_exit_stage(exit_polygon)
        journey = jps.JourneyDescription([exit_id])
        journey_id = simulation.add_journey(journey)

        agent_ids = []
        for position in starts:
            safe_position = self._safe_agent_position(geometry, position, 0.18)
            agent_ids.append(
                simulation.add_agent(
                    self._agent_parameters_for_name(
                        operational_model,
                        journey_id=journey_id,
                        stage_id=exit_id,
                        position=safe_position,
                        target=target,
                        radius=0.18,
                    )
                )
            )

        iterations = 0
        while simulation.agent_count() > 0 and iterations < max_iterations:
            simulation.iterate()
            iterations += 1

        active_positions = {agent.id: agent.position for agent in simulation.agents()}
        return [
            (
                float(active_positions.get(agent_id, target)[0]),
                float(active_positions.get(agent_id, target)[1]),
            )
            for agent_id in agent_ids
        ]

    def simulate_walk_tick(
        self,
        *,
        starts: list[tuple[float, float]],
        target: tuple[float, float],
        width: float,
        height: float,
        iterations: int,
        radius: float = 0.18,
        target_radius: float = 0.45,
        walkable_area=None,
        operational_model: str = "collision_free_speed",
    ) -> list[tuple[float, float]]:
        """Run a short JuPedSim micro-step and return updated positions."""

        if self._jps is None:
            raise RuntimeError(self.status.message)
        if not starts:
            return []

        jps = self._jps
        geometry = self.build_walkable_area(width, height, walkable_area)
        tx, ty = target
        exit_polygon = self._exit_stage_polygon(geometry, (tx, ty), target_radius)
        simulation = jps.Simulation(
            model=self._model_for_name(operational_model),
            geometry=geometry,
        )
        exit_id = simulation.add_exit_stage(exit_polygon)
        journey = jps.JourneyDescription([exit_id])
        journey_id = simulation.add_journey(journey)

        agent_ids = []
        for position in starts:
            safe_position = self._safe_agent_position(geometry, position, radius)
            agent_ids.append(
                simulation.add_agent(
                    self._agent_parameters_for_name(
                        operational_model,
                        journey_id=journey_id,
                        stage_id=exit_id,
                        position=safe_position,
                        target=target,
                        radius=radius,
                    )
                )
            )

        for _ in range(max(1, iterations)):
            if simulation.agent_count() <= 0:
                break
            simulation.iterate()

        active_positions = {agent.id: agent.position for agent in simulation.agents()}
        return [
            (
                float(active_positions.get(agent_id, target)[0]),
                float(active_positions.get(agent_id, target)[1]),
            )
            for agent_id in agent_ids
        ]

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
                desired_speed=1.2,
            )
        if operational_model == "social_force":
            return jps.SocialForceModelAgentParameters(
                journey_id=journey_id,
                stage_id=stage_id,
                position=position,
                orientation=_unit_vector(position, target),
                radius=radius,
                desired_speed=1.2,
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
