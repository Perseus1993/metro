from __future__ import annotations

import math
import random
import re

from ..config import PEAK_ROUTE_SPAWNS, SIM_DURATION
from ..geometry import meters
from ..specs import SpawnSpec
from .constants import ENTRY_DEMAND_HORIZON
from .types import ArrivalSlot, EntryJourneyRuntime


def make_spawns(
    rng: random.Random,
    entry_journeys: list[EntryJourneyRuntime],
    count: int = PEAK_ROUTE_SPAWNS,
) -> list[SpawnSpec]:
    spawns: list[SpawnSpec] = []
    for agent_id, arrival in enumerate(bursty_arrival_slots(rng, entry_journeys, count)):
        entry = arrival.entry
        start_x, start_y = meters(entry.start)
        group_column = arrival.member_index % 3 - 1
        group_row = arrival.member_index // 3
        position = (
            start_x + group_column * rng.uniform(0.16, 0.28) + rng.uniform(-0.18, 0.18),
            start_y + group_row * rng.uniform(0.10, 0.20) + rng.uniform(-0.14, 0.14),
        )
        radius = rng.uniform(0.18, 0.23)
        speed = max(0.88, min(1.45, arrival.speed_base + rng.uniform(-0.08, 0.18)))
        spawns.append(
            SpawnSpec(
                agent_id=agent_id,
                route_name=entry.name,
                spawn_time=arrival.time,
                position=position,
                color=entry.color,
                size=round(rng.uniform(0.82, 1.12), 3),
                desired_speed=speed,
                journey_id=entry.journey_id,
                first_stage_id=entry.first_stage_id,
                radius=radius,
                time_gap=rng.uniform(0.58, 0.88),
                group_id=arrival.group_id,
                motion_phase=rng.uniform(0.0, math.tau),
                motion_wobble=rng.uniform(0.75, 1.35),
                stride_hz=rng.uniform(1.25, 1.75),
            )
        )
    return sorted(spawns, key=lambda item: item.spawn_time)


def bursty_arrival_slots(
    rng: random.Random,
    entry_journeys: list[EntryJourneyRuntime],
    count: int,
) -> list[ArrivalSlot]:
    raw: list[tuple[float, EntryJourneyRuntime, int, int, int, float]] = []
    t = 0.0
    group_id = 0
    while len(raw) < count:
        t += rng.uniform(0.55, 2.8)
        group_size = rng.randint(3, 9)
        anchor = weighted_entry_choice(rng, entry_journeys)
        side, gate_index = entry_side_and_gate(anchor)
        candidates = [
            entry
            for entry in entry_journeys
            if entry_side_and_gate(entry)[0] == side
            and abs(entry_side_and_gate(entry)[1] - gate_index) <= 1
        ] or [anchor]
        speed_base = rng.uniform(0.86, 1.24)
        member_time = t
        for member_index in range(group_size):
            member_time += rng.uniform(0.04, 0.24)
            entry = weighted_entry_choice(rng, candidates)
            raw.append((member_time, entry, group_id, member_index, group_size, speed_base))
            if len(raw) >= count:
                break
        group_id += 1

    max_raw_time = max(item[0] for item in raw)
    horizon = min(SIM_DURATION - 12.0, ENTRY_DEMAND_HORIZON)
    scale = horizon / max(max_raw_time, 1.0)
    slots = [
        ArrivalSlot(
            time=round(1.0 + raw_time * scale, 3),
            entry=entry,
            group_id=group,
            member_index=member,
            group_size=size,
            speed_base=speed,
        )
        for raw_time, entry, group, member, size, speed in raw
    ]
    return sorted(slots, key=lambda item: item.time)


def weighted_entry_choice(
    rng: random.Random,
    entries: list[EntryJourneyRuntime],
) -> EntryJourneyRuntime:
    total_weight = sum(entry.weight for entry in entries)
    pick = rng.uniform(0, total_weight)
    acc = 0.0
    for entry in entries:
        acc += entry.weight
        if pick <= acc:
            return entry
    return entries[-1]


def entry_side_and_gate(entry: EntryJourneyRuntime) -> tuple[str, int]:
    match = re.match(r"entry_(left|right)_gate_(\d+)", entry.name)
    if match:
        return match.group(1), int(match.group(2))
    match = re.match(r"entry_(left|right)_gate_choice", entry.name)
    if match:
        return match.group(1), 3
    match = re.match(r"entry_(left|right)_lane_(\d+)_gate_choice", entry.name)
    if match:
        return match.group(1), int(match.group(2)) + 1
    return "left", 3
