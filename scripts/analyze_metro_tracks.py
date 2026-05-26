from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    REPO_ROOT
    / "sandbox"
    / "metro_station_sandbox"
    / "visual_demo"
    / "assets"
    / "passenger_tracks_jps.js"
)
DEFAULT_CANVAS_WIDTH = 1672.0
DEFAULT_CANVAS_HEIGHT = 941.0
DEFAULT_PX_PER_METER = 20.0
ASSIGNMENT_RE = re.compile(r"(?:window\.)?JPS_TRACKS\s*=")


@dataclass(frozen=True)
class TrackSample:
    time: float
    x: float
    y: float


@dataclass(frozen=True)
class TrackRecord:
    track_id: str
    route: str
    source: str
    samples: tuple[TrackSample, ...]


@dataclass(frozen=True)
class AnalysisConfig:
    grid_size_px: float = 80.0
    slow_speed_m_s: float = 0.20
    stationary_speed_m_s: float = 0.03
    px_per_meter: float = DEFAULT_PX_PER_METER
    canvas_width: float = DEFAULT_CANVAS_WIDTH
    canvas_height: float = DEFAULT_CANVAS_HEIGHT
    top_n: int = 15

    @property
    def slow_speed_px_s(self) -> float:
        return self.slow_speed_m_s * self.px_per_meter

    @property
    def stationary_speed_px_s(self) -> float:
        return self.stationary_speed_m_s * self.px_per_meter


@dataclass
class MotionAggregate:
    total_segments: int = 0
    total_duration_s: float = 0.0
    total_distance_px: float = 0.0
    slow_segments: int = 0
    slow_duration_s: float = 0.0
    stationary_segments: int = 0
    stationary_duration_s: float = 0.0
    agent_ids: set[str] = field(default_factory=set)
    slow_agent_ids: set[str] = field(default_factory=set)
    stationary_agent_ids: set[str] = field(default_factory=set)

    def add(
        self,
        *,
        track_id: str,
        duration_s: float,
        distance_px: float,
        is_slow: bool,
        is_stationary: bool,
    ) -> None:
        self.total_segments += 1
        self.total_duration_s += duration_s
        self.total_distance_px += distance_px
        self.agent_ids.add(track_id)
        if is_slow:
            self.slow_segments += 1
            self.slow_duration_s += duration_s
            self.slow_agent_ids.add(track_id)
        if is_stationary:
            self.stationary_segments += 1
            self.stationary_duration_s += duration_s
            self.stationary_agent_ids.add(track_id)

    def as_dict(self, px_per_meter: float) -> dict[str, object]:
        mean_speed_px_s = (
            self.total_distance_px / self.total_duration_s if self.total_duration_s > 0 else 0.0
        )
        return {
            "total_segments": self.total_segments,
            "total_duration_s": round_float(self.total_duration_s),
            "total_distance_px": round_float(self.total_distance_px),
            "total_distance_m": round_float(self.total_distance_px / px_per_meter),
            "mean_speed_m_s": round_float(mean_speed_px_s / px_per_meter),
            "slow_segments": self.slow_segments,
            "slow_duration_s": round_float(self.slow_duration_s),
            "slow_duration_share": ratio(self.slow_duration_s, self.total_duration_s),
            "slow_agents": len(self.slow_agent_ids),
            "stationary_segments": self.stationary_segments,
            "stationary_duration_s": round_float(self.stationary_duration_s),
            "stationary_duration_share": ratio(self.stationary_duration_s, self.total_duration_s),
            "stationary_agents": len(self.stationary_agent_ids),
            "agents": len(self.agent_ids),
        }


@dataclass
class CellStats:
    active_observations: int = 0
    point_agent_ids: set[str] = field(default_factory=set)
    segment_count: int = 0
    segment_duration_s: float = 0.0
    slow_segments: int = 0
    slow_duration_s: float = 0.0
    stationary_segments: int = 0
    stationary_duration_s: float = 0.0
    segment_agent_ids: set[str] = field(default_factory=set)
    routes: Counter[str] = field(default_factory=Counter)

    def add_point(self, track_id: str) -> None:
        self.active_observations += 1
        self.point_agent_ids.add(track_id)

    def add_segment(
        self,
        *,
        track_id: str,
        route: str,
        duration_s: float,
        is_slow: bool,
        is_stationary: bool,
    ) -> None:
        self.segment_count += 1
        self.segment_duration_s += duration_s
        self.segment_agent_ids.add(track_id)
        self.routes[route] += 1
        if is_slow:
            self.slow_segments += 1
            self.slow_duration_s += duration_s
        if is_stationary:
            self.stationary_segments += 1
            self.stationary_duration_s += duration_s


@dataclass
class QueueSampleStats:
    samples: int = 0
    enqueued_sum: int = 0
    targeting_sum: int = 0
    total_sum: int = 0
    max_enqueued: int = 0
    max_targeting: int = 0
    max_total: int = 0
    max_total_time: float | None = None
    last_enqueued: int = 0
    last_targeting: int = 0
    last_total: int = 0

    def add(self, *, time: float, enqueued: int, targeting: int) -> None:
        total = enqueued + targeting
        self.samples += 1
        self.enqueued_sum += enqueued
        self.targeting_sum += targeting
        self.total_sum += total
        self.last_enqueued = enqueued
        self.last_targeting = targeting
        self.last_total = total
        self.max_enqueued = max(self.max_enqueued, enqueued)
        self.max_targeting = max(self.max_targeting, targeting)
        if total > self.max_total:
            self.max_total = total
            self.max_total_time = time


def round_float(value: float, digits: int = 3) -> float:
    rounded = round(float(value), digits)
    if rounded == -0.0:
        return 0.0
    return rounded


def ratio(part: float, whole: float) -> float:
    return round_float(part / whole, 4) if whole > 0 else 0.0


def parse_jps_tracks_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        payload = json.loads(stripped)
    else:
        match = ASSIGNMENT_RE.search(text)
        if match is None:
            raise ValueError("could not find window.JPS_TRACKS assignment")
        rhs = text[match.end() :].lstrip()
        payload, index = json.JSONDecoder().raw_decode(rhs)
        trailing = rhs[index:].strip()
        if trailing and not trailing.startswith(";"):
            raise ValueError("unexpected text after JPS_TRACKS JSON payload")

    if not isinstance(payload, dict):
        raise ValueError("JPS_TRACKS payload must be a JSON object")
    return payload


def load_payload(path: Path) -> dict[str, Any]:
    return parse_jps_tracks_text(path.read_text(encoding="utf-8-sig"))


def extract_track_records(payload: dict[str, Any]) -> list[TrackRecord]:
    agents_obj = payload.get("agents", payload.get("tracks"))
    if not isinstance(agents_obj, list):
        raise ValueError("payload must contain an 'agents' or 'tracks' list")

    records: list[TrackRecord] = []
    for index, agent_obj in enumerate(agents_obj):
        if not isinstance(agent_obj, dict):
            continue
        points_obj = agent_obj.get("points")
        if not isinstance(points_obj, list):
            continue

        samples: list[TrackSample] = []
        for point_obj in points_obj:
            if not isinstance(point_obj, list | tuple) or len(point_obj) < 3:
                continue
            try:
                time = float(point_obj[0])
                x = float(point_obj[1])
                y = float(point_obj[2])
            except (TypeError, ValueError):
                continue
            samples.append(TrackSample(time=time, x=x, y=y))

        if not samples:
            continue
        samples.sort(key=lambda item: item.time)
        raw_id = agent_obj.get("id", agent_obj.get("track_id", index))
        records.append(
            TrackRecord(
                track_id=str(raw_id),
                route=str(agent_obj.get("route", "unknown")),
                source=str(agent_obj.get("source", "unknown")),
                samples=tuple(samples),
            )
        )
    return records


def build_report(
    payload: dict[str, Any],
    *,
    input_path: Path | None,
    config: AnalysisConfig,
) -> dict[str, Any]:
    tracks = extract_track_records(payload)
    if not tracks:
        raise ValueError("no tracks with usable points found")

    active_counter: Counter[float] = Counter()
    overall_motion = MotionAggregate()
    motion_by_route: defaultdict[str, MotionAggregate] = defaultdict(MotionAggregate)
    cell_stats: defaultdict[tuple[int, int], CellStats] = defaultdict(CellStats)
    route_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    per_agent_stats: list[dict[str, object]] = []
    sample_count = 0
    time_min = math.inf
    time_max = -math.inf

    for track in tracks:
        route_counts[track.route] += 1
        source_counts[track.source] += 1
        sample_count += len(track.samples)
        time_min = min(time_min, track.samples[0].time)
        time_max = max(time_max, track.samples[-1].time)

        agent_motion = MotionAggregate()
        for sample in track.samples:
            active_counter[round_float(sample.time, 6)] += 1
            cell_stats[cell_index(sample.x, sample.y, config.grid_size_px)].add_point(
                track.track_id
            )

        for previous, current in zip(track.samples, track.samples[1:], strict=False):
            dt = current.time - previous.time
            if dt <= 0:
                continue
            distance_px = math.hypot(current.x - previous.x, current.y - previous.y)
            speed_px_s = distance_px / dt
            is_stationary = speed_px_s <= config.stationary_speed_px_s
            is_slow = is_stationary or speed_px_s <= config.slow_speed_px_s
            for aggregate in (
                overall_motion,
                motion_by_route[track.route],
                agent_motion,
            ):
                aggregate.add(
                    track_id=track.track_id,
                    duration_s=dt,
                    distance_px=distance_px,
                    is_slow=is_slow,
                    is_stationary=is_stationary,
                )

            midpoint_x = (previous.x + current.x) / 2.0
            midpoint_y = (previous.y + current.y) / 2.0
            cell_stats[cell_index(midpoint_x, midpoint_y, config.grid_size_px)].add_segment(
                track_id=track.track_id,
                route=track.route,
                duration_s=dt,
                is_slow=is_slow,
                is_stationary=is_stationary,
            )

        agent_dict = agent_motion.as_dict(config.px_per_meter)
        agent_dict.update(
            {
                "track_id": track.track_id,
                "route": track.route,
                "sample_count": len(track.samples),
                "start_time_s": round_float(track.samples[0].time),
                "end_time_s": round_float(track.samples[-1].time),
                "observed_duration_s": round_float(track.samples[-1].time - track.samples[0].time),
            }
        )
        per_agent_stats.append(agent_dict)

    active_curve = [
        {"time_s": round_float(time), "active": count}
        for time, count in sorted(active_counter.items())
    ]
    peak_active = max(item["active"] for item in active_curve)
    peak_times = [item["time_s"] for item in active_curve if item["active"] == peak_active][:10]

    top_slow_agents = sorted(
        per_agent_stats,
        key=lambda item: (
            -float(item["slow_duration_s"]),
            -float(item["stationary_duration_s"]),
            str(item["track_id"]),
        ),
    )[: config.top_n]
    top_stationary_agents = sorted(
        per_agent_stats,
        key=lambda item: (
            -float(item["stationary_duration_s"]),
            -float(item["slow_duration_s"]),
            str(item["track_id"]),
        ),
    )[: config.top_n]

    queue_layout_counts = summarize_queue_layouts(payload.get("queue_layouts"))
    queue_sample_counts = summarize_queue_samples(payload.get("queue_samples"), config.top_n)

    return {
        "input": str(input_path) if input_path is not None else None,
        "generated_by": payload.get("generated_by"),
        "analysis_parameters": {
            "grid_size_px": config.grid_size_px,
            "slow_speed_m_s": config.slow_speed_m_s,
            "slow_speed_px_s": round_float(config.slow_speed_px_s),
            "stationary_speed_m_s": config.stationary_speed_m_s,
            "stationary_speed_px_s": round_float(config.stationary_speed_px_s),
            "px_per_meter": config.px_per_meter,
            "canvas_width": config.canvas_width,
            "canvas_height": config.canvas_height,
            "top_n": config.top_n,
        },
        "summary": {
            "tracks": len(tracks),
            "samples": sample_count,
            "time_min_s": round_float(time_min),
            "time_max_s": round_float(time_max),
            "duration_s": round_float(time_max - time_min),
            "payload_duration_s": payload.get("duration"),
            "route_counts": dict(route_counts.most_common()),
            "source_counts": dict(source_counts.most_common()),
        },
        "active_curve": {
            "points": active_curve,
            "sample_count": len(active_curve),
            "peak_active": peak_active,
            "peak_times_s": peak_times,
            "mean_active": round_float(
                sum(int(item["active"]) for item in active_curve) / len(active_curve)
            ),
        },
        "movement": {
            "overall": overall_motion.as_dict(config.px_per_meter),
            "by_route": {
                route: aggregate.as_dict(config.px_per_meter)
                for route, aggregate in sorted(motion_by_route.items())
            },
            "top_slow_agents": top_slow_agents,
            "top_stationary_agents": top_stationary_agents,
        },
        "bottleneck_grid": {
            "score": "slow_duration_s + stationary_duration_s",
            "top_cells": top_bottleneck_cells(cell_stats, config),
        },
        "queues": {
            "layout_counts": queue_layout_counts,
            "sample_counts": queue_sample_counts,
        },
        "clearance_audit": payload.get("clearance_audit"),
        "native_queue_model": payload.get("native_queue_model"),
    }


def cell_index(x: float, y: float, grid_size_px: float) -> tuple[int, int]:
    if grid_size_px <= 0:
        raise ValueError("grid size must be positive")
    return math.floor(x / grid_size_px), math.floor(y / grid_size_px)


def top_bottleneck_cells(
    cell_stats: dict[tuple[int, int], CellStats],
    config: AnalysisConfig,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (cell_x, cell_y), stats in cell_stats.items():
        score = stats.slow_duration_s + stats.stationary_duration_s
        x0 = cell_x * config.grid_size_px
        y0 = cell_y * config.grid_size_px
        rows.append(
            {
                "cell": [cell_x, cell_y],
                "bounds_px": [
                    round_float(x0),
                    round_float(y0),
                    round_float(x0 + config.grid_size_px),
                    round_float(y0 + config.grid_size_px),
                ],
                "center_px": [
                    round_float(x0 + config.grid_size_px / 2.0),
                    round_float(y0 + config.grid_size_px / 2.0),
                ],
                "bottleneck_score_s": round_float(score),
                "slow_duration_s": round_float(stats.slow_duration_s),
                "stationary_duration_s": round_float(stats.stationary_duration_s),
                "slow_segments": stats.slow_segments,
                "stationary_segments": stats.stationary_segments,
                "active_observations": stats.active_observations,
                "unique_agents": len(stats.point_agent_ids | stats.segment_agent_ids),
                "top_routes": dict(stats.routes.most_common(3)),
            }
        )

    rows.sort(
        key=lambda item: (
            -float(item["bottleneck_score_s"]),
            -int(item["active_observations"]),
            item["cell"],
        )
    )
    return rows[: config.top_n]


def summarize_queue_layouts(queue_layouts_obj: object) -> dict[str, object]:
    if not isinstance(queue_layouts_obj, list):
        return {
            "queue_count": 0,
            "total_capacity": 0,
            "total_slots": 0,
            "by_kind": {},
            "per_queue": [],
        }

    by_kind: dict[str, dict[str, int]] = {}
    per_queue: list[dict[str, object]] = []
    total_capacity = 0
    total_slots = 0
    for queue_obj in queue_layouts_obj:
        if not isinstance(queue_obj, dict):
            continue
        queue_id = str(queue_obj.get("id", "unknown"))
        kind = str(queue_obj.get("kind", "unknown"))
        slots_obj = queue_obj.get("slots", [])
        slot_count = len(slots_obj) if isinstance(slots_obj, list) else 0
        capacity = int_from_obj(queue_obj.get("capacity"), slot_count)
        lanes = int_from_obj(queue_obj.get("lanes"), 0)
        total_capacity += capacity
        total_slots += slot_count
        kind_stats = by_kind.setdefault(kind, {"queues": 0, "capacity": 0, "slots": 0})
        kind_stats["queues"] += 1
        kind_stats["capacity"] += capacity
        kind_stats["slots"] += slot_count
        per_queue.append(
            {
                "id": queue_id,
                "kind": kind,
                "lanes": lanes,
                "capacity": capacity,
                "slot_count": slot_count,
            }
        )

    per_queue.sort(key=lambda item: (-int(item["capacity"]), str(item["id"])))
    return {
        "queue_count": len(per_queue),
        "total_capacity": total_capacity,
        "total_slots": total_slots,
        "by_kind": dict(sorted(by_kind.items())),
        "per_queue": per_queue,
    }


def summarize_queue_samples(queue_samples_obj: object, top_n: int) -> dict[str, object]:
    if not isinstance(queue_samples_obj, list):
        return {
            "sample_count": 0,
            "queue_count": 0,
            "top_queues": [],
            "per_queue": [],
        }

    stats_by_queue: defaultdict[str, QueueSampleStats] = defaultdict(QueueSampleStats)
    sorted_samples = sorted(
        (sample for sample in queue_samples_obj if isinstance(sample, dict)),
        key=lambda sample: float(sample.get("time", 0.0)),
    )
    for sample in sorted_samples:
        try:
            time = float(sample.get("time", 0.0))
        except (TypeError, ValueError):
            time = 0.0
        queues_obj = sample.get("queues")
        if not isinstance(queues_obj, dict):
            continue
        for queue_id, counts_obj in queues_obj.items():
            if not isinstance(counts_obj, dict):
                continue
            enqueued = int_from_obj(counts_obj.get("enqueued"), 0)
            targeting = int_from_obj(counts_obj.get("targeting"), 0)
            stats_by_queue[str(queue_id)].add(
                time=time,
                enqueued=enqueued,
                targeting=targeting,
            )

    per_queue = [
        {
            "id": queue_id,
            "samples": stats.samples,
            "mean_enqueued": ratio_value(stats.enqueued_sum, stats.samples),
            "mean_targeting": ratio_value(stats.targeting_sum, stats.samples),
            "mean_total": ratio_value(stats.total_sum, stats.samples),
            "max_enqueued": stats.max_enqueued,
            "max_targeting": stats.max_targeting,
            "max_total": stats.max_total,
            "max_total_time_s": round_float(stats.max_total_time or 0.0),
            "last_enqueued": stats.last_enqueued,
            "last_targeting": stats.last_targeting,
            "last_total": stats.last_total,
        }
        for queue_id, stats in stats_by_queue.items()
    ]
    per_queue.sort(key=lambda item: (-int(item["max_total"]), str(item["id"])))
    return {
        "sample_count": len(sorted_samples),
        "queue_count": len(per_queue),
        "top_queues": per_queue[:top_n],
        "per_queue": per_queue,
    }


def int_from_obj(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def ratio_value(total: int | float, count: int) -> float:
    return round_float(float(total) / count) if count > 0 else 0.0


def render_markdown(report: dict[str, Any], *, active_curve_limit: int) -> str:
    summary = report["summary"]
    active = report["active_curve"]
    movement = report["movement"]["overall"]
    params = report["analysis_parameters"]
    queues = report["queues"]
    lines: list[str] = [
        "# Metro Track Bottleneck Diagnostics",
        "",
        f"- Input: `{report.get('input')}`",
        f"- Tracks: {summary['tracks']}",
        f"- Samples: {summary['samples']}",
        f"- Time range: {summary['time_min_s']}s to {summary['time_max_s']}s",
        f"- Grid size: {params['grid_size_px']} px",
        (f"- Slow threshold: {params['slow_speed_m_s']} m/s ({params['slow_speed_px_s']} px/s)"),
        (
            "- Stationary threshold: "
            f"{params['stationary_speed_m_s']} m/s "
            f"({params['stationary_speed_px_s']} px/s)"
        ),
        "",
        "## Active Passenger Curve",
        "",
        f"- Curve samples: {active['sample_count']}",
        f"- Peak active passengers: {active['peak_active']} at {active['peak_times_s']}s",
        f"- Mean active passengers: {active['mean_active']}",
        "",
        "| time_s | active |",
        "| ---: | ---: |",
    ]
    curve_points = list(active["points"])
    curve_rows = curve_points if active_curve_limit <= 0 else curve_points[:active_curve_limit]
    for item in curve_rows:
        lines.append(f"| {item['time_s']} | {item['active']} |")
    if 0 < active_curve_limit < len(curve_points):
        lines.append(f"| ... | truncated, {len(curve_points) - active_curve_limit} more samples |")

    lines.extend(
        [
            "",
            "## Slow And Stationary Movement",
            "",
            "| metric | value |",
            "| --- | ---: |",
            f"| total_segments | {movement['total_segments']} |",
            f"| total_duration_s | {movement['total_duration_s']} |",
            f"| mean_speed_m_s | {movement['mean_speed_m_s']} |",
            f"| slow_segments | {movement['slow_segments']} |",
            f"| slow_duration_s | {movement['slow_duration_s']} |",
            f"| slow_duration_share | {movement['slow_duration_share']} |",
            f"| slow_agents | {movement['slow_agents']} |",
            f"| stationary_segments | {movement['stationary_segments']} |",
            f"| stationary_duration_s | {movement['stationary_duration_s']} |",
            f"| stationary_duration_share | {movement['stationary_duration_share']} |",
            f"| stationary_agents | {movement['stationary_agents']} |",
            "",
            "## Top Bottleneck Cells",
            "",
            (
                "| rank | cell | center_px | score_s | slow_s | stationary_s | "
                "active_obs | unique_agents | top_routes |"
            ),
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for rank, cell in enumerate(report["bottleneck_grid"]["top_cells"], start=1):
        top_routes = ", ".join(f"{key}:{value}" for key, value in cell["top_routes"].items())
        lines.append(
            "| "
            f"{rank} | {cell['cell']} | {cell['center_px']} | "
            f"{cell['bottleneck_score_s']} | {cell['slow_duration_s']} | "
            f"{cell['stationary_duration_s']} | {cell['active_observations']} | "
            f"{cell['unique_agents']} | {top_routes} |"
        )

    layout_counts = queues["layout_counts"]
    lines.extend(
        [
            "",
            "## Queue Layout Counts",
            "",
            f"- Queue layouts: {layout_counts['queue_count']}",
            f"- Total capacity: {layout_counts['total_capacity']}",
            f"- Total slots: {layout_counts['total_slots']}",
            "",
            "| kind | queues | capacity | slots |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for kind, stats in layout_counts["by_kind"].items():
        lines.append(f"| {kind} | {stats['queues']} | {stats['capacity']} | {stats['slots']} |")

    lines.extend(
        [
            "",
            "## Queue Sample Peaks",
            "",
            "| queue | max_total | max_time_s | mean_total | last_total |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in queues["sample_counts"]["top_queues"]:
        lines.append(
            "| "
            f"{item['id']} | {item['max_total']} | {item['max_total_time_s']} | "
            f"{item['mean_total']} | {item['last_total']} |"
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze window.JPS_TRACKS passenger trajectories for active counts, "
            "slow/stationary motion, grid bottlenecks, and queue layout counts."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help=f"Path to passenger_tracks_jps.js. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument("--input", dest="input_option", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--json-out", type=Path, help="Write full analysis report as JSON.")
    parser.add_argument(
        "--markdown-out",
        "--md-out",
        dest="markdown_out",
        type=Path,
        help="Write a Markdown diagnostics report.",
    )
    parser.add_argument("--top", type=int, default=15, help="Number of top rows to include.")
    parser.add_argument(
        "--grid-size-px",
        type=float,
        default=80.0,
        help="Spatial grid cell size in canvas pixels.",
    )
    parser.add_argument(
        "--slow-speed-m-s",
        type=float,
        default=0.20,
        help="Segments at or below this speed are counted as slow.",
    )
    parser.add_argument(
        "--stationary-speed-m-s",
        type=float,
        default=0.03,
        help="Segments at or below this speed are counted as stationary.",
    )
    parser.add_argument(
        "--px-per-meter",
        type=float,
        default=DEFAULT_PX_PER_METER,
        help="Canvas pixel to meter scale for speed thresholds.",
    )
    parser.add_argument(
        "--canvas-width",
        type=float,
        default=DEFAULT_CANVAS_WIDTH,
        help="Canvas width used for report metadata.",
    )
    parser.add_argument(
        "--canvas-height",
        type=float,
        default=DEFAULT_CANVAS_HEIGHT,
        help="Canvas height used for report metadata.",
    )
    parser.add_argument(
        "--markdown-curve-limit",
        type=int,
        default=250,
        help="Maximum active curve rows in Markdown. Use 0 for all rows.",
    )
    return parser


def resolve_input_path(args: argparse.Namespace) -> Path:
    path = args.input_option or args.input or DEFAULT_INPUT
    if path.exists():
        return path
    candidate = REPO_ROOT / path
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"input file not found: {path}")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.grid_size_px <= 0:
            raise ValueError("--grid-size-px must be positive")
        if args.px_per_meter <= 0:
            raise ValueError("--px-per-meter must be positive")
        if args.top <= 0:
            raise ValueError("--top must be positive")
        input_path = resolve_input_path(args).resolve()
        config = AnalysisConfig(
            grid_size_px=args.grid_size_px,
            slow_speed_m_s=args.slow_speed_m_s,
            stationary_speed_m_s=args.stationary_speed_m_s,
            px_per_meter=args.px_per_meter,
            canvas_width=args.canvas_width,
            canvas_height=args.canvas_height,
            top_n=args.top,
        )
        payload = load_payload(input_path)
        report = build_report(payload, input_path=input_path, config=config)
    except Exception as exc:
        print(f"[TRACK ANALYSIS] error: {exc}", file=sys.stderr)
        return 2

    markdown = render_markdown(report, active_curve_limit=args.markdown_curve_limit)
    if args.json_out is not None:
        write_text(
            args.json_out,
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
    if args.markdown_out is not None:
        write_text(args.markdown_out, markdown)

    if args.json_out is None and args.markdown_out is None:
        print(markdown, end="")
    else:
        active = report["active_curve"]
        movement = report["movement"]["overall"]
        print(
            "[TRACK ANALYSIS] "
            f"tracks={report['summary']['tracks']} "
            f"samples={report['summary']['samples']} "
            f"peak_active={active['peak_active']} "
            f"slow_duration_s={movement['slow_duration_s']} "
            f"stationary_duration_s={movement['stationary_duration_s']}"
        )
        if args.json_out is not None:
            print(f"[TRACK ANALYSIS] json={args.json_out}")
        if args.markdown_out is not None:
            print(f"[TRACK ANALYSIS] markdown={args.markdown_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
