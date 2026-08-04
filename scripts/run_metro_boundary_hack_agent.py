from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from math import hypot
from pathlib import Path
from typing import Any, Sequence

from shapely.geometry import Point as ShapelyPoint
from shapely.ops import nearest_points


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sandbox.metro_station_sandbox.planning.plan import AgentIntent, AgentState  # noqa: E402
from sandbox.metro_station_sandbox.agents import PassengerAgent  # noqa: E402
from sandbox.metro_station_sandbox.design import create_design  # noqa: E402
from sandbox.metro_station_sandbox.station.geometry import (  # noqa: E402
    document_walkable_geometry,
    element_representative_point,
    element_walkable_domain,
    grid_safe_points,
    level_walkable_geometry,
    project_to_safe_point,
    safe_core,
    sample_safe_point,
)
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel  # noqa: E402
from sandbox.metro_station_sandbox.station.scenario import StationSandboxScenario  # noqa: E402


AGENT_NAME = "Hans Landa"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "metro_boundary_hack_agent"
FIELDNAMES = (
    "case_id",
    "status",
    "severity",
    "reward_points",
    "intent",
    "expected_outcome",
    "jupedsim_operational_model",
    "simulation_clock_mode",
    "goal_graph_mode",
    "origin",
    "boundary_relation",
    "level_id",
    "raw_start_x",
    "raw_start_y",
    "start_x",
    "start_y",
    "normalization_distance",
    "final_state",
    "final_x",
    "final_y",
    "steps_run",
    "seconds_run",
    "boarded_persons",
    "station_persons",
    "failure_reason",
)


@dataclass(frozen=True)
class BoundaryCase:
    case_id: str
    origin: str
    level_id: str
    point: tuple[float, float]
    intent: str
    expected_outcome: str
    boundary_relation: str = "safe"
    raw_point: tuple[float, float] | None = None
    normalization_distance: float = 0.0


@dataclass(frozen=True)
class OutputPaths:
    csv_path: Path
    json_path: Path
    markdown_path: Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Adversarial lifecycle boundary tester for MetroStationModel. "
            "Places one real passenger at edge-case coordinates and verifies boarding/exiting."
        )
    )
    parser.add_argument("--seed", type=int, default=20260525)
    parser.add_argument("--minutes", type=int, default=12)
    parser.add_argument("--tick-seconds", type=int, default=1)
    parser.add_argument("--samples-per-walkable", type=int, default=2)
    parser.add_argument("--platform-slots", type=int, default=48)
    parser.add_argument("--queue-slots", type=int, default=6)
    parser.add_argument("--boundary-samples", type=int, default=8)
    parser.add_argument("--epsilon-boundary-samples", type=int, default=4)
    parser.add_argument("--boundary-epsilon", type=float, default=0.05)
    parser.add_argument("--grid-spacing", type=float, default=8.0)
    parser.add_argument("--max-cases", type=int, default=60, help="0 means all cases.")
    parser.add_argument("--include-transfer", action="store_true", default=True)
    parser.add_argument("--no-transfer", dest="include_transfer", action="store_false")
    parser.add_argument(
        "--design-template",
        default="visual_demo_station",
        choices=(
            "single_level_terminal",
            "two_level_island_platform",
            "three_level_transfer",
            "visual_demo_station",
        ),
    )
    parser.add_argument(
        "--movement-backend",
        choices=("jupedsim", "batched_jupedsim", "micro_jupedsim"),
        default="jupedsim",
    )
    parser.add_argument(
        "--jupedsim-model",
        choices=("collision_free_speed", "social_force"),
        default="collision_free_speed",
    )
    parser.add_argument(
        "--clock-mode",
        choices=("legacy_scaled", "physical"),
        default="legacy_scaled",
    )
    parser.add_argument(
        "--goal-graph-mode",
        choices=("active",),
        default="active",
    )
    parser.add_argument("--goal-graph-config", type=Path, default=None)
    parser.add_argument("--initial-train-offset-seconds", type=int, default=20)
    parser.add_argument("--train-headway-seconds", type=int, default=90)
    parser.add_argument("--train-dwell-seconds", type=int, default=40)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-stem", default="metro_boundary_hack_agent")
    parser.add_argument("--csv-out", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--md-out", type=Path, default=None)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def output_paths(args: argparse.Namespace) -> OutputPaths:
    out_dir = args.out_dir
    return OutputPaths(
        csv_path=args.csv_out or out_dir / f"{args.output_stem}.csv",
        json_path=args.json_out or out_dir / f"{args.output_stem}.json",
        markdown_path=args.md_out or out_dir / f"{args.output_stem}.md",
    )


def make_scenario(args: argparse.Namespace) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="boundary_hack_agent",
        hour=18,
        minutes=max(1, int(args.minutes)),
        tick_seconds=max(1, int(args.tick_seconds)),
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label=AGENT_NAME,
        sample_hours=1,
        station_design=create_design(args.design_template),
        movement_backend_name=args.movement_backend,
        jupedsim_operational_model=args.jupedsim_model,
        simulation_clock_mode=args.clock_mode,
        goal_graph_mode=args.goal_graph_mode,
        goal_graph_catalog_path=(
            None if args.goal_graph_config is None else str(args.goal_graph_config)
        ),
        audit_enabled=True,
        audit_print_events=False,
        initial_train_offset_seconds=max(1, int(args.initial_train_offset_seconds)),
        train_headway_seconds=max(10, int(args.train_headway_seconds)),
        train_dwell_seconds=max(5, int(args.train_dwell_seconds)),
    )


def collect_boundary_cases(
    model: MetroStationModel,
    args: argparse.Namespace,
) -> list[BoundaryCase]:
    graph = model.layout_graph.station_graph
    if graph is None or graph.source_document is None:
        raise RuntimeError("Boundary hack agent requires a StationGraph-backed design.")

    document = graph.source_document
    walkable = document_walkable_geometry(document)
    raw_points: list[tuple[str, str, tuple[float, float]]] = []

    for node in graph.nodes.values():
        raw_points.append((f"node:{node.node_id}", node.level_id, node.position))

    for facility in model.facilities:
        spec = facility.spec
        if spec.entry_level_id is not None:
            raw_points.append(
                (f"facility:{spec.facility_id}:position", spec.entry_level_id, spec.position)
            )
            raw_points.append(
                (
                    f"facility:{spec.facility_id}:queue_anchor",
                    spec.entry_level_id,
                    spec.queue_layout.anchor,
                )
            )
            for index in range(max(0, args.queue_slots)):
                raw_points.append(
                    (
                        f"facility:{spec.facility_id}:queue_slot:{index}",
                        spec.entry_level_id,
                        spec.queue_layout.slot(index),
                    )
                )
        if spec.exit_level_id is not None:
            raw_points.append(
                (f"facility:{spec.facility_id}:exit", spec.exit_level_id, spec.exit_position)
            )

    for index in range(max(0, args.platform_slots)):
        raw_points.append(
            (
                f"platform_waiting_slot:{index}",
                "b2_platform",
                model.layout_graph.platform_waiting_position(index),
            )
        )

    rng = model.random
    for element in document.elements:
        if element.kind != "walkable_area" and element.role != "floor":
            continue
        domain = element_walkable_domain(element, walkable)
        raw_points.append(
            (
                f"walkable:{element.id}:representative",
                element.level_id,
                element_representative_point(element.geometry),
            )
        )
        for index in range(max(0, args.samples_per_walkable)):
            raw_points.append(
                (
                    f"walkable:{element.id}:sample:{index}",
                    element.level_id,
                    sample_safe_point(
                        domain,
                        rng,
                        clearance=model.scenario.jupedsim_agent_radius_units,
                    ),
                )
            )

    for level in document.levels:
        level_domain = level_walkable_geometry(document, level.id, walkable)
        for index, point in enumerate(
            grid_safe_points(
                level_domain,
                spacing=max(1.0, float(args.grid_spacing)),
                clearance=model.scenario.jupedsim_agent_radius_units,
            )
        ):
            raw_points.append((f"level_grid:{level.id}:{index}", level.id, point))
        raw_points.extend(_boundary_points(level.id, level_domain, args.boundary_samples))

    cases = _cases_from_raw_points(
        model,
        raw_points,
        include_transfer=bool(args.include_transfer),
        max_cases=0,
    )
    cases.extend(
        _boundary_epsilon_cases(
            model,
            count=max(0, int(args.epsilon_boundary_samples)),
            epsilon=max(0.001, float(args.boundary_epsilon)),
            include_transfer=bool(args.include_transfer),
            start_index=len(cases) + 1,
        )
    )
    return _limit_cases(cases, max(0, int(args.max_cases)))


def _boundary_points(
    level_id: str,
    domain,
    count: int,
) -> list[tuple[str, str, tuple[float, float]]]:
    if count <= 0 or domain.is_empty:
        return []
    boundary = domain.boundary
    if boundary.is_empty or boundary.length <= 0:
        return []
    points: list[tuple[str, str, tuple[float, float]]] = []
    for index in range(count):
        fraction = (index + 0.5) / count
        point = boundary.interpolate(boundary.length * fraction)
        points.append((f"boundary:{level_id}:{index}", level_id, (float(point.x), float(point.y))))
    return points


def _boundary_epsilon_cases(
    model: MetroStationModel,
    *,
    count: int,
    epsilon: float,
    include_transfer: bool,
    start_index: int,
) -> list[BoundaryCase]:
    if count <= 0:
        return []
    graph = model.layout_graph.station_graph
    document = graph.source_document if graph is not None else None
    if document is None:
        return []

    walkable = document_walkable_geometry(document)
    cases: list[BoundaryCase] = []
    next_index = start_index
    clearance = model.scenario.jupedsim_agent_radius_units
    for level in document.levels:
        domain = level_walkable_geometry(document, level.id, walkable)
        if domain.is_empty or domain.boundary.is_empty or domain.boundary.length <= 0:
            continue
        core = safe_core(domain, max(clearance, epsilon))
        expanded_boundary = domain.buffer(epsilon).boundary
        for sample_index in range(count):
            fraction = (sample_index + 0.5) / count
            boundary_point = domain.boundary.interpolate(domain.boundary.length * fraction)
            _, inside_point = nearest_points(boundary_point, core)
            _, outside_point = nearest_points(boundary_point, expanded_boundary)
            relation_points = (
                ("inside_epsilon", (float(inside_point.x), float(inside_point.y))),
                ("on_boundary", (float(boundary_point.x), float(boundary_point.y))),
                ("outside_epsilon", (float(outside_point.x), float(outside_point.y))),
            )
            for relation, raw_point in relation_points:
                if relation == "outside_epsilon" and domain.covers(ShapelyPoint(raw_point)):
                    continue
                normalized = project_to_safe_point(
                    domain,
                    raw_point,
                    clearance=clearance,
                    require_inside=False,
                )
                for intent, expected in _intents_for_level(
                    level.id,
                    include_transfer=include_transfer,
                ):
                    cases.append(
                        BoundaryCase(
                            case_id=f"case_{next_index:04d}",
                            origin=(
                                f"epsilon_boundary:{relation}:{level.id}:{sample_index}"
                            ),
                            level_id=level.id,
                            point=normalized,
                            intent=intent,
                            expected_outcome=expected,
                            boundary_relation=relation,
                            raw_point=raw_point,
                            normalization_distance=hypot(
                                normalized[0] - raw_point[0],
                                normalized[1] - raw_point[1],
                            ),
                        )
                    )
                    next_index += 1
    return cases


def _cases_from_raw_points(
    model: MetroStationModel,
    raw_points: list[tuple[str, str, tuple[float, float]]],
    *,
    include_transfer: bool,
    max_cases: int,
) -> list[BoundaryCase]:
    graph = model.layout_graph.station_graph
    document = graph.source_document if graph is not None else None
    if document is None:
        return []
    walkable = document_walkable_geometry(document)
    cases: list[BoundaryCase] = []
    seen: set[tuple[str, str, str, tuple[float, float]]] = set()

    for origin, level_id, raw_point in raw_points:
        level_domain = level_walkable_geometry(document, level_id, walkable)
        safe_point = project_to_safe_point(
            level_domain,
            raw_point,
            clearance=model.scenario.jupedsim_agent_radius_units,
            require_inside=False,
        )
        intents = _intents_for_level(level_id, include_transfer=include_transfer)
        for intent, expected in intents:
            key = (
                level_id,
                intent,
                origin.split(":", 1)[0],
                (round(safe_point[0], 3), round(safe_point[1], 3)),
            )
            if key in seen:
                continue
            seen.add(key)
            cases.append(
                BoundaryCase(
                    case_id=f"case_{len(cases) + 1:04d}",
                    origin=origin,
                    level_id=level_id,
                    point=safe_point,
                    intent=intent,
                    expected_outcome=expected,
                )
            )
    return _limit_cases(cases, max_cases)


def _limit_cases(cases: list[BoundaryCase], max_cases: int) -> list[BoundaryCase]:
    if max_cases <= 0 or len(cases) <= max_cases:
        return cases

    buckets: dict[tuple[str, str, str], list[BoundaryCase]] = {}
    for case in cases:
        origin_kind = case.origin.split(":", 1)[0]
        key = (case.intent, case.level_id, origin_kind, case.boundary_relation)
        buckets.setdefault(key, []).append(case)

    selected: list[BoundaryCase] = []
    while len(selected) < max_cases and buckets:
        for key in sorted(list(buckets)):
            bucket = buckets[key]
            if not bucket:
                buckets.pop(key)
                continue
            selected.append(bucket.pop(0))
            if len(selected) >= max_cases:
                break
    return selected


def _intents_for_level(
    level_id: str,
    *,
    include_transfer: bool,
) -> tuple[tuple[str, str], ...]:
    if "platform" in level_id.lower() or level_id.upper() == "B2":
        intents = [(AgentIntent.EXIT_STATION.value, "exited")]
        if include_transfer:
            intents.append((AgentIntent.TRANSFER.value, "boarded"))
        return tuple(intents)
    return ((AgentIntent.ENTER_AND_BOARD.value, "boarded"),)


def run_case(case: BoundaryCase, args: argparse.Namespace, *, seed: int) -> dict[str, Any]:
    scenario = make_scenario(args)
    model = MetroStationModel(scenario, seed=seed)
    passenger = _place_passenger(model, case)
    started = time.perf_counter()
    trace: list[dict[str, Any]] = []
    last_state: str | None = None
    failure_reason = ""
    severity = "pass"

    try:
        for _ in range(scenario.horizon_steps):
            model.step()
            if passenger.state != last_state:
                trace.append(_trace_event(model, passenger))
                last_state = passenger.state
            if (
                passenger.state != AgentState.DEPARTED.value
                and not model.jupedsim_walkable_area().covers(ShapelyPoint(passenger.pos))
            ):
                failure_reason = "passenger_left_walkable_area"
                severity = "hard_failure"
                break
            if passenger.state == AgentState.DEPARTED.value:
                break
    except Exception as exc:
        failure_reason = f"{type(exc).__name__}: {exc}"
        severity = "hard_failure"

    elapsed = time.perf_counter() - started
    if not failure_reason:
        failure_reason, severity = _classify_case_result(model, passenger, case)

    reward_points = _reward_points(severity)
    status = "ok" if severity == "pass" else "failed" if severity == "hard_failure" else "warning"
    metrics = model.frames[-1].get("metrics", {}) if model.frames else {}
    return {
        "case_id": case.case_id,
        "status": status,
        "severity": severity,
        "reward_points": reward_points,
        "intent": case.intent,
        "expected_outcome": case.expected_outcome,
        "jupedsim_operational_model": args.jupedsim_model,
        "simulation_clock_mode": args.clock_mode,
        "goal_graph_mode": args.goal_graph_mode,
        "origin": case.origin,
        "boundary_relation": case.boundary_relation,
        "level_id": case.level_id,
        "raw_start_x": round((case.raw_point or case.point)[0], 3),
        "raw_start_y": round((case.raw_point or case.point)[1], 3),
        "start_x": round(case.point[0], 3),
        "start_y": round(case.point[1], 3),
        "normalization_distance": round(case.normalization_distance, 6),
        "final_state": passenger.state,
        "final_x": round(passenger.pos[0], 3),
        "final_y": round(passenger.pos[1], 3),
        "steps_run": model.step_index,
        "seconds_run": model.step_index * scenario.tick_seconds,
        "elapsed_seconds": round(elapsed, 4),
        "boarded_persons": model.boarded_persons,
        "station_persons": int(metrics.get("station_persons", len(model.passengers)) or 0),
        "trace": trace,
        "audit_counts": model.audit.summary(),
        "failure_reason": failure_reason,
    }


def _place_passenger(model: MetroStationModel, case: BoundaryCase) -> PassengerAgent:
    passenger = model._spawn_passenger(
        intent=case.intent,
        initial_position=case.point,
        initial_level_id=case.level_id,
    )
    passenger.assigned_line_id = "default"
    passenger.assigned_direction = "down"
    return passenger


def _trace_event(model: MetroStationModel, passenger: PassengerAgent) -> dict[str, Any]:
    goal = passenger.current_goal.as_dict()
    return {
        "step": model.step_index,
        "time_s": model.step_index * model.scenario.tick_seconds,
        "state": passenger.state,
        "x": round(passenger.pos[0], 3),
        "y": round(passenger.pos[1], 3),
        "goal": goal,
    }


def _classify_case_result(
    model: MetroStationModel,
    passenger: PassengerAgent,
    case: BoundaryCase,
) -> tuple[str, str]:
    if passenger.state != AgentState.DEPARTED.value:
        return "did_not_depart_within_horizon", "hard_failure"
    if case.expected_outcome == "boarded" and model.boarded_persons < passenger.group_size:
        return "departed_without_boarding", "hard_failure"
    if case.expected_outcome == "exited" and model.boarded_persons:
        return "exit_case_counted_as_boarding", "hard_failure"

    severe_audits = {
        key: value
        for key, value in model.audit.summary().items()
        if "failed" in key or "error" in key or "missing" in key
    }
    if severe_audits:
        return f"audit_risk:{json.dumps(severe_audits, sort_keys=True)}", "diagnostic"
    if model.step_index >= int(model.scenario.horizon_steps * 0.85):
        return "completed_near_horizon", "diagnostic"
    return "", "pass"


def _reward_points(severity: str) -> int:
    if severity == "hard_failure":
        return 100
    if severity == "diagnostic":
        return 25
    return 0


def write_outputs(
    paths: OutputPaths,
    *,
    args: argparse.Namespace,
    cases: Sequence[BoundaryCase],
    rows: Sequence[dict[str, Any]],
) -> None:
    for path in (paths.csv_path, paths.json_path, paths.markdown_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    with paths.csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    failures = [row for row in rows if row["severity"] == "hard_failure"]
    diagnostics = [row for row in rows if row["severity"] == "diagnostic"]
    payload = {
        "generated_by": "scripts.run_metro_boundary_hack_agent",
        "agent_name": AGENT_NAME,
        "generated_at": datetime.now(UTC).isoformat(),
        "reward_policy": {"hard_failure": 100, "diagnostic": 25, "pass": 0},
        "parameters": vars(args),
        "summary": {
            "cases": len(cases),
            "runs": len(rows),
            "passed": sum(1 for row in rows if row["severity"] == "pass"),
            "diagnostic": len(diagnostics),
            "hard_failed": len(failures),
            "reward_points": sum(int(row["reward_points"]) for row in rows),
        },
        "runs": rows,
    }
    paths.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    paths.markdown_path.write_text(_markdown_report(payload), encoding="utf-8")


def _markdown_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Metro Boundary Hack Agent",
        "",
        f"- agent: {payload['agent_name']}",
        f"- cases: {summary['cases']}",
        f"- passed: {summary['passed']}",
        f"- diagnostic: {summary['diagnostic']}",
        f"- hard_failed: {summary['hard_failed']}",
        f"- reward_points: {summary['reward_points']}",
        "",
        "| status | severity | reward | intent | expected | origin | level | start | seconds | reason |",
        "| --- | --- | ---: | --- | --- | --- | --- | --- | ---: | --- |",
    ]
    sorted_rows = sorted(
        payload["runs"],
        key=lambda row: (-int(row["reward_points"]), row["case_id"]),
    )
    for row in sorted_rows[:80]:
        lines.append(
            "| {status} | {severity} | {reward_points} | {intent} | {expected_outcome} | "
            "{origin} | {level_id} | [{start_x}, {start_y}] | {seconds_run} | {failure_reason} |".format(
                **row
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = output_paths(args)
    probe_model = MetroStationModel(make_scenario(args), seed=args.seed)
    cases = collect_boundary_cases(probe_model, args)

    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        row = run_case(case, args, seed=args.seed + index + 1)
        rows.append(row)
        if not args.quiet:
            print(
                "[BOUNDARY] "
                f"{case.case_id} status={row['status']} reward={row['reward_points']} "
                f"intent={case.intent} origin={case.origin}"
            )
        if args.fail_fast and row["severity"] == "hard_failure":
            break

    write_outputs(paths, args=args, cases=cases, rows=rows)
    hard_failed = sum(1 for row in rows if row["severity"] == "hard_failure")
    diagnostics = sum(1 for row in rows if row["severity"] == "diagnostic")
    reward = sum(int(row["reward_points"]) for row in rows)
    print(f"[BOUNDARY] wrote_csv={paths.csv_path.resolve()}")
    print(f"[BOUNDARY] wrote_json={paths.json_path.resolve()}")
    print(f"[BOUNDARY] wrote_markdown={paths.markdown_path.resolve()}")
    print(
        f"[BOUNDARY] runs={len(rows)} hard_failed={hard_failed} "
        f"diagnostic={diagnostics} reward_points={reward}"
    )
    return 1 if hard_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
