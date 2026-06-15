from __future__ import annotations

from collections.abc import Iterable
import math
import random

import jupedsim as jps
from shapely.geometry import LineString, Polygon

from ..field_routing import QueueFieldCandidate
from ..floor_field import GridFloorField
from ..queue_runtime import NativeQueueRuntime
from .constants import (
    QUEUE_ATTRACTIVENESS_FIELD,
    QUEUE_FIELD_DENSITY_RADIUS_CELLS,
    QUEUE_FIELD_DENSITY_WEIGHT,
    QUEUE_FIELD_SWITCHABLE_PREFIXES,
    QUEUE_FIELD_SWITCHING_ENABLED,
    QUEUE_REPLAN_MIN_IMPROVEMENT,
    QUEUE_TARGET_REPLAN_STALL_SECONDS,
    STAGE_REPLAN_DISTANCE_COST,
    STAGE_REPLAN_LOAD_COST,
    STAGE_REPLAN_MIN_DELTA_M,
    STAGE_REPLAN_QUEUE_COST,
    STAGE_REPLAN_STALL_SECONDS,
)
from .types import (
    AgentProgress,
    QueueDistanceFields,
    QueueReplanTargets,
    StageAdvanceTargets,
    StageInfo,
    StageRegistry,
)


def stage_target_points(
    stage_registry: StageRegistry,
    stage_id: int,
) -> tuple[tuple[float, float], ...]:
    stage_info = stage_registry.get(stage_id)
    if stage_info is None:
        return ()
    if stage_info.slots_m:
        return stage_info.slots_m[:4]
    if stage_info.point_m is not None:
        return (stage_info.point_m,)
    return ()


def stage_reachable_from_position(
    *,
    position: tuple[float, float],
    stage_id: int,
    stage_registry: StageRegistry,
    geometry: Polygon,
) -> bool:
    points = stage_target_points(stage_registry, stage_id)
    if not points:
        return True
    return any(geometry.covers(LineString([position, point])) for point in points)


def reachable_release_targets(
    *,
    position: tuple[float, float],
    targets: tuple[int, ...],
    stage_registry: StageRegistry,
    geometry: Polygon,
) -> tuple[int, ...]:
    reachable: list[int] = []
    for stage_id in targets:
        points = stage_target_points(stage_registry, stage_id)
        if not points:
            reachable.append(stage_id)
            continue
        if any(geometry.covers(LineString([position, point])) for point in points):
            reachable.append(stage_id)
    return tuple(reachable)


def stage_load_counts(sim: jps.Simulation, stage_ids: tuple[int, ...]) -> dict[int, int]:
    counts = {int(stage_id): 0 for stage_id in stage_ids}
    for agent in sim.agents():
        stage_id = int(agent.stage_id)
        if stage_id in counts:
            counts[stage_id] += 1
    return counts


def choose_least_loaded_stage(sim: jps.Simulation, stage_ids: tuple[int, ...]) -> int:
    if len(stage_ids) == 1:
        return int(stage_ids[0])
    counts = stage_load_counts(sim, stage_ids)
    return min(counts, key=lambda stage_id: (counts[stage_id], stage_id))


def stage_reference_distance(
    position: tuple[float, float],
    stage_info: StageInfo | None,
) -> float:
    if stage_info is None:
        return 0.0
    points = stage_target_points({stage_info.stage_id: stage_info}, stage_info.stage_id)
    if not points:
        return 0.0
    return min(math.hypot(position[0] - point[0], position[1] - point[1]) for point in points)


def stage_replan_cost(
    *,
    position: tuple[float, float],
    stage_info: StageInfo | None,
    load: int,
) -> tuple[float, float]:
    distance = stage_reference_distance(position, stage_info)
    queue_cost = (
        STAGE_REPLAN_QUEUE_COST if stage_info is not None and stage_info.kind == "queue" else 0.0
    )
    cost = distance * STAGE_REPLAN_DISTANCE_COST + load * STAGE_REPLAN_LOAD_COST + queue_cost
    return cost, distance


def stage_replan_diagnostics(
    *,
    sim: jps.Simulation,
    stage_ids: tuple[int, ...],
    stage_registry: StageRegistry,
    position: tuple[float, float],
) -> list[dict[str, object]]:
    stage_ids = tuple(int(stage_id) for stage_id in stage_ids)
    if len(stage_ids) == 1:
        stage_id = stage_ids[0]
        info = stage_registry.get(stage_id)
        return [
            {
                "stage_id": stage_id,
                "label": info.label if info is not None else f"stage_{stage_id}",
                "kind": info.kind if info is not None else "unknown",
                "load": 0,
                "distance_m": 0.0,
                "cost": 0.0,
            }
        ]

    loads = stage_load_counts(sim, stage_ids)
    diagnostics: list[dict[str, object]] = []
    for stage_id in stage_ids:
        info = stage_registry.get(stage_id)
        cost, distance = stage_replan_cost(
            position=position,
            stage_info=info,
            load=loads.get(stage_id, 0),
        )
        diagnostics.append(
            {
                "stage_id": stage_id,
                "label": info.label if info is not None else f"stage_{stage_id}",
                "kind": info.kind if info is not None else "unknown",
                "load": loads.get(stage_id, 0),
                "distance_m": round(distance, 3),
                "cost": round(cost, 3),
            }
        )
    diagnostics.sort(key=lambda item: (float(item["cost"]), int(item["stage_id"])))
    return diagnostics


def reachable_advance_targets(
    *,
    position: tuple[float, float],
    targets: tuple[int, ...],
    stage_registry: StageRegistry,
    geometry: Polygon,
) -> tuple[int, ...]:
    reachable: list[int] = []
    for stage_id in targets:
        stage_info = stage_registry.get(stage_id)
        if stage_info is None:
            reachable.append(stage_id)
            continue
        if stage_info.kind == "queue":
            if not stage_info.slots_m:
                continue
            nearest_slots = sorted(
                stage_info.slots_m,
                key=lambda slot: math.hypot(position[0] - slot[0], position[1] - slot[1]),
            )[:6]
            if not any(
                math.hypot(position[0] - slot[0], position[1] - slot[1]) <= 10.0
                and geometry.covers(LineString([position, slot]))
                for slot in nearest_slots
            ):
                continue
            reachable.append(stage_id)
            continue
        if stage_info.kind == "exit" and stage_info.point_m is not None:
            distance = math.hypot(
                position[0] - stage_info.point_m[0],
                position[1] - stage_info.point_m[1],
            )
            if distance > max(4.0, (stage_info.radius_m or 0.0) * 1.4):
                continue
            if not geometry.covers(LineString([position, stage_info.point_m])):
                continue
        if stage_info.kind == "waypoint" and stage_info.point_m is not None:
            distance = math.hypot(
                position[0] - stage_info.point_m[0],
                position[1] - stage_info.point_m[1],
            )
            reach_radius = max(5.0, (stage_info.radius_m or 0.0) * 2.2)
            if distance > reach_radius:
                continue
            if not geometry.covers(LineString([position, stage_info.point_m])):
                continue
        reachable.append(stage_id)
    return tuple(reachable)


def queue_stage_reachable_from_position(
    *,
    position: tuple[float, float],
    stage_info: StageInfo | None,
    geometry: Polygon,
) -> bool:
    if stage_info is None:
        return False
    points = stage_target_points({stage_info.stage_id: stage_info}, stage_info.stage_id)
    if not points:
        return True
    nearest_points = sorted(
        points,
        key=lambda point: math.hypot(position[0] - point[0], position[1] - point[1]),
    )[:8]
    return any(geometry.covers(LineString([position, point])) for point in nearest_points)


def queue_field_candidates(
    *,
    sim: jps.Simulation,
    position: tuple[float, float],
    current_stage_id: int,
    candidate_stage_ids: tuple[int, ...],
    stage_registry: StageRegistry,
    runtime_by_stage: dict[int, NativeQueueRuntime],
    geometry: Polygon,
    queue_distance_fields: QueueDistanceFields,
) -> tuple[QueueFieldCandidate, ...]:
    loads = stage_load_counts(sim, candidate_stage_ids)
    candidates: list[QueueFieldCandidate] = []
    for stage_id in candidate_stage_ids:
        stage_info = stage_registry.get(stage_id)
        runtime = runtime_by_stage.get(stage_id)
        if stage_info is None or stage_info.kind != "queue":
            continue
        distance_field = queue_distance_fields.get(stage_id)
        if distance_field is not None:
            field_cost = distance_field.cost_at(position)
            reachable = math.isfinite(field_cost)
            distance_m = field_cost
        else:
            distance_m = stage_reference_distance(position, stage_info)
            reachable = queue_stage_reachable_from_position(
                position=position,
                stage_info=stage_info,
                geometry=geometry,
            )
        candidates.append(
            QueueFieldCandidate(
                stage_id=stage_id,
                facility=stage_info.facility,
                distance_m=distance_m,
                load=loads.get(stage_id, 0),
                service_interval_s=runtime.service_interval if runtime is not None else 0.0,
                current=stage_id == current_stage_id,
                reachable=reachable,
            )
        )
    return tuple(candidates)


def queue_field_score_payload(scores: tuple[object, ...]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for score in scores:
        payload.append(
            {
                "stage_id": score.stage_id,
                "facility": score.facility,
                "reachable": score.reachable,
                "current": score.current,
                "distance_m": round(score.distance_m, 3),
                "load": score.load,
                "service_interval_s": round(score.service_interval_s, 3),
                "cost": round(score.cost, 3) if math.isfinite(score.cost) else "inf",
            }
        )
    return payload


def queue_field_stage_is_enabled(runtime: NativeQueueRuntime | None) -> bool:
    if runtime is None:
        return False
    return not (runtime.name.startswith("entry_gate") or runtime.name.startswith("exit_gate"))


def queue_field_switching_is_enabled(runtime: NativeQueueRuntime | None) -> bool:
    if runtime is None or not QUEUE_FIELD_SWITCHING_ENABLED:
        return False
    return runtime.name.startswith(QUEUE_FIELD_SWITCHABLE_PREFIXES)


def active_queue_field_stage_ids(
    *,
    sim: jps.Simulation,
    queue_replan_targets: QueueReplanTargets,
    runtime_by_stage: dict[int, NativeQueueRuntime],
) -> tuple[int, ...]:
    active_options: set[int] = set()
    for agent in sim.agents():
        stage_id = int(agent.stage_id)
        journey_id = int(agent.journey_id)
        runtime = runtime_by_stage.get(stage_id)
        if not queue_field_stage_is_enabled(runtime):
            continue
        options = queue_replan_targets.get((stage_id, journey_id))
        if not options:
            continue
        active_options.update(options)
    return tuple(sorted(active_options))


def refresh_queue_distance_fields(
    *,
    sim: jps.Simulation,
    grid: GridFloorField,
    stage_registry: StageRegistry,
    queue_replan_targets: QueueReplanTargets,
    runtime_by_stage: dict[int, NativeQueueRuntime],
) -> QueueDistanceFields:
    stage_ids = active_queue_field_stage_ids(
        sim=sim,
        queue_replan_targets=queue_replan_targets,
        runtime_by_stage=runtime_by_stage,
    )
    if not stage_ids:
        return {}
    positions = [(float(agent.position[0]), float(agent.position[1])) for agent in sim.agents()]
    density_penalty = grid.density_penalty(
        positions,
        radius_cells=QUEUE_FIELD_DENSITY_RADIUS_CELLS,
        weight=QUEUE_FIELD_DENSITY_WEIGHT,
    )
    fields: QueueDistanceFields = {}
    for stage_id in stage_ids:
        stage_info = stage_registry.get(stage_id)
        if stage_info is None or stage_info.kind != "queue" or not stage_info.slots_m:
            continue
        fields[stage_id] = grid.distance_field(
            stage_info.slots_m,
            dynamic_penalty=density_penalty,
        )
    return fields


def replan_stalled_queue_target(
    *,
    sim: jps.Simulation,
    sim_id: int,
    journey_id: int,
    stage_id: int,
    position: tuple[float, float],
    stuck_seconds: float,
    queue_replan_targets: QueueReplanTargets,
    stage_registry: StageRegistry,
    runtime_by_stage: dict[int, NativeQueueRuntime],
    geometry: Polygon,
    queue_distance_fields: QueueDistanceFields,
    rng: random.Random,
) -> tuple[int, dict[str, object]] | None:
    options = queue_replan_targets.get((stage_id, journey_id))
    if not options:
        return None
    runtime = runtime_by_stage.get(stage_id)
    if not queue_field_stage_is_enabled(runtime):
        return None
    if sim_id in set(int(agent_id) for agent_id in sim.get_stage(stage_id).enqueued()):
        return None
    if sim_id in runtime.virtual_queue_order:
        return None

    candidates = queue_field_candidates(
        sim=sim,
        position=position,
        current_stage_id=stage_id,
        candidate_stage_ids=options,
        stage_registry=stage_registry,
        runtime_by_stage=runtime_by_stage,
        geometry=geometry,
        queue_distance_fields=queue_distance_fields,
    )
    scores = QUEUE_ATTRACTIVENESS_FIELD.rank(candidates)
    choice = QUEUE_ATTRACTIVENESS_FIELD.choose(candidates, rng)
    if choice is None:
        return None
    current_score = next((score for score in scores if score.stage_id == stage_id), None)
    switching_enabled = queue_field_switching_is_enabled(runtime)
    should_switch = (
        switching_enabled
        and choice.stage_id != stage_id
        and current_score is not None
        and choice.cost + QUEUE_REPLAN_MIN_IMPROVEMENT < current_score.cost
    )

    next_stage = choice.stage_id if should_switch else stage_id
    if should_switch:
        sim.switch_agent_journey(sim_id, journey_id, choice.stage_id)

    current_info = stage_registry.get(stage_id)
    return next_stage, {
        "time": None,
        "type": "queue_field_replan",
        "reason": "targeting_stalled",
        "policy": "queue_attractiveness_field_logit",
        "distance_model": "grid_dynamic_floor_field"
        if queue_distance_fields
        else "euclidean_distance",
        "sim_id": sim_id,
        "from_stage": stage_id,
        "to_stage": next_stage,
        "suggested_stage": choice.stage_id,
        "changed": should_switch,
        "switching_enabled": switching_enabled,
        "min_improvement": QUEUE_REPLAN_MIN_IMPROVEMENT,
        "location": current_info.label if current_info is not None else f"stage_{stage_id}",
        "stuck_seconds": round(stuck_seconds, 2),
        "candidate_costs": queue_field_score_payload(scores),
    }


def replan_stalled_agents(
    *,
    sim: jps.Simulation,
    time: float,
    progress: dict[int, AgentProgress],
    stage_advance_targets: StageAdvanceTargets,
    queue_replan_targets: QueueReplanTargets,
    runtimes: Iterable[NativeQueueRuntime],
    stage_registry: StageRegistry,
    geometry: Polygon,
    queue_distance_fields: QueueDistanceFields,
    rng: random.Random,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    runtime_by_stage = {runtime.stage_id: runtime for runtime in runtimes}
    live_ids: set[int] = set()
    for agent in sim.agents():
        sim_id = int(agent.id)
        live_ids.add(sim_id)
        stage_id = int(agent.stage_id)
        journey_id = int(agent.journey_id)
        position = (float(agent.position[0]), float(agent.position[1]))
        previous = progress.get(sim_id)
        if previous is None or previous.stage_id != stage_id or previous.journey_id != journey_id:
            progress[sim_id] = AgentProgress(stage_id, journey_id, position, time)
            continue

        displacement = math.hypot(
            position[0] - previous.position[0],
            position[1] - previous.position[1],
        )
        if displacement > STAGE_REPLAN_MIN_DELTA_M:
            progress[sim_id] = AgentProgress(stage_id, journey_id, position, time)
            continue

        stuck_seconds = time - previous.last_progress_time
        targets = stage_advance_targets.get((stage_id, journey_id))
        stage_info = stage_registry.get(stage_id)
        if stage_info is not None and stage_info.kind == "queue":
            if stuck_seconds < QUEUE_TARGET_REPLAN_STALL_SECONDS:
                continue
            replan_result = replan_stalled_queue_target(
                sim=sim,
                sim_id=sim_id,
                journey_id=journey_id,
                stage_id=stage_id,
                position=position,
                stuck_seconds=stuck_seconds,
                queue_replan_targets=queue_replan_targets,
                stage_registry=stage_registry,
                runtime_by_stage=runtime_by_stage,
                geometry=geometry,
                queue_distance_fields=queue_distance_fields,
                rng=rng,
            )
            if replan_result is None:
                continue
            next_stage, event = replan_result
            event["time"] = round(time, 2)
            events.append(event)
            progress[sim_id] = AgentProgress(next_stage, journey_id, position, time)
            continue
        if stuck_seconds < STAGE_REPLAN_STALL_SECONDS or not targets:
            continue

        reachable_targets = reachable_advance_targets(
            position=position,
            targets=targets,
            stage_registry=stage_registry,
            geometry=geometry,
        )
        if not reachable_targets:
            continue
        next_stage = choose_least_loaded_stage(sim, reachable_targets)
        candidate_costs = stage_replan_diagnostics(
            sim=sim,
            stage_ids=reachable_targets,
            stage_registry=stage_registry,
            position=position,
        )
        sim.switch_agent_journey(sim_id, journey_id, next_stage)
        progress[sim_id] = AgentProgress(next_stage, journey_id, position, time)
        events.append(
            {
                "time": round(time, 2),
                "type": "behavior_replan",
                "reason": "movement_stalled",
                "policy": "least_loaded_stage_with_cost_diagnostics",
                "sim_id": sim_id,
                "from_stage": stage_id,
                "to_stage": next_stage,
                "location": stage_info.label if stage_info is not None else f"stage_{stage_id}",
                "stuck_seconds": round(stuck_seconds, 2),
                "candidate_costs": candidate_costs,
            }
        )

    for sim_id in list(progress):
        if sim_id not in live_ids:
            progress.pop(sim_id, None)
    return events


def reroute_stuck_agents(
    *,
    sim: jps.Simulation,
    time: float,
    progress: dict[int, AgentProgress],
    stage_advance_targets: StageAdvanceTargets,
    queue_replan_targets: QueueReplanTargets,
    runtimes: Iterable[NativeQueueRuntime],
    stage_registry: StageRegistry,
    geometry: Polygon,
    queue_distance_fields: QueueDistanceFields,
    rng: random.Random,
) -> list[dict[str, object]]:
    return replan_stalled_agents(
        sim=sim,
        time=time,
        progress=progress,
        stage_advance_targets=stage_advance_targets,
        queue_replan_targets=queue_replan_targets,
        runtimes=runtimes,
        stage_registry=stage_registry,
        geometry=geometry,
        queue_distance_fields=queue_distance_fields,
        rng=rng,
    )
