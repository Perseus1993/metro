from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Any

from ..station.geometry import project_to_safe_point


@dataclass(frozen=True)
class JuPedSimStatus:
    available: bool
    message: str
    version: str | None = None


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
