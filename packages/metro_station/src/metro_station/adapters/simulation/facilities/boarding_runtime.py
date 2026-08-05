from __future__ import annotations

from dataclasses import dataclass, replace
from math import hypot
from typing import TYPE_CHECKING

from shapely.geometry import LineString, Point as ShapelyPoint

from ..movement.dynamic_body_clearance import external_body_positions
from ..movement.waypoint_policy import intermediate_waypoint_radius
from .process import FacilityKind
from .process_motion import minimum_jerk_duration_seconds, minimum_jerk_progress
from .runtime_base import FacilityProcessAgent
from .service_events import FacilityServiceEvent
from ..planning.plan import AgentState

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.transit import PlatformAgent, TrainAgent


@dataclass
class ActiveDoorBoarding:
    passenger: PassengerAgent
    event_id: int
    start_position: tuple[float, float]
    end_position: tuple[float, float]
    start_time: float
    end_time: float
    duration_seconds: float
    train: TrainAgent
    train_arrival_sequence: int
    elapsed_seconds: float = 0.0

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.duration_seconds - self.elapsed_seconds)


class BoardingDoorProcessAgent(FacilityProcessAgent):
    """Train-door process with continuous, process-owned boarding motion."""

    def __init__(self, model, *, spec) -> None:
        super().__init__(model, spec=spec)
        self.active_boardings: list[ActiveDoorBoarding] = []
        self._crossing_waiting_passenger_ids: set[int] = set()

    def _initial_state(self) -> str:
        return "closed"

    def _active_state(self) -> str:
        return "open"

    @property
    def is_available_for_queue(self) -> bool:
        # The service handoff remains physically owned until the active body
        # has crossed the train-door plane.  A passenger may still wait on the
        # platform, but cannot capture this door queue during that interval.
        return (
            not self.is_forced_disabled
            and not self.queue.is_full
            and not self.active_boardings
        )

    @property
    def lifecycle_reserved_queue_slot_indices(self) -> tuple[int, ...]:
        # Slot zero is the queue-to-door handoff.  Popping the admitted head
        # must not make it available to approach routing while the associated
        # swept crossing corridor is still active.
        return (0,) if self.active_boardings else ()

    def _sync_state(self, train: TrainAgent | None = None) -> None:
        self.state = "open" if train is not None and train.is_boarding else "closed"

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._advance_active_boardings()
        # The head passenger's swept door-crossing corridor remains a live
        # body resource until that crossing finishes.  Compacting the queue
        # first moves the follower into the vacated service slot and can then
        # block the active rider forever.  Freeze queue compaction while the
        # corridor is owned; once it clears, followers may advance and the
        # next rider may be admitted in this same process tick.
        if not self.active_boardings:
            self._layout_queue()
        self._serve_queue(train)

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return any(active.passenger is passenger for active in self.active_boardings)

    def _process_interval_seconds(self) -> float:
        simulation_clock = getattr(self.model, "simulation_clock", None)
        if simulation_clock is not None:
            return float(simulation_clock.mesa_tick_seconds)
        return float(self.model.scenario.tick_seconds)

    def _service_ready_radius(self) -> float:
        """Require the queue head to reach the physical door handoff point.

        The ordinary facility radius describes arrival in a semantic target
        region.  A train-door admission transfers body-motion ownership to a
        swept crossing corridor, so admitting from anywhere in that broad
        region can leave the rider and its follower on opposite sides of the
        same corridor reservation.  Use the shared tactical waypoint
        tolerance for this physical ownership boundary.
        """

        scenario = self.model.scenario
        agent_radius = float(scenario.jupedsim_agent_radius_units)
        return max(
            agent_radius * 0.5,
            intermediate_waypoint_radius(
                agent_radius=agent_radius,
                final_target_radius=float(scenario.jupedsim_target_radius_units),
            ),
        )

    def _can_start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> bool:
        if not (
            not self.active_boardings
            and super()._can_start_service(
                passenger,
                train,
                release_index=release_index,
                release_count=release_count,
            )
            and train is not None
            and train.capacity_remaining >= passenger.group_size
        ):
            return False
        start, end, duration = self._boarding_motion(passenger)
        close_step = getattr(train, "close_step", None)
        if close_step is None:
            return False
        close_time = float(close_step) * self._process_interval_seconds()
        start_time = float(self.model.current_time_seconds) + self._process_interval_seconds()
        if start_time + duration > close_time + 1e-9:
            return False
        return self._boarding_path_is_clear(
            passenger,
            start,
            end,
            allow_pending_approaches=True,
        )

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> None:
        del release_index, release_count
        if train is None:
            return
        if passenger.unique_id is None:
            raise RuntimeError("Train-door service requires a stable passenger id")

        start_position, end_position, duration_seconds = self._boarding_motion(passenger)
        if not self._boarding_path_is_clear(
            passenger,
            start_position,
            end_position,
            allow_pending_approaches=True,
        ):
            raise RuntimeError("train-door swept path became occupied before admission")
        tick_seconds = self._process_interval_seconds()
        start_time = float(self.model.current_time_seconds) + tick_seconds
        close_step = getattr(train, "close_step", None)
        if close_step is None:
            raise RuntimeError("train-door admission requires an active close boundary")
        close_time = float(close_step) * tick_seconds
        if start_time + duration_seconds > close_time + 1e-9:
            raise RuntimeError("train-door service cannot finish before the close boundary")
        end_time = start_time + duration_seconds
        event_id = self.model.next_facility_service_event_id()
        approach_relocations = self._reserve_active_crossing_waits(passenger)

        # Capacity is reserved at admission, while completion and Goal Graph
        # advancement wait for the actual body to cross the door trajectory.
        train.reserved_boarding_persons += passenger.group_size
        passenger.physical_motion_layer_id = "train_door:" + str(
            self.spec.source_element_id or self.facility_id
        )
        passenger.begin_facility_service(self.spec)
        passenger.passive_facility_service = True
        passenger.set_target(
            end_position,
            goal_kind="being_served",
            goal_label=self.spec.label,
            facility_id=self.spec.facility_id,
            stage=self.spec.stage,
        )
        event = FacilityServiceEvent(
            event_id=event_id,
            facility_id=self.facility_id,
            facility_kind=FacilityKind.TRAIN_DOOR.value,
            mode=self.spec.stage,
            passenger_ids=(int(passenger.unique_id),),
            start_time=start_time,
            board_end_time=end_time,
            arrive_time=end_time,
            end_time=end_time,
            start_position=start_position,
            end_position=end_position,
            commit_time=float(self.model.current_time_seconds),
            direction=self.portal_direction,
            from_level=self.portal_entry_level_id,
            to_level=self.portal_exit_level_id,
        )
        record_pending = getattr(
            self.model,
            "record_pending_facility_service_event",
            self.model.record_facility_service_event,
        )
        record_pending(event)
        self.active_boardings.append(
            ActiveDoorBoarding(
                passenger=passenger,
                event_id=event_id,
                start_position=start_position,
                end_position=end_position,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=duration_seconds,
                train=train,
                train_arrival_sequence=int(train.arrival_sequence),
            )
        )
        for approaching, platform, target in approach_relocations:
            if approaching not in platform.waiting:
                platform.waiting.append(approaching)
            approaching.state = AgentState.WAITING_PLATFORM.value
            approaching.set_target(
                target,
                goal_kind="waiting",
                goal_label="active train-door crossing wait",
            )
            approaching.passive_layout_motion_step = None
            approaching.passive_layout_motion_target = None
            approaching.passive_layout_motion_speed_mps = None
        # ``step`` lays out the queue before it admits the head.  A persistent
        # movement backend consumes those layout requests later in the same
        # interval, after the head has begun its swept crossing.  Cancel every
        # follower request now; otherwise a follower can enter the newly owned
        # crossing corridor and mutually block the rider until train close.
        for queued in self.queue:
            queued.passive_layout_motion_step = None
            queued.passive_layout_motion_target = None
            queued.passive_layout_motion_speed_mps = None

    def _reserve_active_crossing_waits(
        self,
        rider: PassengerAgent,
    ) -> tuple[tuple[PassengerAgent, PlatformAgent, tuple[float, float]], ...]:
        """Relocate pending approach owners before the crossing becomes active."""

        stage = self.spec.stage
        relocations: list[
            tuple[PassengerAgent, PlatformAgent, tuple[float, float]]
        ] = []
        for approaching in tuple(self.model.passengers):
            if (
                approaching is rider
                or approaching in self.queue
                or getattr(
                    approaching,
                    "facility_approach_facility_ids_by_stage",
                    {},
                ).get(stage)
                != self.facility_id
            ):
                continue
            platform = self.model.platform_for_passenger(approaching)
            if platform is None:
                platform = next(
                    (
                        candidate
                        for candidate in self.model.platforms
                        if candidate.platform_id == self.spec.platform_id
                    ),
                    None,
                )
            if platform is None:
                continue
            approaching.assigned_platform_id = platform.platform_id
            approaching.assigned_line_id = platform.line_id
            approaching.assigned_direction = platform.direction
            target = self.model._reserve_platform_waiting_slot(
                approaching,
                platform,
            )
            self._crossing_waiting_passenger_ids.add(int(approaching.unique_id))
            relocations.append((approaching, platform, target))
        return tuple(relocations)

    def _resume_crossing_waiters(self) -> None:
        """Retry durable FIFO owners as soon as the swept crossing clears.

        The platform scheduler runs before train-door completion.  Waiting for
        its next train-available poll can therefore miss the close boundary
        and strand a passenger whose approach was moved aside for the active
        body.  The physical crossing-clear fact is the precise retry trigger.
        """

        if self.active_boardings or not self._crossing_waiting_passenger_ids:
            return
        passengers_by_id = {
            int(passenger.unique_id): passenger
            for passenger in self.model.passengers
            if passenger.unique_id is not None
        }
        stage = self.spec.stage
        for passenger_id in tuple(self._crossing_waiting_passenger_ids):
            passenger = passengers_by_id.get(passenger_id)
            if passenger is None or (
                getattr(
                    passenger,
                    "facility_approach_facility_ids_by_stage",
                    {},
                ).get(stage)
                != self.facility_id
            ):
                self._crossing_waiting_passenger_ids.discard(passenger_id)
                continue
            self.model.goal_coordinator.poll(passenger)
            if (
                passenger.state != AgentState.WAITING_PLATFORM.value
                or getattr(
                    passenger,
                    "facility_approach_facility_ids_by_stage",
                    {},
                ).get(stage)
                != self.facility_id
            ):
                self._crossing_waiting_passenger_ids.discard(passenger_id)

    def _boarding_motion(
        self,
        passenger: PassengerAgent,
    ) -> tuple[tuple[float, float], tuple[float, float], float]:
        start = (float(passenger.pos[0]), float(passenger.pos[1]))
        end = self.model.clamp_position(self.portal_entry_position)
        distance = hypot(end[0] - start[0], end[1] - start[1])
        transaction_seconds = (
            60.0
            * max(1, int(passenger.group_size))
            / max(0.001, float(self.effective_service_persons_per_min))
        )
        scenario = self.model.scenario
        duration = minimum_jerk_duration_seconds(
            distance,
            minimum_seconds=transaction_seconds,
            maximum_speed_m_s=float(getattr(scenario, "jupedsim_desired_speed_mps", 1.2)),
            maximum_acceleration_m_s2=float(
                getattr(scenario, "cornering_acceleration_limit_m_s2", 3.2)
            ),
        )
        return start, end, duration

    def _boarding_path_is_clear(
        self,
        passenger: PassengerAgent,
        start: tuple[float, float],
        end: tuple[float, float],
        *,
        allow_pending_approaches: bool = False,
    ) -> bool:
        path = (
            ShapelyPoint(start)
            if hypot(end[0] - start[0], end[1] - start[1]) <= 1e-9
            else LineString((start, end))
        )
        minimum_distance = self._release_min_distance()
        excluded_ids = {int(passenger.unique_id)}
        if allow_pending_approaches:
            excluded_ids.update(
                int(approaching.unique_id)
                for approaching in self.model.passengers
                if approaching not in self.queue
                and getattr(
                    approaching,
                    "facility_approach_facility_ids_by_stage",
                    {},
                ).get(self.spec.stage)
                == self.facility_id
            )
        return all(
            path.distance(ShapelyPoint(position)) >= minimum_distance - 1e-9
            for position in external_body_positions(
                self.model,
                level_id=self.portal_entry_level_id,
                excluded_passenger_ids=excluded_ids,
            )
        )

    def _advance_active_boardings(self) -> None:
        if not self.active_boardings:
            return
        current_time = float(self.model.current_time_seconds)
        tick_seconds = self._process_interval_seconds()
        remaining: list[ActiveDoorBoarding] = []
        owns_passive_motion = getattr(
            self.model.movement_backend,
            "owns_passive_layout_motion",
            None,
        )
        backend_owns_motion = bool(
            callable(owns_passive_motion) and owns_passive_motion()
        )
        for active in self.active_boardings:
            if current_time + 1e-9 < active.start_time:
                remaining.append(active)
                continue
            elapsed_before = active.elapsed_seconds
            elapsed_after = min(
                active.duration_seconds,
                elapsed_before + tick_seconds,
            )
            proposed_position = self.model.clamp_position(
                self._position_at_elapsed(active, elapsed_after)
            )
            if backend_owns_motion and not self._boarding_path_is_clear(
                active.passenger,
                tuple(active.passenger.pos),
                proposed_position,
            ):
                self._delay_boarding(active, tick_seconds)
                remaining.append(active)
                continue
            active.elapsed_seconds = elapsed_after
            distance = hypot(
                proposed_position[0] - active.passenger.pos[0],
                proposed_position[1] - active.passenger.pos[1],
            )
            active.passenger.request_passive_layout_motion(
                proposed_position,
                requested_speed_mps=max(
                    0.001,
                    distance / max(1e-9, tick_seconds) * 1.25,
                ),
            )
            active.passenger.train_door_motion_episode_id = (
                f"train_door:{self.facility_id}:{active.event_id}:boarding"
            )
            if not backend_owns_motion:
                interval_start = max(
                    current_time,
                    active.start_time + elapsed_before,
                )
                interval_end = interval_start + (elapsed_after - elapsed_before)
                self._record_boarding_motion(
                    active,
                    interval_start_time_s=interval_start,
                    interval_end_time_s=interval_end,
                    elapsed_before_s=elapsed_before,
                    elapsed_after_s=elapsed_after,
                )
                active.passenger.pos = proposed_position
                if active.remaining_seconds <= 1e-9:
                    self._finish_boarding(active)
                    continue
            remaining.append(active)
        self.active_boardings = remaining
        self._resume_crossing_waiters()

    def commit_active_boardings_after_movement(self) -> None:
        """Commit only native JuPedSim door crossings at the interval end."""

        tick_seconds = self._process_interval_seconds()
        completion_time = float(self.model.current_time_seconds) + tick_seconds
        remaining: list[ActiveDoorBoarding] = []
        for active in self.active_boardings:
            if active.remaining_seconds > 1e-9:
                remaining.append(active)
                continue
            distance = hypot(
                active.passenger.pos[0] - active.end_position[0],
                active.passenger.pos[1] - active.end_position[1],
            )
            crossed_door_plane = self._has_crossed_service_entry(
                tuple(active.passenger.pos),
                active.start_position,
                active.end_position,
                tolerance=0.0,
                lane_half_width=max(
                    self._release_min_distance(),
                    float(self.model.scenario.jupedsim_agent_radius_units) * 1.5,
                ),
            )
            # A portal is a tactical capture region and an oriented crossing
            # plane, not an infinitesimal attractor.  Social-force integration
            # can carry a body a few centimetres beyond the nominal point.  A
            # Euclidean-only 2 cm obligation then waits forever even though
            # the body has physically crossed the door.  Accept either the
            # shared tactical tolerance or a correctly oriented plane
            # crossing, and retain the native coordinate as event truth.
            if distance > self._service_ready_radius() and not crossed_door_plane:
                self._delay_boarding(active, tick_seconds)
                remaining.append(active)
                continue
            active.end_time = completion_time
            self._set_boarding_event_completion(active, completion_time)
            recorder = getattr(self.model, "facility_motion_trace_recorder", None)
            if recorder is not None:
                recorder.record_positions(
                    time_seconds=completion_time,
                    level_id=str(active.passenger.physical_motion_layer_id),
                    phase="train_door_boarding",
                    episode_id=str(active.passenger.train_door_motion_episode_id),
                    positions={int(active.passenger.unique_id): tuple(active.passenger.pos)},
                )
            self._finish_boarding(active)
        self.active_boardings = remaining
        self._resume_crossing_waiters()

    def _set_boarding_event_completion(
        self,
        active: ActiveDoorBoarding,
        completion_time: float,
    ) -> None:
        for index, event in enumerate(self.model.facility_service_events):
            if event.event_id != active.event_id:
                continue
            self.model.facility_service_events[index] = replace(
                event,
                board_end_time=float(completion_time),
                arrive_time=float(completion_time),
                end_time=float(completion_time),
                end_position=tuple(active.passenger.pos),
            )
            break

    def _delay_boarding(self, active: ActiveDoorBoarding, delay_seconds: float) -> None:
        delay = max(0.0, float(delay_seconds))
        active.end_time += delay
        for index, event in enumerate(self.model.facility_service_events):
            if event.event_id != active.event_id:
                continue
            self.model.facility_service_events[index] = replace(
                event,
                board_end_time=event.board_end_time + delay,
                arrive_time=event.arrive_time + delay,
                end_time=event.end_time + delay,
            )
            break

    def _position_at_elapsed(
        self,
        active: ActiveDoorBoarding,
        elapsed_seconds: float,
    ) -> tuple[float, float]:
        ratio = (
            1.0
            if active.duration_seconds <= 1e-12
            else minimum_jerk_progress(elapsed_seconds / active.duration_seconds)
        )
        return (
            active.start_position[0] + (active.end_position[0] - active.start_position[0]) * ratio,
            active.start_position[1] + (active.end_position[1] - active.start_position[1]) * ratio,
        )

    def _record_boarding_motion(
        self,
        active: ActiveDoorBoarding,
        *,
        interval_start_time_s: float,
        interval_end_time_s: float,
        elapsed_before_s: float,
        elapsed_after_s: float,
    ) -> None:
        recorder = getattr(self.model, "facility_motion_trace_recorder", None)
        if recorder is None:
            return
        wall_duration = max(0.0, interval_end_time_s - interval_start_time_s)
        episode_id = f"train_door:{self.facility_id}:{int(active.event_id)}:boarding"
        layer_id = "train_door:" + str(self.spec.source_element_id or self.facility_id)
        for time_s in recorder.sample_times(
            interval_start_time_s,
            interval_end_time_s,
        ):
            wall_ratio = (
                1.0
                if wall_duration <= 1e-12
                else max(
                    0.0,
                    min(1.0, (float(time_s) - interval_start_time_s) / wall_duration),
                )
            )
            elapsed = elapsed_before_s + (elapsed_after_s - elapsed_before_s) * wall_ratio
            recorder.record_positions(
                time_seconds=time_s,
                level_id=layer_id,
                phase="train_door_boarding",
                episode_id=episode_id,
                positions={
                    int(active.passenger.unique_id): self.model.clamp_position(
                        self._position_at_elapsed(active, elapsed)
                    )
                },
            )

    def _finish_boarding(self, active: ActiveDoorBoarding) -> None:
        passenger = active.passenger
        train = active.train
        if train.arrival_sequence != active.train_arrival_sequence or not train.is_boarding:
            raise RuntimeError("train-door crossing outlived the train run that admitted it")
        train.reserved_boarding_persons = max(
            0,
            train.reserved_boarding_persons - passenger.group_size,
        )
        train.current_load_persons += passenger.group_size
        # JuPedSim owns the body coordinate through the crossing boundary.
        # Preserve its accepted endpoint instead of snapping backwards to the
        # nominal portal point after a small physical overshoot.
        passenger.pos = self.model.clamp_position(tuple(passenger.pos))
        passenger.passive_layout_motion_step = None
        passenger.passive_layout_motion_target = None
        passenger.passive_layout_motion_speed_mps = None
        passenger.train_door_motion_episode_id = None
        # Boarding is a terminal process boundary. Keep the process layer as
        # physical authority until Goal Graph removes the passenger from the
        # station; re-inserting a just-boarded body into the platform JuPedSim
        # session for one interval creates both a ghost collision and a native
        # removal/recreation race.
        self.served_persons += passenger.group_size
        observer = getattr(self.model, "observe_facility_service_completed", None)
        if callable(observer):
            observer(
                self.facility_id,
                (int(passenger.unique_id),),
                active.end_time,
                poll_immediately=True,
            )


__all__ = ["ActiveDoorBoarding", "BoardingDoorProcessAgent"]
