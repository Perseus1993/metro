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
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sandbox.metro_station_sandbox.design import create_design  # noqa: E402
from sandbox.metro_station_sandbox.calibration.contracts import (  # noqa: E402
    SUPPORTED_CALIBRATION_STATUSES,
    CalibrationProfile,
)
from metro_station_experiments.acceptance import (  # noqa: E402
    assess_production_scenario,
)
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel  # noqa: E402
from sandbox.metro_station_sandbox.station.scenario import StationSandboxScenario  # noqa: E402
from sandbox.metro_station_sandbox.station.disruptions import (  # noqa: E402
    FacilityAvailabilityEvent,
)
from sandbox.metro_station_sandbox.station.train_disruptions import (  # noqa: E402
    TrainServiceAvailabilityEvent,
)


DEFAULT_ENTRIES = (60, 120)
DEFAULT_EXITS = (60, 120)
DEFAULT_OUTPUT_DIR = ROOT / "output" / "metro_stress_matrix"
DEFAULT_OUTPUT_STEM = "metro_stress_matrix"

FIELDNAMES = (
    "run_id",
    "status",
    "acceptance_status",
    "acceptance_issues",
    "entry_count_hour",
    "exit_count_hour",
    "seed",
    "minutes",
    "demand_minutes",
    "clearance_minutes",
    "tick_seconds",
    "group_size",
    "design_template",
    "movement_backend",
    "jupedsim_operational_model",
    "simulation_clock_mode",
    "goal_graph_mode",
    "calibration_status",
    "calibration_profile_id",
    "calibration_dataset_id",
    "validation_dataset_id",
    "goal_graph_config",
    "disabled_facility_ids",
    "facility_availability_events",
    "applied_facility_availability_events",
    "facility_service_start_violations",
    "active_service_disruption_diagnostics",
    "active_service_stranded_persons_final",
    "active_service_outage_person_seconds",
    "train_service_events",
    "applied_train_service_events",
    "cancelled_train_arrivals",
    "train_arrival_during_suspension_violations",
    "initial_train_offset_seconds",
    "train_headway_seconds",
    "train_dwell_seconds",
    "train_capacity_persons",
    "elevator_preference_share",
    "stairs_preference_share",
    "station_name",
    "hour",
    "steps_run",
    "simulated_seconds",
    "elapsed_seconds",
    "spawned_persons",
    "scheduled_demand_persons",
    "unspawned_alighting_persons_final",
    "demand_accounting_error_persons",
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
    "train_load_persons_max",
    "train_departed_load_persons_max",
    "departed_trains_final",
    "cancelled_trains_final",
    "next_train_arrival_seconds_final",
    "train_service_suspended_final",
    "platform_waiting_persons_final",
    "platform_waiting_persons_max",
    "deferred_alighting_persons_max",
    "average_system_minutes",
    "crowding_index_max",
    "average_walk_speed_factor_min",
    "jupedsim_steps",
    "jupedsim_batches",
    "audit_counts",
    "final_state_persons",
    "final_intent_state_persons",
    "final_facility_backlogs",
    "final_facility_service",
    "final_passenger_samples",
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


def unit_interval(value: str) -> float:
    parsed = float(value)
    if not isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
        raise argparse.ArgumentTypeError("value must be between 0 and 1")
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


def parse_facility_event(value: str) -> FacilityAvailabilityEvent:
    pieces = value.split(":", maxsplit=2)
    if len(pieces) != 3:
        raise argparse.ArgumentTypeError(
            "facility events must look like SECONDS:disable|enable:FACILITY_ID"
        )
    seconds_text, action, facility_id = (piece.strip() for piece in pieces)
    try:
        seconds = int(seconds_text)
        return FacilityAvailabilityEvent(seconds, action, facility_id)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_train_event(value: str) -> TrainServiceAvailabilityEvent:
    pieces = value.split(":", maxsplit=2)
    if len(pieces) != 3:
        raise argparse.ArgumentTypeError(
            "train events must look like SECONDS:suspend|resume:PLATFORM_ID"
        )
    seconds_text, action, platform_id = (piece.strip() for piece in pieces)
    try:
        return TrainServiceAvailabilityEvent(int(seconds_text), action, platform_id)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


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
    parser.add_argument(
        "--demand-minutes",
        type=positive_int,
        default=None,
        help="Stop arrivals after this many minutes, leaving the remainder for clearance.",
    )
    parser.add_argument("--tick-seconds", type=positive_int, default=1)
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
        "--clock-mode",
        choices=("legacy_scaled", "physical"),
        default="legacy_scaled",
        help="Mesa/JuPedSim clock coupling mode.",
    )
    parser.add_argument(
        "--goal-graph-mode",
        choices=("active",),
        default="active",
        help="Passenger planning authority mode.",
    )
    parser.add_argument("--goal-graph-config", type=Path, default=None)
    parser.add_argument(
        "--calibration-status",
        choices=tuple(sorted(SUPPORTED_CALIBRATION_STATUSES)),
        default="uncalibrated",
    )
    parser.add_argument("--calibration-profile-id", default="stress_matrix")
    parser.add_argument("--calibration-dataset-id", default=None)
    parser.add_argument("--validation-dataset-id", default=None)
    parser.add_argument(
        "--production-acceptance",
        action="store_true",
        help="Reject the run unless its configuration satisfies production readiness gates.",
    )
    parser.add_argument(
        "--disable-facility",
        action="append",
        default=[],
        help="Facility id to keep unavailable for the entire run. Repeatable.",
    )
    parser.add_argument(
        "--facility-event",
        action="append",
        type=parse_facility_event,
        default=[],
        help=(
            "Step-boundary availability event as SECONDS:disable|enable:FACILITY_ID. "
            "Events must be time ordered and actions must alternate. Repeatable."
        ),
    )
    parser.add_argument(
        "--train-event",
        action="append",
        type=parse_train_event,
        default=[],
        help=(
            "Train availability event as SECONDS:suspend|resume:PLATFORM_ID. "
            "Events must be time ordered and actions must alternate. Repeatable."
        ),
    )
    parser.add_argument("--initial-train-offset-seconds", type=nonnegative_int, default=75)
    parser.add_argument("--train-headway-seconds", type=positive_int, default=240)
    parser.add_argument("--train-dwell-seconds", type=positive_int, default=35)
    parser.add_argument("--train-capacity-persons", type=positive_int, default=1200)
    parser.add_argument("--elevator-preference-share", type=unit_interval, default=0.08)
    parser.add_argument("--stairs-preference-share", type=unit_interval, default=0.18)
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
        "--min-completion-rate",
        type=unit_interval,
        default=None,
        help="Fail a matrix cell when completion is below this 0..1 threshold.",
    )
    parser.add_argument(
        "--max-final-station-persons",
        type=nonnegative_int,
        default=None,
        help="Fail a matrix cell when final station backlog exceeds this threshold.",
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
        demand_minutes=args.demand_minutes,
        tick_seconds=args.tick_seconds,
        group_size=args.group_size,
        entry_count_hour=case.entry_count_hour,
        exit_count_hour=case.exit_count_hour,
        source_label="stress_matrix_cli",
        sample_hours=1,
        station_design=create_design(args.design_template),
        movement_backend_name=args.movement_backend,
        jupedsim_operational_model=args.jupedsim_model,
        simulation_clock_mode=args.clock_mode,
        goal_graph_mode=args.goal_graph_mode,
        goal_graph_catalog_path=(
            None if args.goal_graph_config is None else str(args.goal_graph_config)
        ),
        calibration_profile=calibration_profile_from_args(args),
        disabled_facility_ids=tuple(args.disable_facility),
        facility_availability_events=tuple(args.facility_event),
        train_service_events=tuple(args.train_event),
        initial_train_offset_seconds=args.initial_train_offset_seconds,
        train_headway_seconds=args.train_headway_seconds,
        train_dwell_seconds=args.train_dwell_seconds,
        train_capacity_persons=args.train_capacity_persons,
        elevator_preference_share=args.elevator_preference_share,
        stairs_preference_share=args.stairs_preference_share,
        audit_enabled=args.audit,
        audit_print_events=False,
        admin_agent_count=args.admins,
    )


def calibration_profile_from_args(args: argparse.Namespace) -> CalibrationProfile:
    return CalibrationProfile(
        profile_id=str(args.calibration_profile_id),
        status=str(args.calibration_status),
        calibration_dataset_id=args.calibration_dataset_id,
        validation_dataset_id=args.validation_dataset_id,
        notes="Stress matrix CLI calibration evidence.",
    )


def production_preflight_issues(
    args: argparse.Namespace,
    case: StressCase,
) -> list[str]:
    issues = [
        issue.message
        for issue in assess_production_scenario(make_scenario(args, case)).issues
    ]
    if args.min_completion_rate is None and args.max_final_station_persons is None:
        issues.append("production acceptance requires at least one result threshold")
    return issues


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


def train_service_diagnostics(frames: Sequence[dict[str, Any]]) -> dict[str, Any]:
    max_current_load = 0
    max_departed_load = 0
    departed_trains_final = 0
    cancelled_trains_final = 0
    next_arrival_seconds_final = 0
    service_suspended_final = False
    for frame in frames:
        trains = frame.get("trains", [])
        if not isinstance(trains, list):
            continue
        frame_departures = 0
        frame_cancellations = 0
        frame_next_arrival_seconds = 0
        frame_service_suspended = False
        for train in trains:
            if not isinstance(train, dict):
                continue
            max_current_load = max(
                max_current_load,
                int(train.get("current_load_persons", 0) or 0),
            )
            max_departed_load = max(
                max_departed_load,
                int(train.get("last_departed_load_persons", 0) or 0),
            )
            frame_departures += int(train.get("departed_trains", 0) or 0)
            frame_cancellations += int(train.get("cancelled_trains", 0) or 0)
            frame_next_arrival_seconds = max(
                frame_next_arrival_seconds,
                int(float(train.get("next_arrival_seconds", 0.0) or 0.0)),
            )
            frame_service_suspended = frame_service_suspended or bool(
                train.get("service_suspended", False)
            )
        departed_trains_final = max(departed_trains_final, frame_departures)
        cancelled_trains_final = frame_cancellations
        next_arrival_seconds_final = frame_next_arrival_seconds
        service_suspended_final = frame_service_suspended
    return {
        "train_load_persons_max": max_current_load,
        "train_departed_load_persons_max": max_departed_load,
        "departed_trains_final": departed_trains_final,
        "cancelled_trains_final": cancelled_trains_final,
        "next_train_arrival_seconds_final": next_arrival_seconds_final,
        "train_service_suspended_final": service_suspended_final,
    }


def min_frame_metric(frames: Sequence[dict[str, Any]], key: str, default: float = 0.0) -> float:
    values = frame_metrics(frames, key)
    return round(min(values), 4) if values else default


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def final_population_diagnostics(frames: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not frames:
        return {
            "final_state_persons": {},
            "final_intent_state_persons": {},
            "final_facility_backlogs": [],
            "final_facility_service": [],
            "final_passenger_samples": [],
        }

    final_frame = frames[-1]
    state_persons: dict[str, int] = {}
    intent_state_persons: dict[str, int] = {}
    for passenger in final_frame.get("passengers", []):
        if not isinstance(passenger, dict):
            continue
        persons = max(0, int(passenger.get("n", 1)))
        state = str(passenger.get("state", "unknown"))
        intent = str(passenger.get("intent", "unknown"))
        state_persons[state] = state_persons.get(state, 0) + persons
        key = f"{intent}::{state}"
        intent_state_persons[key] = intent_state_persons.get(key, 0) + persons

    facility_backlogs: list[dict[str, Any]] = []
    facility_service: list[dict[str, Any]] = []
    for facility in final_frame.get("facilities", []):
        if not isinstance(facility, dict):
            continue
        queue_persons = max(0, int(facility.get("queue_persons", 0)))
        active_persons = max(0, int(facility.get("active_persons", 0)))
        facility_service.append(
            {
                "id": str(facility.get("id", "unknown")),
                "kind": str(facility.get("kind", "unknown")),
                "state": str(facility.get("state", "unknown")),
                "served_persons": max(0, int(facility.get("served_persons", 0))),
            }
        )
        if queue_persons <= 0 and active_persons <= 0:
            continue
        facility_backlogs.append(
            {
                "id": str(facility.get("id", "unknown")),
                "kind": str(facility.get("kind", "unknown")),
                "queue_persons": queue_persons,
                "active_persons": active_persons,
            }
        )
    facility_backlogs.sort(
        key=lambda item: (-item["queue_persons"], -item["active_persons"], item["id"])
    )
    passenger_samples = sorted(
        (
            _final_passenger_sample(passenger)
            for passenger in final_frame.get("passengers", [])
            if isinstance(passenger, dict)
        ),
        key=lambda item: (-item["progress_age_seconds"], item["id"]),
    )
    return {
        "final_state_persons": dict(sorted(state_persons.items())),
        "final_intent_state_persons": dict(sorted(intent_state_persons.items())),
        "final_facility_backlogs": facility_backlogs,
        "final_facility_service": sorted(facility_service, key=lambda item: item["id"]),
        "final_passenger_samples": passenger_samples[:100],
    }


def active_service_disruption_diagnostics(
    model: MetroStationModel | None,
) -> dict[str, Any]:
    if model is None:
        return {
            "active_service_disruption_diagnostics": [],
            "active_service_stranded_persons_final": 0,
            "active_service_outage_person_seconds": 0.0,
        }
    diagnostics: list[dict[str, Any]] = []
    stranded = 0
    outage_person_seconds = 0.0
    for facility in model.vertical_transports:
        forced_stops = int(getattr(facility, "forced_stop_count", 0) or 0)
        impacted = int(getattr(facility, "forced_stop_persons", 0) or 0)
        outage = float(getattr(facility, "outage_person_seconds", 0.0) or 0.0)
        active = int(
            getattr(
                facility,
                "cabin_load_persons",
                getattr(facility, "active_ride_persons", 0),
            )
            or 0
        )
        if bool(facility.is_forced_disabled):
            stranded += active
        outage_person_seconds += outage
        if forced_stops <= 0 and outage <= 0.0 and active <= 0:
            continue
        diagnostics.append(
            {
                "facility_id": facility.facility_id,
                "kind": facility.spec.kind,
                "forced_stop_count": forced_stops,
                "forced_stop_persons": impacted,
                "outage_person_seconds": round(outage, 3),
                "active_persons_final": active,
                "disabled_final": bool(facility.is_forced_disabled),
            }
        )
    return {
        "active_service_disruption_diagnostics": diagnostics,
        "active_service_stranded_persons_final": stranded,
        "active_service_outage_person_seconds": round(outage_person_seconds, 3),
    }


def _final_passenger_sample(passenger: dict[str, Any]) -> dict[str, Any]:
    behavior = passenger.get("behavior", {})
    behavior = behavior if isinstance(behavior, dict) else {}
    goal = passenger.get("goal", {})
    goal = goal if isinstance(goal, dict) else {}
    return {
        "id": int(passenger.get("id", 0)),
        "n": max(0, int(passenger.get("n", 1))),
        "intent": str(passenger.get("intent", "unknown")),
        "state": str(passenger.get("state", "unknown")),
        "x": float(passenger.get("x", 0.0)),
        "y": float(passenger.get("y", 0.0)),
        "current_level_id": passenger.get("current_level_id"),
        "goal_kind": goal.get("kind"),
        "goal_target": goal.get("target"),
        "target_region": behavior.get("target_region"),
        "facility_id": behavior.get("facility_id"),
        "queue_mode": behavior.get("queue_mode"),
        "distance_to_target": behavior.get("distance_to_target"),
        "progress_age_seconds": float(behavior.get("progress_age_seconds", 0.0) or 0.0),
        "last_replan_reason": behavior.get("last_replan_reason"),
        "goal_graph": passenger.get("goal_graph"),
    }


def summarize_run(
    *,
    args: argparse.Namespace,
    case: StressCase,
    frames: Sequence[dict[str, Any]],
    elapsed_seconds: float,
    model: MetroStationModel | None = None,
) -> dict[str, Any]:
    final_metrics: dict[str, Any] = {}
    if frames and isinstance(frames[-1].get("metrics"), dict):
        final_metrics = frames[-1]["metrics"]

    spawned = metric_int(final_metrics, "spawned_persons")
    boarded = metric_int(final_metrics, "boarded_persons")
    exited = metric_int(final_metrics, "exit_gate_served_persons")
    completed = boarded + exited
    scheduled_demand = spawned
    unspawned_alighting = 0
    demand_accounting_error = 0
    if model is not None:
        scenario = model.scenario
        scheduled_demand = (
            scenario.entry_groups + scenario.exit_groups + scenario.transfer_groups
        ) * scenario.group_size
        unspawned_alighting = model.pending_alighting_groups * scenario.group_size
        demand_accounting_error = scheduled_demand - spawned - unspawned_alighting
    completion_rate = (
        round(completed / scheduled_demand, 4) if scheduled_demand else None
    )

    disruption_controller = None if model is None else model.disruption_controller
    train_disruption_controller = (
        None if model is None else model.train_disruption_controller
    )
    return {
        "run_id": case.run_id,
        "status": "ok",
        "entry_count_hour": case.entry_count_hour,
        "exit_count_hour": case.exit_count_hour,
        "seed": case.seed,
        "minutes": args.minutes,
        "demand_minutes": args.demand_minutes or args.minutes,
        "clearance_minutes": max(0, args.minutes - (args.demand_minutes or args.minutes)),
        "tick_seconds": args.tick_seconds,
        "group_size": args.group_size,
        "design_template": args.design_template,
        "movement_backend": final_metrics.get("movement_backend", args.movement_backend),
        "jupedsim_operational_model": final_metrics.get(
            "jupedsim_operational_model",
            args.jupedsim_model,
        ),
        "simulation_clock_mode": args.clock_mode,
        "goal_graph_mode": args.goal_graph_mode,
        "calibration_status": args.calibration_status,
        "calibration_profile_id": args.calibration_profile_id,
        "calibration_dataset_id": args.calibration_dataset_id,
        "validation_dataset_id": args.validation_dataset_id,
        "goal_graph_config": None
        if args.goal_graph_config is None
        else str(args.goal_graph_config),
        "disabled_facility_ids": list(args.disable_facility),
        "facility_availability_events": [
            event.as_dict() for event in args.facility_event
        ],
        "applied_facility_availability_events": (
            []
            if disruption_controller is None
            else disruption_controller.applied_event_dicts()
        ),
        "facility_service_start_violations": (
            0
            if disruption_controller is None
            else disruption_controller.service_start_violations(
                model.facility_service_events
            )
        ),
        "train_service_events": [event.as_dict() for event in args.train_event],
        "applied_train_service_events": (
            []
            if train_disruption_controller is None
            else train_disruption_controller.applied_event_dicts()
        ),
        "cancelled_train_arrivals": (
            []
            if train_disruption_controller is None
            else list(train_disruption_controller.cancelled_arrivals)
        ),
        "train_arrival_during_suspension_violations": (
            0
            if train_disruption_controller is None
            else train_disruption_controller.arrival_during_suspension_violations()
        ),
        "initial_train_offset_seconds": args.initial_train_offset_seconds,
        "train_headway_seconds": args.train_headway_seconds,
        "train_dwell_seconds": args.train_dwell_seconds,
        "train_capacity_persons": args.train_capacity_persons,
        "elevator_preference_share": args.elevator_preference_share,
        "stairs_preference_share": args.stairs_preference_share,
        "station_name": args.station_name,
        "hour": args.hour,
        "steps_run": len(frames),
        "simulated_seconds": args.minutes * 60,
        "elapsed_seconds": round(elapsed_seconds, 4),
        "spawned_persons": spawned,
        "scheduled_demand_persons": scheduled_demand,
        "unspawned_alighting_persons_final": unspawned_alighting,
        "demand_accounting_error_persons": demand_accounting_error,
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
        **train_service_diagnostics(frames),
        "platform_waiting_persons_final": metric_int(
            final_metrics,
            "platform_waiting_persons",
        ),
        "platform_waiting_persons_max": max_frame_metric(frames, "platform_waiting_persons"),
        "deferred_alighting_persons_max": max_frame_metric(
            frames,
            "pending_alighting_persons",
        ),
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
        **active_service_disruption_diagnostics(model),
        **final_population_diagnostics(frames),
        "error_type": None,
        "error": None,
    }


def assess_stress_row(
    row: dict[str, Any],
    *,
    min_completion_rate: float | None,
    max_final_station_persons: int | None,
) -> dict[str, Any]:
    if row.get("status") != "ok":
        return {
            "acceptance_status": "fail",
            "acceptance_issues": [str(row.get("error") or "stress run failed")],
        }
    issues: list[str] = []
    has_result_threshold = (
        min_completion_rate is not None or max_final_station_persons is not None
    )
    scheduled_demand = metric_int(
        row,
        "scheduled_demand_persons",
        metric_int(row, "spawned_persons"),
    )
    completion_rate = row.get("completion_rate")
    if min_completion_rate is not None and scheduled_demand > 0:
        if completion_rate is None:
            issues.append("completion rate is missing")
        elif float(completion_rate) < min_completion_rate:
            issues.append(
                f"completion rate {float(completion_rate):.1%} < {min_completion_rate:.1%}"
            )

    if max_final_station_persons is not None:
        final_backlog = row.get("station_persons_final")
        if final_backlog is None:
            issues.append("final station backlog is missing")
        elif int(final_backlog) > max_final_station_persons:
            issues.append(
                f"final station backlog {int(final_backlog)} > {max_final_station_persons}"
            )

    service_violations = metric_int(row, "facility_service_start_violations")
    if service_violations > 0:
        issues.append(
            f"{service_violations} facility services started during disabled intervals"
        )
    arrival_violations = metric_int(
        row,
        "train_arrival_during_suspension_violations",
    )
    if arrival_violations > 0:
        issues.append(
            f"{arrival_violations} trains arrived during suspended service intervals"
        )
    accounting_error = metric_int(row, "demand_accounting_error_persons")
    if accounting_error != 0:
        issues.append(
            f"demand accounting error is {accounting_error} persons"
        )
    stranded = metric_int(row, "active_service_stranded_persons_final")
    if stranded > 0:
        issues.append(
            f"{stranded} passengers remain stranded in disabled active service"
        )

    return {
        "acceptance_status": (
            "fail" if issues else "pass" if has_result_threshold else "not_evaluated"
        ),
        "acceptance_issues": issues,
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
            "demand_minutes": args.demand_minutes or args.minutes,
            "clearance_minutes": max(
                0,
                args.minutes - (args.demand_minutes or args.minutes),
            ),
            "tick_seconds": args.tick_seconds,
            "group_size": args.group_size,
            "design_template": args.design_template,
            "movement_backend": args.movement_backend,
            "jupedsim_operational_model": args.jupedsim_model,
            "simulation_clock_mode": args.clock_mode,
            "goal_graph_mode": args.goal_graph_mode,
            "calibration_status": args.calibration_status,
            "calibration_profile_id": args.calibration_profile_id,
            "calibration_dataset_id": args.calibration_dataset_id,
            "validation_dataset_id": args.validation_dataset_id,
            "goal_graph_config": None
            if args.goal_graph_config is None
            else str(args.goal_graph_config),
            "disabled_facility_ids": list(args.disable_facility),
            "facility_availability_events": [
                event.as_dict() for event in args.facility_event
            ],
            "train_service_events": [event.as_dict() for event in args.train_event],
            "initial_train_offset_seconds": args.initial_train_offset_seconds,
            "train_headway_seconds": args.train_headway_seconds,
            "train_dwell_seconds": args.train_dwell_seconds,
            "train_capacity_persons": args.train_capacity_persons,
            "elevator_preference_share": args.elevator_preference_share,
            "stairs_preference_share": args.stairs_preference_share,
            "station_name": args.station_name,
            "hour": args.hour,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    )
    row.update(
        assess_stress_row(
            row,
            min_completion_rate=args.min_completion_rate,
            max_final_station_persons=args.max_final_station_persons,
        )
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
    row = summarize_run(
        args=args,
        case=case,
        frames=frames,
        elapsed_seconds=time.perf_counter() - started,
        model=model,
    )
    row.update(
        assess_stress_row(
            row,
            min_completion_rate=args.min_completion_rate,
            max_final_station_persons=args.max_final_station_persons,
        )
    )
    return row


def run_matrix(
    args: argparse.Namespace,
    cases: Sequence[StressCase],
    *,
    checkpoint: Callable[[Sequence[dict[str, Any]]], None] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if not args.quiet:
            print(f"[STRESS] {index}/{len(cases)} {case.run_id}")
        try:
            row = run_case(args, case)
        except Exception as exc:  # noqa: BLE001
            row = error_row(args, case, exc)
        rows.append(row)
        if checkpoint is not None:
            checkpoint(rows)
        if args.fail_fast and row.get("acceptance_status") == "fail":
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
        "demand_minutes": args.demand_minutes or args.minutes,
        "clearance_minutes": max(0, args.minutes - (args.demand_minutes or args.minutes)),
        "tick_seconds": args.tick_seconds,
        "group_size": args.group_size,
        "design_template": args.design_template,
        "movement_backend": args.movement_backend,
        "simulation_clock_mode": args.clock_mode,
        "goal_graph_mode": args.goal_graph_mode,
        "calibration_status": args.calibration_status,
        "calibration_profile_id": args.calibration_profile_id,
        "calibration_dataset_id": args.calibration_dataset_id,
        "validation_dataset_id": args.validation_dataset_id,
        "goal_graph_config": None
        if args.goal_graph_config is None
        else str(args.goal_graph_config),
        "disabled_facility_ids": list(args.disable_facility),
        "facility_availability_events": [
            event.as_dict() for event in args.facility_event
        ],
        "train_service_events": [event.as_dict() for event in args.train_event],
        "initial_train_offset_seconds": args.initial_train_offset_seconds,
        "train_headway_seconds": args.train_headway_seconds,
        "train_dwell_seconds": args.train_dwell_seconds,
        "train_capacity_persons": args.train_capacity_persons,
        "elevator_preference_share": args.elevator_preference_share,
        "stairs_preference_share": args.stairs_preference_share,
        "station_name": args.station_name,
        "hour": args.hour,
        "min_completion_rate": args.min_completion_rate,
        "max_final_station_persons": args.max_final_station_persons,
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
        "acceptance_passed": sum(
            1 for row in rows if row.get("acceptance_status") == "pass"
        ),
        "acceptance_failed": sum(
            1 for row in rows if row.get("acceptance_status") == "fail"
        ),
        "acceptance_not_evaluated": sum(
            1 for row in rows if row.get("acceptance_status") == "not_evaluated"
        ),
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
        ("acceptance", "acceptance_status"),
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
        ("fault_service_errors", "facility_service_start_violations"),
        ("train_cancellations", "cancelled_trains_final"),
        ("train_fault_errors", "train_arrival_during_suspension_violations"),
        ("avg_min", "average_system_minutes"),
        ("issues", "acceptance_issues"),
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
            f"- acceptance_passed: {summary['acceptance_passed']}",
            f"- acceptance_failed: {summary['acceptance_failed']}",
            f"- minutes: {args.minutes}",
            f"- demand_minutes: {args.demand_minutes or args.minutes}",
            f"- clearance_minutes: {max(0, args.minutes - (args.demand_minutes or args.minutes))}",
            f"- design_template: {args.design_template}",
            f"- movement_backend: {args.movement_backend}",
            f"- jupedsim_operational_model: {args.jupedsim_model}",
            f"- simulation_clock_mode: {args.clock_mode}",
            f"- goal_graph_mode: {args.goal_graph_mode}",
            f"- calibration_status: {args.calibration_status}",
            f"- calibration_profile_id: {args.calibration_profile_id}",
            f"- calibration_dataset_id: {args.calibration_dataset_id}",
            f"- validation_dataset_id: {args.validation_dataset_id}",
            f"- disabled_facility_ids: {','.join(args.disable_facility) or '-'}",
            "- facility_availability_events: "
            + (
                compact_json([event.as_dict() for event in args.facility_event])
                if args.facility_event
                else "-"
            ),
            "- train_service_events: "
            + (
                compact_json([event.as_dict() for event in args.train_event])
                if args.train_event
                else "-"
            ),
            f"- initial_train_offset_seconds: {args.initial_train_offset_seconds}",
            f"- train_headway_seconds: {args.train_headway_seconds}",
            f"- train_dwell_seconds: {args.train_dwell_seconds}",
            f"- train_capacity_persons: {args.train_capacity_persons}",
            f"- elevator_preference_share: {args.elevator_preference_share}",
            f"- stairs_preference_share: {args.stairs_preference_share}",
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

    if args.production_acceptance:
        try:
            preflight_issues = production_preflight_issues(args, cases[0])
        except ValueError as exc:
            print(f"[STRESS] configuration_error={exc}", file=sys.stderr)
            return 2
        if preflight_issues:
            print(
                "[STRESS] production_preflight=fail issues="
                + json.dumps(preflight_issues, ensure_ascii=False),
                file=sys.stderr,
            )
            return 2

    rows = run_matrix(
        args,
        cases,
        checkpoint=lambda partial_rows: write_outputs(
            paths,
            args=args,
            cases=cases,
            rows=partial_rows,
        ),
    )
    write_outputs(paths, args=args, cases=cases, rows=rows)

    summary = aggregate_summary(rows)
    print(f"[STRESS] wrote_csv={paths.csv_path.resolve()}")
    print(f"[STRESS] wrote_json={paths.json_path.resolve()}")
    print(f"[STRESS] wrote_markdown={paths.markdown_path.resolve()}")
    print(
        "[STRESS] "
        f"runs={summary['runs']} ok={summary['ok']} errors={summary['errors']} "
        f"acceptance_failed={summary['acceptance_failed']} "
        f"worst_backlog={summary['worst_final_station_persons']}"
    )
    return 1 if summary["errors"] or summary["acceptance_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
