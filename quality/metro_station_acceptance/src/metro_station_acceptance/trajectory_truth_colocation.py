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
    maximum_distance_m: float = 0.0


def instantaneous_exact_colocations(
    observations: Iterable[TruthObservation],
    *,
    max_examples: int,
) -> tuple[int, list[dict[str, object]]]:
    positions_by_time = _unambiguous_positions_by_time(observations)
    failures = [
        (time_s, pair)
        for time_s, positions in sorted(positions_by_time.items())
        for pair in sorted(_colocated_pairs(positions))
    ]
    return len(failures), [
        {"time_s": time_s, "agent_ids": list(pair)}
        for time_s, pair in failures[:max_examples]
    ]


def persistent_exact_colocations(
    observations: Iterable[TruthObservation],
    *,
    min_duration_s: float,
    min_samples: int,
    max_examples: int,
) -> tuple[int, list[dict[str, object]]]:
    return _persistent_colocations(
        observations,
        pair_finder=lambda positions: {
            pair: 0.0 for pair in _colocated_pairs(positions)
        },
        min_duration_s=min_duration_s,
        min_samples=min_samples,
        max_examples=max_examples,
    )


def persistent_near_colocations(
    observations: Iterable[TruthObservation],
    *,
    maximum_distance_m: float,
    min_duration_s: float,
    min_samples: int,
    max_examples: int,
) -> tuple[int, list[dict[str, object]]]:
    return _persistent_colocations(
        observations,
        pair_finder=lambda positions: _near_pairs(
            positions,
            maximum_distance_m=maximum_distance_m,
        ),
        min_duration_s=min_duration_s,
        min_samples=min_samples,
        max_examples=max_examples,
    )


def interpolated_near_colocations(
    observations: Iterable[TruthObservation],
    *,
    maximum_distance_m: float,
    max_examples: int,
) -> tuple[int, list[dict[str, object]]]:
    """Find body overlaps between samples under piecewise-linear motion.

    Same-time sampling alone misses two agents that exchange sides inside one
    observation interval.  For each pair of overlapping motion segments,
    minimise their relative squared distance analytically over continuous time.
    Count at most one failure per agent pair so cadence does not inflate it.
    """

    if maximum_distance_m <= 0.0:
        return 0, []
    tracks = _unambiguous_tracks_by_agent(observations)
    failures: list[dict[str, object]] = []
    for left_id, right_id in combinations(sorted(tracks), 2):
        event = _first_interpolated_near_event(
            tracks[left_id],
            tracks[right_id],
            maximum_distance_m=maximum_distance_m,
        )
        if event is None:
            continue
        failures.append(
            {
                "agent_ids": [left_id, right_id],
                **event,
            }
        )
    failures.sort(
        key=lambda item: (float(item["time_s"]), tuple(item["agent_ids"]))
    )
    return len(failures), failures[:max_examples]


def _persistent_colocations(
    observations: Iterable[TruthObservation],
    *,
    pair_finder,
    min_duration_s: float,
    min_samples: int,
    max_examples: int,
) -> tuple[int, list[dict[str, object]]]:
    positions_by_time = _unambiguous_positions_by_time(observations)
    active_runs: dict[tuple[str, str], _ColocationRun] = {}
    completed: list[_ColocationRun] = []

    for time_s, positions in sorted(positions_by_time.items()):
        active_pairs = pair_finder(positions)
        for pair, distance_m in sorted(active_pairs.items()):
            current = active_runs.get(pair)
            if current is None:
                active_runs[pair] = _ColocationRun(
                    pair,
                    time_s,
                    time_s,
                    1,
                    distance_m,
                )
                continue
            current.end_time_s = time_s
            current.sample_count += 1
            current.maximum_distance_m = max(current.maximum_distance_m, distance_m)

        present_ids = set(positions)
        ended_pairs = [
            pair
            for pair in active_runs
            if pair not in active_pairs and pair[0] in present_ids and pair[1] in present_ids
        ]
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
            "maximum_distance_m": run.maximum_distance_m,
        }
        for run in failures[:max_examples]
    ]
    return len(failures), examples


def _unambiguous_positions_by_time(
    observations: Iterable[TruthObservation],
) -> dict[float, dict[str, tuple[float, float, str | None]]]:
    raw: defaultdict[
        float,
        defaultdict[str, set[tuple[float, float, str | None]]],
    ] = defaultdict(
        lambda: defaultdict(set)
    )
    for item in observations:
        if not all(math.isfinite(value) for value in (item.time_s, item.x, item.y)):
            continue
        raw[item.time_s][item.agent_id].add((item.x, item.y, item.level_id))

    result: dict[float, dict[str, tuple[float, float, str | None]]] = {}
    for time_s, by_agent in raw.items():
        result[time_s] = {
            agent_id: next(iter(positions))
            for agent_id, positions in by_agent.items()
            if len(positions) == 1
        }
    return result


def _unambiguous_tracks_by_agent(
    observations: Iterable[TruthObservation],
) -> dict[str, tuple[TruthObservation, ...]]:
    raw: defaultdict[tuple[str, float], list[TruthObservation]] = defaultdict(list)
    for item in observations:
        if all(math.isfinite(value) for value in (item.time_s, item.x, item.y)):
            raw[(item.agent_id, item.time_s)].append(item)
    tracks: defaultdict[str, list[TruthObservation]] = defaultdict(list)
    for (agent_id, _time_s), values in raw.items():
        positions = {(item.x, item.y, item.level_id) for item in values}
        if len(positions) == 1:
            tracks[agent_id].append(values[0])
    return {
        agent_id: tuple(sorted(values, key=lambda item: item.time_s))
        for agent_id, values in tracks.items()
    }


def _first_interpolated_near_event(
    left: tuple[TruthObservation, ...],
    right: tuple[TruthObservation, ...],
    *,
    maximum_distance_m: float,
) -> dict[str, object] | None:
    left_index = 0
    right_index = 0
    while left_index + 1 < len(left) and right_index + 1 < len(right):
        left_start, left_end = left[left_index], left[left_index + 1]
        right_start, right_end = right[right_index], right[right_index + 1]
        overlap_start = max(left_start.time_s, right_start.time_s)
        overlap_end = min(left_end.time_s, right_end.time_s)
        if overlap_end > overlap_start + 1e-9:
            if not (
                left_start.level_id
                == left_end.level_id
                == right_start.level_id
                == right_end.level_id
            ):
                if left_end.time_s <= right_end.time_s + 1e-9:
                    left_index += 1
                if right_end.time_s <= left_end.time_s + 1e-9:
                    right_index += 1
                continue
            left_at_start = _interpolate(left_start, left_end, overlap_start)
            left_at_end = _interpolate(left_start, left_end, overlap_end)
            right_at_start = _interpolate(right_start, right_end, overlap_start)
            right_at_end = _interpolate(right_start, right_end, overlap_end)
            relative_start = (
                left_at_start[0] - right_at_start[0],
                left_at_start[1] - right_at_start[1],
            )
            relative_delta = (
                (left_at_end[0] - right_at_end[0]) - relative_start[0],
                (left_at_end[1] - right_at_end[1]) - relative_start[1],
            )
            delta_squared = (
                relative_delta[0] ** 2 + relative_delta[1] ** 2
            )
            ratio = 0.0
            if delta_squared > 1e-18:
                ratio = max(
                    0.0,
                    min(
                        1.0,
                        -(
                            relative_start[0] * relative_delta[0]
                            + relative_start[1] * relative_delta[1]
                        )
                        / delta_squared,
                    ),
                )
            closest = (
                relative_start[0] + relative_delta[0] * ratio,
                relative_start[1] + relative_delta[1] * ratio,
            )
            distance = math.hypot(closest[0], closest[1])
            if distance < maximum_distance_m:
                return {
                    "time_s": overlap_start
                    + (overlap_end - overlap_start) * ratio,
                    "minimum_distance_m": distance,
                    "interval_start_s": overlap_start,
                    "interval_end_s": overlap_end,
                }
        if left_end.time_s <= right_end.time_s + 1e-9:
            left_index += 1
        if right_end.time_s <= left_end.time_s + 1e-9:
            right_index += 1
    return None


def _interpolate(
    start: TruthObservation,
    end: TruthObservation,
    time_s: float,
) -> tuple[float, float]:
    duration = end.time_s - start.time_s
    if duration <= 1e-9:
        return (start.x, start.y)
    ratio = (time_s - start.time_s) / duration
    return (
        start.x + (end.x - start.x) * ratio,
        start.y + (end.y - start.y) * ratio,
    )


def _colocated_pairs(
    positions: dict[str, tuple[float, float, str | None]],
) -> set[tuple[str, str]]:
    ids_by_position: defaultdict[
        tuple[float, float, str | None],
        list[str],
    ] = defaultdict(list)
    for agent_id, position in positions.items():
        ids_by_position[position].append(agent_id)
    return {
        pair
        for agent_ids in ids_by_position.values()
        if len(agent_ids) > 1
        for pair in combinations(sorted(agent_ids), 2)
    }


def _near_pairs(
    positions: dict[str, tuple[float, float, str | None]],
    *,
    maximum_distance_m: float,
) -> dict[tuple[str, str], float]:
    if maximum_distance_m <= 0:
        return {}
    buckets: defaultdict[
        tuple[str | None, int, int],
        list[tuple[str, tuple[float, float, str | None]]],
    ] = defaultdict(list)
    result: dict[tuple[str, str], float] = {}
    for agent_id, position in sorted(positions.items()):
        cell = (
            position[2],
            math.floor(position[0] / maximum_distance_m),
            math.floor(position[1] / maximum_distance_m),
        )
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other_id, other_position in buckets.get(
                    (cell[0], cell[1] + dx, cell[2] + dy),
                    (),
                ):
                    distance = math.hypot(
                        position[0] - other_position[0],
                        position[1] - other_position[1],
                    )
                    if distance < maximum_distance_m:
                        result[tuple(sorted((agent_id, other_id)))] = distance
        buckets[cell].append((agent_id, position))
    return result
