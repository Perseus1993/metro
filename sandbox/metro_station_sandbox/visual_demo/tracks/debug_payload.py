from __future__ import annotations

from collections.abc import Iterable
import math

import jupedsim as jps

from ..config import CLEARANCE_MAX_DURATION, SIM_DURATION
from ..queue_runtime import NativeQueueRuntime, normalized_from_meters
from ..specs import SpawnSpec
from .types import StageInfo, StageRegistry


def append_point(
    track: list[list[float]],
    time: float,
    x: float,
    y: float,
    angle: float,
    alpha: float,
    target: tuple[float, float] | None = None,
    target_mode: str | None = None,
) -> None:
    sample = [round(time, 2), round(x, 2), round(y, 2), round(angle, 4), round(alpha, 3)]
    if target is not None:
        sample.extend([round(target[0], 2), round(target[1], 2)])
        if target_mode is not None:
            sample.append(target_mode)
    track.append(sample)


def angle(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def sample_simulation_debug(
    sim: jps.Simulation,
    runtimes: Iterable[NativeQueueRuntime],
    sim_to_track: dict[int, int],
    stage_registry: StageRegistry,
    time: float,
) -> dict[str, object]:
    runtime_by_stage = {runtime.stage_id: runtime for runtime in runtimes}
    enqueued_by_stage: dict[int, set[int]] = {}
    for runtime in runtime_by_stage.values():
        stage = sim.get_stage(runtime.stage_id)
        enqueued_by_stage[runtime.stage_id] = {int(agent_id) for agent_id in stage.enqueued()}

    agents: list[dict[str, object]] = []
    facility_counts: dict[str, dict[str, int]] = {}
    stage_counts: dict[str, dict[str, object]] = {}
    for agent in sim.agents():
        sim_id = int(agent.id)
        stage_id = int(agent.stage_id)
        runtime = runtime_by_stage.get(stage_id)
        stage_info = stage_registry.get(stage_id)
        enqueued = sim_id in enqueued_by_stage.get(stage_id, set())
        queue_facility = runtime.name if runtime is not None else None
        facility = (
            queue_facility
            if queue_facility is not None
            else (stage_info.facility if stage_info else None)
        )
        stage_label = stage_info.label if stage_info is not None else f"stage_{stage_id}"
        stage_kind = stage_info.kind if stage_info is not None else "unknown"
        location = queue_facility if queue_facility is not None else stage_label
        queue_mode = visual_queue_mode(runtime, sim_id, enqueued)
        behavior_action = visual_behavior_action(stage_info, runtime, sim_id, enqueued)
        region_goal = visual_region_goal(stage_label, facility)
        current_region = visual_current_region(stage_label, stage_kind, facility)
        target_region = visual_target_region(stage_label, stage_kind, facility)
        if queue_facility is not None:
            counts = facility_counts.setdefault(
                queue_facility, {"total": 0, "enqueued": 0, "targeting": 0}
            )
            counts["total"] += 1
            counts["enqueued" if enqueued else "targeting"] += 1
        counts_by_stage = stage_counts.setdefault(
            stage_label,
            {
                "stage_id": stage_id,
                "kind": stage_kind,
                "facility": facility,
                "total": 0,
                "enqueued": 0,
                "targeting": 0,
            },
        )
        counts_by_stage["total"] = int(counts_by_stage["total"]) + 1
        key = "enqueued" if enqueued else "targeting"
        counts_by_stage[key] = int(counts_by_stage[key]) + 1
        agents.append(
            {
                "sim_id": sim_id,
                "track_id": sim_to_track.get(sim_id),
                "journey_id": int(agent.journey_id),
                "stage_id": stage_id,
                "stage_label": stage_label,
                "stage_kind": stage_kind,
                "stage_radius_m": (
                    round(stage_info.radius_m, 3)
                    if stage_info is not None and stage_info.radius_m is not None
                    else None
                ),
                "stage_point": (
                    normalized_from_meters(stage_info.point_m)
                    if stage_info is not None and stage_info.point_m is not None
                    else None
                ),
                "facility": facility,
                "location": location,
                "enqueued": enqueued,
                "behavior_action": behavior_action,
                "queue_mode": queue_mode,
                "region_goal": region_goal,
                "current_region": current_region,
                "target_region": target_region,
                "x": round(float(agent.position[0]), 3),
                "y": round(float(agent.position[1]), 3),
            }
        )
    return {
        "time": round(time, 2),
        "agent_count": len(agents),
        "facility_counts": facility_counts,
        "stage_counts": stage_counts,
        "agents": agents,
    }


def visual_queue_mode(
    runtime: NativeQueueRuntime | None,
    sim_id: int,
    enqueued: bool,
) -> str | None:
    if runtime is None:
        return None
    if enqueued:
        return "enqueued"
    if sim_id in runtime.virtual_queue_order:
        return "virtual_queue"
    return "targeting"


def visual_behavior_action(
    stage_info: StageInfo | None,
    runtime: NativeQueueRuntime | None,
    sim_id: int,
    enqueued: bool,
) -> str:
    if stage_info is not None and stage_info.kind == "exit":
        return "depart"
    if runtime is not None:
        if enqueued:
            return "wait_in_queue"
        return "walk_to_queue_tail"
    if stage_info is None:
        return "unknown"
    label = stage_info.label.lower()
    if "boarding_door" in label and ("vestibule" in label or "train_exit" in label):
        return "board_train"
    if stage_info.facility is not None and ("release" in label or "exit" in label):
        return "use_facility"
    if stage_info.kind == "waypoint":
        return "walk_to_region"
    return "unknown"


def visual_region_goal(stage_label: str, facility: str | None = None) -> dict[str, object]:
    facility_name = facility or ""
    if stage_label.startswith("alighting.") or "exit_gate" in facility_name:
        return {
            "intent": "exit_station",
            "origin_region": "train_platform",
            "destination_region": "station_exit",
            "via_regions": ["vertical_transfer", "exit_gate"],
        }
    if facility_name.startswith("up_"):
        return {
            "intent": "exit_station",
            "origin_region": "train_platform",
            "destination_region": "station_exit",
            "via_regions": ["vertical_transfer", "exit_gate"],
        }
    if (
        stage_label.startswith("entry.")
        or "boarding_door" in facility_name
        or facility_name.startswith("down_")
        or ("gate" in facility_name and "exit_gate" not in facility_name)
    ):
        return {
            "intent": "enter_and_board",
            "origin_region": "station_entrance",
            "destination_region": "train_interior",
            "via_regions": ["entry_gate", "vertical_transfer", "platform", "boarding_door"],
        }
    return {
        "intent": "unknown",
        "origin_region": "unknown",
        "destination_region": "unknown",
        "via_regions": [],
    }


def visual_current_region(
    stage_label: str,
    stage_kind: str,
    facility: str | None,
) -> str:
    label = stage_label.lower()
    if stage_kind == "exit":
        return "outside_or_train"
    if facility is not None:
        if "exit_gate" in facility:
            return "exit_concourse"
        if "gate" in facility:
            return "unpaid_concourse"
        if "escalator" in facility or "stairs" in facility or "elevator" in facility:
            return "vertical_transfer"
        if "boarding_door" in facility:
            return "platform"
    if "platform" in label or "boarding" in label:
        return "platform"
    if "transfer" in label or "escalator" in label or "stairs" in label or "elevator" in label:
        return "vertical_transfer"
    if "exit_gate" in label:
        return "exit_concourse"
    if "gate" in label:
        return "unpaid_concourse"
    if "entry" in label:
        return "station_entrance"
    return "unknown"


def visual_target_region(
    stage_label: str,
    stage_kind: str,
    facility: str | None,
) -> str | None:
    label = stage_label.lower()
    if stage_kind == "exit":
        return None
    if facility is not None:
        if "boarding_door" in facility:
            return "boarding_door"
        if "exit_gate" in facility:
            return "exit_gate"
        if "gate" in facility:
            return "entry_gate"
        if "escalator" in facility or "stairs" in facility or "elevator" in facility:
            return "vertical_transfer"
    if "platform" in label:
        return "platform"
    if "transfer" in label or "escalator" in label or "stairs" in label or "elevator" in label:
        return "vertical_transfer"
    if "exit" in label:
        return "station_exit"
    if "gate" in label:
        return "entry_gate"
    return "walkable_region"


def build_stuck_report(
    debug_samples: list[dict[str, object]],
    debug_events: list[dict[str, object]],
) -> dict[str, object]:
    event_counts: dict[str, int] = {}
    events_by_sim: dict[int, list[dict[str, object]]] = {}
    for event in debug_events:
        event_type = str(event.get("type", "unknown"))
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
        sim_id = event.get("sim_id")
        if isinstance(sim_id, int):
            events_by_sim.setdefault(sim_id, []).append(event)

    records_by_sim: dict[int, list[tuple[float, dict[str, object]]]] = {}
    for sample in debug_samples:
        time = float(sample["time"])
        agents = sample.get("agents", [])
        if not isinstance(agents, list):
            continue
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            if agent.get("enqueued"):
                continue
            facility = agent.get("facility")
            location = str(
                agent.get("location")
                or facility
                or agent.get("stage_label")
                or f"stage_{agent.get('stage_id')}"
            )
            sim_id = int(agent["sim_id"])
            records_by_sim.setdefault(sim_id, []).append((time, agent))
            agent["location"] = location

    stuck_windows: list[dict[str, object]] = []
    window_seconds = 7.0
    max_displacement_m = 0.35
    for sim_id, records in records_by_sim.items():
        if len(records) < 2:
            continue
        reported = False
        for start_index, (start_time, start_agent) in enumerate(records):
            start_facility = start_agent.get("facility")
            start_location = start_agent.get("location", start_facility)
            start_track = start_agent.get("track_id")
            start_x = float(start_agent["x"])
            start_y = float(start_agent["y"])
            for end_time, end_agent in records[start_index + 1 :]:
                if end_time - start_time < window_seconds:
                    continue
                if (
                    end_agent.get("location", end_agent.get("facility")) != start_location
                    or end_agent.get("track_id") != start_track
                ):
                    break
                displacement = math.hypot(
                    float(end_agent["x"]) - start_x, float(end_agent["y"]) - start_y
                )
                if displacement <= max_displacement_m:
                    resolving_event = next(
                        (
                            event
                            for event in events_by_sim.get(sim_id, [])
                            if float(event.get("time", -1.0)) >= end_time
                            and event.get("type") in {"service_release", "behavior_replan"}
                        ),
                        None,
                    )
                    stuck_windows.append(
                        {
                            "sim_id": sim_id,
                            "track_id": start_track,
                            "facility": start_facility,
                            "location": start_location,
                            "stage_id": start_agent.get("stage_id"),
                            "stage_label": start_agent.get("stage_label"),
                            "stage_kind": start_agent.get("stage_kind"),
                            "stage_radius_m": start_agent.get("stage_radius_m"),
                            "stage_point": start_agent.get("stage_point"),
                            "behavior_action": start_agent.get("behavior_action"),
                            "queue_mode": start_agent.get("queue_mode"),
                            "current_region": start_agent.get("current_region"),
                            "target_region": start_agent.get("target_region"),
                            "region_goal": start_agent.get("region_goal"),
                            "from": round(start_time, 2),
                            "to": round(end_time, 2),
                            "duration": round(end_time - start_time, 2),
                            "displacement_m": round(displacement, 3),
                            "resolved_by": resolving_event.get("type")
                            if resolving_event is not None
                            else None,
                            "resolved_at": resolving_event.get("time")
                            if resolving_event is not None
                            else None,
                        }
                    )
                    reported = True
                break
            if reported:
                break

    last_live_by_facility: dict[str, dict[str, int]] = {}
    last_live_by_stage: dict[str, dict[str, object]] = {}
    last_live_ids: set[int] = set()
    if debug_samples:
        last_agents = debug_samples[-1].get("agents", [])
        if isinstance(last_agents, list):
            for agent in last_agents:
                if isinstance(agent, dict) and isinstance(agent.get("sim_id"), int):
                    last_live_ids.add(int(agent["sim_id"]))
        last_counts = debug_samples[-1].get("facility_counts", {})
        if isinstance(last_counts, dict):
            for facility, counts in last_counts.items():
                if isinstance(counts, dict):
                    last_live_by_facility[str(facility)] = {
                        "total": int(counts.get("total", 0)),
                        "enqueued": int(counts.get("enqueued", 0)),
                        "targeting": int(counts.get("targeting", 0)),
                    }
        last_stage_counts = debug_samples[-1].get("stage_counts", {})
        if isinstance(last_stage_counts, dict):
            for label, counts in last_stage_counts.items():
                if isinstance(counts, dict):
                    total = int(counts.get("total", 0))
                    if total <= 0:
                        continue
                    last_live_by_stage[str(label)] = {
                        "stage_id": int(counts.get("stage_id", -1)),
                        "kind": str(counts.get("kind", "unknown")),
                        "facility": counts.get("facility"),
                        "total": total,
                        "enqueued": int(counts.get("enqueued", 0)),
                        "targeting": int(counts.get("targeting", 0)),
                    }

    stuck_windows.sort(key=lambda item: (-float(item["duration"]), str(item["facility"])))
    unresolved = [
        item
        for item in stuck_windows
        if item.get("resolved_by") is None and int(item["sim_id"]) in last_live_ids
    ]
    return {
        "event_counts": event_counts,
        "all_stuck_window_count": len(stuck_windows),
        "resolved_stuck_window_count": len(stuck_windows) - len(unresolved),
        "stuck_window_count": len(unresolved),
        "stuck_windows": unresolved[:80],
        "resolved_stuck_windows": stuck_windows[:80],
        "last_live_by_facility": last_live_by_facility,
        "last_live_by_stage": last_live_by_stage,
    }


def sample_queue_metrics(
    sim: jps.Simulation, runtimes: Iterable[NativeQueueRuntime]
) -> dict[str, dict[str, int]]:
    snapshot: dict[str, dict[str, int]] = {}
    for runtime in runtimes:
        stage = sim.get_stage(runtime.stage_id)
        snapshot[runtime.name] = {
            "enqueued": int(stage.count_enqueued()),
            "targeting": int(stage.count_targeting()),
        }
    return snapshot


def track_source(route_name: str) -> str:
    if route_name.startswith("alighting_"):
        return "jupedsim_exit_queue"
    if route_name.startswith("boarding_door") or route_name.startswith("entry_to_train_door"):
        return "jupedsim_boarding_queue"
    if route_name.startswith("entry_") or route_name.startswith("gate_to_"):
        return "jupedsim_gate_queue"
    return "jupedsim"


def make_track_record(spawn: SpawnSpec) -> dict[str, object]:
    return {
        "id": spawn.agent_id,
        "source": track_source(spawn.route_name),
        "route": spawn.route_name,
        "route_chain": [spawn.route_name],
        "group_id": spawn.group_id,
        "color": spawn.color,
        "size": spawn.size,
        "radius": round(spawn.radius, 3),
        "time_gap": round(spawn.time_gap, 3),
        "motion": {
            "phase": round(spawn.motion_phase, 4),
            "wobble": round(spawn.motion_wobble, 3),
            "stride_hz": round(spawn.stride_hz, 3),
        },
        "points": [],
    }


def route_family(route_name: str) -> str:
    if route_name.startswith("entry_right"):
        return "entry_right"
    if route_name.startswith("entry_left"):
        return "entry_left"
    if route_name.startswith("alighting_"):
        return "alighting"
    return "other"


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    index = (len(ordered) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return round(ordered[lower], 2)
    weight = index - lower
    return round(ordered[lower] * (1.0 - weight) + ordered[upper] * weight, 2)


def track_duration_s(record: dict[str, object]) -> float | None:
    points = record.get("points", [])
    if not isinstance(points, list) or not points:
        return None
    first = points[0]
    last = points[-1]
    if not isinstance(first, list) or not isinstance(last, list):
        return None
    return round(float(last[0]) - float(first[0]), 2)


def build_clearance_audit(
    *,
    tracks: dict[int, dict[str, object]],
    spawns: list[SpawnSpec],
    live_track_ids: set[int],
    pending: list[SpawnSpec],
    final_time: float,
) -> dict[str, object]:
    pending_track_ids = {spawn.agent_id for spawn in pending}
    live_or_pending = live_track_ids | pending_track_ids
    skipped_track_ids = {
        track_id for track_id, record in tracks.items() if bool(record.get("skipped"))
    }
    observed_track_ids = {
        track_id
        for track_id, record in tracks.items()
        if isinstance(record.get("points"), list) and bool(record.get("points"))
    }
    completed_track_ids = observed_track_ids - live_or_pending - skipped_track_ids
    remaining_track_ids = live_or_pending | (set(tracks) - observed_track_ids - skipped_track_ids)

    def duration_stats(track_ids: set[int]) -> dict[str, float | None]:
        durations = [
            duration
            for track_id in track_ids
            if (duration := track_duration_s(tracks[track_id])) is not None
        ]
        return {
            "p50_s": percentile(durations, 0.50),
            "p90_s": percentile(durations, 0.90),
            "p95_s": percentile(durations, 0.95),
            "max_s": round(max(durations), 2) if durations else None,
        }

    ids_by_family: dict[str, set[int]] = {}
    for spawn in spawns:
        ids_by_family.setdefault(route_family(spawn.route_name), set()).add(spawn.agent_id)

    by_family: dict[str, dict[str, object]] = {}
    for family, family_ids in sorted(ids_by_family.items()):
        family_completed = family_ids & completed_track_ids
        family_remaining = family_ids & remaining_track_ids
        family_skipped = family_ids & skipped_track_ids
        by_family[family] = {
            "total": len(family_ids),
            "completed": len(family_completed),
            "remaining": len(family_remaining),
            "skipped": len(family_skipped),
            "duration": duration_stats(family_ids - family_skipped),
            "completed_duration": duration_stats(family_completed),
        }

    cleared = not remaining_track_ids and not skipped_track_ids
    return {
        "demand_duration_s": round(SIM_DURATION, 2),
        "max_duration_s": round(CLEARANCE_MAX_DURATION, 2),
        "final_time_s": round(final_time, 2),
        "cleared": cleared,
        "clearance_time_s": round(final_time, 2) if cleared else None,
        "total_agents": len(spawns),
        "observed_agents": len(observed_track_ids),
        "completed_agents": len(completed_track_ids),
        "remaining_agents": len(remaining_track_ids),
        "skipped_agents": len(skipped_track_ids),
        "live_agents": len(live_track_ids),
        "pending_agents": len(pending_track_ids),
        "duration": duration_stats(observed_track_ids),
        "completed_duration": duration_stats(completed_track_ids),
        "by_family": by_family,
    }
