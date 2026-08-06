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
        active = [item for item in published if int(item.passenger_id) in active_ids]
        completed = [item for item in published if int(item.passenger_id) in terminal_ids]
        wait_steps = sorted(item.residence_steps for item in published)
        scheduled = sum(ticket.group_size for ticket in waiting) + sum(
            item.ticket.group_size for item in published
        )
        row = {
            "source_ref": source_ref,
            "scheduled_persons": scheduled,
            "admitted_persons": sum(item.ticket.group_size for item in published),
            "source_waiting_persons": sum(ticket.group_size for ticket in waiting),
            "active_inside_persons": sum(item.ticket.group_size for item in active),
            "completed_persons": sum(item.ticket.group_size for item in completed),
            "not_alighted_persons": 0,
            "dropped_persons": 0,
            "wait_steps": _distribution(wait_steps),
        }
        row["conserved"] = scheduled == (
            row["source_waiting_persons"]
            + row["active_inside_persons"]
            + row["completed_persons"]
        )
        entry_rows.append(row)
    return {
        "schema_version": "metro_source_boundaries.v1",
        "entry_sources": entry_rows,
        "train_alighting_manifests": model.train_exchange_result_rows(),
        "train_alighting_unbound_failures": list(model.train_exchange_failure_rows),
        "pooled_source_wait_duration": None,
        "pooling_prohibited": True,
    }


def aggregate_source_counts(boundaries: dict[str, Any]) -> dict[str, int]:
    """Aggregate only conservation counts; never aggregate duration distributions."""

    totals: defaultdict[str, int] = defaultdict(int)
    for row in boundaries.get("entry_sources", []):
        for field in (
            "scheduled_persons",
            "admitted_persons",
            "source_waiting_persons",
            "active_inside_persons",
            "completed_persons",
            "dropped_persons",
        ):
            totals[field] += int(row.get(field, 0))
    return dict(totals)


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
