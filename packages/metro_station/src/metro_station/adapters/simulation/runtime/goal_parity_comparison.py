from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .goal_parity import GoalParityEvent


_LIFECYCLE_KINDS = frozenset(
    {
        "facility_selected",
        "queue_joined",
        "service_started",
        "service_completed",
    }
)


def compare_goal_event_streams(
    events: Iterable[GoalParityEvent],
    passenger_ids: list[int],
) -> dict[str, Any]:
    event_list = list(events)
    comparisons = {
        "commitment_mismatches": _compare(
            event_list,
            passenger_ids,
            kinds={"facility_selected"},
        ),
        "lifecycle_mismatches": _compare(
            event_list,
            passenger_ids,
            kinds=_LIFECYCLE_KINDS,
        ),
        "stage_sequence_mismatches": _compare(
            event_list,
            passenger_ids,
            kinds={"service_completed"},
            fields=("stage",),
        ),
        "queue_mismatches": _compare(
            event_list,
            passenger_ids,
            kinds={"queue_joined"},
        ),
        "service_mismatches": _compare(
            event_list,
            passenger_ids,
            kinds={"service_started", "service_completed"},
        ),
        "level_transition_mismatches": _compare(
            event_list,
            passenger_ids,
            kinds={"level_changed"},
            fields=("stage", "facility_id", "level_id", "time_seconds"),
        ),
        "replan_mismatches": _compare(
            event_list,
            passenger_ids,
            kinds={"progress_stalled", "facility_unavailable"},
            fields=("kind", "stage", "facility_id", "reason"),
        ),
    }
    comparisons["post_terminal_lifecycle_events"] = _post_terminal_events(event_list)
    return comparisons


def _compare(
    events: list[GoalParityEvent],
    passenger_ids: list[int],
    *,
    kinds: set[str] | frozenset[str],
    fields: tuple[str, ...] = ("kind", "stage", "facility_id"),
) -> list[dict[str, object]]:
    physical = _sequences(events, "physical", kinds, fields)
    graph = _sequences(events, "graph", kinds, fields)
    return [
        {
            "passenger_id": passenger_id,
            "physical": physical.get(passenger_id, ()),
            "graph": graph.get(passenger_id, ()),
        }
        for passenger_id in passenger_ids
        if physical.get(passenger_id, ()) != graph.get(passenger_id, ())
    ]


def _sequences(
    events: list[GoalParityEvent],
    stream: str,
    kinds: set[str] | frozenset[str],
    fields: tuple[str, ...],
) -> dict[int, tuple[tuple[object, ...], ...]]:
    sequences: dict[int, list[tuple[object, ...]]] = {}
    for event in events:
        if event.stream != stream or event.kind not in kinds:
            continue
        item = tuple(getattr(event, field) for field in fields)
        sequences.setdefault(event.passenger_id, []).append(item)
    return {passenger_id: tuple(items) for passenger_id, items in sequences.items()}


def _post_terminal_events(events: list[GoalParityEvent]) -> list[dict[str, object]]:
    terminal_seen: set[tuple[int, str]] = set()
    violations: list[dict[str, object]] = []
    for event in events:
        key = (event.passenger_id, event.stream)
        if event.kind == "terminal_reached":
            terminal_seen.add(key)
            continue
        if key in terminal_seen and event.kind in _LIFECYCLE_KINDS:
            violations.append(
                {
                    "passenger_id": event.passenger_id,
                    "stream": event.stream,
                    "kind": event.kind,
                    "stage": event.stage,
                    "facility_id": event.facility_id,
                }
            )
    return violations
