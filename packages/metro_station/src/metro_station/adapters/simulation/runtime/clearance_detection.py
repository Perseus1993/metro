from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .clearance_evidence import collect_clearance_evidence

if TYPE_CHECKING:
    from .mesa_model import MetroStationModel


def build_clearance_debug(model: MetroStationModel) -> dict[str, Any]:
    """Build independent physical, facility, movement, and Goal Graph evidence."""

    evidence = collect_clearance_evidence(model)
    active = evidence.active
    terminals_by_id = evidence.terminals_by_id
    queue_memberships = evidence.queue_memberships
    service_memberships = evidence.service_memberships
    movement_ids = list(evidence.movement_ids)
    passengers = list(evidence.passengers)

    duplicate_terminal_ids = sorted(
        passenger_id
        for passenger_id, events in terminals_by_id.items()
        if len(events) != 1
    )
    active_ids = sorted(active)
    incomplete_graph_ids = sorted(
        item["passenger_id"]
        for item in passengers
        if item["graph_present"] and not item["graph_complete"]
    )
    terminal_without_graph_ids = sorted(
        item["passenger_id"]
        for item in passengers
        if item["terminal_reached"] and not item["graph_present"]
    )
    graph_without_terminal_ids = sorted(
        item["passenger_id"]
        for item in passengers
        if item["graph_complete"] and not item["terminal_reached"]
    )
    missing_terminal_ids = sorted(
        item["passenger_id"]
        for item in passengers
        if item["graph_present"] and not item["terminal_reached"]
    )
    queued_ids = sorted(queue_memberships)
    in_service_ids = sorted(service_memberships)
    queued_persons = sum(
        int(getattr(passenger, "group_size", 1) or 1)
        for passenger_id in queued_ids
        if (passenger := active.get(passenger_id)) is not None
    )
    in_service_persons = sum(
        int(getattr(passenger, "group_size", 1) or 1)
        for passenger_id in in_service_ids
        if (passenger := active.get(passenger_id)) is not None
    )
    active_persons = sum(int(passenger.group_size) for passenger in active.values())
    accounted_persons = sum(int(item["persons"]) for item in passengers)
    spawned_persons = int(model.spawned_persons)
    unaccounted_persons = max(0, spawned_persons - accounted_persons)
    overaccounted_persons = max(0, accounted_persons - spawned_persons)
    graph_required = True

    physical_cleared = not active_ids
    facilities_cleared = not queued_ids and not in_service_ids
    movement_cleared = not movement_ids
    terminal_complete = (
        not duplicate_terminal_ids
        and not missing_terminal_ids
        and unaccounted_persons == 0
        and overaccounted_persons == 0
        and sum(int(event.persons) for event in model.passenger_terminal_events)
        == spawned_persons
    )
    graph_cleared = (
        not incomplete_graph_ids
        and not terminal_without_graph_ids
        and not graph_without_terminal_ids
        and len(model.passenger_goal_runtimes) == len(passengers)
    )
    fully_cleared = (
        physical_cleared
        and facilities_cleared
        and movement_cleared
        and terminal_complete
        and (graph_cleared if graph_required else True)
    )

    blockers = _blockers(
        active_ids=active_ids,
        queued_ids=queued_ids,
        in_service_ids=in_service_ids,
        movement_ids=movement_ids,
        duplicate_terminal_ids=duplicate_terminal_ids,
        missing_terminal_ids=missing_terminal_ids,
        incomplete_graph_ids=incomplete_graph_ids,
        terminal_without_graph_ids=terminal_without_graph_ids,
        graph_without_terminal_ids=graph_without_terminal_ids,
        unaccounted_persons=unaccounted_persons,
        overaccounted_persons=overaccounted_persons,
        graph_required=graph_required,
    )
    terminal_times = [float(event.time_seconds) for event in model.passenger_terminal_events]
    return {
        "schema_version": "clearance_debug.v1",
        "goal_graph_mode": model.scenario.goal_graph_mode,
        "graph_required": graph_required,
        "cleared": fully_cleared,
        "clearance_time_s": max(terminal_times) if fully_cleared and terminal_times else None,
        "checks": {
            "physical_cleared": physical_cleared,
            "facilities_cleared": facilities_cleared,
            "movement_backend_cleared": movement_cleared,
            "terminal_events_complete": terminal_complete,
            "goal_graphs_complete": graph_cleared,
        },
        "counts": {
            "spawned_persons": spawned_persons,
            "accounted_persons": accounted_persons,
            "active_persons": active_persons,
            "queued_persons": queued_persons,
            "in_service_persons": in_service_persons,
            "passenger_groups": len(passengers),
            "terminal_events": len(model.passenger_terminal_events),
            "goal_runtimes": len(model.passenger_goal_runtimes),
        },
        "blockers": blockers,
        "active_passenger_ids": active_ids,
        "queued_passenger_ids": queued_ids,
        "in_service_passenger_ids": in_service_ids,
        "movement_passenger_ids": movement_ids,
        "duplicate_terminal_ids": duplicate_terminal_ids,
        "missing_terminal_ids": missing_terminal_ids,
        "incomplete_graph_ids": incomplete_graph_ids,
        "terminal_without_graph_ids": terminal_without_graph_ids,
        "graph_without_terminal_ids": graph_without_terminal_ids,
        "unaccounted_persons": unaccounted_persons,
        "overaccounted_persons": overaccounted_persons,
        "passengers": passengers,
    }
def _blockers(**values: Any) -> list[dict[str, Any]]:
    graph_required = bool(values.pop("graph_required"))
    labels = {
        "active_ids": "physical_passengers_remaining",
        "queued_ids": "facility_queue_not_empty",
        "in_service_ids": "facility_service_not_empty",
        "movement_ids": "movement_backend_not_empty",
        "duplicate_terminal_ids": "duplicate_terminal_events",
        "missing_terminal_ids": "terminal_events_missing",
        "incomplete_graph_ids": "goal_graph_incomplete",
        "terminal_without_graph_ids": "terminal_without_goal_graph",
        "graph_without_terminal_ids": "goal_graph_complete_without_terminal",
        "unaccounted_persons": "spawned_persons_unaccounted",
        "overaccounted_persons": "passenger_ledger_exceeds_spawned_persons",
    }
    graph_keys = {
        "incomplete_graph_ids",
        "terminal_without_graph_ids",
        "graph_without_terminal_ids",
    }
    blockers: list[dict[str, Any]] = []
    for key, value in values.items():
        if key in graph_keys and not graph_required:
            continue
        if not value:
            continue
        blockers.append({"code": labels[key], "evidence": value})
    return blockers
