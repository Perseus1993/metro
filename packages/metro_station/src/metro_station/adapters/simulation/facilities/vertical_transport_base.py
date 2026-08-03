from __future__ import annotations

from dataclasses import replace
from math import ceil, hypot
from typing import TYPE_CHECKING

import mesa

from .process import FacilityKind, FacilitySpec
from ..movement.dynamic_body_clearance import external_body_positions
from .runtime_base import FacilityProcessAgent
from .service_events import FacilityServiceEvent
from .vertical_physical_resource import ActiveVerticalRide, VerticalPhysicalResource
from .vertical_release_geometry import VerticalReleaseGeometryMixin

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.transit import TrainAgent


def _point_to_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-18:
        return hypot(point[0] - start[0], point[1] - start[1])
    projection = (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    ) / length_squared
    ratio = max(0.0, min(1.0, projection))
    closest = (start[0] + dx * ratio, start[1] + dy * ratio)
    return hypot(point[0] - closest[0], point[1] - closest[1])


def _motion_segment_samples(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    maximum_step: float,
) -> tuple[tuple[float, float], ...]:
    distance = hypot(end[0] - start[0], end[1] - start[1])
    segment_count = max(1, ceil(distance / max(1e-6, maximum_step)))
    return tuple(
        (
            start[0] + (end[0] - start[0]) * index / segment_count,
            start[1] + (end[1] - start[1]) * index / segment_count,
        )
        for index in range(segment_count + 1)
    )


class VerticalTransportProcessAgent(
    VerticalReleaseGeometryMixin,
    FacilityProcessAgent,
):
    """Base process for vertical passenger movers."""

    requires_exclusive_direction = False

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model, spec=spec)
        self.active_rides: list[ActiveVerticalRide] = []
        self._active_ride_swept_positions_this_tick: tuple[tuple[float, float], ...] = ()
        self.forced_stop_count = 0
        self.forced_stop_persons = 0
        self.outage_person_seconds = 0.0
        source_id = str(spec.source_element_id or spec.facility_id)
        self.physical_resource = VerticalPhysicalResource(source_id)
        if spec.queue_layout.slots and spec.kind in {
            FacilityKind.STAIRS.value,
            FacilityKind.ESCALATOR.value,
        }:
            # The final compiled slot is a physical backpressure reserve. It
            # lets an opposing landing clear the shared exit portal without
            # squeezing the queue tail outside its validated geometry.
            self.queue.max_length = max(1, len(spec.queue_layout.slots) - 1)

    def bind_physical_resource(self, resource: VerticalPhysicalResource) -> None:
        if resource.source_element_id != str(self.spec.source_element_id or self.spec.facility_id):
            raise ValueError("vertical physical resource belongs to a different connector")
        self.physical_resource = resource

    @property
    def is_open(self) -> bool:
        """Whether this facade is operational and may accept a landing queue."""

        return super().is_open

    @property
    def can_start_physical_service(self) -> bool:
        """Whether the shared connector dispatcher currently grants this facade."""

        return self.is_open and self.physical_resource.can_acquire(self.facility_id)

    def _request_physical_resource(self) -> None:
        self.physical_resource.request(self.facility_id)

    def _withdraw_physical_resource_request(self) -> None:
        self.physical_resource.withdraw_request(self.facility_id)

    def _serve_queue(self, train: TrainAgent | None = None) -> None:
        if not self.is_open or not self.queue:
            self._withdraw_physical_resource_request()
        super()._serve_queue(train)

    def _layout_queue(self) -> None:
        if self.is_open and self.queue:
            # Direction arbitration precedes landing compaction. The selected
            # facade keeps slot 0; every non-selected facade backs up one body
            # so the selected ride has a clear downstream landing.
            self._request_physical_resource()
        super()._layout_queue()

    def _queue_layout_slot_index_offset(self) -> int:
        if not self.queue:
            return 0
        return 0 if self.physical_resource.can_acquire(self.facility_id) else 1

    def _can_start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> bool:
        self._request_physical_resource()
        if not super()._can_start_service(
            passenger,
            train,
            release_index=release_index,
            release_count=release_count,
        ):
            return False
        if not self._connector_entry_has_clearance(passenger):
            return False
        if not self.can_start_physical_service:
            return False
        return self._connector_exit_has_clearance(passenger)

    def _connector_entry_has_clearance(self, passenger: PassengerAgent) -> bool:
        """Do not admit a follower into an occupied microscopic body position."""

        minimum = self._release_min_distance()
        return all(
            ride.passenger is passenger
            or hypot(
                passenger.pos[0] - ride.passenger.pos[0],
                passenger.pos[1] - ride.passenger.pos[1],
            )
            >= minimum - 1e-9
            for ride in self.active_rides
        )

    def _connector_exit_has_clearance(self, passenger: PassengerAgent) -> bool:
        return self._has_release_clearance(
            self.spec.exit_position,
            self._release_min_distance(),
            passenger=passenger,
        )

    def _queue_external_occupied_positions(self) -> tuple[tuple[float, float], ...]:
        """Expose authoritative in-connector bodies to landing-queue layout."""

        return (
            *super()._queue_external_occupied_positions(),
            *(tuple(ride.passenger.pos) for ride in self.active_rides),
            *self._active_ride_swept_positions_this_tick,
        )

    def on_availability_changed(
        self,
        *,
        disabled: bool,
        time_seconds: float,
    ) -> None:
        if not disabled:
            return
        # Control changes commit before the facility loop.  Withdraw at that
        # boundary so an invalid FIFO head cannot hold the shared connector
        # until this facade's later step (a full, tick-sized throughput gap).
        self._withdraw_physical_resource_request()
        self.forced_stop_count += 1
        self.forced_stop_persons += self.active_ride_persons

    def _active_state(self) -> str:
        return "running"

    def _process_interval_seconds(self) -> float:
        simulation_clock = getattr(self.model, "simulation_clock", None)
        if simulation_clock is not None:
            return float(simulation_clock.mesa_tick_seconds)
        return float(self.model.scenario.tick_seconds)

    @property
    def travel_speed_units_per_tick(self) -> float:
        """Physical travel distance advanced during one Mesa process interval."""

        return self.travel_speed_m_s * self._process_interval_seconds()

    @property
    def travel_speed_m_s(self) -> float:
        if self.spec.travel_speed_m_s is not None:
            return max(0.001, float(self.spec.travel_speed_m_s))
        configured = self.spec.speed_units_per_tick
        if configured is not None:
            # Hand-built legacy specs did not carry a physical speed. Preserve
            # their stated per-tick contract instead of silently treating it
            # as metres per second.
            return max(
                0.001,
                float(configured) / self._process_interval_seconds(),
            )
        return max(0.001, float(self.model.scenario.jupedsim_desired_speed_mps))

    def _ride_steps_from_seconds(self, seconds: float | None) -> int:
        duration_seconds = self._ride_duration_seconds(seconds)
        return max(
            1,
            ceil(duration_seconds / self._process_interval_seconds()),
        )

    def _ride_duration_seconds(self, seconds: float | None) -> float:
        """Return the physical duration without Mesa-tick quantization."""

        if seconds is not None:
            return max(0.0, float(seconds))
        distance = hypot(
            self.spec.exit_position[0] - self.spec.position[0],
            self.spec.exit_position[1] - self.spec.position[1],
        )
        return distance / max(0.001, self.travel_speed_m_s)

    @property
    def routing_traversal_seconds(self) -> float:
        """Current free-flow passenger traversal cost used by strategic routing."""

        return self._ride_duration_seconds(None)

    def _begin_passive_vertical_service(
        self,
        passenger: PassengerAgent,
        *,
        lateral_offset: float = 0.0,
        preserve_position: bool = False,
    ) -> None:
        passenger.begin_facility_service(self.spec)
        if self.spec.entry_level_id is not None:
            passenger.current_level_id = self.spec.entry_level_id
        passenger.passive_facility_service = True
        service_target = self._offset_vertical_position(
            self.spec.exit_position,
            lateral_offset,
        )
        passenger.set_target(
            service_target,
            goal_kind="being_served",
            goal_label=self.spec.label,
            facility_id=self.spec.facility_id,
            stage=self.spec.stage,
        )
        if not preserve_position:
            passenger.pos = self.model.clamp_position(
                self._offset_vertical_position(self.spec.position, lateral_offset)
            )

    def _finish_vertical_service(
        self,
        passenger: PassengerAgent,
        *,
        release_index: int = 0,
        event_id: int | None = None,
        preferred_release_position: tuple[float, float] | None = None,
        prefer_forward_clearance: bool = False,
    ) -> bool:
        try:
            release_position = self._vertical_release_position(
                passenger,
                release_index,
                preferred_release_position=preferred_release_position,
                prefer_forward_clearance=prefer_forward_clearance,
            )
        except RuntimeError:
            return False
        try:
            previous_level_id = passenger.current_level_id
            completion_time = self._event_completion_time(event_id)
            if self.spec.exit_level_id is not None:
                passenger.current_level_id = self.spec.exit_level_id
            if passenger.current_level_id != previous_level_id:
                self.model.goal_parity.record(
                    passenger,
                    stream="physical",
                    kind="level_changed",
                    time_seconds=completion_time,
                    stage=self.spec.stage,
                    facility_id=self.facility_id,
                    level_id=passenger.current_level_id,
                )
            passenger.passive_facility_service = False
            passenger.set_target(
                release_position,
                goal_kind="being_served",
                goal_label=self.spec.label,
                facility_id=self.spec.facility_id,
                stage=self.spec.stage,
            )
            passenger.pos = release_position
            suppress_movement = getattr(passenger, "suppress_movement_for_current_step", None)
            if callable(suppress_movement):
                suppress_movement()
            passenger.advance_after_movement(True)
            self.served_persons += passenger.group_size
            observer = getattr(self.model, "observe_facility_service_completed", None)
            if callable(observer):
                observer(
                    self.facility_id,
                    (int(passenger.unique_id),),
                    completion_time,
                )
        finally:
            self._release_physical_resource((passenger,))
        return True

    def _event_completion_time(self, event_id: int | None) -> float:
        if event_id is not None:
            for event in self.model.facility_service_events:
                if event.event_id == event_id:
                    return float(event.end_time)
        return float(self.model.current_time_seconds)

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return any(ride.passenger is passenger for ride in self.active_rides)

    @property
    def active_ride_persons(self) -> int:
        return sum(ride.passenger.group_size for ride in self.active_rides)

    def _start_passive_ride(
        self,
        passenger: PassengerAgent,
        *,
        mode: str | None,
        ride_steps: int,
        ride_duration_seconds: float | None = None,
        release_index: int = 0,
        release_count: int = 1,
        board_end_time: float | None = None,
        arrive_time: float | None = None,
    ) -> None:
        self._acquire_physical_resource((passenger,))
        try:
            lateral_offset = self._ride_lateral_offset(
                passenger,
                release_index=release_index,
                release_count=release_count,
            )
            start_position = (float(passenger.pos[0]), float(passenger.pos[1]))
            self._begin_passive_vertical_service(
                passenger,
                lateral_offset=lateral_offset,
                preserve_position=True,
            )
            start_time = (
                self.model.current_time_seconds + self._process_interval_seconds()
            )
            duration_seconds = (
                float(ride_duration_seconds)
                if ride_duration_seconds is not None
                else float(ride_steps) * self._process_interval_seconds()
            )
            duration_seconds = max(0.0, duration_seconds)
            end_time = start_time + duration_seconds
            event_id = self._record_vertical_event(
                passengers=[passenger],
                mode=mode,
                start_time=start_time,
                board_end_time=board_end_time,
                arrive_time=arrive_time,
                end_time=end_time,
                start_position=start_position,
            )
            self.active_rides.append(
                ActiveVerticalRide(
                    passenger=passenger,
                    event_id=event_id,
                    remaining_steps=ride_steps,
                    total_steps=ride_steps,
                    start_position=start_position,
                    lateral_offset=lateral_offset,
                    duration_seconds=duration_seconds,
                    remaining_seconds=duration_seconds,
                )
            )
        except Exception:
            self._release_physical_resource((passenger,))
            raise

    def _acquire_physical_resource(
        self,
        passengers: tuple[PassengerAgent, ...],
    ) -> None:
        passenger_ids = tuple(int(passenger.unique_id) for passenger in passengers)
        if not self.physical_resource.acquire(self.facility_id, passenger_ids):
            raise RuntimeError(
                f"vertical connector {self.physical_resource.source_element_id!r} is serving "
                f"opposite facility {self.physical_resource.active_facility_id!r}"
            )

    def _release_physical_resource(
        self,
        passengers: tuple[PassengerAgent, ...],
    ) -> None:
        self.physical_resource.release(
            self.facility_id,
            tuple(int(passenger.unique_id) for passenger in passengers),
        )

    def _advance_active_rides(self) -> None:
        tick_seconds = self._process_interval_seconds()
        original_order = list(self.active_rides)
        positions_before = {
            id(ride): tuple(ride.passenger.pos) for ride in original_order
        }
        ordered = sorted(
            original_order,
            key=lambda ride: self._ride_elapsed_ratio(ride, ride.elapsed_seconds),
            reverse=True,
        )
        retained_ids: set[int] = set()
        # Riders and landing-queue bodies share the same projected connector
        # domain.  A ride may not sweep toward a settling queue follower merely
        # because that follower has not moved yet in this process interval.
        ride_and_queue_ids = {
            *(int(passenger.unique_id) for passenger in self.queue),
            *(int(ride.passenger.unique_id) for ride in original_order),
        }
        physical_positions_ahead: list[tuple[float, float]] = [
            *(tuple(passenger.pos) for passenger in self.queue),
            *external_body_positions(
                self.model,
                level_id=self.spec.entry_level_id,
                excluded_passenger_ids=ride_and_queue_ids,
            ),
        ]
        progress_ratios_ahead: list[float] = []
        self._service_release_positions_this_tick = []
        release_blocked = False
        release_index = 0

        # Resolve front to back in one pass. A release decision is made before
        # a follower is advanced, so followers are constrained by the leader's
        # final authoritative pose (released or rolled back), never by a pose
        # that is later undone. Stable sorting plus the final original-order
        # filter preserves FIFO when progress ratios tie.
        for ride in ordered:
            elapsed_before_tick = float(ride.elapsed_seconds)
            progress_before_tick = float(ride.progress_steps)
            duration_seconds = (
                float(ride.duration_seconds)
                if ride.duration_seconds is not None
                else float(ride.total_steps) * tick_seconds
            )
            progress_factor = max(0.0, self._ride_progress_steps_per_tick(ride))
            remaining_before = max(0.0, duration_seconds - ride.elapsed_seconds)
            progress_seconds = min(
                remaining_before,
                tick_seconds * progress_factor,
            )
            proposed_elapsed = min(
                duration_seconds,
                float(ride.elapsed_seconds) + progress_seconds,
            )
            capped_elapsed = self._cap_elapsed_for_connector_spacing(
                ride,
                elapsed_before_tick,
                proposed_elapsed,
                physical_positions_ahead,
                progress_ratios_ahead,
            )
            ratio = self._ride_elapsed_ratio(ride, capped_elapsed)
            ride.elapsed_seconds = capped_elapsed
            ride.progress_steps = min(float(ride.total_steps), ratio * ride.total_steps)
            ride.remaining_seconds = max(0.0, duration_seconds - ride.elapsed_seconds)
            ride.remaining_steps = max(
                0,
                ceil(float(ride.remaining_seconds) / tick_seconds - 1e-12),
            )
            if float(ride.remaining_seconds) > 1e-9:
                actual_elapsed_advance = max(
                    0.0,
                    capped_elapsed - elapsed_before_tick,
                )
                self._delay_ride_event(
                    ride,
                    max(0.0, tick_seconds - actual_elapsed_advance),
                )
                self._update_active_ride_position(ride)
                retained_ids.add(id(ride))
                physical_positions_ahead.append(tuple(ride.passenger.pos))
                progress_ratios_ahead.append(ratio)
                continue

            continuous_exit = self._offset_vertical_position(
                self.spec.exit_position,
                ride.lateral_offset,
            )
            completion_wall_seconds = (
                0.0
                if remaining_before <= 1e-12
                else remaining_before / max(1e-12, progress_factor)
            )
            completion_delay = max(
                0.0,
                min(tick_seconds, completion_wall_seconds) - remaining_before,
            )
            self._delay_ride_event(ride, completion_delay)
            if not release_blocked and self._finish_vertical_service(
                ride.passenger,
                release_index=release_index,
                event_id=ride.event_id,
                preferred_release_position=continuous_exit,
            ):
                physical_positions_ahead.append(tuple(ride.passenger.pos))
                progress_ratios_ahead.append(1.0)
                release_index += 1
                continue

            # The leader could not cross the downstream boundary. Roll it back
            # before processing any follower and publish that actual pose as
            # the next spacing constraint. Later riders therefore cannot
            # collapse onto or overtake it in this same process interval.
            release_blocked = True
            ride.elapsed_seconds = elapsed_before_tick
            ride.progress_steps = progress_before_tick
            ride.remaining_seconds = max(
                0.0,
                float(ride.duration_seconds or 0.0) - elapsed_before_tick,
            )
            ride.remaining_steps = max(
                0,
                ceil(float(ride.remaining_seconds) / tick_seconds - 1e-12),
            )
            self._delay_ride_event(
                ride,
                max(0.0, tick_seconds - completion_delay),
            )
            retained_ids.add(id(ride))
            physical_positions_ahead.append(tuple(ride.passenger.pos))
            progress_ratios_ahead.append(
                self._ride_elapsed_ratio(ride, ride.elapsed_seconds)
            )
            release_index += 1

        self.active_rides = [
            ride for ride in original_order if id(ride) in retained_ids
        ]
        sample_step = max(0.02, self._release_min_distance() * 0.2)
        self._active_ride_swept_positions_this_tick = tuple(
            sample
            for ride in original_order
            for sample in _motion_segment_samples(
                positions_before[id(ride)],
                tuple(ride.passenger.pos),
                maximum_step=sample_step,
            )
        )

    def _ride_elapsed_ratio(self, ride: ActiveVerticalRide, elapsed_seconds: float) -> float:
        duration_seconds = float(ride.duration_seconds or 0.0)
        if duration_seconds <= 1e-12:
            return 1.0
        return max(0.0, min(1.0, float(elapsed_seconds) / duration_seconds))

    def _ride_position_at_elapsed(
        self,
        ride: ActiveVerticalRide,
        elapsed_seconds: float,
    ) -> tuple[float, float]:
        ratio = self._ride_elapsed_ratio(ride, elapsed_seconds)
        start_x, start_y = ride.start_position
        end_x, end_y = self._offset_vertical_position(
            self.spec.exit_position,
            ride.lateral_offset,
        )
        return (
            start_x + (end_x - start_x) * ratio,
            start_y + (end_y - start_y) * ratio,
        )

    def _cap_elapsed_for_connector_spacing(
        self,
        ride: ActiveVerticalRide,
        elapsed_before: float,
        proposed_elapsed: float,
        positions_ahead: list[tuple[float, float]],
        progress_ratios_ahead: list[float],
    ) -> float:
        if not positions_ahead or proposed_elapsed <= elapsed_before + 1e-12:
            return proposed_elapsed
        min_distance = self._release_min_distance()
        duration_seconds = float(ride.duration_seconds or 0.0)
        if progress_ratios_ahead and duration_seconds > 1e-12:
            # A follower may draw level with a leader in a physically separate
            # lane, but it may never pass that leader.
            proposed_elapsed = min(
                proposed_elapsed,
                min(progress_ratios_ahead) * duration_seconds,
            )

        position_before = self._ride_position_at_elapsed(ride, elapsed_before)

        def position_is_clear(elapsed: float) -> bool:
            position = self._ride_position_at_elapsed(ride, elapsed)
            return all(
                _point_to_segment_distance(occupied, position_before, position)
                >= min_distance - 1e-9
                for occupied in positions_ahead
            )

        if position_is_clear(proposed_elapsed):
            return proposed_elapsed
        # Connector progress is authoritative and monotone.  An invalid
        # pre-existing overlap must hold until the blocking body clears; it
        # must never be "repaired" by rewinding a rider toward the entrance.
        low = elapsed_before
        high = proposed_elapsed
        if not position_is_clear(low):
            return elapsed_before
        for _ in range(40):
            midpoint = (low + high) / 2.0
            if position_is_clear(midpoint):
                low = midpoint
            else:
                high = midpoint
        return low

    def _ride_progress_steps_per_tick(self, ride: ActiveVerticalRide) -> float:
        return 1.0

    def _update_active_ride_position(self, ride: ActiveVerticalRide) -> None:
        ride.passenger.pos = self.model.clamp_position(
            self._interpolated_individual_vertical_position(ride)
        )

    def _interpolated_individual_vertical_position(
        self,
        ride: ActiveVerticalRide,
    ) -> tuple[float, float]:
        ratio = (
            1.0
            if (
                ride.total_steps <= 0
                or ride.progress_steps >= float(ride.total_steps) - 1e-12
                or (
                    ride.duration_seconds is not None
                    and ride.duration_seconds <= 1e-12
                )
            )
            else (
                max(
                    0.0,
                    min(
                        1.0,
                        ride.elapsed_seconds / ride.duration_seconds,
                    ),
                )
                if ride.duration_seconds is not None
                else max(
                    0.0,
                    min(1.0, ride.progress_steps / ride.total_steps),
                )
            )
        )
        start_x, start_y = ride.start_position
        end_x, end_y = self._offset_vertical_position(
            self.spec.exit_position,
            ride.lateral_offset,
        )
        return (
            start_x + (end_x - start_x) * ratio,
            start_y + (end_y - start_y) * ratio,
        )

    def _delay_ride_event(self, ride: ActiveVerticalRide, delay_seconds: float) -> None:
        if delay_seconds <= 0.0:
            return
        for index, event in enumerate(self.model.facility_service_events):
            if event.event_id != ride.event_id:
                continue
            self.model.facility_service_events[index] = replace(
                event,
                end_time=event.end_time + delay_seconds,
                arrive_time=(
                    None if event.arrive_time is None else event.arrive_time + delay_seconds
                ),
            )
            return

    def _interpolated_vertical_position(
        self,
        progress_steps: float,
        total_steps: int,
    ) -> tuple[float, float]:
        ratio = 1.0 if total_steps <= 0 else max(0.0, min(1.0, progress_steps / total_steps))
        sx, sy = self.spec.position
        ex, ey = self.spec.exit_position
        return (sx + (ex - sx) * ratio, sy + (ey - sy) * ratio)

    def finalize(self) -> None:
        """Preserve in-flight rides at a truncated simulation horizon."""

    def _record_vertical_event(
        self,
        *,
        passengers: list[PassengerAgent],
        mode: str | None,
        start_time: float,
        end_time: float,
        board_end_time: float | None = None,
        arrive_time: float | None = None,
        start_position: tuple[float, float] | None = None,
    ) -> int:
        event = FacilityServiceEvent(
            event_id=self.model.next_facility_service_event_id(),
            facility_id=self.facility_id,
            facility_kind=self.spec.kind,
            mode=mode,
            passenger_ids=tuple(int(passenger.unique_id) for passenger in passengers),
            start_time=start_time,
            board_end_time=board_end_time,
            arrive_time=arrive_time,
            end_time=end_time,
            start_position=start_position or self.spec.position,
            end_position=self.spec.exit_position,
            # Facility changes are first authoritative in the interval-end
            # snapshot.  Use that physical service boundary, not the Mesa
            # callback's interval-start timestamp, as the commitment instant.
            commit_time=float(start_time),
            direction=self.spec.direction,
            from_level=self.spec.entry_level_id,
            to_level=self.spec.exit_level_id,
        )
        pending_recorder = getattr(
            self.model,
            "record_pending_facility_service_event",
            None,
        )
        if callable(pending_recorder):
            pending_recorder(event)
        else:
            self.model.record_facility_service_event(event)
        return event.event_id
