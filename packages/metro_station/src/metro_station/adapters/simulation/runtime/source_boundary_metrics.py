from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from .external_demand_reservoir import DemandSourceKind, DemandTicketState

if TYPE_CHECKING:
    from .mesa_model import MetroStationModel


def source_boundary_metrics(model: MetroStationModel) -> dict[str, Any]:
    """Report source ownership without pooling semantically different waits."""

    active_ids = {int(passenger.unique_id) for passenger in model.passengers}
    terminal_ids = {int(event.passenger_id) for event in model.passenger_terminal_events}
    pending = model.external_demand_reservoir.pending_tickets()
    residences = model.external_demand_reservoir.residences
    entry_refs = sorted(
        {
            str(ticket.source_ref or ticket.intent)
            for ticket in pending
            if ticket.source_kind == DemandSourceKind.ENTRY
        }
        | {
            str(item.ticket.source_ref or item.ticket.intent)
            for item in residences
            if item.ticket.source_kind == DemandSourceKind.ENTRY
        }
    )
    entry_rows = []
    for source_ref in entry_refs:
        waiting = [
            ticket
            for ticket in pending
            if ticket.source_kind == DemandSourceKind.ENTRY
            and str(ticket.source_ref or ticket.intent) == source_ref
        ]
        published = [
            item
            for item in residences
            if item.ticket.source_kind == DemandSourceKind.ENTRY
            and str(item.ticket.source_ref or item.ticket.intent) == source_ref
            and item.outcome == DemandTicketState.PUBLISHED
        ]
        right_censored = [
            item
            for item in residences
            if item.ticket.source_kind == DemandSourceKind.ENTRY
            and str(item.ticket.source_ref or item.ticket.intent) == source_ref
            and item.outcome == DemandTicketState.RIGHT_CENSORED
        ]
        active = [item for item in published if int(item.passenger_id) in active_ids]
        completed = [item for item in published if int(item.passenger_id) in terminal_ids]
        wait_steps = sorted(item.residence_steps for item in published)
        right_censored_wait_steps = sorted(
            item.residence_steps for item in right_censored
        )
        scheduled = sum(ticket.group_size for ticket in waiting) + sum(
            item.ticket.group_size for item in published
        ) + sum(item.ticket.group_size for item in right_censored)
        row = {
            "source_ref": source_ref,
            "scheduled_persons": scheduled,
            "admitted_persons": sum(item.ticket.group_size for item in published),
            # A censored source wait is still unresolved demand at the final
            # observation boundary. Keep it inside waiting for conservation;
            # the explicit field below is an explanatory subset, not another
            # mutually exclusive partition.
            "source_waiting_persons": sum(ticket.group_size for ticket in waiting)
            + sum(item.ticket.group_size for item in right_censored),
            "active_inside_persons": sum(item.ticket.group_size for item in active),
            "completed_persons": sum(item.ticket.group_size for item in completed),
            "not_alighted_persons": 0,
            "right_censored_persons": sum(
                item.ticket.group_size for item in right_censored
            ),
            "dropped_persons": 0,
            "wait_steps": _distribution(wait_steps),
            "right_censored_wait_steps": _distribution(right_censored_wait_steps),
        }
        row["conserved"] = scheduled == (
            row["source_waiting_persons"]
            + row["active_inside_persons"]
            + row["completed_persons"]
        )
        entry_rows.append(row)
    payload = {
        "schema_version": "metro_source_boundaries.v1",
        "entry_sources": entry_rows,
        "train_alighting_manifests": model.train_exchange_result_rows(),
        "train_alighting_unbound_failures": list(model.train_exchange_failure_rows),
        "pooled_source_wait_duration": None,
        "pooling_prohibited": True,
    }
    payload["flows"] = _flow_boundaries(
        model,
        entry_rows=entry_rows,
        active_ids=active_ids,
        terminal_ids=terminal_ids,
        pending=pending,
        residences=residences,
    )
    return payload


def aggregate_source_counts(boundaries: dict[str, Any]) -> dict[str, int]:
    """Aggregate counts without pooling durations across source boundaries.

    ``right_censored_persons`` is an explanatory subset of
    ``source_waiting_persons`` and must not be added to a conservation total.
    """

    totals: defaultdict[str, int] = defaultdict(int)
    for row in boundaries.get("entry_sources", []):
        for field in (
            "scheduled_persons",
            "admitted_persons",
            "source_waiting_persons",
            "active_inside_persons",
            "completed_persons",
            "right_censored_persons",
            "dropped_persons",
        ):
            totals[field] += int(row.get(field, 0))
    return dict(totals)


def _flow_boundaries(
    model: MetroStationModel,
    *,
    entry_rows: list[dict[str, Any]],
    active_ids: set[int],
    terminal_ids: set[int],
    pending,
    residences,
) -> dict[str, dict[str, int | bool]]:
    entry = {
        field: sum(int(row.get(field, 0)) for row in entry_rows)
        for field in (
            "scheduled_persons",
            "admitted_persons",
            "source_waiting_persons",
            "active_inside_persons",
            "completed_persons",
            "not_alighted_persons",
            "right_censored_persons",
            "dropped_persons",
        )
    }
    entry["conserved"] = entry["scheduled_persons"] == (
        entry["source_waiting_persons"]
        + entry["active_inside_persons"]
        + entry["completed_persons"]
        + entry["not_alighted_persons"]
        + entry["dropped_persons"]
    )

    waiting = [
        ticket for ticket in pending if ticket.source_kind == DemandSourceKind.TRAIN_ALIGHTING
    ]
    published = [
        item
        for item in residences
        if item.ticket.source_kind == DemandSourceKind.TRAIN_ALIGHTING
        and item.outcome == DemandTicketState.PUBLISHED
    ]
    retired_not_alighted = [
        item
        for item in residences
        if item.ticket.source_kind == DemandSourceKind.TRAIN_ALIGHTING
        and item.outcome == DemandTicketState.NOT_ALIGHTED
    ]
    right_censored = [
        item
        for item in residences
        if item.ticket.source_kind == DemandSourceKind.TRAIN_ALIGHTING
        and item.outcome == DemandTicketState.RIGHT_CENSORED
    ]
    active = [item for item in published if int(item.passenger_id) in active_ids]
    completed = [item for item in published if int(item.passenger_id) in terminal_ids]
    unbound = int(model.unbound_not_alighted_persons)
    exit_flow: dict[str, int | bool] = {
        "scheduled_persons": sum(ticket.group_size for ticket in waiting)
        + sum(item.ticket.group_size for item in published)
        + sum(item.ticket.group_size for item in retired_not_alighted)
        + sum(item.ticket.group_size for item in right_censored)
        + unbound,
        "admitted_persons": sum(item.ticket.group_size for item in published),
        "source_waiting_persons": sum(ticket.group_size for ticket in waiting)
        + sum(item.ticket.group_size for item in right_censored),
        "active_inside_persons": sum(item.ticket.group_size for item in active),
        "completed_persons": sum(item.ticket.group_size for item in completed),
        "not_alighted_persons": sum(
            item.ticket.group_size for item in retired_not_alighted
        )
        + unbound,
        "right_censored_persons": sum(
            item.ticket.group_size for item in right_censored
        ),
        "dropped_persons": 0,
    }
    exit_flow["conserved"] = exit_flow["scheduled_persons"] == (
        exit_flow["source_waiting_persons"]
        + exit_flow["active_inside_persons"]
        + exit_flow["completed_persons"]
        + exit_flow["not_alighted_persons"]
        + exit_flow["dropped_persons"]
    )
    return {"entry": entry, "exit": exit_flow}


def _distribution(values: list[int]) -> dict[str, int | None]:
    return {
        "n": len(values),
        "p50": _nearest_rank(values, 0.50),
        "p90": _nearest_rank(values, 0.90),
        "p99": _nearest_rank(values, 0.99),
        "max": max(values) if values else None,
    }


def _nearest_rank(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    index = max(0, min(len(values) - 1, int(quantile * len(values) + 0.999999) - 1))
    return int(values[index])


__all__ = ["aggregate_source_counts", "source_boundary_metrics"]
