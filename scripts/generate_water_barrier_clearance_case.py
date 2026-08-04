from __future__ import annotations

import json
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path

from metro_station.adapters.simulation.cli import build_parser, make_scenario
from metro_station.adapters.simulation.design.schema import DesignElement, ElementGeometry
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.executor import MesaSimulationExecutor
from metro_station.adapters.simulation.runtime.clearance_detection import build_clearance_debug
from metro_station.adapters.simulation.simulation_outputs.visual_tracks import (
    write_mesa_visual_tracks_js,
)
from metro_station.application.simulation import SimulationRequest, run_simulation


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "output" / "tutorial" / "water_barrier_clearance_120_tracks.js"
SEED = 42
INITIAL_PERSONS = 120
BARRIER_ID = "water_barrier_tutorial"
BARRIER_GEOMETRY = {
    "x_m": 41.2,
    "y_m": 31.0,
    "width_m": 1.0,
    "height_m": 5.5,
}


def generate_water_barrier_case(output_path: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    baseline_design = create_design("visual_demo_station")
    barrier = _water_barrier()
    candidate_design = replace(
        baseline_design,
        id=f"{baseline_design.id}_water_barrier",
        label=f"{baseline_design.label} + 水马 A",
        elements=(*baseline_design.elements, barrier),
    )

    with redirect_stdout(StringIO()):
        baseline_scenario, baseline = _execute(baseline_design, "水马案例基准")
        candidate_scenario, candidate = _execute(candidate_design, "水马案例候选")
        payload = write_mesa_visual_tracks_js(
            frames=candidate.frames,
            scenario=candidate_scenario,
            output_path=output_path,
            facilities=candidate.runtime.facilities,
            service_events=candidate.runtime.facility_service_events,
            terminal_events=candidate.runtime.passenger_terminal_events,
            clearance_debug=build_clearance_debug(candidate.runtime),
        )

    baseline_seconds = _clearance_seconds(baseline.runtime)
    candidate_seconds = _clearance_seconds(candidate.runtime)
    _add_case_metadata(
        payload,
        candidate_design.constraints.canvas_width_m,
        candidate_design.constraints.canvas_height_m,
        baseline_seconds,
        candidate_seconds,
    )
    output_path.write_text(
        "window.JPS_TRACKS = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return {
        "output": str(output_path.resolve()),
        "seed": SEED,
        "initial_persons": INITIAL_PERSONS,
        "baseline_clearance_time_s": baseline_seconds,
        "candidate_clearance_time_s": candidate_seconds,
        "difference_s": candidate_seconds - baseline_seconds,
        "candidate_cleared": payload["clearance_audit"]["cleared"],  # type: ignore[index]
    }


def _water_barrier() -> DesignElement:
    return DesignElement(
        id=BARRIER_ID,
        kind="obstacle",
        level_id="b2_platform",
        geometry=ElementGeometry(shape="rect", **BARRIER_GEOMETRY),
        label="水马 A",
        role="obstacle",
        metadata={"blocking": True, "visual_kind": "water_barrier"},
    )


def _execute(design, station_name: str):
    args = build_parser().parse_args(
        [
            "--station",
            "小寨",
            "--minutes",
            "15",
            "--tick-seconds",
            "5",
            "--entry-count-hour",
            "0",
            "--exit-count-hour",
            "0",
            "--seed",
            str(SEED),
            "--design-template",
            "visual_demo_station",
            "--movement-backend",
            "batched_jupedsim",
            "--scenario-mode",
            "evacuation",
            "--initial-platform-persons",
            str(INITIAL_PERSONS),
            "--no-audit",
        ]
    )
    scenario = replace(
        make_scenario(args, station_design=design),
        station_name=station_name,
        source_label="paired_water_barrier_tutorial",
    )
    result = run_simulation(
        SimulationRequest(scenario=scenario, seed=SEED),
        MesaSimulationExecutor(),
    )
    return scenario, result


def _clearance_seconds(runtime) -> float:
    value = build_clearance_debug(runtime).get("clearance_time_s")
    if value is None:
        raise RuntimeError("water-barrier tutorial case did not clear")
    return float(value)


def _add_case_metadata(
    payload: dict[str, object],
    canvas_width_m: float,
    canvas_height_m: float,
    baseline_seconds: float,
    candidate_seconds: float,
) -> None:
    x_m = BARRIER_GEOMETRY["x_m"]
    y_m = BARRIER_GEOMETRY["y_m"]
    width_m = BARRIER_GEOMETRY["width_m"]
    height_m = BARRIER_GEOMETRY["height_m"]
    barrier = {
        "id": BARRIER_ID,
        "label": "水马 A",
        "kind": "water_barrier",
        "blocking": True,
        "points": [
            [x_m / canvas_width_m, y_m / canvas_height_m],
            [(x_m + width_m) / canvas_width_m, y_m / canvas_height_m],
            [
                (x_m + width_m) / canvas_width_m,
                (y_m + height_m) / canvas_height_m,
            ],
            [x_m / canvas_width_m, (y_m + height_m) / canvas_height_m],
        ],
    }
    layout = payload["layout"]
    assert isinstance(layout, dict)
    obstacles = layout["obstacles"]
    assert isinstance(obstacles, list)
    obstacles.append(barrier)

    scenario = payload["scenario"]
    assert isinstance(scenario, dict)
    scenario["water_barrier_case"] = {
        "kind": "water_barrier",
        "level_id": "b2_platform",
        "geometry_m": dict(BARRIER_GEOMETRY),
        "paired_seed": SEED,
    }
    scenario["paired_baseline_clearance_time_s"] = baseline_seconds
    scenario["paired_candidate_clearance_time_s"] = candidate_seconds


if __name__ == "__main__":
    print(json.dumps(generate_water_barrier_case(), ensure_ascii=False, indent=2))
