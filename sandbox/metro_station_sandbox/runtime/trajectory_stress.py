from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from shapely.geometry import Point as ShapelyPoint

from ..planning.plan import RouteKey
from ..design.templates import create_design
from ..station.geometry import (
    dedupe_points,
    document_walkable_geometry,
    element_representative_point,
    element_walkable_domain,
    grid_safe_points,
    level_walkable_geometry,
    project_to_safe_point,
    sample_safe_point,
)
from .mesa_model import MetroStationModel
from ..station.scenario import StationSandboxScenario


@dataclass(frozen=True)
class ProbeCase:
    name: str
    level_id: str
    point: tuple[float, float]
    route_key: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stress-test single mocked passenger points across station geometry."
    )
    parser.add_argument("--seed", type=int, default=20260524)
    parser.add_argument("--samples-per-walkable", type=int, default=4)
    parser.add_argument("--platform-slots", type=int, default=160)
    parser.add_argument("--queue-slots", type=int, default=8)
    parser.add_argument("--max-cases", type=int, default=0, help="0 means all cases.")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("output") / "single_mock_trajectory_stress.json",
    )
    return parser


def make_scenario() -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="single_mock_stress",
        hour=18,
        minutes=1,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="mock",
        sample_hours=1,
        station_design=create_design("visual_demo_station"),
        audit_enabled=False,
        audit_print_events=False,
    )


def collect_probe_cases(
    model: MetroStationModel,
    *,
    samples_per_walkable: int,
    platform_slots: int,
    queue_slots: int,
) -> list[ProbeCase]:
    graph = model.layout_graph.station_graph
    if graph is None or graph.source_document is None:
        raise RuntimeError("Single mock stress requires a StationGraph-backed design.")

    document = graph.source_document
    walkable = document_walkable_geometry(document)
    rng = model.random
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
            for index in range(queue_slots):
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

    for index in range(platform_slots):
        raw_points.append(
            (
                f"platform_waiting_slot:{index}",
                "b2_platform",
                model.layout_graph.platform_waiting_position(index),
            )
        )

    for element in document.elements:
        if element.kind != "walkable_area" and element.role != "floor":
            continue
        domain = element_walkable_domain(element, walkable)
        raw_points.append(
            (
                f"walkable:{element.id}:representative",
                element.level_id,
                project_to_safe_point(
                    domain,
                    element_representative_point(element.geometry),
                    clearance=model.scenario.jupedsim_agent_radius_units,
                ),
            )
        )
        for index in range(samples_per_walkable):
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
        for index, point in enumerate(grid_safe_points(level_domain, spacing=6.0, clearance=0.25)):
            raw_points.append((f"level_grid:{level.id}:{index}", level.id, point))

    cases: list[ProbeCase] = []
    for name, level_id, raw_point in raw_points:
        safe_point = project_to_safe_point(
            walkable,
            raw_point,
            clearance=model.scenario.jupedsim_agent_radius_units,
            require_inside=False,
        )
        if level_id == "b1_concourse":
            route_keys = (RouteKey.ENTRY_GATE_DECISION.value, RouteKey.AFTER_EXIT_VERTICAL.value)
        elif level_id == "b2_platform":
            route_keys = (RouteKey.PLATFORM_TO_VERTICAL.value, RouteKey.AFTER_VERTICAL.value)
        else:
            route_keys = (RouteKey.CURRENT_POSITION.value,)
        for route_key in route_keys:
            cases.append(ProbeCase(f"{name}:{route_key}", level_id, safe_point, route_key))

    deduped: list[ProbeCase] = []
    seen: set[tuple[str, str, tuple[float, float]]] = set()
    for case in cases:
        key = (case.level_id, case.route_key, (round(case.point[0], 3), round(case.point[1], 3)))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(case)
    return deduped


def validate_case(model: MetroStationModel, case: ProbeCase) -> dict[str, object]:
    scenario = model.scenario
    geometry = model.jupedsim_walkable_area()
    adapter = model.jupedsim
    if not adapter.status.available:
        raise RuntimeError(adapter.status.message)

    safe_start = project_to_safe_point(
        geometry,
        case.point,
        clearance=scenario.jupedsim_agent_radius_units,
        require_inside=True,
    )
    passenger = SimpleNamespace(
        pos=safe_start,
        current_level_id=case.level_id,
        assigned_line_id="default",
        assigned_direction="down",
    )
    route = model.route_for_key(case.route_key, passenger)
    route = dedupe_points(route)
    current = safe_start
    max_step = 0.0
    for target in route:
        safe_target = project_to_safe_point(
            geometry,
            target,
            clearance=scenario.jupedsim_target_radius_units * 0.25,
            require_inside=True,
        )
        positions = adapter.simulate_walk_tick(
            starts=[current],
            target=safe_target,
            width=model.layout_graph.geometry.width,
            height=model.layout_graph.geometry.height,
            iterations=1,
            radius=scenario.jupedsim_agent_radius_units,
            target_radius=scenario.jupedsim_target_radius_units,
            walkable_area=geometry,
        )
        if len(positions) != 1:
            raise RuntimeError(f"JuPedSim returned {len(positions)} positions for one mock agent.")
        next_position = positions[0]
        max_step = max(
            max_step,
            ((next_position[0] - current[0]) ** 2 + (next_position[1] - current[1]) ** 2) ** 0.5,
        )
        if not geometry.covers(ShapelyPoint(next_position)):
            raise RuntimeError(
                f"JuPedSim moved mock agent outside walkable area: {next_position!r}"
            )
        current = next_position

    return {
        "name": case.name,
        "level_id": case.level_id,
        "route_key": case.route_key,
        "segments": len(route),
        "start": [round(safe_start[0], 3), round(safe_start[1], 3)],
        "end": [round(current[0], 3), round(current[1], 3)],
        "max_step_m": round(max_step, 3),
    }


def main() -> None:
    args = build_parser().parse_args()
    scenario = make_scenario()
    model = MetroStationModel(scenario, seed=args.seed)
    cases = collect_probe_cases(
        model,
        samples_per_walkable=max(0, args.samples_per_walkable),
        platform_slots=max(0, args.platform_slots),
        queue_slots=max(0, args.queue_slots),
    )
    if args.max_cases > 0:
        cases = cases[: args.max_cases]

    passed: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for case in cases:
        try:
            passed.append(validate_case(model, case))
        except Exception as exc:
            failures.append(
                {
                    "name": case.name,
                    "level_id": case.level_id,
                    "route_key": case.route_key,
                    "point": [round(case.point[0], 3), round(case.point[1], 3)],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    report = {
        "generated_by": "metro_station_sandbox.trajectory_stress",
        "cases": len(cases),
        "passed": len(passed),
        "failed": len(failures),
        "failures": failures,
        "sample_passed": passed[:12],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[STRESS] cases={len(cases)} passed={len(passed)} failed={len(failures)}")
    print(f"[STRESS] report={args.report.resolve()}")
    if failures:
        print(json.dumps(failures[:5], ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
