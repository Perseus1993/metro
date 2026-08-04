from __future__ import annotations

from collections import Counter
from math import hypot

from ..agents.passenger import PassengerAgent
from ..agents.transit import TrainAgent
from ..facilities.runtime import FacilityProcessAgent
from ..planning.goal_events import GoalEventKind
from ..planning.plan import AgentIntent, FacilityStage
from ..station.alighting_source_geometry import (
    ALIGHTING_SOURCE_SEARCH_WINDOW,
    alighting_source_projection_clearance_m,
    alighting_source_raw_candidate,
)
from ..station.evacuation import EVACUATION_MODE
from ..station.geometry import project_to_safe_point
from ..spatial_capacity_admission import (
    CertifiedPlacementTemporarilyBlocked,
    SpatialCapacityAdmissionError,
    SpatialCapacityEvidence,
    SpatialCapacityExhausted,
    record_spatial_capacity_event,
)


class PassengerDemandMixin:
    """Scheduled passenger creation, alighting distribution, and evacuation conversion."""

    def spawn_passengers(self) -> None:
        due_by_intent = Counter(self.pending_spawn_groups)
        self.pending_spawn_groups.clear()
        due_by_intent.update(self.demand_scheduler.due_by_intent(self.step_index))
        for intent, count in due_by_intent.items():
            for attempt in range(count):
                try:
                    self._spawn_passenger(intent)
                except SpatialCapacityAdmissionError:
                    # Admission is upstream of PassengerAgent ownership. Keep
                    # the deterministic demand pending instead of creating an
                    # overlapping body or losing the group.
                    self.pending_spawn_groups[str(intent)] += count - attempt
                    break

    def spawn_alighting_passengers(self) -> None:
        newly_due = self.demand_scheduler.due_alightings(self.step_index)
        due = self.pending_alighting_groups + newly_due
        if due <= 0:
            return

        boarding_trains = [train for train in self.trains if train.is_boarding]
        if not boarding_trains:
            self.pending_alighting_groups = due
            self.max_pending_alighting_groups = max(
                self.max_pending_alighting_groups,
                self.pending_alighting_groups,
            )
            self.audit.record(
                "alighting_demand_deferred_without_boarding_train",
                source="demand_scheduler",
                severity="warning",
                step=self.step_index,
                context={
                    "newly_due_groups": newly_due,
                    "pending_groups": self.pending_alighting_groups,
                },
            )
            return

        self.pending_alighting_groups = 0
        for train, count in zip(
            boarding_trains,
            self._split_count(due, len(boarding_trains)),
            strict=True,
        ):
            self._spawn_alighting_passengers_for_train(train, count)

    def _spawn_passenger(
        self,
        intent: str | AgentIntent,
        *,
        initial_position: tuple[float, float] | None = None,
        initial_level_id: str | None = None,
    ) -> PassengerAgent:
        spawn_certificate = None
        spawn_node = None
        if initial_position is None:
            initial_position, initial_level_id, spawn_certificate, spawn_node = (
                self._certified_spawn_location(intent)
            )
        target_line_id = None
        target_direction = None
        intent_value = intent.value if isinstance(intent, AgentIntent) else str(intent)
        if intent_value == AgentIntent.TRANSFER.value:
            target_line_id, target_direction = self._default_transfer_target()
        passenger = PassengerAgent(
            self,
            group_size=self.scenario.group_size,
            created_step=self.step_index,
            intent=intent,
            target_line_id=target_line_id,
            target_direction=target_direction,
            initial_position=initial_position,
            initial_level_id=initial_level_id,
        )
        if spawn_node is not None:
            passenger.spawn_source_element_id = spawn_node.element_id
        if spawn_certificate is not None:
            evidence = SpatialCapacityEvidence(
                certificate_id=spawn_certificate.certificate_id,
                resource_kind=spawn_certificate.resource_kind,
                owner_id=spawn_certificate.owner_id,
                certified_body_capacity=spawn_certificate.certified_body_capacity,
                current_occupancy_bodies=self._spawn_reservoir_occupancy(
                    spawn_certificate
                ),
                requested_bodies=1,
                passenger_id=int(passenger.unique_id),
            )
            try:
                self.movement_backend.resolve_certified_placement(
                    passenger,
                    tuple(passenger.pos),
                    level_id=spawn_certificate.level_id,
                )
            except RuntimeError as exc:
                record_spatial_capacity_event(
                    self,
                    "spawn.dynamic_blocked",
                    evidence,
                )
                raise CertifiedPlacementTemporarilyBlocked(
                    f"spawn cell {tuple(passenger.pos)!r} was blocked before admission",
                    evidence,
                ) from exc
        self.passengers.append(passenger)
        self.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
        self.spawned_persons += passenger.group_size
        self.spawned_persons_by_intent[passenger.intent] += passenger.group_size
        if passenger.spawn_source_element_id is not None:
            self.spawned_persons_by_entrance[passenger.spawn_source_element_id] += (
                passenger.group_size
            )
        self._spawned_since_last_frame = True
        return passenger

    def _certified_spawn_location(
        self,
        intent: str | AgentIntent,
    ):
        intent_value = intent.value if isinstance(intent, AgentIntent) else str(intent)
        wants_platform = intent_value in {
            AgentIntent.EXIT_STATION.value,
            AgentIntent.EVACUATE_STATION.value,
            AgentIntent.TRANSFER.value,
        }
        graph = self.layout_graph.station_graph
        node_kind = "platform" if wants_platform else "entrance"
        nodes = tuple(sorted(graph.nodes_matching(kind=node_kind), key=lambda item: item.node_id))
        certificates = {
            item.owner_id: item
            for item in self.layout_graph.spatial_capacity_certificates
            if item.resource_kind == "spawn_reservoir"
        }
        candidates = tuple(
            (node, certificates[node.node_id])
            for node in nodes
            if node.node_id in certificates
        )
        if not candidates:
            evidence = SpatialCapacityEvidence(
                certificate_id=f"spawn:{node_kind}:missing",
                resource_kind="spawn_reservoir",
                owner_id=node_kind,
                certified_body_capacity=0,
                current_occupancy_bodies=0,
                requested_bodies=1,
                passenger_id=None,
            )
            record_spatial_capacity_event(self, "capacity.certificate_missing", evidence)
            raise SpatialCapacityExhausted(
                f"no compiled {node_kind} spawn reservoir is available",
                evidence,
            )

        minimum_distance = max(
            0.05,
            float(self.scenario.jupedsim_agent_radius_units)
            * float(self.scenario.jupedsim_clearance_multiplier),
        )
        for node, certificate in self._ordered_spawn_reservoirs(
            candidates,
            wants_platform=wants_platform,
        ):
            for point in certificate.slots:
                if all(
                    other.current_level_id != certificate.level_id
                    or hypot(point[0] - other.pos[0], point[1] - other.pos[1])
                    >= minimum_distance - 1e-9
                    for other in self.passengers
                ):
                    return tuple(point), certificate.level_id, certificate, node
        total_capacity = sum(item.certified_body_capacity for _node, item in candidates)
        occupancy = sum(self._spawn_reservoir_occupancy(item) for _node, item in candidates)
        evidence = SpatialCapacityEvidence(
            certificate_id=f"spawn:{node_kind}:all",
            resource_kind="spawn_reservoir",
            owner_id=node_kind,
            certified_body_capacity=total_capacity,
            current_occupancy_bodies=occupancy,
            requested_bodies=1,
            passenger_id=None,
        )
        record_spatial_capacity_event(self, "capacity.admission_exhausted", evidence)
        raise SpatialCapacityExhausted(
            f"all {node_kind} spawn reservoir cells are occupied",
            evidence,
        )

    def _ordered_spawn_reservoirs(self, candidates, *, wants_platform: bool):
        if wants_platform or not self.scenario.entry_entrance_weights:
            return candidates
        weights = dict(self.scenario.entry_entrance_weights)
        weighted = tuple(
            (node, certificate, float(weights.get(str(node.element_id), 0.0)))
            for node, certificate in candidates
        )
        total = sum(weight for _node, _certificate, weight in weighted)
        if total <= 0.0:
            return candidates
        draw = self.random.random() * total
        cumulative = 0.0
        selected = 0
        for index, (_node, _certificate, weight) in enumerate(weighted):
            cumulative += weight
            if draw <= cumulative:
                selected = index
                break
        ordered = candidates[selected:] + candidates[:selected]
        return ordered

    def _spawn_reservoir_occupancy(self, certificate) -> int:
        minimum_distance = max(
            0.05,
            float(self.scenario.jupedsim_agent_radius_units)
            * float(self.scenario.jupedsim_clearance_multiplier),
        )
        return sum(
            1
            for point in certificate.slots
            if any(
                other.current_level_id == certificate.level_id
                and hypot(point[0] - other.pos[0], point[1] - other.pos[1])
                < minimum_distance - 1e-9
                for other in self.passengers
            )
        )

    def _default_transfer_target(self) -> tuple[str | None, str | None]:
        if not self.platforms:
            return None, None
        platform = sorted(
            self.platforms,
            key=lambda item: (item.line_id, item.direction, item.platform_id),
        )[0]
        return platform.line_id, platform.direction

    def _activate_evacuation_if_due(self) -> None:
        if self.scenario.scenario_mode != EVACUATION_MODE or self._evacuation_activated:
            return
        assert self.scenario.evacuation is not None
        if self.step_index < self.scenario.evacuation.alarm_step(self.scenario.tick_seconds):
            return
        self._evacuation_activated = True
        for passenger in tuple(self.passengers):
            if passenger.intent == AgentIntent.EVACUATE_STATION.value:
                continue
            if self.passenger_has_active_facility_service(passenger):
                passenger.evacuation_pending = True
                continue
            self._activate_passenger_evacuation(passenger)

    def _activate_passenger_evacuation(
        self,
        passenger: PassengerAgent,
        *,
        completed_facility_id: str | None = None,
    ) -> None:
        station_interior = self._passenger_is_inside_station_for_alarm(
            passenger,
            completed_facility_id=completed_facility_id,
        )
        # Compile first.  If the physical topology is invalid, do not partially
        # release queues or replace the passenger's still-auditable runtime.
        evacuation_runtime = self.evacuation_goal_runtime_from_position(
            passenger,
            station_interior=station_interior,
        )
        self._remove_from_station_holding_areas(passenger)
        self._clear_all_facility_targeting_reservations(passenger)
        self._clear_all_decision_holding_reservations(passenger)
        passenger.evacuation_pending = False
        passenger.intent = AgentIntent.EVACUATE_STATION.value
        passenger.plan = self.plan_for_intent(AgentIntent.EVACUATE_STATION)
        passenger.goal_runtime = evacuation_runtime
        passenger.assigned_facility_id = None
        passenger.assigned_platform_id = None
        passenger.assigned_line_id = None
        passenger.assigned_direction = None
        self.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
        self.goal_coordinator.initialize(passenger)

    def refresh_evacuation_routes_for_topology_change(
        self,
        changed_facility_ids: set[str] | frozenset[str] = frozenset(),
        *,
        force_all: bool = False,
    ) -> int:
        """Re-root exact evacuation paths invalidated by availability or direction."""

        disabled_ids = {
            facility.facility_id
            for facility in self.facilities
            if isinstance(facility, FacilityProcessAgent)
            and facility.is_forced_disabled
        }
        refreshed = 0
        for passenger in tuple(self.passengers):
            path = tuple(passenger.evacuation_facility_path)
            if (
                passenger.intent != AgentIntent.EVACUATE_STATION.value
                or (
                    not force_all
                    and (
                        not path
                        or not (
                            disabled_ids.intersection(path)
                            or changed_facility_ids.intersection(path)
                        )
                    )
                )
            ):
                continue
            if self.passenger_has_active_facility_service(passenger):
                # Preserve the physical service.  Its completion callback will
                # re-root from the actual release level and position.
                passenger.evacuation_pending = True
                refreshed += 1
                continue
            self._activate_passenger_evacuation(passenger)
            refreshed += 1
        return refreshed

    def refresh_evacuation_routes_for_availability_change(
        self,
        changed_facility_ids: set[str] | frozenset[str] = frozenset(),
    ) -> int:
        """Compatibility name for availability-controller callers."""

        return self.refresh_evacuation_routes_for_topology_change(
            changed_facility_ids,
            force_all=True,
        )

    def _passenger_is_inside_station_for_alarm(
        self,
        passenger: PassengerAgent,
        *,
        completed_facility_id: str | None = None,
    ) -> bool:
        completed_facility = self.facilities_by_id.get(completed_facility_id)
        completed_stage = getattr(getattr(completed_facility, "spec", None), "stage", None)
        if completed_stage == FacilityStage.ENTRY_GATE.value:
            return True
        if completed_stage == FacilityStage.EXIT_GATE.value:
            return False
        completed_stages = {
            node.facility_stage
            for transition in passenger.goal_runtime.transitions
            if transition.event_kind == GoalEventKind.SERVICE_COMPLETED.value
            and (
                node := passenger.goal_runtime.graph.node(transition.before_node_id)
            ).facility_stage
            is not None
        }
        if FacilityStage.EXIT_GATE.value in completed_stages:
            return False
        if passenger.intent == AgentIntent.ENTER_AND_BOARD.value:
            return FacilityStage.ENTRY_GATE.value in completed_stages
        return True

    def _spawn_alighting_passengers_for_train(self, train: TrainAgent, count: int) -> None:
        if count <= 0:
            return

        doors = self.boarding_doors_for_train(train)
        if not doors:
            self.audit.record(
                "alighting_train_has_no_doors",
                source="demand_scheduler",
                severity="error",
                step=self.step_index,
                context={
                    "train_id": train.unique_id,
                    "platform_id": train.platform_id,
                    "due_persons": count,
                },
            )
            return

        door_spawn_counts: Counter[str] = Counter()
        reserved_positions: list[tuple[tuple[float, float], str]] = []
        for index in range(count):
            preferred_door_index = (
                index + self.step_index + train.departed_trains
            ) % len(doors)
            placement: tuple[FacilityProcessAgent, tuple[float, float], str] | None = None
            for door_offset in range(len(doors)):
                door = doors[(preferred_door_index + door_offset) % len(doors)]
                level_id = door.spec.exit_level_id or door.spec.entry_level_id
                if level_id is None:
                    continue
                position = self._alighting_spawn_position(
                    door,
                    door_spawn_counts[door.facility_id],
                    reserved_positions=reserved_positions,
                )
                if position is None:
                    continue
                placement = (door, position, level_id)
                break
            if placement is None:
                self.pending_alighting_groups += 1
                self.max_pending_alighting_groups = max(
                    self.max_pending_alighting_groups,
                    self.pending_alighting_groups,
                )
                self.audit.record(
                    "alighting_demand_deferred_without_clear_spawn_cell",
                    source="demand_scheduler",
                    severity="warning",
                    step=self.step_index,
                    context={
                        "train_id": train.unique_id,
                        "platform_id": train.platform_id,
                        "pending_groups": self.pending_alighting_groups,
                    },
                )
                continue
            door, position, level_id = placement
            door_spawn_counts[door.facility_id] += 1
            reserved_positions.append((position, level_id))
            passenger = self._spawn_passenger(
                AgentIntent.EXIT_STATION,
                initial_position=position,
                initial_level_id=level_id,
            )
            passenger.assigned_platform_id = train.platform_id
            passenger.assigned_line_id = train.line_id
            passenger.assigned_direction = train.direction

    def _alighting_spawn_position(
        self,
        door: FacilityProcessAgent,
        local_index: int,
        *,
        reserved_positions: list[tuple[tuple[float, float], str]] | None = None,
    ) -> tuple[float, float] | None:
        base = door.spec.exit_position
        queue_anchor = door.spec.queue_anchor
        level_id = door.spec.exit_level_id or door.spec.entry_level_id
        if level_id is None:
            return None
        walkable = self.jupedsim_walkable_area(level_id)
        reserved = reserved_positions or []
        # Search the door-local source lattice instead of placing a newly
        # alighted body on top of a platform waiter.  If no cell is available,
        # the demand remains pending for a later train rather than fabricating
        # an overlapping initial condition.
        for candidate_index in range(
            local_index,
            local_index + ALIGHTING_SOURCE_SEARCH_WINDOW,
        ):
            raw = alighting_source_raw_candidate(
                base,
                queue_anchor,
                candidate_index,
                agent_radius_m=self.scenario.jupedsim_agent_radius_units,
            )
            try:
                candidate = project_to_safe_point(
                    walkable,
                    self.clamp_position(raw),
                    clearance=alighting_source_projection_clearance_m(
                        self.scenario.jupedsim_agent_radius_units
                    ),
                    require_inside=False,
                )
            except Exception:
                continue
            if self._alighting_spawn_cell_is_clear(
                candidate,
                level_id,
                reserved,
            ):
                return candidate
        return None

    def _alighting_spawn_cell_is_clear(
        self,
        candidate: tuple[float, float],
        level_id: str,
        reserved_positions: list[tuple[tuple[float, float], str]],
    ) -> bool:
        minimum_distance = self.scenario.jupedsim_agent_radius_units * 2.0 + 1e-6
        occupied = (
            (
                passenger.pos,
                passenger.physical_motion_layer_id or passenger.current_level_id,
            )
            for passenger in self.passengers
        )
        for position, occupied_level_id in (*reserved_positions, *occupied):
            if occupied_level_id != level_id:
                continue
            if hypot(candidate[0] - position[0], candidate[1] - position[1]) < (
                minimum_distance
            ):
                return False
        return True

    @staticmethod
    def _split_count(count: int, buckets: int) -> list[int]:
        if buckets <= 0:
            return []
        base, remainder = divmod(max(0, count), buckets)
        return [base + (1 if index < remainder else 0) for index in range(buckets)]
