from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_metro_emergency_matrix as emergency  # noqa: E402
from metro_station_experiments.performance import (  # noqa: E402
    PerformanceAcceptancePolicy,
    assess_performance,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a long-horizon metro soak profile.")
    parser.add_argument("--population", type=emergency.positive_int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--minutes", type=emergency.positive_int, default=60)
    parser.add_argument("--min-real-time-factor", type=emergency.positive_float, default=20.0)
    parser.add_argument("--max-wall-seconds", type=emergency.positive_float, default=120.0)
    parser.add_argument("--max-peak-memory-mb", type=emergency.positive_float, default=512.0)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "metro_soak.json")
    return parser


def emergency_args(args: argparse.Namespace) -> argparse.Namespace:
    return emergency.build_parser().parse_args(
        [
            "--populations", str(args.population), "--seeds", str(args.seed),
            "--minutes", str(args.minutes), "--tick-seconds", "5",
            "--min-completion-rate", "1", "--max-clearance-seconds", "800",
            "--max-final-station-persons", "0", "--max-local-density-persons-m2", "6",
            "--facility-event", "0:disable:exit_gate:exit_gate_bank_a:lane_1",
            "--facility-event", "0:disable:exit_gate:exit_gate_bank_a:lane_2",
            "--facility-event", "0:disable:exit_gate:exit_gate_bank_a:lane_3",
            "--facility-event", "0:disable:exit_gate:exit_gate_bank_a:lane_4",
            "--facility-event", "0:disable:vertical:elevator_a:up:b2_platform:b1_concourse",
            "--facility-event", "60:disable:vertical:up_escalator_a:up:b2_platform:b1_concourse",
            "--facility-event", "120:enable:vertical:up_escalator_a:up:b2_platform:b1_concourse",
            "--quiet",
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    case = emergency.EmergencyCase(args.population, args.seed)
    started = time.perf_counter()
    row = emergency.run_case(emergency_args(args), case)
    wall_seconds = time.perf_counter() - started

    tracemalloc.start()
    memory_started = time.perf_counter()
    memory_row = emergency.run_case(emergency_args(args), case)
    memory_wall_seconds = time.perf_counter() - memory_started
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    simulated_seconds = args.minutes * 60
    evidence = {
        **row,
        "wall_seconds": round(wall_seconds, 6),
        "simulated_seconds": simulated_seconds,
        "expected_frame_count": simulated_seconds // int(row["tick_seconds"]),
        "real_time_factor": round(simulated_seconds / wall_seconds, 6),
        "current_traced_memory_mb": round(current_bytes / 1024 / 1024, 6),
        "peak_traced_memory_mb": round(peak_bytes / 1024 / 1024, 6),
        "memory_profile_wall_seconds": round(memory_wall_seconds, 6),
        "memory_profile_status": memory_row["status"],
        "memory_profile_frame_count": memory_row["frame_count"],
        "memory_profile_population_accounting_error_persons": memory_row[
            "population_accounting_error_persons"
        ],
    }
    decision = assess_performance(
        evidence,
        PerformanceAcceptancePolicy(
            min_real_time_factor=args.min_real_time_factor,
            max_wall_seconds=args.max_wall_seconds,
            max_peak_memory_mb=args.max_peak_memory_mb,
            require_scenario_acceptance=False,
        ),
    )
    payload = {
        "model_evidence_version": emergency.MODEL_EVIDENCE_VERSION,
        "decision": decision,
        "evidence": evidence,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run(args)
    print(f"[SOAK] status={payload['decision']['status']} output={args.output}")
    return 0 if payload["decision"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
