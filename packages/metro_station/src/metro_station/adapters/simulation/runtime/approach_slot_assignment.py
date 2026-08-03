from __future__ import annotations

from dataclasses import replace
from math import hypot


def rebalance_current_step_approach_slots(model) -> None:
    """Batch all new approach-slot assignments once before physical movement."""

    for facility in model.facilities:
        rebalance_same_step_approach_slots(model, facility)


def rebalance_same_step_approach_slots(model, facility) -> None:
    """Minimise crossing paths for a simultaneously released approach cohort.

    Queue reservations made in earlier process intervals are immutable FIFO
    commitments. Only passengers created in the current interval, still outside
    the queue, and targeting the same facility participate in this assignment.
    The cohort keeps exactly the same reserved slot set; only its one-to-one
    passenger/slot matching changes.
    """

    facility_id = facility.facility_id
    stage = facility.spec.stage
    assigned = model._facility_targeting_slot_indices.get(facility_id, {})
    passengers = sorted(
        (
            passenger
            for passenger in model.passengers
            if passenger not in facility.queue
            and assigned.get(int(passenger.unique_id)) is not None
            and passenger.facility_approach_facility_ids_by_stage.get(stage)
            == facility_id
            and (
                ownership := model._facility_approach_reservation_registry.get(
                    (int(passenger.unique_id), stage)
                )
            )
            is not None
            and int(ownership.reserved_step) == int(model.step_index)
        ),
        key=lambda passenger: int(passenger.unique_id),
    )
    if len(passengers) < 2:
        return

    slot_indices = sorted(
        int(assigned[int(passenger.unique_id)]) for passenger in passengers
    )
    if len(set(slot_indices)) != len(passengers):
        raise RuntimeError(
            f"facility {facility_id!r} has duplicate simultaneous approach slots"
        )
    layout = getattr(facility, "approach_queue_layout", facility.spec.queue_layout)
    slot_positions = [layout.slot(index) for index in slot_indices]
    costs = [
        [
            hypot(passenger.pos[0] - slot[0], passenger.pos[1] - slot[1])
            for slot in slot_positions
        ]
        for passenger in passengers
    ]
    column_by_row = _minimum_cost_assignment(costs)

    for passenger, column in zip(passengers, column_by_row, strict=True):
        passenger_id = int(passenger.unique_id)
        new_index = slot_indices[column]
        assigned[passenger_id] = new_index
        passenger.facility_approach_slots_by_stage[stage] = new_index
        facility.queue.reserve_approach_slot(passenger_id, new_index)
        key = (passenger_id, stage)
        ownership = model._facility_approach_reservation_registry.get(key)
        if ownership is not None:
            model._facility_approach_reservation_registry[key] = replace(
                ownership,
                slot_index=new_index,
            )

    facility.queue.reorder_approach_reservation_cohort(
        tuple(
            int(passenger.unique_id)
            for passenger in sorted(
                passengers,
                key=lambda item: assigned[int(item.unique_id)],
            )
        )
    )

    # Earlier members of the same spawn cohort may already hold a walking
    # command built from the pre-balanced reservation. Retarget those routes
    # atomically after every ownership projection has been updated.
    for passenger in passengers:
        goal = passenger.current_goal
        if goal.kind != "queue_approach" or goal.facility_id != facility_id:
            continue
        route = model.route_to_facility_queue(passenger, facility)
        if not route:
            continue
        passenger.set_route(
            route,
            goal_kind="queue_approach",
            goal_label=f"{facility.spec.label} queue approach",
            facility_id=facility_id,
            stage=stage,
        )


def _minimum_cost_assignment(costs: list[list[float]]) -> list[int]:
    """Return a deterministic square minimum-cost assignment (Hungarian)."""

    size = len(costs)
    if size == 0 or any(len(row) != size for row in costs):
        raise ValueError("approach assignment requires a non-empty square cost matrix")
    row_potential = [0.0] * (size + 1)
    column_potential = [0.0] * (size + 1)
    matched_row = [0] * (size + 1)
    previous_column = [0] * (size + 1)

    for row in range(1, size + 1):
        matched_row[0] = row
        minimum = [float("inf")] * (size + 1)
        used = [False] * (size + 1)
        column = 0
        while True:
            used[column] = True
            active_row = matched_row[column]
            delta = float("inf")
            next_column = 0
            for candidate in range(1, size + 1):
                if used[candidate]:
                    continue
                reduced = (
                    costs[active_row - 1][candidate - 1]
                    - row_potential[active_row]
                    - column_potential[candidate]
                )
                if reduced < minimum[candidate]:
                    minimum[candidate] = reduced
                    previous_column[candidate] = column
                if minimum[candidate] < delta:
                    delta = minimum[candidate]
                    next_column = candidate
            for candidate in range(size + 1):
                if used[candidate]:
                    row_potential[matched_row[candidate]] += delta
                    column_potential[candidate] -= delta
                else:
                    minimum[candidate] -= delta
            column = next_column
            if matched_row[column] == 0:
                break
        while True:
            previous = previous_column[column]
            matched_row[column] = matched_row[previous]
            column = previous
            if column == 0:
                break

    assignment = [0] * size
    for column in range(1, size + 1):
        assignment[matched_row[column] - 1] = column - 1
    return assignment
