from __future__ import annotations

from dataclasses import dataclass, replace
from math import hypot, isfinite

from ..facilities.process import FacilityKind
from ..planning.plan import AgentGoal, FacilityStage


@dataclass(frozen=True)
class _NavigationSnapshot:
    passenger: object
    target: tuple[float, float]
    route: tuple[tuple[float, float], ...]
    route_segment_start: tuple[float, float]
    pending_route_transition: object
    corner_recovery_anchor: tuple[float, float] | None
    corner_recovery_speed_limit_mps: float | None
    goal: object


@dataclass(frozen=True)
class _PreparedNavigation:
    passenger: object
    points: tuple[tuple[float, float], ...]
    expected_terminal: tuple[float, float]
    goal: object


def rebalance_current_step_approach_slots(model) -> None:
    """Batch all new approach-slot assignments once before physical movement."""

    for facility in model.facilities:
        if not compact_existing_approach_slots(model, facility):
            rebalance_same_step_approach_slots(model, facility)


def compact_existing_approach_slots(model, facility) -> bool:
    """Close released holes without changing the pending FIFO order.

    A tail reservation is a physical ownership claim, but it is not a promise
    to wait forever at that exact slot.  When earlier claimants join or leave,
    retaining the outermost index can make every free inner slot unavailable
    under the no-overtaking frontier rule.  Compact all pending owners as one
    atomic transaction and retarget their authoritative routes to the new
    contiguous slots.
    """

    facility_id = facility.facility_id
    stage = facility.spec.stage
    assigned = model._facility_targeting_slot_indices.get(facility_id, {})
    reservation_state = facility.queue.approach_reservation_state()
    reserved_slots = dict(reservation_state.slots)
    priorities = dict(reservation_state.priorities)
    if not assigned or set(assigned) != set(reserved_slots):
        return False

    active_by_id = {int(passenger.unique_id): passenger for passenger in model.passengers}
    if any(passenger_id not in active_by_id for passenger_id in assigned):
        return False
    passengers = [active_by_id[passenger_id] for passenger_id in assigned]
    if any(
        passenger in facility.queue
        or passenger.facility_approach_facility_ids_by_stage.get(stage) != facility_id
        or model._facility_approach_reservation_registry.get(
            (int(passenger.unique_id), stage)
        )
        is None
        for passenger in passengers
    ):
        return False
    passengers.sort(
        key=lambda passenger: (
            priorities[int(passenger.unique_id)],
            int(passenger.unique_id),
        )
    )

    binding = model.facility_portal_binding(facility_id)
    rank_by_index = {
        int(slot.runtime_slot_index): int(slot.service_rank)
        for slot in binding.queue_slot_bindings
        if slot.runtime_slot_index is not None and slot.service_rank is not None
    }
    candidate_indices = sorted(
        model._facility_approach_slot_indices(facility),
        key=rank_by_index.__getitem__,
    )
    occupied_by_queue = (
        set(facility.queue.committed_slot_indices)
    ) | set(facility.lifecycle_reserved_queue_slot_indices)
    occupied_ranks = [
        rank_by_index[index]
        for index in occupied_by_queue
        if index in rank_by_index
    ]
    frontier_rank = max(occupied_ranks, default=-1)
    compacted_indices = [
        index
        for index in candidate_indices
        if index not in occupied_by_queue and rank_by_index[index] > frontier_rank
    ][: len(passengers)]
    if len(compacted_indices) != len(passengers):
        return False

    previous_slot_by_passenger_id = {
        int(passenger.unique_id): int(assigned[int(passenger.unique_id)])
        for passenger in passengers
    }
    proposed_slot_by_passenger_id = {
        int(passenger.unique_id): int(slot_index)
        for passenger, slot_index in zip(passengers, compacted_indices, strict=True)
    }
    if proposed_slot_by_passenger_id == previous_slot_by_passenger_id:
        return False

    prepared_navigation: list[_PreparedNavigation] = []
    navigation_snapshots = tuple(
        _navigation_snapshot(passenger) for passenger in passengers
    )
    for passenger in passengers:
        passenger_id = int(passenger.unique_id)
        old_index = previous_slot_by_passenger_id[passenger_id]
        new_index = proposed_slot_by_passenger_id[passenger_id]
        if old_index == new_index:
            continue
        dormant_platform_wait = (
            str(passenger.state) == "waiting_platform"
            and passenger_id in model._platform_waiting_reservations
        )
        if dormant_platform_wait:
            # The approach claim preserves future FIFO order while the body
            # is temporarily stored outside an active train-door crossing.
            # Compact the ownership mirrors, but keep the current platform
            # waiting target under its own physical authority.
            continue
        old_target = model._facility_approach_slot_position(facility, old_index)
        new_target = model._facility_approach_slot_position(facility, new_index)
        route_terminal = _effective_navigation_terminal(passenger)
        owns_old_terminal = hypot(
            route_terminal[0] - old_target[0],
            route_terminal[1] - old_target[1],
        ) <= 1e-6
        already_at_new_target = hypot(
            passenger.pos[0] - new_target[0],
            passenger.pos[1] - new_target[1],
        ) <= 1e-6
        if not owns_old_terminal and not already_at_new_target:
            return False
        if already_at_new_target and not owns_old_terminal:
            route = ()
        elif facility.spec.kind == FacilityKind.GATE.value:
            # A gate approach already owns a certified path through the bank
            # tail. Closing a released queue-slot hole must not rebuild that
            # path from the passenger's current position: doing so can send an
            # in-flight body back to the tail aisle. Keep the live prefix and
            # replace only its stale finite-slot terminal.
            route = _replace_effective_navigation_terminal(
                passenger,
                new_target,
            )
        else:
            route = tuple(
                model.route_to_facility_queue_slot(
                    passenger,
                    facility,
                    new_index,
                )
            )
        points = route or (new_target,)
        if any(
            not isfinite(float(coordinate))
            for point in points
            for coordinate in point
        ) or hypot(
            points[-1][0] - new_target[0],
            points[-1][1] - new_target[1],
        ) > 1e-6:
            return False
        prepared_navigation.append(
            _PreparedNavigation(
                passenger=passenger,
                points=points,
                expected_terminal=new_target,
                goal=_effective_navigation_goal(
                    passenger,
                    fallback=passenger.current_goal,
                ),
            )
        )

    fifo_passenger_ids = tuple(int(passenger.unique_id) for passenger in passengers)
    prepared_queue = facility.queue.prepare_approach_rebalance(
        proposed_slot_by_passenger_id,
        fifo_passenger_ids,
    )
    ownership_snapshot = {
        (int(passenger.unique_id), stage): model._facility_approach_reservation_registry[
            (int(passenger.unique_id), stage)
        ]
        for passenger in passengers
    }
    try:
        facility.queue.apply_approach_rebalance(prepared_queue)
        for passenger in passengers:
            passenger_id = int(passenger.unique_id)
            new_index = proposed_slot_by_passenger_id[passenger_id]
            assigned[passenger_id] = new_index
            passenger.facility_approach_slots_by_stage[stage] = new_index
            key = (passenger_id, stage)
            model._facility_approach_reservation_registry[key] = replace(
                ownership_snapshot[key],
                slot_index=new_index,
            )
        for prepared in prepared_navigation:
            prepared.passenger.set_route(
                prepared.points,
                goal_kind=prepared.goal.kind,
                goal_label=prepared.goal.label,
                facility_id=prepared.goal.facility_id,
                stage=prepared.goal.stage,
            )
        _assert_rebalance_committed(
            model,
            facility,
            passengers,
            stage,
            proposed_slot_by_passenger_id,
            prepared_navigation,
        )
    except Exception:
        for snapshot in navigation_snapshots:
            _restore_navigation_snapshot(snapshot)
        for passenger in passengers:
            passenger_id = int(passenger.unique_id)
            old_index = previous_slot_by_passenger_id[passenger_id]
            assigned[passenger_id] = old_index
            passenger.facility_approach_slots_by_stage[stage] = old_index
            key = (passenger_id, stage)
            model._facility_approach_reservation_registry[key] = ownership_snapshot[key]
        facility.queue.restore_approach_reservation_state(reservation_state)
        raise
    return True


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
    previous_slot_by_passenger_id = {
        int(passenger.unique_id): int(assigned[int(passenger.unique_id)])
        for passenger in passengers
    }
    if len(set(slot_indices)) != len(passengers):
        raise RuntimeError(
            f"facility {facility_id!r} has duplicate simultaneous approach slots"
        )
    slot_positions = [
        model._facility_approach_slot_position(facility, index)
        for index in slot_indices
    ]
    costs = [
        [
            hypot(passenger.pos[0] - slot[0], passenger.pos[1] - slot[1])
            for slot in slot_positions
        ]
        for passenger in passengers
    ]
    column_by_row = _minimum_cost_assignment(costs)
    proposed_slot_by_passenger_id = {
        int(passenger.unique_id): slot_indices[column]
        for passenger, column in zip(passengers, column_by_row, strict=True)
    }
    for passenger in passengers:
        passenger_id = int(passenger.unique_id)
        key = (passenger_id, stage)
        ownership = model._facility_approach_reservation_registry.get(key)
        old_index = previous_slot_by_passenger_id[passenger_id]
        if (
            passenger.facility_approach_slots_by_stage.get(stage) != old_index
            or facility.queue.approach_slot_reservation(passenger_id) != old_index
            or ownership is None
            or int(ownership.slot_index) != old_index
        ):
            raise RuntimeError(
                f"facility {facility_id!r} approach reservation mirrors disagree "
                f"for passenger {passenger_id}"
            )

    fifo_passenger_ids = tuple(
        passenger_id
        for passenger_id, _slot_index in sorted(
            proposed_slot_by_passenger_id.items(),
            key=lambda item: (item[1], item[0]),
        )
    )
    prepared_queue = facility.queue.prepare_approach_rebalance(
        proposed_slot_by_passenger_id,
        fifo_passenger_ids,
    )

    # Earlier members of the same spawn cohort may already hold a walking
    # command built from the pre-balanced reservation.  This includes the
    # WALK_TO_REGION command that physically targets a reserved queue slot
    # before the Goal Graph emits WALK_TO_QUEUE.  Retarget every command whose
    # route still terminates at its old owned slot, while preserving its
    # strategic goal semantics.
    prepared_navigation: list[_PreparedNavigation] = []
    navigation_snapshots = tuple(
        _navigation_snapshot(passenger) for passenger in passengers
    )
    for passenger in passengers:
        goal = passenger.current_goal
        passenger_id = int(passenger.unique_id)
        old_index = previous_slot_by_passenger_id[passenger_id]
        new_index = proposed_slot_by_passenger_id[passenger_id]
        if old_index == new_index:
            continue
        old_target = model._facility_approach_slot_position(facility, old_index)
        new_target = model._facility_approach_slot_position(facility, new_index)
        route_terminal = _effective_navigation_terminal(passenger)
        owns_old_terminal = hypot(
            route_terminal[0] - old_target[0],
            route_terminal[1] - old_target[1],
        ) <= 1e-6
        already_at_new_target = hypot(
            passenger.pos[0] - new_target[0],
            passenger.pos[1] - new_target[1],
        ) <= 1e-6
        if not owns_old_terminal and not already_at_new_target:
            # This reservation is not the authority for the passenger's
            # current navigation command.  Changing only its slot mirror
            # would create a durable split-brain state (reservation=N while
            # movement still terminates at M), so leave the whole cohort's
            # FIFO assignment unchanged.
            return
        route = (
            ()
            if already_at_new_target and not owns_old_terminal
            else tuple(
                model.route_to_facility_queue_slot(
                    passenger,
                    facility,
                    new_index,
                )
            )
        )
        points = route or (new_target,)
        if any(
            not isfinite(float(coordinate))
            for point in points
            for coordinate in point
        ):
            raise RuntimeError(
                f"facility {facility_id!r} rebalance route contains non-finite coordinates"
            )
        if hypot(
            points[-1][0] - new_target[0],
            points[-1][1] - new_target[1],
        ) > 1e-6:
            raise RuntimeError(
                f"facility {facility_id!r} rebalance route does not terminate at "
                f"compiled slot {new_index}"
            )
        prepared_navigation.append(
            _PreparedNavigation(
                passenger=passenger,
                points=points,
                expected_terminal=new_target,
                goal=_effective_navigation_goal(passenger, fallback=goal),
            )
        )

    queue_snapshot = facility.queue.approach_reservation_state()
    ownership_snapshot = {
        (int(passenger.unique_id), stage):
        model._facility_approach_reservation_registry[
            (int(passenger.unique_id), stage)
        ]
        for passenger in passengers
    }
    try:
        facility.queue.apply_approach_rebalance(prepared_queue)
        for passenger in passengers:
            passenger_id = int(passenger.unique_id)
            new_index = proposed_slot_by_passenger_id[passenger_id]
            assigned[passenger_id] = new_index
            passenger.facility_approach_slots_by_stage[stage] = new_index
            key = (passenger_id, stage)
            model._facility_approach_reservation_registry[key] = replace(
                ownership_snapshot[key],
                slot_index=new_index,
            )
        for prepared in prepared_navigation:
            prepared.passenger.set_route(
                prepared.points,
                goal_kind=prepared.goal.kind,
                goal_label=prepared.goal.label,
                facility_id=prepared.goal.facility_id,
                stage=prepared.goal.stage,
            )
        _assert_rebalance_committed(
            model,
            facility,
            passengers,
            stage,
            proposed_slot_by_passenger_id,
            prepared_navigation,
        )
    except Exception:
        for snapshot in navigation_snapshots:
            _restore_navigation_snapshot(snapshot)
        for passenger in passengers:
            passenger_id = int(passenger.unique_id)
            old_index = previous_slot_by_passenger_id[passenger_id]
            assigned[passenger_id] = old_index
            passenger.facility_approach_slots_by_stage[stage] = old_index
            key = (passenger_id, stage)
            model._facility_approach_reservation_registry[key] = ownership_snapshot[key]
        facility.queue.restore_approach_reservation_state(queue_snapshot)
        raise


def _navigation_snapshot(passenger) -> _NavigationSnapshot:
    return _NavigationSnapshot(
        passenger=passenger,
        target=tuple(passenger.target),
        route=tuple(passenger.route),
        route_segment_start=tuple(passenger.route_segment_start),
        pending_route_transition=passenger._pending_route_transition,
        corner_recovery_anchor=passenger.corner_recovery_anchor,
        corner_recovery_speed_limit_mps=passenger.corner_recovery_speed_limit_mps,
        goal=passenger.current_goal,
    )


def _restore_navigation_snapshot(snapshot: _NavigationSnapshot) -> None:
    passenger = snapshot.passenger
    passenger.target = snapshot.target
    passenger.route = list(snapshot.route)
    passenger.route_segment_start = snapshot.route_segment_start
    passenger._pending_route_transition = snapshot.pending_route_transition
    passenger.corner_recovery_anchor = snapshot.corner_recovery_anchor
    passenger.corner_recovery_speed_limit_mps = (
        snapshot.corner_recovery_speed_limit_mps
    )
    passenger.plan.current_goal = snapshot.goal


def _effective_navigation_terminal(passenger) -> tuple[float, float]:
    pending = passenger._pending_route_transition
    if pending is not None and pending[0]:
        return tuple(pending[0][-1])
    if passenger.route:
        return tuple(passenger.route[-1])
    return tuple(passenger.target)


def _replace_effective_navigation_terminal(
    passenger,
    new_target: tuple[float, float],
) -> tuple[tuple[float, float], ...]:
    pending = passenger._pending_route_transition
    if pending is not None and pending[0]:
        points = tuple(tuple(point) for point in pending[0])
    else:
        points = (tuple(passenger.target), *(tuple(point) for point in passenger.route))
    return (*points[:-1], tuple(new_target))


def _effective_navigation_goal(passenger, *, fallback) -> AgentGoal:
    pending = passenger._pending_route_transition
    if pending is None:
        return fallback
    _route, kind, label, facility_id, stage = pending
    return AgentGoal(
        kind=str(kind),
        label=str(label),
        facility_id=facility_id,
        stage=(
            stage.value
            if isinstance(stage, FacilityStage)
            else None
            if stage is None
            else str(stage)
        ),
    )


def _assert_rebalance_committed(
    model,
    facility,
    passengers,
    stage: str,
    proposed_slot_by_passenger_id: dict[int, int],
    prepared_navigation: list[_PreparedNavigation],
) -> None:
    for passenger in passengers:
        passenger_id = int(passenger.unique_id)
        expected = proposed_slot_by_passenger_id[passenger_id]
        ownership = model._facility_approach_reservation_registry[
            (passenger_id, stage)
        ]
        mirrors = (
            model._facility_targeting_slot_indices[facility.facility_id][passenger_id],
            passenger.facility_approach_slots_by_stage[stage],
            facility.queue.approach_slot_reservation(passenger_id),
            int(ownership.slot_index),
        )
        if any(value != expected for value in mirrors):
            raise RuntimeError(
                f"facility {facility.facility_id!r} approach rebalance committed "
                f"inconsistent mirrors for passenger {passenger_id}"
            )
    for prepared in prepared_navigation:
        terminal = _effective_navigation_terminal(prepared.passenger)
        if hypot(
            terminal[0] - prepared.expected_terminal[0],
            terminal[1] - prepared.expected_terminal[1],
        ) > 1e-6:
            raise RuntimeError(
                f"passenger {prepared.passenger.unique_id} navigation did not commit "
                "the rebalanced approach slot"
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
