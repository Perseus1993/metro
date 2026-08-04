from __future__ import annotations

import math

import jupedsim as jps
from shapely.geometry import Point, Polygon

from ..config import H, PX_PER_METER, W
from ..geometry import meters
from ..region_flow import RegionFlowPlan
from .stages import add_registered_exit_stage, add_registered_waypoint_stage
from .types import QueueReplanTargets, StageInfo, StageRegistry, WaypointBandChain


def add_waypoint_band_sequence(
    sim: jps.Simulation,
    points: list[tuple[float, float]],
    *,
    geometry: Polygon,
    final_radius_m: float,
    radius_m: float,
    band_width_m: float,
    lanes: int,
    stage_registry: StageRegistry,
    label_prefix: str,
    journey: str,
    band_start_index: int = 1,
) -> WaypointBandChain:
    bands: list[tuple[int, ...]] = []
    for index, point in enumerate(points):
        radius = final_radius_m if index == len(points) - 1 else radius_m
        lane_points = waypoint_band_points(
            points=points,
            index=index,
            geometry=geometry,
            width_m=band_width_m,
            lanes=lanes if index >= band_start_index else 1,
        )
        stage_ids: list[int] = []
        for lane_index, point_m in enumerate(lane_points):
            suffix = (
                f"{index + 1}" if len(lane_points) == 1 else f"{index + 1}.lane{lane_index + 1}"
            )
            stage_ids.append(
                add_registered_waypoint_stage(
                    sim,
                    stage_registry,
                    f"{label_prefix}.{suffix}",
                    point_m,
                    radius,
                    journey=journey,
                )
            )
        bands.append(tuple(stage_ids))
    return WaypointBandChain(tuple(bands))


def add_registered_waypoint_band(
    sim: jps.Simulation,
    stage_registry: StageRegistry,
    label_prefix: str,
    center: tuple[float, float],
    *,
    normal_hint: tuple[float, float],
    geometry: Polygon,
    width_m: float,
    lanes: int,
    radius_m: float,
    journey: str,
    facility: str | None = None,
) -> tuple[int, ...]:
    center_m = meters(center)
    normal_m = normalized_vector(
        (normal_hint[0] * W / PX_PER_METER, normal_hint[1] * H / PX_PER_METER)
    )
    lane_points = offset_points_from_center(center_m, normal_m, width_m, lanes, geometry)
    stages: list[int] = []
    for lane_index, point_m in enumerate(lane_points):
        suffix = "1" if len(lane_points) == 1 else f"lane{lane_index + 1}"
        stages.append(
            add_registered_waypoint_stage(
                sim,
                stage_registry,
                f"{label_prefix}.{suffix}",
                point_m,
                radius_m,
                facility=facility,
                journey=journey,
            )
        )
    return tuple(stages)


def add_region_flow_chain(
    sim: jps.Simulation,
    stage_registry: StageRegistry,
    plan: RegionFlowPlan,
    *,
    geometry: Polygon,
    journey: str,
) -> WaypointBandChain:
    bands: list[tuple[int, ...]] = []
    for portal in plan.portals:
        band = add_registered_waypoint_band(
            sim,
            stage_registry,
            portal.label,
            portal.center,
            normal_hint=portal.normal_hint,
            geometry=geometry,
            width_m=portal.width_m,
            lanes=portal.lanes,
            radius_m=portal.radius_m,
            facility=portal.facility,
            journey=journey,
        )
        bands.append(band)
    return WaypointBandChain(tuple(bands))


def paired_stage_targets(
    source_stage_ids: tuple[int, ...],
    target_stage_ids: tuple[int, ...],
    stage_registry: StageRegistry,
) -> dict[int, int]:
    targets = tuple(int(stage_id) for stage_id in target_stage_ids)
    if not targets:
        return {}
    mapping: dict[int, int] = {}
    for source_index, source_stage_id in enumerate(source_stage_ids):
        source_info = stage_registry.get(int(source_stage_id))
        if source_info is not None and source_info.point_m is not None:
            target_stage_id = min(
                targets,
                key=lambda candidate: _stage_distance(
                    source_info.point_m, stage_registry.get(candidate)
                ),
            )
        else:
            target_stage_id = targets[min(source_index, len(targets) - 1)]
        mapping[int(source_stage_id)] = int(target_stage_id)
    return mapping


def _stage_distance(point_m: tuple[float, float], target_info: StageInfo | None) -> float:
    if target_info is None or target_info.point_m is None:
        return float("inf")
    return math.hypot(point_m[0] - target_info.point_m[0], point_m[1] - target_info.point_m[1])


def set_paired_stage_transitions(
    journey: jps.JourneyDescription,
    source_stage_ids: tuple[int, ...],
    target_stage_ids: tuple[int, ...],
    stage_registry: StageRegistry,
) -> None:
    for source_stage_id, target_stage_id in paired_stage_targets(
        source_stage_ids,
        target_stage_ids,
        stage_registry,
    ).items():
        journey.set_transition_for_stage(
            source_stage_id,
            jps.Transition.create_fixed_transition(target_stage_id),
        )


def set_region_flow_transitions(
    journey: jps.JourneyDescription,
    chain: WaypointBandChain,
    stage_registry: StageRegistry,
) -> None:
    for current_band, next_band in zip(chain.bands, chain.bands[1:]):
        set_paired_stage_transitions(journey, current_band, next_band, stage_registry)


def record_paired_stage_advance(
    local_targets: dict[int, tuple[int, ...]],
    source_stage_ids: tuple[int, ...],
    target_stage_ids: tuple[int, ...],
    stage_registry: StageRegistry,
) -> None:
    for source_stage_id, target_stage_id in paired_stage_targets(
        source_stage_ids,
        target_stage_ids,
        stage_registry,
    ).items():
        local_targets[source_stage_id] = (target_stage_id,)


def record_region_flow_advance(
    local_targets: dict[int, tuple[int, ...]],
    chain: WaypointBandChain,
    stage_registry: StageRegistry,
) -> None:
    for current_band, next_band in zip(chain.bands, chain.bands[1:]):
        record_paired_stage_advance(local_targets, current_band, next_band, stage_registry)


def add_registered_exit_band(
    sim: jps.Simulation,
    stage_registry: StageRegistry,
    label_prefix: str,
    center: tuple[float, float],
    *,
    normal_hint: tuple[float, float],
    geometry: Polygon,
    width_m: float,
    lanes: int,
    half_size_m: float,
    journey: str,
) -> tuple[int, ...]:
    center_m = meters(center)
    normal_m = normalized_vector(
        (normal_hint[0] * W / PX_PER_METER, normal_hint[1] * H / PX_PER_METER)
    )
    lane_points = offset_points_from_center(center_m, normal_m, width_m, lanes, geometry)
    exits: list[int] = []
    for lane_index, point_m in enumerate(lane_points):
        suffix = "1" if len(lane_points) == 1 else f"lane{lane_index + 1}"
        exits.append(
            add_registered_exit_stage(
                sim,
                stage_registry,
                f"{label_prefix}.{suffix}",
                point_m,
                half_size_m,
                journey=journey,
            )
        )
    return tuple(exits)


def waypoint_band_points(
    *,
    points: list[tuple[float, float]],
    index: int,
    geometry: Polygon,
    width_m: float,
    lanes: int,
) -> tuple[tuple[float, float], ...]:
    center_m = meters(points[index])
    if lanes <= 1:
        return (center_m,)
    prev_m = meters(points[max(0, index - 1)])
    next_m = meters(points[min(len(points) - 1, index + 1)])
    tangent = (next_m[0] - prev_m[0], next_m[1] - prev_m[1])
    if math.hypot(*tangent) < 0.001 and index > 0:
        prev_m = meters(points[index - 1])
        tangent = (center_m[0] - prev_m[0], center_m[1] - prev_m[1])
    normal = normalized_vector((-tangent[1], tangent[0]))
    return offset_points_from_center(center_m, normal, width_m, lanes, geometry)


def offset_points_from_center(
    center_m: tuple[float, float],
    normal_m: tuple[float, float],
    width_m: float,
    lanes: int,
    geometry: Polygon,
) -> tuple[tuple[float, float], ...]:
    if lanes <= 1 or width_m <= 0:
        return (center_m,)
    offsets = [-width_m / 2.0 + width_m * lane / max(1, lanes - 1) for lane in range(lanes)]
    candidates = [
        (center_m[0] + normal_m[0] * offset, center_m[1] + normal_m[1] * offset)
        for offset in offsets
    ]
    walkable = [point for point in candidates if geometry.covers(Point(point))]
    if not walkable:
        return (center_m,)
    if center_m not in walkable and geometry.covers(Point(center_m)):
        walkable.insert(len(walkable) // 2, center_m)
    return tuple(walkable)


def routing_area_half_size(*, radius_m: float, band_width_m: float, lanes: int) -> float:
    lane_spacing = band_width_m / max(1, lanes - 1) if lanes > 1 else band_width_m
    return max(0.9, min(radius_m * 0.55, lane_spacing * 0.62, 2.2))


def normalized_vector(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(vector[0], vector[1])
    if length <= 0.001:
        return (1.0, 0.0)
    return (vector[0] / length, vector[1] / length)


def set_band_chain_transitions(
    journey: jps.JourneyDescription,
    chain: WaypointBandChain,
) -> None:
    for current_band, next_band in zip(chain.bands, chain.bands[1:]):
        transition = (
            jps.Transition.create_fixed_transition(next_band[0])
            if len(next_band) == 1
            else jps.Transition.create_least_targeted_transition(list(next_band))
        )
        for current_stage in current_band:
            journey.set_transition_for_stage(current_stage, transition)


def transition_to_stage_set(stage_ids: tuple[int, ...] | list[int]) -> jps.Transition:
    return (
        jps.Transition.create_fixed_transition(stage_ids[0])
        if len(stage_ids) == 1
        else jps.Transition.create_least_targeted_transition(list(stage_ids))
    )


def record_stage_advance(
    local_targets: dict[int, tuple[int, ...]],
    from_stage_ids: tuple[int, ...] | list[int],
    to_stage_ids: tuple[int, ...] | list[int],
) -> None:
    targets = tuple(int(stage_id) for stage_id in to_stage_ids)
    for stage_id in from_stage_ids:
        local_targets[int(stage_id)] = targets


def record_queue_replan_options(
    queue_replan_targets: QueueReplanTargets,
    journey_id: int,
    queue_stage_ids: tuple[int, ...] | list[int],
) -> None:
    options = tuple(dict.fromkeys(int(stage_id) for stage_id in queue_stage_ids))
    if len(options) < 2:
        return
    for stage_id in options:
        queue_replan_targets[(stage_id, int(journey_id))] = options


def record_band_chain_advance(
    local_targets: dict[int, tuple[int, ...]],
    chain: WaypointBandChain,
) -> None:
    for current_band, next_band in zip(chain.bands, chain.bands[1:]):
        record_stage_advance(local_targets, current_band, next_band)


def append_unique_stage(stages: list[int], seen: set[int], stage_id: int) -> None:
    if stage_id not in seen:
        stages.append(stage_id)
        seen.add(stage_id)
