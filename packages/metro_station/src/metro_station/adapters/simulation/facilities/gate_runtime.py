from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil, hypot, inf, nextafter, sqrt
from typing import TYPE_CHECKING

import mesa

from .gate_downstream_admission import (
    direct_boarding_candidates,
    has_direct_boarding_admission,
    reserve_direct_boarding_admission,
)
from .process import FacilityKind, FacilitySpec
from .runtime_base import FacilityProcessAgent
from .service_events import FacilityServiceEvent
from ..movement.waypoint_policy import intermediate_waypoint_radius
from ..planning.plan import FacilityStage
from ..spatial_capacity_admission import (
    CertifiedPlacementTemporarilyBlocked,
    SpatialCapacityExhausted,
)

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.transit import TrainAgent


@dataclass
class ActiveGatePass:
    passenger: PassengerAgent
    event_id: int
    start_position: tuple[float, float]
    end_position: tuple[float, float]
    end_time: float
    total_steps: int
    progress_steps: float = 0.0
    duration_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    remaining_seconds: float = 0.0
    last_motion_request_time: float | None = None
    release_slot_index: int | None = None


class GateProcessAgent(FacilityProcessAgent):
    """Entry or exit fare-gate process."""

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model, spec=spec)
        self.active_passes: list[ActiveGatePass] = []

    def _active_state(self) -> str:
        return "open"

    def _mechanical_service_entry_position(self) -> tuple[float, float]:
        return self.portal_entry_position

    def _mechanical_service_release_position(self) -> tuple[float, float]:
        return self.portal_exit_position

    def _queue_crossing_service_entry_position(self) -> tuple[float, float]:
        return self._mechanical_service_entry_position()

    def _queue_layout_slot_index_offset(self) -> int:
        """Keep the opposing release mouth clear while a shared-lane pass runs."""

        opposing = tuple(
            gate
            for gate in self._shared_physical_lane_facilities()
            if gate is not self and gate.portal_direction != self.portal_direction
        )
        if any(gate.active_passes for gate in opposing):
            return 2
        if not any(gate.is_open and gate.queue for gate in opposing):
            return 0
        last_direction = getattr(
            self.model,
            "_shared_gate_lane_last_started_direction",
            {},
        ).get(self._physical_lane_key())
        # With demand on both sides, the direction that just used the lane is
        # the yielding side. Slot 1 does not clear the opposing release
        # certificate in the formal layout, so retain the body-clear slot 2.
        return 2 if last_direction == self.portal_direction else 0

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._layout_queue()
        self._advance_active_passes()
        active_passes_before_service = len(self.active_passes)
        head_prepositioning_during_active_pass = (
            bool(self.active_passes)
            and bool(self.queue)
            and not self._passenger_ready_for_service(self.queue[0])
        )
        if head_prepositioning_during_active_pass:
            # This interval is the queue's physical slot advance, not a failed
            # service opportunity. Preserve the configured headway credit; if
            # the head is still absent after the active pass ends, the next
            # interval records queue_head_not_service_ready normally.
            self.service_credit += self._service_groups_per_tick()
            self._clear_service_blocked_state()
        else:
            self._serve_queue(train)
        owns_passive_motion = getattr(
            self.model.movement_backend,
            "owns_passive_layout_motion",
            None,
        )
        service_started = len(self.active_passes) > active_passes_before_service
        if service_started:
            # Queue ownership and queue-approach ownership are one FIFO. Move
            # the pending reservations into the slots released by this service
            # before physical movement consumes the interval.
            compact_approach_slots = getattr(
                self.model,
                "_compact_existing_facility_approach_slots",
                None,
            )
            if callable(compact_approach_slots):
                compact_approach_slots(self)
        if (
            self.queue
            and service_started
            and callable(owns_passive_motion)
            and owns_passive_motion()
        ):
            # Service removes slot 0 before the physical movement phase.  Re-
            # publish the compacted FIFO targets now so the next head advances
            # from slot 1 during the active pass instead of waiting one empty
            # process interval before it starts moving toward service.
            self._layout_queue()

    def _layout_queue(self) -> None:
        offset = self._queue_layout_slot_index_offset()
        self.queue.align_assigned_slots_with_fifo(slot_index_offset=offset)
        super()._layout_queue()

    def _queue_layout_uses_strict_fifo_assignment(self) -> bool:
        return True

    def _queue_layout_reverses_processing_order(self) -> bool:
        return self._queue_layout_slot_index_offset() > 0

    def _max_service_starts_per_step(self) -> int | None:
        # One process interval contains one physical queue advance. Retain any
        # accumulated credit for the next interval instead of popping a second
        # head before that body has consumed its slot-1 -> slot-0 movement.
        return 1

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return any(active.passenger is passenger for active in self.active_passes)

    def _process_interval_seconds(self) -> float:
        simulation_clock = getattr(self.model, "simulation_clock", None)
        if simulation_clock is not None:
            return float(simulation_clock.mesa_tick_seconds)
        return float(self.model.scenario.tick_seconds)

    def _can_start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> bool:
        if not super()._can_start_service(
            passenger,
            train,
            release_index=release_index,
            release_count=release_count,
        ):
            return False
        if not has_direct_boarding_admission(self, passenger):
            return False

        lane_facilities = self._shared_physical_lane_facilities()
        opposing = tuple(
            gate
            for gate in lane_facilities
            if gate is not self and gate.portal_direction != self.portal_direction
        )
        if any(gate.active_passes for gate in opposing):
            return False

        waiting_opposing = tuple(
            gate
            for gate in opposing
            if gate.is_open and gate.queue
        )
        if not waiting_opposing:
            return True

        # Once the opposite facade has demand, stop adding same-direction
        # followers and let the lane drain.  This is the service analogue of
        # an alternating single-track block and prevents permanent starvation
        # under sustained flow in one direction.
        if self.active_passes:
            return False

        ready_opposing = tuple(
            gate
            for gate in waiting_opposing
            if gate._head_can_claim_shared_lane()
        )
        if not ready_opposing:
            # Fairness must remain work-conserving. A facade whose head has
            # not reached the handoff cannot own the next turn merely because
            # it has a queue record; let the ready direction use the otherwise
            # idle lane while the opposing head continues to preposition.
            return True

        last_direction = getattr(
            self.model,
            "_shared_gate_lane_last_started_direction",
            {},
        ).get(self._physical_lane_key())
        if last_direction is not None:
            # Oldest-head selection is not fair under batched demand: one
            # train can inject a whole older exit cohort and starve entries
            # until that cohort drains. Alternate directions whenever both
            # sides have a ready head; a lone direction still uses the lane
            # continuously above.
            if str(last_direction) == self.portal_direction:
                return False
            # This direction owns the next turn, but the previous direction's
            # head must first finish retracting from the shared mouth.
            return not any(
                gate.queue.is_settling(gate.queue[0])
                for gate in waiting_opposing
            )

        contenders = (self, *ready_opposing)
        winner = min(
            contenders,
            key=lambda gate: (
                gate.queue.service_order_key(gate.queue[0]),
                gate.facility_id,
            ),
        )
        return winner is self

    def _service_start_block_reason(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int,
    ) -> str:
        if self._queue_layout_slot_index_offset() > 0:
            # A bidirectional lane deliberately retracts the yielding facade
            # head from slot 0.  Its distance from the service entry is an
            # arbitration state, not a passenger readiness failure.
            return "shared_lane_opposing_flow"
        if not self._passenger_ready_for_service(
            passenger,
            release_index=release_index,
        ):
            return "queue_head_not_service_ready"
        if not super()._can_start_service(
            passenger,
            train,
            release_index=release_index,
            release_count=1,
        ):
            return super()._service_start_block_reason(
                passenger,
                train,
                release_index=release_index,
            )
        if not has_direct_boarding_admission(self, passenger):
            return "downstream_boarding_capacity_unavailable"
        if not self._release_slot_available(passenger):
            return "gate_release_slot_unavailable"
        return "shared_lane_opposing_flow"

    def _direct_boarding_candidates(
        self,
        passenger: PassengerAgent,
    ) -> tuple[FacilityProcessAgent, ...]:
        return direct_boarding_candidates(self, passenger)

    def _head_is_ready_for_shared_lane(self) -> bool:
        if not self.is_open or not self.queue:
            return False
        passenger = self.queue[0]
        return not self.queue.is_settling(
            passenger
        ) and self._passenger_ready_for_service(passenger)

    def _head_can_claim_shared_lane(self) -> bool:
        if not self._head_is_ready_for_shared_lane():
            return False
        passenger = self.queue[0]
        return has_direct_boarding_admission(
            self,
            passenger,
        ) and self._release_slot_available(passenger)

    def _release_slot_available(self, passenger: PassengerAgent) -> bool:
        try:
            self._planned_gate_release_position(passenger, release_index=0)
        except (CertifiedPlacementTemporarilyBlocked, SpatialCapacityExhausted):
            return False
        return True

    def _shared_physical_lane_facilities(self) -> tuple[GateProcessAgent, ...]:
        lane_key = self._physical_lane_key()
        return tuple(
            facility
            for facility in self.model.facilities
            if isinstance(facility, GateProcessAgent)
            and facility._physical_lane_key() == lane_key
        )

    def _physical_lane_key(self) -> tuple[object, ...]:
        endpoints = tuple(
            sorted(
                (
                    tuple(round(float(value), 6) for value in self.portal_entry_position),
                    tuple(round(float(value), 6) for value in self.portal_exit_position),
                )
            )
        )
        return (
            str(self.spec.source_element_id or self.facility_id),
            str(self.portal_entry_level_id),
            str(self.portal_exit_level_id),
            endpoints,
        )

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> None:
        del train, release_count
        start_position = (float(passenger.pos[0]), float(passenger.pos[1]))
        if passenger.unique_id is None:
            raise RuntimeError("Gate service requires a stable passenger id")
        passenger_id = int(passenger.unique_id)
        # Preflight every operation that can reject the physical admission
        # before mutating queue ownership, Goal Graph state, or native-body
        # lifecycle.  In particular, endpoint placement is a read-only query
        # and must not leave a half-started service behind on failure.
        downstream_reservation = reserve_direct_boarding_admission(self, passenger)
        try:
            end_position, release_slot_index = self._reserve_certified_release_slot(
                passenger,
                preferred_index=release_index,
                persistent=True,
            )
        except Exception:
            if downstream_reservation == "approach":
                self.model._clear_facility_targeting_reservation(
                    passenger,
                    FacilityStage.BOARDING_DOOR.value,
                )
            elif downstream_reservation == "holding":
                self.model._clear_decision_holding_reservation(
                    passenger,
                    "boarding_decision",
                )
            elif downstream_reservation == "platform":
                self.model._clear_platform_waiting_reservation(passenger)
            raise
        distance = hypot(
            end_position[0] - start_position[0],
            end_position[1] - start_position[1],
        )
        tick_seconds = self._process_interval_seconds()
        speed_m_s = self._walking_speed_m_s()
        duration_seconds = distance / max(0.001, speed_m_s)
        total_steps = max(1, ceil(duration_seconds / tick_seconds))
        start_time = float(
            self.model.current_time_seconds + tick_seconds
        )
        end_time = start_time + duration_seconds
        if end_time - start_time < duration_seconds:
            # Adding an absolute start time can round the interval down by one
            # ULP. Keep the published event contract conservative: its elapsed
            # time must never imply a speed above the admitted walking speed.
            end_time = nextafter(end_time, inf)
        transaction_seconds = (
            60.0
            * max(1, int(passenger.group_size))
            / max(0.001, float(self.effective_service_persons_per_min))
        )
        board_end_time = min(end_time, start_time + transaction_seconds)
        passenger.begin_facility_service(self.spec)
        passenger.passive_facility_service = True
        passenger.set_target(
            end_position,
            goal_kind="being_served",
            goal_label=self.spec.label,
            facility_id=self.spec.facility_id,
            stage=self.spec.stage,
        )
        event_id = self.model.next_facility_service_event_id()
        self.model.record_pending_facility_service_event(
            FacilityServiceEvent(
                event_id=event_id,
                facility_id=self.facility_id,
                facility_kind=FacilityKind.GATE.value,
                mode=self.spec.stage,
                passenger_ids=(passenger_id,),
                start_time=start_time,
                board_end_time=board_end_time,
                arrive_time=end_time,
                end_time=end_time,
                start_position=start_position,
                end_position=end_position,
                commit_time=float(self.model.current_time_seconds),
                direction=self.portal_direction,
                from_level=self.portal_entry_level_id,
                to_level=self.portal_exit_level_id,
            )
        )
        self.active_passes.append(
            ActiveGatePass(
                passenger=passenger,
                event_id=event_id,
                start_position=start_position,
                end_position=end_position,
                end_time=end_time,
                total_steps=total_steps,
                duration_seconds=duration_seconds,
                remaining_seconds=duration_seconds,
                release_slot_index=release_slot_index,
            )
        )
        lane_directions = getattr(
            self.model,
            "_shared_gate_lane_last_started_direction",
            None,
        )
        if lane_directions is None:
            lane_directions = {}
            self.model._shared_gate_lane_last_started_direction = lane_directions
        lane_directions[self._physical_lane_key()] = self.portal_direction

    def _planned_gate_release_position(
        self,
        passenger: PassengerAgent,
        *,
        release_index: int,
    ) -> tuple[float, float]:
        position, _slot_index = self._reserve_certified_release_slot(
            passenger,
            preferred_index=release_index,
            persistent=False,
        )
        return position

    def _advance_active_passes(self) -> None:
        if self._backend_owns_gate_service_motion():
            self._advance_active_passes_with_physical_backend()
            return

        remaining: list[ActiveGatePass] = []
        completed: list[ActiveGatePass] = []
        tick_seconds = self._process_interval_seconds()
        for active in self.active_passes:
            desired_elapsed = min(
                active.duration_seconds,
                active.elapsed_seconds + tick_seconds,
            )
            desired_ratio = (
                1.0
                if active.duration_seconds <= 1e-12
                else desired_elapsed / active.duration_seconds
            )
            desired_position = (
                active.start_position[0]
                + (active.end_position[0] - active.start_position[0]) * desired_ratio,
                active.start_position[1]
                + (active.end_position[1] - active.start_position[1]) * desired_ratio,
            )
            movement_fraction = self._gate_backpressure_fraction(
                active.passenger,
                active.passenger.pos,
                desired_position,
            )
            elapsed_advance = (desired_elapsed - active.elapsed_seconds) * movement_fraction
            active.elapsed_seconds += elapsed_advance
            active.remaining_seconds = max(
                0.0,
                active.duration_seconds - active.elapsed_seconds,
            )
            blocked_seconds = (
                max(0.0, tick_seconds - elapsed_advance)
                if active.remaining_seconds > 1e-9
                else 0.0
            )
            if blocked_seconds > 1e-9:
                self._delay_gate_event(active, blocked_seconds)
            active.progress_steps = (
                float(active.total_steps)
                if active.duration_seconds <= 1e-12
                else active.total_steps
                * active.elapsed_seconds
                / active.duration_seconds
            )
            ratio = (
                1.0
                if active.duration_seconds <= 1e-12
                else active.elapsed_seconds / active.duration_seconds
            )
            active.passenger.pos = self.model.clamp_position(
                (
                    active.start_position[0]
                    + (active.end_position[0] - active.start_position[0]) * ratio,
                    active.start_position[1]
                    + (active.end_position[1] - active.start_position[1]) * ratio,
                )
            )
            if active.remaining_seconds <= 1e-9:
                completed.append(active)
            else:
                remaining.append(active)
        for active in completed:
            self._finish_gate_pass(active)
        self.active_passes = remaining

    def _advance_active_passes_with_physical_backend(self) -> None:
        """Let JuPedSim integrate same-floor gate traversal bodies.

        The process layer owns admission and service time; it only publishes
        the lane endpoint and desired speed.  The persistent operational model
        commits the actual position later in the same simulation interval, so
        ordinary walkers and gate users remain in one reciprocal collision
        world.
        """

        current_time = float(self.model.current_time_seconds)
        tick_seconds = self._process_interval_seconds()
        remaining: list[ActiveGatePass] = []
        completed: list[ActiveGatePass] = []
        for active in self.active_passes:
            elapsed_before = float(active.elapsed_seconds)
            elapsed_now = max(
                elapsed_before,
                self._elapsed_from_committed_gate_position(active),
            )
            if active.last_motion_request_time is not None:
                wall_elapsed = max(
                    0.0,
                    current_time - active.last_motion_request_time,
                )
                physical_elapsed = max(0.0, elapsed_now - elapsed_before)
                self._delay_gate_event(
                    active,
                    max(0.0, wall_elapsed - physical_elapsed),
                )
            active.elapsed_seconds = elapsed_now
            active.remaining_seconds = max(
                0.0,
                active.duration_seconds - elapsed_now,
            )
            active.progress_steps = (
                float(active.total_steps)
                if active.duration_seconds <= 1e-12
                else active.total_steps * elapsed_now / active.duration_seconds
            )

            finish_tolerance = intermediate_waypoint_radius(
                agent_radius=float(
                    self.model.scenario.jupedsim_agent_radius_units
                ),
                final_target_radius=float(
                    self.model.scenario.jupedsim_target_radius_units
                ),
            )
            distance_to_release = hypot(
                active.passenger.pos[0] - active.end_position[0],
                active.passenger.pos[1] - active.end_position[1],
            )
            crossed_release_plane = self._has_crossed_service_entry(
                tuple(active.passenger.pos),
                active.start_position,
                active.end_position,
                tolerance=finish_tolerance,
                lane_half_width=max(
                    self._release_min_distance(),
                    float(self.model.scenario.jupedsim_agent_radius_units) * 1.5,
                ),
            )
            # The release is an oriented portal, not an infinitesimal point.
            # JuPedSim may settle a body a few centimetres laterally from its
            # lane endpoint (especially for simultaneous adjacent passes).
            # Once it has reached/crossed the release plane inside its lane,
            # retaining the exact-point target creates a permanent force
            # equilibrium and prevents the domain service from committing.
            if distance_to_release <= finish_tolerance or crossed_release_plane:
                active.elapsed_seconds = active.duration_seconds
                active.remaining_seconds = 0.0
                active.progress_steps = float(active.total_steps)
                completed.append(active)
                continue

            active.passenger.move_directly_toward_target(
                self._walking_speed_m_s() * tick_seconds,
            )
            active.last_motion_request_time = current_time
            remaining.append(active)

        for active in completed:
            self._finish_gate_pass(active)
        self.active_passes = remaining

    @staticmethod
    def _elapsed_from_committed_gate_position(active: ActiveGatePass) -> float:
        dx = active.end_position[0] - active.start_position[0]
        dy = active.end_position[1] - active.start_position[1]
        length_squared = dx * dx + dy * dy
        if length_squared <= 1e-18:
            return active.duration_seconds
        progress = (
            (active.passenger.pos[0] - active.start_position[0]) * dx
            + (active.passenger.pos[1] - active.start_position[1]) * dy
        ) / length_squared
        return max(
            0.0,
            min(active.duration_seconds, progress * active.duration_seconds),
        )

    def _gate_backpressure_fraction(
        self,
        passenger: PassengerAgent,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> float:
        """Return the body-clear fraction of one proposed in-lane advance."""

        dx = end[0] - start[0]
        dy = end[1] - start[1]
        distance = hypot(dx, dy)
        if distance <= 1e-12:
            return 1.0
        ux = dx / distance
        uy = dy / distance
        minimum_distance = self._release_min_distance()
        level_id = self.portal_exit_level_id
        allowed_distance = distance
        for other in self.model.passengers:
            if other is passenger or other.current_level_id != level_id:
                continue
            offset_x = other.pos[0] - start[0]
            offset_y = other.pos[1] - start[1]
            longitudinal = offset_x * ux + offset_y * uy
            if longitudinal <= 1e-9:
                continue
            lateral = abs(offset_x * uy - offset_y * ux)
            if lateral >= minimum_distance - 1e-9:
                continue
            clearance_along_path = sqrt(
                max(0.0, minimum_distance**2 - lateral**2)
            )
            allowed_distance = min(
                allowed_distance,
                max(0.0, longitudinal - clearance_along_path),
            )
        return max(0.0, min(1.0, allowed_distance / distance))

    def _delay_gate_event(self, active: ActiveGatePass, delay_seconds: float) -> None:
        if delay_seconds <= 0.0:
            return
        active.end_time += delay_seconds
        for index, event in enumerate(self.model.facility_service_events):
            if event.event_id != active.event_id:
                continue
            self.model.facility_service_events[index] = replace(
                event,
                end_time=event.end_time + delay_seconds,
                arrive_time=(
                    None
                    if event.arrive_time is None
                    else event.arrive_time + delay_seconds
                ),
            )
            return

    def _finish_gate_pass(self, active: ActiveGatePass) -> None:
        passenger = active.passenger
        passenger.passive_facility_service = False
        if self._backend_owns_gate_service_motion():
            # Completion is detected from the native JuPedSim coordinate.  A
            # waypoint-radius hit is a valid physical portal crossing; snapping
            # Mesa to the nominal endpoint would split the two authorities by
            # as much as the target radius and make the next walking command
            # reverse back toward the still-native body.
            passenger.pos = self.model.clamp_position(tuple(passenger.pos))
            self._set_gate_event_completion_time(
                active,
                float(self.model.current_time_seconds),
            )
            self.model.movement_backend.record_facility_motion_boundary(
                passenger,
                time_seconds=active.end_time,
                phase="same_floor_facility",
            )
        else:
            passenger.pos = self.model.clamp_position(active.end_position)
            passenger.suppress_movement_for_current_step()
        passenger.advance_after_movement(True)
        self.served_persons += passenger.group_size
        if passenger.unique_id is None:
            raise RuntimeError("Gate service completion requires a stable passenger id")
        self.model.observe_facility_service_completed(
            self.facility_id,
            (int(passenger.unique_id),),
            active.end_time,
            poll_immediately=True,
        )
        self._release_certified_slot(passenger, active.release_slot_index)

    def _set_gate_event_completion_time(
        self,
        active: ActiveGatePass,
        completion_time: float,
    ) -> None:
        actual_end = max(0.0, float(completion_time))
        active.end_time = actual_end
        for index, event in enumerate(self.model.facility_service_events):
            if event.event_id != active.event_id:
                continue
            self.model.facility_service_events[index] = replace(
                event,
                end_time=actual_end,
                arrive_time=actual_end,
                end_position=tuple(active.passenger.pos),
                board_end_time=(
                    None
                    if event.board_end_time is None
                    else min(float(event.board_end_time), actual_end)
                ),
            )
            return

    def _backend_owns_gate_service_motion(self) -> bool:
        owns_service_motion = getattr(
            self.model.movement_backend,
            "owns_continuous_facility_service_motion",
            None,
        )
        return bool(
            callable(owns_service_motion)
            and owns_service_motion(
                facility_kind=str(self.spec.kind),
                entry_level_id=self.spec.entry_level_id,
                exit_level_id=self.spec.exit_level_id,
            )
        )

    def finalize(self) -> None:
        """Preserve in-flight passes at a truncated simulation horizon."""
