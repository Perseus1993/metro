from __future__ import annotations

from collections import Counter
from math import hypot

from ..agents.passenger import PassengerAgent
from ..agents.transit import TrainAgent
from ..facilities.runtime import FacilityProcessAgent
from ..planning.goal_events import GoalEventKind
from ..planning.plan import AgentIntent, FacilityStage
from ..spatial_capacity_admission import (
    CertifiedPlacementTemporarilyBlocked,
    SpatialCapacityAdmissionError,
    SpatialCapacityEvidence,
    SpatialCapacityExhausted,
    record_spatial_capacity_event,
)
from ..station.alighting_source_geometry import ALIGHTING_SOURCE_SEARCH_WINDOW
from ..station.evacuation import EVACUATION_MODE
from .downstream_admission_evidence import downstream_admission_evidence
from .external_demand_reservoir import (
    DemandSourceKind,
    TemporaryDemandBlockReason,
)
from .source_publication_transaction import (
    PassengerPublicationTransaction,
    rollback_published_passenger,
)
from .source_demand_runtime import spawn_alighting_demand, spawn_entry_demand


class PassengerDemandMixin:
    """Scheduled passenger creation, alighting distribution, and evacuation conversion."""

    def spawn_passengers(self) -> None:
        spawn_entry_demand(self)

    def spawn_alighting_passengers(self) -> None:
        spawn_alighting_demand(self)

    def _record_alighting_demand_due(self, newly_due_groups: int) -> None:
        del newly_due_groups

    def _record_unavailable_alighting_manifest_remainder(self, groups: int) -> None:
        del groups

    def _require_alighting_spawn_conservation(self) -> None:
        pass

    def _spawn_passenger(
        self,
        intent: str | AgentIntent,
        *,
        initial_position: tuple[float, float] | None = None,
        initial_level_id: str | None = None,
    ) -> PassengerAgent:
        spawn_certificate = None
        spawn_node = None
        explicit_initial_position = initial_position is not None
        intent_value = intent.value if isinstance(intent, AgentIntent) else str(intent)
        if initial_position is None:
            initial_position, initial_level_id, spawn_certificate, spawn_node = (
                self._certified_spawn_location(intent)
            )
        if initial_level_id is not None:
            downstream = self._source_admission_evidence(
                intent_value,
                release_levels={str(initial_level_id)},
            )
            if not downstream["available"]:
                evidence = SpatialCapacityEvidence(
                    certificate_id=(
                        f"downstream_admission:{intent_value}:{downstream['decision_region_id']}"
                    ),
                    resource_kind="stage_storage",
                    owner_id=str(
                        downstream["decision_region_id"]
                        or downstream["downstream_stage"]
                        or intent_value
                    ),
                    certified_body_capacity=int(downstream["certified_downstream_slots"]),
                    current_occupancy_bodies=int(downstream["occupied_downstream_slots"]),
                    requested_bodies=1,
                    passenger_id=None,
                )
                record_spatial_capacity_event(
                    self,
                    "passenger_demand_deferred_without_downstream_admission",
                    evidence,
                )
                # The stage-specific code explains *where* admission was
                # exhausted; the generic code preserves the repository-wide
                # capacity contract used by dashboards and acceptance tests.
                record_spatial_capacity_event(
                    self,
                    "capacity.admission_exhausted",
                    evidence,
                )
                raise SpatialCapacityExhausted(
                    f"{intent_value} demand has no downstream ownership before spawn",
                    evidence,
                )
        target_line_id = None
        target_direction = None
        if intent_value == AgentIntent.TRANSFER.value:
            target_line_id, target_direction = self._default_transfer_target()
        passenger: PassengerAgent | None = None
        placement_blocked = None
        try:
            with PassengerPublicationTransaction(self) as publication:
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
                if spawn_certificate is not None or explicit_initial_position:
                    evidence = SpatialCapacityEvidence(
                        certificate_id=(
                            spawn_certificate.certificate_id
                            if spawn_certificate is not None
                            else f"runtime_source_placement:{intent_value}:{initial_level_id}"
                        ),
                        resource_kind=(
                            spawn_certificate.resource_kind
                            if spawn_certificate is not None
                            else "source_placement"
                        ),
                        owner_id=(
                            spawn_certificate.owner_id
                            if spawn_certificate is not None
                            else f"{intent_value}_source"
                        ),
                        certified_body_capacity=(
                            spawn_certificate.certified_body_capacity
                            if spawn_certificate is not None
                            else 1
                        ),
                        current_occupancy_bodies=(
                            self._spawn_reservoir_occupancy(spawn_certificate)
                            if spawn_certificate is not None
                            else 0
                        ),
                        requested_bodies=1,
                        passenger_id=int(passenger.unique_id),
                    )
                    try:
                        self.movement_backend.resolve_certified_placement(
                            passenger,
                            tuple(passenger.pos),
                            level_id=(
                                spawn_certificate.level_id
                                if spawn_certificate is not None
                                else str(initial_level_id)
                            ),
                        )
                    except RuntimeError as exc:
                        placement_blocked = CertifiedPlacementTemporarilyBlocked(
                            f"spawn cell {tuple(passenger.pos)!r} was blocked before admission",
                            evidence,
                        )
                        raise placement_blocked from exc
                self.passengers.append(passenger)
                self.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
                self.spawned_persons += passenger.group_size
                self.spawned_persons_by_intent[passenger.intent] += passenger.group_size
                if passenger.spawn_source_element_id is not None:
                    self.spawned_persons_by_entrance[passenger.spawn_source_element_id] += (
                        passenger.group_size
                    )
                self._spawned_since_last_frame = True
                publication.commit()
        except CertifiedPlacementTemporarilyBlocked as exc:
            if exc is placement_blocked:
                record_spatial_capacity_event(
                    self,
                    "spawn.dynamic_blocked",
                    exc.evidence,
                )
            raise
        if passenger is None:
            raise RuntimeError("passenger publication committed without a Passenger")
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
            (node, certificates[node.node_id]) for node in nodes if node.node_id in certificates
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
        platform = min(
            self.platforms,
            key=lambda item: (item.line_id, item.direction, item.platform_id),
        )
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
            if isinstance(facility, FacilityProcessAgent) and facility.is_forced_disabled
        }
        refreshed = 0
        for passenger in tuple(self.passengers):
            path = tuple(passenger.evacuation_facility_path)
            if passenger.intent != AgentIntent.EVACUATE_STATION.value or (
                not force_all
                and (
                    not path
                    or not (
                        disabled_ids.intersection(path) or changed_facility_ids.intersection(path)
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

        run_ref = self._train_run_ref(train)
        if run_ref not in self.train_exchange_manifests:
            raise RuntimeError(f"train exchange manifest required for alighting demand: {run_ref}")
        doors = self.boarding_doors_for_train(train)
        if not doors:
            raise RuntimeError(f"model_invalid: train {run_ref} has no mapped doors")

        door_spawn_counts: Counter[str] = Counter()
        reserved_positions: list[tuple[tuple[float, float], str]] = []
        for index in range(count):
            claim = self.external_demand_reservoir.claim_next(
                DemandSourceKind.TRAIN_ALIGHTING,
                run_ref,
                step=int(self.step_index),
            )
            if claim is None:
                break
            try:
                downstream = self._alighting_source_admission_reservation(doors)
            except BaseException:
                self.external_demand_reservoir.defer(
                    claim,
                    step=int(self.step_index),
                    reason=TemporaryDemandBlockReason.DOWNSTREAM_CAPACITY_EXHAUSTED,
                )
                raise
            if not downstream["available"]:
                self.external_demand_reservoir.defer(
                    claim,
                    step=int(self.step_index),
                    reason=TemporaryDemandBlockReason.ADMISSION_CREDIT_EXHAUSTED,
                )
                self.audit.record(
                    "alighting_demand_deferred_without_downstream_admission",
                    source="demand_scheduler",
                    severity="warning",
                    count=1,
                    step=self.step_index,
                    context={
                        "train_id": train.unique_id,
                        "platform_id": train.platform_id,
                        "deferred_groups": 1,
                        "pending_groups": count - index,
                        **downstream,
                    },
                )
                break
            preferred_door_index = (index + self.step_index + train.departed_trains) % len(doors)
            placement: tuple[FacilityProcessAgent, tuple[float, float], str] | None = None
            try:
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
            except BaseException:
                self._release_alighting_source_admission_reservation(
                    downstream,
                    reason="source_placement_exception",
                )
                self.external_demand_reservoir.defer(
                    claim,
                    step=int(self.step_index),
                    reason=TemporaryDemandBlockReason.SOURCE_PLACEMENT_BLOCKED,
                )
                raise
            if placement is None:
                self._release_alighting_source_admission_reservation(
                    downstream,
                    reason="source_placement_blocked",
                )
                self.external_demand_reservoir.defer(
                    claim,
                    step=int(self.step_index),
                    reason=TemporaryDemandBlockReason.SOURCE_PLACEMENT_BLOCKED,
                )
                self.audit.record(
                    "alighting_demand_deferred_without_clear_spawn_cell",
                    source="demand_scheduler",
                    severity="warning",
                    step=self.step_index,
                    context={
                        "train_id": train.unique_id,
                        "platform_id": train.platform_id,
                        "deferred_groups": 1,
                        "pending_groups": count - index,
                    },
                )
                break
            door, position, level_id = placement
            door_spawn_counts[door.facility_id] += 1
            reserved_positions.append((position, level_id))
            try:
                passenger = self._spawn_passenger(
                    AgentIntent.EXIT_STATION,
                    initial_position=position,
                    initial_level_id=level_id,
                )
            except SpatialCapacityAdmissionError:
                self._release_alighting_source_admission_reservation(
                    downstream,
                    reason="physical_placement_retry",
                )
                self.external_demand_reservoir.defer(
                    claim,
                    step=int(self.step_index),
                    reason=TemporaryDemandBlockReason.SOURCE_PLACEMENT_BLOCKED,
                )
                break
            except BaseException:
                self._release_alighting_source_admission_reservation(
                    downstream,
                    reason="spawn_exception",
                )
                self.external_demand_reservoir.defer(
                    claim,
                    step=int(self.step_index),
                    reason=TemporaryDemandBlockReason.SOURCE_PLACEMENT_BLOCKED,
                )
                raise
            manifest = self.train_exchange_manifests[run_ref]
            try:
                self.external_demand_reservoir.validate_commit(
                    claim,
                    passenger_id=int(passenger.unique_id),
                    published_step=int(self.step_index),
                )
                manifest.preflight_alighting_release(
                    int(passenger.group_size),
                    at_step=int(self.step_index),
                )
            except BaseException:
                self._release_alighting_source_admission_reservation(
                    downstream,
                    reason="publication_preflight_exception",
                )
                rollback_published_passenger(self, passenger)
                self.external_demand_reservoir.defer(
                    claim,
                    step=int(self.step_index),
                    reason=TemporaryDemandBlockReason.DOWNSTREAM_CAPACITY_EXHAUSTED,
                )
                raise
            try:
                self._commit_alighting_source_admission_reservation(
                    downstream,
                    passenger,
                )
            except BaseException:
                rollback_published_passenger(self, passenger)
                self.external_demand_reservoir.defer(
                    claim,
                    step=int(self.step_index),
                    reason=TemporaryDemandBlockReason.DOWNSTREAM_CAPACITY_EXHAUSTED,
                )
                raise
            manifest_released = False
            try:
                manifest.release_alighting_group(
                    int(passenger.group_size),
                    at_step=int(self.step_index),
                )
                manifest_released = True
                self.external_demand_reservoir.commit(
                    claim,
                    passenger_id=int(passenger.unique_id),
                    published_step=int(self.step_index),
                )
            except BaseException:
                if manifest_released:
                    manifest.rollback_latest_alighting_release(
                        int(passenger.group_size),
                        at_step=int(self.step_index),
                    )
                resource = getattr(self, "alignment_admission_resources", {}).get("exit")
                if resource is not None and int(passenger.unique_id) in resource.owners:
                    resource.release(
                        int(passenger.unique_id),
                        self.step_index,
                        reason="manifest_or_reservoir_commit_exception",
                    )
                rollback_published_passenger(self, passenger)
                self.external_demand_reservoir.defer(
                    claim,
                    step=int(self.step_index),
                    reason=TemporaryDemandBlockReason.DOWNSTREAM_CAPACITY_EXHAUSTED,
                )
                raise
            passenger.assigned_platform_id = train.platform_id
            passenger.assigned_line_id = train.line_id
            passenger.assigned_direction = train.direction

    def _defer_alighting_groups(self, count: int) -> None:
        del count

    def _alighting_source_admission_reservation(
        self,
        doors: list[FacilityProcessAgent],
    ) -> dict[str, object]:
        """Reserve admission before publishing one alighting body.

        The base runtime preserves its existing downstream-evidence policy.
        Alignment overrides this seam with a geometry-free counting credit and
        uses the paired commit/release hooks to make publication transactional.
        """

        return self._alighting_downstream_admission_evidence(doors)

    def _release_alighting_source_admission_reservation(
        self,
        reservation: dict[str, object],
        *,
        reason: str,
    ) -> None:
        del reservation, reason

    def _commit_alighting_source_admission_reservation(
        self,
        reservation: dict[str, object],
        passenger: PassengerAgent,
    ) -> None:
        del reservation, passenger

    def _alighting_downstream_admission_evidence(
        self,
        doors: list[FacilityProcessAgent],
    ) -> dict[str, object]:
        """Prove downstream ownership before publishing an alighting body.

        A clear source cell is necessary but not sufficient admission.  The
        release level must also have either a free first-stage approach or a
        free compiler-certified platform staging cell. Decision holding is
        recovery storage for bodies already admitted to the station and does
        not license publication behind an occupied holding cross-section.
        Without either owned resource, demand stays train-side pending.
        """

        release_levels = {
            str(level_id)
            for door in doors
            if (level_id := door.spec.exit_level_id or door.spec.entry_level_id) is not None
        }
        return self._downstream_admission_evidence(
            AgentIntent.EXIT_STATION.value,
            release_levels=release_levels,
        )

    def _downstream_admission_evidence(
        self,
        intent: str,
        *,
        release_levels: set[str],
    ) -> dict[str, object]:
        return downstream_admission_evidence(
            self,
            intent,
            release_levels=release_levels,
        )

    def _source_admission_evidence(
        self,
        intent: str,
        *,
        release_levels: set[str],
    ) -> dict[str, object]:
        """Return the source publication licence for this runtime.

        The default Metro runtime retains its compiler-certified physical
        storage policy. Alignment overrides this seam with independent flow
        credits, leaving physical placement to the existing placement path.
        """

        return self._downstream_admission_evidence(
            intent,
            release_levels=release_levels,
        )

    def _alighting_spawn_position(
        self,
        door: FacilityProcessAgent,
        local_index: int,
        *,
        reserved_positions: list[tuple[tuple[float, float], str]] | None = None,
    ) -> tuple[float, float] | None:
        level_id = door.spec.exit_level_id or door.spec.entry_level_id
        if level_id is None:
            return None
        reserved = reserved_positions or []
        try:
            certificate = self.layout_graph.spatial_capacity_certificate(
                "alighting_source",
                f"alighting_source:{door.facility_id}",
                level_id=level_id,
            )
        except KeyError:
            return None
        # Runtime consumes the exact compiler-certified pool.  This keeps
        # fallback placement aligned with the co-active queue/holding proof;
        # recomputing the raw lattice here could reintroduce rejected cells.
        candidates = certificate.slots
        if not candidates:
            return None
        for candidate_offset in range(min(ALIGHTING_SOURCE_SEARCH_WINDOW, len(candidates))):
            candidate = candidates[(local_index + candidate_offset) % len(candidates)]
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
            if hypot(candidate[0] - position[0], candidate[1] - position[1]) < (minimum_distance):
                return False
        return True

    @staticmethod
    def _split_count(count: int, buckets: int) -> list[int]:
        if buckets <= 0:
            return []
        base, remainder = divmod(max(0, count), buckets)
        return [base + (1 if index < remainder else 0) for index in range(buckets)]
