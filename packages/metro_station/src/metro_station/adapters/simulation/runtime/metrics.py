from __future__ import annotations

from ..planning.plan import AgentState


def persons_in_states(model, states: set[str]) -> int:
    return sum(p.group_size for p in model.passengers if p.state in states)


def station_persons(model) -> int:
    return sum(p.group_size for p in model.passengers if p.state != AgentState.DEPARTED.value)


def gate_queue_persons(model) -> int:
    return sum(gate.queue_persons for gate in model.gates)


def platform_waiting_persons(model) -> int:
    return sum(
        platform.waiting_persons for platform in getattr(model, "platforms", [model.platform])
    )


def vertical_queue_persons(model) -> int:
    return sum(transport.queue_persons for transport in model.vertical_transports)


def crowding_index(model) -> float:
    return round(model.crowding_index(), 2)


def average_walk_speed_factor(model) -> float:
    return round(model.average_walk_speed_factor(), 2)


def average_system_minutes(model) -> float:
    if not model.departed_wait_minutes:
        return 0.0
    return round(sum(model.departed_wait_minutes) / len(model.departed_wait_minutes), 2)
