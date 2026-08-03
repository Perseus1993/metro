from __future__ import annotations

from abc import ABC, abstractmethod
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
from .dynamic_body_trace import DynamicBodyTraceResolver
from .initialization_clearance import (
    can_share_initialization_batch,
    clearance_adjusted_position,
    has_initialization_clearance,
)
from .jps_adapter import JuPedSimPlacementBlocked
from .session_lifecycle import evict_ownerless_session
from .trajectory_trace import MovementTraceRecorder, empty_movement_trace

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from .jps_adapter import JuPedSimAdapter


class MovementBackend(ABC):
    """Movement engine interface for movable station agents."""

    @abstractmethod
    def move(self, passenger: PassengerAgent) -> MovementResult:
        """Return one passenger's next physical position and target reach state."""

    def step_all(
        self, passengers: list[PassengerAgent]
    ) -> list[tuple[PassengerAgent, MovementResult]]:
        """Compute movement results for all active passenger agents."""
        results: list[tuple[PassengerAgent, MovementResult]] = []
        for passenger in list(passengers):
            if (
                passenger.state not in WALKING_STATES
                or passenger.passive_facility_service
                or _movement_suppressed_this_step(passenger)
            ):
                continue
            results.append((passenger, self.move(passenger)))
        return results

    def place_passenger(
        self,
        passenger: PassengerAgent,
        position: tuple[float, float],
        *,
        target: tuple[float, float] | None = None,
        level_id: str | None = None,
    ) -> tuple[float, float]:
        """Place a passenger at a legal movement-engine position."""

        return passenger.model.clamp_position(position)

    def resolve_placement(
        self,
        passenger: PassengerAgent,
        position: tuple[float, float],
        *,
        level_id: str | None = None,
    ) -> tuple[float, float]:
        """Resolve a legal future position without mutating backend state."""

        del level_id
        return passenger.model.clamp_position(position)

    def remove_passenger(self, passenger: PassengerAgent) -> None:
        """Remove a passenger from any movement-engine state."""

    def active_passenger_ids(self) -> set[int]:
        """Return passengers still retained by the physical movement engine."""

        return set()

    def on_walkable_geometry_changed(self, model: object) -> None:
        """Refresh geometry-dependent state after a scheduled control event."""

    def movement_trace(self) -> dict[str, object]:
        """Return walking samples owned by the movement backend."""

        return empty_movement_trace(reason="movement_backend_has_no_trace")


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
        self._model_identity: int | None = None
        self._movement_trace_recorder: MovementTraceRecorder | None = None
        self._movement_trace_disabled_reason = "simulation_not_started"

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
        return self._move_passengers(eligible, sync_sessions=True)

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

    def remove_passenger(self, passenger: PassengerAgent) -> None:
        passenger_id = int(passenger.unique_id)
        session_key = self._session_keys_by_passenger.pop(passenger_id, None)
        self._active_episode_ids.pop(passenger_id, None)
        self._remove_from_session_key(passenger_id, session_key)

    def active_passenger_ids(self) -> set[int]:
        return set(self._session_keys_by_passenger)

    def movement_trace(self) -> dict[str, object]:
        if self._movement_trace_recorder is None:
            return empty_movement_trace(reason=self._movement_trace_disabled_reason)
        return self._movement_trace_recorder.as_dict()

    def on_walkable_geometry_changed(self, model: object) -> None:
        self._sessions.clear()
        self._session_keys_by_passenger.clear()
        self._active_episode_ids.clear()

    def _move_passengers(
        self,
        passengers: list[PassengerAgent],
        *,
        sync_sessions: bool,
    ) -> list[tuple[PassengerAgent, MovementResult]]:
        if not self.adapter.status.available:
            raise RuntimeError(
                f"JuPedSim movement requested but unavailable: {self.adapter.status.message}"
            )

        if sync_sessions:
            self._sync_session_membership(passengers)

        result_by_id: dict[int, MovementResult] = {}
        tracked: list[tuple[PassengerAgent, str | None]] = []
        dynamic_resolver: DynamicBodyTraceResolver | None = None
        sessions_to_iterate: set[str | None] = set()
        for passenger in passengers:
            if passenger.state not in self.MOVEMENT_STATES:
                raise RuntimeError(
                    f"JuPedSim cannot move passenger {passenger.unique_id} in state "
                    f"{passenger.state!r}."
                )
            request = MovementRequest.from_passenger(passenger)
            reached = self._finish_if_already_at_target(passenger)
            if reached is not None:
                # ``_sync_session_membership`` runs before this exact-target
                # check, so a passenger can still be retained by a shared JPS
                # session even though Mesa has already finished its walking
                # episode.  Leaving it there lets another passenger's batch
                # advance and record a ghost trajectory that disagrees with
                # the authoritative snapshot.
                self.remove_passenger(passenger)
                result_by_id[request.passenger_id] = reached
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

        if tracked:
            model = tracked[0][0].model
            dynamic_resolver = DynamicBodyTraceResolver(
                model,
                [passenger for passenger, _session_key in tracked],
            )
            recorder = self._movement_trace_recorder_for(model)
            for session_key in sessions_to_iterate:
                session = self._sessions[session_key]
                if recorder is None:
                    session.iterate(model.simulation_clock.jupedsim_iterations_per_tick)
                else:
                    tick_start_seconds = float(model.current_time_seconds)
                    dt_seconds = float(model.simulation_clock.jupedsim_dt_seconds)

                    # Record the physical start of each newly active walking
                    # episode. Continuing agents already have a sample at this
                    # boundary and the recorder de-duplicates it. Without this
                    # anchor, placement correction during episode creation is
                    # invisible to the kinematic gate.
                    start_positions = {
                        int(passenger.unique_id): tuple(passenger.pos)
                        for passenger, tracked_session_key in tracked
                        if tracked_session_key == session_key
                    }
                    recorder.record_positions(
                        time_seconds=tick_start_seconds,
                        level_id=session_key,
                        positions=dynamic_resolver.resolve(
                            time_seconds=tick_start_seconds,
                            level_id=session_key,
                            proposed_positions=start_positions,
                        ),
                        episode_ids=session.episode_ids_by_passenger(),
                    )

                    def observe(
                        iteration: int,
                        positions: Mapping[int, tuple[float, float]],
                        *,
                        level_id: str | None = session_key,
                    ) -> None:
                        resolved_positions = dynamic_resolver.resolve(
                            time_seconds=tick_start_seconds + iteration * dt_seconds,
                            level_id=level_id,
                            proposed_positions=positions,
                        )
                        recorder.record_positions(
                            time_seconds=tick_start_seconds + iteration * dt_seconds,
                            level_id=level_id,
                            positions=resolved_positions,
                            episode_ids=session.episode_ids_by_passenger(),
                        )

                    session.iterate(
                        model.simulation_clock.jupedsim_iterations_per_tick,
                        sample_every_nth_iteration=recorder.every_nth_iteration,
                        sample_observer=observe,
                    )
                    for passenger, tracked_session_key in tracked:
                        if tracked_session_key != session_key:
                            continue
                        record = session.removal_record_for(int(passenger.unique_id))
                        if record is None:
                            continue
                        removal_time = tick_start_seconds + record.last_position_after_seconds
                        resolved_position = dynamic_resolver.resolve(
                            time_seconds=removal_time,
                            level_id=session_key,
                            proposed_positions={
                                int(passenger.unique_id): record.last_authoritative_position
                            },
                        )
                        recorder.record_positions(
                            time_seconds=(
                                removal_time
                            ),
                            level_id=session_key,
                            positions=resolved_position,
                            episode_ids={int(passenger.unique_id): record.episode_id},
                        )
                self.jps_batch_count += 1

        for passenger, session_key in tracked:
            request = MovementRequest.from_passenger(passenger)
            session = self._sessions.get(session_key)
            position = session.position_for(request.passenger_id) if session is not None else None
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
            if dynamic_resolver is not None:
                resolved_position = dynamic_resolver.resolve(
                    time_seconds=(
                        float(passenger.model.current_time_seconds)
                        + float(passenger.model.scenario.tick_seconds)
                    ),
                    level_id=session_key,
                    proposed_positions={request.passenger_id: next_position},
                ).get(request.passenger_id)
                if resolved_position is not None:
                    next_position = passenger.model.clamp_position(resolved_position)
            self.jps_step_count += 1
            reached = (
                hypot(
                    request.target[0] - next_position[0],
                    request.target[1] - next_position[1],
                )
                <= request.radius
            )
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
        self._movement_trace_recorder = None
        self._movement_trace_disabled_reason = "model_changed"
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
                authority="jupedsim_dynamic_body_resolver",
            )
            self._movement_trace_disabled_reason = ""
        return self._movement_trace_recorder

    def _session_key_for(self, passenger: PassengerAgent) -> str | None:
        return self._session_key_for_position(
            passenger.model,
            passenger.pos,
            passenger.target,
            self._movement_level_key(passenger),
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
        self._sessions[session_key].remove_passenger(int(passenger_id))

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
