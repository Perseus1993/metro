from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from metro_cloud_api.output_schema import (
    SCHEMA_VERSION,
    TRAJECTORY_SCHEMA,
    dictionary_array,
)
from metro_cloud_api.runner import ProgressCallback

from .fake_events import build_fake_events


STATES = (
    "entering_station", "queueing_gate", "passing_gate", "walking_to_vertical",
    "queueing_vertical", "riding_vertical", "walking_to_platform", "waiting_capacity",
    "waiting_platform", "queueing_door", "boarding_train", "departed",
)
STAGES = ("entry_gate", "vertical_transfer", "boarding_door", "exit_gate")


class FakeRunner:
    kind = "fake"
    version = "0.1.0"

    def __init__(self, *, seconds_per_tick: float = 0.0) -> None:
        self.seconds_per_tick = seconds_per_tick

    def run(
        self,
        spec: dict[str, Any],
        output_dir: Path,
        on_progress: ProgressCallback,
    ) -> None:
        rng = random.Random(spec["seed"])
        total = int(spec["horizon_minutes"] * 60)
        sample = int(spec["trajectory_sample_seconds"])
        count = _passenger_agent_count(spec)
        agents = _make_agents(spec, count, total, rng)
        rows = _trajectory_rows(agents, total, sample, rng, on_progress, self.seconds_per_tick)
        trajectories = _trajectory_table(rows)
        pq.write_table(
            trajectories.sort_by([("agent_id", "ascending"), ("t_seconds", "ascending")]),
            output_dir / "trajectories.parquet",
            compression="zstd",
            compression_level=3,
        )
        events = build_fake_events(agents, total)
        pq.write_table(events, output_dir / "events.parquet", compression="zstd")
        completed = [agent["end"] for agent in agents if agent["end"] <= total]
        result = {
            "schema_version": SCHEMA_VERSION,
            "passenger_agent_count": count,
            "admin_agent_count": int(spec["admins"]),
            "total_agent_count": count + int(spec["admins"]),
            "person_count": count * int(spec["group_size"]),
            "simulated_seconds": float(total),
            "trajectory_rows": trajectories.num_rows,
            "event_rows": events.num_rows,
            "clearance_seconds": max(completed) if len(completed) == count else None,
            "coordinate_transform": "identity_meters",
        }
        (output_dir / "_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _passenger_agent_count(spec: dict[str, Any]) -> int:
    if spec["scenario_mode"] == "evacuation":
        return int(spec["initial_platform_persons"] // spec["group_size"])
    return sum(
        round(spec[name] * spec["demand_minutes"] / 60 / spec["group_size"])
        for name in ("entry_count_hour", "exit_count_hour", "transfer_count_hour")
    )


def _make_agents(
    spec: dict[str, Any], count: int, total: int, rng: random.Random
) -> list[dict[str, Any]]:
    intents = _intent_allocation(spec, count)
    demand_seconds = int(spec["demand_minutes"] * 60)
    agents = []
    for index, intent in enumerate(intents):
        birth = 0.0 if spec["scenario_mode"] == "evacuation" else rng.uniform(0, demand_seconds)
        duration = 30.0 + rng.gammavariate(6.0, 25.0)
        agents.append(
            {
                "id": 1000 + index,
                "intent": intent,
                "birth": birth,
                "end": birth + duration,
                "x0": rng.uniform(-40, 40),
                "y0": rng.uniform(-30, -15),
                "x1": rng.uniform(-20, 20),
                "y1": rng.uniform(20, 35),
                "group_size": int(spec["group_size"]),
                "total": total,
            }
        )
    return agents


def _intent_allocation(spec: dict[str, Any], count: int) -> list[str]:
    if spec["scenario_mode"] == "evacuation":
        return ["evacuate_station"] * count
    weighted = [
        ("enter_and_board", int(spec["entry_count_hour"])),
        ("exit_station", int(spec["exit_count_hour"])),
        ("transfer", int(spec["transfer_count_hour"])),
    ]
    total_weight = sum(weight for _, weight in weighted)
    boundaries = []
    running = 0
    for intent, weight in weighted:
        running += weight
        boundaries.append((intent, running / total_weight))
    return [next(intent for intent, bound in boundaries if (i + 0.5) / count <= bound)
            for i in range(count)]


def _trajectory_rows(
    agents: list[dict[str, Any]],
    total: int,
    sample: int,
    rng: random.Random,
    on_progress: ProgressCallback,
    seconds_per_tick: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    last_report = 0.0
    ticks = range(0, total, sample)
    for index, tick in enumerate(ticks):
        for agent in agents:
            if not agent["birth"] <= tick < agent["end"]:
                continue
            fraction = (tick - agent["birth"]) / (agent["end"] - agent["birth"])
            state_index = min(int(fraction * len(STATES)), len(STATES) - 1)
            stage_index = min(int(fraction * len(STAGES)), len(STAGES) - 1)
            level = "platform_l2" if fraction > 0.55 else "concourse"
            jitter = rng.gauss(0, 0.4)
            rows.append(
                {
                    "agent_id": agent["id"], "t_seconds": float(tick),
                    "x": agent["x0"] + (agent["x1"] - agent["x0"]) * fraction + jitter,
                    "y": agent["y0"] + (agent["y1"] - agent["y0"]) * fraction + jitter,
                    "group_size": agent["group_size"], "state": STATES[state_index],
                    "intent": agent["intent"], "goal_kind": "facility",
                    "goal_stage": STAGES[stage_index], "goal_facility_id": f"fac_{stage_index}",
                    "level_id": level, "platform_id": "plat_1" if fraction > 0.55 else None,
                }
            )
        if seconds_per_tick:
            time.sleep(seconds_per_tick)
        now = time.monotonic()
        if now - last_report >= 1 or index == len(ticks) - 1:
            on_progress(min(tick + sample, total), total)
            last_report = now
    return rows


def _trajectory_table(rows: list[dict[str, Any]]) -> pa.Table:
    if not rows:
        return TRAJECTORY_SCHEMA.empty_table()
    arrays = []
    for field in TRAJECTORY_SCHEMA:
        values = [row[field.name] for row in rows]
        arrays.append(
            dictionary_array(values) if pa.types.is_dictionary(field.type)
            else pa.array(values, type=field.type)
        )
    return pa.Table.from_arrays(arrays, schema=TRAJECTORY_SCHEMA)
