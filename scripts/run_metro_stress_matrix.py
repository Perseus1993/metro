from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sandbox.metro_station_sandbox.design import create_design  # noqa: E402
from sandbox.metro_station_sandbox.mesa_model import MetroStationModel  # noqa: E402
from sandbox.metro_station_sandbox.scenario import StationSandboxScenario  # noqa: E402


DEFAULT_ENTRIES = (60, 120)
DEFAULT_EXITS = (60, 120)
DEFAULT_OUTPUT_DIR = ROOT / "output" / "metro_stress_matrix"
DEFAULT_OUTPUT_STEM = "metro_stress_matrix"

FIELDNAMES = (
    "run_id",
    "status",
    "entry_count_hour",
    "exit_count_hour",
    "seed",
    "minutes",
    "tick_seconds",
    "group_size",
    "design_template",
    "movement_backend",
    "jupedsim_operational_model",
    "station_name",
    "hour",
    "steps_run",
    "simulated_seconds",
    "elapsed_seconds",
    "spawned_persons",
    "spawned_entry_persons",
    "spawned_exit_persons",
    "completed_persons",
    "completion_rate",
    "boarded_persons",
    "exit_gate_served_persons",
    "station_persons_final",
    "station_persons_max",
    "gate_queue_persons_final",
    "gate_queue_persons_max",
    "vertical_queue_persons_final",
    "vertical_queue_persons_max",
    "door_queue_persons_final",
    "door_queue_persons_max",
    "platform_waiting_persons_final",
    "platform_waiting_persons_max",
    "average_system_minutes",
    "crowding_index_max",
    "average_walk_speed_factor_min",
    "jupedsim_steps",
    "jupedsim_batches",
    "audit_counts",
    "error_type",
    "error",
)


@dataclass(frozen=True)
class StressCase:
    entry_count_hour: int
    exit_count_hour: int
    seed: int

    @property
    def run_id(self) -> str:
        return f"entry_{self.entry_count_hour}_exit_{self.exit_count_hour}_seed_{self.seed}"


@dataclass(frozen=True)
class OutputPaths:
    csv_path: Path
    json_path: Path
    markdown_path: Path


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def parse_int_list(value: str) -> tuple[int, ...]:
    values: list[int] = []
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        parsed = int(part)
        if parsed < 0:
            raise argparse.ArgumentTypeError("matrix values must be >= 0")
        values.append(parsed)
    if not values:
        raise argparse.ArgumentTypeError("provide at least one integer")
    return tuple(values)


def parse_pairs(value: str) -> tuple[tuple[int, int], ...]:
    pairs: list[tuple[int, int]] = []
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        pieces = part.split(":", maxsplit=1)
        if len(pieces) != 2:
            raise argparse.ArgumentTypeError("pairs must look like ENTRY:EXIT")
        entry_count, exit_count = (int(piece.strip()) for piece in pieces)
        if entry_count < 0 or exit_count < 0:
            raise argparse.ArgumentTypeError("pair values must be >= 0")
        pairs.append((entry_count, exit_count))
    if not pairs:
        raise argparse.ArgumentTypeError("provide at least one ENTRY:EXIT pair")
    return tuple(pairs)


def build_cases(
    *,
    entries: Sequence[int],
    exits: Sequence[int],
    seeds: Sequence[int],
    pairs: Sequence[tuple[int, int]] | None,
) -> list[StressCase]:
    flow_pairs = list(pairs) if pairs else list(product(entries, exits))
    return [
        StressCase(entry_count_hour=entry, exit_count_hour=exit_count, seed=seed)
        for entry, exit_count in flow_pairs
        for seed in seeds
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a small MetroStationModel entry/exit stress matrix."
    )
    parser.add_argument(
        "--entries",
        type=parse_int_list,
        default=DEFAULT_ENTRIES,
        help="Comma-separated hourly entry demands. Default: 60,120.",
    )
    parser.add_argument(
        "--exits",
        type=parse_int_list,
        default=DEFAULT_EXITS,
        help="Comma-separated hourly exit demands. Default: 60,120.",
    )
    parser.add_argument(
        "--pairs",
        type=parse_pairs,
        default=None,
        help="Explicit ENTRY:EXIT pairs. When set, --entries/--exits are ignored.",
    )
    parser.add_argument("--minutes", type=positive_int, default=1)
    parser.add_argument("--tick-seconds", type=positive_int, default=5)
    parser.add_argument("--group-size", type=positive_int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--seeds",
        type=parse_int_list,
        default=None,
        help="Comma-separated seeds. Overrides --seed.",
    )
    parser.add_argument("--station-name", default="stress_matrix")
    parser.add_argument("--hour", type=int, default=18)
    parser.add_argument(
        "--design-template",
        choices=(
            "single_level_terminal",
            "two_level_island_platform",
            "three_level_transfer",
            "visual_demo_station",
        ),
        default="two_level_island_platform",
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
        "--audit",
        action="store_true",
        help="Enable sandbox audit collection. Default keeps stress runs quiet.",
    )
    parser.add_argument("--admins", type=nonnegative_int, default=0)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-stem", default=DEFAULT_OUTPUT_STEM)
    parser.add_argument("--csv-out", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--md-out", type=Path, default=None)
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failed matrix cell.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print output paths and final status.",
    )
    return parser


def resolve_output_paths(args: argparse.Namespace) -> OutputPaths:
    out_dir = args.out_dir
    stem = args.output_stem
    return OutputPaths(
        csv_path=args.csv_out or out_dir / f"{stem}.csv",
        json_path=args.json_out or out_dir / f"{stem}.json",
        markdown_path=args.md_out or out_dir / f"{stem}.md",
    )


def make_scenario(args: argparse.Namespace, case: StressCase) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name=args.station_name,
        hour=args.hour,
        minutes=args.minutes,
        tick_seconds=args.tick_seconds,
        group_size=args.group_size,
        entry_count_hour=case.entry_count_hour,
        exit_count_hour=case.exit_count_hour,
        source_label="stress_matrix_cli",
        sample_hours=1,
        station_design=create_design(args.design_template),
        movement_backend_name=args.movement_backend,
        jupedsim_operational_model=args.jupedsim_model,
        audit_enabled=args.audit,
        audit_print_events=False,
        admin_agent_count=args.admins,
    )


def metric_number(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = metrics.get(key, default)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def metric_int(metrics: dict[str, Any], key: str, default: int = 0) -> int:
    return int(round(metric_number(metrics, key, float(default))))


def frame_metrics(frames: Sequence[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for frame in frames:
        metrics = frame.get("metrics", {})
        if isinstance(metrics, dict):
            values.append(metric_number(metrics, key))
    return values


def max_frame_metric(frames: Sequence[dict[str, Any]], key: str) -> int:
    values = frame_metrics(frames, key)
    return int(round(max(values))) if values else 0


def min_frame_metric(frames: Sequence[dict[str, Any]], key: str, default: float = 0.0) -> float:
    values = frame_metrics(frames, key)
    return round(min(values), 4) if values else default


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def summarize_run(
    *,
    args: argparse.Namespace,
    case: StressCase,
    frames: Sequence[dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    final_metrics: dict[str, Any] = {}
    if frames and isinstance(frames[-1].get("metrics"), dict):
        final_metrics = frames[-1]["metrics"]

    spawned = metric_int(final_metrics, "spawned_persons")
    boarded = metric_int(final_metrics, "boarded_persons")
    exited = metric_int(final_metrics, "exit_gate_served_persons")
    completed = boarded + exited
    completion_rate = round(completed / spawned, 4) if spawned else None

    return {
        "run_id": case.run_id,
        "status": "ok",
        "entry_count_hour": case.entry_count_hour,
        "exit_count_hour": case.exit_count_hour,
        "seed": case.seed,
        "minutes": args.minutes,
        "tick_seconds": args.tick_seconds,
        "group_size": args.group_size,
        "design_template": args.design_template,
        "movement_backend": final_metrics.get("movement_backend", args.movement_backend),
        "jupedsim_operational_model": final_metrics.get(
            "jupedsim_operational_model",
            args.jupedsim_model,
        ),
        "station_name": args.station_name,
        "hour": args.hour,
        "steps_run": len(frames),
        "simulated_seconds": args.minutes * 60,
        "elapsed_seconds": round(elapsed_seconds, 4),
        "spawned_persons": spawned,
        "spawned_entry_persons": metric_int(final_metrics, "spawned_entry_persons"),
        "spawned_exit_persons": metric_int(final_metrics, "spawned_exit_persons"),
        "completed_persons": completed,
        "completion_rate": completion_rate,
        "boarded_persons": boarded,
        "exit_gate_served_persons": exited,
        "station_persons_final": metric_int(final_metrics, "station_persons"),
        "station_persons_max": max_frame_metric(frames, "station_persons"),
        "gate_queue_persons_final": metric_int(final_metrics, "gate_queue_persons"),
        "gate_queue_persons_max": max_frame_metric(frames, "gate_queue_persons"),
        "vertical_queue_persons_final": metric_int(final_metrics, "vertical_queue_persons"),
        "vertical_queue_persons_max": max_frame_metric(frames, "vertical_queue_persons"),
        "door_queue_persons_final": metric_int(final_metrics, "door_queue_persons"),
        "door_queue_persons_max": max_frame_metric(frames, "door_queue_persons"),
        "platform_waiting_persons_final": metric_int(
            final_metrics,
            "platform_waiting_persons",
        ),
        "platform_waiting_persons_max": max_frame_metric(frames, "platform_waiting_persons"),
        "average_system_minutes": metric_number(final_metrics, "average_system_minutes"),
        "crowding_index_max": max(frame_metrics(frames, "crowding_index"), default=0.0),
        "average_walk_speed_factor_min": min_frame_metric(
            frames,
            "average_walk_speed_factor",
            default=1.0,
        ),
        "jupedsim_steps": metric_int(final_metrics, "jupedsim_steps"),
        "jupedsim_batches": metric_int(final_metrics, "jupedsim_batches"),
        "audit_counts": final_metrics.get("audit_counts", {}),
        "error_type": None,
        "error": None,
    }


def error_row(args: argparse.Namespace, case: StressCase, exc: Exception) -> dict[str, Any]:
    row = {field: None for field in FIELDNAMES}
    row.update(
        {
            "run_id": case.run_id,
            "status": "error",
            "entry_count_hour": case.entry_count_hour,
            "exit_count_hour": case.exit_count_hour,
            "seed": case.seed,
            "minutes": args.minutes,
            "tick_seconds": args.tick_seconds,
            "group_size": args.group_size,
            "design_template": args.design_template,
            "movement_backend": args.movement_backend,
            "jupedsim_operational_model": args.jupedsim_model,
            "station_name": args.station_name,
            "hour": args.hour,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    )
    return row


def run_case(args: argparse.Namespace, case: StressCase) -> dict[str, Any]:
    scenario = make_scenario(args, case)
    started = time.perf_counter()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"The use of the `seed` keyword argument is deprecated.*",
            category=FutureWarning,
        )
        model = MetroStationModel(scenario, seed=case.seed)
    frames = model.run()
    return summarize_run(
        args=args,
        case=case,
        frames=frames,
        elapsed_seconds=time.perf_counter() - started,
    )


def run_matrix(args: argparse.Namespace, cases: Sequence[StressCase]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if not args.quiet:
            print(f"[STRESS] {index}/{len(cases)} {case.run_id}")
        try:
            rows.append(run_case(args, case))
        except Exception as exc:  # noqa: BLE001
            rows.append(error_row(args, case, exc))
            if args.fail_fast:
                break
    return rows


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return compact_json(value)
    return value


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field)) for field in FIELDNAMES})


def metadata_for(args: argparse.Namespace, cases: Sequence[StressCase]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "script": "scripts.run_metro_stress_matrix",
        "case_count": len(cases),
        "minutes": args.minutes,
        "tick_seconds": args.tick_seconds,
        "group_size": args.group_size,
        "design_template": args.design_template,
        "movement_backend": args.movement_backend,
        "station_name": args.station_name,
        "hour": args.hour,
    }


def write_json_summary(
    path: Path,
    *,
    args: argparse.Namespace,
    cases: Sequence[StressCase],
    rows: Sequence[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": metadata_for(args, cases),
        "summary": aggregate_summary(rows),
        "runs": list(rows),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def aggregate_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    error_rows = [row for row in rows if row.get("status") != "ok"]
    worst_backlog = max(
        (int(row.get("station_persons_final") or 0) for row in ok_rows),
        default=0,
    )
    worst_station_load = max(
        (int(row.get("station_persons_max") or 0) for row in ok_rows),
        default=0,
    )
    return {
        "runs": len(rows),
        "ok": len(ok_rows),
        "errors": len(error_rows),
        "worst_final_station_persons": worst_backlog,
        "worst_station_persons_max": worst_station_load,
    }


def markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def markdown_table(rows: Sequence[dict[str, Any]]) -> str:
    columns = (
        ("status", "status"),
        ("entry/h", "entry_count_hour"),
        ("exit/h", "exit_count_hour"),
        ("seed", "seed"),
        ("spawned", "spawned_persons"),
        ("done", "completed_persons"),
        ("rate", "completion_rate"),
        ("backlog", "station_persons_final"),
        ("max_station", "station_persons_max"),
        ("max_gate_q", "gate_queue_persons_max"),
        ("max_vert_q", "vertical_queue_persons_max"),
        ("max_door_q", "door_queue_persons_max"),
        ("avg_min", "average_system_minutes"),
    )
    header = "| " + " | ".join(label for label, _key in columns) + " |"
    divider = "| " + " | ".join("---" for _label, _key in columns) + " |"
    body = [
        "| " + " | ".join(markdown_cell(row.get(key)) for _label, key in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def write_markdown_summary(
    path: Path,
    *,
    args: argparse.Namespace,
    cases: Sequence[StressCase],
    rows: Sequence[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = metadata_for(args, cases)
    summary = aggregate_summary(rows)
    content = "\n".join(
        [
            "# Metro Stress Matrix Summary",
            "",
            f"- generated_at: {meta['generated_at']}",
            f"- cases: {summary['runs']}",
            f"- ok: {summary['ok']}",
            f"- errors: {summary['errors']}",
            f"- minutes: {args.minutes}",
            f"- design_template: {args.design_template}",
            f"- movement_backend: {args.movement_backend}",
            f"- jupedsim_operational_model: {args.jupedsim_model}",
            "",
            markdown_table(rows),
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def write_outputs(
    paths: OutputPaths,
    *,
    args: argparse.Namespace,
    cases: Sequence[StressCase],
    rows: Sequence[dict[str, Any]],
) -> None:
    write_csv(paths.csv_path, rows)
    write_json_summary(paths.json_path, args=args, cases=cases, rows=rows)
    write_markdown_summary(paths.markdown_path, args=args, cases=cases, rows=rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    seeds = args.seeds or (args.seed,)
    cases = build_cases(entries=args.entries, exits=args.exits, seeds=seeds, pairs=args.pairs)
    paths = resolve_output_paths(args)

    rows = run_matrix(args, cases)
    write_outputs(paths, args=args, cases=cases, rows=rows)

    summary = aggregate_summary(rows)
    print(f"[STRESS] wrote_csv={paths.csv_path.resolve()}")
    print(f"[STRESS] wrote_json={paths.json_path.resolve()}")
    print(f"[STRESS] wrote_markdown={paths.markdown_path.resolve()}")
    print(
        "[STRESS] "
        f"runs={summary['runs']} ok={summary['ok']} errors={summary['errors']} "
        f"worst_backlog={summary['worst_final_station_persons']}"
    )
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
