from __future__ import annotations

import math
import random

import jupedsim as jps
from shapely.geometry import Point, Polygon

from ..queue_runtime import NativeQueueRuntime
from .constants import STUCK_RECOVERY_MAX_PER_TRACK, STUCK_RECOVERY_SECONDS
from .replanning import stage_target_points
from .types import (
    AgentProgress,
    SoftReleaseTargets,
    StageAdvanceTargets,
    StageRegistry,
)


def recover_stalled_agents(
    *,
    sim: jps.Simulation,
    time: float,
    progress: dict[int, AgentProgress],
    stage_advance_targets: StageAdvanceTargets,
    soft_release_targets: SoftReleaseTargets,
    stage_registry: StageRegistry,
    geometry: Polygon,
    sim_to_track: dict[int, int],
    last_positions: dict[int, tuple[float, float]],
    recovery_counts: dict[int, int],
    runtimes: list[NativeQueueRuntime],
    rng: random.Random,
) -> list[dict[str, object]]:
    enqueued_ids = _enqueued_agent_ids(sim, runtimes)
    events: list[dict[str, object]] = []

    for agent in list(sim.agents()):
        sim_id = int(agent.id)
        if sim_id in enqueued_ids:
            continue
        previous = progress.get(sim_id)
        if previous is None:
            continue

        stuck_seconds = time - previous.last_progress_time
        if stuck_seconds < STUCK_RECOVERY_SECONDS:
            continue

        track_id = sim_to_track.get(sim_id)
        if track_id is None:
            continue

        stage_id = int(agent.stage_id)
        journey_id = int(agent.journey_id)
        stage_info = stage_registry.get(stage_id)
        recovery_count = recovery_counts.get(track_id, 0)
        if recovery_count >= STUCK_RECOVERY_MAX_PER_TRACK:
            _remove_agent(
                sim=sim,
                sim_id=sim_id,
                progress=progress,
                sim_to_track=sim_to_track,
                last_positions=last_positions,
            )
            events.append(
                {
                    "time": round(time, 2),
                    "type": "stuck_recovery_remove",
                    "reason": "max_recovery_attempts",
                    "sim_id": sim_id,
                    "track_id": track_id,
                    "stage_id": stage_id,
                    "location": stage_info.label if stage_info is not None else f"stage_{stage_id}",
                    "stuck_seconds": round(stuck_seconds, 2),
                    "recoveries": recovery_count,
                }
            )
            continue

        target = _recovery_target(
            stage_id=stage_id,
            journey_id=journey_id,
            stage_advance_targets=stage_advance_targets,
            soft_release_targets=soft_release_targets,
            stage_registry=stage_registry,
        )
        if target is None:
            continue

        target_stage, target_position, mode = target
        recovery_position = _safe_recovery_position(target_position, geometry, rng)
        if recovery_position is None:
            continue

        replacement_id = _replace_agent(
            sim=sim,
            agent=agent,
            target_stage=target_stage,
            recovery_position=recovery_position,
        )
        if replacement_id is None:
            continue

        sim.mark_agent_for_removal(sim_id)
        sim_to_track.pop(sim_id, None)
        sim_to_track[replacement_id] = track_id
        last_positions.pop(sim_id, None)
        last_positions[replacement_id] = recovery_position
        progress.pop(sim_id, None)
        progress[replacement_id] = AgentProgress(
            int(target_stage),
            journey_id,
            recovery_position,
            time,
        )
        recovery_counts[track_id] = recovery_count + 1
        events.append(
            {
                "time": round(time, 2),
                "type": "stuck_recovery_reposition",
                "reason": "movement_stalled",
                "mode": mode,
                "sim_id": sim_id,
                "replacement_sim_id": replacement_id,
                "track_id": track_id,
                "from_stage": stage_id,
                "to_stage": int(target_stage),
                "location": stage_info.label if stage_info is not None else f"stage_{stage_id}",
                "stuck_seconds": round(stuck_seconds, 2),
                "recoveries": recovery_count + 1,
            }
        )

    return events


def _recovery_target(
    *,
    stage_id: int,
    journey_id: int,
    stage_advance_targets: StageAdvanceTargets,
    soft_release_targets: SoftReleaseTargets,
    stage_registry: StageRegistry,
) -> tuple[int, tuple[float, float], str] | None:
    stage_info = stage_registry.get(stage_id)
    if stage_info is not None and stage_info.kind == "exit":
        return None

    soft_targets = soft_release_targets.get((stage_id, journey_id))
    if soft_targets:
        target_stage = int(soft_targets[0])
        point = _first_stage_point(stage_registry, target_stage)
        if point is not None:
            return target_stage, point, "service_release_snap"

    if stage_info is not None and stage_info.point_m is not None:
        return stage_id, stage_info.point_m, "stage_target_snap"

    advance_targets = stage_advance_targets.get((stage_id, journey_id))
    if advance_targets:
        target_stage = int(advance_targets[0])
        point = _first_stage_point(stage_registry, target_stage)
        if point is not None:
            return target_stage, point, "advance_target_snap"

    return None


def _first_stage_point(
    stage_registry: StageRegistry,
    stage_id: int,
) -> tuple[float, float] | None:
    points = stage_target_points(stage_registry, stage_id)
    if points:
        return points[0]
    return None


def _replace_agent(
    *,
    sim: jps.Simulation,
    agent: object,
    target_stage: int,
    recovery_position: tuple[float, float],
) -> int | None:
    model = agent.model
    try:
        return int(
            sim.add_agent(
                jps.CollisionFreeSpeedModelV3AgentParameters(
                    position=recovery_position,
                    journey_id=int(agent.journey_id),
                    stage_id=int(target_stage),
                    radius=float(model.radius),
                    desired_speed=float(model.desired_speed),
                    time_gap=float(model.time_gap),
                    strength_neighbor_repulsion=float(model.strength_neighbor_repulsion),
                    range_neighbor_repulsion=float(model.range_neighbor_repulsion),
                    strength_geometry_repulsion=float(model.strength_geometry_repulsion),
                    range_geometry_repulsion=float(model.range_geometry_repulsion),
                    agent_buffer=float(model.agent_buffer),
                )
            )
        )
    except Exception:
        return None


def _safe_recovery_position(
    position: tuple[float, float],
    geometry: Polygon,
    rng: random.Random,
) -> tuple[float, float] | None:
    if geometry.covers(Point(position)):
        return position
    for radius in (0.2, 0.45, 0.8, 1.2):
        for _ in range(12):
            angle = rng.uniform(0.0, math.tau)
            candidate = (
                position[0] + math.cos(angle) * radius,
                position[1] + math.sin(angle) * radius,
            )
            if geometry.covers(Point(candidate)):
                return candidate
    return None


def _remove_agent(
    *,
    sim: jps.Simulation,
    sim_id: int,
    progress: dict[int, AgentProgress],
    sim_to_track: dict[int, int],
    last_positions: dict[int, tuple[float, float]],
) -> None:
    sim.mark_agent_for_removal(sim_id)
    progress.pop(sim_id, None)
    sim_to_track.pop(sim_id, None)
    last_positions.pop(sim_id, None)


def _enqueued_agent_ids(
    sim: jps.Simulation,
    runtimes: list[NativeQueueRuntime],
) -> set[int]:
    enqueued: set[int] = set()
    for runtime in runtimes:
        enqueued.update(int(agent_id) for agent_id in sim.get_stage(runtime.stage_id).enqueued())
    return enqueued
