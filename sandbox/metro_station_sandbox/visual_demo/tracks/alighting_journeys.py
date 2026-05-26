from __future__ import annotations

import math
import random

import jupedsim as jps
from shapely.geometry import Polygon

from ..config import SIM_DURATION, TRAIN_CYCLE, W
from ..geometry import meters, px
from ..layout import STATION_LAYOUT
from ..process_model import PROCESS_MODEL
from ..queue_runtime import BOARDING_SCREEN_DOOR_Y, NativeQueueRuntime
from ..region_flow import build_region_capture_flow
from ..specs import SpawnSpec
from .constants import (
    ALIGHTING_APPROACH_RADIUS_M,
    ALIGHTING_EXIT_APPROACH_RADIUS_M,
    ALIGHTING_VERTICAL_DECISION_RADIUS_M,
    EXIT_CORRIDOR_RADIUS_M,
    GATE_DECISION_RADIUS_M,
)
from .stages import native_queue_capture_aprons_n
from .types import (
    QueueReplanTargets,
    SoftReleaseTargets,
    StageAdvanceTargets,
    StageRegistry,
    WaypointBandChain,
)
from .waypoints import (
    add_region_flow_chain,
    add_registered_exit_band,
    add_registered_waypoint_band,
    add_waypoint_band_sequence,
    append_unique_stage,
    record_band_chain_advance,
    record_queue_replan_options,
    record_region_flow_advance,
    record_stage_advance,
    set_band_chain_transitions,
    set_region_flow_transitions,
    transition_to_stage_set,
)


def exit_gate_release_band_parameters(
    exit_gate_runtime: NativeQueueRuntime,
) -> tuple[tuple[float, float], float, int]:
    if exit_gate_runtime.spec is None:
        return (0.820, 0.300), 1.6, 2
    exit_x, exit_y = exit_gate_runtime.spec.exit
    return (exit_x, exit_y + 0.006), 1.6, 2


def exit_gate_decision_point(
    exit_gate_runtimes: list[NativeQueueRuntime],
) -> tuple[float, float]:
    heads = [runtime.spec.head for runtime in exit_gate_runtimes if runtime.spec is not None]
    if not heads:
        return (0.785, 0.345)
    xs = [point[0] for point in heads]
    ys = [point[1] for point in heads]
    return (sum(xs) / len(xs), sum(ys) / len(ys) + 0.030)


def add_continuous_alighting_journeys(
    sim: jps.Simulation,
    native_queues: dict[str, NativeQueueRuntime],
    stage_registry: StageRegistry,
    geometry: Polygon,
    soft_release_targets: SoftReleaseTargets,
    stage_advance_targets: StageAdvanceTargets,
    queue_replan_targets: QueueReplanTargets,
) -> dict[str, tuple[int, int]]:
    exit_gate_runtimes = [
        native_queues[spec.name]
        for spec in sorted(PROCESS_MODEL.exit_gate_queues, key=lambda item: item.head[0])
    ]
    definitions = {
        "left": {
            "approach": [(0.270, 0.746), (0.288, 0.716)],
            "vertical": native_queues["up_escalator_1_queue"],
            "post_vertical": [
                (0.276, 0.428),
                (0.340, 0.412),
                (0.470, 0.404),
                (0.600, 0.385),
                (0.700, 0.355),
            ],
        },
        "mid": {
            "approach": [(0.735, 0.732), (0.815, 0.716)],
            "vertical": native_queues["up_escalator_2_queue"],
            "post_vertical": [(0.776, 0.428), (0.775, 0.390), (0.780, 0.350)],
        },
        "right": {
            "approach": [(0.815, 0.735), (0.850, 0.708)],
            "vertical": native_queues["stairs_up_queue"],
            "post_vertical": [(0.892, 0.426), (0.865, 0.384), (0.840, 0.344)],
        },
    }
    journeys: dict[str, tuple[int, int]] = {}
    for name, definition in definitions.items():
        stages: list[int] = []
        seen: set[int] = set()
        local_advance_targets: dict[int, tuple[int, ...]] = {}
        journey_name = f"alighting.{name}.continuous_exit"
        approach_chain = add_waypoint_band_sequence(
            sim,
            list(definition["approach"]),
            geometry=geometry,
            final_radius_m=ALIGHTING_VERTICAL_DECISION_RADIUS_M,
            radius_m=ALIGHTING_APPROACH_RADIUS_M,
            band_width_m=5.0,
            lanes=4,
            stage_registry=stage_registry,
            label_prefix=f"{journey_name}.vertical_approach",
            journey=journey_name,
            band_start_index=1,
        )
        for stage_id in approach_chain.stage_ids:
            append_unique_stage(stages, seen, stage_id)
        vertical_runtime = definition["vertical"]
        append_unique_stage(stages, seen, vertical_runtime.stage_id)
        post_vertical_points = [
            *list(definition["post_vertical"]),
            exit_gate_decision_point(exit_gate_runtimes),
        ]
        post_vertical_chain = add_waypoint_band_sequence(
            sim,
            post_vertical_points,
            geometry=geometry,
            final_radius_m=GATE_DECISION_RADIUS_M,
            radius_m=ALIGHTING_EXIT_APPROACH_RADIUS_M,
            band_width_m=6.0,
            lanes=5,
            stage_registry=stage_registry,
            label_prefix=f"{journey_name}.exit_gate_decision",
            journey=journey_name,
            band_start_index=0,
        )
        for stage_id in post_vertical_chain.stage_ids:
            append_unique_stage(stages, seen, stage_id)
        exit_gate_options = exit_gate_runtimes
        exit_gate_stage_ids = [runtime.stage_id for runtime in exit_gate_options]
        exit_gate_capture_flows: dict[int, WaypointBandChain] = {}
        capture_aprons = native_queue_capture_aprons_n(exit_gate_options)
        decision_center = exit_gate_decision_point(exit_gate_runtimes)
        for stage_id in exit_gate_stage_ids:
            append_unique_stage(stages, seen, stage_id)
        for exit_gate in exit_gate_options:
            if exit_gate.spec is None:
                continue
            plan = build_region_capture_flow(
                name=f"{journey_name}.{exit_gate.name}.capture",
                source=decision_center,
                queue_spec=exit_gate.spec,
                queue_stage_id=exit_gate.stage_id,
                capture_aprons=capture_aprons,
                portal_count=1,
                width_m=2.6,
                lanes=2,
                approach_radius_m=2.4,
                capture_radius_m=2.4,
            )
            flow = add_region_flow_chain(
                sim,
                stage_registry,
                plan,
                geometry=geometry,
                journey=journey_name,
            )
            exit_gate_capture_flows[exit_gate.stage_id] = flow
            for stage_id in flow.stage_ids:
                append_unique_stage(stages, seen, stage_id)
        station_exit_band = add_registered_exit_band(
            sim,
            stage_registry,
            f"{journey_name}.station_exit",
            (0.820, 0.330),
            normal_hint=(1.0, 0.0),
            geometry=geometry,
            width_m=10.0,
            lanes=5,
            half_size_m=4.5,
            journey=journey_name,
        )
        exit_corridor_bands: dict[int, tuple[int, ...]] = {}
        for exit_gate in exit_gate_options:
            corridor_center, corridor_width_m, corridor_lanes = exit_gate_release_band_parameters(
                exit_gate
            )
            corridor_band = add_registered_waypoint_band(
                sim,
                stage_registry,
                f"{journey_name}.{exit_gate.name}.exit_corridor",
                corridor_center,
                normal_hint=(1.0, 0.0),
                geometry=geometry,
                width_m=corridor_width_m,
                lanes=corridor_lanes,
                radius_m=EXIT_CORRIDOR_RADIUS_M * 1.5,
                journey=journey_name,
            )
            exit_corridor_bands[exit_gate.stage_id] = corridor_band
            for stage_id in corridor_band:
                append_unique_stage(stages, seen, stage_id)
        for stage_id in station_exit_band:
            append_unique_stage(stages, seen, stage_id)

        journey = jps.JourneyDescription(stages)
        set_band_chain_transitions(journey, approach_chain)
        for stage_id in approach_chain.last_band:
            journey.set_transition_for_stage(
                stage_id,
                jps.Transition.create_fixed_transition(vertical_runtime.stage_id),
            )
        journey.set_transition_for_stage(
            vertical_runtime.stage_id,
            transition_to_stage_set(post_vertical_chain.first_band),
        )
        set_band_chain_transitions(journey, post_vertical_chain)
        exit_gate_entry_stages = tuple(
            flow.first_stage_id for flow in exit_gate_capture_flows.values()
        ) or tuple(exit_gate_stage_ids)
        exit_gate_transition = transition_to_stage_set(exit_gate_entry_stages)
        for stage_id in post_vertical_chain.last_band:
            journey.set_transition_for_stage(stage_id, exit_gate_transition)
        for exit_gate in exit_gate_options:
            flow = exit_gate_capture_flows.get(exit_gate.stage_id)
            if flow is None:
                continue
            set_region_flow_transitions(journey, flow, stage_registry)
            for capture_stage in flow.last_band:
                journey.set_transition_for_stage(
                    capture_stage,
                    jps.Transition.create_fixed_transition(exit_gate.stage_id),
                )
        for exit_gate in exit_gate_options:
            journey.set_transition_for_stage(
                exit_gate.stage_id,
                transition_to_stage_set(exit_corridor_bands[exit_gate.stage_id]),
            )
        for corridor_band in exit_corridor_bands.values():
            for exit_corridor_stage in corridor_band:
                journey.set_transition_for_stage(
                    exit_corridor_stage,
                    transition_to_stage_set(station_exit_band),
                )
        journey_id = sim.add_journey(journey)
        record_queue_replan_options(queue_replan_targets, journey_id, exit_gate_stage_ids)
        record_band_chain_advance(local_advance_targets, approach_chain)
        record_stage_advance(
            local_advance_targets, approach_chain.last_band, (vertical_runtime.stage_id,)
        )
        soft_release_targets[(vertical_runtime.stage_id, journey_id)] = tuple(
            post_vertical_chain.first_band
        )
        record_stage_advance(
            local_advance_targets,
            (vertical_runtime.stage_id,),
            post_vertical_chain.first_band,
        )
        record_band_chain_advance(local_advance_targets, post_vertical_chain)
        record_stage_advance(
            local_advance_targets, post_vertical_chain.last_band, exit_gate_entry_stages
        )
        for exit_gate in exit_gate_options:
            flow = exit_gate_capture_flows.get(exit_gate.stage_id)
            if flow is None:
                continue
            record_region_flow_advance(local_advance_targets, flow, stage_registry)
            record_stage_advance(local_advance_targets, flow.last_band, (exit_gate.stage_id,))
        for exit_gate in exit_gate_options:
            corridor_band = exit_corridor_bands[exit_gate.stage_id]
            soft_release_targets[(exit_gate.stage_id, journey_id)] = corridor_band
            record_stage_advance(local_advance_targets, (exit_gate.stage_id,), corridor_band)
            record_stage_advance(local_advance_targets, corridor_band, station_exit_band)
        for stage_id, targets in local_advance_targets.items():
            stage_advance_targets[(stage_id, journey_id)] = targets
        journeys[name] = (journey_id, approach_chain.first_stage_id)
    return journeys


def alighting_exit_source(vertical_top: tuple[float, float]) -> str:
    nx = vertical_top[0] / W
    if nx < 0.50:
        return "left"
    if nx < 0.84:
        return "mid"
    return "right"


def alighting_exit_target(door_x: float, door_index: int, slot: int) -> tuple[float, float]:
    if door_x < 0.50:
        base = (0.288, 0.716)
        spread = (-0.010 + 0.006 * (slot % 4), -0.006 * (slot // 2))
    elif door_index < 4:
        base = (0.815, 0.716)
        spread = (-0.012 + 0.008 * (slot % 4), -0.005 * (slot // 2))
    elif slot % 2 == 0:
        base = (0.850, 0.708)
        spread = (-0.010 + 0.008 * (slot % 4), -0.004 * (slot // 2))
    else:
        base = (0.815, 0.716)
        spread = (-0.012 + 0.008 * (slot % 4), -0.005 * (slot // 2))
    return px((base[0] + spread[0], base[1] + spread[1]))


def alighting_vertical_top(transfer_target: tuple[float, float]) -> tuple[float, float]:
    nx = transfer_target[0] / W
    if nx < 0.50:
        return px((0.276, 0.428))
    if nx < 0.84:
        return px((0.776, 0.428))
    return px((0.892, 0.426))


def make_continuous_alighting_spawns(
    rng: random.Random,
    alighting_journeys: dict[str, tuple[int, int]],
    start_id: int,
) -> list[SpawnSpec]:
    spawns: list[SpawnSpec] = []
    cohort_starts = [cohort * TRAIN_CYCLE for cohort in range(int(SIM_DURATION / TRAIN_CYCLE) + 1)]
    for cohort_index, cohort_start in enumerate(cohort_starts):
        for door_index, point in enumerate(STATION_LAYOUT.control_points["platform_doors"]):
            door_x = float(point[0])
            for slot in range(5):
                transfer_target = alighting_exit_target(door_x, door_index, slot)
                source = alighting_exit_source(alighting_vertical_top(transfer_target))
                journey_id, first_stage_id = alighting_journeys[source]
                spawn_time = round(cohort_start + 6.15 + slot * 0.48 + door_index * 0.10, 3)
                if spawn_time > SIM_DURATION - 4.0:
                    continue
                agent_id = start_id + len(spawns)
                position = meters(
                    (
                        door_x + (slot % 2 - 0.5) * 0.010 + rng.uniform(-0.006, 0.006),
                        BOARDING_SCREEN_DOOR_Y + rng.uniform(-0.006, 0.006),
                    )
                )
                spawns.append(
                    SpawnSpec(
                        agent_id=agent_id,
                        route_name=f"alighting_{source}_continuous_exit",
                        spawn_time=spawn_time,
                        position=position,
                        color="#ff8a27",
                        size=round(rng.uniform(0.82, 1.02), 3),
                        desired_speed=rng.uniform(1.0, 1.34),
                        journey_id=journey_id,
                        first_stage_id=first_stage_id,
                        radius=rng.uniform(0.18, 0.23),
                        time_gap=rng.uniform(0.62, 0.92),
                        group_id=10000 + cohort_index * 100 + door_index * 10 + slot,
                        motion_phase=rng.uniform(0.0, math.tau),
                        motion_wobble=rng.uniform(0.75, 1.25),
                        stride_hz=rng.uniform(1.18, 1.62),
                    )
                )
    return spawns
