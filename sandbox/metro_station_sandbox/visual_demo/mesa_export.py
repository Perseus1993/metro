from __future__ import annotations

import json
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..planning.plan import AgentState, FacilityStage
from ..facilities.process import FacilityKind
from ..facilities.service_events import FacilityServiceEvent
from ..runtime.contracts import (
    SIMULATION_TRACE_SCHEMA_VERSION,
    TRACK_POINT_SCHEMA,
    VISUALIZATION_BUNDLE_SCHEMA_VERSION,
    SimulationTrace,
    VisualizationBundle,
    track_point_meta,
)
from ..runtime.snapshots import FrameSnapshot, PassengerSnapshot, TrainSnapshot
from ..station.scenario import StationSandboxScenario
from .config import H, SAMPLE_DT, TRACKS_JS, W
from .facilities import elevator_payload
from .layout import layout_payload
from .tracks.vertical_events import (
    conveyor_events_payload,
    elevator_events_payload,
    gate_events_payload,
    vertical_service_events_payload,
)


FrameInput = FrameSnapshot | Mapping[str, Any]


def write_mesa_visual_tracks_js(
    *,
    frames: Sequence[FrameInput],
    scenario: StationSandboxScenario,
    output_path: Path = TRACKS_JS,
    facilities: Iterable[Any] | None = None,
    service_events: Iterable[FacilityServiceEvent] | None = None,
) -> dict[str, object]:
    payload = mesa_frames_to_visual_tracks(
        frames=frames,
        scenario=scenario,
        facilities=facilities,
        service_events=service_events,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "window.JPS_TRACKS = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return payload


def mesa_frames_to_visual_tracks(
    *,
    frames: Sequence[FrameInput],
    scenario: StationSandboxScenario,
    facilities: Iterable[Any] | None = None,
    service_events: Iterable[FacilityServiceEvent] | None = None,
) -> dict[str, object]:
    frame_snapshots = tuple(FrameSnapshot.from_any(frame) for frame in frames)
    duration = _duration(frame_snapshots, scenario)
    final_metrics = frame_snapshots[-1].metrics.to_dict() if frame_snapshots else {}
    run_id = _run_id(scenario, final_metrics)
    agents_by_id: dict[int, dict[str, object]] = {}
    previous_position: dict[int, tuple[float, float]] = {}
    previous_time: dict[int, float] = {}
    rng = random.Random(20260524)
    queue_layouts = _mesa_queue_layout_payload(facilities, scenario)
    queue_ids = {str(queue["id"]) for queue in queue_layouts}
    diagnostic_samples: list[dict[str, object]] = []

    for frame in frame_snapshots:
        time_s = float(frame.time_seconds)
        diagnostic_counts = {"target": 0, "queue": 0, "slow": 0, "platform_wait": 0}
        for passenger in frame.passengers:
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
            last = last or (px, py)
            heading = math.atan2(py - last[1], px - last[0]) if (px, py) != last else 0.0
            previous_position[passenger_id] = (px, py)
            previous_time[passenger_id] = time_s

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
                    round(heading, 4),
                    0.94,
                    round(target[0], 2) if target is not None else None,
                    round(target[1], 2) if target is not None else None,
                    target_mode,
                    diagnostic,
                    track_point_meta("simulation", visual_only=False),
                ]
            )
        diagnostic_samples.append(_diagnostic_sample_from_frame(frame, diagnostic_counts))

    queue_samples = [_queue_sample_from_frame(frame, queue_ids) for frame in frame_snapshots]
    service_event_list = list(service_events or [])
    _insert_vertical_service_waypoints(agents_by_id, service_event_list, scenario)
    _insert_gate_service_waypoints(agents_by_id, service_event_list, scenario)
    agents = [record for record in agents_by_id.values() if len(record.get("points", [])) >= 2]
    completed_agents = int(final_metrics.get("boarded_persons", 0) or 0) + int(
        final_metrics.get("exit_gate_served_persons", 0) or 0
    )
    remaining_agents = _person_count(final_metrics.get("station_persons", 0))
    cleared = remaining_agents == 0
    clearance_audit = {
        "demand_duration_s": round(scenario.demand_duration_seconds, 2),
        "max_duration_s": round(scenario.horizon_duration_seconds, 2),
        "final_time_s": duration,
        "clearance_time_s": duration if cleared else None,
        "cleared": cleared,
        "completed_agents": completed_agents,
        "remaining_agents": remaining_agents,
        "skipped_agents": 0,
        "total_agents": int(final_metrics.get("spawned_persons", len(agents)) or len(agents)),
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
        },
        snapshots=[frame.to_dict() for frame in frame_snapshots],
        facility_events=[event.as_dict() for event in service_event_list],
        aggregate_metrics=final_metrics,
    ).as_dict()
    derived_payload = {
        "clearance_audit": clearance_audit,
        "queue_samples": queue_samples,
        "facility_samples": facility_samples,
        "train_samples": train_samples,
        "diagnostic_samples": diagnostic_samples,
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
        },
    ).as_dict()
    return {
        "schema_version": VISUALIZATION_BUNDLE_SCHEMA_VERSION,
        "source_run_id": run_id,
        "track_point_schema": list(TRACK_POINT_SCHEMA),
        "simulation_trace": simulation_trace,
        "derived": derived_payload,
        "visualization_bundle": visualization_bundle,
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
    }


def _scenario_payload(
    scenario: StationSandboxScenario,
    final_metrics: dict[str, Any],
) -> dict[str, object]:
    design = scenario.station_design
    return {
        "station_name": scenario.station_name,
        "hour": int(scenario.hour),
        "minutes": int(scenario.minutes),
        "demand_minutes": int(scenario.demand_duration_minutes),
        "clearance_minutes": int(scenario.clearance_minutes),
        "tick_seconds": int(scenario.tick_seconds),
        "group_size": int(scenario.group_size),
        "entry_count_hour": int(scenario.entry_count_hour),
        "exit_count_hour": int(scenario.exit_count_hour),
        "source_label": scenario.source_label,
        "sample_hours": int(scenario.sample_hours),
        "movement_backend_name": scenario.movement_backend_name,
        "movement_backend": final_metrics.get("movement_backend") or scenario.movement_backend_name,
        "jupedsim_operational_model": scenario.jupedsim_operational_model,
        "design_template": design.template_id if design is not None else None,
        "clock_start_seconds": int(scenario.hour) * 3600,
    }


def _train_service_payload(scenario: StationSandboxScenario) -> dict[str, object]:
    return {
        "headway_seconds": int(scenario.train_headway_seconds),
        "dwell_seconds": int(scenario.train_dwell_seconds),
        "initial_offset_seconds": int(scenario.initial_train_offset_seconds),
        "capacity_persons": int(scenario.train_capacity_persons),
        "boarding_persons_per_min": int(scenario.boarding_persons_per_min),
    }


def _run_id(
    scenario: StationSandboxScenario,
    final_metrics: dict[str, Any],
) -> str:
    design = scenario.station_design
    design_id = design.id if design is not None else "no_design"
    spawned = int(final_metrics.get("spawned_persons", 0) or 0)
    return (
        f"{design_id}:h{int(scenario.hour):02d}:"
        f"entry{int(scenario.entry_count_hour)}:"
        f"exit{int(scenario.exit_count_hour)}:"
        f"d{int(scenario.demand_duration_minutes)}:"
        f"m{int(scenario.minutes)}:spawned{spawned}"
    )


def _train_samples_from_frames(frames: Sequence[FrameSnapshot]) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for frame in frames:
        samples.append(
            {
                "time": round(float(frame.time_seconds), 2),
                "trains": [_train_payload(train) for train in frame.trains],
            }
        )
    return samples


def _train_payload(train: TrainSnapshot) -> dict[str, object]:
    return {
        "id": train.id,
        "line_id": train.line_id,
        "direction": train.direction,
        "platform_id": train.platform_id,
        "state": train.state,
        "current_load_persons": int(train.current_load_persons),
        "last_departed_load_persons": int(train.last_departed_load_persons),
        "departure_elapsed_seconds": train.departure_elapsed_seconds,
        "departed_trains": int(train.departed_trains),
    }


def _insert_gate_service_waypoints(
    agents_by_id: dict[int, dict[str, object]],
    events: Sequence[FacilityServiceEvent],
    scenario: StationSandboxScenario,
) -> None:
    for event in events:
        if event.facility_kind != FacilityKind.GATE.value:
            continue
        gate_position = _canvas_position(event.start_position, scenario)
        exit_position = _canvas_position(event.end_position, scenario)
        for passenger_id in event.passenger_ids:
            record = agents_by_id.get(int(passenger_id))
            if record is None:
                continue
            points = record.get("points")
            if not isinstance(points, list) or len(points) < 2:
                continue
            _insert_gate_waypoints(points, event, gate_position, exit_position)


def _insert_vertical_service_waypoints(
    agents_by_id: dict[int, dict[str, object]],
    events: Sequence[FacilityServiceEvent],
    scenario: StationSandboxScenario,
) -> None:
    vertical_kinds = {
        FacilityKind.ESCALATOR.value,
        FacilityKind.ELEVATOR.value,
        FacilityKind.STAIRS.value,
    }
    visual_slots = _vertical_service_visual_slots(events, vertical_kinds)
    for event in events:
        if event.facility_kind not in vertical_kinds:
            continue
        start_position = _canvas_position(event.start_position, scenario)
        end_position = _canvas_position(event.end_position, scenario)
        for passenger_id in event.passenger_ids:
            record = agents_by_id.get(int(passenger_id))
            if record is None:
                continue
            points = record.get("points")
            if not isinstance(points, list) or len(points) < 2:
                continue
            slot, group_size = visual_slots.get((event.event_id, int(passenger_id)), (0, 1))
            lane_offset_px, progress_offset = _vertical_service_visual_offsets(
                event,
                slot,
                group_size,
            )
            _smooth_facility_service_points(
                points,
                event,
                start_position,
                end_position,
                lane_offset_px=lane_offset_px,
                progress_offset=progress_offset,
                reason="vertical_service_visual_smoothing",
            )


def _vertical_service_visual_slots(
    events: Sequence[FacilityServiceEvent],
    vertical_kinds: set[str],
) -> dict[tuple[int, int], tuple[int, int]]:
    groups: dict[tuple[str, str, float, float], list[tuple[int, int]]] = {}
    for event in events:
        if event.facility_kind not in vertical_kinds:
            continue
        if event.facility_kind == FacilityKind.ELEVATOR.value:
            continue
        move_start = float(event.board_end_time or event.start_time)
        move_end = float(event.arrive_time or event.end_time)
        key = (event.facility_id, event.facility_kind, round(move_start, 2), round(move_end, 2))
        group = groups.setdefault(key, [])
        for passenger_id in event.passenger_ids:
            group.append((event.event_id, int(passenger_id)))

    slots: dict[tuple[int, int], tuple[int, int]] = {}
    for group in groups.values():
        group_size = len(group)
        for slot, item in enumerate(sorted(group)):
            slots[item] = (slot, group_size)
    return slots


def _vertical_service_visual_offsets(
    event: FacilityServiceEvent,
    slot: int,
    group_size: int,
) -> tuple[float, float]:
    if group_size <= 1:
        return 0.0, 0.0
    if event.facility_kind == FacilityKind.STAIRS.value:
        lane_count = 5
        lane_width_px = 5.5
        row_progress = 0.055
    elif event.facility_kind == FacilityKind.ESCALATOR.value:
        lane_count = 3
        lane_width_px = 4.0
        row_progress = 0.035
    else:
        return 0.0, 0.0

    active_lanes = min(group_size, lane_count)
    lane_index = slot % active_lanes
    centered_lane = lane_index - (active_lanes - 1) / 2
    row_index = slot // active_lanes
    return centered_lane * lane_width_px, min(0.16, row_index * row_progress)


def _smooth_facility_service_points(
    points: list[Any],
    event: FacilityServiceEvent,
    start_position: tuple[float, float],
    end_position: tuple[float, float],
    *,
    lane_offset_px: float = 0.0,
    progress_offset: float = 0.0,
    reason: str,
) -> None:
    move_start = float(event.board_end_time or event.start_time)
    move_end = float(event.arrive_time or event.end_time)
    if move_end <= move_start:
        return

    heading = math.atan2(end_position[1] - start_position[1], end_position[0] - start_position[0])
    for point in points:
        time_s = float(point[0])
        if time_s < move_start - 0.001 or time_s > move_end + 0.001:
            continue
        fraction = max(0.0, min(1.0, (time_s - move_start) / (move_end - move_start)))
        x, y = _service_visual_position(
            start_position,
            end_position,
            fraction,
            lane_offset_px=lane_offset_px,
            progress_offset=progress_offset,
        )
        target_x, target_y = _offset_point_normal(start_position, end_position, end_position, lane_offset_px)
        point[1] = round(x, 2)
        point[2] = round(y, 2)
        point[3] = round(heading, 4)
        point[5] = round(target_x, 2)
        point[6] = round(target_y, 2)
        point[7] = "targeting"
        point[8] = "target"
        point[9] = track_point_meta("interpolation", visual_only=True, reason=reason)

    for fraction in (0.25, 0.5, 0.75):
        time_s = move_start + (move_end - move_start) * fraction
        if _has_track_point_near(points, time_s):
            continue
        points.append(
            _service_waypoint(
                time_s,
                fraction,
                start_position,
                end_position,
                heading,
                lane_offset_px=lane_offset_px,
                progress_offset=progress_offset,
                reason=reason,
            )
        )
    points.sort(key=lambda point: float(point[0]))


def _service_waypoint(
    time_s: float,
    fraction: float,
    start_position: tuple[float, float],
    end_position: tuple[float, float],
    heading: float,
    *,
    lane_offset_px: float = 0.0,
    progress_offset: float = 0.0,
    reason: str,
) -> list[Any]:
    x, y = _service_visual_position(
        start_position,
        end_position,
        fraction,
        lane_offset_px=lane_offset_px,
        progress_offset=progress_offset,
    )
    target_x, target_y = _offset_point_normal(start_position, end_position, end_position, lane_offset_px)
    return [
        round(time_s, 2),
        round(x, 2),
        round(y, 2),
        round(heading, 4),
        0.94,
        round(target_x, 2),
        round(target_y, 2),
        "targeting",
        "target",
        track_point_meta("interpolation", visual_only=True, reason=reason),
    ]


def _service_visual_position(
    start_position: tuple[float, float],
    end_position: tuple[float, float],
    fraction: float,
    *,
    lane_offset_px: float,
    progress_offset: float,
) -> tuple[float, float]:
    adjusted_fraction = max(0.0, min(1.0, fraction + progress_offset))
    x, y = _lerp_point(start_position, end_position, adjusted_fraction)
    return _offset_point_normal(start_position, end_position, (x, y), lane_offset_px)


def _offset_point_normal(
    start_position: tuple[float, float],
    end_position: tuple[float, float],
    point: tuple[float, float],
    offset_px: float,
) -> tuple[float, float]:
    if abs(offset_px) <= 0.001:
        return point
    dx = end_position[0] - start_position[0]
    dy = end_position[1] - start_position[1]
    length = math.hypot(dx, dy)
    if length <= 0.001:
        return point
    x = point[0] - dy / length * offset_px
    y = point[1] + dx / length * offset_px
    return max(0.0, min(W, x)), max(0.0, min(H, y))


def _has_track_point_near(points: Sequence[Any], time_s: float) -> bool:
    return any(abs(float(point[0]) - time_s) <= 0.02 for point in points)


def _insert_gate_waypoints(
    points: list[Any],
    event: FacilityServiceEvent,
    gate_position: tuple[float, float],
    exit_position: tuple[float, float],
) -> None:
    segment_index = _track_segment_index(points, float(event.start_time))
    if segment_index is None:
        return

    previous = points[segment_index - 1]
    current = points[segment_index]
    previous_time = float(previous[0])
    current_time = float(current[0])
    span = current_time - previous_time
    if span <= 0.02:
        return

    gate_time = _clamped_waypoint_time(float(event.start_time), previous_time, current_time)
    exit_time = _clamped_waypoint_time(float(event.end_time), previous_time, current_time)
    min_gap = min(1.5, span * 0.3)
    if exit_time - gate_time < min_gap:
        gate_time = round(previous_time + span * 0.35, 2)
        exit_time = round(previous_time + span * 0.75, 2)
    if not previous_time < gate_time < exit_time < current_time:
        gate_time = round(previous_time + span * 0.45, 2)
        exit_time = round(previous_time + span * 0.88, 2)
        if not previous_time < gate_time < exit_time < current_time:
            return

    px, py = float(previous[1]), float(previous[2])
    cx, cy = float(current[1]), float(current[2])
    gate_visual, exit_visual = _gate_visual_positions(
        previous=(px, py),
        current=(cx, cy),
        gate_position=gate_position,
        exit_position=exit_position,
    )
    gate_heading = math.atan2(gate_visual[1] - py, gate_visual[0] - px)
    exit_heading = math.atan2(
        exit_visual[1] - gate_visual[1],
        exit_visual[0] - gate_visual[0],
    )
    target_x, target_y = round(exit_position[0], 2), round(exit_position[1], 2)
    inserted = [
        [
            gate_time,
            round(gate_visual[0], 2),
            round(gate_visual[1], 2),
            round(gate_heading, 4),
            0.94,
            target_x,
            target_y,
            "targeting",
            "target",
            track_point_meta("interpolation", visual_only=True, reason="gate_service_visual_smoothing"),
        ],
        [
            exit_time,
            round(exit_visual[0], 2),
            round(exit_visual[1], 2),
            round(exit_heading, 4),
            0.94,
            target_x,
            target_y,
            "targeting",
            "target",
            track_point_meta("interpolation", visual_only=True, reason="gate_service_visual_smoothing"),
        ],
    ]
    points[segment_index:segment_index] = inserted


def _clamped_waypoint_time(
    event_time: float,
    previous_time: float,
    current_time: float,
) -> float:
    span = max(0.0, current_time - previous_time)
    padding = min(1.75, max(0.01, span * 0.35))
    lower = previous_time + padding
    upper = current_time - padding
    return round(max(lower, min(upper, event_time)), 2)


def _gate_visual_positions(
    *,
    previous: tuple[float, float],
    current: tuple[float, float],
    gate_position: tuple[float, float],
    exit_position: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    direct = math.hypot(current[0] - previous[0], current[1] - previous[1])
    detour = (
        math.hypot(gate_position[0] - previous[0], gate_position[1] - previous[1])
        + math.hypot(exit_position[0] - gate_position[0], exit_position[1] - gate_position[1])
        + math.hypot(current[0] - exit_position[0], current[1] - exit_position[1])
    )
    if direct > 0.001 and detour > direct * 1.15:
        return (
            _lerp_point(previous, current, 0.45),
            _lerp_point(previous, current, 0.88),
        )
    return gate_position, exit_position


def _lerp_point(
    start: tuple[float, float],
    end: tuple[float, float],
    amount: float,
) -> tuple[float, float]:
    return (
        start[0] + (end[0] - start[0]) * amount,
        start[1] + (end[1] - start[1]) * amount,
    )


def _track_segment_index(points: list[Any], event_time: float) -> int | None:
    for index in range(1, len(points)):
        current_time = float(points[index][0])
        if current_time > event_time + 0.001:
            return index
    return None


def _facility_samples_from_frames(frames: Sequence[FrameSnapshot]) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    previous_served: dict[str, int] = {}
    previous_time: float | None = None
    for frame in frames:
        time_s = float(frame.time_seconds)
        dt = 0.0 if previous_time is None else max(0.0, time_s - previous_time)
        facilities: dict[str, dict[str, object]] = {}
        for facility in frame.facilities:
            served = int(facility.served_persons)
            served_delta = max(0, served - previous_served.get(facility.id, served))
            capacity_delta = facility.service_persons_per_min * dt / 60.0 if dt > 0 else 0.0
            utilization = served_delta / capacity_delta if capacity_delta > 0 else 0.0
            load_persons = int(facility.queue_persons) + int(facility.active_persons)
            pressure = load_persons / max(1, int(facility.queue_capacity))
            facilities[facility.id] = {
                "id": facility.id,
                "label": facility.label,
                "kind": facility.kind,
                "stage": facility.stage,
                "state": facility.state,
                "queue_persons": int(facility.queue_persons),
                "active_persons": int(facility.active_persons),
                "served_persons": served,
                "service_persons_per_min": round(float(facility.service_persons_per_min), 3),
                "queue_capacity": int(facility.queue_capacity),
                "served_delta": served_delta,
                "utilization": round(max(0.0, min(1.5, utilization)), 3),
                "pressure": round(max(0.0, min(2.0, pressure)), 3),
            }
            previous_served[facility.id] = served
        samples.append({"time": round(time_s, 2), "facilities": facilities})
        previous_time = time_s
    return samples


def _make_agent_record(
    passenger: PassengerSnapshot,
    rng: random.Random,
) -> dict[str, object]:
    passenger_id = int(passenger.id)
    intent = str(passenger.intent or "unknown")
    state = str(passenger.state or "unknown")
    return {
        "id": passenger_id,
        "source": "mesa_jupedsim",
        "route": intent,
        "route_chain": [intent, state],
        "group_id": passenger_id,
        "color": _color_for_intent(intent),
        "size": 0.86,
        "motion": {
            "phase": round(rng.random() * math.tau, 4),
            "wobble": round(0.8 + rng.random() * 0.35, 3),
            "stride_hz": round(1.25 + rng.random() * 0.45, 3),
        },
        "points": [],
    }


def _color_for_intent(intent: str) -> str:
    if intent == "exit_station":
        return "#4aa3ff"
    if intent == "transfer":
        return "#52d273"
    return "#f6b342"


def _canvas_position(
    position: tuple[float, float],
    scenario: StationSandboxScenario,
) -> tuple[float, float]:
    design = scenario.station_design
    width = float(
        design.constraints.canvas_width_m if design is not None else scenario.geometry.width
    )
    height = float(
        design.constraints.canvas_height_m if design is not None else scenario.geometry.height
    )
    return (
        max(0.0, min(W, position[0] / width * W)),
        max(0.0, min(H, position[1] / height * H)),
    )


def _passenger_goal_canvas_target(
    passenger: PassengerSnapshot,
    scenario: StationSandboxScenario,
) -> tuple[float, float] | None:
    goal = passenger.goal
    target = goal.get("target")
    if not isinstance(target, (list, tuple)) or len(target) < 2:
        return None
    try:
        return _canvas_position((float(target[0]), float(target[1])), scenario)
    except (TypeError, ValueError):
        return None


def _target_mode(passenger: PassengerSnapshot) -> str:
    goal = passenger.goal
    state = str(passenger.state)
    goal_kind = str(goal.get("kind", ""))
    if state == AgentState.WAITING_PLATFORM.value or goal_kind == "waiting":
        return "waiting"
    if state in _QUEUE_STATES or goal_kind == "queued":
        return "enqueued"
    return "targeting"


def _diagnostic_code(
    passenger: PassengerSnapshot,
    speed_px_s: float | None,
    target: tuple[float, float] | None,
) -> str:
    goal = passenger.goal
    state = str(passenger.state)
    goal_kind = str(goal.get("kind", ""))
    if state == AgentState.WAITING_PLATFORM.value or goal_kind == "waiting":
        return "platform_wait"
    if state in _QUEUE_STATES or goal_kind == "queued":
        return "queue"
    if speed_px_s is not None and speed_px_s <= 4.0:
        return "slow"
    if target is not None:
        return "target"
    return "walk"


def _diagnostic_sample_from_frame(
    frame: FrameSnapshot,
    counts: dict[str, int],
) -> dict[str, object]:
    metrics = frame.metrics.to_dict()
    return {
        "time": round(float(frame.time_seconds), 2),
        "counts": counts,
        "average_walk_speed_factor": round(
            float(metrics.get("average_walk_speed_factor", 1.0) or 1.0),
            4,
        ),
        "platform_waiting_persons": int(metrics.get("platform_waiting_persons", 0) or 0),
    }


def _duration(frames: Sequence[FrameSnapshot], scenario: StationSandboxScenario) -> float:
    if frames:
        return round(float(frames[-1].time_seconds), 2)
    return round(float(scenario.minutes) * 60.0, 2)


def _person_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    return int(value or 0)


def _queue_sample_from_frame(
    frame: FrameSnapshot,
    queue_ids: set[str],
) -> dict[str, object]:
    metrics = frame.metrics.to_dict()
    queues = {queue_id: {"enqueued": 0, "targeting": 0} for queue_id in queue_ids}
    for passenger in frame.passengers:
        goal = passenger.goal
        facility_id = goal.get("facility_id")
        if not facility_id:
            continue
        queue_id = _queue_id(str(facility_id))
        if queue_id not in queues:
            continue
        count = int(passenger.n or 1)
        state = str(passenger.state)
        goal_kind = str(goal.get("kind", ""))
        if goal_kind == "queued" or state in _QUEUE_STATES:
            queues[queue_id]["enqueued"] += count
        elif goal_kind in {"walk", "waiting"}:
            queues[queue_id]["targeting"] += count

    if queues:
        return {
            "time": round(float(frame.time_seconds), 2),
            "queues": queues,
        }

    return {
        "time": round(float(frame.time_seconds), 2),
        "queues": {
            "entry_gate_mesa": {
                "enqueued": int(metrics.get("gate_queue_persons", 0) or 0),
                "targeting": 0,
            },
            "vertical_mesa": {
                "enqueued": int(metrics.get("vertical_queue_persons", 0) or 0),
                "targeting": 0,
            },
            "boarding_door_mesa": {
                "enqueued": int(metrics.get("door_queue_persons", 0) or 0),
                "targeting": int(metrics.get("platform_waiting_persons", 0) or 0),
            },
        },
    }


def _mesa_queue_layout_payload(
    facilities: Iterable[Any] | None,
    scenario: StationSandboxScenario,
) -> list[dict[str, object]]:
    if facilities is None:
        return []
    return [
        _facility_queue_layout_payload(facility.spec, scenario)
        for facility in facilities
        if getattr(facility, "spec", None) is not None
    ]


def _facility_queue_layout_payload(
    spec: Any, scenario: StationSandboxScenario
) -> dict[str, object]:
    slots = _queue_slots_for_spec(spec)
    return {
        "id": _queue_id(str(spec.facility_id)),
        "role": "queue",
        "kind": _queue_kind(str(spec.stage)),
        "layer": "queues",
        "color": _queue_color(str(spec.stage)),
        "head": list(_normalized_position(spec.queue_layout.anchor, scenario)),
        "exit": list(_normalized_position(spec.position, scenario)),
        "lanes": int(spec.queue_layout.per_row),
        "capacity": len(slots),
        "slots": [list(_normalized_position(point, scenario)) for point in slots],
        "geometry": {
            "type": "mesa_queue_layout",
            "facility_id": spec.facility_id,
            "stage": spec.stage,
        },
    }


def _queue_slots_for_spec(spec: Any) -> tuple[tuple[float, float], ...]:
    if spec.queue_layout.slots:
        return tuple(spec.queue_layout.slots)
    count = max(8, min(96, int(spec.queue_layout.per_row) * 4))
    return tuple(spec.queue_layout.slot(index) for index in range(count))


def _normalized_position(
    position: tuple[float, float],
    scenario: StationSandboxScenario,
) -> tuple[float, float]:
    design = scenario.station_design
    width = float(
        design.constraints.canvas_width_m if design is not None else scenario.geometry.width
    )
    height = float(
        design.constraints.canvas_height_m if design is not None else scenario.geometry.height
    )
    return (
        round(max(0.0, min(1.0, position[0] / width)), 5),
        round(max(0.0, min(1.0, position[1] / height)), 5),
    )


def _queue_id(facility_id: str) -> str:
    return facility_id.replace(":", "_")


def _queue_kind(stage: str) -> str:
    if stage == FacilityStage.BOARDING_DOOR.value:
        return "boarding"
    if stage == FacilityStage.VERTICAL_TRANSFER.value:
        return "vertical"
    if stage == FacilityStage.EXIT_GATE.value:
        return "exit_gate"
    return "entry_gate"


def _queue_color(stage: str) -> str:
    if stage == FacilityStage.EXIT_GATE.value:
        return "#4aa3ff"
    if stage == FacilityStage.VERTICAL_TRANSFER.value:
        return "#5dd45f"
    if stage == FacilityStage.BOARDING_DOOR.value:
        return "#ff66cc"
    return "#ffd166"


_QUEUE_STATES = {
    AgentState.QUEUEING_GATE.value,
    AgentState.QUEUEING_VERTICAL.value,
    AgentState.QUEUEING_DOOR.value,
    AgentState.QUEUEING_EXIT_GATE.value,
}
