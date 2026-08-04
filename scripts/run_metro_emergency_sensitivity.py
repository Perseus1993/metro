from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_metro_emergency_matrix as emergency  # noqa: E402
from metro_station_experiments.sensitivity import (  # noqa: E402
    sensitivity_report,
)


BASELINES = {
    "jupedsim_desired_speed_mps": 1.2,
    "gate_service_persons_per_min": 55.0,
    "density_slowdown_strength": 0.035,
    "escalator_stop_seconds": 60.0,
}


def float_list(value: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in value.split(",") if part.strip())
    if not values:
        raise argparse.ArgumentTypeError("provide at least one number")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one-at-a-time emergency sensitivity.")
    parser.add_argument("--population", type=int, default=60)
    parser.add_argument("--density-population", type=int, default=240)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument("--desired-speeds", type=float_list, default=(0.9, 1.2, 1.5))
    parser.add_argument("--gate-rates", type=float_list, default=(20.0, 55.0, 90.0))
    parser.add_argument("--density-slowdowns", type=float_list, default=(0.0, 0.035, 0.1))
    parser.add_argument("--fault-times", type=float_list, default=(45.0, 60.0, 75.0))
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "metro_emergency_sensitivity.json")
    return parser


def variants(args: argparse.Namespace) -> list[tuple[str, float]]:
    return [
        *(("jupedsim_desired_speed_mps", value) for value in args.desired_speeds),
        *(("gate_service_persons_per_min", value) for value in args.gate_rates),
        *(("density_slowdown_strength", value) for value in args.density_slowdowns),
        *(("escalator_stop_seconds", value) for value in args.fault_times),
    ]


def emergency_args(
    args: argparse.Namespace,
    parameter: str,
    value: float,
) -> argparse.Namespace:
    settings = dict(BASELINES)
    settings[parameter] = value
    stop = int(settings["escalator_stop_seconds"])
    population = args.density_population if parameter == "density_slowdown_strength" else args.population
    zero_time_events = [
        "0:disable:exit_gate:exit_gate_bank_a:lane_1",
        "0:disable:exit_gate:exit_gate_bank_a:lane_2",
        "0:disable:vertical:elevator_a:up:b2_platform:b1_concourse",
    ]
    if parameter == "gate_service_persons_per_min":
        zero_time_events.append("0:disable:exit_gate:exit_gate_bank_a:lane_3")
    if parameter == "escalator_stop_seconds":
        zero_time_events.extend(
            [
                "0:disable:vertical:up_escalator_b:up:b2_platform:b1_concourse",
                "0:disable:vertical:stairs_a:up:b2_platform:b1_concourse",
            ]
        )
    argv = [
        "--populations", str(population), "--seeds", str(args.seed),
        "--minutes", str(args.minutes), "--tick-seconds", "1",
        "--min-completion-rate", "1", "--max-clearance-seconds", "800",
        "--max-final-station-persons", "0", "--max-local-density-persons-m2", "6",
        "--jupedsim-desired-speed-mps", str(settings["jupedsim_desired_speed_mps"]),
        "--gate-service-persons-per-min", str(int(settings["gate_service_persons_per_min"])),
        "--density-slowdown-strength", str(settings["density_slowdown_strength"]),
    ]
    for event in zero_time_events:
        argv.extend(("--facility-event", event))
    argv.extend(
        (
            "--facility-event",
            f"{stop}:disable:vertical:up_escalator_a:up:b2_platform:b1_concourse",
            "--facility-event",
            f"{stop + 60}:enable:vertical:up_escalator_a:up:b2_platform:b1_concourse",
            "--quiet",
        )
    )
    return emergency.build_parser().parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for parameter, value in variants(args):
        population = (
            args.density_population
            if parameter == "density_slowdown_strength"
            else args.population
        )
        case = emergency.EmergencyCase(population, args.seed)
        row = emergency.run_case(emergency_args(args, parameter, value), case)
        row["run_id"] = f"{parameter}_{value:g}"
        row["sensitivity_parameter"] = parameter
        row["sensitivity_value"] = value
        row["sensitivity_baseline"] = value == BASELINES[parameter]
        rows.append(row)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {"model_evidence_version": emergency.MODEL_EVIDENCE_VERSION, "runs": rows},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    report = sensitivity_report(rows)
    payload = {
        "model_evidence_version": emergency.MODEL_EVIDENCE_VERSION,
        "report": report,
        "runs": rows,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return payload


def analyze_existing(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("runs")
    if not isinstance(rows, list):
        raise ValueError("sensitivity output must contain a runs list")
    report = sensitivity_report(rows)
    updated = {"report": report, "runs": rows}
    path.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return updated


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run(args)
    print(f"[SENSITIVITY] status={payload['report']['status']} output={args.output}")
    return 0 if payload["report"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
