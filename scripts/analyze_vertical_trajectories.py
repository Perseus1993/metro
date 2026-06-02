from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.analyze_metro_tracks import (
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
    DEFAULT_INPUT,
    DEFAULT_PX_PER_METER,
    REPO_ROOT,
    load_payload,
    round_float,
    write_text,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "vertical_trajectory_analysis"
DEFAULT_JSON_OUTPUT = DEFAULT_OUTPUT_DIR / "vertical_trajectory_analysis.json"
DEFAULT_MARKDOWN_OUTPUT = DEFAULT_OUTPUT_DIR / "vertical_trajectory_analysis.md"


@dataclass(frozen=True)
class Point:
    time: float
    x: float
    y: float
    mode: str = "unknown"
    label: str = "unknown"


@dataclass(frozen=True)
class AgentTrack:
    track_id: str
    route: str
    route_chain: tuple[str, ...]
    source: str
    points: tuple[Point, ...]


@dataclass(frozen=True)
class ConnectorChannel:
    channel_id: str
    kind: str
    direction: str
    width_px: float
    line: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Projection:
    distance_px: float
    progress: float


@dataclass(frozen=True)
class ChannelHit:
    channel: ConnectorChannel
    distance_px: float
    progress: float


@dataclass(frozen=True)
class TrajectoryConfig:
    kinds: tuple[str, ...] = ("elevator", "elevator_lobby", "escalator")
    margin_px: float = 16.0
    stationary_speed_m_s: float = 0.03
    max_speed_m_s: float = 4.0
    max_segment_m: float = 25.0
    reverse_tolerance: float = 0.08
    stuck_seconds: float = 25.0
    px_per_meter: float = DEFAULT_PX_PER_METER
    canvas_width: float = DEFAULT_CANVAS_WIDTH
    canvas_height: float = DEFAULT_CANVAS_HEIGHT
    top_n: int = 30

    @property
    def stationary_speed_px_s(self) -> float:
        return self.stationary_speed_m_s * self.px_per_meter

    @property
    def max_speed_px_s(self) -> float:
        return self.max_speed_m_s * self.px_per_meter

    @property
    def max_segment_px(self) -> float:
        return self.max_segment_m * self.px_per_meter


@dataclass
class ConnectorStats:
    channel: ConnectorChannel
    segments: int = 0
    duration_s: float = 0.0
    distance_px: float = 0.0
    max_speed_m_s: float = 0.0
    reverse_segments: int = 0
    teleport_segments: int = 0
    stationary_duration_s: float = 0.0
    agent_ids: set[str] = field(default_factory=set)
    stuck_agent_ids: set[str] = field(default_factory=set)

    def add_segment(
        self,
        *,
        track_id: str,
        duration_s: float,
        distance_px: float,
        speed_m_s: float,
        stationary: bool,
    ) -> None:
        self.segments += 1
        self.duration_s += duration_s
        self.distance_px += distance_px
        self.max_speed_m_s = max(self.max_speed_m_s, speed_m_s)
        self.agent_ids.add(track_id)
        if stationary:
            self.stationary_duration_s += duration_s

    def as_dict(self, px_per_meter: float) -> dict[str, object]:
        mean_speed_m_s = (
            self.distance_px / self.duration_s / px_per_meter if self.duration_s > 0 else 0.0
        )
        return {
            "id": self.channel.channel_id,
            "kind": self.channel.kind,
            "direction": self.channel.direction,
            "width_px": round_float(self.channel.width_px),
            "agents": len(self.agent_ids),
            "segments": self.segments,
            "duration_s": round_float(self.duration_s),
            "distance_m": round_float(self.distance_px / px_per_meter),
            "mean_speed_m_s": round_float(mean_speed_m_s),
            "max_speed_m_s": round_float(self.max_speed_m_s),
            "reverse_segments": self.reverse_segments,
            "teleport_segments": self.teleport_segments,
            "stationary_duration_s": round_float(self.stationary_duration_s),
            "stuck_agents": len(self.stuck_agent_ids),
        }


@dataclass
class StuckAccumulator:
    track_id: str
    route: str
    channel_id: str
    kind: str
    direction: str
    start_s: float
    end_s: float
    duration_s: float = 0.0

    def add(self, start_s: float, end_s: float) -> None:
        self.start_s = min(self.start_s, start_s)
        self.end_s = max(self.end_s, end_s)
        self.duration_s += end_s - start_s


def parse_kinds(raw: str) -> tuple[str, ...]:
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    return values or ("elevator", "elevator_lobby", "escalator")


def extract_tracks(payload: dict[str, Any]) -> list[AgentTrack]:
    agents_obj = payload.get("agents", payload.get("tracks"))
    if not isinstance(agents_obj, list):
        raise ValueError("payload must contain an 'agents' or 'tracks' list")

    tracks: list[AgentTrack] = []
    for index, agent_obj in enumerate(agents_obj):
        if not isinstance(agent_obj, dict):
            continue
        points_obj = agent_obj.get("points")
        if not isinstance(points_obj, list):
            continue

        points: list[Point] = []
        for point_obj in points_obj:
            if not isinstance(point_obj, list | tuple) or len(point_obj) < 3:
                continue
            try:
                time = float(point_obj[0])
                x = float(point_obj[1])
                y = float(point_obj[2])
            except (TypeError, ValueError):
                continue
            mode = str(point_obj[7]) if len(point_obj) > 7 else "unknown"
            label = str(point_obj[8]) if len(point_obj) > 8 else "unknown"
            points.append(Point(time=time, x=x, y=y, mode=mode, label=label))

        if not points:
            continue
        route_chain_obj = agent_obj.get("route_chain", [])
        route_chain = (
            tuple(str(item) for item in route_chain_obj) if isinstance(route_chain_obj, list) else ()
        )
        raw_id = agent_obj.get("id", agent_obj.get("track_id", index))
        tracks.append(
            AgentTrack(
                track_id=str(raw_id),
                route=str(agent_obj.get("route", "unknown")),
                route_chain=route_chain,
                source=str(agent_obj.get("source", "unknown")),
                points=tuple(sorted(points, key=lambda item: item.time)),
            )
        )
    return tracks


def extract_channels(payload: dict[str, Any], config: TrajectoryConfig) -> list[ConnectorChannel]:
    layout_obj = payload.get("layout")
    if not isinstance(layout_obj, dict):
        raise ValueError("payload must contain a layout object")
    channels_obj = layout_obj.get("connector_channels")
    if not isinstance(channels_obj, list):
        raise ValueError("payload layout must contain connector_channels")

    include_all = "all" in config.kinds
    channels: list[ConnectorChannel] = []
    for channel_obj in channels_obj:
        if not isinstance(channel_obj, dict):
            continue
        kind = str(channel_obj.get("kind", "unknown"))
        if not include_all and kind not in config.kinds:
            continue
        line_obj = channel_obj.get("line")
        if not isinstance(line_obj, list) or len(line_obj) < 2:
            continue
        line = tuple(
            scaled_layout_point(point_obj, config)
            for point_obj in line_obj
            if isinstance(point_obj, list | tuple) and len(point_obj) >= 2
        )
        if len(line) < 2:
            continue
        channels.append(
            ConnectorChannel(
                channel_id=str(channel_obj.get("id", f"channel_{len(channels)}")),
                kind=kind,
                direction=str(channel_obj.get("direction", "both")),
                width_px=float(channel_obj.get("width_px", 0.0) or 0.0),
                line=line,
            )
        )
    if not channels:
        raise ValueError(f"no connector channels matched kinds: {', '.join(config.kinds)}")
    return channels


def scaled_layout_point(point_obj: Sequence[object], config: TrajectoryConfig) -> tuple[float, float]:
    x = float(point_obj[0])  # type: ignore[arg-type]
    y = float(point_obj[1])  # type: ignore[arg-type]
    return scale_layout_coord(x, config.canvas_width), scale_layout_coord(y, config.canvas_height)


def scale_layout_coord(value: float, canvas_size: float) -> float:
    if -1.5 <= value <= 1.5:
        return value * canvas_size
    return value


def project_to_polyline(point: Point | tuple[float, float], line: Sequence[tuple[float, float]]) -> Projection:
    px, py = point_xy(point)
    lengths = [
        math.hypot(line[index + 1][0] - line[index][0], line[index + 1][1] - line[index][1])
        for index in range(len(line) - 1)
    ]
    total_length = sum(lengths)
    if total_length <= 0:
        return Projection(distance_px=math.inf, progress=0.0)

    best_distance = math.inf
    best_progress = 0.0
    travelled = 0.0
    for index, length in enumerate(lengths):
        start = line[index]
        end = line[index + 1]
        distance, segment_t = project_to_segment((px, py), start, end)
        progress = (travelled + segment_t * length) / total_length
        if distance < best_distance:
            best_distance = distance
            best_progress = progress
        travelled += length
    return Projection(distance_px=best_distance, progress=best_progress)


def project_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    px, py = point
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0:
        return math.hypot(px - ax, py - ay), 0.0
    raw_t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    segment_t = min(1.0, max(0.0, raw_t))
    projected_x = ax + segment_t * dx
    projected_y = ay + segment_t * dy
    return math.hypot(px - projected_x, py - projected_y), segment_t


def point_xy(point: Point | tuple[float, float]) -> tuple[float, float]:
    if isinstance(point, Point):
        return point.x, point.y
    return point


def nearest_hit(
    point: Point | tuple[float, float],
    channels: Sequence[ConnectorChannel],
    config: TrajectoryConfig,
) -> ChannelHit | None:
    best_hit: ChannelHit | None = None
    best_ratio = math.inf
    for channel in channels:
        projection = project_to_polyline(point, channel.line)
        threshold = channel.width_px / 2.0 + config.margin_px
        if threshold <= 0 or projection.distance_px > threshold:
            continue
        ratio = projection.distance_px / threshold
        if ratio < best_ratio:
            best_ratio = ratio
            best_hit = ChannelHit(
                channel=channel,
                distance_px=projection.distance_px,
                progress=projection.progress,
            )
    return best_hit


def segment_hit(
    previous: Point,
    current: Point,
    channels: Sequence[ConnectorChannel],
    config: TrajectoryConfig,
) -> ChannelHit | None:
    midpoint = ((previous.x + current.x) / 2.0, (previous.y + current.y) / 2.0)
    hits = [
        nearest_hit(midpoint, channels, config),
        nearest_hit(previous, channels, config),
        nearest_hit(current, channels, config),
    ]
    valid_hits = [hit for hit in hits if hit is not None]
    if not valid_hits:
        return None
    return min(
        valid_hits,
        key=lambda hit: hit.distance_px / max(1.0, hit.channel.width_px / 2.0 + config.margin_px),
    )


def build_report(
    payload: dict[str, Any],
    *,
    input_path: Path | None,
    config: TrajectoryConfig,
) -> dict[str, Any]:
    tracks = extract_tracks(payload)
    if not tracks:
        raise ValueError("no tracks with usable points found")
    channels = extract_channels(payload, config)
    stats_by_channel = {channel.channel_id: ConnectorStats(channel) for channel in channels}
    anomalies: list[dict[str, object]] = []
    stuck: dict[tuple[str, str], StuckAccumulator] = {}
    route_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    sample_count = 0
    segment_count = 0
    connector_segment_count = 0
    time_min = math.inf
    time_max = -math.inf
    dt_values: list[float] = []

    for track in tracks:
        route_counts[track.route] += 1
        source_counts[track.source] += 1
        sample_count += len(track.points)
        time_min = min(time_min, track.points[0].time)
        time_max = max(time_max, track.points[-1].time)

        for previous, current in zip(track.points, track.points[1:], strict=False):
            dt = current.time - previous.time
            if dt <= 0:
                continue
            segment_count += 1
            dt_values.append(dt)
            distance_px = math.hypot(current.x - previous.x, current.y - previous.y)
            speed_px_s = distance_px / dt
            speed_m_s = speed_px_s / config.px_per_meter
            hit = segment_hit(previous, current, channels, config)
            if hit is None:
                continue

            connector_segment_count += 1
            channel = hit.channel
            stats = stats_by_channel[channel.channel_id]
            stationary = speed_px_s <= config.stationary_speed_px_s
            active_stationary = stationary and _is_active_connector_motion(previous, current)
            stats.add_segment(
                track_id=track.track_id,
                duration_s=dt,
                distance_px=distance_px,
                speed_m_s=speed_m_s,
                stationary=active_stationary,
            )

            previous_progress = project_to_polyline(previous, channel.line).progress
            current_progress = project_to_polyline(current, channel.line).progress
            progress_delta = current_progress - previous_progress
            if channel.direction in {"down", "up"} and progress_delta < -config.reverse_tolerance:
                stats.reverse_segments += 1
                anomalies.append(
                    anomaly_row(
                        "reverse",
                        track,
                        channel,
                        previous,
                        current,
                        distance_px,
                        speed_m_s,
                        progress_delta,
                        config,
                    )
                )

            if speed_px_s > config.max_speed_px_s or distance_px > config.max_segment_px:
                stats.teleport_segments += 1
                anomalies.append(
                    anomaly_row(
                        "jump_or_speed",
                        track,
                        channel,
                        previous,
                        current,
                        distance_px,
                        speed_m_s,
                        progress_delta,
                        config,
                    )
                )

            if active_stationary:
                key = (track.track_id, channel.channel_id)
                if key not in stuck:
                    stuck[key] = StuckAccumulator(
                        track_id=track.track_id,
                        route=track.route,
                        channel_id=channel.channel_id,
                        kind=channel.kind,
                        direction=channel.direction,
                        start_s=previous.time,
                        end_s=current.time,
                    )
                stuck[key].add(previous.time, current.time)

    for item in stuck.values():
        if item.duration_s < config.stuck_seconds:
            continue
        stats_by_channel[item.channel_id].stuck_agent_ids.add(item.track_id)
        anomalies.append(
            {
                "issue": "stuck_in_connector",
                "track_id": item.track_id,
                "route": item.route,
                "channel_id": item.channel_id,
                "kind": item.kind,
                "direction": item.direction,
                "start_s": round_float(item.start_s),
                "end_s": round_float(item.end_s),
                "duration_s": round_float(item.duration_s),
                "distance_m": 0.0,
                "speed_m_s": 0.0,
                "progress_delta": 0.0,
                "from_px": None,
                "to_px": None,
            }
        )

    anomalies.sort(
        key=lambda item: (
            issue_priority(str(item["issue"])),
            -float(item.get("speed_m_s") or 0.0),
            -float(item.get("duration_s") or 0.0),
            str(item.get("track_id")),
        )
    )
    channel_rows = [
        stats.as_dict(config.px_per_meter)
        for stats in sorted(stats_by_channel.values(), key=lambda item: item.channel.channel_id)
    ]
    anomaly_counts = Counter(str(item["issue"]) for item in anomalies)
    median_dt = median(dt_values)

    return {
        "input": str(input_path) if input_path is not None else None,
        "generated_by": payload.get("generated_by"),
        "analysis_parameters": {
            "kinds": list(config.kinds),
            "margin_px": config.margin_px,
            "stationary_speed_m_s": config.stationary_speed_m_s,
            "max_speed_m_s": config.max_speed_m_s,
            "max_segment_m": config.max_segment_m,
            "reverse_tolerance": config.reverse_tolerance,
            "stuck_seconds": config.stuck_seconds,
            "px_per_meter": config.px_per_meter,
            "canvas_width": config.canvas_width,
            "canvas_height": config.canvas_height,
            "top_n": config.top_n,
        },
        "summary": {
            "status": "ok" if not anomalies else "review",
            "tracks": len(tracks),
            "samples": sample_count,
            "segments": segment_count,
            "connector_channels": len(channels),
            "connector_segments": connector_segment_count,
            "connector_segment_share": round_float(connector_segment_count / segment_count, 4)
            if segment_count
            else 0.0,
            "time_min_s": round_float(time_min),
            "time_max_s": round_float(time_max),
            "duration_s": round_float(time_max - time_min),
            "payload_duration_s": payload.get("duration"),
            "median_sample_dt_s": round_float(median_dt),
            "route_counts": dict(route_counts.most_common()),
            "source_counts": dict(source_counts.most_common()),
            "anomaly_counts": dict(anomaly_counts),
            "reverse_segments": anomaly_counts.get("reverse", 0),
            "jump_or_speed_segments": anomaly_counts.get("jump_or_speed", 0),
            "stuck_agents": anomaly_counts.get("stuck_in_connector", 0),
        },
        "channels": channel_rows,
        "anomalies": anomalies[: config.top_n],
        "all_anomaly_count": len(anomalies),
        "limits": [
            "The check uses sampled canvas points, so a coarse sample interval can hide brief path changes.",
            "Connector membership is geometric: a segment is counted when an endpoint or midpoint falls inside a connector channel plus margin.",
        ],
    }


def _is_active_connector_motion(previous: Point, current: Point) -> bool:
    passive_modes = {"enqueued", "waiting"}
    return previous.mode not in passive_modes and current.mode not in passive_modes


def anomaly_row(
    issue: str,
    track: AgentTrack,
    channel: ConnectorChannel,
    previous: Point,
    current: Point,
    distance_px: float,
    speed_m_s: float,
    progress_delta: float,
    config: TrajectoryConfig,
) -> dict[str, object]:
    return {
        "issue": issue,
        "track_id": track.track_id,
        "route": track.route,
        "route_chain": list(track.route_chain),
        "channel_id": channel.channel_id,
        "kind": channel.kind,
        "direction": channel.direction,
        "start_s": round_float(previous.time),
        "end_s": round_float(current.time),
        "duration_s": round_float(current.time - previous.time),
        "distance_m": round_float(distance_px / config.px_per_meter),
        "speed_m_s": round_float(speed_m_s),
        "progress_delta": round_float(progress_delta, 4),
        "from_px": [round_float(previous.x), round_float(previous.y)],
        "to_px": [round_float(current.x), round_float(current.y)],
        "from_state": {"mode": previous.mode, "label": previous.label},
        "to_state": {"mode": current.mode, "label": current.label},
    }


def issue_priority(issue: str) -> int:
    priorities = {
        "jump_or_speed": 0,
        "reverse": 1,
        "stuck_in_connector": 2,
    }
    return priorities.get(issue, 99)


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    params = report["analysis_parameters"]
    lines: list[str] = [
        "# Vertical Connector Trajectory Diagnostics",
        "",
        f"- Input: `{report.get('input')}`",
        f"- Status: {summary['status']}",
        f"- Tracks: {summary['tracks']}",
        f"- Samples: {summary['samples']}",
        f"- Time range: {summary['time_min_s']}s to {summary['time_max_s']}s",
        f"- Median sample interval: {summary['median_sample_dt_s']}s",
        f"- Connector kinds: {', '.join(params['kinds'])}",
        f"- Connector margin: {params['margin_px']} px",
        f"- Max normal speed: {params['max_speed_m_s']} m/s",
        f"- Max normal segment: {params['max_segment_m']} m",
        f"- Reverse tolerance: {params['reverse_tolerance']}",
        f"- Stuck threshold: {params['stuck_seconds']} s",
        "",
        "## Summary",
        "",
        "| metric | value |",
        "| --- | ---: |",
        f"| connector_channels | {summary['connector_channels']} |",
        f"| total_segments | {summary['segments']} |",
        f"| connector_segments | {summary['connector_segments']} |",
        f"| connector_segment_share | {summary['connector_segment_share']} |",
        f"| reverse_segments | {summary['reverse_segments']} |",
        f"| jump_or_speed_segments | {summary['jump_or_speed_segments']} |",
        f"| stuck_agents | {summary['stuck_agents']} |",
        f"| all_anomaly_count | {report['all_anomaly_count']} |",
        "",
        "## By Connector",
        "",
        (
            "| connector | kind | direction | agents | segments | mean_speed_m_s | "
            "max_speed_m_s | reverse | jump/speed | stationary_s | stuck_agents |"
        ),
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for channel in report["channels"]:
        lines.append(
            "| "
            f"{channel['id']} | {channel['kind']} | {channel['direction']} | "
            f"{channel['agents']} | {channel['segments']} | "
            f"{channel['mean_speed_m_s']} | {channel['max_speed_m_s']} | "
            f"{channel['reverse_segments']} | {channel['teleport_segments']} | "
            f"{channel['stationary_duration_s']} | {channel['stuck_agents']} |"
        )

    lines.extend(
        [
            "",
            "## Top Anomalies",
            "",
        ]
    )
    if not report["anomalies"]:
        lines.append("No connector trajectory anomalies detected.")
    else:
        lines.extend(
            [
                (
                    "| issue | track | route | connector | time_s | duration_s | "
                    "distance_m | speed_m_s | progress_delta |"
                ),
                "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for item in report["anomalies"]:
            lines.append(
                "| "
                f"{item['issue']} | {item['track_id']} | {item['route']} | "
                f"{item['channel_id']} | {item['start_s']} -> {item['end_s']} | "
                f"{item['duration_s']} | {item['distance_m']} | {item['speed_m_s']} | "
                f"{item['progress_delta']} |"
            )

    lines.extend(["", "## Limits", ""])
    for item in report["limits"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze sampled passenger trajectories around elevator/escalator connector "
            "channels for reverse motion, jumps, abnormal speed, and stuck agents."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help=f"Path to passenger_tracks_jps.js. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument("--input", dest="input_option", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=DEFAULT_JSON_OUTPUT,
        help=f"Write full JSON report. Default: {DEFAULT_JSON_OUTPUT}",
    )
    parser.add_argument(
        "--markdown-out",
        "--md-out",
        dest="markdown_out",
        type=Path,
        default=DEFAULT_MARKDOWN_OUTPUT,
        help=f"Write Markdown report. Default: {DEFAULT_MARKDOWN_OUTPUT}",
    )
    parser.add_argument(
        "--kinds",
        default="elevator,elevator_lobby,escalator",
        help="Comma-separated connector kinds to inspect. Use all to include every channel.",
    )
    parser.add_argument("--top", type=int, default=30, help="Maximum anomalies in the report.")
    parser.add_argument(
        "--margin-px",
        type=float,
        default=16.0,
        help="Extra geometric margin around each connector channel.",
    )
    parser.add_argument(
        "--stationary-speed-m-s",
        type=float,
        default=0.03,
        help="Segments at or below this speed count as stationary.",
    )
    parser.add_argument(
        "--max-speed-m-s",
        type=float,
        default=4.0,
        help="Segments above this speed count as jumps or abnormal speed.",
    )
    parser.add_argument(
        "--max-segment-m",
        type=float,
        default=25.0,
        help="Segments longer than this distance count as jumps even if dt is large.",
    )
    parser.add_argument(
        "--reverse-tolerance",
        type=float,
        default=0.08,
        help="Minimum negative progress along a directed connector before flagging reverse motion.",
    )
    parser.add_argument(
        "--stuck-seconds",
        type=float,
        default=25.0,
        help="Stationary time inside one connector before flagging a stuck agent.",
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
        help="Canvas width used to scale normalized connector coordinates.",
    )
    parser.add_argument(
        "--canvas-height",
        type=float,
        default=DEFAULT_CANVAS_HEIGHT,
        help="Canvas height used to scale normalized connector coordinates.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress completion summary.")
    return parser


def resolve_input_path(args: argparse.Namespace) -> Path:
    path = args.input_option or args.input or DEFAULT_INPUT
    if path.exists():
        return path
    candidate = REPO_ROOT / path
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"input file not found: {path}")


def validate_config(config: TrajectoryConfig) -> None:
    if config.margin_px < 0:
        raise ValueError("--margin-px must be non-negative")
    if config.stationary_speed_m_s < 0:
        raise ValueError("--stationary-speed-m-s must be non-negative")
    if config.max_speed_m_s <= 0:
        raise ValueError("--max-speed-m-s must be positive")
    if config.max_segment_m <= 0:
        raise ValueError("--max-segment-m must be positive")
    if config.reverse_tolerance < 0:
        raise ValueError("--reverse-tolerance must be non-negative")
    if config.stuck_seconds <= 0:
        raise ValueError("--stuck-seconds must be positive")
    if config.px_per_meter <= 0:
        raise ValueError("--px-per-meter must be positive")
    if config.top_n <= 0:
        raise ValueError("--top must be positive")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = TrajectoryConfig(
            kinds=parse_kinds(args.kinds),
            margin_px=args.margin_px,
            stationary_speed_m_s=args.stationary_speed_m_s,
            max_speed_m_s=args.max_speed_m_s,
            max_segment_m=args.max_segment_m,
            reverse_tolerance=args.reverse_tolerance,
            stuck_seconds=args.stuck_seconds,
            px_per_meter=args.px_per_meter,
            canvas_width=args.canvas_width,
            canvas_height=args.canvas_height,
            top_n=args.top,
        )
        validate_config(config)
        input_path = resolve_input_path(args).resolve()
        payload = load_payload(input_path)
        report = build_report(payload, input_path=input_path, config=config)
    except Exception as exc:
        print(f"[VERTICAL TRAJECTORY] error: {exc}", file=sys.stderr)
        return 2

    markdown = render_markdown(report)
    if args.json_out is not None:
        write_text(args.json_out, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.markdown_out is not None:
        write_text(args.markdown_out, markdown)
    if args.json_out is None and args.markdown_out is None:
        print(markdown, end="")
    elif not args.quiet:
        summary = report["summary"]
        print(
            "[VERTICAL TRAJECTORY] "
            f"status={summary['status']} "
            f"tracks={summary['tracks']} "
            f"connector_segments={summary['connector_segments']} "
            f"reverse={summary['reverse_segments']} "
            f"jump_or_speed={summary['jump_or_speed_segments']} "
            f"stuck={summary['stuck_agents']}"
        )
        if args.json_out is not None:
            print(f"[VERTICAL TRAJECTORY] json={args.json_out}")
        if args.markdown_out is not None:
            print(f"[VERTICAL TRAJECTORY] markdown={args.markdown_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
