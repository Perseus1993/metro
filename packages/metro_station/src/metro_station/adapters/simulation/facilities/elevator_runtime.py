from __future__ import annotations

from dataclasses import replace
from math import ceil, hypot
from typing import TYPE_CHECKING

import mesa
from .process import FacilitySpec
from .filters import facility_can_ever_serve_passenger
from .vertical import (
    ElevatorConfig,
    default_elevator_config,
)
from .elevator_cabin_runtime import ElevatorCabinCompletionMixin
from ..movement.native_facility_motion import NativeFacilityMotion
from .vertical_transport_base import VerticalTransportProcessAgent

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.transit import TrainAgent


class ElevatorProcessAgent(
    ElevatorCabinCompletionMixin,
    VerticalTransportProcessAgent,
):
    """Batch elevator process with cabin capacity, doors, travel, and unloading."""

    requires_exclusive_direction = True

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model, spec=spec)
        binding = model.layout_graph.facility_portal_binding(spec.facility_id)
        waiting_slots = binding.approach_slots
        if not waiting_slots:
            raise RuntimeError(
                f"elevator {self.facility_id!r} has no waiting slot outside its "
                "opposite-direction unloading corridor"
            )
        self.queue.layout = replace(
            self.queue.layout,
            anchor=waiting_slots[0],
            slots=waiting_slots,
        )
        self.queue.max_length = len(waiting_slots)
        self.cabin_state = "idle"
        self.boarding_remaining_steps = 0
        self.boarding_wait_remaining_steps = 0
        self.travel_remaining_steps = 0
        self.unload_remaining_steps = 0
        self.return_remaining_steps = 0
        self.cycle_remaining_steps = 0
        self.boarding_remaining_seconds = 0.0
        self.boarding_wait_remaining_seconds = 0.0
        self.travel_remaining_seconds = 0.0
        self.unload_remaining_seconds = 0.0
        self.return_remaining_seconds = 0.0
        self.cabin_passengers: list[PassengerAgent] = []
        self.cabin_load_persons = 0
        self.departed_cabins = 0
        self.last_departure_step: int | None = None
        self.last_departure_load_persons = 0
        self.active_event_id: int | None = None
        self._cabin_offsets_by_passenger: dict[int, tuple[float, float]] = {}
        self._boarding_start_positions: dict[int, tuple[float, float]] = {}
        self._boarding_segment_durations_seconds: tuple[float, ...] = ()
        self._effective_boarding_duration_seconds = 0.0
        self._unloading_start_positions: dict[int, tuple[float, float]] = {}
        self._unloading_release_positions: dict[int, tuple[float, float]] = {}
        self._unloading_segment_durations_seconds: tuple[float, ...] = ()
        self._effective_unloading_duration_seconds = 0.0

    def _service_entry_position(self, release_index: int = 0) -> tuple[float, float]:
        return self.model.clamp_position(self.queue.layout.slot(max(0, int(release_index))))

    def join_queue(
        self,
        passenger: PassengerAgent,
        *,
        authority: str | None = None,
        settle_after_walking: bool = False,
        preferred_slot_index: int | None = None,
    ) -> bool:
        """Reject an unserviceable FIFO head before it can block the cabin."""

        if not facility_can_ever_serve_passenger(passenger, self):
            return False
        return super().join_queue(
            passenger,
            authority=authority,
            settle_after_walking=settle_after_walking,
            preferred_slot_index=preferred_slot_index,
        )

    @property
    def approach_queue_layout(self):
        """Physical waiting layout with the shared landing doorway reserved."""

        return self.queue.layout

    @property
    def _elevator_config(self) -> ElevatorConfig:
        configured = self.spec.vertical_config.elevator if self.spec.vertical_config else None
        if configured is not None:
            return configured
        scenario = self.model.scenario
        unload_seconds = getattr(scenario, "elevator_unload_seconds", 0.0)
        return default_elevator_config(
            batch_capacity=scenario.elevator_cabin_capacity_persons,
            min_dispatch_persons=getattr(scenario, "elevator_min_dispatch_persons", 1),
            max_dispatch_wait_seconds=getattr(
                scenario,
                "elevator_max_dispatch_wait_seconds",
                0.0,
            ),
            boarding_seconds=scenario.elevator_boarding_seconds,
            travel_seconds=scenario.elevator_cycle_seconds,
            unload_seconds=unload_seconds,
        )

    @property
    def effective_service_persons_per_min(self) -> float:
        cycle = max(0.001, self.effective_cycle_seconds)
        return self.cabin_capacity_persons * 60.0 / cycle

    @property
    def effective_boarding_seconds(self) -> float:
        configured = max(0.0, float(self._elevator_config.boarding_seconds))
        return max(configured, float(self._effective_boarding_duration_seconds))

    @property
    def max_dispatch_wait_seconds(self) -> float:
        return max(0.0, float(self._elevator_config.max_dispatch_wait_seconds))

    @property
    def effective_cycle_seconds(self) -> float:
        """Current physically feasible cycle, including kinematic expansion."""

        config = self._elevator_config
        return (
            self.effective_boarding_seconds
            + max(0.0, float(config.travel_seconds))
            + self.effective_unloading_seconds
            + float(config.return_trip_seconds)
        )

    @property
    def effective_unloading_seconds(self) -> float:
        configured = max(0.0, float(self._elevator_config.unload_seconds))
        return max(configured, float(self._effective_unloading_duration_seconds))

    @property
    def routing_traversal_seconds(self) -> float:
        """Passenger time through the current elevator cycle, excluding return."""

        config = self._elevator_config
        dispatch_wait = (
            max(0.0, float(config.max_dispatch_wait_seconds))
            if self.queue_persons < self.min_dispatch_persons
            else 0.0
        )
        return (
            dispatch_wait
            + self.effective_boarding_seconds
            + max(0.0, float(config.travel_seconds))
            + self.effective_unloading_seconds
        )

    @property
    def cabin_capacity_persons(self) -> int:
        return max(1, int(self._elevator_config.batch_capacity))

    @property
    def min_dispatch_persons(self) -> int:
        return max(
            1,
            min(self.cabin_capacity_persons, int(self._elevator_config.min_dispatch_persons)),
        )

    @property
    def boarding_steps(self) -> int:
        return max(
            1,
            ceil(self.effective_boarding_seconds / self._process_interval_seconds()),
        )

    @property
    def travel_steps(self) -> int:
        return max(
            1,
            ceil(self._elevator_config.travel_seconds / self._process_interval_seconds()),
        )

    @property
    def unload_steps(self) -> int:
        seconds = self.effective_unloading_seconds
        if seconds <= 0.0:
            return 0
        return max(1, ceil(seconds / self._process_interval_seconds()))

    @property
    def return_steps(self) -> int:
        seconds = self._elevator_config.return_trip_seconds
        if seconds <= 0.0:
            return 0
        return max(1, ceil(seconds / self._process_interval_seconds()))

    @property
    def boarding_wait_steps(self) -> int:
        seconds = self._elevator_config.max_dispatch_wait_seconds
        if seconds > 0.0:
            return max(1, ceil(seconds / self._process_interval_seconds()))
        return self.boarding_steps

    @property
    def cycle_steps(self) -> int:
        return self.travel_steps + self.unload_steps + self.return_steps

    def _steps_for_remaining_seconds(self, seconds: float) -> int:
        if seconds <= 1e-9:
            return 0
        tick_seconds = self._process_interval_seconds()
        return max(1, ceil(float(seconds) / tick_seconds - 1e-12))

    def _sync_legacy_step_counters(self) -> None:
        """Expose second-based phase state through the historical step API."""

        self.boarding_remaining_steps = self._steps_for_remaining_seconds(
            self.boarding_remaining_seconds
        )
        self.boarding_wait_remaining_steps = self._steps_for_remaining_seconds(
            self.boarding_wait_remaining_seconds
        )
        self.travel_remaining_steps = self._steps_for_remaining_seconds(
            self.travel_remaining_seconds
        )
        self.unload_remaining_steps = self._steps_for_remaining_seconds(
            self.unload_remaining_seconds
        )
        self.return_remaining_steps = self._steps_for_remaining_seconds(
            self.return_remaining_seconds
        )
        if self.cabin_state == "waiting":
            self.cycle_remaining_steps = self.boarding_wait_remaining_steps + self.cycle_steps
        elif self.cabin_state == "boarding":
            self.cycle_remaining_steps = self.cycle_steps
        elif self.cabin_state == "moving":
            self.cycle_remaining_steps = (
                self.travel_remaining_steps
                + self.unload_remaining_steps
                + self.return_remaining_steps
            )
        elif self.cabin_state == "unloading":
            self.cycle_remaining_steps = self.unload_remaining_steps + self.return_remaining_steps
        elif self.cabin_state == "returning":
            self.cycle_remaining_steps = self.return_remaining_steps
        else:
            self.cycle_remaining_steps = 0

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._layout_queue()
        if not self.queue or not self.is_open:
            self._withdraw_physical_resource_request()
        if self.is_forced_disabled:
            self._advance_disabled_cabin()
            return
        self._advance_cabin()
        if self.cabin_state in {"idle", "waiting"} and self.queue and self.is_open:
            self._start_boarding(
                force=(
                    self.cabin_state == "waiting"
                    and (
                        self.boarding_wait_remaining_steps <= 0
                        or self.boarding_wait_remaining_seconds <= 1e-9
                    )
                )
            )
        elif self.cabin_state == "waiting" and not self.queue:
            self._finish_returning()

    def on_availability_changed(
        self,
        *,
        disabled: bool,
        time_seconds: float,
    ) -> None:
        if not disabled:
            return
        self._withdraw_physical_resource_request()
        self.forced_stop_count += 1
        self.forced_stop_persons += self.cabin_load_persons

    def _advance_disabled_cabin(self) -> None:
        if self.cabin_state == "unloading":
            self._advance_cabin()
            return
        if self.cabin_load_persons <= 0:
            return
        tick_seconds = self._process_interval_seconds()
        self._record_stationary_cabin_motion(
            interval_start_time_s=float(self.model.current_time_seconds),
            interval_end_time_s=float(self.model.current_time_seconds) + tick_seconds,
            phase=(
                "elevator_travel"
                if self.cabin_state == "moving"
                else f"elevator_{self.cabin_state}"
            ),
        )
        self.outage_person_seconds += self.cabin_load_persons * tick_seconds
        self._delay_active_service_event(tick_seconds)

    def _delay_active_service_event(self, delay_seconds: float) -> None:
        if self.active_event_id is None:
            return
        for index, event in enumerate(self.model.facility_service_events):
            if event.event_id != self.active_event_id:
                continue
            updates: dict[str, float] = {"end_time": event.end_time + delay_seconds}
            if self.cabin_state == "boarding":
                if event.board_end_time is not None:
                    updates["board_end_time"] = event.board_end_time + delay_seconds
                if event.arrive_time is not None:
                    updates["arrive_time"] = event.arrive_time + delay_seconds
            elif self.cabin_state == "moving" and event.arrive_time is not None:
                updates["arrive_time"] = event.arrive_time + delay_seconds
            self.model.facility_service_events[index] = replace(event, **updates)
            return

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return passenger in self.cabin_passengers

    def _advance_cabin(self, elapsed_seconds: float | None = None) -> None:
        """Advance physical phases in seconds and carry sub-tick surplus onward."""

        budget = float(
            self._process_interval_seconds() if elapsed_seconds is None else elapsed_seconds
        )
        cursor = float(self.model.current_time_seconds)
        epsilon = 1e-9
        # A few compatibility callers explicitly expire the legacy wait
        # counter.  Treat that as expiring the physical deadline too.
        if self.cabin_state == "waiting" and self.boarding_wait_remaining_steps <= 0:
            self.boarding_wait_remaining_seconds = 0.0

        for _phase_transition in range(8):
            if budget <= epsilon:
                break
            if self.cabin_state == "waiting":
                consumed = min(budget, self.boarding_wait_remaining_seconds)
                self.boarding_wait_remaining_seconds -= consumed
                budget -= consumed
                cursor += consumed
                if self.boarding_wait_remaining_seconds > epsilon:
                    break
                previous_state = self.cabin_state
                self._start_boarding(force=True, start_time=cursor)
                if self.cabin_state == previous_state:
                    break
                continue

            if self.cabin_state == "boarding":
                phase_start_time = cursor
                remaining_before = self.boarding_remaining_seconds
                consumed = min(budget, self.boarding_remaining_seconds)
                self.boarding_remaining_seconds -= consumed
                budget -= consumed
                cursor += consumed
                self._sync_legacy_step_counters()
                duration = max(
                    0.0,
                    float(self._effective_boarding_duration_seconds),
                )
                ratio = (
                    1.0
                    if duration <= epsilon
                    else max(
                        0.0,
                        min(
                            1.0,
                            1.0 - self.boarding_remaining_seconds / duration,
                        ),
                    )
                )
                if not self._backend_owns_native_landing_motion():
                    self._update_boarding_positions()
                    self._record_boarding_motion(
                        interval_start_time_s=phase_start_time,
                        interval_end_time_s=cursor,
                        remaining_before_s=remaining_before,
                    )
                    if self.boarding_remaining_seconds > epsilon:
                        break
                    self._depart_cabin()
                    continue
                self._assign_native_landing_targets(
                    phase="elevator_boarding",
                    collision_level_id=self.portal_entry_level_id,
                    positions=self._boarding_positions_at_ratio(ratio),
                    active_after_seconds=max(
                        0.0,
                        phase_start_time - float(self.model.current_time_seconds),
                    ),
                    terminal=self.boarding_remaining_seconds <= epsilon,
                    motion_duration_seconds=consumed,
                )
                # Native positions are committed after the shared crowd step.
                # Shaft travel cannot begin from a proposed landing coordinate.
                break

            if self.cabin_state == "moving":
                phase_start_time = cursor
                remaining_before = self.travel_remaining_seconds
                consumed = min(budget, self.travel_remaining_seconds)
                self.travel_remaining_seconds -= consumed
                budget -= consumed
                cursor += consumed
                self._sync_legacy_step_counters()
                self._update_cabin_positions()
                self._record_travel_motion(
                    interval_start_time_s=phase_start_time,
                    interval_end_time_s=cursor,
                    remaining_before_s=remaining_before,
                )
                if self.travel_remaining_seconds > epsilon:
                    break
                if budget <= epsilon and self._backend_owns_native_landing_motion():
                    # Reaching the landing at the interval boundary does not
                    # leave any shared-crowd budget in which an exit-level
                    # native body can be established.  Keep connector
                    # authority until the next facility step can validate the
                    # latest landing occupancy and insert at that exact start
                    # boundary.
                    break
                if not self._arrive_cabin(cursor):
                    self._record_stationary_cabin_motion(
                        interval_start_time_s=cursor,
                        interval_end_time_s=cursor + budget,
                        phase="elevator_travel",
                    )
                    self._delay_active_service_event(budget)
                    budget = 0.0
                    break
                continue

            if self.cabin_state == "unloading":
                if not self._unloading_release_positions:
                    if not self._configure_unloading_motion_profile(cursor):
                        self._record_stationary_cabin_motion(
                            interval_start_time_s=cursor,
                            interval_end_time_s=cursor + budget,
                            phase="elevator_unloading",
                        )
                        self._delay_active_service_event(budget)
                        budget = 0.0
                        break
                if (
                    not self._backend_owns_native_landing_motion()
                    and not self._unloading_paths_are_clear()
                ):
                    self._record_stationary_cabin_motion(
                        interval_start_time_s=cursor,
                        interval_end_time_s=cursor + budget,
                        phase="elevator_unloading",
                    )
                    self._delay_active_service_event(budget)
                    budget = 0.0
                    break
                phase_start_time = cursor
                remaining_before = self.unload_remaining_seconds
                consumed = min(budget, self.unload_remaining_seconds)
                self.unload_remaining_seconds -= consumed
                budget -= consumed
                cursor += consumed
                duration = max(
                    0.0,
                    float(self._effective_unloading_duration_seconds),
                )
                ratio = (
                    1.0
                    if duration <= epsilon
                    else max(
                        0.0,
                        min(
                            1.0,
                            1.0 - self.unload_remaining_seconds / duration,
                        ),
                    )
                )
                if not self._backend_owns_native_landing_motion():
                    self._update_unloading_positions()
                    self._record_unloading_motion(
                        interval_start_time_s=phase_start_time,
                        interval_end_time_s=cursor,
                        remaining_before_s=remaining_before,
                    )
                    if self.unload_remaining_seconds > epsilon:
                        break
                    self._service_release_positions_this_tick = []
                    if not self._finish_unloading():
                        self._delay_active_service_event(
                            self._process_interval_seconds()
                        )
                        break
                    if self.cabin_state == "idle" and self.queue and self.is_open:
                        self._start_boarding(start_time=cursor)
                    continue
                self._assign_native_landing_targets(
                    phase="elevator_unloading",
                    collision_level_id=self.portal_exit_level_id,
                    positions=self._unloading_positions_at_ratio(ratio),
                    active_after_seconds=max(
                        0.0,
                        phase_start_time - float(self.model.current_time_seconds),
                    ),
                    terminal=self.unload_remaining_seconds <= epsilon,
                    motion_duration_seconds=consumed,
                )
                # Completion waits for native endpoints after crowd iteration.
                break

            if self.cabin_state == "returning":
                consumed = min(budget, self.return_remaining_seconds)
                self.return_remaining_seconds -= consumed
                budget -= consumed
                cursor += consumed
                if self.return_remaining_seconds > epsilon:
                    break
                self._finish_returning()
                if self.queue and self.is_open:
                    self._start_boarding(start_time=cursor)
                continue
            break
        self._sync_legacy_step_counters()

    def commit_native_facility_motion_after_movement(self) -> None:
        """Commit a landing phase only from collision-authoritative positions."""

        if not self._backend_owns_native_landing_motion():
            return
        epsilon = 1e-9
        if self.cabin_state == "boarding" and self.boarding_remaining_seconds <= epsilon:
            endpoints = self._boarding_positions_at_ratio(1.0)
            native_arrival_time = self._native_landing_completion_time(endpoints)
            if native_arrival_time is None:
                self._delay_active_service_event(self._process_interval_seconds())
                return
            handoff_time = (
                float(self.model.current_time_seconds)
                + self._process_interval_seconds()
            )
            self._set_native_boarding_completion_time(handoff_time)
            center = self.model.clamp_position(self.portal_entry_position)
            self._cabin_offsets_by_passenger = {
                int(passenger.unique_id): (
                    float(passenger.pos[0]) - center[0],
                    float(passenger.pos[1]) - center[1],
                )
                for passenger in self.cabin_passengers
            }
            self._clear_native_landing_motion()
            connector_layer = "connector:" + str(
                self.spec.source_element_id or self.spec.facility_id
            )
            for passenger in self.cabin_passengers:
                self.model.movement_backend.remove_passenger(passenger)
                passenger.physical_motion_layer_id = connector_layer
            self._depart_cabin()
            return

        if self.cabin_state != "unloading" or self.unload_remaining_seconds > epsilon:
            return
        native_arrival_time = self._native_landing_completion_time(
            self._unloading_release_positions
        )
        if native_arrival_time is None:
            self._delay_active_service_event(self._process_interval_seconds())
            return
        handoff_time = (
            float(self.model.current_time_seconds)
            + self._process_interval_seconds()
        )
        self._set_native_unloading_completion_time(handoff_time)
        self._unloading_release_positions = {
            int(passenger.unique_id): (
                float(passenger.pos[0]),
                float(passenger.pos[1]),
            )
            for passenger in self.cabin_passengers
        }
        self._clear_native_landing_motion()
        self._service_release_positions_this_tick = []
        if not self._finish_unloading():
            raise RuntimeError(
                f"elevator {self.facility_id!r} rejected native release endpoints"
            )

    def _native_landing_completion_time(
        self,
        endpoints: dict[int, tuple[float, float]],
    ) -> float | None:
        arrival_times: list[float] = []
        for passenger in self.cabin_passengers:
            passenger_id = int(passenger.unique_id)
            endpoint = endpoints.get(passenger_id)
            motion = passenger.native_facility_motion
            arrival_time = passenger.native_facility_arrival_time_seconds
            if endpoint is None or motion is None or arrival_time is None:
                return None
            if hypot(
                float(passenger.pos[0]) - float(endpoint[0]),
                float(passenger.pos[1]) - float(endpoint[1]),
            ) > motion.endpoint_tolerance_m + 1e-9:
                return None
            arrival_times.append(float(arrival_time))
        return max(arrival_times) if arrival_times else None

    def _set_native_boarding_completion_time(self, completion_time: float) -> None:
        if self.active_event_id is None:
            return
        for index, event in enumerate(self.model.facility_service_events):
            if event.event_id != self.active_event_id:
                continue
            board_end = float(event.board_end_time or completion_time)
            delay = max(0.0, float(completion_time) - board_end)
            self.model.facility_service_events[index] = replace(
                event,
                board_end_time=float(completion_time),
                arrive_time=(
                    None
                    if event.arrive_time is None
                    else float(event.arrive_time) + delay
                ),
                end_time=float(event.end_time) + delay,
            )
            return

    def _set_native_unloading_completion_time(self, completion_time: float) -> None:
        if self.active_event_id is None:
            return
        for index, event in enumerate(self.model.facility_service_events):
            if event.event_id != self.active_event_id:
                continue
            self.model.facility_service_events[index] = replace(
                event,
                end_time=max(float(event.end_time), float(completion_time)),
            )
            return

    def _backend_owns_native_landing_motion(self) -> bool:
        owns_motion = getattr(
            self.model.movement_backend,
            "owns_continuous_facility_service_motion",
            None,
        )
        return bool(
            callable(owns_motion)
            and owns_motion(
                facility_kind=str(self.spec.kind),
                entry_level_id=self.portal_entry_level_id,
                exit_level_id=self.portal_exit_level_id,
            )
        )

    def _start_boarding(
        self,
        *,
        force: bool = False,
        start_time: float | None = None,
    ) -> None:
        if not self.is_open:
            self._withdraw_physical_resource_request()
            return
        # Register demand before evaluating doorway poses. A facade waiting
        # behind the opposite cabin is intentionally offset from slot zero,
        # so pose-readiness alone cannot decide whether its FIFO claim lives.
        self._request_physical_resource()
        if not self.can_start_physical_service:
            return
        (
            boarded,
            loaded_persons,
            blocked_by_unready,
            geometry_limited,
        ) = self._ready_boarding_batch()
        if not boarded:
            self._withdraw_physical_resource_request()
            if force:
                self._finish_returning()
            return

        if self._should_wait_for_boarders(
            loaded_persons=loaded_persons,
            blocked_by_unready=blocked_by_unready,
            geometry_limited=geometry_limited,
            force=force,
        ):
            self._withdraw_physical_resource_request()
            self._start_waiting_for_boarders()
            return

        # Opposite facades of one physical elevator are independent landing
        # queues but share one cabin.  Ready dispatches join the resource's
        # FIFO request order; a returning facade cannot immediately reclaim
        # the cabin ahead of an older request from the other side.
        self._request_physical_resource()
        if not self.can_start_physical_service:
            return
        self._begin_boarding(boarded, loaded_persons, start_time=start_time)

    def _should_wait_for_boarders(
        self,
        *,
        loaded_persons: int,
        blocked_by_unready: bool,
        geometry_limited: bool,
        force: bool,
    ) -> bool:
        if geometry_limited and loaded_persons > 0:
            # The remaining FIFO members cannot traverse the doorway while
            # this prefix is stationary in the cabin. Dispatch the largest
            # safe prefix even when it is below the configured fill target;
            # waiting cannot improve a static geometric incompatibility.
            return False
        if loaded_persons >= self.cabin_capacity_persons or self.boarding_wait_steps <= 0:
            return False
        # ``max_dispatch_wait_seconds`` is a hard service deadline.  Demand
        # outside the queue cannot extend it: the landing queue may already be
        # full, so counting nearby pedestrians here creates a self-sustaining
        # wait in which those pedestrians can never become boarders.
        if force:
            return False
        if loaded_persons < self.min_dispatch_persons:
            return True
        return blocked_by_unready and loaded_persons < self.cabin_capacity_persons

    def _ready_boarding_batch(
        self,
    ) -> tuple[list[PassengerAgent], int, bool, bool]:
        loaded_persons = 0
        boarded: list[PassengerAgent] = []
        blocked_by_unready = False
        for passenger in self.queue:
            if not self._passenger_ready_for_service(passenger, release_index=len(boarded)):
                blocked_by_unready = True
                break
            would_exceed_capacity = (
                loaded_persons + passenger.group_size > self.cabin_capacity_persons
            )
            if would_exceed_capacity:
                break
            boarded.append(passenger)
            loaded_persons += passenger.group_size
            if loaded_persons >= self.cabin_capacity_persons:
                break
        boarded, geometry_limited = self._largest_feasible_boarding_prefix(boarded)
        loaded_persons = sum(passenger.group_size for passenger in boarded)
        return boarded, loaded_persons, blocked_by_unready, geometry_limited

    def _largest_feasible_boarding_prefix(
        self,
        boarded: list[PassengerAgent],
    ) -> tuple[list[PassengerAgent], bool]:
        """Return the largest collision-free FIFO prefix for this dispatch."""

        for prefix_length in range(len(boarded), 0, -1):
            candidate = boarded[:prefix_length]
            try:
                self._plan_cabin_offsets(candidate)
            except RuntimeError:
                continue
            return candidate, prefix_length < len(boarded)
        return [], bool(boarded)

    def _start_waiting_for_boarders(self) -> None:
        if self.cabin_state != "waiting" or self.boarding_wait_remaining_steps <= 0:
            self.boarding_wait_remaining_seconds = max(
                0.0,
                float(self._elevator_config.max_dispatch_wait_seconds),
            )
            if self.boarding_wait_remaining_seconds <= 0.0:
                self.boarding_wait_remaining_seconds = max(
                    0.0,
                    float(self._elevator_config.boarding_seconds),
                )
            self.cabin_state = "waiting"
        self._sync_legacy_step_counters()

    def _begin_boarding(
        self,
        boarded: list[PassengerAgent],
        loaded_persons: int,
        *,
        start_time: float | None = None,
    ) -> None:
        self._acquire_physical_resource(tuple(boarded))
        if not self.physical_resource.retain(self.facility_id):
            self._release_physical_resource(tuple(boarded))
            raise RuntimeError(
                f"elevator cabin {self.physical_resource.source_element_id!r} "
                "could not retain its directional journey"
            )
        for _ in boarded:
            self.queue.pop(0)
        self.cabin_passengers = boarded
        self.cabin_load_persons = loaded_persons
        config = self._elevator_config
        self.boarding_remaining_seconds = max(0.0, float(config.boarding_seconds))
        self.boarding_wait_remaining_seconds = 0.0
        self.travel_remaining_seconds = max(0.0, float(config.travel_seconds))
        self.unload_remaining_seconds = max(0.0, float(config.unload_seconds))
        self.return_remaining_seconds = max(0.0, float(config.return_trip_seconds))
        self.cabin_state = "boarding"
        self._sync_legacy_step_counters()

        self._boarding_start_positions = {
            int(passenger.unique_id): (float(passenger.pos[0]), float(passenger.pos[1]))
            for passenger in self.cabin_passengers
        }
        for passenger in self.cabin_passengers:
            self._begin_passive_vertical_service(passenger, preserve_position=True)
        self._assign_cabin_offsets()
        self._configure_boarding_motion_profile()
        self.boarding_remaining_seconds = self._effective_boarding_duration_seconds
        self._effective_unloading_duration_seconds = (
            self._predicted_unloading_duration_seconds()
        )
        self.unload_remaining_seconds = self._effective_unloading_duration_seconds
        self._sync_legacy_step_counters()

        service_start_time = (
            float(start_time)
            if start_time is not None
            else float(self.model.current_time_seconds + self._process_interval_seconds())
        )
        board_end = service_start_time + self._effective_boarding_duration_seconds
        arrive = board_end + max(0.0, float(config.travel_seconds))
        end = arrive + self.effective_unloading_seconds
        self.active_event_id = self._record_vertical_event(
            passengers=self.cabin_passengers,
            mode="batch",
            start_time=service_start_time,
            board_end_time=board_end,
            arrive_time=arrive,
            end_time=end,
        )
        if self._backend_owns_native_landing_motion():
            self._assign_native_landing_targets(
                phase="elevator_boarding",
                collision_level_id=self.portal_entry_level_id,
                positions=self._boarding_start_positions,
                active_after_seconds=max(
                    0.0,
                    service_start_time - float(self.model.current_time_seconds),
                ),
                terminal=False,
                motion_duration_seconds=None,
            )
        else:
            self._record_boarding_motion(
                interval_start_time_s=service_start_time,
                interval_end_time_s=service_start_time,
                remaining_before_s=self.boarding_remaining_seconds,
            )

    def _assign_native_landing_targets(
        self,
        *,
        phase: str,
        collision_level_id: str | None,
        positions: dict[int, tuple[float, float]],
        active_after_seconds: float,
        terminal: bool,
        motion_duration_seconds: float | None,
    ) -> None:
        if collision_level_id is None or self.active_event_id is None:
            raise RuntimeError(
                f"elevator {self.facility_id!r} native landing motion lacks "
                "a collision level or active event"
            )
        episode_prefix = (
            f"elevator:{self.facility_id}:{self.active_event_id}:"
            f"{phase.removeprefix('elevator_')}:native"
        )
        maximum_speed = max(
            0.001,
            float(self.model.scenario.jupedsim_desired_speed_mps),
        )
        for passenger in self.cabin_passengers:
            passenger_id = int(passenger.unique_id)
            target = positions.get(passenger_id)
            if target is None:
                raise RuntimeError(
                    f"elevator native target missing passenger {passenger_id}"
                )
            passenger.physical_motion_layer_id = collision_level_id
            distance = hypot(
                float(target[0]) - float(passenger.pos[0]),
                float(target[1]) - float(passenger.pos[1]),
            )
            desired_speed = (
                maximum_speed
                if motion_duration_seconds is None
                or motion_duration_seconds <= 1e-9
                else min(
                    maximum_speed,
                    max(0.001, distance / motion_duration_seconds * 1.25),
                )
            )
            passenger.native_facility_motion = NativeFacilityMotion(
                collision_level_id=collision_level_id,
                phase=phase,
                target=self.model.clamp_position(target),
                desired_speed_mps=desired_speed,
                endpoint_tolerance_m=0.01,
                episode_id=f"{episode_prefix}:passenger:{passenger_id}",
                active_after_seconds=max(0.0, float(active_after_seconds)),
                terminal=bool(terminal),
            )

    def _clear_native_landing_motion(self) -> None:
        for passenger in self.cabin_passengers:
            passenger.native_facility_motion = None
            passenger.native_facility_arrival_time_seconds = None

    def finalize(self) -> None:
        """Preserve cabin phase and ownership at a truncated horizon."""
