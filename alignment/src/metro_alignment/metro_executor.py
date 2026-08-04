from __future__ import annotations

import json
from collections import Counter, deque
from dataclasses import dataclass
from math import cos, hypot, radians, sin
from typing import NamedTuple

from metro_station.adapters.simulation.compilation.validation import (
    validate_compiled_station_design,
)
from metro_station.adapters.simulation.executor import MesaSimulationExecutor
from metro_station.adapters.simulation.movement.dynamic_body_clearance import (
    minimum_body_clearance,
)
from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.alighting_demand import peak_alighting_batch
from metro_station.adapters.simulation.station.alighting_source_geometry import (
    ALIGHTING_SOURCE_SEARCH_WINDOW,
    alighting_source_projection_clearance_m,
    alighting_source_raw_candidate,
    alighting_source_spacing_m,
)
from metro_station.adapters.simulation.station.geometry import (
    document_walkable_geometry,
    element_shape,
    element_walkable_domain,
    level_walkable_geometry,
    project_to_safe_point,
    sample_safe_point,
)
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.application.simulation import (
    ProgressCallback,
    SimulationExecutionResult,
    SimulationRequest,
)
from shapely.geometry import LineString
from shapely.geometry import Point as ShapelyPoint


class SourceAdmission(NamedTuple):
    position: tuple[float, float]
    level_id: str
    source_element_id: str | None


@dataclass(frozen=True)
class PendingSourceDemand:
    sequence_id: int
    scheduled_step: int
    intent: str
    group_size: int
    source_node: object
    source_id: str
    level_id: str
    local_radius: float


class AlignmentSourceGeometryConflict(RuntimeError):
    def __init__(self, report: dict) -> None:
        self.report = report
        super().__init__(
            "alignment source geometry preflight failed: "
            + json.dumps(report, ensure_ascii=False, sort_keys=True)
        )


def alignment_source_geometry_preflight(scenario: StationSandboxScenario) -> dict:
    """Check document-level queue/source contracts before Metro compilation."""

    document = scenario.station_design
    if document is None:
        raise RuntimeError("alignment source preflight requires a station design document")
    minimum_distance = max(
        0.05,
        float(scenario.jupedsim_agent_radius_units)
        * float(scenario.jupedsim_clearance_multiplier),
    )
    compiled = validate_compiled_station_design(document, scenario)
    source_certificates = {
        certificate.certificate_id: certificate
        for certificate in compiled.spatial_capacity_certificates
        if certificate.resource_kind == "alighting_source"
    }
    coactive_issues = tuple(
        item
        for item in compiled.issues
        if item.severity == "error"
        and item.code == "capacity.coactive_slot_conflict"
    )
    peak_batch = peak_alighting_batch(scenario)
    elements_by_id = document.element_by_id()
    reports: list[dict] = []
    for queue in document.queues:
        owner = elements_by_id.get(queue.owner_element_id)
        if owner is None or owner.kind != "platform_edge" or queue.kind != "holding_area":
            continue
        base_x, base_y = queue.service_point_m
        angle = radians(float(queue.direction_deg))
        anchor_x = base_x - cos(angle) * float(queue.spacing_m)
        anchor_y = base_y - sin(angle) * float(queue.spacing_m)
        runtime_spacing = alighting_source_spacing_m(
            scenario.jupedsim_agent_radius_units
        )
        candidate_count = ALIGHTING_SOURCE_SEARCH_WINDOW + max(0, peak_batch - 1)
        raw_candidates = [
            alighting_source_raw_candidate(
                (base_x, base_y),
                (anchor_x, anchor_y),
                index,
                agent_radius_m=scenario.jupedsim_agent_radius_units,
            )
            for index in range(candidate_count)
        ]
        walkable = level_walkable_geometry(
            document,
            queue.level_id,
            document_walkable_geometry(document),
        )
        projection_clearance = alighting_source_projection_clearance_m(
            scenario.jupedsim_agent_radius_units
        )
        candidates = [
            project_to_safe_point(
                walkable,
                candidate,
                clearance=projection_clearance,
                require_inside=False,
            )
            for candidate in raw_candidates
        ]
        projection_shifts = [
            hypot(projected[0] - raw[0], projected[1] - raw[1])
            for raw, projected in zip(raw_candidates, candidates, strict=True)
        ]
        holding_area = element_shape(queue.geometry)
        holding_clearance = holding_area.buffer(minimum_distance)
        holding_overlap = [
            index
            for index, candidate in enumerate(candidates)
            if holding_area.covers(ShapelyPoint(candidate))
        ]
        holding_clearance_overlap = [
            index
            for index, candidate in enumerate(candidates)
            if holding_clearance.covers(ShapelyPoint(candidate))
        ]
        door_axis = LineString([(base_x, base_y), (anchor_x, anchor_y)])
        door_axis_overlap = [
            index
            for index, candidate in enumerate(candidates)
            if door_axis.distance(ShapelyPoint(candidate)) < minimum_distance - 1e-9
        ]
        unique_candidate_count = len(
            {(round(x, 12), round(y, 12)) for x, y in candidates}
        )
        blockers = []
        if holding_clearance_overlap:
            blockers.append("boarding_holding_area_overlaps_alighting_source_lattice")
        if door_axis_overlap:
            blockers.append("boarding_door_axis_overlaps_alighting_source_lattice")
        if unique_candidate_count < peak_batch:
            blockers.append("insufficient_unique_alighting_sources_for_peak_batch")
        certificate_id = f"alighting_source:{queue.id}"
        certificate = source_certificates.get(certificate_id)
        compiler_issues = tuple(
            item for item in coactive_issues if queue.id in item.message
        )
        reports.append(
            {
                "queue_id": queue.id,
                "owner_element_id": queue.owner_element_id,
                "level_id": queue.level_id,
                "status": "conflict" if blockers else "pass",
                "blockers": blockers,
                "minimum_body_clearance_m": minimum_distance,
                "runtime_candidate_spacing_m": runtime_spacing,
                "projection_clearance_m": projection_clearance,
                "maximum_candidate_projection_shift_m": max(
                    projection_shifts,
                    default=0.0,
                ),
                "peak_scheduled_alighting_batch": peak_batch,
                "source_candidate_count": len(candidates),
                "unique_source_candidate_count": unique_candidate_count,
                "holding_area_overlap_candidate_count": len(holding_overlap),
                "holding_area_overlap_candidate_indices": holding_overlap,
                "holding_clearance_overlap_candidate_count": len(
                    holding_clearance_overlap
                ),
                "holding_clearance_overlap_candidate_indices": holding_clearance_overlap,
                "boarding_door_axis_overlap_candidate_count": len(door_axis_overlap),
                "boarding_door_axis_overlap_candidate_indices": door_axis_overlap,
                "capacity_certificate": certificate is not None,
                "capacity_certificate_id": certificate_id,
                "compiler_error_codes": sorted({item.code for item in compiler_issues}),
                "compiler_rejection_reproduced": bool(compiler_issues),
            }
        )
    blockers = [
        {"queue_id": report["queue_id"], "blockers": report["blockers"]}
        for report in reports
        if report["status"] != "pass"
    ]
    return {
        "schema_version": "alignment_source_geometry_preflight.v3",
        "runtime_status": "not_started" if blockers else "ready",
        "scientific_status": "source_geometry_conflict" if blockers else "eligible",
        "outcome": "model_invalid" if blockers else "eligible",
        "status": "fail" if blockers else "pass",
        "minimum_body_clearance_m": minimum_distance,
        "capacity_certificate": bool(reports)
        and all(report["capacity_certificate"] for report in reports),
        "compiler_error_codes": sorted(
            {
                code
                for report in reports
                for code in report["compiler_error_codes"]
            }
        ),
        "compiler_rejection_reproduced": bool(blockers)
        and all(
            report["compiler_rejection_reproduced"]
            for report in reports
            if report["status"] != "pass"
        ),
        "queue_reports": reports,
        "blockers": blockers,
    }


class AlignmentMetroStationModel(MetroStationModel):
    """Apply conservative, backpressured admission to alignment sources.

    Metro's source pre-check currently uses ``2 * agent_radius`` while the
    movement layer uses the scenario-wide clearance multiplier.  Alignment
    runs use the stricter shared policy before publishing an alighting
    passenger, allowing Metro's existing candidate search and pending queue to
    provide backpressure when the source is occupied.

    Scheduled entry demand is also retained in a FIFO until a collision-free
    source position is found.  Admission is completed before constructing a
    Mesa agent, so a blocked source cannot leak a half-built agent, consume an
    ID, publish a trace frame, or increment a demand counter.

    This is deliberately a compatibility policy, not a claim that native-body
    admission and passenger publication are atomic in Metro itself.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.alignment_pending_source_demands: deque[PendingSourceDemand] = deque()
        self.alignment_next_source_sequence_id = 0
        self.alignment_requested_source_persons_by_intent: Counter[str] = Counter()
        self.alignment_max_pending_source_groups = 0
        self.alignment_source_deferred_attempts = 0

    def spawn_passengers(self) -> None:
        due_by_intent = self.demand_scheduler.due_by_intent(self.step_index)
        for intent, count in due_by_intent.items():
            self.alignment_requested_source_persons_by_intent[str(intent)] += (
                int(count) * int(self.scenario.group_size)
            )
            for _ in range(int(count)):
                self.alignment_pending_source_demands.append(
                    self._alignment_schedule_source_demand(str(intent))
                )

        self.alignment_max_pending_source_groups = max(
            self.alignment_max_pending_source_groups,
            len(self.alignment_pending_source_demands),
        )
        pending_round = list(self.alignment_pending_source_demands)
        self.alignment_pending_source_demands.clear()
        blocked_source_ids: set[str] = set()
        for index, demand in enumerate(pending_round):
            if demand.source_id in blocked_source_ids:
                self.alignment_pending_source_demands.append(demand)
                continue
            admission = self._alignment_source_admission(demand)
            if admission is None:
                self.alignment_source_deferred_attempts += 1
                blocked_source_ids.add(demand.source_id)
                self.alignment_pending_source_demands.append(demand)
                self.audit.record(
                    "alignment_source_demand_deferred_without_clear_spawn_cell",
                    source="alignment_source_admission",
                    severity="warning",
                    step=self.step_index,
                    context={
                        "sequence_id": demand.sequence_id,
                        "scheduled_step": demand.scheduled_step,
                        "intent": demand.intent,
                        "source_id": demand.source_id,
                        "pending_groups": (
                            len(self.alignment_pending_source_demands)
                            + len(pending_round)
                            - index
                            - 1
                        ),
                    },
                )
                continue

            try:
                passenger = self._spawn_passenger(
                    demand.intent,
                    initial_position=admission.position,
                    initial_level_id=admission.level_id,
                )
            except BaseException:
                self.alignment_pending_source_demands.append(demand)
                self.alignment_pending_source_demands.extend(
                    pending_round[index + 1 :]
                )
                raise
            if admission.source_element_id is not None:
                passenger.spawn_source_element_id = admission.source_element_id
                self.spawned_persons_by_entrance[admission.source_element_id] += (
                    passenger.group_size
                )
        self._require_alignment_source_conservation()

    def _require_alignment_source_conservation(self) -> None:
        requested = sum(self.alignment_requested_source_persons_by_intent.values())
        admitted = sum(
            int(self.spawned_persons_by_intent[intent])
            for intent in self.alignment_requested_source_persons_by_intent
        )
        pending = sum(
            demand.group_size for demand in self.alignment_pending_source_demands
        )
        if requested != admitted + pending:
            raise RuntimeError(
                "alignment source-demand conservation failed: "
                f"requested={requested}, admitted={admitted}, pending={pending}"
            )

    def _alignment_schedule_source_demand(self, intent: str) -> PendingSourceDemand:
        station_graph = getattr(self.layout_graph, "station_graph", None)
        if station_graph is None:
            raise RuntimeError(
                "alignment source backpressure requires Metro's compiled station graph"
            )

        intent_value = str(intent)
        if intent_value in {
            AgentIntent.EXIT_STATION.value,
            AgentIntent.EVACUATE_STATION.value,
            AgentIntent.TRANSFER.value,
        }:
            nodes = station_graph.nodes_matching(kind="platform")
            local_radius = 3.0
            node = self.random.choice(nodes) if nodes else None
        else:
            nodes = station_graph.nodes_matching(kind="entrance")
            local_radius = 2.4
            node = self._alignment_select_entrance_node(nodes) if nodes else None
        if node is None:
            raise RuntimeError(f"no source node is available for intent {intent_value!r}")

        demand = PendingSourceDemand(
            sequence_id=self.alignment_next_source_sequence_id,
            scheduled_step=int(self.step_index),
            intent=intent_value,
            group_size=int(self.scenario.group_size),
            source_node=node,
            source_id=str(node.element_id or node.node_id),
            level_id=str(node.level_id),
            local_radius=local_radius,
        )
        self.alignment_next_source_sequence_id += 1
        return demand

    def _alignment_source_admission(
        self,
        demand: PendingSourceDemand,
    ) -> SourceAdmission | None:
        """Select a source position without constructing or publishing an agent."""

        random_state = self.random.getstate()
        position = self._alignment_sample_source_position(
            demand.source_node,
            local_radius=demand.local_radius,
        )
        if position is None:
            self.random.setstate(random_state)
            return None
        return SourceAdmission(
            position=position,
            level_id=demand.level_id,
            source_element_id=(
                demand.source_id
                if demand.intent == AgentIntent.ENTER_AND_BOARD.value
                else None
            ),
        )

    def _alignment_select_entrance_node(self, entrance_nodes):
        configured = dict(self.scenario.entry_entrance_weights)
        if not configured:
            return self.random.choice(entrance_nodes)
        weighted = [
            (node, float(configured.get(str(node.element_id), 0.0)))
            for node in sorted(entrance_nodes, key=lambda item: item.node_id)
        ]
        total = sum(weight for _, weight in weighted)
        draw = self.random.random() * total
        cumulative = 0.0
        for node, weight in weighted:
            cumulative += weight
            if draw <= cumulative:
                return node
        return weighted[-1][0]

    def _alignment_sample_source_position(
        self,
        node,
        *,
        local_radius: float,
    ) -> tuple[float, float] | None:
        station_graph = self.layout_graph.station_graph
        document = getattr(station_graph, "source_document", None)
        if document is None or node.element_id is None:
            candidate = self.clamp_position(node.position)
            return candidate if self._alignment_source_cell_is_clear(candidate, node.level_id) else None

        element = document.element_by_id().get(node.element_id)
        if element is None:
            candidate = self.clamp_position(node.position)
            return candidate if self._alignment_source_cell_is_clear(candidate, node.level_id) else None

        walkable = document_walkable_geometry(document)
        if element.kind == "walkable_area" or element.role == "floor":
            domain = element_walkable_domain(element, walkable)
        else:
            level_domain = level_walkable_geometry(document, node.level_id, walkable)
            domain = level_domain.intersection(
                element_shape(element.geometry).buffer(max(0.1, local_radius))
            )
            if domain.is_empty:
                domain = level_domain.intersection(
                    ShapelyPoint(node.position).buffer(max(0.1, local_radius))
                )
            if domain.is_empty:
                candidate = self.clamp_position(
                    project_to_safe_point(
                        level_domain,
                        node.position,
                        clearance=self._alignment_initial_body_clearance(),
                        require_inside=False,
                    )
                )
                return (
                    candidate
                    if self._alignment_source_cell_is_clear(candidate, node.level_id)
                    else None
                )

        for _attempt in range(512):
            candidate = self.clamp_position(
                sample_safe_point(
                    domain,
                    self.random,
                    clearance=self._alignment_initial_body_clearance(),
                )
            )
            if self._alignment_source_cell_is_clear(candidate, node.level_id):
                return candidate
        return None

    def _alignment_initial_body_clearance(self) -> float:
        return max(0.02, float(self.scenario.jupedsim_agent_radius_units) * 1.05)

    def _alignment_source_cell_is_clear(
        self,
        candidate: tuple[float, float],
        level_id: str,
    ) -> bool:
        minimum_distance = minimum_body_clearance(self)
        return all(
            (passenger.physical_motion_layer_id or passenger.current_level_id) != level_id
            or hypot(candidate[0] - passenger.pos[0], candidate[1] - passenger.pos[1])
            >= minimum_distance - 1e-9
            for passenger in self.passengers
        )

    def _should_stop(self) -> bool:
        if self.step_index >= self.scenario.horizon_steps:
            return True
        return super()._should_stop() and not self.alignment_pending_source_demands

    def alignment_source_admission_metrics(self) -> dict[str, int | str | bool]:
        group_size = int(self.scenario.group_size)
        pending_source_groups = len(self.alignment_pending_source_demands)
        pending_entry_groups = sum(
            demand.intent == AgentIntent.ENTER_AND_BOARD.value
            for demand in self.alignment_pending_source_demands
        )
        pending_source_persons = sum(
            demand.group_size for demand in self.alignment_pending_source_demands
        )
        requested_due_source_persons = sum(
            self.alignment_requested_source_persons_by_intent.values()
        )
        scheduled_entry_persons = sum(
            int(counter.get(AgentIntent.ENTER_AND_BOARD.value, 0)) * group_size
            for counter in self.demand_scheduler.spawn_schedule.values()
        )
        scheduled_source_persons = sum(
            sum(int(count) for count in counter.values()) * group_size
            for counter in self.demand_scheduler.spawn_schedule.values()
        )
        spawned_entry_persons = int(
            self.spawned_persons_by_intent[AgentIntent.ENTER_AND_BOARD.value]
        )
        spawned_source_persons = sum(
            int(self.spawned_persons_by_intent[intent])
            for intent in {
                intent
                for counter in self.demand_scheduler.spawn_schedule.values()
                for intent in counter
            }
        )
        pending_entry_persons = pending_entry_groups * group_size
        return {
            "alignment_source_admission_policy": "alignment_source_backpressure.v1",
            "alignment_scheduled_source_persons": scheduled_source_persons,
            "alignment_requested_due_source_persons": requested_due_source_persons,
            "alignment_pending_source_groups": pending_source_groups,
            "alignment_pending_source_persons": pending_source_persons,
            "alignment_scheduled_entry_persons": scheduled_entry_persons,
            "alignment_pending_entry_groups": pending_entry_groups,
            "alignment_pending_entry_persons": pending_entry_persons,
            "alignment_max_pending_source_groups": self.alignment_max_pending_source_groups,
            "alignment_source_deferred_attempts": self.alignment_source_deferred_attempts,
            "alignment_entry_dropped_persons": (
                scheduled_entry_persons - spawned_entry_persons - pending_entry_persons
            ),
            "alignment_entry_demand_conserved": (
                scheduled_entry_persons == spawned_entry_persons + pending_entry_persons
            ),
            "alignment_source_dropped_persons": (
                scheduled_source_persons - spawned_source_persons - pending_source_persons
            ),
            "alignment_source_demand_conserved": (
                scheduled_source_persons == spawned_source_persons + pending_source_persons
            ),
            "alignment_active_boardings": sum(
                len(door.active_boardings) for door in self.boarding_doors
            ),
            "alignment_reserved_boarding_persons": sum(
                int(train.reserved_boarding_persons) for train in self.trains
            ),
            "alignment_departure_safety_hold_steps": sum(
                int(train.departure_safety_hold_steps) for train in self.trains
            ),
        }

    def _alighting_spawn_cell_is_clear(
        self,
        candidate: tuple[float, float],
        level_id: str,
        reserved_positions: list[tuple[tuple[float, float], str]],
    ) -> bool:
        if not super()._alighting_spawn_cell_is_clear(
            candidate,
            level_id,
            reserved_positions,
        ):
            return False

        minimum_distance = minimum_body_clearance(self)
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


class AlignmentMesaSimulationExecutor(MesaSimulationExecutor):
    """Build the alignment-scoped Metro model without changing Metro sources."""

    def build_model(
        self,
        request: SimulationRequest[StationSandboxScenario],
    ) -> AlignmentMetroStationModel:
        return AlignmentMetroStationModel(
            request.scenario,
            seed=request.seed,
            routing_algorithm=self.routing_algorithm,
            routing_parameters=self.routing_parameters,
        )

    def execute(
        self,
        request: SimulationRequest[StationSandboxScenario],
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> SimulationExecutionResult[dict, AlignmentMetroStationModel]:
        preflight = alignment_source_geometry_preflight(request.scenario)
        if preflight["status"] != "pass":
            raise AlignmentSourceGeometryConflict(preflight)
        model = self.build_model(request)
        frames = model.run(progress_callback=progress_callback)
        return SimulationExecutionResult(frames=frames, runtime=model)
