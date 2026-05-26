from __future__ import annotations

import json
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..agent_plan import AgentState, FacilityStage
from ..scenario import StationSandboxScenario
from ..snapshots import FrameSnapshot, PassengerSnapshot, TrainSnapshot
from .config import H, SAMPLE_DT, TRACKS_JS, W
from .facilities import elevator_payload
from .layout import layout_payload


FrameInput = FrameSnapshot | Mapping[str, Any]


def write_mesa_visual_tracks_js(
    *,
    frames: Sequence[FrameInput],
    scenario: StationSandboxScenario,
    output_path: Path = TRACKS_JS,
    facilities: Iterable[Any] | None = None,
) -> dict[str, object]:
    payload = mesa_frames_to_visual_tracks(
        frames=frames,
        scenario=scenario,
        facilities=facilities,
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
) -> dict[str, object]:
    frame_snapshots = tuple(FrameSnapshot.from_any(frame) for frame in frames)
    duration = _duration(frame_snapshots, scenario)
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
                ]
            )
        diagnostic_samples.append(_diagnostic_sample_from_frame(frame, diagnostic_counts))

    agents = [record for record in agents_by_id.values() if len(record.get("points", [])) >= 2]
    queue_samples = [_queue_sample_from_frame(frame, queue_ids) for frame in frame_snapshots]
    final_metrics = frame_snapshots[-1].metrics.to_dict() if frame_snapshots else {}
    completed_agents = int(final_metrics.get("boarded_persons", 0) or 0) + int(
        final_metrics.get("exit_gate_served_persons", 0) or 0
    )
    return {
        "generated_by": "Mesa MetroStationModel + JuPedSim movement backend + animation_demo renderer",
        "geometry": "mesa_model_frames_scaled_to_animation_demo_canvas",
        "scenario": _scenario_payload(scenario, final_metrics),
        "train_service": _train_service_payload(scenario),
        "layout": layout_payload(),
        "facilities": {"elevator": elevator_payload(W, H)},
        "queue_layouts": queue_layouts,
        "duration": duration,
        "sample_dt": SAMPLE_DT,
        "clearance_audit": {
            "demand_duration_s": round(float(scenario.minutes) * 60.0, 2),
            "max_duration_s": duration,
            "final_time_s": duration,
            "cleared": len(final_metrics.get("station_persons", [])) == 0
            if isinstance(final_metrics.get("station_persons"), list)
            else final_metrics.get("station_persons", 0) == 0,
            "completed_agents": completed_agents,
            "remaining_agents": int(final_metrics.get("station_persons", 0) or 0),
            "skipped_agents": 0,
            "total_agents": int(final_metrics.get("spawned_persons", len(agents)) or len(agents)),
        },
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
        "train_samples": _train_samples_from_frames(frame_snapshots),
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
