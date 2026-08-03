from __future__ import annotations

from math import hypot
from typing import TYPE_CHECKING, Protocol, overload

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent


Point = tuple[float, float]


class QueueLayoutLike(Protocol):
    def slot(self, index: int) -> Point: ...


class FacilityQueue(list):
    """Queue collection with capacity and layout behavior for facility agents."""

    def __init__(
        self,
        layout: QueueLayoutLike,
        *,
        max_length: int | None = None,
        ordered: bool = True,
        reaction_seconds: float = 1.0,
    ) -> None:
        super().__init__()
        self.layout = layout
        self.max_length = max_length
        self.ordered = ordered
        self.reaction_seconds = max(0.0, float(reaction_seconds))
        self._joined_time_seconds_by_passenger_id: dict[int, float] = {}
        self._assigned_slot_index_by_passenger_id: dict[int, int] = {}
        self._priority_by_passenger_id: dict[int, int] = {}
        self._reserved_slot_index_by_unique_id: dict[int, int] = {}
        self._reservation_priority_by_unique_id: dict[int, int] = {}
        self._last_layout_motion_by_passenger_id: dict[int, Point] = {}
        self._direction_change_ready_time_by_passenger_id: dict[int, float] = {}
        self._next_priority = 0
        self._service_handoff_passenger_id: int | None = None

    def join(
        self,
        passenger: PassengerAgent,
        *,
        settle: bool = False,
        preferred_slot_index: int | None = None,
    ) -> bool:
        if passenger in self:
            return True
        if self.is_full:
            return False
        passenger_id = id(passenger)
        unique_id = int(getattr(passenger, "unique_id", passenger_id))
        priority = self._reservation_priority_by_unique_id.get(unique_id)
        if priority is None:
            priority = self._allocate_priority()

        # A physical portal reservation is also a FIFO reservation.  A later
        # arrival must wait outside the queue while an earlier reservation is
        # still approaching; otherwise a recycled standing-slot index can let
        # it overtake the earlier passenger.
        if settle and any(
            other_unique_id != unique_id and other_priority < priority
            for other_unique_id, other_priority in self._reservation_priority_by_unique_id.items()
        ):
            return False
        if settle and not self._append_preserves_physical_order(passenger, priority):
            return False

        super().append(passenger)
        nearest_slot_index = self._nearest_explicit_slot_index(passenger)
        assigned_slot_index = (
            nearest_slot_index
            if preferred_slot_index is None
            else max(0, int(preferred_slot_index))
        )
        self._assigned_slot_index_by_passenger_id[passenger_id] = assigned_slot_index
        self._priority_by_passenger_id[passenger_id] = priority
        super().sort(key=lambda item: self._priority_by_passenger_id[id(item)])
        if settle:
            model = passenger.model
            self._joined_time_seconds_by_passenger_id[id(passenger)] = float(
                model.current_time_seconds
            ) + float(
                model.scenario.tick_seconds
            )
        return True

    def pop_ready(self) -> PassengerAgent | None:
        if not self:
            return None
        return self.pop(0)

    def remove(self, passenger: PassengerAgent) -> None:
        super().remove(passenger)
        self._joined_time_seconds_by_passenger_id.pop(id(passenger), None)
        self._assigned_slot_index_by_passenger_id.pop(id(passenger), None)
        self._priority_by_passenger_id.pop(id(passenger), None)
        self._last_layout_motion_by_passenger_id.pop(id(passenger), None)
        self._direction_change_ready_time_by_passenger_id.pop(id(passenger), None)

    def discard(self, passenger: PassengerAgent) -> bool:
        try:
            self.remove(passenger)
        except ValueError:
            return False
        return True

    def layout_positions(
        self,
        *,
        speed: float,
        goal_label: str,
        facility_id: str,
        stage: str,
        external_occupied_positions: tuple[Point, ...] = (),
        slot_index_offset: int = 0,
    ) -> None:
        # Queue compaction shares physical space with bodies that may already
        # be inside a facility (for example, a rider paused at a connector
        # entry).  Keeping those bodies in the same collision set prevents the
        # queue head from being tidied onto an occupied service position.
        occupied_positions: list[Point] = list(external_occupied_positions)
        reserved_motion_positions: list[Point] = []
        processed_passenger_ids: set[int] = set()
        # Admission and tactical slot reservation must prevent co-location.
        # A continuous swept-clear solver cannot legitimately move two bodies
        # apart from distance zero, so fail closed instead of inventing a
        # collision-free fan-out after the invalid state was already recorded.
        if self._has_current_overlap():
            raise RuntimeError("queue layout input contains co-located bodies")
        indexed_passengers = list(enumerate(self))
        for index, passenger in indexed_passengers:
            unprocessed_positions = [
                other.pos
                for other in self
                if other is not passenger and id(other) not in processed_passenger_ids
            ]
            collision_positions = [
                *occupied_positions,
                *reserved_motion_positions,
                *unprocessed_positions,
            ]
            desired_index = index + max(0, int(slot_index_offset))
            assigned_index = self._next_assigned_slot_index(passenger, desired_index)
            slot = self._safe_slot_for(passenger, assigned_index)
            passenger.set_target(
                slot,
                goal_kind="queued",
                goal_label=goal_label,
                facility_id=facility_id,
                stage=stage,
            )
            min_clearance = _passenger_layout_min_clearance(passenger)
            motion_fraction = self.settling_motion_fraction(passenger)
            if motion_fraction <= 0.0:
                # A person who has just reached a queue needs one complete
                # reaction interval before reversing into a serpentine tail
                # or compacting toward the service point.  Without this
                # physical dwell, one coarse process tick can contain both
                # the inbound walking segment and a full-speed outbound queue
                # segment, producing an impossible instantaneous U-turn.
                occupied_positions.append(passenger.pos)
                reserved_motion_positions.extend(
                    _segment_samples(
                        passenger.pos,
                        slot,
                        maximum_step=max(0.02, min_clearance * 0.2),
                    )
                )
                processed_passenger_ids.add(id(passenger))
                continue
            motion_fraction *= self._direction_change_motion_fraction(passenger, slot)
            if motion_fraction <= 0.0:
                occupied_positions.append(passenger.pos)
                reserved_motion_positions.extend(
                    _segment_samples(
                        passenger.pos,
                        slot,
                        maximum_step=max(0.02, min_clearance * 0.2),
                    )
                )
                processed_passenger_ids.add(id(passenger))
                continue
            layout_speed = self._layout_speed_for(
                passenger,
                index,
                slot,
                speed,
                collision_positions,
                min_clearance,
            ) * motion_fraction
            position_before = passenger.pos
            passenger.move_directly_toward_target(
                layout_speed,
                occupied_positions=collision_positions,
                min_clearance=min_clearance,
            )
            actual_motion = (
                passenger.pos[0] - position_before[0],
                passenger.pos[1] - position_before[1],
            )
            if hypot(actual_motion[0], actual_motion[1]) > 1e-6:
                self._last_layout_motion_by_passenger_id[id(passenger)] = actual_motion
            occupied_positions.append(passenger.pos)
            reserved_motion_positions.extend(
                _segment_samples(
                    passenger.pos,
                    slot,
                    maximum_step=max(0.02, min_clearance * 0.2),
                )
            )
            processed_passenger_ids.add(id(passenger))

    @property
    def persons(self) -> int:
        return sum(passenger.group_size for passenger in self)

    @property
    def is_full(self) -> bool:
        return self.max_length is not None and len(self) >= self.max_length

    @property
    def occupied_slot_indices(self) -> tuple[int, ...]:
        """Physical and FIFO slots currently claimed by queue occupants."""

        claimed = set(range(len(self)))
        claimed.update(
            int(index)
            for passenger in self
            if (
                index := self._assigned_slot_index_by_passenger_id.get(id(passenger))
            )
            is not None
        )
        claimed.update(self._reserved_slot_index_by_unique_id.values())
        return tuple(sorted(claimed))

    def reserve_approach_slot(self, passenger_unique_id: int, slot_index: int) -> None:
        unique_id = int(passenger_unique_id)
        self._reserved_slot_index_by_unique_id[unique_id] = max(
            0,
            int(slot_index),
        )
        if unique_id not in self._reservation_priority_by_unique_id:
            self._reservation_priority_by_unique_id[unique_id] = self._allocate_priority()

    def reorder_approach_reservation_cohort(
        self,
        passenger_unique_ids: tuple[int, ...],
    ) -> None:
        """Align one simultaneous cohort's FIFO order with its physical slots.

        The method only permutes priorities already owned by the supplied
        passengers.  Earlier reservations therefore remain earlier, while a
        same-interval cohort can approach a one-body-wide queue without
        crossing or waiting for an ID-ordered passenger parked at its tail.
        """

        unique_ids = tuple(int(value) for value in passenger_unique_ids)
        if len(set(unique_ids)) != len(unique_ids):
            raise ValueError("approach reservation cohort contains duplicate passengers")
        if any(
            unique_id not in self._reserved_slot_index_by_unique_id
            or unique_id not in self._reservation_priority_by_unique_id
            for unique_id in unique_ids
        ):
            raise ValueError("approach reservation cohort must already own every slot")
        priorities = sorted(
            self._reservation_priority_by_unique_id[unique_id]
            for unique_id in unique_ids
        )
        for unique_id, priority in zip(unique_ids, priorities, strict=True):
            self._reservation_priority_by_unique_id[unique_id] = priority

    def approach_slot_reservation(self, passenger_unique_id: int) -> int | None:
        """Return the physical approach slot reserved by one passenger.

        Routing deliberately verifies this queue-owned copy against its other
        reservation records before treating an approach target as durable.
        """

        return self._reserved_slot_index_by_unique_id.get(int(passenger_unique_id))

    @property
    def approach_slot_reservations(self) -> tuple[tuple[int, int], ...]:
        """Expose an immutable snapshot for consistency checks/invalidation."""

        return tuple(sorted(self._reserved_slot_index_by_unique_id.items()))

    def clear_approach_slot_reservations(self) -> tuple[int, ...]:
        """Atomically release every pending physical/FIFO approach claim."""

        passenger_ids = tuple(sorted(self._reserved_slot_index_by_unique_id))
        self._reserved_slot_index_by_unique_id.clear()
        self._reservation_priority_by_unique_id.clear()
        return passenger_ids

    def release_approach_slot(self, passenger_unique_id: int) -> None:
        unique_id = int(passenger_unique_id)
        self._reserved_slot_index_by_unique_id.pop(unique_id, None)
        self._reservation_priority_by_unique_id.pop(unique_id, None)

    def append(self, passenger: PassengerAgent) -> None:
        if not self.join(passenger):
            raise OverflowError("facility queue is full")

    def insert(self, index: int, passenger: PassengerAgent) -> None:
        if passenger in self:
            super().remove(passenger)
        elif self.is_full:
            raise OverflowError("facility queue is full")
        super().insert(index, passenger)
        self._assigned_slot_index_by_passenger_id.setdefault(
            id(passenger),
            self._nearest_explicit_slot_index(passenger),
        )
        if id(passenger) not in self._priority_by_passenger_id:
            before = self[index - 1] if index > 0 else None
            after = self[index + 1] if index + 1 < len(self) else None
            before_priority = (
                self._priority_by_passenger_id.get(id(before), -2)
                if before is not None
                else -2
            )
            after_priority = (
                self._priority_by_passenger_id.get(id(after), before_priority + 2)
                if after is not None
                else before_priority + 2
            )
            self._priority_by_passenger_id[id(passenger)] = (
                before_priority + after_priority
            ) // 2

    def is_settling(self, passenger: PassengerAgent) -> bool:
        return self.settling_motion_fraction(passenger) <= 0.0

    def settling_motion_fraction(self, passenger: PassengerAgent) -> float:
        joined_time_seconds = self._joined_time_seconds_by_passenger_id.get(id(passenger))
        if joined_time_seconds is None:
            return 1.0
        # Queue joins happen after the walking phase, at the end of the current
        # process interval.  Express the reaction dwell in physical seconds so
        # timestep refinement does not change passenger behavior.  If the dwell
        # expires inside a coarse legacy tick, expose only the remaining motion
        # fraction instead of rounding the reaction up to the whole tick.
        interval_start = float(passenger.model.current_time_seconds)
        tick_seconds = float(passenger.model.scenario.tick_seconds)
        interval_end = interval_start + tick_seconds
        reaction_end = joined_time_seconds + self.reaction_seconds
        if reaction_end >= interval_end - 1e-9:
            return 0.0
        if reaction_end <= interval_start + 1e-9:
            return 1.0
        return max(0.0, min(1.0, (interval_end - reaction_end) / tick_seconds))

    def _has_current_overlap(self) -> bool:
        for left_index, left in enumerate(self):
            left_clearance = _passenger_layout_min_clearance(left)
            for right in self[left_index + 1 :]:
                clearance = max(left_clearance, _passenger_layout_min_clearance(right))
                collapsed_anchor_tolerance = min(0.05, clearance * 0.25)
                if hypot(
                    left.pos[0] - right.pos[0],
                    left.pos[1] - right.pos[1],
                ) < collapsed_anchor_tolerance:
                    return True
        return False

    def _allocate_priority(self) -> int:
        priority = self._next_priority
        self._next_priority += 1
        return priority

    def _append_preserves_physical_order(
        self,
        passenger: PassengerAgent,
        priority: int,
    ) -> bool:
        """Reject a join that cannot compact on a one-body-wide slot chain.

        Queue layout movement deliberately has no teleport or overlap recovery.
        Therefore the FIFO order and the physical order along the slot polyline
        must agree at admission time.  A rejected passenger remains in the
        tactical approach state and can retry after the queue advances.
        """

        if not self:
            return True
        ordered = [
            (
                self._queue_path_progress(item.pos),
                item,
                self._priority_by_passenger_id[id(item)],
            )
            for item in self
        ]
        ordered.append((self._queue_path_progress(passenger.pos), passenger, priority))
        ordered.sort(key=lambda record: record[2])
        for left, right in zip(ordered, ordered[1:]):
            left_progress, left_passenger, _left_priority = left
            right_progress, right_passenger, _right_priority = right
            left_position = left_passenger.pos
            right_position = right_passenger.pos
            clearance = max(
                _passenger_layout_min_clearance(left_passenger),
                _passenger_layout_min_clearance(right_passenger),
            )
            if right_progress + 1e-6 < left_progress:
                return False
            if hypot(
                left_position[0] - right_position[0],
                left_position[1] - right_position[1],
            ) < clearance - 1e-6:
                return False
        return True

    def _queue_path_progress(self, position: Point) -> float:
        slots = tuple(getattr(self.layout, "slots", ()))
        if len(slots) < 2:
            return hypot(position[0] - self.layout.slot(0)[0], position[1] - self.layout.slot(0)[1])
        best_distance = float("inf")
        best_progress = 0.0
        prefix = 0.0
        for start, end in zip(slots, slots[1:]):
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            segment_length = hypot(dx, dy)
            if segment_length <= 1e-9:
                continue
            ratio = max(
                0.0,
                min(
                    1.0,
                    ((position[0] - start[0]) * dx + (position[1] - start[1]) * dy)
                    / (segment_length * segment_length),
                ),
            )
            projected = (start[0] + dx * ratio, start[1] + dy * ratio)
            distance = hypot(position[0] - projected[0], position[1] - projected[1])
            progress = prefix + segment_length * ratio
            if (distance, progress) < (best_distance, best_progress):
                best_distance = distance
                best_progress = progress
            prefix += segment_length
        return best_progress

    @overload
    def __getitem__(self, index: int) -> PassengerAgent: ...

    @overload
    def __getitem__(self, index: slice) -> list[PassengerAgent]: ...

    def __getitem__(self, index: int | slice) -> PassengerAgent | list[PassengerAgent]:
        return super().__getitem__(index)

    def pop(self, index: int = -1) -> PassengerAgent:
        passenger = super().pop(index)
        if index == 0:
            self._service_handoff_passenger_id = id(passenger)
        self._joined_time_seconds_by_passenger_id.pop(id(passenger), None)
        self._assigned_slot_index_by_passenger_id.pop(id(passenger), None)
        self._priority_by_passenger_id.pop(id(passenger), None)
        self._last_layout_motion_by_passenger_id.pop(id(passenger), None)
        self._direction_change_ready_time_by_passenger_id.pop(id(passenger), None)
        return passenger

    def _direction_change_motion_fraction(
        self,
        passenger: PassengerAgent,
        slot: Point,
    ) -> float:
        """Apply a physical reaction dwell before reversing queue motion."""

        passenger_id = id(passenger)
        previous = self._last_layout_motion_by_passenger_id.get(passenger_id)
        desired = (slot[0] - passenger.pos[0], slot[1] - passenger.pos[1])
        if (
            previous is None
            or hypot(previous[0], previous[1]) <= 1e-6
            or hypot(desired[0], desired[1]) <= 1e-6
            or previous[0] * desired[0] + previous[1] * desired[1] >= 0.0
        ):
            self._direction_change_ready_time_by_passenger_id.pop(passenger_id, None)
            return 1.0

        model = passenger.model
        interval_start = float(model.current_time_seconds)
        tick_seconds = float(model.scenario.tick_seconds)
        interval_end = interval_start + tick_seconds
        ready_time = self._direction_change_ready_time_by_passenger_id.get(passenger_id)
        if ready_time is None:
            ready_time = interval_start + self.reaction_seconds
            self._direction_change_ready_time_by_passenger_id[passenger_id] = ready_time
        if ready_time >= interval_end - 1e-9:
            return 0.0
        if ready_time <= interval_start + 1e-9:
            self._direction_change_ready_time_by_passenger_id.pop(passenger_id, None)
            return 1.0
        return max(0.0, min(1.0, (interval_end - ready_time) / tick_seconds))

    def consume_service_handoff(self, passenger: PassengerAgent) -> bool:
        if self._service_handoff_passenger_id != id(passenger):
            return False
        self._service_handoff_passenger_id = None
        return True

    def as_list(self) -> list[PassengerAgent]:
        return list(self)

    def _safe_slot_for(self, passenger: PassengerAgent, index: int) -> Point:
        slot = self.layout.slot(index)
        projector = getattr(passenger, "_project_direct_layout_position", None)
        if callable(projector):
            return projector(slot)
        return slot

    def _nearest_explicit_slot_index(self, passenger: PassengerAgent) -> int:
        slots = tuple(getattr(self.layout, "slots", ()))
        if not slots:
            return max(0, len(self) - 1)
        return min(
            range(len(slots)),
            key=lambda index: hypot(
                passenger.pos[0] - slots[index][0],
                passenger.pos[1] - slots[index][1],
            ),
        )

    def _next_assigned_slot_index(
        self,
        passenger: PassengerAgent,
        desired_index: int,
    ) -> int:
        passenger_id = id(passenger)
        assigned = self._assigned_slot_index_by_passenger_id.get(
            passenger_id,
            desired_index,
        )
        assigned = max(0, int(assigned))
        assigned_slot = self._safe_slot_for(passenger, assigned)
        assigned_distance = hypot(
            passenger.pos[0] - assigned_slot[0],
            passenger.pos[1] - assigned_slot[1],
        )
        nearest = self._nearest_explicit_slot_index(passenger)
        nearest_slot = self._safe_slot_for(passenger, nearest)
        nearest_distance = hypot(
            passenger.pos[0] - nearest_slot[0],
            passenger.pos[1] - nearest_slot[1],
        )
        if nearest_distance <= 0.12 < assigned_distance:
            assigned = nearest
            assigned_distance = nearest_distance
        at_assigned_slot = assigned_distance <= 0.12
        proposed_index = assigned
        if assigned < desired_index:
            # A newly appended follower can be geometrically nearer the
            # occupied head slot (including an exact distance tie).  Its FIFO
            # destination is nevertheless tailward, so it must be allowed to
            # target the adjacent free slot without first reaching the head.
            proposed_index = assigned + 1
        elif at_assigned_slot and assigned > desired_index:
            proposed_index = assigned - 1
        if not self._slot_claimed_by_other(passenger, proposed_index):
            assigned = proposed_index
        self._assigned_slot_index_by_passenger_id[passenger_id] = assigned
        return assigned

    def _slot_claimed_by_other(
        self,
        passenger: PassengerAgent,
        slot_index: int,
    ) -> bool:
        for other in self:
            if other is passenger:
                continue
            if self._assigned_slot_index_by_passenger_id.get(id(other)) == slot_index:
                return True
        for unique_id, reserved_index in self._reserved_slot_index_by_unique_id.items():
            if int(unique_id) == int(passenger.unique_id):
                continue
            if reserved_index == slot_index:
                return True
        return False

    def _layout_speed_for(
        self,
        passenger: PassengerAgent,
        index: int,
        slot: Point,
        speed: float,
        occupied_positions: list[Point],
        min_clearance: float,
    ) -> float:
        del passenger, index, slot, occupied_positions, min_clearance
        # Queue compaction is physical motion.  Overlap pressure must never
        # multiply a passenger's per-tick displacement merely to make a tidy
        # snapshot; distinct tactical approach portals prevent most overlaps.
        return speed

def _passenger_layout_min_clearance(passenger: PassengerAgent) -> float:
    method = getattr(passenger, "_direct_layout_min_clearance", None)
    if callable(method):
        return float(method())
    scenario = getattr(getattr(passenger, "model", None), "scenario", None)
    radius = float(getattr(scenario, "jupedsim_agent_radius_units", 0.18))
    multiplier = float(getattr(scenario, "jupedsim_clearance_multiplier", 2.2))
    return max(0.05, radius * multiplier)


def _segment_samples(start: Point, end: Point, *, maximum_step: float) -> tuple[Point, ...]:
    """Reserve a leader's remaining compaction sweep for following bodies."""

    distance = hypot(end[0] - start[0], end[1] - start[1])
    if distance <= 1e-9:
        return ()
    segment_count = max(1, int(distance / max(1e-6, maximum_step)) + 1)
    return tuple(
        (
            start[0] + (end[0] - start[0]) * index / segment_count,
            start[1] + (end[1] - start[1]) * index / segment_count,
        )
        for index in range(1, segment_count + 1)
    )
