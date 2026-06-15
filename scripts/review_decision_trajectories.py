from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sandbox.metro_station_sandbox.runtime.contracts import diagnostic_truth_payload

TRACKS_JS = ROOT_DIR / "sandbox/metro_station_sandbox/visual_demo/assets/passenger_tracks_jps.js"
W = 1672.0
H = 941.0


TIME = 0
X = 1
Y = 2
TARGET_X = 5
TARGET_Y = 6
TARGET_MODE = 7
DIAGNOSTIC = 8

DEFAULT_OUTPUT_DIR = Path("output/decision_trajectory_review")

DECISION_GRAPHS = {
    "enter_and_board": (
        "入口缓冲区",
        "entry_gate_decision: 到闸机决策区",
        "choose entry_gate lane: 在决策区按队列/距离选闸机",
        "queue/pass entry_gate: 排队并通过闸机",
        "vertical_transfer_decision: 到换乘/下楼决策区",
        "choose vertical_transfer: 选扶梯/楼梯/电梯",
        "queue/ride vertical_transfer: 排队并乘坐垂直交通",
        "platform_boarding_decision: 到站台候车/屏蔽门决策区",
        "wait/queue boarding_door: 候车并排队上车",
        "depart: 上车离开仿真",
    ),
    "exit_station": (
        "站台下车点",
        "exit_vertical_decision: 到上行垂直交通决策区",
        "choose vertical_transfer: 选扶梯/楼梯/电梯上楼",
        "queue/ride vertical_transfer: 排队并乘坐垂直交通",
        "exit_gate_decision: 到出站闸机决策区",
        "choose exit_gate lane: 在决策区按队列/距离选出站闸机",
        "queue/pass exit_gate: 排队并通过出站闸机",
        "depart: 出站离开仿真",
    ),
    "transfer": (
        "站台换乘起点",
        "vertical_transfer_decision: 如需跨层则选择垂直交通",
        "queue/ride vertical_transfer: 排队并乘坐垂直交通",
        "platform_boarding_decision: 到目标站台候车/屏蔽门决策区",
        "wait/queue boarding_door: 候车并排队上车",
        "depart: 上车离开仿真",
    ),
}


def main() -> None:
    args = _parse_args()
    payload = _load_tracks_payload(args.tracks)
    review = review_decisions(payload, samples=args.samples)
    payload = diagnostic_truth_payload(payload)
    agents = _agents_with_points(payload)
    regions = _decision_regions(payload)
    selected = _select_samples(agents, regions, args.samples)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "decision_trajectory_review.json"
    md_path = args.output_dir / "decision_trajectory_review.md"
    svg_path = args.output_dir / "decision_trajectory_samples.svg"

    json_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_markdown(review, svg_path.name), encoding="utf-8")
    svg_path.write_text(_svg(payload, selected, regions), encoding="utf-8")

    print(f"tracks={args.tracks}")
    print(f"agents={len(agents)} selected={len(selected)}")
    print(f"markdown={md_path}")
    print(f"svg={svg_path}")
    print(f"json={json_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review decision graphs and representative passenger trajectories."
    )
    parser.add_argument(
        "--tracks",
        type=Path,
        default=TRACKS_JS,
        help="JPS_TRACKS JavaScript payload to inspect.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for markdown/json/svg review artifacts.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=6,
        help="Maximum representative agents to include.",
    )
    return parser.parse_args()


def _load_tracks_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"window\.JPS_TRACKS\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not match:
        raise ValueError(f"{path} does not look like a JPS_TRACKS payload")
    return json.loads(match.group(1))


def review_decisions(tracks_payload: dict[str, Any], *, samples: int = 6) -> dict[str, Any]:
    """Review decision-stage target jumps in an in-memory JPS_TRACKS payload."""

    tracks_payload = diagnostic_truth_payload(tracks_payload)
    agents = _agents_with_points(tracks_payload)
    regions = _decision_regions(tracks_payload)
    selected = _select_samples(agents, regions, samples)
    return _build_review(tracks_payload, agents, selected, regions)


def _agents_with_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [agent for agent in payload.get("agents", []) if _points(agent)]


def _build_review(
    payload: dict[str, Any],
    agents: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    regions: list[dict[str, Any]],
) -> dict[str, Any]:
    route_counts = Counter(str(agent.get("route", "unknown")) for agent in agents)
    completion = payload.get("clearance_audit", {})
    scenario = payload.get("scenario", {})
    return {
        "scenario": scenario,
        "duration_s": payload.get("duration"),
        "clearance_audit": completion,
        "route_counts": dict(sorted(route_counts.items())),
        "decision_regions": [
            {
                "id": region["id"],
                "label": region.get("label", region["id"]),
                "bbox_norm": _bbox(region["points"]),
            }
            for region in regions
        ],
        "decision_graphs": DECISION_GRAPHS,
        "samples": [_agent_review(agent, regions) for agent in selected],
        "population_warnings": _population_warnings(agents, regions),
    }


def _population_warnings(
    agents: list[dict[str, Any]],
    regions: list[dict[str, Any]],
) -> dict[str, Any]:
    suspicious = []
    for agent in agents:
        for event in _target_jump_events(agent, regions):
            if event["nearest_decision_region_distance_px"] > 90:
                suspicious.append({"agent_id": agent.get("id"), **event})
    suspicious.sort(key=lambda item: item["nearest_decision_region_distance_px"], reverse=True)
    return {
        "target_jumps_far_from_decision_regions": suspicious[:20],
        "far_jump_agent_count": len({item["agent_id"] for item in suspicious}),
        "far_jump_event_count": len(suspicious),
    }


def _select_samples(
    agents: list[dict[str, Any]],
    regions: list[dict[str, Any]],
    max_samples: int,
) -> list[dict[str, Any]]:
    buckets: list[tuple[str, list[dict[str, Any]]]] = [
        (
            "enter_left",
            [
                agent
                for agent in agents
                if agent.get("route") == "enter_and_board"
                and _points(agent)[0][X] < W * 0.5
            ],
        ),
        (
            "enter_right",
            [
                agent
                for agent in agents
                if agent.get("route") == "enter_and_board"
                and _points(agent)[0][X] >= W * 0.5
            ],
        ),
        (
            "exit_left_platform",
            [
                agent
                for agent in agents
                if agent.get("route") == "exit_station"
                and _points(agent)[0][X] < W * 0.5
            ],
        ),
        (
            "exit_right_platform",
            [
                agent
                for agent in agents
                if agent.get("route") == "exit_station"
                and _points(agent)[0][X] >= W * 0.5
            ],
        ),
        (
            "queued_vertical_or_gate",
            [
                agent
                for agent in agents
                if "enqueued" in _mode_counts(agent)
            ],
        ),
        (
            "largest_target_jump",
            sorted(
                agents,
                key=lambda agent: _max_target_jump(agent),
                reverse=True,
            ),
        ),
    ]

    selected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for label, bucket in buckets:
        if len(selected) >= max_samples:
            break
        if not bucket:
            continue
        ranked = sorted(
            bucket,
            key=lambda agent: (
                _score_agent(agent, regions),
                len(_points(agent)),
            ),
            reverse=True,
        )
        for agent in ranked:
            agent_id = int(agent.get("id", -1))
            if agent_id in seen:
                continue
            copied = dict(agent)
            copied["sample_label"] = label
            selected.append(copied)
            seen.add(agent_id)
            break

    return selected[:max_samples]


def _score_agent(agent: dict[str, Any], regions: list[dict[str, Any]]) -> float:
    hits = _region_hits(agent, regions)
    jumps = _target_jump_events(agent, regions)
    queue_bonus = 2 if "enqueued" in _mode_counts(agent) else 0
    return len(hits) * 4 + len(jumps) + queue_bonus


def _agent_review(agent: dict[str, Any], regions: list[dict[str, Any]]) -> dict[str, Any]:
    points = _points(agent)
    start = points[0]
    end = points[-1]
    duration = max(0.001, float(end[TIME]) - float(start[TIME]))
    path_len = _path_length(points)
    displacement = _distance((start[X], start[Y]), (end[X], end[Y]))
    directness = path_len / displacement if displacement > 1 else None
    jumps = _target_jump_events(agent, regions)
    far_jumps = [
        event for event in jumps if event["nearest_decision_region_distance_px"] > 90
    ]
    return {
        "sample_label": agent.get("sample_label"),
        "agent_id": agent.get("id"),
        "route": agent.get("route"),
        "route_chain": agent.get("route_chain", []),
        "time_window_s": [round(float(start[TIME]), 2), round(float(end[TIME]), 2)],
        "start_norm": _norm_xy(start[X], start[Y]),
        "end_norm": _norm_xy(end[X], end[Y]),
        "samples": len(points),
        "path_length_px": round(path_len, 2),
        "avg_speed_px_s": round(path_len / duration, 2),
        "directness_ratio": round(directness, 2) if directness is not None else None,
        "target_modes": dict(_mode_counts(agent)),
        "diagnostics": dict(_diagnostic_counts(agent)),
        "decision_regions_touched": _region_hits(agent, regions),
        "target_jump_events": jumps,
        "judgement": _judgement(agent, regions, far_jumps),
    }


def _judgement(
    agent: dict[str, Any],
    regions: list[dict[str, Any]],
    far_jumps: list[dict[str, Any]],
) -> str:
    hits = _region_hits(agent, regions)
    modes = _mode_counts(agent)
    if far_jumps:
        return "需要看动画复核：有目标点大跳变发生在固定决策区外，可能是不自然绕行或状态切换太早。"
    if not hits:
        return "样本太短或未经过决策区，不能判断完整行为。"
    if "enqueued" in modes:
        return "基本像真人：先到决策区，再进入队列；目标切换与排队状态能对应。"
    return "局部正常：行走目标切换靠近决策区，但此样本未覆盖完整排队/服务过程。"


def _decision_regions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    layout = payload.get("layout", {})
    regions = layout.get("decision_regions", [])
    return [region for region in regions if isinstance(region, dict) and region.get("points")]


def _points(agent: dict[str, Any]) -> list[list[Any]]:
    points = agent.get("points", [])
    return points if isinstance(points, list) else []


def _mode_counts(agent: dict[str, Any]) -> Counter[str]:
    return Counter(str(point[TARGET_MODE]) for point in _points(agent) if len(point) > TARGET_MODE)


def _diagnostic_counts(agent: dict[str, Any]) -> Counter[str]:
    return Counter(str(point[DIAGNOSTIC]) for point in _points(agent) if len(point) > DIAGNOSTIC)


def _path_length(points: list[list[Any]]) -> float:
    return sum(
        _distance((a[X], a[Y]), (b[X], b[Y]))
        for a, b in zip(points, points[1:])
    )


def _target_jump_events(
    agent: dict[str, Any],
    regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    previous_target: tuple[float, float] | None = None
    for point in _points(agent):
        if len(point) <= TARGET_Y or point[TARGET_X] is None or point[TARGET_Y] is None:
            continue
        current_target = (float(point[TARGET_X]), float(point[TARGET_Y]))
        if previous_target is not None:
            jump = _distance(previous_target, current_target)
            if jump >= 70:
                nearest = _nearest_region_distance(point[X], point[Y], regions)
                events.append(
                    {
                        "time_s": round(float(point[TIME]), 2),
                        "position_norm": _norm_xy(point[X], point[Y]),
                        "target_from_norm": _norm_xy(*previous_target),
                        "target_to_norm": _norm_xy(*current_target),
                        "jump_px": round(jump, 2),
                        "nearest_decision_region": nearest["id"],
                        "nearest_decision_region_distance_px": round(nearest["distance_px"], 2),
                    }
                )
        previous_target = current_target
    return events


def _max_target_jump(agent: dict[str, Any]) -> float:
    jumps = _target_jump_events(agent, [])
    if not jumps:
        return 0.0
    return max(float(event["jump_px"]) for event in jumps)


def _region_hits(agent: dict[str, Any], regions: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for point in _points(agent):
        nx, ny = float(point[X]) / W, float(point[Y]) / H
        for region in regions:
            region_id = str(region["id"])
            if region_id in seen:
                continue
            if _inside_polygon(nx, ny, region["points"]):
                seen.add(region_id)
                ordered.append(region_id)
    return ordered


def _nearest_region_distance(
    x: float,
    y: float,
    regions: list[dict[str, Any]],
) -> dict[str, Any]:
    if not regions:
        return {"id": "none", "distance_px": float("inf")}
    best = {"id": "none", "distance_px": float("inf")}
    nx, ny = float(x) / W, float(y) / H
    for region in regions:
        min_x, min_y, max_x, max_y = _bbox(region["points"])
        dx_norm = max(min_x - nx, 0.0, nx - max_x)
        dy_norm = max(min_y - ny, 0.0, ny - max_y)
        distance = math.hypot(dx_norm * W, dy_norm * H)
        if distance < best["distance_px"]:
            best = {"id": str(region["id"]), "distance_px": distance}
    return best


def _bbox(points: list[list[float]]) -> list[float]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [round(min(xs), 5), round(min(ys), 5), round(max(xs), 5), round(max(ys), 5)]


def _inside_polygon(x: float, y: float, points: list[list[float]]) -> bool:
    inside = False
    j = len(points) - 1
    for i, point in enumerate(points):
        xi, yi = float(point[0]), float(point[1])
        xj, yj = float(points[j][0]), float(points[j][1])
        crosses = (yi > y) != (yj > y)
        if crosses:
            x_at_y = (xj - xi) * (y - yi) / max(1e-9, yj - yi) + xi
            if x < x_at_y:
                inside = not inside
        j = i
    return inside


def _norm_xy(x: float, y: float) -> list[float]:
    return [round(float(x) / W, 4), round(float(y) / H, 4)]


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _markdown(review: dict[str, Any], svg_name: str) -> str:
    lines: list[str] = []
    scenario = review["scenario"]
    lines.append("# Decision Trajectory Review")
    lines.append("")
    lines.append(
        f"- scenario: minutes={scenario.get('minutes')} "
        f"entry_count_hour={scenario.get('entry_count_hour')} "
        f"exit_count_hour={scenario.get('exit_count_hour')} "
        f"duration_s={review.get('duration_s')}"
    )
    lines.append(f"- route_counts: {review['route_counts']}")
    audit = review.get("clearance_audit", {})
    lines.append(
        f"- completed_agents={audit.get('completed_agents')} "
        f"remaining_agents={audit.get('remaining_agents')}"
    )
    warnings = review["population_warnings"]
    lines.append(
        f"- far_target_jump_events={warnings['far_jump_event_count']} "
        f"far_target_jump_agents={warnings['far_jump_agent_count']}"
    )
    lines.append(f"- trajectory_overlay: {svg_name}")
    lines.append("")

    lines.append("## Decision Graphs")
    for route, graph in review["decision_graphs"].items():
        lines.append("")
        lines.append(f"### {route}")
        lines.append(" -> ".join(graph))
    lines.append("")

    lines.append("## Decision Regions")
    for region in review["decision_regions"]:
        lines.append(f"- {region['id']}: bbox_norm={region['bbox_norm']}")
    lines.append("")

    lines.append("## Representative Samples")
    for sample in review["samples"]:
        lines.append("")
        lines.append(
            f"### {sample['sample_label']} / agent {sample['agent_id']} / {sample['route']}"
        )
        lines.append(
            f"- time={sample['time_window_s']} start={sample['start_norm']} "
            f"end={sample['end_norm']} samples={sample['samples']}"
        )
        lines.append(
            f"- path_length_px={sample['path_length_px']} "
            f"avg_speed_px_s={sample['avg_speed_px_s']} "
            f"directness_ratio={sample['directness_ratio']}"
        )
        lines.append(f"- target_modes={sample['target_modes']}")
        lines.append(f"- diagnostics={sample['diagnostics']}")
        lines.append(f"- decision_regions_touched={sample['decision_regions_touched']}")
        lines.append(f"- target_jump_events={sample['target_jump_events']}")
        lines.append(f"- judgement={sample['judgement']}")
    lines.append("")

    if warnings["target_jumps_far_from_decision_regions"]:
        lines.append("## Population Warnings")
        for warning in warnings["target_jumps_far_from_decision_regions"][:10]:
            lines.append(
                f"- agent {warning['agent_id']} t={warning['time_s']} "
                f"jump_px={warning['jump_px']} pos={warning['position_norm']} "
                f"nearest={warning['nearest_decision_region']} "
                f"dist_px={warning['nearest_decision_region_distance_px']}"
            )
        lines.append("")
    return "\n".join(lines)


def _svg(
    payload: dict[str, Any],
    selected: list[dict[str, Any]],
    regions: list[dict[str, Any]],
) -> str:
    colors = ("#f6b342", "#4aa3ff", "#52d273", "#e45f6f", "#8f6ed5", "#00a890")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">',
        '<rect width="100%" height="100%" fill="#f7f7f4"/>',
    ]
    for region in payload.get("layout", {}).get("walkable_regions", []):
        points = " ".join(f"{x * W:.1f},{y * H:.1f}" for x, y in region.get("points", []))
        parts.append(f'<polygon points="{points}" fill="#e6e1d6" stroke="#c9c2b4" stroke-width="1"/>')
    for region in regions:
        points = " ".join(f"{x * W:.1f},{y * H:.1f}" for x, y in region["points"])
        parts.append(
            f'<polygon points="{points}" fill="rgba(255,255,255,0.15)" '
            f'stroke="#111" stroke-dasharray="8 6" stroke-width="2"/>'
        )
        min_x, min_y, _, _ = _bbox(region["points"])
        parts.append(
            f'<text x="{min_x * W + 4:.1f}" y="{min_y * H + 16:.1f}" '
            f'font-family="Arial" font-size="15" fill="#111">{region["id"]}</text>'
        )
    for index, agent in enumerate(selected):
        color = colors[index % len(colors)]
        points = _points(agent)
        line = " ".join(f"{point[X]},{point[Y]}" for point in points)
        label = f'{agent.get("sample_label")} #{agent.get("id")}'
        parts.append(
            f'<polyline points="{line}" fill="none" stroke="{color}" '
            f'stroke-width="5" stroke-linejoin="round" stroke-linecap="round" opacity="0.82"/>'
        )
        start = points[0]
        end = points[-1]
        parts.append(f'<circle cx="{start[X]}" cy="{start[Y]}" r="8" fill="{color}"/>')
        parts.append(f'<rect x="{end[X] - 6}" y="{end[Y] - 6}" width="12" height="12" fill="{color}"/>')
        parts.append(
            f'<text x="{end[X] + 10}" y="{end[Y] - 8}" font-family="Arial" '
            f'font-size="18" fill="{color}" font-weight="700">{label}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


if __name__ == "__main__":
    main()
