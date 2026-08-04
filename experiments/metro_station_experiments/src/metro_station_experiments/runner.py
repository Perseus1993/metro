from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

from metro_station.application.simulation import SimulationRequest, run_simulation
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.executor import MesaSimulationExecutor
from metro_station.adapters.simulation.runtime.clearance_detection import build_clearance_debug
from metro_station.adapters.simulation.runtime.snapshots import FrameSnapshot
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.adapters.simulation.simulation_outputs.visual_tracks import mesa_frames_to_visual_tracks
from .paths import (
    EXPERIMENT_REPLAY_DIR,
    EXPERIMENT_REPLAY_URL_PREFIX,
    RENDERER_ROOT,
)
from .acceptance import assess_experiment_results, experiment_exit_code
from .diagnosis import TrajectoryReport, diagnose_tracks
from .report import write_experiment_report


DEFAULT_OUTPUT_DIR = Path.cwd() / "output" / "metro_experiment"


@dataclass(frozen=True)
class ExperimentCase:
    case_id: str
    design: StationDesignDocument
    design_label: str
    entry_count_hour: int
    exit_count_hour: int
    transfer_count_hour: int = 0
    seed: int = 42
    minutes: int = 3
    tick_seconds: int = 5
    group_size: int = 1
    movement_backend: str = "batched_jupedsim"
    jupedsim_model: str = "collision_free_speed"
    station_name: str = "experiment"
    hour: int = 18
    operations: dict[str, int | float] = field(default_factory=dict)


@dataclass
class CaseResult:
    case: ExperimentCase
    status: str
    frames: list[dict[str, Any]]
    metrics: dict[str, Any]
    tracks_payload: dict[str, Any] | None
    trajectory_report: TrajectoryReport | None
    error: str | None = None


class ExperimentRunner:
    def __init__(self, cases: Iterable[ExperimentCase]) -> None:
        self.cases = list(cases)

    def run_all(self) -> list[CaseResult]:
        return [self.run_case(case) for case in self.cases]

    def run_case(
        self,
        case: ExperimentCase,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> CaseResult:
        try:
            scenario = scenario_from_case(case)
            execution = run_simulation(
                SimulationRequest(scenario=scenario, seed=case.seed),
                MesaSimulationExecutor(),
                progress_callback=progress_callback,
            )
            model = execution.runtime
            frames = execution.frames
            frame_dicts = [_frame_dict(frame) for frame in frames]
            tracks_payload = mesa_frames_to_visual_tracks(
                frames=frames,
                scenario=scenario,
                facilities=model.facilities,
                service_events=model.facility_service_events,
                terminal_events=model.passenger_terminal_events,
                clearance_debug=build_clearance_debug(model),
                movement_trace=model.movement_backend.movement_trace(),
            )
            return CaseResult(
                case=case,
                status="ok",
                frames=frame_dicts,
                metrics=_final_metrics(frames),
                tracks_payload=tracks_payload,
                trajectory_report=diagnose_tracks(tracks_payload),
            )
        except Exception as exc:
            return CaseResult(
                case=case,
                status="error",
                frames=[],
                metrics={},
                tracks_payload=None,
                trajectory_report=None,
                error=f"{type(exc).__name__}: {exc}",
            )


def scenario_from_case(case: ExperimentCase) -> StationSandboxScenario:
    kwargs: dict[str, Any] = _scenario_operation_overrides(case.operations)
    kwargs.update(
        {
            "station_name": case.station_name,
            "hour": case.hour,
            "minutes": case.minutes,
            "tick_seconds": case.tick_seconds,
            "group_size": case.group_size,
            "entry_count_hour": max(0, int(case.entry_count_hour)),
            "exit_count_hour": max(0, int(case.exit_count_hour)),
            "transfer_count_hour": max(0, int(case.transfer_count_hour)),
            "source_label": "experiment_runner",
            "sample_hours": 1,
            "station_design": case.design,
            "movement_backend_name": case.movement_backend,
            "jupedsim_operational_model": case.jupedsim_model,
            "simulation_clock_mode": "physical",
            "goal_graph_mode": "active",
            "audit_enabled": False,
            "audit_print_events": False,
        }
    )
    return StationSandboxScenario(**kwargs)


def _scenario_operation_overrides(operations: dict[str, int | float]) -> dict[str, int | float]:
    scenario_fields = {
        "train_headway_seconds",
        "train_dwell_seconds",
        "train_capacity_persons",
        "boarding_persons_per_min",
        "gate_service_persons_per_min",
        "walk_units_per_tick",
        "escalator_speed_units_per_tick",
        "stairs_speed_units_per_tick",
        "elevator_speed_units_per_tick",
        "elevator_cabin_capacity_persons",
        "elevator_min_dispatch_persons",
        "elevator_max_dispatch_wait_seconds",
        "elevator_boarding_seconds",
        "elevator_cycle_seconds",
    }
    return {
        key: value
        for key, value in operations.items()
        if key in scenario_fields and isinstance(value, int | float)
    }


def load_design_file(path: Path) -> StationDesignDocument:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    document_payload = payload.get("document", payload)
    if not isinstance(document_payload, dict):
        raise ValueError(f"{path} does not contain a design document")
    return StationDesignDocument.from_dict(document_payload)


def build_cases(
    *,
    designs: Sequence[tuple[str, StationDesignDocument]],
    entries: Sequence[int],
    exits: Sequence[int],
    transfers: Sequence[int] = (0,),
    seeds: Sequence[int],
    minutes: int,
    tick_seconds: int,
    group_size: int,
    movement_backend: str,
    jupedsim_model: str,
    station_name: str,
    hour: int,
) -> list[ExperimentCase]:
    cases: list[ExperimentCase] = []
    for design_label, design in designs:
        for entry_count, exit_count, transfer_count, seed in product(
            entries,
            exits,
            transfers,
            seeds,
        ):
            case_id = _case_id(design_label, entry_count, exit_count, transfer_count, seed)
            cases.append(
                ExperimentCase(
                    case_id=case_id,
                    design=design,
                    design_label=design_label,
                    entry_count_hour=entry_count,
                    exit_count_hour=exit_count,
                    transfer_count_hour=transfer_count,
                    seed=seed,
                    minutes=minutes,
                    tick_seconds=tick_seconds,
                    group_size=group_size,
                    movement_backend=movement_backend,
                    jupedsim_model=jupedsim_model,
                    station_name=station_name,
                    hour=hour,
                )
            )
    return cases


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run design alternatives through simulation and trajectory diagnosis."
    )
    parser.add_argument(
        "--design-template",
        nargs="*",
        default=None,
        help="Station design template ids. Multiple templates become alternatives.",
    )
    parser.add_argument(
        "--design-file",
        nargs="*",
        type=Path,
        default=(),
        help="StationDesignDocument JSON files or /api/compile payloads.",
    )
    parser.add_argument("--entry", type=parse_int_list, default=(4000,))
    parser.add_argument("--exit", type=parse_int_list, default=(2000,))
    parser.add_argument("--transfer", type=parse_int_list, default=(0,))
    parser.add_argument("--seed", type=parse_int_list, default=(42,))
    parser.add_argument("--minutes", type=positive_int, default=3)
    parser.add_argument("--tick-seconds", type=positive_int, default=5)
    parser.add_argument("--group-size", type=positive_int, default=1)
    parser.add_argument("--station-name", default="experiment")
    parser.add_argument("--hour", type=int, default=18)
    parser.add_argument(
        "--movement-backend",
        choices=("jupedsim", "batched_jupedsim", "micro_jupedsim"),
        default="batched_jupedsim",
    )
    parser.add_argument(
        "--jupedsim-model",
        choices=("collision_free_speed", "social_force"),
        default="collision_free_speed",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="Treat trajectory warnings as a failed acceptance run.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        designs = _designs_from_args(args)
        cases = build_cases(
            designs=designs,
            entries=args.entry,
            exits=args.exit,
            transfers=args.transfer,
            seeds=args.seed,
            minutes=args.minutes,
            tick_seconds=args.tick_seconds,
            group_size=args.group_size,
            movement_backend=args.movement_backend,
            jupedsim_model=args.jupedsim_model,
            station_name=args.station_name,
            hour=args.hour,
        )
        results = ExperimentRunner(cases).run_all()
        write_experiment_report(
            results,
            args.output,
            replay_asset_dir=EXPERIMENT_REPLAY_DIR,
            replay_url_prefix=EXPERIMENT_REPLAY_URL_PREFIX,
        )
    except Exception as exc:
        print(f"[EXPERIMENT] error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        _print_summary(results, args.output)
        decision = assess_experiment_results(results, fail_on_warning=args.fail_on_warn)
        print(
            "[EXPERIMENT] acceptance="
            f"{decision.status} blocking_issues={len(decision.issues)}"
        )
    return experiment_exit_code(results, fail_on_warning=args.fail_on_warn)


def parse_int_list(value: str | Sequence[int]) -> tuple[int, ...]:
    if isinstance(value, str):
        values = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    else:
        values = tuple(int(item) for item in value)
    if not values:
        raise argparse.ArgumentTypeError("provide at least one integer")
    if any(item < 0 for item in values):
        raise argparse.ArgumentTypeError("values must be >= 0")
    return values


def positive_int(value: str | int) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def _designs_from_args(args: argparse.Namespace) -> list[tuple[str, StationDesignDocument]]:
    designs: list[tuple[str, StationDesignDocument]] = []
    template_ids = args.design_template
    if template_ids is None:
        template_ids = () if args.design_file else ("visual_demo_station",)
    for template_id in template_ids:
        designs.append((str(template_id), create_design(str(template_id))))
    for path in args.design_file:
        designs.append((path.stem, load_design_file(path)))
    if not designs:
        raise ValueError("provide at least one --design-template or --design-file")
    return designs


def _case_id(
    design_label: str,
    entry_count: int,
    exit_count: int,
    transfer_count: int,
    seed: int,
) -> str:
    label = re.sub(r"[^a-zA-Z0-9]+", "_", design_label).strip("_").lower()
    label = label or "design"
    if transfer_count > 0:
        return (
            f"{label}_entry_{entry_count}_exit_{exit_count}_"
            f"transfer_{transfer_count}_seed_{seed}"
        )
    return f"{label}_entry_{entry_count}_exit_{exit_count}_seed_{seed}"


def _frame_dict(frame: Any) -> dict[str, Any]:
    snapshot = FrameSnapshot.from_any(frame)
    return snapshot.to_dict()


def _final_metrics(frames: Sequence[Any]) -> dict[str, Any]:
    if not frames:
        return {}
    snapshot = FrameSnapshot.from_any(frames[-1])
    return snapshot.metrics.to_dict()


def _print_summary(results: Sequence[CaseResult], output_dir: Path) -> None:
    ok = sum(1 for result in results if result.status == "ok")
    errors = len(results) - ok
    failures = sum(
        1
        for result in results
        if result.trajectory_report is not None
        and result.trajectory_report.pass_fail == "fail"
    )
    print(
        "[EXPERIMENT] "
        f"cases={len(results)} ok={ok} errors={errors} trajectory_fail={failures}"
    )
    print(f"[EXPERIMENT] report={output_dir / 'experiment_report.md'}")
    print(f"[EXPERIMENT] json={output_dir / 'experiment_results.json'}")
    for result in results:
        if result.tracks_payload is None:
            continue
        replay_file = f"{EXPERIMENT_REPLAY_URL_PREFIX}/{result.case.case_id}_tracks.js"
        print(
            "[EXPERIMENT] animation="
            f"{RENDERER_ROOT / 'animation_demo.html'}?file={replay_file}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
