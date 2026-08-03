from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
import math

from .trajectory_truth_inputs import TruthObservation


def observations_by_agent(
    observations: Iterable[TruthObservation],
) -> dict[str, list[TruthObservation]]:
    result: defaultdict[str, list[TruthObservation]] = defaultdict(list)
    for item in observations:
        result[item.agent_id].append(item)
    return dict(result)


def non_finite_observations(
    observations: Iterable[TruthObservation],
    *,
    max_examples: int,
) -> tuple[int, list[dict[str, object]]]:
    count = 0
    examples: list[dict[str, object]] = []
    for item in observations:
        fields = [
            name
            for name, value in (("t", item.time_s), ("x", item.x), ("y", item.y))
            if not math.isfinite(value)
        ]
        if not fields:
            continue
        count += 1
        if len(examples) < max_examples:
            examples.append(
                {
                    "agent_id": item.agent_id,
                    "source_index": item.source_index,
                    "non_finite_fields": fields,
                }
            )
    return count, examples


def time_regressions(
    by_agent: dict[str, list[TruthObservation]],
    *,
    time_epsilon_s: float,
    max_examples: int,
) -> tuple[int, list[dict[str, object]]]:
    count = 0
    examples: list[dict[str, object]] = []
    for agent_id in sorted(by_agent):
        finite = [item for item in by_agent[agent_id] if math.isfinite(item.time_s)]
        for previous, current in zip(finite, finite[1:], strict=False):
            if current.time_s >= previous.time_s - time_epsilon_s:
                continue
            count += 1
            if len(examples) < max_examples:
                examples.append(
                    {
                        "agent_id": agent_id,
                        "previous_time_s": previous.time_s,
                        "current_time_s": current.time_s,
                        "previous_source_index": previous.source_index,
                        "current_source_index": current.source_index,
                    }
                )
    return count, examples


def same_time_position_conflicts(
    observations: Iterable[TruthObservation],
    *,
    position_epsilon: float,
    max_examples: int,
) -> tuple[int, list[dict[str, object]]]:
    grouped: defaultdict[tuple[str, float], list[TruthObservation]] = defaultdict(list)
    for item in observations:
        if all(math.isfinite(value) for value in (item.time_s, item.x, item.y)):
            grouped[(item.agent_id, item.time_s)].append(item)

    failures: list[dict[str, object]] = []
    for (agent_id, time_s), items in sorted(grouped.items()):
        if len(items) < 2 or not _positions_differ(items, position_epsilon):
            continue
        failures.append(
            {
                "agent_id": agent_id,
                "time_s": time_s,
                "positions": sorted({(item.x, item.y) for item in items}),
                "source_indexes": [item.source_index for item in items],
            }
        )
    return len(failures), failures[:max_examples]


def excessive_average_speeds(
    by_agent: dict[str, list[TruthObservation]],
    *,
    max_speed: float,
    time_epsilon_s: float,
    max_examples: int,
) -> tuple[int, list[dict[str, object]], float | None]:
    count = 0
    observed_max: float | None = None
    examples: list[dict[str, object]] = []
    for agent_id in sorted(by_agent):
        finite = [
            item
            for item in by_agent[agent_id]
            if all(math.isfinite(value) for value in (item.time_s, item.x, item.y))
        ]
        for previous, current in zip(finite, finite[1:], strict=False):
            duration = current.time_s - previous.time_s
            if duration <= time_epsilon_s:
                continue
            distance = math.hypot(current.x - previous.x, current.y - previous.y)
            speed = distance / duration
            observed_max = speed if observed_max is None else max(observed_max, speed)
            if speed <= max_speed:
                continue
            count += 1
            if len(examples) < max_examples:
                examples.append(
                    {
                        "agent_id": agent_id,
                        "start_time_s": previous.time_s,
                        "end_time_s": current.time_s,
                        "distance_m": distance,
                        "duration_s": duration,
                        "average_speed_m_s": speed,
                    }
                )
    return count, examples, observed_max


def sampling_interval_distribution(
    by_agent: dict[str, list[TruthObservation]],
    *,
    time_epsilon_s: float,
) -> dict[str, float | int | None]:
    positive: list[float] = []
    zero_count = 0
    negative_count = 0
    for items in by_agent.values():
        finite_times = [item.time_s for item in items if math.isfinite(item.time_s)]
        for previous, current in zip(finite_times, finite_times[1:], strict=False):
            interval = current - previous
            if interval < -time_epsilon_s:
                negative_count += 1
            elif interval <= time_epsilon_s:
                zero_count += 1
            else:
                positive.append(interval)

    positive.sort()
    return {
        "positive_count": len(positive),
        "zero_count": zero_count,
        "negative_count": negative_count,
        "min": None if not positive else positive[0],
        "mean": None if not positive else sum(positive) / len(positive),
        "p50": _percentile(positive, 0.50),
        "p90": _percentile(positive, 0.90),
        "p95": _percentile(positive, 0.95),
        "p99": _percentile(positive, 0.99),
        "max": None if not positive else positive[-1],
    }


def _positions_differ(items: list[TruthObservation], epsilon: float) -> bool:
    first = items[0]
    return any(math.hypot(item.x - first.x, item.y - first.y) > epsilon for item in items[1:])


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction
