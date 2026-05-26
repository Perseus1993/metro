from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sandbox.metro_station_sandbox.agent_plan import AgentIntent, AgentState  # noqa: E402
from sandbox.metro_station_sandbox.agents import PassengerAgent  # noqa: E402
from sandbox.metro_station_sandbox.behavior import behavior_status_for_passenger  # noqa: E402
from sandbox.metro_station_sandbox.design import create_design  # noqa: E402
from sandbox.metro_station_sandbox.mesa_model import MetroStationModel  # noqa: E402
from sandbox.metro_station_sandbox.scenario import StationSandboxScenario  # noqa: E402


OUTPUT_ROOT = ROOT / "output" / "metro_debug_runs"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def append_ndjson(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str))
            handle.write("\n")


def passenger_record(model: MetroStationModel, passenger: PassengerAgent) -> dict[str, Any]:
    return {
        "step": model.step_index,
        "time_seconds": model.step_index * model.scenario.tick_seconds,
        "id": passenger.unique_id,
        "intent": passenger.intent,
        "state": passenger.state,
        "x": round(passenger.pos[0], 3),
        "y": round(passenger.pos[1], 3),
        "target": [round(passenger.target[0], 3), round(passenger.target[1], 3)],
        "assigned_facility_id": passenger.assigned_facility_id,
        "assigned_platform_id": passenger.assigned_platform_id,
        "goal": passenger.current_goal.as_dict(),
        "behavior": behavior_status_for_passenger(passenger).as_dict(),
        "progress_age_seconds": passenger.progress_age_seconds,
        "last_replan_reason": passenger.last_replan_reason,
    }


def changed_signature(record: dict[str, Any]) -> tuple[Any, ...]:
    behavior = record["behavior"]
    goal = record["goal"]
    return (
        record["state"],
        behavior["action"],
        behavior["queue_mode"],
        behavior["target_region"],
        record["assigned_facility_id"],
        record["assigned_platform_id"],
        goal["label"],
        goal["stage"],
    )


def run_single_flow(run_dir: Path) -> dict[str, Any]:
    scenario = StationSandboxScenario(
        station_name="single_board_alight_debug",
        hour=18,
        minutes=18,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=1,
        exit_count_hour=1,
        source_label="debug_single",
        sample_hours=1,
        train_headway_seconds=240,
        train_dwell_seconds=150,
        initial_train_offset_seconds=55,
        station_design=create_design("two_level_island_platform"),
        audit_enabled=True,
        audit_print_events=False,
        progress_monitor_enabled=True,
    )
    model = MetroStationModel(scenario, seed=20260521)
    model.spawn_schedule.clear()

    boarding = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    alighting = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EXIT_STATION,
    )
    model.passengers.extend([boarding, alighting])
    tracked = [boarding, alighting]

    step_rows: list[dict[str, Any]] = []
    transition_rows: list[dict[str, Any]] = []
    last_signatures: dict[int, tuple[Any, ...]] = {}

    while model.step_index < scenario.horizon_steps:
        model.step()
        for passenger in tracked:
            row = passenger_record(model, passenger)
            step_rows.append(row)
            signature = changed_signature(row)
            if last_signatures.get(passenger.unique_id) != signature:
                transition_rows.append(row)
                last_signatures[passenger.unique_id] = signature
        if all(passenger.state == AgentState.DEPARTED.value for passenger in tracked):
            break

    audit_rows = [event.__dict__ for event in model.audit.events]
    frames_path = run_dir / "single_flow_frames.json"
    steps_path = run_dir / "single_flow_steps.ndjson"
    transitions_path = run_dir / "single_flow_transitions.ndjson"
    audit_path = run_dir / "single_flow_audit.ndjson"

    write_json(frames_path, model.frames)
    append_ndjson(steps_path, step_rows)
    append_ndjson(transitions_path, transition_rows)
    append_ndjson(audit_path, audit_rows)

    summary = {
        "scenario": "single_board_alight",
        "description": "One enter-and-board passenger and one alighting exit-station passenger.",
        "steps_run": model.step_index,
        "time_seconds": model.step_index * scenario.tick_seconds,
        "passengers": [
            {
                "id": passenger.unique_id,
                "intent": passenger.intent,
                "final_state": passenger.state,
                "departed_step": passenger.boarded_step,
                "duration_seconds": None
                if passenger.boarded_step is None
                else passenger.boarded_step * scenario.tick_seconds,
                "assigned_platform_id": passenger.assigned_platform_id,
                "assigned_facility_id": passenger.assigned_facility_id,
            }
            for passenger in tracked
        ],
        "metrics": model.frames[-1]["metrics"] if model.frames else {},
        "audit_counts": model.audit.summary(),
        "files": {
            "frames": str(frames_path),
            "steps": str(steps_path),
            "transitions": str(transitions_path),
            "audit": str(audit_path),
        },
    }
    write_json(run_dir / "single_flow_summary.json", summary)
    return summary


def run_group_visual_demo(run_dir: Path) -> dict[str, Any]:
    stdout_path = run_dir / "group_visual_stdout.log"
    stderr_path = run_dir / "group_visual_stderr.log"
    result = subprocess.run(
        [sys.executable, "-m", "sandbox.metro_station_sandbox.visual_demo.generate_jps_tracks"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"visual demo failed with code {result.returncode}; see {stderr_path}")

    source_debug = ROOT / "output" / "visual_demo_sim_debug.json"
    copied_debug = run_dir / "group_visual_sim_debug.json"
    shutil.copy2(source_debug, copied_debug)

    data = json.loads(copied_debug.read_text(encoding="utf-8"))
    report = data.get("report", {})
    clearance = data.get("clearance_audit", {})
    events = data.get("events", [])
    samples = data.get("samples", [])
    stuck_windows = report.get("stuck_windows", []) if isinstance(report, dict) else []

    append_ndjson(run_dir / "group_visual_events.ndjson", events)
    append_ndjson(run_dir / "group_visual_stuck_windows.ndjson", stuck_windows)
    if samples:
        append_ndjson(run_dir / "group_visual_final_agents.ndjson", samples[-1].get("agents", []))

    summary = {
        "scenario": "group_visual_demo",
        "returncode": result.returncode,
        "stdout_tail": result.stdout.strip().splitlines()[-8:],
        "clearance": clearance,
        "event_counts": Counter(event.get("type", "unknown") for event in events),
        "stuck_window_count": report.get("stuck_window_count", 0),
        "resolved_stuck_window_count": report.get("resolved_stuck_window_count", 0),
        "all_stuck_window_count": report.get("all_stuck_window_count", 0),
        "stuck_by_behavior": Counter(str(item.get("behavior_action")) for item in stuck_windows),
        "stuck_by_queue_mode": Counter(str(item.get("queue_mode")) for item in stuck_windows),
        "stuck_by_target_region": Counter(str(item.get("target_region")) for item in stuck_windows),
        "top_stuck_locations": Counter(
            str(item.get("location")) for item in stuck_windows
        ).most_common(20),
        "last_live_by_facility": report.get("last_live_by_facility", {}),
        "files": {
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            "debug_json": str(copied_debug),
            "events": str(run_dir / "group_visual_events.ndjson"),
            "stuck_windows": str(run_dir / "group_visual_stuck_windows.ndjson"),
            "final_agents": str(run_dir / "group_visual_final_agents.ndjson"),
        },
    }
    write_json(run_dir / "group_visual_summary.json", summary)
    return summary


def main() -> None:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    single_summary = run_single_flow(run_dir)
    group_summary = run_group_visual_demo(run_dir)
    combined = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "single_flow": single_summary,
        "group_visual": group_summary,
    }
    write_json(run_dir / "run_summary.json", combined)
    print(json.dumps(combined, ensure_ascii=False, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
