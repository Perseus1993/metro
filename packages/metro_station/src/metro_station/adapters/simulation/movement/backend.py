from __future__ import annotations

from collections.abc import Mapping
from math import hypot
from typing import TYPE_CHECKING

from shapely.geometry import Point as ShapelyPoint

from ..planning.plan import CROWD_INTERACTION_STATES, WALKING_STATES
from .contracts import (
    MovementRequest,
    MovementResult,
    _desired_speed_mps,
    _movement_suppressed_this_step,
)
from .initialization_clearance import (
    can_share_initialization_batch,
    clearance_adjusted_position,
    has_initialization_clearance,
)
from .jps_adapter import JuPedSimPlacementBlocked, JuPedSimRelocationRejected
from .movement_backend_contract import MovementBackend
from .native_facility_motion import NativeFacilityMotion
from .session_lifecycle import evict_ownerless_session
from .trajectory_trace import MovementTraceRecorder, empty_movement_trace

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from .jps_adapter import JuPedSimAdapter


class JuPedSimMovementBackend(MovementBackend):
    """Persistent JuPedSim movement backend.

    Mesa still owns queues, train events, and plan transitions. JuPedSim owns
    continuous walking physics for active walking agents. Each walkable level is
    represented by a long-lived JuPedSim simulation so agent state survives
    across Mesa ticks.
    """

    MOVEMENT_STATES = WALKING_STATES

    def __init__(self, adapter: JuPedSimAdapter, *, strict: bool = True) -> None:
        self.adapter = adapter
        self.strict = strict
        self.jps_step_count = 0
        self.jps_batch_count = 0
        self.missing_agent_count = 0
        self.recovered_agent_count = 0
        self.completed_agent_count = 0
        self.placement_blocked_count = 0
        self.degraded_hold_count = 0
        self._sessions = {}
        self._session_keys_by_passenger: dict[int, str | None] = {}
        self._episode_number_by_passenger: dict[int, int] = {}
        self._active_episode_ids: dict[int, str] = {}
        self._passive_episode_number_by_passenger: dict[int, int] = {}
        self._passive_episode_ids: dict[int, str] = {}
        self._passive_phase_by_passenger: dict[int, str] = {}
        self._model_identity: int | None = None
        self._movement_trace_recorder: MovementTraceRecorder | None = None
        self._movement_trace_disabled_reason = "simulation_not_started"
        self._pending_trace_commits: dict[
            int,
            tuple[float, float, tuple[float, float], str | None, str],
        ] = {}

    def move(self, passenger: PassengerAgent) -> MovementResult:
        results = self._move_passengers([passenger], sync_sessions=False)
        if not results:
            raise RuntimeError(f"JuPedSim produced no result for passenger {passenger.unique_id}.")
        return results[0][1]

    def step_all(
        self, passengers: list[PassengerAgent]
    ) -> list[tuple[PassengerAgent, MovementResult]]:
        eligible = [
            passenger
            for passenger in list(passengers)
            if passenger.state in self.MOVEMENT_STATES
            and not passenger.passive_facility_service
            and not _movement_suppressed_this_step(passenger)
        ]
        eligible_ids = {int(passenger.unique_id) for passenger in eligible}
        stationary_blockers = [
            passenger
            for passenger in passengers
            if int(passenger.unique_id) not in eligible_ids
            and passenger.current_level_id is not None
            and (
                getattr(passenger, "native_facility_motion", None) is not None
                or
                not passenger.passive_facility_service
                or getattr(passenger, "physical_motion_layer_id", None)
                in {None, passenger.current_level_id}
                or str(getattr(passenger, "physical_motion_layer_id", "")).startswith("train_door:")
            )
        ]
        return self._move_passengers(
            eligible,
            sync_sessions=True,
            stationary_blockers=stationary_blockers,
        )

    def place_passenger(
        self,
        passenger: PassengerAgent,
        position: tuple[float, float],
        *,
        target: tuple[float, float] | None = None,
        level_id: str | None = None,
    ) -> tuple[float, float]:
        if not self.adapter.status.available:
            raise RuntimeError(
                f"JuPedSim placement requested but unavailable: {self.adapter.status.message}"
            )

        model = passenger.model
        placement_target = target or passenger.target or position
        session_key = self._session_key_for_position(
            model,
            position,
            placement_target,
            level_id if level_id is not None else passenger.current_level_id,
        )
        passenger_id = int(passenger.unique_id)
        previous_key = self._session_keys_by_passenger.get(passenger_id)
        if previous_key != session_key:
            self._remove_from_session_key(passenger_id, previous_key)

        try:
            session = self._session_for_key(model, session_key)
            placed = session.place_agent(
                passenger_id=passenger_id,
                position=position,
                target=placement_target,
                desired_speed_mps=_desired_speed_mps(passenger),
            )
        except JuPedSimRelocationRejected:
            raise
        except Exception:
            if self.strict:
                raise
            return super().place_passenger(
                passenger,
                position,
                target=target,
                level_id=level_id,
            )

        self._session_keys_by_passenger[passenger_id] = session_key
        return model.clamp_position(placed)

    def resolve_placement(
        self,
        passenger: PassengerAgent,
        position: tuple[float, float],
        *,
        level_id: str | None = None,
    ) -> tuple[float, float]:
        if not self.adapter.status.available:
            raise RuntimeError(
                f"JuPedSim placement requested but unavailable: {self.adapter.status.message}"
            )
        model = passenger.model
        session_key = self._session_key_for_position(
            model,
            position,
            position,
            level_id if level_id is not None else passenger.current_level_id,
        )
        session = self._session_for_key(model, session_key)
        resolved = session.resolve_placement(
            passenger_id=int(passenger.unique_id),
            position=position,
            allow_relocation=True,
        )
        return model.clamp_position(resolved)

    def resolve_certified_placement(
        self,
        passenger: PassengerAgent,
        position: tuple[float, float],
        *,
        level_id: str | None = None,
    ) -> tuple[float, float]:
        """Validate an exact certificate cell; never search nearby points."""

        if not self.adapter.status.available:
            raise RuntimeError(
                f"JuPedSim placement requested but unavailable: {self.adapter.status.message}"
            )
        model = passenger.model
        session_key = self._session_key_for_position(
            model,
            position,
            position,
            level_id if level_id is not None else passenger.current_level_id,
        )
        session = self._session_for_key(model, session_key)
        resolved = session.resolve_placement(
            passenger_id=int(passenger.unique_id),
            position=position,
            allow_relocation=False,
        )
        return model.clamp_position(resolved)

    def remove_passenger(self, passenger: PassengerAgent) -> None:
        passenger_id = int(passenger.unique_id)
        session_key = self._session_keys_by_passenger.pop(passenger_id, None)
        self._active_episode_ids.pop(passenger_id, None)
        self._passive_episode_ids.pop(passenger_id, None)
        self._passive_phase_by_passenger.pop(passenger_id, None)
        self._remove_from_session_key(passenger_id, session_key)

    def active_passenger_ids(self) -> set[int]:
        passenger_ids = set(self._session_keys_by_passenger)
        for session in self._sessions.values():
            active_ids = getattr(session, "active_passenger_ids", None)
            if callable(active_ids):
                passenger_ids.update(int(value) for value in active_ids())
        return passenger_ids

    def owns_passive_layout_motion(self) -> bool:
        return True

    def owns_continuous_facility_service_motion(
        self,
        *,
        facility_kind: str,
        entry_level_id: str | None,
        exit_level_id: str | None,
    ) -> bool:
        # Gates and train-door crossings are same-floor crowd interactions.
        # Keep both native bodies in the persistent JuPedSim session so an
        # admission transaction never creates a collision-invisible interval.
        # Elevator landing embed/de-embed segments use the same native body
        # contract; only the enclosed shaft travel leaves the level session.
        return (
            (
                str(facility_kind) in {"gate", "train_door"}
                and entry_level_id is not None
                and entry_level_id == exit_level_id
            )
            or (str(facility_kind) == "elevator" and entry_level_id is not None)
        )

    def movement_trace(self) -> dict[str, object]:
        if self._movement_trace_recorder is None:
            return empty_movement_trace(reason=self._movement_trace_disabled_reason)
        return self._movement_trace_recorder.as_dict()

    def record_facility_motion_boundary(
        self,
        passenger: PassengerAgent,
        *,
        time_seconds: float,
        phase: str,
    ) -> None:
        passenger_id = int(passenger.unique_id)
        # Facility completion runs before the movement phase of a Mesa tick.
        # With a coarse tick a gate body can reach its native endpoint before
        # any session has needed to iterate, so the recorder may legitimately
        # still be uninitialised even though the passive episode is active.
        # Boundary publication is itself a trace-producing operation and must
        # therefore acquire the recorder rather than depend on movement-loop
        # call order.
        recorder = self._movement_trace_recorder_for(passenger.model)
        episode_id = self._passive_episode_ids.get(passenger_id)
        # A deliberately non-research clock does not publish a high-rate
        # movement trace.  That is an explicit clock capability, not a lost
        # facility episode, so keep the physical simulation running and let
        # the exported trace declare its disabled reason.
        if recorder is None:
            return
        if episode_id is None:
            if self.strict:
                raise RuntimeError(
                    "JuPedSim facility boundary has no active movement-trace "
                    f"episode: passenger_id={passenger_id} phase={phase!r}"
                )
            return
        recorder.record_positions(
            time_seconds=float(time_seconds),
            level_id=passenger.current_level_id,
            positions={passenger_id: tuple(passenger.pos)},
            episode_ids={passenger_id: episode_id},
            phases_by_passenger={passenger_id: str(phase)},
        )

    def commit_movement_result(
        self,
        passenger: PassengerAgent,
        result: MovementResult,
    ) -> None:
        pending = self._pending_trace_commits.pop(int(passenger.unique_id), None)
        recorder = self._movement_trace_recorder
        if pending is not None and recorder is not None:
            tick_start, tick_end, proposed, level_id, episode_id = pending
            if (
                hypot(
                    result.position[0] - proposed[0],
                    result.position[1] - proposed[1],
                )
                > 1e-9
            ):
                recorder.discard_passenger_samples_after(
                    int(passenger.unique_id),
                    time_seconds=tick_start,
                )
                recorder.record_positions(
                    time_seconds=tick_end,
                    level_id=level_id,
                    positions={int(passenger.unique_id): tuple(result.position)},
                    episode_ids={int(passenger.unique_id): episode_id},
                )

        if result.reached:
            # A Waypoint stage keeps the arriving native body alive (unlike an
            # Exit stage). Switch that exact body into a waiting stage before
            # Mesa advances its Goal Graph state, preserving native identity
            # and continuous collision authority at queue capture.
            level_id = passenger.current_level_id
            session_key = self._session_key_for_position(
                passenger.model,
                tuple(result.position),
                tuple(result.position),
                level_id,
            )
            session = self._session_for_key(passenger.model, session_key)
            session.ensure_waiting_agent(
                passenger_id=int(passenger.unique_id),
                position=tuple(result.position),
                target=tuple(result.position),
                desired_speed_mps=0.001,
            )
            self._session_keys_by_passenger[int(passenger.unique_id)] = session_key

    def on_walkable_geometry_changed(self, model: object) -> None:
        self._sessions.clear()
        self._session_keys_by_passenger.clear()
        self._active_episode_ids.clear()
        self._passive_episode_ids.clear()
        self._passive_phase_by_passenger.clear()
        self._pending_trace_commits.clear()

    def _move_passengers(
        self,
        passengers: list[PassengerAgent],
        *,
        sync_sessions: bool,
        stationary_blockers: list[PassengerAgent] | None = None,
    ) -> list[tuple[PassengerAgent, MovementResult]]:
        if not self.adapter.status.available:
            raise RuntimeError(
                f"JuPedSim movement requested but unavailable: {self.adapter.status.message}"
            )

        blockers = list(stationary_blockers or ())
        if sync_sessions:
            self._sync_session_membership([*passengers, *blockers])

        passive_bodies_to_commit_by_session: dict[
            str | None,
            list[tuple[PassengerAgent, tuple[float, float], bool]],
        ] = {}
        blockers_by_session: dict[str | None, list[PassengerAgent]] = {}
        sessions_to_iterate: set[str | None] = set()
        for blocker in blockers:
            blocker_id = int(blocker.unique_id)
            trace_authority_deferred = _movement_suppressed_this_step(blocker)
            native_motion = self._native_facility_motion(blocker)
            # Queue/service bodies remain in JuPedSim for collision avoidance,
            # but they are no longer part of a walking episode. Ending the
            # trace episode here prevents a later cross-level release from
            # reusing the pre-service episode id on another level.
            self._active_episode_ids.pop(blocker_id, None)
            self._pending_trace_commits.pop(blocker_id, None)
            session_key = self._session_key_for(blocker)
            previous_key = self._session_keys_by_passenger.get(blocker_id)
            if previous_key != session_key:
                self._remove_from_session_key(blocker_id, previous_key)
            session = self._session_for_key(blocker.model, session_key)
            layout_target, layout_speed = (
                (None, 0.001) if trace_authority_deferred else self._passive_layout_request(blocker)
            )
            waiting_target = (
                tuple(blocker.pos)
                if layout_target is None
                or (
                    native_motion is not None
                    and native_motion.active_after_seconds > 1e-9
                )
                else layout_target
            )
            physical_layer = str(
                getattr(blocker, "physical_motion_layer_id", "") or ""
            )
            try:
                session.ensure_waiting_agent(
                    passenger_id=blocker_id,
                    position=tuple(blocker.pos),
                    target=waiting_target,
                    desired_speed_mps=layout_speed,
                    # A train-door event declares a centimetre-audited portal
                    # endpoint. Keep the native body moving until it reaches
                    # that obligation; ordinary queue compaction retains the
                    # body-radius-derived deadband that prevents idle jitter.
                    stop_tolerance_m=(
                        native_motion.endpoint_tolerance_m
                        if native_motion is not None
                        else 0.01
                        if physical_layer.startswith("train_door:")
                        else None
                    ),
                )
            except JuPedSimPlacementBlocked:
                self.placement_blocked_count += 1
                # A passive body must never remain in snapshots while being
                # absent from the collision world. Endpoint hand-off retains
                # ordinary arrivals above; any remaining insertion failure is
                # a genuine upstream admission invariant violation.
                self._session_keys_by_passenger.pop(blocker_id, None)
                self._active_episode_ids.pop(blocker_id, None)
                raise
            self._session_keys_by_passenger[blocker_id] = session_key
            if trace_authority_deferred:
                # A connector/process hand-off may require JuPedSim to project
                # the released body by a few millimetres to satisfy native
                # clearance.  The native body is already the collision truth,
                # so commit that accepted coordinate to the end-of-interval
                # snapshot even though this interval intentionally emits no
                # movement-trace episode.  Keeping the nominal release point
                # in Mesa would publish two physical positions at the same
                # timestamp on the following interval.
                native_position = session.position_for(blocker_id)
                if native_position is None:
                    raise RuntimeError(
                        "JuPedSim lost a suppressed process-handoff body "
                        f"during placement: passenger_id={blocker_id}"
                    )
                blocker.pos = blocker.model.clamp_position(native_position)
                blocker.last_walk_velocity_mps = (0.0, 0.0)
                blocker.passive_layout_committed_delta = None
            phase = (
                native_motion.phase
                if native_motion is not None
                else "train_door_boarding"
                if physical_layer.startswith("train_door:")
                else "same_floor_facility"
                if blocker.passive_facility_service
                else "passive_layout"
            )
            if (
                not trace_authority_deferred
                and (
                    self._passive_phase_by_passenger.get(blocker_id) != phase
                    or (
                        native_motion is not None
                        and self._passive_episode_ids.get(blocker_id)
                        != native_motion.episode_id
                    )
                )
            ):
                episode_number = self._passive_episode_number_by_passenger.get(blocker_id, 0) + 1
                self._passive_episode_number_by_passenger[blocker_id] = episode_number
                self._passive_episode_ids[blocker_id] = (
                    (native_motion.episode_id if native_motion is not None else "")
                    or str(getattr(blocker, "train_door_motion_episode_id", "") or "")
                    or f"{blocker_id}:passive:{episode_number}"
                )
                self._passive_phase_by_passenger[blocker_id] = phase
                blocker.native_facility_arrival_time_seconds = None
            # A suppressed passenger has just crossed a discrete process
            # boundary during this Mesa interval.  Retain its native collision
            # body immediately, but leave trajectory authority with the prior
            # boundary snapshot until the next interval.  Publishing the new
            # floor coordinate at the same timestamp as the connector snapshot
            # would create two simultaneous physical truths.
            if not trace_authority_deferred:
                blockers_by_session.setdefault(session_key, []).append(blocker)
                # Waiting bodies can still move because their active waiting
                # stage was projected to safe geometry or because other crowd
                # bodies exert pressure.  Commit every native passive body
                # whenever its session advances, even when the process layer
                # did not issue a fresh compaction request this tick.
            # Even a trace-suppressed hand-off body participates in this
            # session's collision step.  Commit its final native coordinate
            # to Mesa without creating a movement episode so the snapshot and
            # next boundary sample retain one position authority.
            passive_bodies_to_commit_by_session.setdefault(
                session_key,
                [],
            ).append((blocker, tuple(blocker.pos), trace_authority_deferred))
            if layout_target is not None or native_motion is not None:
                sessions_to_iterate.add(session_key)

        result_by_id: dict[int, MovementResult] = {}
        tracked: list[tuple[PassengerAgent, str | None]] = []
        reached_waiters: list[tuple[PassengerAgent, str | None, MovementRequest]] = []
        for passenger in passengers:
            if passenger.state not in self.MOVEMENT_STATES:
                raise RuntimeError(
                    f"JuPedSim cannot move passenger {passenger.unique_id} in state "
                    f"{passenger.state!r}."
                )
            request = MovementRequest.from_passenger(passenger)
            self._passive_episode_ids.pop(request.passenger_id, None)
            self._passive_phase_by_passenger.pop(request.passenger_id, None)
            reached = self._finish_if_already_at_target(passenger)
            if reached is not None:
                # Finish by switching the existing native body to a waiting
                # journey, never delete/recreate it inside one tick.  It stays
                # collision-visible while other walkers advance, but this
                # hand-off interval is not emitted as a second trajectory
                # authority.  Its final native coordinate is committed below.
                session_key = self._session_key_for(passenger)
                previous_key = self._session_keys_by_passenger.get(request.passenger_id)
                if previous_key != session_key:
                    self._remove_from_session_key(
                        request.passenger_id,
                        previous_key,
                    )
                session = self._session_for_key(passenger.model, session_key)
                session.ensure_waiting_agent(
                    passenger_id=request.passenger_id,
                    position=request.position,
                    target=request.position,
                    desired_speed_mps=0.001,
                )
                self._session_keys_by_passenger[request.passenger_id] = session_key
                self._active_episode_ids.pop(request.passenger_id, None)
                reached_waiters.append((passenger, session_key, request))
                continue

            session_key = self._session_key_for(passenger)
            previous_key = self._session_keys_by_passenger.get(request.passenger_id)
            if previous_key != session_key:
                self._remove_from_session_key(request.passenger_id, previous_key)

            try:
                session = self._session_for_key(passenger.model, session_key)
                session.ensure_agent(
                    passenger_id=request.passenger_id,
                    position=request.position,
                    target=request.target,
                    target_radius=request.radius,
                    desired_speed_mps=request.desired_speed_mps,
                )
            except JuPedSimPlacementBlocked:
                # Waiting for physical clearance is a valid zero-motion state.
                # Moving the requested coordinate to make insertion succeed
                # would create a discontinuity before the first trace sample.
                self.placement_blocked_count += 1
                self._active_episode_ids.pop(request.passenger_id, None)
                result_by_id[request.passenger_id] = MovementResult(
                    request.passenger_id,
                    request.position,
                    reached=False,
                )
                continue
            except Exception as exc:
                if self.strict:
                    raise RuntimeError(
                        "JuPedSim persistent tick failed for passenger "
                        f"{passenger.unique_id} target=({request.target[0]:.3f}, "
                        f"{request.target[1]:.3f})"
                    ) from exc
                result_by_id[request.passenger_id] = self._hold_on_backend_failure(
                    passenger,
                    reason="ensure_agent_failed",
                    error=exc,
                    session_key=session_key,
                )
                continue

            episode_id = self._active_episode_ids.get(request.passenger_id)
            if episode_id is None or previous_key != session_key:
                episode_number = self._episode_number_by_passenger.get(request.passenger_id, 0) + 1
                self._episode_number_by_passenger[request.passenger_id] = episode_number
                episode_id = f"{request.passenger_id}:{episode_number}"
                self._active_episode_ids[request.passenger_id] = episode_id
            session.set_episode_id(request.passenger_id, episode_id)
            self._session_keys_by_passenger[request.passenger_id] = session_key
            sessions_to_iterate.add(session_key)
            tracked.append((passenger, session_key))

        maintenance_session_keys = {
            session_key
            for session_key, session in self._sessions.items()
            if session_key not in sessions_to_iterate
            and callable(
                has_pending_removals := getattr(
                    session,
                    "has_pending_removals",
                    None,
                )
            )
            and has_pending_removals()
        }
        sessions_to_process = sessions_to_iterate | maintenance_session_keys
        if sessions_to_process:
            model = (
                tracked[0][0] if tracked else blockers[0] if blockers else reached_waiters[0][0]
            ).model
            recorder = self._movement_trace_recorder_for(model)
            for session_key in sessions_to_process:
                session = self._sessions[session_key]
                tracked_for_session = [
                    passenger
                    for passenger, tracked_session_key in tracked
                    if tracked_session_key == session_key
                ]
                blockers_for_session = blockers_by_session.get(session_key, [])
                native_blockers_for_session = [
                    blocker
                    for blocker, _position, _trace_deferred in (
                        passive_bodies_to_commit_by_session.get(session_key, [])
                    )
                    if self._native_facility_motion(blocker) is not None
                ]
                tick_start_seconds = float(model.current_time_seconds)
                dt_seconds = float(model.simulation_clock.jupedsim_dt_seconds)
                pending_native_activation = {
                    int(blocker.unique_id): motion
                    for blocker in native_blockers_for_session
                    if (motion := self._native_facility_motion(blocker)) is not None
                    and motion.active_after_seconds > 1e-9
                }

                def activate_native_facility_motion(iteration: int) -> None:
                    elapsed_before = (int(iteration) - 1) * dt_seconds
                    for blocker in native_blockers_for_session:
                        passenger_id = int(blocker.unique_id)
                        motion = pending_native_activation.get(passenger_id)
                        if motion is None or (
                            elapsed_before + 1e-9 < motion.active_after_seconds
                        ):
                            continue
                        native_position = session.position_for(passenger_id)
                        if native_position is None:
                            raise RuntimeError(
                                "native facility body disappeared before its "
                                f"activation boundary: passenger_id={passenger_id}"
                            )
                        session.ensure_waiting_agent(
                            passenger_id=passenger_id,
                            position=native_position,
                            target=motion.target,
                            desired_speed_mps=motion.desired_speed_mps,
                            stop_tolerance_m=motion.endpoint_tolerance_m,
                        )
                        pending_native_activation.pop(passenger_id, None)

                def observe_native_arrivals(
                    iteration: int,
                    positions: Mapping[int, tuple[float, float]],
                ) -> None:
                    for blocker in native_blockers_for_session:
                        motion = self._native_facility_motion(blocker)
                        if motion is None or not motion.terminal:
                            continue
                        if blocker.native_facility_arrival_time_seconds is not None:
                            continue
                        position = positions.get(int(blocker.unique_id))
                        if position is None:
                            continue
                        if hypot(
                            position[0] - motion.target[0],
                            position[1] - motion.target[1],
                        ) > motion.endpoint_tolerance_m + 1e-9:
                            continue
                        blocker.native_facility_arrival_time_seconds = (
                            tick_start_seconds + iteration * dt_seconds
                        )

                native_iteration_observers = (
                    {
                        "pre_iteration_observer": activate_native_facility_motion,
                        "post_iteration_observer": observe_native_arrivals,
                    }
                    if native_blockers_for_session
                    else {}
                )
                if recorder is None:
                    session.iterate(
                        1
                        if session_key in maintenance_session_keys
                        else model.simulation_clock.jupedsim_iterations_per_tick,
                        **native_iteration_observers,
                    )
                else:
                    # Record the physical start of each newly active walking
                    # episode. Continuing agents already have a sample at this
                    # boundary and the recorder de-duplicates it. Without this
                    # anchor, placement correction during episode creation is
                    # invisible to the kinematic gate.
                    tracked_ids = {int(passenger.unique_id) for passenger in tracked_for_session}
                    all_blocker_ids = {
                        int(passenger.unique_id) for passenger in blockers_for_session
                    }
                    delayed_native_activation_by_id = {
                        int(blocker.unique_id): motion.active_after_seconds
                        for blocker in blockers_for_session
                        if (motion := self._native_facility_motion(blocker)) is not None
                        and motion.active_after_seconds > 1e-9
                    }
                    blocker_ids = all_blocker_ids - set(
                        delayed_native_activation_by_id
                    )
                    observed_ids = tracked_ids | blocker_ids
                    start_positions = {}
                    for passenger in (*tracked_for_session, *blockers_for_session):
                        passenger_id = int(passenger.unique_id)
                        native_position = session.position_for(passenger_id)
                        start_positions[passenger_id] = tuple(
                            passenger.pos if native_position is None else native_position
                        )
                    episode_ids = {
                        passenger_id: episode_id
                        for passenger_id, episode_id in (session.episode_ids_by_passenger().items())
                        if passenger_id in tracked_ids
                    }
                    episode_ids.update(
                        {
                            passenger_id: self._passive_episode_ids[passenger_id]
                            for passenger_id in all_blocker_ids
                        }
                    )
                    phases = {
                        **{passenger_id: "walking" for passenger_id in tracked_ids},
                        **{
                            passenger_id: self._passive_phase_by_passenger[passenger_id]
                            for passenger_id in all_blocker_ids
                        },
                    }
                    recorder.record_positions(
                        time_seconds=tick_start_seconds,
                        level_id=session_key,
                        positions={
                            passenger_id: position
                            for passenger_id, position in start_positions.items()
                            if passenger_id in observed_ids
                        },
                        episode_ids=episode_ids,
                        phases_by_passenger=phases,
                    )
                    tick_duration_seconds = float(
                        getattr(
                            model.simulation_clock,
                            "jupedsim_elapsed_seconds_per_tick",
                            model.simulation_clock.jupedsim_iterations_per_tick
                            * dt_seconds,
                        )
                    )
                    for passenger_id, active_after_seconds in sorted(
                        delayed_native_activation_by_id.items()
                    ):
                        if active_after_seconds > tick_duration_seconds + 1e-9:
                            continue
                        recorder.record_positions(
                            time_seconds=(
                                tick_start_seconds + active_after_seconds
                            ),
                            level_id=session_key,
                            positions={passenger_id: start_positions[passenger_id]},
                            episode_ids=episode_ids,
                            phases_by_passenger=phases,
                        )

                    train_door_blockers = tuple(
                        blocker
                        for blocker in blockers_for_session
                        if str(getattr(blocker, "physical_motion_layer_id", "") or "").startswith(
                            "train_door:"
                        )
                    )
                    facility_recorder = getattr(
                        model,
                        "facility_motion_trace_recorder",
                        None,
                    )

                    def record_train_door_positions(
                        time_seconds: float,
                        positions: Mapping[int, tuple[float, float]],
                    ) -> None:
                        if facility_recorder is None:
                            return
                        for blocker in train_door_blockers:
                            passenger_id = int(blocker.unique_id)
                            position = positions.get(passenger_id)
                            episode_id = str(
                                getattr(
                                    blocker,
                                    "train_door_motion_episode_id",
                                    "",
                                )
                                or ""
                            )
                            if position is None or not episode_id:
                                continue
                            facility_recorder.record_positions(
                                time_seconds=float(time_seconds),
                                level_id=str(blocker.physical_motion_layer_id),
                                phase="train_door_boarding",
                                episode_id=episode_id,
                                positions={passenger_id: position},
                            )

                    record_train_door_positions(
                        tick_start_seconds,
                        start_positions,
                    )

                    def observe(
                        iteration: int,
                        positions: Mapping[int, tuple[float, float]],
                        *,
                        level_id: str | None = session_key,
                    ) -> None:
                        elapsed_seconds = iteration * dt_seconds
                        active_blocker_ids = blocker_ids | {
                            passenger_id
                            for passenger_id, active_after_seconds in (
                                delayed_native_activation_by_id.items()
                            )
                            if elapsed_seconds + 1e-9 >= active_after_seconds
                        }
                        active_observed_ids = tracked_ids | active_blocker_ids
                        recorder.record_positions(
                            time_seconds=tick_start_seconds + iteration * dt_seconds,
                            level_id=level_id,
                            positions={
                                passenger_id: position
                                for passenger_id, position in positions.items()
                                if passenger_id in active_observed_ids
                            },
                            episode_ids=episode_ids,
                            phases_by_passenger=phases,
                        )
                        record_train_door_positions(
                            tick_start_seconds + iteration * dt_seconds,
                            positions,
                        )

                    session.iterate(
                        (
                            1
                            if session_key in maintenance_session_keys
                            else model.simulation_clock.jupedsim_iterations_per_tick
                        ),
                        sample_every_nth_iteration=recorder.every_nth_iteration,
                        sample_observer=observe,
                        **native_iteration_observers,
                    )
                    for passenger in tracked_for_session:
                        record = session.removal_record_for(int(passenger.unique_id))
                        if record is None:
                            continue
                        removal_time = tick_start_seconds + record.last_position_after_seconds
                        recorder.record_positions(
                            time_seconds=removal_time,
                            level_id=session_key,
                            positions={
                                int(passenger.unique_id): record.last_authoritative_position
                            },
                            episode_ids={int(passenger.unique_id): record.episode_id},
                            phases_by_passenger={int(passenger.unique_id): "walking"},
                        )
                for (
                    blocker,
                    position_before,
                    trace_authority_deferred,
                ) in passive_bodies_to_commit_by_session.get(
                    session_key,
                    (),
                ):
                    physical_position = session.position_for(int(blocker.unique_id))
                    if physical_position is None:
                        continue
                    committed = blocker.model.clamp_position(physical_position)
                    tick_seconds = max(
                        1e-9,
                        float(blocker.model.scenario.tick_seconds),
                    )
                    if trace_authority_deferred:
                        blocker.last_walk_velocity_mps = (0.0, 0.0)
                        blocker.passive_layout_committed_delta = None
                    else:
                        blocker.last_walk_velocity_mps = (
                            (committed[0] - position_before[0]) / tick_seconds,
                            (committed[1] - position_before[1]) / tick_seconds,
                        )
                        blocker.passive_layout_committed_delta = (
                            committed[0] - position_before[0],
                            committed[1] - position_before[1],
                        )
                    blocker.pos = committed
                self.jps_batch_count += 1

        for _passenger, session_key, request in reached_waiters:
            session = self._sessions.get(session_key)
            native_position = (
                None if session is None else session.position_for(request.passenger_id)
            )
            if native_position is None:
                raise RuntimeError(
                    "JuPedSim lost an exact-target waiting body during the "
                    f"same movement batch: passenger_id={request.passenger_id}"
                )
            result_by_id[request.passenger_id] = MovementResult(
                request.passenger_id,
                _passenger.model.clamp_position(native_position),
                reached=True,
            )

        for passenger, session_key in tracked:
            request = MovementRequest.from_passenger(passenger)
            session = self._sessions.get(session_key)
            position = session.position_for(request.passenger_id) if session is not None else None
            removal_record = None
            if position is None:
                removal_record = (
                    session.removal_record_for(request.passenger_id, consume=True)
                    if session is not None
                    else None
                )
                if removal_record is not None and removal_record.reached:
                    self.completed_agent_count += 1
                    self._session_keys_by_passenger.pop(request.passenger_id, None)
                    self._active_episode_ids.pop(request.passenger_id, None)
                    next_position = passenger.model.clamp_position(
                        removal_record.last_authoritative_position
                    )
                else:
                    self.missing_agent_count += 1
                    recovery_request = request
                    if removal_record is not None:
                        recovery_request = MovementRequest(
                            passenger_id=request.passenger_id,
                            position=removal_record.last_authoritative_position,
                            target=request.target,
                            radius=request.radius,
                            level=request.level,
                            desired_speed_mps=request.desired_speed_mps,
                        )
                    self._active_episode_ids.pop(request.passenger_id, None)
                    recovered = self._recover_missing_agent(
                        passenger,
                        session_key=session_key,
                        request=recovery_request,
                    )
                    if recovered is None:
                        self._session_keys_by_passenger.pop(request.passenger_id, None)
                        if self.strict:
                            raise RuntimeError(
                                "JuPedSim lost a tracked passenger after iteration and "
                                "bounded recovery failed: "
                                f"passenger_id={request.passenger_id} session={session_key!r}"
                            )
                        result_by_id[request.passenger_id] = self._hold_on_backend_failure(
                            passenger,
                            reason="bounded_recovery_failed",
                            session_key=session_key,
                        )
                        continue
                    next_position = recovered
            else:
                next_position = passenger.model.clamp_position(position)
            recorder = self._movement_trace_recorder
            episode_id = self._active_episode_ids.get(request.passenger_id)
            if episode_id is None and removal_record is not None:
                episode_id = removal_record.episode_id
            if recorder is not None and episode_id is not None:
                self._pending_trace_commits[request.passenger_id] = (
                    float(passenger.model.current_time_seconds),
                    float(passenger.model.current_time_seconds)
                    + float(passenger.model.scenario.tick_seconds),
                    tuple(next_position),
                    session_key,
                    episode_id,
                )
            self.jps_step_count += 1
            projected_arrival = getattr(session, "waypoint_arrival_held", None)
            reached = bool(
                callable(projected_arrival) and projected_arrival(request.passenger_id)
            ) or (
                hypot(
                    request.target[0] - next_position[0],
                    request.target[1] - next_position[1],
                )
                <= request.radius
            )
            if reached:
                # A local waypoint is a scientific episode boundary even when
                # Mesa keeps the passenger in a walking state while its goal
                # coordinator selects the next route segment.  Reusing the
                # old episode after stationary decision time would publish a
                # false multi-second sampling gap inside one walk episode.
                self._active_episode_ids.pop(request.passenger_id, None)
            result_by_id[request.passenger_id] = MovementResult(
                request.passenger_id,
                next_position,
                reached=reached,
            )

        return [
            (passenger, result_by_id[int(passenger.unique_id)])
            for passenger in passengers
            if int(passenger.unique_id) in result_by_id
        ]

    @staticmethod
    def _passive_layout_request(
        passenger: PassengerAgent,
    ) -> tuple[tuple[float, float] | None, float]:
        native_motion = JuPedSimMovementBackend._native_facility_motion(passenger)
        if native_motion is not None:
            return native_motion.target, native_motion.desired_speed_mps
        if getattr(passenger, "passive_layout_motion_step", None) != int(
            passenger.model.step_index
        ):
            return None, 0.001
        target = getattr(passenger, "passive_layout_motion_target", None)
        speed = getattr(passenger, "passive_layout_motion_speed_mps", None)
        if target is None or speed is None:
            return None, 0.001
        return (float(target[0]), float(target[1])), max(0.001, float(speed))

    @staticmethod
    def _native_facility_motion(
        passenger: PassengerAgent,
    ) -> NativeFacilityMotion | None:
        motion = getattr(passenger, "native_facility_motion", None)
        if motion is None:
            return None
        if not isinstance(motion, NativeFacilityMotion):
            raise TypeError(
                "passenger.native_facility_motion must be NativeFacilityMotion"
            )
        return motion

    def _recover_missing_agent(
        self,
        passenger: PassengerAgent,
        *,
        session_key: str | None,
        request: MovementRequest,
    ) -> tuple[float, float] | None:
        session = self._sessions.get(session_key)
        if session is None:
            return None
        try:
            session.ensure_agent(
                passenger_id=request.passenger_id,
                position=request.position,
                target=request.target,
                target_radius=request.radius,
                desired_speed_mps=request.desired_speed_mps,
            )
            recovered = session.position_for(request.passenger_id)
        except Exception:
            return None
        if recovered is None:
            return None
        maximum_displacement = max(
            request.radius,
            float(passenger.model.scenario.jupedsim_agent_radius_units) * 2.5,
        )
        if (
            hypot(recovered[0] - request.position[0], recovered[1] - request.position[1])
            > maximum_displacement + 1e-9
        ):
            session.remove_passenger(request.passenger_id)
            return None
        self._session_keys_by_passenger[request.passenger_id] = session_key
        episode_number = self._episode_number_by_passenger.get(request.passenger_id, 0) + 1
        self._episode_number_by_passenger[request.passenger_id] = episode_number
        episode_id = f"{request.passenger_id}:{episode_number}"
        self._active_episode_ids[request.passenger_id] = episode_id
        session.set_episode_id(request.passenger_id, episode_id)
        self.recovered_agent_count += 1
        return passenger.model.clamp_position(recovered)

    def _sync_session_membership(self, passengers: list[PassengerAgent]) -> None:
        desired_keys = {
            int(passenger.unique_id): self._session_key_for(passenger) for passenger in passengers
        }
        for session_key, session in list(self._sessions.items()):
            keep = {
                passenger_id
                for passenger_id, desired_key in desired_keys.items()
                if desired_key == session_key
            }
            session.sync_passengers(keep)
            # JuPedSim applies mark-for-removal on its next iterate.  Rebuild
            # an ownerless session so invisible ghosts cannot block insertion.
            evict_ownerless_session(
                self._sessions,
                self._session_keys_by_passenger,
                self._active_episode_ids,
                session_key,
                session,
            )

        for passenger_id, session_key in list(self._session_keys_by_passenger.items()):
            if passenger_id not in desired_keys:
                self._remove_from_session_key(passenger_id, session_key)
                self._session_keys_by_passenger.pop(passenger_id, None)
                self._active_episode_ids.pop(passenger_id, None)
                self._passive_episode_ids.pop(passenger_id, None)
                self._passive_phase_by_passenger.pop(passenger_id, None)

    def _session_for_key(self, model, session_key: str | None):
        self._reset_sessions_if_model_changed(model)
        if session_key not in self._sessions:
            scenario = model.scenario
            self._sessions[session_key] = self.adapter.create_walking_session(
                width=model.layout_graph.geometry.width,
                height=model.layout_graph.geometry.height,
                walkable_area=model.jupedsim_walkable_area(session_key),
                operational_model=scenario.jupedsim_operational_model,
                agent_radius=scenario.jupedsim_agent_radius_units,
                target_radius=scenario.jupedsim_target_radius_units,
                dt_seconds=model.simulation_clock.jupedsim_dt_seconds,
            )
        return self._sessions[session_key]

    def _reset_sessions_if_model_changed(self, model) -> None:
        model_identity = id(model)
        if self._model_identity is None:
            self._model_identity = model_identity
            return
        if self._model_identity == model_identity:
            return
        self._sessions.clear()
        self._session_keys_by_passenger.clear()
        self._passive_episode_ids.clear()
        self._passive_phase_by_passenger.clear()
        self._movement_trace_recorder = None
        self._movement_trace_disabled_reason = "model_changed"
        self._pending_trace_commits.clear()
        self._model_identity = model_identity

    def _movement_trace_recorder_for(self, model) -> MovementTraceRecorder | None:
        if not model.simulation_clock.research_valid:
            self._movement_trace_disabled_reason = "non_physical_simulation_clock"
            return None
        if self._movement_trace_recorder is None:
            self._movement_trace_recorder = MovementTraceRecorder(
                sample_interval_seconds=float(
                    getattr(model.scenario, "movement_trace_sample_seconds", 0.2)
                ),
                integration_dt_seconds=float(model.simulation_clock.jupedsim_dt_seconds),
                authority="jupedsim_committed_walk",
            )
            self._movement_trace_disabled_reason = ""
        return self._movement_trace_recorder

    def _session_key_for(self, passenger: PassengerAgent) -> str | None:
        native_motion = self._native_facility_motion(passenger)
        target = passenger.target if native_motion is None else native_motion.target
        level_id = (
            self._movement_level_key(passenger)
            if native_motion is None
            else native_motion.collision_level_id
        )
        return self._session_key_for_position(
            passenger.model,
            passenger.pos,
            target,
            level_id,
        )

    def _session_key_for_position(
        self,
        model,
        position: tuple[float, float],
        target: tuple[float, float],
        level_id: str | None,
    ) -> str | None:
        if level_id is None:
            return None
        level_area = model.jupedsim_walkable_area(level_id)
        if level_area.covers(ShapelyPoint(position)) and level_area.covers(ShapelyPoint(target)):
            return level_id
        return None

    def _remove_from_session_key(self, passenger_id: int, session_key: str | None) -> None:
        if session_key not in self._sessions:
            return
        session = self._sessions[session_key]
        session.remove_passenger(int(passenger_id))
        flush_pending = getattr(
            session,
            "flush_pending_removals_if_no_active_owners",
            None,
        )
        if callable(flush_pending):
            flush_pending()
        active_ids = getattr(session, "active_passenger_ids", None)
        if callable(active_ids) and not active_ids():
            self._sessions.pop(session_key, None)

    def _hold_on_backend_failure(
        self,
        passenger: PassengerAgent,
        *,
        reason: str,
        error: Exception | None = None,
        session_key: str | None = None,
    ) -> MovementResult:
        """Fail closed when JuPedSim cannot provide an authoritative position.

        A Euclidean fallback is not a weaker pedestrian model: it can cross
        walls, queues, or closed geometry.  Non-strict operation therefore
        means an auditable zero-motion degraded state, never fabricated
        movement.  The normal progress monitor may retry or replan later.
        """

        request = MovementRequest.from_passenger(passenger)
        self.degraded_hold_count += 1
        audit = getattr(passenger.model, "audit", None)
        record = getattr(audit, "record", None)
        if callable(record):
            record(
                "jupedsim_backend_failure_hold",
                source="movement_backend",
                severity="error",
                step=int(getattr(passenger.model, "step_index", 0) or 0),
                context={
                    "passenger_id": request.passenger_id,
                    "reason": reason,
                    "session_key": session_key,
                    "position": list(request.position),
                    "target": list(request.target),
                    "error_type": None if error is None else type(error).__name__,
                },
            )
        return MovementResult(
            request.passenger_id,
            request.position,
            reached=False,
        )

    def _finish_if_already_at_target(self, passenger: PassengerAgent) -> MovementResult | None:
        x, y = passenger.pos
        tx, ty = passenger.target
        if hypot(tx - x, ty - y) <= 0.001:
            return MovementResult(int(passenger.unique_id), passenger.pos, reached=True)
        return None

    def _local_starts(self, passenger: PassengerAgent) -> list[tuple[float, float]]:
        model = passenger.model
        scenario = model.scenario
        starts = [passenger.pos]
        walkable_area = self._walkable_area_for(passenger)
        try:
            nearby = model.nearby_passengers(passenger, scenario.jupedsim_neighbor_radius_units)
        except Exception as exc:
            raise RuntimeError(
                f"Nearby passenger lookup failed for passenger {passenger.unique_id}."
            ) from exc
        for other, _dx, _dy, _dist in nearby[: scenario.jupedsim_neighbor_sample_limit]:
            if other.state not in CROWD_INTERACTION_STATES:
                continue
            candidate = other.pos
            adjusted = self._clearance_adjusted_position(
                candidate,
                starts,
                scenario.jupedsim_agent_radius_units,
                scenario.jupedsim_clearance_multiplier,
                walkable_area=walkable_area,
                seed=int(getattr(other, "unique_id", 0) or 0),
            )
            if adjusted is not None:
                starts.append(adjusted)
        return starts

    def _movement_level_key(self, passenger: PassengerAgent) -> str | None:
        return passenger.current_level_id

    def _walkable_area_for(self, passenger: PassengerAgent):
        return self._walkable_area_for_segment(
            passenger.model,
            self._movement_level_key(passenger),
            [passenger.pos],
            passenger.target,
        )

    def _walkable_area_for_segment(
        self,
        model,
        level_id: str | None,
        starts: list[tuple[float, float]],
        target: tuple[float, float],
    ):
        if level_id is None:
            return model.jupedsim_walkable_area()
        level_area = model.jupedsim_walkable_area(level_id)
        if level_area.covers(ShapelyPoint(target)) and all(
            level_area.covers(ShapelyPoint(start)) for start in starts
        ):
            return level_area
        return model.jupedsim_walkable_area()

    _has_initialization_clearance = staticmethod(has_initialization_clearance)
    _can_share_initialization_batch = staticmethod(can_share_initialization_batch)
    _clearance_adjusted_position = staticmethod(clearance_adjusted_position)


class BatchedJuPedSimMovementBackend(JuPedSimMovementBackend):
    """Backward-compatible name for the shared persistent JuPedSim backend."""
