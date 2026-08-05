"""The only backend module allowed to import the heavyweight simulation package."""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from metro_station.adapters.simulation.cli import (
    build_parser,
    make_scenario,
    open_routing_algorithm,
)
from metro_station.adapters.simulation.executor import MesaSimulationExecutor
from metro_station.application.simulation import SimulationRequest, run_simulation

from metro_cloud_api.output_schema import (
    EVENT_SCHEMA,
    SCHEMA_VERSION,
    TRAJECTORY_SCHEMA,
    dictionary_array,
)
from metro_cloud_api.runner import ProgressCallback


class MetroStationRunner:
    kind = "real"
    version = version("metro-station")

    def run(
        self,
        spec: dict[str, Any],
        output_dir: Path,
        on_progress: ProgressCallback,
    ) -> None:
        args = build_parser().parse_args(_arguments(spec))
        scenario = make_scenario(args)
        with open_routing_algorithm(args) as (algorithm, parameters):
            execution = run_simulation(
                SimulationRequest(scenario=scenario, seed=spec["seed"]),
                MesaSimulationExecutor(
                    routing_algorithm=algorithm,
                    routing_parameters=parameters,
                ),
                progress_callback=on_progress,
            )
        trajectories, passenger_groups = _trajectories(
            execution.frames, int(spec["trajectory_sample_seconds"])
        )
        events = _events(execution.runtime, passenger_groups)
        pq.write_table(trajectories, output_dir / "trajectories.parquet", compression="zstd")
        pq.write_table(events, output_dir / "events.parquet", compression="zstd")
        passenger_agent_count = int(spec["_estimated_passenger_agents"])
        result = {
            "schema_version": SCHEMA_VERSION,
            "passenger_agent_count": passenger_agent_count,
            "admin_agent_count": int(spec["admins"]),
            "total_agent_count": passenger_agent_count + int(spec["admins"]),
            "person_count": passenger_agent_count * int(spec["group_size"]),
            "simulated_seconds": float(spec["horizon_minutes"] * 60),
            "trajectory_rows": trajectories.num_rows,
            "event_rows": events.num_rows,
            "clearance_seconds": _clearance_seconds(execution.runtime, passenger_agent_count),
            "coordinate_transform": "identity_meters",
        }
        (output_dir / "_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _arguments(spec: dict[str, Any]) -> list[str]:
    clearance = int(spec["horizon_minutes"] - spec["demand_minutes"])
    values = {
        "--station": spec["station"], "--hour": spec["hour"],
        "--minutes": spec["horizon_minutes"], "--demand-minutes": spec["demand_minutes"],
        "--clearance-minutes": clearance, "--tick-seconds": spec["tick_seconds"],
        "--group-size": spec["group_size"], "--entry-count-hour": spec["entry_count_hour"],
        "--exit-count-hour": spec["exit_count_hour"],
        "--transfer-count-hour": spec["transfer_count_hour"], "--seed": spec["seed"],
        "--design-template": spec["design_template"],
        "--movement-backend": spec["movement_backend"],
        "--jupedsim-model": spec["jupedsim_model"], "--clock-mode": spec["clock_mode"],
        "--routing-algorithm": spec["routing_algorithm"],
        "--scenario-mode": spec["scenario_mode"],
        "--initial-platform-persons": spec["initial_platform_persons"],
        "--alarm-delay-seconds": spec["alarm_delay_seconds"], "--admins": spec["admins"],
    }
    result: list[str] = ["--no-audit"]
    for flag, value in values.items():
        result.extend([flag, str(value)])
    return result


def _trajectories(
    frames: list[Any], sample_seconds: int
) -> tuple[pa.Table, dict[int, int]]:
    rows: list[dict[str, Any]] = []
    groups: dict[int, int] = {}
    for frame_value in frames:
        frame = frame_value.to_dict() if hasattr(frame_value, "to_dict") else frame_value
        at = float(frame["time_seconds"])
        if round(at) % sample_seconds:
            continue
        for passenger in frame.get("passengers", []):
            agent_id = int(passenger["id"])
            groups[agent_id] = int(passenger.get("n", 1))
            goal = passenger.get("goal") or {}
            rows.append(
                {"agent_id": agent_id, "t_seconds": at, "x": passenger["x"],
                 "y": passenger["y"], "group_size": groups[agent_id],
                 "state": passenger["state"], "intent": passenger["intent"],
                 "goal_kind": goal.get("kind"), "goal_stage": goal.get("stage"),
                 "goal_facility_id": goal.get("facility_id"),
                 "level_id": passenger.get("current_level_id"),
                 "platform_id": passenger.get("platform_id")}
            )
    return _table(rows, TRAJECTORY_SCHEMA).sort_by(
        [("agent_id", "ascending"), ("t_seconds", "ascending")]
    ), groups


def _events(runtime: Any, groups: dict[int, int]) -> pa.Table:
    rows: list[dict[str, Any]] = []
    for event in runtime.facility_service_events:
        for passenger_id in event.passenger_ids:
            rows.append(
                {"event_id": f"facility:{event.event_id}", "agent_id": passenger_id,
                 "t_seconds": event.start_time, "end_seconds": event.end_time,
                 "event_type": "facility_service", "facility_id": event.facility_id,
                 "facility_kind": event.facility_kind, "party_size": len(event.passenger_ids),
                 "detail_json": json.dumps(event.as_dict(), ensure_ascii=False, sort_keys=True)}
            )
    for index, event in enumerate(runtime.passenger_terminal_events):
        rows.append(
            {"event_id": f"terminal:{event.passenger_id}:{index}",
             "agent_id": event.passenger_id, "t_seconds": event.time_seconds,
             "end_seconds": None, "event_type": "passenger_terminal",
             "facility_id": None, "facility_kind": None,
             "party_size": int(event.persons or groups.get(event.passenger_id, 1)),
             "detail_json": json.dumps(event.as_dict(), ensure_ascii=False, sort_keys=True)}
        )
    rows.sort(key=lambda row: (row["t_seconds"], row["event_id"], row["agent_id"] or -1))
    return _table(rows, EVENT_SCHEMA)


def _table(rows: list[dict[str, Any]], schema: pa.Schema) -> pa.Table:
    if not rows:
        return schema.empty_table()
    arrays = []
    for field in schema:
        values = [row[field.name] for row in rows]
        arrays.append(
            dictionary_array(values) if pa.types.is_dictionary(field.type)
            else pa.array(values, type=field.type)
        )
    return pa.Table.from_arrays(arrays, schema=schema)


def _clearance_seconds(runtime: Any, expected_agents: int) -> float | None:
    terminal = runtime.passenger_terminal_events
    if len(terminal) < expected_agents:
        return None
    return max((float(event.time_seconds) for event in terminal), default=0.0)
