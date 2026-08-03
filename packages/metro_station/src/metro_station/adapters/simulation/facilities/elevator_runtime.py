from __future__ import annotations

from dataclasses import replace
from math import ceil, hypot
from typing import TYPE_CHECKING

import mesa
from shapely.geometry import LineString, Point as ShapelyPoint

from ..planning.plan import AgentIntent, AgentState
from .process import FacilitySpec
from .vertical import (
    ElevatorConfig,
    default_elevator_config,
)
from .elevator_cabin_runtime import ElevatorCabinCompletionMixin
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
        waiting_offset = self._landing_waiting_slot_offset()
        waiting_slots = tuple(spec.queue_layout.slots[waiting_offset:])
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

    def _landing_waiting_slot_offset(self) -> int:
        """Reserve the landing doorway and alighting corridor for unloaders."""

        slots = tuple(self.spec.queue_layout.slots)
        if len(slots) <= 1:
            return 0
        forward, _lateral = self._release_axes()
        spacing = self._release_spacing()
        corridor_length = spacing * max(1, int(self.spec.release_forward_extra))
        portal = self.spec.position
        # The opposing facade arrives along the reverse of this facade's
        # connector direction. Its alighting corridor continues through the
        # shared landing portal in that same direction.
        corridor = LineString(
            (
                portal,
                (
                    portal[0] - forward[0] * corridor_length,
                    portal[1] - forward[1] * corridor_length,
                ),
            )
        )
        min_distance = self._release_min_distance()
        for index, slot in enumerate(slots[1:], start=1):
            if corridor.distance(ShapelyPoint(slot)) >= min_distance - 1e-9:
                return index
        raise RuntimeError(
            f"elevator {self.facility_id!r} queue has no body-clear landing wait slot"
        )

    def _service_entry_position(self, release_index: int = 0) -> tuple[float, float]:
        return self.model.clamp_position(
            self.queue.layout.slot(max(0, int(release_index)))
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
        cycle = max(0.001, self._elevator_config.cycle_seconds)
        return self.cabin_capacity_persons * 60.0 / cycle

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
            + max(0.0, float(config.boarding_seconds))
            + max(0.0, float(config.travel_seconds))
            + max(0.0, float(config.unload_seconds))
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
            ceil(self._elevator_config.boarding_seconds / self._process_interval_seconds()),
        )

    @property
    def travel_steps(self) -> int:
        return max(
            1,
            ceil(self._elevator_config.travel_seconds / self._process_interval_seconds()),
        )

    @property
    def unload_steps(self) -> int:
        seconds = self._elevator_config.unload_seconds
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
            self.cycle_remaining_steps = (
                self.boarding_wait_remaining_steps + self.cycle_steps
            )
        elif self.cabin_state == "boarding":
            self.cycle_remaining_steps = self.cycle_steps
        elif self.cabin_state == "moving":
            self.cycle_remaining_steps = (
                self.travel_remaining_steps
                + self.unload_remaining_steps
                + self.return_remaining_steps
            )
        elif self.cabin_state == "unloading":
            self.cycle_remaining_steps = (
                self.unload_remaining_steps + self.return_remaining_steps
            )
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
            self._process_interval_seconds()
            if elapsed_seconds is None
            else elapsed_seconds
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
                consumed = min(budget, self.boarding_remaining_seconds)
                self.boarding_remaining_seconds -= consumed
                budget -= consumed
                cursor += consumed
                self._sync_legacy_step_counters()
                self._update_boarding_positions()
                if self.boarding_remaining_seconds > epsilon:
                    break
                self._depart_cabin()
                continue

            if self.cabin_state == "moving":
                consumed = min(budget, self.travel_remaining_seconds)
                self.travel_remaining_seconds -= consumed
                budget -= consumed
                cursor += consumed
                self._sync_legacy_step_counters()
                self._update_cabin_positions()
                if self.travel_remaining_seconds > epsilon:
                    break
                if not self._arrive_cabin():
                    self._delay_active_service_event(
                        self._process_interval_seconds()
                    )
                    break
                continue

            if self.cabin_state == "unloading":
                consumed = min(budget, self.unload_remaining_seconds)
                self.unload_remaining_seconds -= consumed
                budget -= consumed
                cursor += consumed
                if self.unload_remaining_seconds > epsilon:
                    break
                if not self._finish_unloading():
                    self._delay_active_service_event(
                        self._process_interval_seconds()
                    )
                    break
                if self.cabin_state == "idle" and self.queue and self.is_open:
                    self._start_boarding(start_time=cursor)
                continue

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

    def _start_boarding(
        self,
        *,
        force: bool = False,
        start_time: float | None = None,
    ) -> None:
        if not self.is_open:
            self._withdraw_physical_resource_request()
            return
        boarded, loaded_persons, blocked_by_unready = self._ready_boarding_batch()
        if not boarded:
            self._withdraw_physical_resource_request()
            if force:
                self._finish_returning()
            return

        if self._should_wait_for_boarders(
            loaded_persons=loaded_persons,
            blocked_by_unready=blocked_by_unready,
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
        force: bool,
    ) -> bool:
        if loaded_persons >= self.cabin_capacity_persons or self.boarding_wait_steps <= 0:
            return False
        if loaded_persons < self.min_dispatch_persons:
            if force:
                return self._has_pending_min_dispatch_demand(blocked_by_unready=blocked_by_unready)
            return True
        if force:
            return False
        return blocked_by_unready and loaded_persons < self.cabin_capacity_persons

    def _has_pending_min_dispatch_demand(self, *, blocked_by_unready: bool) -> bool:
        if blocked_by_unready and self.queue_persons >= self.min_dispatch_persons:
            return True
        return self._near_term_dispatch_demand_persons() >= self.min_dispatch_persons

    def _near_term_dispatch_demand_persons(self) -> int:
        demand_persons = self.queue_persons
        queued_ids = {id(passenger) for passenger in self.queue}
        for passenger in self.model.passengers:
            if id(passenger) in queued_ids:
                continue
            if not self._passenger_is_approaching_this_elevator(passenger):
                continue
            demand_persons += passenger.group_size
            if demand_persons >= self.min_dispatch_persons:
                return demand_persons
        return demand_persons

    def _passenger_is_approaching_this_elevator(self, passenger: PassengerAgent) -> bool:
        if passenger.passive_facility_service:
            return False
        if passenger.state != AgentState.WALKING_TO_VERTICAL.value:
            return False

        chosen_facility = passenger.facility_approach_facility_ids_by_stage.get(self.spec.stage)
        if chosen_facility is not None:
            return chosen_facility == self.facility_id
        if not passenger.prefers_elevator:
            return False
        if not self._passenger_matches_direction(passenger):
            return False
        if self.spec.entry_level_id is not None and passenger.current_level_id not in {
            None,
            self.spec.entry_level_id,
        }:
            return False

        # In the full graph, vertical choice is often made at the lobby decision point,
        # so the elevator must account for nearby elevator-preferring pedestrians.
        return self._distance_to_queue_anchor(passenger) <= self._dispatch_arrival_horizon_units()

    def _passenger_matches_direction(self, passenger: PassengerAgent) -> bool:
        direction = (
            "up"
            if passenger.intent
            in {AgentIntent.EXIT_STATION.value, AgentIntent.EVACUATE_STATION.value}
            else "down"
        )
        return self.spec.direction in {direction, "both"}

    def _distance_to_queue_anchor(self, passenger: PassengerAgent) -> float:
        px, py = passenger.pos
        qx, qy = self.spec.queue_anchor
        return hypot(px - qx, py - qy)

    def _dispatch_arrival_horizon_units(self) -> float:
        scenario = self.model.scenario
        wait_window = max(self.boarding_wait_steps, self.min_dispatch_persons)
        dynamic_horizon = scenario.walk_units_per_tick * wait_window * 6.0
        return max(45.0, dynamic_horizon)

    def _ready_boarding_batch(self) -> tuple[list[PassengerAgent], int, bool]:
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
            if would_exceed_capacity and boarded:
                break
            boarded.append(passenger)
            loaded_persons += passenger.group_size
            if loaded_persons >= self.cabin_capacity_persons:
                break
        return boarded, loaded_persons, blocked_by_unready

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

        service_start_time = (
            float(start_time)
            if start_time is not None
            else float(
                self.model.current_time_seconds + self._process_interval_seconds()
            )
        )
        board_end = service_start_time + max(0.0, float(config.boarding_seconds))
        arrive = board_end + max(0.0, float(config.travel_seconds))
        end = arrive + max(0.0, float(config.unload_seconds))
        self.active_event_id = self._record_vertical_event(
            passengers=self.cabin_passengers,
            mode="batch",
            start_time=service_start_time,
            board_end_time=board_end,
            arrive_time=arrive,
            end_time=end,
        )

    def finalize(self) -> None:
        """Preserve cabin phase and ownership at a truncated horizon."""

