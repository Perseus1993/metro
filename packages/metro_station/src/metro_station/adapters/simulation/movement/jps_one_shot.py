from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .jps_adapter import JuPedSimAdapter


def simulate_walk_segment(
    self: JuPedSimAdapter,
    *,
    starts: list[tuple[float, float]],
    target: tuple[float, float],
    width: float,
    height: float,
    max_iterations: int = 300,
    walkable_area=None,
    operational_model: str = "collision_free_speed",
    dt_seconds: float = 0.01,
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
        dt=dt_seconds,
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
    self: JuPedSimAdapter,
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
    dt_seconds: float = 0.01,
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
        dt=dt_seconds,
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
