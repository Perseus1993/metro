from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from ..planning.goal_graph import GoalNodeKind

if TYPE_CHECKING:
    from .mesa_model import MetroStationModel


@dataclass(frozen=True)
class ClearanceEvidence:
    active: dict[int, Any]
    terminals_by_id: dict[int, list[Any]]
    queue_memberships: dict[int, list[str]]
    service_memberships: dict[int, list[str]]
    movement_ids: tuple[int, ...]
    passengers: tuple[dict[str, Any], ...]


def collect_clearance_evidence(model: MetroStationModel) -> ClearanceEvidence:
    active = {int(passenger.unique_id): passenger for passenger in model.passengers}
    terminals = _group_terminal_events(model)
    parity = _group_parity_events(model)
    services = _group_service_events(model)
    queues = _queue_memberships(model)
    active_services = _service_memberships(model)
    movement_ids = tuple(sorted(model.movement_backend.active_passenger_ids()))
    passenger_ids = sorted(
        set(active)
        | set(model.passenger_goal_runtimes)
        | set(terminals)
        | set(parity)
        | set(services)
        | set(queues)
        | set(active_services)
        | set(movement_ids)
    )
    passengers = tuple(
        _passenger_debug(
            model,
            passenger_id,
            active.get(passenger_id),
            terminals.get(passenger_id, []),
            parity.get(passenger_id, []),
            services.get(passenger_id, []),
            queues.get(passenger_id, []),
            active_services.get(passenger_id, []),
            passenger_id in movement_ids,
        )
        for passenger_id in passenger_ids
    )
    return ClearanceEvidence(
        active=active,
        terminals_by_id=terminals,
        queue_memberships=queues,
        service_memberships=active_services,
        movement_ids=movement_ids,
        passengers=passengers,
    )


def _passenger_debug(
    model: MetroStationModel,
    passenger_id: int,
    passenger: Any,
    terminal_events: list[Any],
    parity_events: list[Any],
    service_events: list[Any],
    queue_facility_ids: list[str],
    service_facility_ids: list[str],
    movement_tracked: bool,
) -> dict[str, Any]:
    runtime = model.passenger_goal_runtimes.get(passenger_id)
    terminal = terminal_events[-1] if terminal_events else None
    node = None if runtime is None else runtime.graph.node(runtime.state.current_node_id)
    return {
        "passenger_id": passenger_id,
        "persons": _persons(model, passenger, terminal),
        "intent": _intent(passenger, terminal),
        "physically_active": passenger is not None,
        "movement_tracked": movement_tracked,
        "terminal_reached": len(terminal_events) == 1,
        "terminal_events": [event.as_dict() for event in terminal_events],
        "graph_present": runtime is not None,
        "graph_id": None if runtime is None else runtime.graph.graph_id,
        "graph_node_id": None if runtime is None else runtime.state.current_node_id,
        "graph_node_kind": None if node is None else node.kind,
        "graph_complete": node is not None and node.kind == GoalNodeKind.COMPLETE.value,
        "goal_state": None if runtime is None else runtime.state.as_dict(),
        "transition_history": []
        if runtime is None
        else [asdict(transition) for transition in runtime.transitions],
        "parity_events": [asdict(event) for event in parity_events],
        "facility_service_events": [event.as_dict() for event in service_events],
        "queue_facility_ids": sorted(set(queue_facility_ids)),
        "service_facility_ids": sorted(set(service_facility_ids)),
    }


def _persons(model: MetroStationModel, passenger: Any, terminal: Any) -> int:
    if passenger is not None:
        return int(passenger.group_size)
    if terminal is not None:
        return int(terminal.persons)
    return int(model.scenario.group_size)


def _intent(passenger: Any, terminal: Any) -> str | None:
    if passenger is not None:
        return str(passenger.intent)
    if terminal is not None:
        return str(terminal.intent)
    return None


def _group_terminal_events(model: MetroStationModel) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    for event in model.passenger_terminal_events:
        grouped[int(event.passenger_id)].append(event)
    return grouped


def _group_parity_events(model: MetroStationModel) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    for event in model.goal_parity.events:
        grouped[int(event.passenger_id)].append(event)
    return grouped


def _group_service_events(model: MetroStationModel) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    for event in model.facility_service_events:
        for passenger_id in event.passenger_ids:
            grouped[int(passenger_id)].append(event)
    return grouped


def _queue_memberships(model: MetroStationModel) -> dict[int, list[str]]:
    memberships: dict[int, list[str]] = defaultdict(list)
    for facility in model.facilities:
        for passenger in getattr(facility, "queue", ()):
            memberships[int(passenger.unique_id)].append(str(facility.facility_id))
    return memberships


def _service_memberships(model: MetroStationModel) -> dict[int, list[str]]:
    memberships: dict[int, list[str]] = defaultdict(list)
    for facility in model.facilities:
        passengers = [
            *(ride.passenger for ride in getattr(facility, "active_rides", ())),
            *getattr(facility, "cabin_passengers", ()),
        ]
        for passenger in passengers:
            memberships[int(passenger.unique_id)].append(str(facility.facility_id))
    return memberships
