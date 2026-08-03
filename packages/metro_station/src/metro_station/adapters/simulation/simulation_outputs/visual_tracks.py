"""Build versioned visualization bundles from simulation snapshots."""

from __future__ import annotations

import json
import math
import random
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from metro_station.application.replay import ReplayPackage

from ..facilities.service_events import FacilityServiceEvent
from ..movement.trajectory_trace import movement_trace_from_any
from ..planning.plan import WALKING_STATES
from ..runtime.evacuation_metrics import evacuation_metrics
from ..runtime.contracts import (
    SIMULATION_TRACE_SCHEMA_VERSION,
    TRACK_POINT_SCHEMA,
    VISUALIZATION_BUNDLE_SCHEMA_VERSION,
    SimulationTrace,
    VisualizationBundle,
    track_point_meta,
)
from ..runtime.snapshots import FrameSnapshot, PassengerSnapshot
from ..runtime.terminal_events import PassengerTerminalEvent
from ..station.evacuation import EVACUATION_MODE
from ..station.scenario import StationSandboxScenario
from ..presets.visual_demo_config import CANVAS_HEIGHT_PX as H
from ..presets.visual_demo_config import CANVAS_WIDTH_PX as W
from ..presets.visual_demo_config import DEFAULT_SAMPLE_DT as SAMPLE_DT
from ..presets.visual_demo_facilities import elevator_payload
from ..presets.visual_demo_layout import layout_payload
from .facility_events import (
    conveyor_events_payload,
    elevator_events_payload,
    gate_events_payload,
    vertical_service_events_payload,
)
from .station_scene import compile_procedural_asset_manifest, compile_station_scene

from .visual_track_debug import (
    _graph_debug_summary,
    _run_id,
    _scenario_payload,
    _train_samples_from_frames,
    _train_service_payload,
    _trajectory_graph_debug,
)
from .visual_track_samples import (
    _canvas_position,
    _diagnostic_code,
    _diagnostic_sample_from_frame,
    _duration,
    _facility_samples_from_frames,
    _make_agent_record,
    _mesa_queue_layout_payload,
    _passenger_goal_canvas_target,
    _person_count,
    _queue_sample_from_frame,
    _target_mode,
)
from .visual_track_waypoints import (
    _finalize_presentation_service_waypoints,
    _insert_gate_service_waypoints,
    _insert_vertical_service_waypoints,
)


FrameInput = FrameSnapshot | Mapping[str, Any]


def _visual_track_coordinate_transform(
    scenario: StationSandboxScenario,
) -> dict[str, object]:
    design = scenario.station_design
    width_m = float(
        design.constraints.canvas_width_m if design is not None else scenario.geometry.width
    )
    height_m = float(
        design.constraints.canvas_height_m if design is not None else scenario.geometry.height
    )
    return {
        "id": "station_meters_to_canvas_pixels.v1",
        "source_coordinates": "station_model_meters",
        "target_coordinates": "animation_canvas_pixels",
        "source_width_m": width_m,
        "source_height_m": height_m,
        "canvas_width_px": float(W),
        "canvas_height_px": float(H),
        "clamp_to_canvas": True,
        "round_output_decimals": 2,
    }


def _simulation_point_meta(
    *,
    authority: str,
    coordinate_transform: Mapping[str, object],
    source_index: object,
    level_id: str | None,
    phase: str,
    state: str | None = None,
    episode_id: str | None = None,
    sample_index: int | None = None,
) -> dict[str, object]:
    meta = track_point_meta("simulation", visual_only=False)
    meta.update(
        {
            "authority": authority,
            "coordinate_transform": str(coordinate_transform["id"]),
            "source_index": source_index,
            "level_id": level_id,
            "phase": phase,
        }
    )
    if state is not None:
        meta["state"] = str(state)
    if episode_id is not None:
        meta["episode_id"] = str(episode_id)
    if sample_index is not None:
        meta["sample_index"] = int(sample_index)
    return meta


def _merge_authoritative_movement_points(
    agents_by_id: dict[int, dict[str, object]],
    snapshot_context_by_id: Mapping[int, list[tuple[float, PassengerSnapshot]]],
    movement_trace: Mapping[str, Any],
    scenario: StationSandboxScenario,
    *,
    coordinate_transform: Mapping[str, object],
) -> None:
    raw_points = movement_trace.get("points", ())
    if not isinstance(raw_points, Sequence) or isinstance(raw_points, str | bytes):
        raise TypeError("movement_trace.points must be an array")
    occupied_times: dict[int, dict[float, int]] = {}
    for passenger_id, record in agents_by_id.items():
        points = record.get("points")
        occupied_times[passenger_id] = (
            {
                round(float(point[0]), 6): index
                for index, point in enumerate(points)
                if isinstance(point, Sequence)
                and not isinstance(point, str | bytes)
                and point
            }
            if isinstance(points, list)
            else {}
        )

    for source_index, raw_point in enumerate(raw_points):
        if not isinstance(raw_point, Mapping):
            raise TypeError(f"movement_trace point {source_index} must be an object")
        passenger_id = int(raw_point["passenger_id"])
        time_s = float(raw_point["time_seconds"])
        time_key = round(time_s, 6)
        record = agents_by_id.get(passenger_id)
        contexts = snapshot_context_by_id.get(passenger_id)
        if record is None or not contexts:
            raise ValueError(
                "movement trace passenger has no simulation snapshot context: "
                f"passenger_id={passenger_id} time={time_s}"
            )
        context = _snapshot_context_at(contexts, time_s)
        existing_index = occupied_times.get(passenger_id, {}).get(time_key)
        if existing_index is not None and context.state not in WALKING_STATES:
            # Queue and facility snapshots own non-walking post-tick state.
            continue
        position = (float(raw_point["x"]), float(raw_point["y"]))
        px, py = _canvas_position(position, scenario)
        target = _passenger_goal_canvas_target(context, scenario)
        target_mode = _target_mode(context)
        diagnostic = _diagnostic_code(context, None, target)
        points = record.get("points")
        assert isinstance(points, list)
        movement_point = [
                round(time_s, 2),
                round(px, 2),
                round(py, 2),
                0.0,
                0.94,
                round(target[0], 2) if target is not None else None,
                round(target[1], 2) if target is not None else None,
                target_mode,
                diagnostic,
                _simulation_point_meta(
                    authority="simulation_trace.movement_trace",
                    coordinate_transform=coordinate_transform,
                    source_index=source_index,
                    level_id=(
                        None
                        if raw_point.get("level_id") is None
                        else str(raw_point.get("level_id"))
                    ),
                    phase="walking",
                    state=context.state,
                    episode_id=str(raw_point["episode_id"]),
                    sample_index=int(raw_point["sample_index"]),
                ),
            ]
        if existing_index is None:
            points.append(movement_point)
            occupied_times.setdefault(passenger_id, {})[time_key] = len(points) - 1
        else:
            # Walking coordinates are owned by the high-rate JuPedSim trace,
            # including exact Mesa tick boundaries.
            points[existing_index] = movement_point


def _snapshot_context_at(
    contexts: list[tuple[float, PassengerSnapshot]],
    time_s: float,
) -> PassengerSnapshot:
    times = [item[0] for item in contexts]
    index = bisect_right(times, time_s + 1e-9) - 1
    if index < 0:
        index = 0
    return contexts[index][1]


def _assign_forward_headings(
    points: list[Any],
    *,
    snapshot_interval_seconds: float,
    movement_interval_seconds: float,
) -> None:
    if not points:
        return
    segment_start = 0
    for index in range(len(points) - 1):
        if _heading_edge_is_continuous(
            points[index],
            points[index + 1],
            snapshot_interval_seconds=snapshot_interval_seconds,
            movement_interval_seconds=movement_interval_seconds,
        ):
            continue
        _assign_segment_forward_headings(points, segment_start, index)
        segment_start = index + 1
    _assign_segment_forward_headings(points, segment_start, len(points) - 1)


def _assign_segment_forward_headings(
    points: list[Any],
    start: int,
    end: int,
) -> None:
    directions: list[float | None] = []
    for index in range(start, end):
        current = points[index]
        following = points[index + 1]
        dx = float(following[1]) - float(current[1])
        dy = float(following[2]) - float(current[2])
        directions.append(math.atan2(dy, dx) if math.hypot(dx, dy) > 0.01 else None)

    next_heading: float | None = None
    assigned: list[float | None] = [None] * (end - start + 1)
    for local_index in range(len(directions) - 1, -1, -1):
        if directions[local_index] is not None:
            next_heading = directions[local_index]
        assigned[local_index] = next_heading

    previous_heading = 0.0
    for local_index, point_index in enumerate(range(start, end + 1)):
        heading = assigned[local_index]
        if heading is None:
            heading = previous_heading
        points[point_index][3] = round(float(heading), 4)
        previous_heading = float(heading)


def _heading_edge_is_continuous(
    current: Sequence[Any],
    following: Sequence[Any],
    *,
    snapshot_interval_seconds: float,
    movement_interval_seconds: float,
) -> bool:
    dt = float(following[0]) - float(current[0])
    if dt <= 0.0:
        return False
    current_meta = current[9] if len(current) > 9 and isinstance(current[9], Mapping) else {}
    following_meta = (
        following[9] if len(following) > 9 and isinstance(following[9], Mapping) else {}
    )
    current_level = current_meta.get("level_id")
    following_level = following_meta.get("level_id")
    if (
        current_level is not None
        and following_level is not None
        and current_level != following_level
    ):
        return False
    current_authority = current_meta.get("authority")
    following_authority = following_meta.get("authority")
    movement_authority = "simulation_trace.movement_trace"
    if current_authority == movement_authority and following_authority == movement_authority:
        return bool(
            current_meta.get("episode_id") == following_meta.get("episode_id")
            and int(following_meta.get("sample_index", -1))
            == int(current_meta.get("sample_index", -2)) + 1
            and dt <= movement_interval_seconds + 0.021
        )
    if movement_authority in {current_authority, following_authority}:
        return dt <= movement_interval_seconds + 0.021
    return dt <= snapshot_interval_seconds + 0.021


def write_mesa_visual_tracks_js(
    *,
    frames: Sequence[FrameInput],
    scenario: StationSandboxScenario,
    output_path: Path,
    facilities: Iterable[Any] | None = None,
    service_events: Iterable[FacilityServiceEvent] | None = None,
    terminal_events: Iterable[PassengerTerminalEvent | Mapping[str, Any]] | None = None,
    routing_decision_logs: Iterable[Any] | None = None,
    clearance_debug: Mapping[str, Any] | None = None,
    movement_trace: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    payload = mesa_frames_to_visual_tracks(
        frames=frames,
        scenario=scenario,
        facilities=facilities,
        service_events=service_events,
        terminal_events=terminal_events,
        routing_decision_logs=routing_decision_logs,
        clearance_debug=clearance_debug,
        movement_trace=movement_trace,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "window.JPS_TRACKS = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return payload


def write_replay_payload_json(
    *,
    payload: Mapping[str, Any],
    output_path: Path,
) -> Path:
    """Write the renderer-neutral replay envelope as plain JSON.

    The JavaScript wrapper remains available for the legacy browser renderer.
    Unity and other replay clients consume this plain JSON boundary instead.
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return output_path


def mesa_frames_to_visual_tracks(
    *,
    frames: Sequence[FrameInput],
    scenario: StationSandboxScenario,
    facilities: Iterable[Any] | None = None,
    service_events: Iterable[FacilityServiceEvent] | None = None,
    terminal_events: Iterable[PassengerTerminalEvent | Mapping[str, Any]] | None = None,
    routing_decision_logs: Iterable[Any] | None = None,
    clearance_debug: Mapping[str, Any] | None = None,
    movement_trace: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    frame_snapshots = tuple(FrameSnapshot.from_any(frame) for frame in frames)
    normalized_movement_trace = movement_trace_from_any(movement_trace)
    coordinate_transform = _visual_track_coordinate_transform(scenario)
    duration = _duration(frame_snapshots, scenario)
    final_metrics = frame_snapshots[-1].metrics.to_dict() if frame_snapshots else {}
    run_id = _run_id(scenario, final_metrics)
    agents_by_id: dict[int, dict[str, object]] = {}
    previous_position: dict[int, tuple[float, float]] = {}
    previous_time: dict[int, float] = {}
    snapshot_context_by_id: dict[int, list[tuple[float, PassengerSnapshot]]] = {}
    rng = random.Random(20260524)
    facility_list = list(facilities or [])
    queue_layouts = _mesa_queue_layout_payload(facility_list, scenario)
    queue_ids = {str(queue["id"]) for queue in queue_layouts}
    diagnostic_samples: list[dict[str, object]] = []

    for frame_index, frame in enumerate(frame_snapshots):
        time_s = float(frame.time_seconds)
        diagnostic_counts = {"target": 0, "queue": 0, "slow": 0, "platform_wait": 0}
        for passenger_index, passenger in enumerate(frame.passengers):
            passenger_id = int(passenger.id)
            x = float(passenger.x)
            y = float(passenger.y)
            px, py = _canvas_position((x, y), scenario)
            last = previous_position.get(passenger_id)
            last_time = previous_time.get(passenger_id)
            dt = max(0.001, time_s - last_time) if last_time is not None else None
            speed_px_s = (
                math.hypot(px - last[0], py - last[1]) / dt
                if last is not None and dt is not None
                else None
            )
            previous_position[passenger_id] = (px, py)
            previous_time[passenger_id] = time_s
            snapshot_context_by_id.setdefault(passenger_id, []).append((time_s, passenger))

            record = agents_by_id.get(passenger_id)
            if record is None:
                record = _make_agent_record(passenger, rng)
                agents_by_id[passenger_id] = record

            points = record["points"]
            assert isinstance(points, list)
            target = _passenger_goal_canvas_target(passenger, scenario)
            target_mode = _target_mode(passenger)
            diagnostic = _diagnostic_code(passenger, speed_px_s, target)
            if diagnostic in diagnostic_counts:
                diagnostic_counts[diagnostic] += int(passenger.n or 1)
            points.append(
                [
                    round(time_s, 2),
                    round(px, 2),
                    round(py, 2),
                    0.0,
                    0.94,
                    round(target[0], 2) if target is not None else None,
                    round(target[1], 2) if target is not None else None,
                    target_mode,
                    diagnostic,
                    _simulation_point_meta(
                        authority="simulation_trace.snapshots",
                        coordinate_transform=coordinate_transform,
                        source_index=[frame_index, passenger_index],
                        level_id=passenger.current_level_id,
                        phase="snapshot",
                        state=passenger.state,
                    ),
                ]
            )
        diagnostic_samples.append(_diagnostic_sample_from_frame(frame, diagnostic_counts))

    _merge_authoritative_movement_points(
        agents_by_id,
        snapshot_context_by_id,
        normalized_movement_trace,
        scenario,
        coordinate_transform=coordinate_transform,
    )
    for record in agents_by_id.values():
        points = record.get("points")
        if not isinstance(points, list):
            continue
        points.sort(key=lambda point: float(point[0]))
        _assign_forward_headings(
            points,
            snapshot_interval_seconds=float(scenario.tick_seconds),
            movement_interval_seconds=float(scenario.movement_trace_sample_seconds),
        )

    queue_samples = [_queue_sample_from_frame(frame, queue_ids) for frame in frame_snapshots]
    service_event_list = list(service_events or [])
    terminal_event_list = [
        event.as_dict() if isinstance(event, PassengerTerminalEvent) else dict(event)
        for event in (terminal_events or [])
    ]
    routing_log_list = [
        log.as_dict() if callable(getattr(log, "as_dict", None)) else dict(log)
        for log in (routing_decision_logs or [])
    ]
    _insert_vertical_service_waypoints(agents_by_id, service_event_list, scenario)
    _insert_gate_service_waypoints(agents_by_id, service_event_list, scenario)
    _finalize_presentation_service_waypoints(agents_by_id)
    # A passenger can enter and complete during one simulation tick. Its single
    # physical sample is still required trajectory evidence and must not vanish
    # from the exported/debug population ledger.
    agents = [record for record in agents_by_id.values() if record.get("points")]
    graph_debug = _trajectory_graph_debug(clearance_debug, agents_by_id)
    graph_debug_summary = _graph_debug_summary(graph_debug)
    completed_agents = int(final_metrics.get("departed_persons", 0) or 0)
    if completed_agents <= 0:
        completed_agents = int(final_metrics.get("boarded_persons", 0) or 0) + int(
            final_metrics.get("exit_gate_served_persons", 0) or 0
        )
    remaining_agents = _person_count(final_metrics.get("station_persons", 0))
    cleared = remaining_agents == 0
    if graph_debug is not None:
        completed_agents = int(
            graph_debug.get("counts", {}).get("spawned_persons", completed_agents)
            - graph_debug.get("counts", {}).get("active_persons", remaining_agents)
        )
        remaining_agents = int(
            graph_debug.get("counts", {}).get("active_persons", remaining_agents)
        )
        cleared = bool(graph_debug.get("cleared", False)) and bool(
            graph_debug.get("checks", {}).get("trajectory_evidence_complete", False)
        )
    debug_clearance_time = (
        graph_debug.get("clearance_time_s") if graph_debug is not None else None
    )
    clearance_time = (
        float(debug_clearance_time)
        if cleared and debug_clearance_time is not None
        else max(float(event.get("time_seconds", 0.0)) for event in terminal_event_list)
        if cleared and terminal_event_list
        else duration
        if cleared
        else None
    )
    research_evacuation_metrics = (
        evacuation_metrics(
            terminal_event_list,
            total_persons=int(final_metrics.get("spawned_persons", len(agents)) or len(agents)),
            remaining_persons=remaining_agents,
        )
        if scenario.scenario_mode == EVACUATION_MODE
        else None
    )
    right_censored = not cleared and duration >= scenario.horizon_duration_seconds - max(
        0.01, scenario.tick_seconds / 2.0
    )
    clearance_audit = {
        "demand_duration_s": round(scenario.demand_duration_seconds, 2),
        "max_duration_s": round(scenario.horizon_duration_seconds, 2),
        "final_time_s": duration,
        "clearance_time_s": clearance_time,
        "cleared": cleared,
        "right_censored": right_censored,
        "outcome": "cleared" if cleared else "right_censored" if right_censored else "incomplete",
        "completed_agents": completed_agents,
        "evacuated_persons": int(final_metrics.get("evacuated_persons", 0) or 0),
        "remaining_agents": remaining_agents,
        "skipped_agents": 0,
        "total_agents": int(final_metrics.get("spawned_persons", len(agents)) or len(agents)),
        "spawned_entry_persons": int(final_metrics.get("spawned_entry_persons", 0) or 0),
        "spawned_exit_persons": int(final_metrics.get("spawned_exit_persons", 0) or 0),
        "spawned_transfer_persons": int(final_metrics.get("spawned_transfer_persons", 0) or 0),
        "evidence_mode": (
            "strict_goal_graph"
            if graph_debug is not None and graph_debug.get("graph_required")
            else "strict_physical_runtime"
            if graph_debug is not None
            else "physical_snapshot_only"
        ),
        "blockers": [] if graph_debug is None else graph_debug.get("blockers", []),
    }
    facility_samples = _facility_samples_from_frames(frame_snapshots)
    train_samples = _train_samples_from_frames(frame_snapshots)
    vertical_events = vertical_service_events_payload(service_event_list, scenario)
    gate_events = gate_events_payload(service_event_list, scenario)
    elevator_events = elevator_events_payload(service_event_list)
    conveyor_events = conveyor_events_payload(service_event_list, scenario)
    simulation_trace = SimulationTrace(
        run_id=run_id,
        metadata={
            "generated_by": "MetroStationModel",
            "schema_version": SIMULATION_TRACE_SCHEMA_VERSION,
            "scenario": _scenario_payload(scenario, final_metrics),
            "clearance_debug_summary": graph_debug_summary,
            "replay_fidelity": {
                "position_authority": "simulation_trace.snapshots",
                "walking_position_authority": "simulation_trace.movement_trace",
                "snapshot_interval_seconds": float(scenario.tick_seconds),
                "movement_trace_interval_seconds": float(
                    scenario.movement_trace_sample_seconds
                ),
                "walking_interpolation": "linear_between_authoritative_movement_samples",
                "facility_motion_authority": "simulation_trace.facility_events",
                "visual_track_coordinate_transform": coordinate_transform,
                "renderer_track_field": "points",
                "visual_tracks_authoritative": False,
                "visual_track_source_points_field": "points",
                "visual_track_presentation_points_field": "presentation_points",
                "facility_overlays_modify_source_points": False,
            },
            "routing_evidence": {
                "decision_count": len(routing_log_list),
                "plugin_ids": sorted(
                    {
                        str(log.get("plugin_id"))
                        for log in routing_log_list
                        if log.get("plugin_id")
                    }
                ),
            },
        },
        snapshots=[frame.to_dict() for frame in frame_snapshots],
        facility_events=[event.as_dict() for event in service_event_list],
        movement_trace=normalized_movement_trace,
        aggregate_metrics=final_metrics,
        terminal_events=terminal_event_list,
        routing_decision_logs=routing_log_list,
    ).as_dict()
    derived_payload = {
        "clearance_audit": clearance_audit,
        "evacuation_metrics": research_evacuation_metrics,
        "queue_samples": queue_samples,
        "facility_samples": facility_samples,
        "train_samples": train_samples,
        "diagnostic_samples": diagnostic_samples,
        "graph_debug_summary": graph_debug_summary,
    }
    visual_facility_animations = {
        "vertical_service_events": vertical_events,
        "gate_events": gate_events,
        "elevator_events": elevator_events,
        "conveyor_events": conveyor_events,
    }
    visualization_bundle = VisualizationBundle(
        source_run_id=run_id,
        visual_tracks=agents,
        visual_facility_animations=visual_facility_animations,
        debug_layers={
            "queue_samples": queue_samples,
            "facility_samples": facility_samples,
            "diagnostic_samples": diagnostic_samples,
            "graph_debug_summary": graph_debug_summary,
        },
    ).as_dict()
    station_scene = compile_station_scene(scenario, facility_list)
    replay_package = ReplayPackage(
        source_run_id=run_id,
        station_scene=station_scene,
        asset_manifest=compile_procedural_asset_manifest(station_scene),
        metadata={
            "compatibility_envelope": VISUALIZATION_BUNDLE_SCHEMA_VERSION,
            "asset_resolution": "procedural_placeholders",
            "trajectory_authority": "#/simulation_trace",
            "visual_tracks_policy": "presentation_only",
        },
    ).as_dict()
    return {
        "schema_version": VISUALIZATION_BUNDLE_SCHEMA_VERSION,
        "source_run_id": run_id,
        "track_point_schema": list(TRACK_POINT_SCHEMA),
        "simulation_trace": simulation_trace,
        "derived": derived_payload,
        "visualization_bundle": visualization_bundle,
        "replay_package": replay_package,
        "generated_by": "Mesa MetroStationModel + JuPedSim movement backend + animation_demo renderer",
        "geometry": "mesa_model_frames_scaled_to_animation_demo_canvas",
        "scenario": _scenario_payload(scenario, final_metrics),
        "train_service": _train_service_payload(scenario),
        "layout": layout_payload(),
        "facilities": {"elevator": elevator_payload(W, H)},
        "queue_layouts": queue_layouts,
        "duration": duration,
        "sample_dt": SAMPLE_DT,
        "clearance_audit": clearance_audit,
        "native_queue_model": {
            "pedestrian_model": "Mesa movement_backend",
            "journey_targets": "mesa_agent_plan",
            "renderer": "animation_demo.html",
            "source_frames": len(frames),
            "movement_backend": final_metrics.get("movement_backend"),
            "jupedsim_operational_model": final_metrics.get("jupedsim_operational_model"),
            "jupedsim_steps": final_metrics.get("jupedsim_steps"),
            "jupedsim_batches": final_metrics.get("jupedsim_batches"),
            "stitched_passenger_tracks": False,
        },
        "queue_samples": queue_samples,
        "facility_samples": facility_samples,
        "vertical_service_events": vertical_events,
        "gate_events": gate_events,
        "elevator_events": elevator_events,
        "conveyor_events": conveyor_events,
        "train_samples": train_samples,
        "diagnostic_samples": diagnostic_samples,
        "agents": agents,
        "terminal_events": terminal_event_list,
        "evacuation_metrics": research_evacuation_metrics,
        "graph_debug": graph_debug,
    }
