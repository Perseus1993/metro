from __future__ import annotations

from math import hypot


def reconcile_settled_physical_fifo(queue) -> None:
    """Repair an impossible FIFO inversion without moving bodies through bodies."""

    slots = tuple(getattr(queue.layout, "slots", ()))
    if len(queue) < 2 or not slots:
        return
    nearest_by_passenger_id = {
        id(passenger): queue._nearest_explicit_slot_index(passenger)
        for passenger in queue
    }
    if len(set(nearest_by_passenger_id.values())) != len(queue):
        return
    if any(
        hypot(
            passenger.pos[0] - slots[nearest_by_passenger_id[id(passenger)]][0],
            passenger.pos[1] - slots[nearest_by_passenger_id[id(passenger)]][1],
        )
        > 0.12
        for passenger in queue
    ):
        return
    def order_key(passenger):
        return (
            nearest_by_passenger_id[id(passenger)],
            int(passenger.unique_id),
        )
    if sorted(queue, key=order_key) == list(queue):
        return
    priorities = sorted(
        queue._priority_by_passenger_id.get(id(passenger), index)
        for index, passenger in enumerate(queue)
    )
    list.sort(queue, key=order_key)
    for priority, passenger in zip(priorities, queue, strict=True):
        passenger_id = id(passenger)
        queue._priority_by_passenger_id[passenger_id] = priority
        queue._assigned_slot_index_by_passenger_id[passenger_id] = (
            nearest_by_passenger_id[passenger_id]
        )


__all__ = ["reconcile_settled_physical_fifo"]
