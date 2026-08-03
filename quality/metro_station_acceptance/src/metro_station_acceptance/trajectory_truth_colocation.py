from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
import math

from .trajectory_truth_inputs import TruthObservation


@dataclass
class _ColocationRun:
    agent_ids: tuple[str, str]
    start_time_s: float
    end_time_s: float
    sample_count: int
    last_time_index: int


def persistent_exact_colocations(
    observations: Iterable[TruthObservation],
    *,
    min_duration_s: float,
    min_samples: int,
    max_examples: int,
) -> tuple[int, list[dict[str, object]]]:
    positions_by_time = _unambiguous_positions_by_time(observations)
    active_runs: dict[tuple[str, str], _ColocationRun] = {}
    completed: list[_ColocationRun] = []

    for time_index, (time_s, positions) in enumerate(sorted(positions_by_time.items())):
        active_pairs = _colocated_pairs(positions)
        for pair in sorted(active_pairs):
            current = active_runs.get(pair)
            if current is None or current.last_time_index != time_index - 1:
                if current is not None:
                    completed.append(current)
                active_runs[pair] = _ColocationRun(pair, time_s, time_s, 1, time_index)
                continue
            current.end_time_s = time_s
            current.sample_count += 1
            current.last_time_index = time_index

        ended_pairs = [pair for pair in active_runs if pair not in active_pairs]
        for pair in ended_pairs:
            completed.append(active_runs.pop(pair))

    completed.extend(active_runs.values())
    failures = [
        run
        for run in completed
        if run.sample_count >= min_samples
        and run.end_time_s - run.start_time_s >= min_duration_s
    ]
    failures.sort(key=lambda run: (run.start_time_s, run.agent_ids))
    examples = [
        {
            "agent_ids": list(run.agent_ids),
            "start_time_s": run.start_time_s,
            "end_time_s": run.end_time_s,
            "duration_s": run.end_time_s - run.start_time_s,
            "sample_count": run.sample_count,
        }
        for run in failures[:max_examples]
    ]
    return len(failures), examples


def _unambiguous_positions_by_time(
    observations: Iterable[TruthObservation],
) -> dict[float, dict[str, tuple[float, float]]]:
    raw: defaultdict[float, defaultdict[str, set[tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for item in observations:
        if not all(math.isfinite(value) for value in (item.time_s, item.x, item.y)):
            continue
        raw[item.time_s][item.agent_id].add((item.x, item.y))

    result: dict[float, dict[str, tuple[float, float]]] = {}
    for time_s, by_agent in raw.items():
        result[time_s] = {
            agent_id: next(iter(positions))
            for agent_id, positions in by_agent.items()
            if len(positions) == 1
        }
    return result


def _colocated_pairs(
    positions: dict[str, tuple[float, float]],
) -> set[tuple[str, str]]:
    ids_by_position: defaultdict[tuple[float, float], list[str]] = defaultdict(list)
    for agent_id, position in positions.items():
        ids_by_position[position].append(agent_id)
    return {
        pair
        for agent_ids in ids_by_position.values()
        if len(agent_ids) > 1
        for pair in combinations(sorted(agent_ids), 2)
    }
