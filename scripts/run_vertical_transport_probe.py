from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import warnings
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sandbox.metro_station_sandbox.agents import PassengerAgent  # noqa: E402
from sandbox.metro_station_sandbox.design import create_design  # noqa: E402
from sandbox.metro_station_sandbox.facilities.process import FacilityKind  # noqa: E402
from sandbox.metro_station_sandbox.facilities.runtime import (  # noqa: E402
    ElevatorProcessAgent,
    FacilityProcessAgent,
)
from sandbox.metro_station_sandbox.movement.backend import MovementBackend, MovementResult  # noqa: E402
from sandbox.metro_station_sandbox.planning.plan import AgentIntent  # noqa: E402
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel  # noqa: E402
from sandbox.metro_station_sandbox.station.scenario import StationSandboxScenario  # noqa: E402


DEFAULT_OUTPUT_DIR = ROOT / "output" / "vertical_transport_probe"
DEFAULT_OUTPUT_STEM = "vertical_transport_probe"
DEFAULT_DEMANDS = (60, 240, 1000, 2000)
DEFAULT_KINDS = (FacilityKind.ELEVATOR.value, FacilityKind.ESCALATOR.value)

FIELDNAMES = (
    "run_id",
    "status",
    "clearance",
    "facility_id",
    "facility_label",
    "facility_kind",
    "direction",
    "entry_level_id",
    "exit_level_id",
    "demand_hour",
    "seed",
    "minutes",
    "tick_seconds",
    "drain_seconds",
    "design_template",
    "arrived_persons",
    "served_persons",
    "unserved_persons",
    "completion_rate",
    "queue_persons_max",
    "queue_persons_final",
    "mean_wait_seconds",
    "p95_wait_seconds",
    "service_persons_per_min",
    "departed_cabins",
    "cabin_capacity_persons",
    "cabin_cycle_seconds",
    "cabin_load_final",
    "last_departure_load_persons",
    "elapsed_seconds",
    "error_type",
    "error",
)


class InstantMovementBackend(MovementBackend):
    """Movement stub for process-only facility probes."""

    def move(self, passenger: PassengerAgent) -> MovementResult:
        return MovementResult(passenger.unique_id, passenger.target, reached=True)


@dataclass(frozen=True)
class ProbeCase:
    facility_id: str
    demand_hour: int
    seed: int

    @property
    def run_id(self) -> str:
        safe_facility = self.facility_id.replace(":", "_")
        return f"{safe_facility}_demand_{self.demand_hour}_seed_{self.seed}"


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
    parsed: list[int] = []
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        item = int(part)
        if item < 0:
            raise argparse.ArgumentTypeError("values must be >= 0")
        parsed.append(item)
    if not parsed:
        raise argparse.ArgumentTypeError("provide at least one integer")
    return tuple(parsed)


def parse_str_list(value: str) -> tuple[str, ...]:
    parsed = tuple(part.strip() for part in value.split(",") if part.strip())
    if not parsed:
        raise argparse.ArgumentTypeError("provide at least one value")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run process-only probes for elevator/escalator vertical transport facilities. "
            "Passengers are injected directly into each selected facility queue so gate, "
            "platform, train, and renderer behavior do not hide facility defects."
        )
    )
    parser.add_argument("--demands", type=parse_int_list, default=DEFAULT_DEMANDS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--seeds",
        type=parse_int_list,
        default=None,
        help="Comma-separated seeds. Overrides --seed.",
    )
    parser.add_argument("--minutes", type=positive_int, default=10)
    parser.add_argument("--tick-seconds", type=positive_int, default=1)
    parser.add_argument(
        "--drain-seconds",
        type=nonnegative_int,
        default=120,
        help="Extra no-arrival seconds after the demand window for queue clearance checks.",
    )
    parser.add_argument("--group-size", type=positive_int, default=1)
    parser.add_argument(
        "--design-template",
        choices=(
            "single_level_terminal",
            "two_level_island_platform",
            "three_level_transfer",
            "visual_demo_station",
        ),
        default="visual_demo_station",
    )
    parser.add_argument(
        "--kinds",
        type=parse_str_list,
        default=DEFAULT_KINDS,
        help="Comma-separated facility kinds. Common values: elevator,escalator,stairs,all.",
    )
    parser.add_argument(
        "--directions",
        type=parse_str_list,
        default=("down", "up", "both"),
        help="Comma-separated directions to include. Default: down,up,both.",
    )
    parser.add_argument(
        "--facility-id",
        default=None,
        help="Optional exact compiled facility id to probe.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-stem", default=DEFAULT_OUTPUT_STEM)
    parser.add_argument("--csv-out", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--md-out", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser


def make_scenario(args: argparse.Namespace) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="vertical_transport_probe",
        hour=18,
        minutes=args.minutes,
        tick_seconds=args.tick_seconds,
        group_size=args.group_size,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="vertical_transport_probe",
        sample_hours=1,
        station_design=create_design(args.design_template),
        goal_graph_mode="active",
        audit_enabled=False,
        audit_print_events=False,
    )


def make_model(args: argparse.Namespace, seed: int) -> MetroStationModel:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"The use of the `seed` keyword argument is deprecated.*",
            category=FutureWarning,
        )
        return MetroStationModel(
            make_scenario(args),
            seed=seed,
            movement_backend=InstantMovementBackend(),
        )


def selected_facilities(
    facilities: Sequence[FacilityProcessAgent],
    *,
    kinds: Sequence[str],
    directions: Sequence[str],
    facility_id: str | None,
) -> list[FacilityProcessAgent]:
    if facility_id is not None:
        return [facility for facility in facilities if facility.facility_id == facility_id]

    kind_filter = {kind.lower() for kind in kinds}
    direction_filter = {direction.lower() for direction in directions}
    include_all_kinds = "all" in kind_filter
    include_all_directions = "all" in direction_filter
    return [
        facility
        for facility in facilities
        if (include_all_kinds or facility.spec.kind.lower() in kind_filter)
        and (include_all_directions or facility.spec.direction.lower() in direction_filter)
    ]


def build_cases(
    facilities: Sequence[FacilityProcessAgent],
    *,
    demands: Sequence[int],
    seeds: Sequence[int],
) -> list[ProbeCase]:
    return [
        ProbeCase(facility_id=facility.facility_id, demand_hour=demand, seed=seed)
        for facility in facilities
        for demand in demands
        for seed in seeds
    ]


def arrival_schedule(
    *,
    demand_hour: int,
    minutes: int,
    tick_seconds: int,
    group_size: int,
) -> Counter[int]:
    horizon_steps = max(1, int(minutes * 60 / tick_seconds))
    total_persons = round(max(0, demand_hour) * minutes / 60.0)
    total_groups = round(total_persons / max(1, group_size))
    schedule: Counter[int] = Counter()
    if total_groups <= 0:
        return schedule

    for index in range(total_groups):
        step = min(horizon_steps - 1, int(index * horizon_steps / total_groups))
        schedule[step] += 1
    return schedule


def passenger_intent_for_facility(facility: FacilityProcessAgent) -> str:
    if facility.spec.direction == "up":
        return AgentIntent.EXIT_STATION.value
    return AgentIntent.ENTER_AND_BOARD.value


def add_arrival(
    model: MetroStationModel,
    facility: FacilityProcessAgent,
    *,
    created_step: int,
) -> PassengerAgent:
    passenger = PassengerAgent(
        model,
        group_size=model.scenario.group_size,
        created_step=created_step,
        intent=passenger_intent_for_facility(facility),
        initial_position=facility.spec.position,
        initial_level_id=facility.spec.entry_level_id,
    )
    # The probe must enter through the same compiled ownership contract as a
    # simulated passenger. Placing every synthetic arrival at ``queue_anchor``
    # manufactured an invalid co-located state before Queue.join could enforce
    # capacity or body clearance.
    model._clear_all_facility_targeting_reservations(passenger)
    model._reserve_facility_approach_slot(passenger, facility)
    passenger.pos = model._safe_facility_queue_approach_target(passenger, facility)
    model.passengers.append(passenger)
    facility.join_queue(passenger, authority="goal_graph")
    return passenger


def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[index]


def elevator_value(facility: FacilityProcessAgent, attr: str, default: Any = None) -> Any:
    if isinstance(facility, ElevatorProcessAgent):
        return getattr(facility, attr)
    return default


def summarize_probe(
    *,
    args: argparse.Namespace,
    case: ProbeCase,
    facility: FacilityProcessAgent,
    arrived_persons: int,
    wait_seconds: Sequence[float],
    queue_persons_max: int,
    elapsed_seconds: float,
) -> dict[str, Any]:
    served = int(facility.served_persons)
    unserved = max(0, arrived_persons - served)
    completion_rate = round(served / arrived_persons, 4) if arrived_persons else None
    return {
        "run_id": case.run_id,
        "status": "ok",
        "clearance": "cleared" if unserved == 0 else "backlog",
        "facility_id": facility.facility_id,
        "facility_label": facility.spec.label,
        "facility_kind": facility.spec.kind,
        "direction": facility.spec.direction,
        "entry_level_id": facility.spec.entry_level_id,
        "exit_level_id": facility.spec.exit_level_id,
        "demand_hour": case.demand_hour,
        "seed": case.seed,
        "minutes": args.minutes,
        "tick_seconds": args.tick_seconds,
        "drain_seconds": args.drain_seconds,
        "design_template": args.design_template,
        "arrived_persons": arrived_persons,
        "served_persons": served,
        "unserved_persons": unserved,
        "completion_rate": completion_rate,
        "queue_persons_max": queue_persons_max,
        "queue_persons_final": int(facility.queue_persons),
        "mean_wait_seconds": round(mean(wait_seconds), 2) if wait_seconds else 0.0,
        "p95_wait_seconds": round(percentile(wait_seconds, 0.95), 2),
        "service_persons_per_min": facility.spec.service_persons_per_min,
        "departed_cabins": elevator_value(facility, "departed_cabins"),
        "cabin_capacity_persons": elevator_value(facility, "cabin_capacity_persons"),
        "cabin_cycle_seconds": (
            args.tick_seconds * elevator_value(facility, "cycle_steps")
            if isinstance(facility, ElevatorProcessAgent)
            else None
        ),
        "cabin_load_final": elevator_value(facility, "cabin_load_persons"),
        "last_departure_load_persons": elevator_value(
            facility,
            "last_departure_load_persons",
        ),
        "elapsed_seconds": round(elapsed_seconds, 4),
        "error_type": None,
        "error": None,
    }


def run_case(args: argparse.Namespace, case: ProbeCase) -> dict[str, Any]:
    model = make_model(args, case.seed)
    facility = model.facilities_by_id[case.facility_id]
    schedule = arrival_schedule(
        demand_hour=case.demand_hour,
        minutes=args.minutes,
        tick_seconds=args.tick_seconds,
        group_size=args.group_size,
    )
    arrival_horizon_steps = model.scenario.horizon_steps
    drain_steps = max(0, round(int(args.drain_seconds) / args.tick_seconds))
    horizon_steps = arrival_horizon_steps + drain_steps
    arrival_step_by_id: dict[int, int] = {}
    served_step_by_id: dict[int, int] = {}
    queue_persons_max = 0
    arrived_persons = 0
    pending_arrival_steps: deque[int] = deque()
    started = time.perf_counter()

    for step in range(horizon_steps):
        model.step_index = step
        scheduled_groups = schedule.get(step, 0)
        pending_arrival_steps.extend(step for _ in range(scheduled_groups))
        arrived_persons += scheduled_groups * model.scenario.group_size
        while pending_arrival_steps:
            created_step = pending_arrival_steps[0]
            try:
                passenger = add_arrival(
                    model,
                    facility,
                    created_step=created_step,
                )
            except RuntimeError as exc:
                if "no reservable compiled queue slot" not in str(exc):
                    raise
                break
            arrival_step_by_id[int(passenger.unique_id)] = created_step
            pending_arrival_steps.popleft()

        facility.step()
        queue_persons_max = max(queue_persons_max, int(facility.queue_persons))
        for passenger in model.passengers:
            passenger_id = int(passenger.unique_id)
            if passenger_id in served_step_by_id:
                continue
            if passenger.state == facility.spec.service_state:
                served_step_by_id[passenger_id] = step

    wait_seconds = [
        (served_step - arrival_step_by_id[passenger_id]) * args.tick_seconds
        for passenger_id, served_step in served_step_by_id.items()
    ]
    return summarize_probe(
        args=args,
        case=case,
        facility=facility,
        arrived_persons=arrived_persons,
        wait_seconds=wait_seconds,
        queue_persons_max=queue_persons_max,
        elapsed_seconds=time.perf_counter() - started,
    )


def error_row(args: argparse.Namespace, case: ProbeCase, exc: Exception) -> dict[str, Any]:
    row = {field: None for field in FIELDNAMES}
    row.update(
        {
            "run_id": case.run_id,
            "status": "error",
            "facility_id": case.facility_id,
            "demand_hour": case.demand_hour,
            "seed": case.seed,
        "minutes": args.minutes,
        "tick_seconds": args.tick_seconds,
        "drain_seconds": args.drain_seconds,
        "design_template": args.design_template,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    )
    return row


def run_cases(args: argparse.Namespace, cases: Sequence[ProbeCase]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if not args.quiet:
            print(f"[VERTICAL] {index}/{len(cases)} {case.run_id}")
        try:
            rows.append(run_case(args, case))
        except Exception as exc:  # noqa: BLE001
            rows.append(error_row(args, case, exc))
    return rows


def resolve_output_paths(args: argparse.Namespace) -> OutputPaths:
    out_dir = args.out_dir
    stem = args.output_stem
    return OutputPaths(
        csv_path=args.csv_out or out_dir / f"{stem}.csv",
        json_path=args.json_out or out_dir / f"{stem}.json",
        markdown_path=args.md_out or out_dir / f"{stem}.md",
    )


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def aggregate_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    backlog_rows = [row for row in ok_rows if row.get("clearance") != "cleared"]
    return {
        "runs": len(rows),
        "ok": len(ok_rows),
        "errors": len(rows) - len(ok_rows),
        "backlog": len(backlog_rows),
        "worst_unserved_persons": max(
            (int(row.get("unserved_persons") or 0) for row in ok_rows),
            default=0,
        ),
        "worst_queue_persons_max": max(
            (int(row.get("queue_persons_max") or 0) for row in ok_rows),
            default=0,
        ),
    }


def metadata_for(args: argparse.Namespace, cases: Sequence[ProbeCase]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "script": "scripts.run_vertical_transport_probe",
        "case_count": len(cases),
        "minutes": args.minutes,
        "tick_seconds": args.tick_seconds,
        "drain_seconds": args.drain_seconds,
        "group_size": args.group_size,
        "design_template": args.design_template,
        "kinds": list(args.kinds),
        "directions": list(args.directions),
    }


def write_json_summary(
    path: Path,
    *,
    args: argparse.Namespace,
    cases: Sequence[ProbeCase],
    rows: Sequence[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": metadata_for(args, cases),
        "summary": aggregate_summary(rows),
        "runs": list(rows),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_table(rows: Sequence[dict[str, Any]]) -> str:
    columns = (
        ("status", "status"),
        ("clearance", "clearance"),
        ("kind", "facility_kind"),
        ("dir", "direction"),
        ("facility", "facility_id"),
        ("demand/h", "demand_hour"),
        ("arrived", "arrived_persons"),
        ("served", "served_persons"),
        ("unserved", "unserved_persons"),
        ("rate", "completion_rate"),
        ("max_q", "queue_persons_max"),
        ("final_q", "queue_persons_final"),
        ("mean_wait_s", "mean_wait_seconds"),
        ("p95_wait_s", "p95_wait_seconds"),
        ("cabins", "departed_cabins"),
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
    cases: Sequence[ProbeCase],
    rows: Sequence[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = metadata_for(args, cases)
    summary = aggregate_summary(rows)
    content = "\n".join(
        [
            "# Vertical Transport Probe Summary",
            "",
            f"- generated_at: {meta['generated_at']}",
            f"- cases: {summary['runs']}",
            f"- ok: {summary['ok']}",
            f"- errors: {summary['errors']}",
            f"- backlog: {summary['backlog']}",
            f"- worst_unserved_persons: {summary['worst_unserved_persons']}",
            f"- worst_queue_persons_max: {summary['worst_queue_persons_max']}",
            f"- minutes: {args.minutes}",
            f"- drain_seconds: {args.drain_seconds}",
            f"- design_template: {args.design_template}",
            "- process_scope: direct queue injection, no gates/platform/trains",
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
    cases: Sequence[ProbeCase],
    rows: Sequence[dict[str, Any]],
) -> None:
    write_csv(paths.csv_path, rows)
    write_json_summary(paths.json_path, args=args, cases=cases, rows=rows)
    write_markdown_summary(paths.markdown_path, args=args, cases=cases, rows=rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    seeds = args.seeds or (args.seed,)
    template_model = make_model(args, seeds[0])
    facilities = selected_facilities(
        template_model.vertical_transports,
        kinds=args.kinds,
        directions=args.directions,
        facility_id=args.facility_id,
    )
    if not facilities:
        parser.error("no vertical facilities matched the requested filters")
    cases = build_cases(facilities, demands=args.demands, seeds=seeds)
    rows = run_cases(args, cases)
    paths = resolve_output_paths(args)
    write_outputs(paths, args=args, cases=cases, rows=rows)

    summary = aggregate_summary(rows)
    print(f"[VERTICAL] wrote_csv={paths.csv_path.resolve()}")
    print(f"[VERTICAL] wrote_json={paths.json_path.resolve()}")
    print(f"[VERTICAL] wrote_markdown={paths.markdown_path.resolve()}")
    print(
        "[VERTICAL] "
        f"runs={summary['runs']} ok={summary['ok']} errors={summary['errors']} "
        f"backlog={summary['backlog']} worst_unserved={summary['worst_unserved_persons']}"
    )
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
