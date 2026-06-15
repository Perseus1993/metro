from __future__ import annotations

import math
import random
import re
from dataclasses import replace

import jupedsim as jps
from shapely.geometry import Point
from shapely.ops import unary_union

from ..config import (
    CLEARANCE_MAX_DURATION,
    H,
    PEAK_ROUTE_SPAWNS,
    SAMPLE_DT,
    SIM_DT,
    SIM_DURATION,
    TRAIN_CYCLE,
    W,
)
from ..facilities import elevator_payload
from ..floor_field import GridFloorField
from ..geometry import canvas, load_station_geometry
from ..layout import layout_payload
from ..process_model import PROCESS_MODEL
from ..queue_runtime import (
    queue_assignment_target_px,
    queue_layout_payload,
    queue_visual_assignments,
)
from ..specs import GATE_QUEUE_SPECS
from .alighting_journeys import (
    add_continuous_alighting_journeys,
    make_continuous_alighting_spawns,
)
from .constants import QUEUE_FIELD_GRID_CELL_SIZE_M
from .debug_payload import (
    angle,
    append_point,
    build_clearance_audit,
    build_stuck_report,
    make_track_record,
    sample_queue_metrics,
    sample_simulation_debug,
)
from .entry_journeys import add_continuous_entry_journeys
from .entry_spawns import make_spawns
from .queues import (
    add_boarding_door_queues,
    add_native_facility_queues,
    service_native_queues,
    train_boarding_geometry,
)
from .replanning import refresh_queue_distance_fields, reroute_stuck_agents
from .stages import build_stage_geometry_diagnostics, stage_registry_payload
from .stuck_recovery import recover_stalled_agents
from .types import (
    AgentProgress,
    QueueReplanTargets,
    SoftReleaseTargets,
    StageAdvanceTargets,
    StageRegistry,
)


def build_tracks() -> dict[str, object]:
    rng = random.Random(20260518)
    replan_rng = random.Random(20260519)
    geometry = unary_union([load_station_geometry(), train_boarding_geometry()])
    floor_grid = GridFloorField.from_geometry(
        geometry,
        cell_size_m=QUEUE_FIELD_GRID_CELL_SIZE_M,
    )
    sim = jps.Simulation(
        model=jps.CollisionFreeSpeedModelV3(),
        geometry=geometry,
        dt=SIM_DT,
    )
    stage_registry: StageRegistry = {}
    soft_release_targets: SoftReleaseTargets = {}
    stage_advance_targets: StageAdvanceTargets = {}
    queue_replan_targets: QueueReplanTargets = {}
    facility_queues = add_native_facility_queues(sim, geometry, stage_registry)
    boarding_queues = add_boarding_door_queues(sim, geometry, stage_registry)
    entry_journeys = add_continuous_entry_journeys(
        sim,
        facility_queues,
        boarding_queues,
        stage_registry,
        geometry,
        soft_release_targets,
        stage_advance_targets,
        queue_replan_targets,
    )
    alighting_journeys = add_continuous_alighting_journeys(
        sim,
        facility_queues,
        stage_registry,
        geometry,
        soft_release_targets,
        stage_advance_targets,
        queue_replan_targets,
    )
    native_queues = [*facility_queues.values(), *boarding_queues]
    runtime_by_stage = {runtime.stage_id: runtime for runtime in native_queues}
    entry_spawns = make_spawns(rng, entry_journeys)
    alighting_spawns = make_continuous_alighting_spawns(
        rng=rng,
        alighting_journeys=alighting_journeys,
        start_id=len(entry_spawns),
    )
    spawns = [*entry_spawns, *alighting_spawns]
    spawns.sort(key=lambda item: item.spawn_time)
    pending = list(spawns)
    sim_to_track: dict[int, int] = {}
    tracks: dict[int, dict[str, object]] = {
        spawn.agent_id: make_track_record(spawn) for spawn in spawns
    }
    last_positions: dict[int, tuple[float, float]] = {}
    max_steps = int(CLEARANCE_MAX_DURATION / SIM_DT)
    sample_every = 1
    debug_every = max(1, round(1.0 / SIM_DT))
    queue_samples: list[dict[str, object]] = []
    debug_samples: list[dict[str, object]] = []
    debug_events: list[dict[str, object]] = []
    elevator_events: list[dict[str, object]] = []
    conveyor_events: list[dict[str, object]] = []
    progress_state: dict[int, AgentProgress] = {}
    recovery_counts: dict[int, int] = {}
    final_time = 0.0
    elevator_event_id = 0
    conveyor_event_id = 0

    for step in range(max_steps + 1):
        time = step * SIM_DT
        final_time = time
        while pending and pending[0].spawn_time <= time:
            spawn = pending.pop(0)
            added = False
            for attempt in range(8):
                jitter = attempt * 0.2
                position = (
                    spawn.position[0] + rng.uniform(-jitter, jitter),
                    spawn.position[1] + rng.uniform(-jitter, jitter),
                )
                if not geometry.covers(Point(position)):
                    continue
                try:
                    sim_id = sim.add_agent(
                        jps.CollisionFreeSpeedModelV3AgentParameters(
                            position=position,
                            journey_id=spawn.journey_id,
                            stage_id=spawn.first_stage_id,
                            radius=spawn.radius,
                            desired_speed=spawn.desired_speed,
                            time_gap=spawn.time_gap,
                            strength_neighbor_repulsion=5.5,
                            range_neighbor_repulsion=0.20,
                            strength_geometry_repulsion=4.2,
                            range_geometry_repulsion=0.06,
                            agent_buffer=0.015,
                        )
                    )
                except Exception:
                    continue
                sim_to_track[sim_id] = spawn.agent_id
                last_positions[sim_id] = position
                added = True
                break
            if not added:
                retry_time = round(time + SIM_DT, 3)
                if retry_time < CLEARANCE_MAX_DURATION:
                    pending.append(replace(spawn, spawn_time=retry_time))
                    pending.sort(key=lambda item: item.spawn_time)
                else:
                    tracks[spawn.agent_id]["skipped"] = True

        service_releases = service_native_queues(
            sim,
            native_queues,
            time,
            soft_release_targets,
            stage_registry,
            geometry,
        )
        elevator_batches: dict[str, list[int]] = {}
        for release in service_releases:
            runtime = release.runtime
            sim_id = release.sim_id
            track_id = sim_to_track.get(sim_id)
            debug_events.append(
                {
                    "time": round(time, 2),
                    "type": "service_release",
                    "sim_id": sim_id,
                    "track_id": track_id,
                    "facility": runtime.name,
                    "mode": release.mode,
                    "release_reachable": release.release_reachable,
                    "release_stage_id": release.release_stage_id,
                }
            )
            if runtime.name == "down_elevator_queue" and track_id is not None:
                elevator_batches.setdefault(runtime.name, []).append(track_id)
            elif is_escalator_runtime(runtime.name) and track_id is not None:
                conveyor_event_id += 1
                conveyor_events.append(
                    conveyor_event_payload(
                        event_id=conveyor_event_id,
                        facility=runtime.name,
                        time=time,
                        track_id=track_id,
                    )
                )

        for runtime_name, track_ids in elevator_batches.items():
            if not track_ids:
                continue
            elevator_event_id += 1
            elevator_events.append(
                elevator_event_payload(
                    event_id=elevator_event_id,
                    facility=runtime_name,
                    time=time,
                    track_ids=track_ids,
                )
            )

        if step % debug_every == 0:
            queue_distance_fields = refresh_queue_distance_fields(
                sim=sim,
                grid=floor_grid,
                stage_registry=stage_registry,
                queue_replan_targets=queue_replan_targets,
                runtime_by_stage=runtime_by_stage,
            )
            debug_events.extend(
                reroute_stuck_agents(
                    sim=sim,
                    time=time,
                    progress=progress_state,
                    stage_advance_targets=stage_advance_targets,
                    queue_replan_targets=queue_replan_targets,
                    runtimes=native_queues,
                    stage_registry=stage_registry,
                    geometry=geometry,
                    queue_distance_fields=queue_distance_fields,
                    rng=replan_rng,
                )
            )

        if step % sample_every == 0:
            queue_assignments = queue_visual_assignments(sim, native_queues)
            for agent in sim.agents():
                track_id = sim_to_track.get(agent.id)
                if track_id is None:
                    continue
                mx, my = float(agent.position[0]), float(agent.position[1])
                render_position = (mx, my)
                assignment = queue_assignments.get(agent.id)
                target_px = None
                target_mode = None
                if assignment is not None:
                    target_px = queue_assignment_target_px(assignment)
                    target_mode = assignment.mode

                last = last_positions.get(agent.id, render_position)
                x, y = canvas(render_position)
                heading = (
                    angle(last, render_position)
                    if math.hypot(render_position[0] - last[0], render_position[1] - last[1]) > 0.01
                    else 0.0
                )
                append_point(
                    tracks[track_id]["points"],  # type: ignore[arg-type]
                    time,
                    x,
                    y,
                    heading,
                    0.94,
                    target=target_px,
                    target_mode=target_mode,
                )
                last_positions[agent.id] = render_position
            queue_samples.append(
                {
                    "time": round(time, 2),
                    "queues": sample_queue_metrics(sim, native_queues),
                }
            )
        if step % debug_every == 0:
            debug_samples.append(
                sample_simulation_debug(
                    sim=sim,
                    runtimes=native_queues,
                    sim_to_track=sim_to_track,
                    stage_registry=stage_registry,
                    time=time,
                )
            )
            debug_events.extend(
                recover_stalled_agents(
                    sim=sim,
                    time=time,
                    progress=progress_state,
                    stage_advance_targets=stage_advance_targets,
                    soft_release_targets=soft_release_targets,
                    stage_registry=stage_registry,
                    geometry=geometry,
                    sim_to_track=sim_to_track,
                    last_positions=last_positions,
                    recovery_counts=recovery_counts,
                    runtimes=native_queues,
                    rng=replan_rng,
                )
            )
        if time >= SIM_DURATION and not pending and not any(True for _agent in sim.agents()):
            break
        try:
            sim.iterate()
        except RuntimeError as exc:
            match = re.search(r"Point \(([-0-9.eE]+), ([-0-9.eE]+)\)", str(exc))
            if match:
                bad = (float(match.group(1)), float(match.group(2)))
                nearest = []
                for agent in sim.agents():
                    mx, my = float(agent.position[0]), float(agent.position[1])
                    track_id = sim_to_track.get(agent.id)
                    route = tracks.get(track_id, {}).get("route") if track_id is not None else None
                    nearest.append(
                        (
                            round(math.hypot(mx - bad[0], my - bad[1]), 3),
                            int(agent.id),
                            route,
                            int(agent.stage_id),
                            (round(mx, 3), round(my, 3)),
                        )
                    )
                nearest.sort(key=lambda item: item[0])
                raise RuntimeError(
                    f"JuPedSim iteration failed at t={time:.2f}s near={nearest[:6]}"
                ) from exc
            raise RuntimeError(f"JuPedSim iteration failed at t={time:.2f}s") from exc

    live_track_ids = {
        track_id
        for agent in sim.agents()
        if (track_id := sim_to_track.get(int(agent.id))) is not None
    }
    clearance_audit = build_clearance_audit(
        tracks=tracks,
        spawns=spawns,
        live_track_ids=live_track_ids,
        pending=pending,
        final_time=final_time,
    )
    agents = [agent for agent in tracks.values() if agent.get("points")]
    visual_speed_smoothing = {
        "enabled": False,
        "reason": "continuous_journey_graph_records_raw_jupedsim_positions",
    }
    simulation_debug = {
        "sample_interval": 1.0,
        "stages": stage_registry_payload(stage_registry),
        "stage_diagnostics": build_stage_geometry_diagnostics(stage_registry, geometry),
        "samples": debug_samples,
        "events": debug_events,
        "report": build_stuck_report(debug_samples, debug_events),
        "clearance_audit": clearance_audit,
    }
    return {
        "generated_by": (
            f"JuPedSim {getattr(jps, '__version__', 'unknown')} + "
            "continuous_station_process_graph + native_queue_service"
        ),
        "geometry": "layout.py",
        "scenario": {
            "station_name": "\u5c0f\u5be8",
            "hour": 18,
            "minutes": 1,
            "tick_seconds": 5,
            "group_size": 1,
            "entry_count_hour": 8683,
            "exit_count_hour": 7253,
            "source_label": "normal_workday_mean",
            "sample_hours": 143,
            "movement_backend_name": "jupedsim",
            "movement_backend": "BatchedJuPedSimMovementBackend",
            "jupedsim_operational_model": "collision_free_speed",
            "design_template": "visual_demo_station",
            "clock_start_seconds": 18 * 3600,
        },
        "train_service": {
            "headway_seconds": TRAIN_CYCLE,
            "dwell_seconds": 14,
            "initial_offset_seconds": 0,
            "capacity_persons": 1200,
            "boarding_persons_per_min": 900,
        },
        "layout": layout_payload(),
        "facilities": {
            "elevator": elevator_payload(W, H),
        },
        "queue_layouts": queue_layout_payload(geometry),
        "duration": clearance_audit["final_time_s"],
        "demo_window_seconds": 55,
        "sample_dt": SAMPLE_DT,
        "clearance_audit": clearance_audit,
        "native_queue_model": {
            "pedestrian_model": "CollisionFreeSpeedModelV3",
            "journey_targets": "continuous_graph",
            "demand_duration_s": SIM_DURATION,
            "clearance_max_duration_s": CLEARANCE_MAX_DURATION,
            "arrival_model": "bursty_group_arrivals",
            "queue_slot_jitter": True,
            "queue_visual_model": "raw_jupedsim_positions_with_queue_target_markers",
            "decision_model": "least_targeted_inside_continuous_journeys",
            "boarding_release_model": "native_queue_pop_to_train_door_journey",
            "alighting_release_model": "native_spawn_at_train_door_to_exit_journey",
            "elevator_model": "native_batch_queue_inside_continuous_journey",
            "service_model": "native_enqueued_pop_with_audited_virtual_queue",
            "stitched_passenger_tracks": False,
            "external_entry_spawns": PEAK_ROUTE_SPAWNS,
            "gate_queues": len(GATE_QUEUE_SPECS),
            "exit_gate_queues": len(PROCESS_MODEL.exit_gate_queues),
            "independent_boarding_spawns": 0,
            "queue_count": len(native_queues),
            "visual_speed_smoothing": visual_speed_smoothing,
        },
        "queue_samples": queue_samples,
        "elevator_events": elevator_events,
        "conveyor_events": conveyor_events,
        "_simulation_debug": simulation_debug,
        "agents": agents,
    }


def elevator_event_payload(
    *,
    event_id: int,
    facility: str,
    time: float,
    track_ids: list[int],
) -> dict[str, object]:
    board_seconds = 1.6
    travel_seconds = 7.4
    unload_seconds = 2.2
    board_end = time + board_seconds
    arrive = board_end + travel_seconds
    end = arrive + unload_seconds
    return {
        "id": event_id,
        "facility": facility,
        "direction": "down",
        "from_level": "B1",
        "to_level": "B2",
        "start": round(time, 2),
        "board_end": round(board_end, 2),
        "arrive": round(arrive, 2),
        "end": round(end, 2),
        "count": len(track_ids),
        "track_ids": sorted(track_ids),
    }


def is_escalator_runtime(name: str) -> bool:
    return "escalator" in name


def conveyor_event_payload(
    *,
    event_id: int,
    facility: str,
    time: float,
    track_id: int,
) -> dict[str, object]:
    duration = 10.2 if facility.startswith("down_") else 9.6
    return {
        "id": event_id,
        "facility": facility,
        "kind": "escalator",
        "direction": "up" if facility.startswith("up_") else "down",
        "start": round(time, 2),
        "end": round(time + duration, 2),
        "count": 1,
        "track_ids": [track_id],
    }
