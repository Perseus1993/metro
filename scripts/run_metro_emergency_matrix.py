from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_metro_stress_matrix import (  # noqa: E402
    active_service_disruption_diagnostics,
    compact_json,
    final_population_diagnostics,
    max_frame_metric,
    parse_facility_event,
    parse_int_list,
    parse_train_event,
    train_service_diagnostics,
    unit_interval,
)
from sandbox.metro_station_sandbox.calibration.contracts import (  # noqa: E402
    SUPPORTED_CALIBRATION_STATUSES,
    CalibrationProfile,
)
from sandbox.metro_station_sandbox.design import create_design  # noqa: E402
from metro_station_experiments.acceptance import (  # noqa: E402
    ProductionAcceptancePolicy,
    assess_production_scenario,
)
from metro_station_experiments.crowd_safety import (  # noqa: E402
    crowd_safety_metrics,
)
from metro_station_experiments.emergency_acceptance import (  # noqa: E402
    EmergencyAcceptancePolicy,
    assess_emergency_row,
)
from metro_station_experiments.evacuation_metrics import (  # noqa: E402
    evacuation_metrics,
)
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel  # noqa: E402
from sandbox.metro_station_sandbox.station.evacuation import (  # noqa: E402
    EVACUATION_MODE,
    EvacuationScenarioConfig,
)
from sandbox.metro_station_sandbox.station.scenario import StationSandboxScenario  # noqa: E402


DEFAULT_OUTPUT_DIR = ROOT / "output" / "metro_emergency_matrix"
MODEL_EVIDENCE_VERSION = "emergency-v4-explicit-facility-wait"
FIELDNAMES = (
    "run_id", "status", "acceptance_status", "acceptance_issues",
    "initial_persons", "seed", "minutes", "tick_seconds", "group_size",
    "design_template", "simulation_clock_mode", "goal_graph_mode", "jupedsim_dt_seconds",
    "walk_units_per_tick", "jupedsim_desired_speed_mps",
    "gate_service_persons_per_min", "density_slowdown_strength",
    "disabled_facility_ids", "facility_availability_events", "train_service_events",
    "spawned_persons", "evacuated_persons", "remaining_persons",
    "population_accounting_error_persons", "completion_rate", "clearance_time_seconds",
    "t90_seconds", "t95_seconds", "t99_seconds", "mean_evacuation_duration_seconds",
    "peak_local_density_persons_m2", "peak_local_density_time_seconds",
    "peak_local_density_level_id", "peak_local_density_x", "peak_local_density_y",
    "peak_local_density_passenger_id",
    "duration_above_density_threshold_seconds", "density_exposure_person_seconds",
    "station_persons_max", "gate_queue_persons_max", "vertical_queue_persons_max",
    "crowding_index_max", "facility_service_start_violations",
    "train_arrival_during_suspension_violations",
    "active_service_stranded_persons_final", "active_service_outage_person_seconds",
    "active_service_disruption_diagnostics", "applied_facility_availability_events",
    "applied_train_service_events", "cancelled_train_arrivals",
    "cancelled_trains_final", "departed_trains_final", "frame_count", "elapsed_seconds",
    "final_state_persons", "final_facility_backlogs", "final_passenger_samples",
    "error_type", "error",
)


@dataclass(frozen=True)
class EmergencyCase:
    initial_persons: int
    seed: int

    @property
    def run_id(self) -> str:
        return f"evac_{self.initial_persons}_seed_{self.seed}"


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if not isfinite(parsed) or parsed <= 0.0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if not isfinite(parsed) or parsed < 0.0:
        raise argparse.ArgumentTypeError("value must be finite and >= 0")
    return parsed


def nonnegative_int_list(value: str) -> tuple[int, ...]:
    return parse_int_list(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run metro combined-emergency evacuation cases.")
    parser.add_argument("--populations", type=nonnegative_int_list, default=(0, 60, 120))
    parser.add_argument("--seeds", type=parse_int_list, default=(42,))
    parser.add_argument("--minutes", type=positive_int, default=12)
    parser.add_argument("--tick-seconds", type=positive_int, default=1)
    parser.add_argument("--group-size", type=positive_int, default=1)
    parser.add_argument("--alarm-delay-seconds", type=float, default=0.0)
    parser.add_argument("--design-template", default="visual_demo_station")
    parser.add_argument("--movement-backend", default="batched_jupedsim")
    parser.add_argument("--jupedsim-dt-seconds", type=positive_float, default=0.01)
    parser.add_argument("--clock-mode", choices=("legacy_scaled", "physical"), default="physical")
    parser.add_argument("--goal-graph-mode", choices=("active",), default="active")
    parser.add_argument("--disable-facility", action="append", default=[])
    parser.add_argument("--facility-event", action="append", type=parse_facility_event, default=[])
    parser.add_argument("--train-event", action="append", type=parse_train_event, default=[])
    parser.add_argument("--density-radius-m", type=positive_float, default=1.5)
    parser.add_argument("--walk-units-per-tick", type=positive_float, default=2.0)
    parser.add_argument("--jupedsim-desired-speed-mps", type=positive_float, default=1.2)
    parser.add_argument("--gate-service-persons-per-min", type=positive_int, default=55)
    parser.add_argument("--density-slowdown-strength", type=nonnegative_float, default=0.035)
    parser.add_argument("--max-local-density-persons-m2", type=positive_float, default=None)
    parser.add_argument("--min-completion-rate", type=unit_interval, default=None)
    parser.add_argument("--max-clearance-seconds", type=positive_float, default=None)
    parser.add_argument("--max-final-station-persons", type=int, default=None)
    parser.add_argument("--calibration-status", choices=tuple(sorted(SUPPORTED_CALIBRATION_STATUSES)), default="uncalibrated")
    parser.add_argument("--calibration-profile-id", default="emergency_matrix")
    parser.add_argument("--calibration-dataset-id", default=None)
    parser.add_argument("--validation-dataset-id", default=None)
    parser.add_argument("--production-acceptance", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-stem", default="metro_emergency_matrix")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser


def build_cases(args: argparse.Namespace) -> list[EmergencyCase]:
    return [EmergencyCase(population, seed) for population in args.populations for seed in args.seeds]


def make_scenario(args: argparse.Namespace, case: EmergencyCase) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="emergency_matrix",
        hour=18,
        minutes=args.minutes,
        tick_seconds=args.tick_seconds,
        group_size=args.group_size,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="emergency_matrix_cli",
        sample_hours=1,
        scenario_mode=EVACUATION_MODE,
        evacuation=EvacuationScenarioConfig(
            initial_platform_persons=case.initial_persons,
            alarm_delay_seconds=args.alarm_delay_seconds,
            stop_train_service=True,
        ),
        station_design=create_design(args.design_template),
        movement_backend_name=args.movement_backend,
        jupedsim_dt_seconds=args.jupedsim_dt_seconds,
        simulation_clock_mode=args.clock_mode,
        goal_graph_mode=args.goal_graph_mode,
        calibration_profile=CalibrationProfile(
            profile_id=args.calibration_profile_id,
            status=args.calibration_status,
            calibration_dataset_id=args.calibration_dataset_id,
            validation_dataset_id=args.validation_dataset_id,
            notes="Emergency matrix CLI calibration evidence.",
        ),
        disabled_facility_ids=tuple(args.disable_facility),
        facility_availability_events=tuple(args.facility_event),
        train_service_events=tuple(args.train_event),
        audit_enabled=False,
        audit_print_events=False,
        walk_units_per_tick=args.walk_units_per_tick,
        jupedsim_desired_speed_mps=args.jupedsim_desired_speed_mps,
        jupedsim_free_speed_min_mps=min(0.75, args.jupedsim_desired_speed_mps),
        jupedsim_free_speed_max_mps=max(1.65, args.jupedsim_desired_speed_mps),
        gate_service_persons_per_min=args.gate_service_persons_per_min,
        density_slowdown_strength=args.density_slowdown_strength,
    )


def acceptance_policy(args: argparse.Namespace) -> EmergencyAcceptancePolicy:
    return EmergencyAcceptancePolicy(
        min_completion_rate=args.min_completion_rate,
        max_clearance_seconds=args.max_clearance_seconds,
        max_final_station_persons=args.max_final_station_persons,
        max_local_density_persons_m2=args.max_local_density_persons_m2,
    )


def production_preflight_issues(args: argparse.Namespace, case: EmergencyCase) -> list[str]:
    scenario = make_scenario(args, case)
    decision = assess_production_scenario(
        scenario,
        ProductionAcceptancePolicy(require_clearance_window=False),
    )
    issues = [issue.message for issue in decision.issues]
    if not acceptance_policy(args).has_result_threshold:
        issues.append("production emergency acceptance requires at least one result threshold")
    return issues


def run_case(args: argparse.Namespace, case: EmergencyCase) -> dict[str, Any]:
    started = time.perf_counter()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r"The use of the `seed` keyword argument is deprecated.*", category=FutureWarning)
        model = MetroStationModel(make_scenario(args, case), seed=case.seed)
    frames = model.run()
    remaining = int(frames[-1]["metrics"]["station_persons"]) if frames else 0
    evacuation = evacuation_metrics(
        model.passenger_terminal_events,
        total_persons=case.initial_persons,
        remaining_persons=remaining,
    )
    density = crowd_safety_metrics(
        frames,
        radius_m=args.density_radius_m,
        tick_seconds=args.tick_seconds,
        threshold_persons_m2=args.max_local_density_persons_m2,
    )
    train_diag = train_service_diagnostics(frames)
    disruption = active_service_disruption_diagnostics(model)
    row: dict[str, Any] = {
        "run_id": case.run_id, "status": "ok", "initial_persons": case.initial_persons,
        "seed": case.seed, "minutes": args.minutes, "tick_seconds": args.tick_seconds,
        "group_size": args.group_size, "design_template": args.design_template,
        "simulation_clock_mode": args.clock_mode, "goal_graph_mode": args.goal_graph_mode,
        "jupedsim_dt_seconds": args.jupedsim_dt_seconds,
        "walk_units_per_tick": args.walk_units_per_tick,
        "jupedsim_desired_speed_mps": args.jupedsim_desired_speed_mps,
        "gate_service_persons_per_min": args.gate_service_persons_per_min,
        "density_slowdown_strength": args.density_slowdown_strength,
        "disabled_facility_ids": list(args.disable_facility),
        "facility_availability_events": [event.as_dict() for event in args.facility_event],
        "train_service_events": [event.as_dict() for event in args.train_event],
        "spawned_persons": model.spawned_persons, "evacuated_persons": model.evacuated_persons,
        "remaining_persons": remaining,
        "population_accounting_error_persons": case.initial_persons - model.evacuated_persons - remaining,
        **evacuation, **density,
        "station_persons_max": max_frame_metric(frames, "station_persons"),
        "gate_queue_persons_max": max_frame_metric(frames, "gate_queue_persons"),
        "vertical_queue_persons_max": max_frame_metric(frames, "vertical_queue_persons"),
        "crowding_index_max": max((float(frame["metrics"].get("crowding_index", 0.0)) for frame in frames), default=0.0),
        "facility_service_start_violations": model.disruption_controller.service_start_violations(model.facility_service_events),
        "train_arrival_during_suspension_violations": model.train_disruption_controller.arrival_during_suspension_violations(),
        **disruption,
        "applied_facility_availability_events": model.disruption_controller.applied_event_dicts(),
        "applied_train_service_events": model.train_disruption_controller.applied_event_dicts(),
        "cancelled_train_arrivals": list(model.train_disruption_controller.cancelled_arrivals),
        **train_diag,
        "frame_count": len(frames),
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        **final_population_diagnostics(frames),
        "error_type": None, "error": None,
    }
    row.update(assess_emergency_row(row, acceptance_policy(args)))
    return row


def error_row(args: argparse.Namespace, case: EmergencyCase, exc: Exception) -> dict[str, Any]:
    row = {field: None for field in FIELDNAMES}
    row.update({"run_id": case.run_id, "status": "error", "initial_persons": case.initial_persons, "seed": case.seed, "error_type": type(exc).__name__, "error": str(exc)})
    row.update(assess_emergency_row(row, acceptance_policy(args)))
    return row


def write_outputs(args: argparse.Namespace, cases: Sequence[EmergencyCase], rows: Sequence[dict[str, Any]]) -> tuple[Path, Path, Path]:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / f"{args.output_stem}.csv"
    json_path = args.out_dir / f"{args.output_stem}.json"
    md_path = args.out_dir / f"{args.output_stem}.md"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: compact_json(row.get(field)) if isinstance(row.get(field), (dict, list, tuple)) else row.get(field) for field in FIELDNAMES})
    payload = {"metadata": {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "case_count": len(cases), "configuration_fingerprint": configuration_fingerprint(args), "model_evidence_version": MODEL_EVIDENCE_VERSION}, "summary": summary(rows), "runs": list(rows)}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    md_path.write_text(_markdown(rows), encoding="utf-8")
    return csv_path, json_path, md_path


def summary(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    return {
        "runs": len(rows),
        "ok": sum(row.get("status") == "ok" for row in rows),
        "errors": sum(row.get("status") != "ok" for row in rows),
        "acceptance_passed": sum(row.get("acceptance_status") == "pass" for row in rows),
        "acceptance_failed": sum(row.get("acceptance_status") == "fail" for row in rows),
    }


def configuration_fingerprint(args: argparse.Namespace) -> str:
    ignored = {"populations", "seeds", "out_dir", "output_stem", "quiet", "resume"}
    payload = {
        "model_evidence_version": MODEL_EVIDENCE_VERSION,
        "configuration": {
        key: _fingerprint_value(value)
        for key, value in sorted(vars(args).items())
        if key not in ignored
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_resume_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    path = args.out_dir / f"{args.output_stem}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    existing = payload.get("metadata", {}).get("configuration_fingerprint")
    current = configuration_fingerprint(args)
    if existing != current:
        raise ValueError("resume output configuration fingerprint does not match current run")
    return [dict(row) for row in payload.get("runs", []) if isinstance(row, dict)]


def _fingerprint_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_fingerprint_value(item) for item in value]
    if hasattr(value, "as_dict"):
        return value.as_dict()
    return value


def _markdown(rows: Sequence[dict[str, Any]]) -> str:
    lines = ["# Metro Emergency Matrix", "", "| run | status | acceptance | population | completion | clearance_s | peak_density | remaining |", "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(key, "")) for key in ("run_id", "status", "acceptance_status", "initial_persons", "completion_rate", "clearance_time_seconds", "peak_local_density_persons_m2", "remaining_persons")) + " |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_final_station_persons is not None and args.max_final_station_persons < 0:
        raise SystemExit("--max-final-station-persons must be >= 0")
    cases = build_cases(args)
    if args.production_acceptance:
        issues = production_preflight_issues(args, cases[0])
        if issues:
            print("[EMERGENCY] preflight failed: " + "; ".join(issues), file=sys.stderr)
            return 2
    rows = load_resume_rows(args) if args.resume else []
    requested_ids = {case.run_id for case in cases}
    rows = [row for row in rows if row.get("run_id") in requested_ids]
    completed_ids = {str(row.get("run_id")) for row in rows}
    for case in cases:
        if case.run_id in completed_ids:
            if not args.quiet:
                print(f"[EMERGENCY] resume skip {case.run_id}")
            continue
        if not args.quiet:
            print(f"[EMERGENCY] {case.run_id}")
        try:
            rows.append(run_case(args, case))
        except Exception as exc:  # noqa: BLE001
            rows.append(error_row(args, case, exc))
        write_outputs(args, cases, rows)
    paths = write_outputs(args, cases, rows)
    result = summary(rows)
    print(f"[EMERGENCY] runs={result['runs']} ok={result['ok']} acceptance_failed={result['acceptance_failed']}")
    for path in paths:
        print(f"[EMERGENCY] wrote={path}")
    return 1 if result["errors"] or result["acceptance_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
