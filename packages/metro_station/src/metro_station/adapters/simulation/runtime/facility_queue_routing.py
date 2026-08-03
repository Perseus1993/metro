from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot

from ..agents.passenger import PassengerAgent
from ..facilities.process import FacilityKind
from ..facilities.runtime import FacilityProcessAgent
from ..planning.plan import AgentIntent, AgentPlan, FacilityStage
from ..station.geometry import project_to_safe_point as project_to_safe_point
from .facility_queue_geometry import (
    FacilityQueueGeometryMixin,
    _ApproachProjectionContext as _ApproachProjectionContext,
)
from .approach_slot_assignment import rebalance_current_step_approach_slots
from .evacuation_journey_rerouting import reroot_evacuation_goal_runtime
from .passenger_goal_runtime import PassengerGoalRuntime


@dataclass(frozen=True)
class _FacilityApproachReservationOwnership:
    """Canonical owner record; subsystem maps below are verified projections."""

    passenger_id: int
    stage: str
    facility_id: str
    persons: int
    slot_index: int
    proof_revision: int
    reserved_step: int
    facility: object = field(compare=False, hash=False, repr=False)
    queue: object = field(compare=False, hash=False, repr=False)


class FacilityQueueRoutingMixin(FacilityQueueGeometryMixin):
    """Resolve facility goals, reservations, and safe queue-approach routes."""

    def plan_for_intent(self, intent) -> AgentPlan:
        return AgentPlan.for_intent(intent)

    def goal_runtime_for_intent(
        self,
        intent: str | AgentIntent,
    ) -> PassengerGoalRuntime:
        graph = self.goal_graph_catalog.graph_for_intent(intent)
        if graph is None:
            raise ValueError(f"Goal Graph catalog has no journey for intent {intent!r}")
        return PassengerGoalRuntime(graph)

    def evacuation_goal_runtime_from_position(
        self,
        passenger: PassengerAgent,
        *,
        station_interior: bool,
    ) -> PassengerGoalRuntime:
        """Re-root an alarm journey from the passenger's physical station state."""
        return reroot_evacuation_goal_runtime(
            self,
            passenger,
            station_interior=station_interior,
        )

    def _facilities_for_stage(self, stage: str | FacilityStage) -> list[FacilityProcessAgent]:
        stage_value = stage.value if isinstance(stage, FacilityStage) else str(stage)
        return [
            facility
            for facility in self.facilities
            if isinstance(facility, FacilityProcessAgent) and facility.spec.stage == stage_value
        ]

    def _passenger_reached_facility_queue_goal(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> bool:
        goal = passenger.current_goal
        if goal.facility_id != facility.facility_id or goal.stage != facility.spec.stage:
            return False
        if goal.kind != "queue_approach":
            return False
        if goal.target is None:
            return False
        target = (
            self._safe_facility_queue_approach_target(passenger, facility)
            if facility.spec.kind
            in {
                FacilityKind.ESCALATOR.value,
                FacilityKind.ELEVATOR.value,
                FacilityKind.STAIRS.value,
            }
            else goal.target
        )
        return hypot(passenger.pos[0] - target[0], passenger.pos[1] - target[1]) <= (
            self._facility_queue_capture_radius()
        )

    def _should_approach_before_queue(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> bool:
        if facility.spec.kind == FacilityKind.TRAIN_DOOR.value:
            return False
        if (
            facility.spec.kind == FacilityKind.GATE.value
            and facility.spec.stage != FacilityStage.ENTRY_GATE.value
        ):
            return False
        if facility.spec.kind not in {
            FacilityKind.GATE.value,
            FacilityKind.ESCALATOR.value,
            FacilityKind.ELEVATOR.value,
            FacilityKind.STAIRS.value,
        }:
            return False
        return not self._passenger_near_facility_queue(passenger, facility)

    def should_route_to_facility_queue(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> bool:
        return self._should_approach_before_queue(passenger, facility)

    def _passenger_near_facility_queue(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> bool:
        target = self._safe_facility_queue_approach_target(passenger, facility)
        return hypot(passenger.pos[0] - target[0], passenger.pos[1] - target[1]) <= (
            self._facility_queue_capture_radius()
        )

    def _facility_queue_capture_radius(self) -> float:
        return max(
            float(self.scenario.jupedsim_target_radius_units) * 1.5,
            float(getattr(self.scenario, "personal_space_units", 0.8)) * 0.75,
            0.65,
        )

    def _route_passenger_to_facility_queue(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> bool:
        route = self.route_to_facility_queue(passenger, facility)
        if not route:
            return False
        passenger.set_route(
            route,
            goal_kind="queue_approach",
            goal_label=f"{facility.spec.label} queue approach",
            facility_id=facility.facility_id,
            stage=facility.spec.stage,
        )
        return True

    def facility_targeting_persons(self, facility: FacilityProcessAgent) -> int:
        reservations = self._facility_targeting_reservations.get(facility.facility_id, {})
        return sum(int(persons) for persons in reservations.values())

    def invalidate_facility_approach_proofs(
        self,
        *,
        reason: str = "facility_approach_projection_changed",
    ) -> int:
        """Atomically revoke every claim derived from the old geometry proof.

        Approach reservations are intentionally represented in several
        subsystem-owned indexes.  A proof revision is global, so invalidation
        sweeps the union of every index instead of trusting any one of them to
        enumerate the others.  This also repairs interrupted/legacy writes
        without leaving phantom capacity or duplicate physical claims.
        """

        self._facility_approach_proof_revision += 1
        self._facility_approach_proof_cache.clear()
        active_passengers = tuple(self.active_passengers())
        active_by_id = {
            int(passenger.unique_id): passenger for passenger in active_passengers
        }
        affected_ids: set[int] = set()
        for reservation_index in (
            self._facility_targeting_reservations,
            self._facility_targeting_slot_indices,
            self._facility_targeting_proof_revisions,
        ):
            for reservations in reservation_index.values():
                affected_ids.update(int(passenger_id) for passenger_id in reservations)
        for (owner_passenger_id, owner_stage), ownership in (
            self._facility_approach_reservation_registry.items()
        ):
            passenger_id = int(owner_passenger_id)
            affected_ids.add(passenger_id)
            self._release_facility_approach_ownership_queue(
                passenger_id,
                owner_stage,
                ownership,
            )

        for facility in self.facilities:
            if not isinstance(facility, FacilityProcessAgent):
                continue
            affected_ids.update(
                int(passenger_id)
                for passenger_id, _slot_index in facility.queue.approach_slot_reservations
            )
            facility.queue.clear_approach_slot_reservations()

        for passenger in active_passengers:
            if (
                passenger.facility_approach_slots_by_stage
                or passenger.facility_approach_facility_ids_by_stage
            ):
                affected_ids.add(int(passenger.unique_id))
            passenger.facility_approach_slots_by_stage.clear()
            passenger.facility_approach_facility_ids_by_stage.clear()

        self._facility_targeting_reservations.clear()
        self._facility_targeting_slot_indices.clear()
        self._facility_targeting_proof_revisions.clear()
        self._facility_approach_reservation_registry.clear()

        replanned = 0
        replan_policy = getattr(
            getattr(self, "progress_monitor", None),
            "replan_policy",
            None,
        )
        if replan_policy is not None:
            for passenger_id in sorted(affected_ids):
                passenger = active_by_id.get(passenger_id)
                if passenger is None:
                    continue
                replanned += int(
                    replan_policy.replan(
                        self,
                        passenger,
                        reason=reason,
                        stalled_seconds=0.0,
                    )
                )
        return replanned

    def facility_has_reservable_approach_slot(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> bool:
        claimed_facility_id, stage_claim_is_corrupt = (
            self._passenger_stage_approach_claim_state(
                passenger,
                facility.spec.stage,
            )
        )
        if stage_claim_is_corrupt:
            self._clear_facility_targeting_reservation(
                passenger,
                facility.spec.stage,
                expected_facility_id=facility.facility_id,
            )
        elif claimed_facility_id == facility.facility_id:
            return True
        if facility.spec.queue_layout.slots:
            return bool(self._available_facility_approach_slot_indices(facility))
        reservations = self._facility_targeting_reservations.get(
            facility.facility_id,
            {},
        )
        capacity = facility.queue.max_length
        return capacity is None or len(facility.queue) + len(reservations) < capacity

    def _reserve_facility_approach_slot(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> int:
        stage_value = facility.spec.stage
        claimed_facility_id, stage_claim_is_corrupt = (
            self._passenger_stage_approach_claim_state(passenger, stage_value)
        )
        if claimed_facility_id == facility.facility_id and not stage_claim_is_corrupt:
            return passenger.facility_approach_slots_by_stage[stage_value]
        if claimed_facility_id is not None or stage_claim_is_corrupt:
            self._clear_facility_targeting_reservation(
                passenger,
                stage_value,
                expected_facility_id=facility.facility_id,
            )

        reservations = self._facility_targeting_reservations[facility.facility_id]
        if facility.spec.queue_layout.slots:
            available_indices = self._available_facility_approach_slot_indices(facility)
            if not available_indices:
                raise RuntimeError(
                    f"facility {facility.facility_id!r} has no reservable queue slot"
                )
            slot_index = available_indices[0]
        else:
            capacity = facility.queue.max_length
            if capacity is not None and len(facility.queue) + len(reservations) >= capacity:
                raise RuntimeError(
                    f"facility {facility.facility_id!r} has no reservable queue slot"
                )
            slot_index = len(facility.queue) + len(reservations)
        reservations[int(passenger.unique_id)] = int(passenger.group_size)
        self._facility_targeting_slot_indices[facility.facility_id][
            int(passenger.unique_id)
        ] = slot_index
        self._facility_targeting_proof_revisions[facility.facility_id][
            int(passenger.unique_id)
        ] = int(self._facility_approach_proof_revision)
        facility.queue.reserve_approach_slot(int(passenger.unique_id), slot_index)
        passenger.facility_approach_slots_by_stage[stage_value] = slot_index
        passenger.facility_approach_facility_ids_by_stage[stage_value] = facility.facility_id
        passenger_id = int(passenger.unique_id)
        self._facility_approach_reservation_registry[(passenger_id, stage_value)] = (
            _FacilityApproachReservationOwnership(
                passenger_id=passenger_id,
                stage=stage_value,
                facility_id=facility.facility_id,
                persons=int(passenger.group_size),
                slot_index=int(slot_index),
                proof_revision=int(self._facility_approach_proof_revision),
                reserved_step=int(self.step_index),
                facility=facility,
                queue=facility.queue,
            )
        )
        return passenger.facility_approach_slots_by_stage[stage_value]

    def _rebalance_current_step_approach_slots(self) -> None:
        rebalance_current_step_approach_slots(self)

    def _clear_facility_targeting_reservation(
        self,
        passenger: PassengerAgent,
        stage: str | FacilityStage,
        *,
        expected_facility_id: str | None = None,
    ) -> None:
        stage_value = stage.value if isinstance(stage, FacilityStage) else str(stage)
        mapped_facility_id = passenger.facility_approach_facility_ids_by_stage.get(
            stage_value
        )
        passenger_id = int(passenger.unique_id)
        ownership = self._facility_approach_reservation_registry.pop(
            (passenger_id, stage_value),
            None,
        )
        facility_ids = set(
            self._passenger_stage_approach_claim_facility_ids(
                passenger,
                stage_value,
            )
        )
        if ownership is not None:
            ownership_facility = self._facility_approach_ownership_facility(
                stage_value,
                ownership,
            )
            if ownership_facility is not None:
                facility_ids.add(ownership_facility.facility_id)
            self._release_facility_approach_ownership_queue(
                passenger_id,
                stage_value,
                ownership,
            )
        for facility_id in (expected_facility_id, mapped_facility_id):
            facility = self.facilities_by_id.get(facility_id)
            if (
                isinstance(facility, FacilityProcessAgent)
                and facility.spec.stage == stage_value
            ):
                facility_ids.add(facility.facility_id)
        for facility_id in self._facility_approach_unknown_facility_ids(passenger_id):
            facility_ids.add(facility_id)
        for facility_id in facility_ids:
            reservations = self._facility_targeting_reservations.get(facility_id)
            if reservations is not None:
                reservations.pop(passenger_id, None)
            slot_indices = self._facility_targeting_slot_indices.get(facility_id)
            if slot_indices is not None:
                slot_indices.pop(passenger_id, None)
            revisions = self._facility_targeting_proof_revisions.get(facility_id)
            if revisions is not None:
                revisions.pop(passenger_id, None)
            facility = self.facilities_by_id.get(facility_id)
            if isinstance(facility, FacilityProcessAgent):
                facility.queue.release_approach_slot(passenger_id)
        passenger.facility_approach_slots_by_stage.pop(stage_value, None)
        passenger.facility_approach_facility_ids_by_stage.pop(stage_value, None)

    def _clear_all_facility_targeting_reservations(
        self,
        passenger: PassengerAgent,
    ) -> None:
        """Release every approach claim owned by a terminal passenger."""

        passenger_id = int(passenger.unique_id)
        stages = set(passenger.facility_approach_slots_by_stage)
        stages.update(passenger.facility_approach_facility_ids_by_stage)
        stages.update(
            stage
            for owner_passenger_id, stage in self._facility_approach_reservation_registry
            if int(owner_passenger_id) == passenger_id
        )
        for facility in self.facilities:
            if not isinstance(facility, FacilityProcessAgent):
                continue
            facility_id = facility.facility_id
            if (
                passenger_id
                in self._facility_targeting_reservations.get(facility_id, {})
                or passenger_id
                in self._facility_targeting_slot_indices.get(facility_id, {})
                or passenger_id
                in self._facility_targeting_proof_revisions.get(facility_id, {})
                or facility.queue.approach_slot_reservation(passenger_id) is not None
            ):
                stages.add(facility.spec.stage)
        for stage in sorted(stages):
            self._clear_facility_targeting_reservation(passenger, stage)

        # Unknown catalog keys have no stage to classify.  They can never be
        # valid ownership records, so terminal cleanup removes them by owner.
        for reservation_index in (
            self._facility_targeting_reservations,
            self._facility_targeting_slot_indices,
            self._facility_targeting_proof_revisions,
        ):
            for reservations in reservation_index.values():
                reservations.pop(passenger_id, None)
        for owner_key, ownership in tuple(
            self._facility_approach_reservation_registry.items()
        ):
            if int(owner_key[0]) != passenger_id:
                continue
            self._release_facility_approach_ownership_queue(
                passenger_id,
                owner_key[1],
                ownership,
            )
            self._facility_approach_reservation_registry.pop(owner_key, None)
        for facility in self.facilities:
            if isinstance(facility, FacilityProcessAgent):
                facility.queue.release_approach_slot(passenger_id)
        passenger.facility_approach_slots_by_stage.clear()
        passenger.facility_approach_facility_ids_by_stage.clear()

    def _facility_approach_ownership_facility(
        self,
        owner_stage: str,
        ownership: object,
    ) -> FacilityProcessAgent | None:
        """Resolve the facility handle using the registry key's stage."""

        facility = getattr(ownership, "facility", None)
        if not isinstance(facility, FacilityProcessAgent):
            return None
        if facility.spec.stage != str(owner_stage):
            return None
        return facility

    def _release_facility_approach_ownership_queue(
        self,
        owner_passenger_id: int,
        owner_stage: str,
        ownership: object,
    ) -> None:
        queues: list[object] = []
        facility = self._facility_approach_ownership_facility(
            owner_stage,
            ownership,
        )
        if facility is not None:
            queues.append(facility.queue)

        record_queue = getattr(ownership, "queue", None)
        release = getattr(record_queue, "release_approach_slot", None)
        if callable(release):
            current_queue_owner = next(
                (
                    candidate
                    for candidate in self.facilities
                    if isinstance(candidate, FacilityProcessAgent)
                    and candidate.queue is record_queue
                ),
                None,
            )
            if (
                current_queue_owner is None
                or current_queue_owner.spec.stage == str(owner_stage)
            ):
                queues.append(record_queue)

        released_queue_ids: set[int] = set()
        for queue in queues:
            if id(queue) in released_queue_ids:
                continue
            queue.release_approach_slot(int(owner_passenger_id))
            released_queue_ids.add(id(queue))

    def _facility_approach_unknown_facility_ids(
        self,
        passenger_id: int,
    ) -> tuple[str, ...]:
        facility_ids: set[str] = set()
        for reservation_index in (
            self._facility_targeting_reservations,
            self._facility_targeting_slot_indices,
            self._facility_targeting_proof_revisions,
        ):
            for facility_id, reservations in reservation_index.items():
                if int(passenger_id) not in reservations:
                    continue
                facility = self.facilities_by_id.get(facility_id)
                if not isinstance(facility, FacilityProcessAgent):
                    facility_ids.add(facility_id)
        return tuple(sorted(facility_ids))

    def _passenger_stage_approach_claim_facility_ids(
        self,
        passenger: PassengerAgent,
        stage: str | FacilityStage,
    ) -> tuple[str, ...]:
        """Discover every real facility claiming a passenger for one stage."""

        stage_value = stage.value if isinstance(stage, FacilityStage) else str(stage)
        passenger_id = int(passenger.unique_id)
        facility_ids: set[str] = set()
        ownership = self._facility_approach_reservation_registry.get(
            (passenger_id, stage_value)
        )
        if ownership is not None:
            ownership_facility = self._facility_approach_ownership_facility(
                stage_value,
                ownership,
            )
            if ownership_facility is not None:
                facility_ids.add(ownership_facility.facility_id)
        for facility in self.facilities:
            if (
                not isinstance(facility, FacilityProcessAgent)
                or facility.spec.stage != stage_value
            ):
                continue
            facility_id = facility.facility_id
            if (
                passenger_id
                in self._facility_targeting_reservations.get(facility_id, {})
                or passenger_id
                in self._facility_targeting_slot_indices.get(facility_id, {})
                or passenger_id
                in self._facility_targeting_proof_revisions.get(facility_id, {})
                or facility.queue.approach_slot_reservation(passenger_id) is not None
            ):
                facility_ids.add(facility_id)

        mapped_facility_id = passenger.facility_approach_facility_ids_by_stage.get(
            stage_value
        )
        mapped_facility = self.facilities_by_id.get(mapped_facility_id)
        if (
            isinstance(mapped_facility, FacilityProcessAgent)
            and mapped_facility.spec.stage == stage_value
        ):
            facility_ids.add(mapped_facility.facility_id)
        return tuple(sorted(facility_ids))

    def _passenger_stage_approach_claim_state(
        self,
        passenger: PassengerAgent,
        stage: str | FacilityStage,
    ) -> tuple[str | None, bool]:
        """Classify a stage claim as absent, uniquely valid, or corrupt."""

        stage_value = stage.value if isinstance(stage, FacilityStage) else str(stage)
        facility_ids = self._passenger_stage_approach_claim_facility_ids(
            passenger,
            stage_value,
        )
        if self._facility_approach_unknown_facility_ids(int(passenger.unique_id)):
            return (facility_ids[0] if len(facility_ids) == 1 else None, True)
        has_passenger_slot = stage_value in passenger.facility_approach_slots_by_stage
        has_passenger_facility = (
            stage_value in passenger.facility_approach_facility_ids_by_stage
        )
        mapped_facility_id = passenger.facility_approach_facility_ids_by_stage.get(
            stage_value
        )
        mapped_facility = self.facilities_by_id.get(mapped_facility_id)
        passenger_copies_are_well_owned = (
            has_passenger_slot
            and has_passenger_facility
            and isinstance(mapped_facility, FacilityProcessAgent)
            and mapped_facility.spec.stage == stage_value
        )
        if (has_passenger_slot or has_passenger_facility) and not (
            passenger_copies_are_well_owned
        ):
            return (facility_ids[0] if len(facility_ids) == 1 else None, True)
        if not facility_ids:
            return None, False
        if len(facility_ids) != 1:
            return None, True
        facility_id = facility_ids[0]
        facility = self.facilities_by_id.get(facility_id)
        if not isinstance(facility, FacilityProcessAgent):
            return facility_id, True
        return (
            facility_id,
            not self._existing_facility_approach_reservation_is_valid(
                passenger,
                facility,
            ),
        )

    def _existing_facility_approach_reservation_is_valid(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> bool:
        passenger_id = int(passenger.unique_id)
        stage = facility.spec.stage
        index = passenger.facility_approach_slots_by_stage.get(stage)
        if index is None:
            return False
        ownership = self._facility_approach_reservation_registry.get(
            (passenger_id, stage)
        )
        if not isinstance(ownership, _FacilityApproachReservationOwnership):
            return False
        if (
            ownership.passenger_id != passenger_id
            or ownership.stage != stage
            or ownership.facility_id != facility.facility_id
            or ownership.persons != int(passenger.group_size)
            or ownership.slot_index != index
            or ownership.proof_revision != int(self._facility_approach_proof_revision)
            or ownership.facility is not facility
            or ownership.queue is not facility.queue
        ):
            return False
        if (
            passenger.facility_approach_facility_ids_by_stage.get(stage)
            != facility.facility_id
        ):
            return False
        if (
            self._facility_targeting_reservations.get(facility.facility_id, {}).get(
                passenger_id
            )
            != int(passenger.group_size)
        ):
            return False
        if (
            self._facility_targeting_slot_indices.get(facility.facility_id, {}).get(
                passenger_id
            )
            != index
        ):
            return False
        if (
            self._facility_targeting_proof_revisions.get(facility.facility_id, {}).get(
                passenger_id
            )
            != int(self._facility_approach_proof_revision)
        ):
            return False
        if facility.queue.approach_slot_reservation(passenger_id) != index:
            return False
        if any(
            other_passenger_id != passenger_id and other_index == index
            for other_passenger_id, other_index in (
                facility.queue.approach_slot_reservations
            )
        ):
            return False
        if any(
            int(other_passenger_id) != passenger_id and int(other_index) == index
            for other_passenger_id, other_index in self._facility_targeting_slot_indices.get(
                facility.facility_id,
                {},
            ).items()
        ):
            return False
        if not facility.spec.queue_layout.slots:
            capacity = facility.queue.max_length
            return index >= 0 and (capacity is None or index < capacity)
        return index in self._facility_approach_slot_indices(facility)
