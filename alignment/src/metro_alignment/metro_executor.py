from __future__ import annotations

import hashlib
import json
from collections import Counter, deque
from dataclasses import dataclass, replace
from math import cos, hypot, radians, sin
from pathlib import Path
from random import Random
from typing import NamedTuple

from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.compilation.validation import (
    validate_compiled_station_design,
)
from metro_station.adapters.simulation.executor import MesaSimulationExecutor
from metro_station.adapters.simulation.facilities.admission_resource import (
    AdmissionTokenResource,
)
from metro_station.adapters.simulation.facilities.runtime import FacilityProcessAgent
from metro_station.adapters.simulation.movement.dynamic_body_clearance import (
    minimum_body_clearance,
)
from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.demand_scheduler import DemandScheduler
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.spatial_capacity_admission import (
    SpatialCapacityAdmissionError,
    SpatialCapacityEvidence,
    record_spatial_capacity_event,
)
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

from .admission_tokens import AdmissionTokenPolicy, admission_preflight_report
from .analysis_runtime import analysis_runtime_fingerprint
from .metro_runtime import metro_source_fingerprint

_SOURCE_ADMISSION_FLOWS = {
    AgentIntent.ENTER_AND_BOARD.value: ("entry", "entry_gate:"),
    AgentIntent.EXIT_STATION.value: ("exit", "exit_gate:"),
}


def _nearest_rank(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(int(value) for value in values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile + 0.999999) - 1))
    return ordered[index]


def _right_censored_nearest_rank(
    completed_values: list[int],
    censored_values: list[int],
    percentile: float,
) -> int | None:
    target_rank = int(
        (len(completed_values) + len(censored_values)) * percentile + 0.999999
    )
    if target_rank <= 0 or len(completed_values) < target_rank:
        return None
    ordered = sorted(int(value) for value in completed_values)
    return ordered[target_rank - 1]


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


@dataclass(frozen=True)
class PendingUnresolvedSourceDemand:
    scheduled_step: int
    intent: str
    group_size: int


class AlignmentSourceGeometryConflict(RuntimeError):
    def __init__(self, report: dict) -> None:
        self.report = report
        super().__init__(
            "alignment source geometry preflight failed: "
            + json.dumps(report, ensure_ascii=False, sort_keys=True)
        )


class AlignmentAdmissionCapacityConflict(RuntimeError):
    def __init__(self, report: dict) -> None:
        self.report = report
        super().__init__(
            "alignment admission preflight failed: "
            + json.dumps(report, ensure_ascii=False, sort_keys=True)
        )


def _alignment_admission_policies(
    scenario: StationSandboxScenario,
) -> tuple[AdmissionTokenPolicy, ...]:
    scheduler = DemandScheduler.from_scenario(
        scenario,
        Random(int(scenario.admission_residence_evidence_seed or 0)),
    )
    entry_schedule = {
        step: int(counter.get(AgentIntent.ENTER_AND_BOARD.value, 0))
        for step, counter in scheduler.spawn_schedule.items()
    }
    return (
        AdmissionTokenPolicy(
            flow_id="entry",
            count_hour=int(scenario.entry_count_hour),
            registered_residence_seconds=scenario.entry_admission_residence_seconds,
            residence_percentile=scenario.entry_admission_residence_percentile,
            residence_evidence_ref=scenario.entry_admission_residence_evidence_ref,
            burst_sigma=float(scenario.entry_admission_burst_sigma),
            configured_capacity=scenario.entry_admission_token_capacity,
            deterministic_arrival_envelope=_deterministic_arrival_envelope(
                entry_schedule,
                residence_seconds=scenario.entry_admission_residence_seconds,
                tick_seconds=scenario.tick_seconds,
                group_size=scenario.group_size,
            ),
            evidence_validation_errors=_residence_evidence_validation_errors(
                scenario,
                flow="entry",
            ),
        ),
        AdmissionTokenPolicy(
            flow_id="exit",
            count_hour=int(scenario.exit_count_hour),
            registered_residence_seconds=scenario.exit_admission_residence_seconds,
            residence_percentile=scenario.exit_admission_residence_percentile,
            residence_evidence_ref=scenario.exit_admission_residence_evidence_ref,
            burst_sigma=float(scenario.entry_admission_burst_sigma),
            configured_capacity=scenario.exit_admission_token_capacity,
            deterministic_arrival_envelope=_deterministic_arrival_envelope(
                scheduler.alighting_schedule,
                residence_seconds=scenario.exit_admission_residence_seconds,
                tick_seconds=scenario.tick_seconds,
                group_size=scenario.group_size,
            ),
            evidence_validation_errors=_residence_evidence_validation_errors(
                scenario,
                flow="exit",
            ),
        ),
    )


def _deterministic_arrival_envelope(
    schedule: dict[int, object],
    *,
    residence_seconds: float | None,
    tick_seconds: int,
    group_size: int,
) -> int:
    if residence_seconds is None or not schedule:
        return 0
    window_steps = max(
        1,
        int(float(residence_seconds) / float(tick_seconds) + 0.999999),
    )
    arrivals = sorted((int(step), int(count)) for step, count in schedule.items())
    return max(
        sum(
            count
            for candidate_step, count in arrivals
            if start_step <= candidate_step < start_step + window_steps
        )
        * int(group_size)
        for start_step, _count in arrivals
    )


def _residence_evidence_validation_errors(
    scenario: StationSandboxScenario,
    *,
    flow: str,
) -> tuple[dict[str, str], ...]:
    ref = str(getattr(scenario, f"{flow}_admission_residence_evidence_ref") or "")
    seconds = getattr(scenario, f"{flow}_admission_residence_seconds")
    percentile = getattr(scenario, f"{flow}_admission_residence_percentile")
    if not ref or seconds is None or percentile not in {"p90", "p99"}:
        return ()
    reference_path, separator, pointer = ref.partition("#")
    errors: list[dict[str, str]] = []
    if not separator or pointer != f"{flow}.{percentile}":
        errors.append(
            {
                "code": "admission_residence_evidence_pointer_mismatch",
                "message": f"{flow} evidence ref must end with #{flow}.{percentile}",
            }
        )
        return tuple(errors)
    repository_root = Path(__file__).resolve().parents[3]
    path = (repository_root / reference_path).resolve()
    try:
        path.relative_to(repository_root)
    except ValueError:
        errors.append(
            {
                "code": "admission_residence_evidence_path_invalid",
                "message": f"{flow} evidence path escapes the repository",
            }
        )
        return tuple(errors)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(
            {
                "code": "admission_residence_evidence_unreadable",
                "message": f"{flow} evidence cannot be read: {type(exc).__name__}",
            }
        )
        return tuple(errors)
    registered_hash = payload.get("artifact_sha256")
    unhashed = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    actual_hash = hashlib.sha256(
        json.dumps(
            unhashed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    if registered_hash != actual_hash:
        errors.append(
            {
                "code": "admission_residence_evidence_hash_mismatch",
                "message": f"{flow} evidence artifact hash is missing or invalid",
            }
        )
    design_bytes = json.dumps(
        scenario.station_design.as_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    design_sha256 = hashlib.sha256(design_bytes).hexdigest()
    if payload.get("design_sha256") != design_sha256:
        errors.append(
            {
                "code": "admission_residence_evidence_design_mismatch",
                "message": f"{flow} evidence design fingerprint does not match",
            }
        )
    if payload.get("metro_runtime_fingerprint") != metro_source_fingerprint():
        errors.append(
            {
                "code": "admission_residence_evidence_metro_runtime_mismatch",
                "message": f"{flow} evidence Metro runtime fingerprint does not match",
            }
        )
    if payload.get("analysis_runtime_fingerprint") != analysis_runtime_fingerprint():
        errors.append(
            {
                "code": "admission_residence_evidence_analysis_runtime_mismatch",
                "message": f"{flow} evidence analysis runtime fingerprint does not match",
            }
        )
    scheduler = DemandScheduler.from_scenario(
        scenario,
        Random(int(scenario.admission_residence_evidence_seed or 0)),
    )
    entry_schedule = {
        int(step): int(counter.get(AgentIntent.ENTER_AND_BOARD.value, 0))
        for step, counter in scheduler.spawn_schedule.items()
    }
    exit_schedule = {
        int(step): int(count) for step, count in scheduler.alighting_schedule.items()
    }
    scope = payload.get("evidence_scope", {})
    expected_scope = {
        "seed": scenario.admission_residence_evidence_seed,
        "entry_count_hour": int(scenario.entry_count_hour),
        "exit_count_hour": int(scenario.exit_count_hour),
        "demand_minutes": int(scenario.demand_duration_minutes),
        "entry_scheduled_persons": sum(entry_schedule.values())
        * int(scenario.group_size),
        "exit_scheduled_persons": sum(exit_schedule.values())
        * int(scenario.group_size),
        "entry_last_scheduled_step": max(entry_schedule, default=-1),
        "exit_last_scheduled_step": max(exit_schedule, default=-1),
        "group_size": int(scenario.group_size),
        "gate_service_persons_per_min": int(scenario.gate_service_persons_per_min),
        "train_dwell_seconds": int(scenario.train_dwell_seconds),
        "train_headway_seconds": int(scenario.train_headway_seconds),
        "initial_train_offset_seconds": int(scenario.initial_train_offset_seconds),
        "jupedsim_dt_seconds": float(scenario.jupedsim_dt_seconds),
        "jupedsim_iterations_per_tick": int(scenario.jupedsim_iterations_per_tick),
        "jupedsim_desired_speed_mps": float(scenario.jupedsim_desired_speed_mps),
        "jupedsim_free_speed_min_mps": float(
            scenario.jupedsim_free_speed_min_mps
        ),
        "jupedsim_free_speed_max_mps": float(
            scenario.jupedsim_free_speed_max_mps
        ),
        "jupedsim_agent_radius_units": float(scenario.jupedsim_agent_radius_units),
        "jupedsim_clearance_multiplier": float(
            scenario.jupedsim_clearance_multiplier
        ),
        "movement_backend_name": str(scenario.movement_backend_name),
        "jupedsim_operational_model": str(scenario.jupedsim_operational_model),
    }
    comparable_scope = dict(scope) if isinstance(scope, dict) else {}
    measurement_horizon_steps = comparable_scope.pop(
        "measurement_horizon_steps", None
    )
    if comparable_scope != expected_scope:
        errors.append(
            {
                "code": "admission_residence_evidence_scope_mismatch",
                "message": f"{flow} evidence demand/movement/seed scope does not match",
            }
        )
    last_scheduled_step = expected_scope[f"{flow}_last_scheduled_step"]
    required_measurement_horizon = int(last_scheduled_step) + int(
        float(seconds) / float(scenario.tick_seconds) + 0.999999
    )
    if (
        not isinstance(measurement_horizon_steps, int)
        or measurement_horizon_steps < required_measurement_horizon
    ):
        errors.append(
            {
                "code": "admission_residence_evidence_clearance_tail_insufficient",
                "message": (
                    f"{flow} evidence horizon {measurement_horizon_steps!r} is below "
                    f"last schedule + W = {required_measurement_horizon} steps"
                ),
            }
        )
    measured = payload.get(flow, {}).get(f"{percentile}_steps")
    if measured != seconds:
        errors.append(
            {
                "code": "admission_residence_evidence_value_mismatch",
                "message": (
                    f"{flow} registered residence {seconds!r} does not match "
                    f"artifact {percentile}={measured!r}"
                ),
            }
        )
    return tuple(errors)


def alignment_entry_admission_preflight(scenario: StationSandboxScenario) -> dict:
    """Compatibility entry point returning the complete two-flow preflight."""

    return admission_preflight_report(_alignment_admission_policies(scenario))


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
                lateral_offset_m=scenario.alighting_source_lateral_offset_m,
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

    def __init__(self, *args, formal_horizon_steps: int | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if formal_horizon_steps is not None and not (
            1 <= formal_horizon_steps <= self.scenario.horizon_steps
        ):
            raise ValueError("formal horizon must be within the scenario horizon")
        self.formal_horizon_steps = formal_horizon_steps
        self.alignment_pending_source_demands: deque[PendingSourceDemand] = deque()
        self.alignment_unresolved_source_demands: deque[
            PendingUnresolvedSourceDemand
        ] = deque()
        self.alignment_next_source_sequence_id = 0
        self.alignment_requested_source_persons_by_intent: Counter[str] = Counter()
        self.alignment_max_pending_source_groups = 0
        self.alignment_source_deferred_attempts = 0
        policies = _alignment_admission_policies(self.scenario)
        if any(policy.effective_capacity is None for policy in policies):
            raise AlignmentAdmissionCapacityConflict(
                admission_preflight_report(policies)
            )
        self.alignment_admission_policies = {
            policy.flow_id: policy for policy in policies
        }
        self.alignment_admission_resources = {
            policy.flow_id: AdmissionTokenResource(
                resource_id=f"alignment:{policy.flow_id}_admission_tokens",
                capacity=int(policy.effective_capacity),
            )
            for policy in policies
        }
        self.alignment_admission_attempts: Counter[str] = Counter()
        self.alignment_admission_exhausted_attempts: Counter[str] = Counter()
        self.alignment_max_pending_residence_steps_by_flow: Counter[str] = Counter()
        self._alignment_inflight_admission_owner_by_intent: dict[str, object] = {}
        self.alignment_requested_alighting_persons = 0
        self.alignment_pending_alighting_scheduled_steps: deque[int] = deque()

    def _record_alighting_demand_due(self, newly_due_groups: int) -> None:
        self.alignment_requested_alighting_persons += (
            int(newly_due_groups) * int(self.scenario.group_size)
        )
        self.alignment_pending_alighting_scheduled_steps.extend(
            int(self.step_index) for _ in range(int(newly_due_groups))
        )

    def _require_alighting_spawn_conservation(self) -> None:
        requested = int(self.alignment_requested_alighting_persons)
        admitted = int(
            self.spawned_persons_by_intent[AgentIntent.EXIT_STATION.value]
        )
        pending = int(self.pending_alighting_groups) * int(self.scenario.group_size)
        if len(self.alignment_pending_alighting_scheduled_steps) != int(
            self.pending_alighting_groups
        ):
            raise RuntimeError(
                "alignment alighting pending ownership failed: "
                f"owners={len(self.alignment_pending_alighting_scheduled_steps)}, "
                f"pending_groups={self.pending_alighting_groups}"
            )
        oldest_pending_residence = max(
            (
                int(self.step_index) - scheduled_step
                for scheduled_step in self.alignment_pending_alighting_scheduled_steps
            ),
            default=0,
        )
        self.alignment_max_pending_residence_steps_by_flow["exit"] = max(
            self.alignment_max_pending_residence_steps_by_flow["exit"],
            oldest_pending_residence,
        )
        if requested != admitted + pending:
            raise RuntimeError(
                "alignment alighting-demand conservation failed: "
                f"requested={requested}, admitted={admitted}, pending={pending}"
            )

    def _alighting_source_admission_reservation(
        self,
        doors: list[FacilityProcessAgent],
    ) -> dict[str, object]:
        del doors
        flow = "exit"
        resource = self.alignment_admission_resources[flow]
        self.alignment_admission_attempts[flow] += 1
        provisional_owner = f"alighting:{self.alignment_next_source_sequence_id}"
        self.alignment_next_source_sequence_id += 1
        if not resource.acquire(provisional_owner, self.step_index):
            self._defer_exhausted_admission_token(flow)
            return {
                "available": False,
                "admission_resource": resource.resource_id,
                "resource_semantics": "counting_signal_not_physical_storage",
                "certified_downstream_slots": resource.capacity,
                "occupied_downstream_slots": resource.occupancy,
            }
        self._alignment_inflight_admission_owner_by_intent[
            AgentIntent.EXIT_STATION.value
        ] = provisional_owner
        return {
            "available": True,
            "admission_resource": resource.resource_id,
            "resource_semantics": "counting_signal_not_physical_storage",
            "certified_downstream_slots": resource.capacity,
            "occupied_downstream_slots": resource.occupancy,
            "reservation_owner": provisional_owner,
        }

    def _release_alighting_source_admission_reservation(
        self,
        reservation: dict[str, object],
        *,
        reason: str,
    ) -> None:
        owner = reservation.get("reservation_owner")
        self._alignment_inflight_admission_owner_by_intent.pop(
            AgentIntent.EXIT_STATION.value,
            None,
        )
        if owner is not None:
            self.alignment_admission_resources["exit"].release(
                owner,
                self.step_index,
                reason=reason,
            )

    def _commit_alighting_source_admission_reservation(
        self,
        reservation: dict[str, object],
        passenger: PassengerAgent,
    ) -> None:
        owner = reservation.get("reservation_owner")
        self._alignment_inflight_admission_owner_by_intent.pop(
            AgentIntent.EXIT_STATION.value,
            None,
        )
        if owner is None:
            raise RuntimeError("alighting admission reservation owner is missing")
        if not self.alignment_pending_alighting_scheduled_steps:
            raise RuntimeError("alighting pending FIFO is empty at publication commit")
        resource = self.alignment_admission_resources["exit"]
        try:
            resource.transfer(owner, int(passenger.unique_id))
        except BaseException:
            if owner in resource.owners:
                resource.release(
                    owner,
                    self.step_index,
                    reason="publication_commit_exception",
                )
            raise
        finally:
            self.alignment_pending_alighting_scheduled_steps.popleft()

    def spawn_passengers(self) -> None:
        self._release_completed_source_admission_tokens()
        due_by_intent = self.demand_scheduler.due_by_intent(self.step_index)
        new_unresolved_demands: list[PendingUnresolvedSourceDemand] = []
        requested_increments: Counter[str] = Counter()
        for intent, count in due_by_intent.items():
            requested_increments[str(intent)] += int(count) * int(
                self.scenario.group_size
            )
            new_unresolved_demands.extend(
                PendingUnresolvedSourceDemand(
                    scheduled_step=int(self.step_index),
                    intent=str(intent),
                    group_size=int(self.scenario.group_size),
                )
                for _ in range(int(count))
            )
        self.alignment_unresolved_source_demands.extend(new_unresolved_demands)
        self.alignment_requested_source_persons_by_intent.update(
            requested_increments
        )
        try:
            while self.alignment_unresolved_source_demands:
                unresolved = self.alignment_unresolved_source_demands[0]
                resolved = replace(
                    self._alignment_schedule_source_demand(unresolved.intent),
                    scheduled_step=unresolved.scheduled_step,
                    group_size=unresolved.group_size,
                )
                self.alignment_pending_source_demands.append(resolved)
                self.alignment_unresolved_source_demands.popleft()
        except BaseException:
            self._finalize_alignment_source_phase()
            raise

        self.alignment_max_pending_source_groups = max(
            self.alignment_max_pending_source_groups,
            len(self.alignment_pending_source_demands),
        )
        pending_round = list(self.alignment_pending_source_demands)
        self.alignment_pending_source_demands.clear()
        for index, demand in enumerate(pending_round):
            flow = self._alignment_admission_flow(demand.intent)
            provisional_owner = None
            if flow is not None:
                self.alignment_admission_attempts[flow] += 1
                provisional_owner = f"demand:{demand.sequence_id}"
                resource = self.alignment_admission_resources[flow]
                if not resource.acquire(provisional_owner, self.step_index):
                    self.alignment_pending_source_demands.append(demand)
                    self.alignment_pending_source_demands.extend(
                        pending_round[index + 1 :]
                    )
                    try:
                        self._defer_exhausted_admission_token(flow)
                    finally:
                        self._finalize_alignment_source_phase()
                    return
            try:
                admission = self._alignment_source_admission(demand)
            except BaseException:
                if flow is not None and provisional_owner is not None:
                    self.alignment_admission_resources[flow].release(
                        provisional_owner,
                        self.step_index,
                        reason="source_admission_exception",
                    )
                self.alignment_pending_source_demands.append(demand)
                self.alignment_pending_source_demands.extend(
                    pending_round[index + 1 :]
                )
                self._finalize_alignment_source_phase()
                raise
            if admission is None:
                if flow is not None and provisional_owner is not None:
                    self.alignment_admission_resources[flow].release(
                        provisional_owner,
                        self.step_index,
                        reason="source_placement_blocked",
                    )
                self.alignment_source_deferred_attempts += 1
                self.alignment_pending_source_demands.append(demand)
                self.alignment_pending_source_demands.extend(
                    pending_round[index + 1 :]
                )
                try:
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
                            "pending_groups": len(
                                self.alignment_pending_source_demands
                            ),
                        },
                    )
                finally:
                    self._finalize_alignment_source_phase()
                return

            try:
                if flow is not None and provisional_owner is not None:
                    self._alignment_inflight_admission_owner_by_intent[
                        demand.intent
                    ] = provisional_owner
                passenger = self._spawn_passenger(
                    demand.intent,
                    initial_position=admission.position,
                    initial_level_id=admission.level_id,
                )
            except SpatialCapacityAdmissionError:
                if flow is not None and provisional_owner is not None:
                    self.alignment_admission_resources[flow].release(
                        provisional_owner,
                        self.step_index,
                        reason="physical_placement_retry",
                    )
                self.alignment_source_deferred_attempts += 1
                self.alignment_pending_source_demands.append(demand)
                self.alignment_pending_source_demands.extend(
                    pending_round[index + 1 :]
                )
                self._finalize_alignment_source_phase()
                return
            except BaseException:
                if flow is not None and provisional_owner is not None:
                    self.alignment_admission_resources[flow].release(
                        provisional_owner,
                        self.step_index,
                        reason="spawn_exception",
                    )
                self.alignment_pending_source_demands.append(demand)
                self.alignment_pending_source_demands.extend(
                    pending_round[index + 1 :]
                )
                self._finalize_alignment_source_phase()
                raise
            finally:
                self._alignment_inflight_admission_owner_by_intent.pop(
                    demand.intent,
                    None,
                )
            if flow is not None and provisional_owner is not None:
                resource = self.alignment_admission_resources[flow]
                try:
                    resource.transfer(
                        provisional_owner,
                        int(passenger.unique_id),
                    )
                except BaseException:
                    if provisional_owner in resource.owners:
                        resource.release(
                            provisional_owner,
                            self.step_index,
                            reason="publication_commit_exception",
                        )
                    self.alignment_pending_source_demands.extend(
                        pending_round[index + 1 :]
                    )
                    self._finalize_alignment_source_phase()
                    raise
            try:
                if admission.source_element_id is not None:
                    passenger.spawn_source_element_id = admission.source_element_id
                    self.spawned_persons_by_entrance[admission.source_element_id] += (
                        passenger.group_size
                    )
            except BaseException:
                self.alignment_pending_source_demands.extend(
                    pending_round[index + 1 :]
                )
                self._finalize_alignment_source_phase()
                raise
        self._finalize_alignment_source_phase()

    def _finalize_alignment_source_phase(self) -> None:
        for intent, (flow, _release_prefix) in _SOURCE_ADMISSION_FLOWS.items():
            self.alignment_max_pending_residence_steps_by_flow[flow] = max(
                self.alignment_max_pending_residence_steps_by_flow[flow],
                max(
                    [
                        int(self.step_index) - demand.scheduled_step
                        for demand in self.alignment_pending_source_demands
                        if demand.intent == intent
                    ]
                    + [
                        int(self.step_index) - demand.scheduled_step
                        for demand in self.alignment_unresolved_source_demands
                        if demand.intent == intent
                    ],
                    default=0,
                ),
            )
        self._require_alignment_source_conservation()

    def _defer_exhausted_admission_token(
        self,
        flow: str,
    ) -> None:
        self.alignment_admission_exhausted_attempts[flow] += 1
        resource = self.alignment_admission_resources[flow]
        evidence = SpatialCapacityEvidence(
            certificate_id=resource.resource_id,
            resource_kind="admission_token",
            owner_id=f"{flow}_source_flow",
            certified_body_capacity=resource.capacity,
            current_occupancy_bodies=resource.occupancy,
            requested_bodies=1,
            passenger_id=None,
        )
        record_spatial_capacity_event(
            self,
            f"alignment_{flow}_admission_token_exhausted",
            evidence,
        )
        record_spatial_capacity_event(self, "capacity.admission_exhausted", evidence)

    def _source_admission_evidence(
        self,
        intent: str,
        *,
        release_levels: set[str],
    ) -> dict[str, object]:
        flow = self._alignment_admission_flow(intent)
        if flow is None:
            return super()._source_admission_evidence(
                intent,
                release_levels=release_levels,
            )
        resource = self.alignment_admission_resources[flow]
        provisional_owner = self._alignment_inflight_admission_owner_by_intent.get(
            str(intent)
        )
        owns_credit = provisional_owner in resource.owners
        return {
            "available": owns_credit or resource.available > 0,
            "downstream_stage": f"{flow}_gate",
            "decision_region_id": f"{flow}_gate_decision",
            "certified_downstream_slots": resource.capacity,
            "occupied_downstream_slots": resource.occupancy,
            "admission_resource": resource.resource_id,
            "resource_semantics": "counting_signal_not_physical_storage",
        }

    @staticmethod
    def _alignment_admission_flow(intent: str) -> str | None:
        registration = _SOURCE_ADMISSION_FLOWS.get(str(intent))
        return None if registration is None else registration[0]

    def _release_completed_source_admission_tokens(self) -> None:
        passenger_by_id = {
            int(passenger.unique_id): passenger for passenger in self.passengers
        }
        for flow, release_prefix in _SOURCE_ADMISSION_FLOWS.values():
            resource = self.alignment_admission_resources[flow]
            for owner_id in resource.owners:
                if not isinstance(owner_id, int):
                    continue
                passenger = passenger_by_id.get(owner_id)
                if passenger is None:
                    resource.release(
                        owner_id,
                        self.step_index,
                        reason="owner_removed_after_publication",
                    )
                    self.audit.record(
                        "alignment_admission_owner_removed",
                        source="alignment_source_admission",
                        severity="warning",
                        step=self.step_index,
                        context={"flow": flow, "passenger_id": owner_id},
                    )
                    continue
                completed = str(
                    getattr(passenger, "last_completed_facility_id", None) or ""
                )
                if completed.startswith(release_prefix):
                    resource.release(
                        owner_id,
                        self.step_index,
                        reason="downstream_stage_released",
                    )

    def _finalize_facilities(self) -> None:
        try:
            super()._finalize_facilities()
        finally:
            for resource in self.alignment_admission_resources.values():
                resource.close(self.step_index)

    def _require_alignment_source_conservation(self) -> None:
        requested = sum(self.alignment_requested_source_persons_by_intent.values())
        admitted = sum(
            int(self.spawned_persons_by_intent[intent])
            for intent in self.alignment_requested_source_persons_by_intent
        )
        pending = sum(
            demand.group_size for demand in self.alignment_pending_source_demands
        ) + sum(
            demand.group_size for demand in self.alignment_unresolved_source_demands
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
        horizon = self.formal_horizon_steps or self.scenario.horizon_steps
        if self.step_index >= horizon:
            return True
        return (
            super()._should_stop()
            and not self.alignment_pending_source_demands
            and not self.alignment_unresolved_source_demands
        )

    def alignment_source_admission_metrics(self) -> dict[str, object]:
        group_size = int(self.scenario.group_size)
        evidence_horizon = int(
            getattr(self, "formal_horizon_steps", None) or self.scenario.horizon_steps
        )
        pending_source_groups = len(self.alignment_pending_source_demands) + len(
            self.alignment_unresolved_source_demands
        )
        pending_entry_groups = sum(
            demand.intent == AgentIntent.ENTER_AND_BOARD.value
            for demand in (
                *self.alignment_pending_source_demands,
                *self.alignment_unresolved_source_demands,
            )
        )
        pending_direct_exit_groups = sum(
            demand.intent == AgentIntent.EXIT_STATION.value
            for demand in (
                *self.alignment_pending_source_demands,
                *self.alignment_unresolved_source_demands,
            )
        )
        pending_source_persons = sum(
            demand.group_size
            for demand in (
                *self.alignment_pending_source_demands,
                *self.alignment_unresolved_source_demands,
            )
        )
        requested_due_source_persons = sum(
            self.alignment_requested_source_persons_by_intent.values()
        ) + int(self.alignment_requested_alighting_persons)
        scheduled_entry_persons = sum(
            int(counter.get(AgentIntent.ENTER_AND_BOARD.value, 0)) * group_size
            for step, counter in self.demand_scheduler.spawn_schedule.items()
            if int(step) < evidence_horizon
        )
        scheduled_exit_persons = (
            sum(
                int(count)
                for step, count in self.demand_scheduler.alighting_schedule.items()
                if int(step) < evidence_horizon
            )
            * group_size
        )
        scheduled_source_persons = scheduled_entry_persons + scheduled_exit_persons
        spawned_entry_persons = int(
            self.spawned_persons_by_intent[AgentIntent.ENTER_AND_BOARD.value]
        )
        spawned_exit_persons = int(
            self.spawned_persons_by_intent[AgentIntent.EXIT_STATION.value]
        )
        spawned_source_persons = spawned_entry_persons + spawned_exit_persons
        pending_entry_persons = pending_entry_groups * group_size
        pending_exit_groups = pending_direct_exit_groups + int(
            self.pending_alighting_groups
        )
        pending_exit_persons = pending_exit_groups * group_size
        pending_source_groups += int(self.pending_alighting_groups)
        pending_source_persons += int(self.pending_alighting_groups) * group_size
        metrics: dict[str, object] = {
            "alignment_source_admission_policy": "alignment_source_tokens.v2",
            "alignment_scheduled_source_persons": scheduled_source_persons,
            "alignment_requested_due_source_persons": requested_due_source_persons,
            "alignment_pending_source_groups": pending_source_groups,
            "alignment_pending_source_persons": pending_source_persons,
            "alignment_scheduled_entry_persons": scheduled_entry_persons,
            "alignment_pending_entry_groups": pending_entry_groups,
            "alignment_pending_entry_persons": pending_entry_persons,
            "alignment_scheduled_exit_persons": scheduled_exit_persons,
            "alignment_pending_exit_groups": pending_exit_groups,
            "alignment_pending_exit_persons": pending_exit_persons,
            "alignment_max_pending_source_groups": self.alignment_max_pending_source_groups,
            "alignment_source_deferred_attempts": self.alignment_source_deferred_attempts,
            "alignment_entry_dropped_persons": (
                scheduled_entry_persons - spawned_entry_persons - pending_entry_persons
            ),
            "alignment_entry_demand_conserved": (
                scheduled_entry_persons == spawned_entry_persons + pending_entry_persons
            ),
            "alignment_exit_dropped_persons": (
                scheduled_exit_persons - spawned_exit_persons - pending_exit_persons
            ),
            "alignment_exit_demand_conserved": (
                scheduled_exit_persons == spawned_exit_persons + pending_exit_persons
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
        for intent, (flow, _release_prefix) in _SOURCE_ADMISSION_FLOWS.items():
            resource = self.alignment_admission_resources[flow]
            attempts = int(self.alignment_admission_attempts[flow])
            exhausted = int(self.alignment_admission_exhausted_attempts[flow])
            completed_residence_steps = [
                item.residence_steps
                for item in resource.completed_residences
                if item.release_reason == "downstream_stage_released"
            ]
            censored_residence_steps = [
                item.residence_steps
                for item in resource.completed_residences
                if item.right_censored
            ] + resource.active_residence_steps(self.step_index)
            abnormal_residences = [
                {
                    "owner_id": str(item.owner_id),
                    "residence_steps": item.residence_steps,
                    "release_reason": item.release_reason,
                }
                for item in resource.completed_residences
                if item.release_reason
                not in {"downstream_stage_released", "lifecycle_right_censored"}
            ]
            residence_lower_bound_steps = (
                completed_residence_steps + censored_residence_steps
            )
            pending_residence = max(
                (
                    int(self.step_index) - demand.scheduled_step
                    for demand in (
                        *self.alignment_pending_source_demands,
                        *self.alignment_unresolved_source_demands,
                    )
                    if demand.intent == intent
                ),
                default=0,
            )
            if flow == "exit":
                pending_residence = max(
                    pending_residence,
                    max(
                        (
                            int(self.step_index) - scheduled_step
                            for scheduled_step in (
                                self.alignment_pending_alighting_scheduled_steps
                            )
                        ),
                        default=0,
                    ),
                )
            metrics.update(
                {
                    f"alignment_{flow}_admission_token_capacity": resource.capacity,
                    f"alignment_{flow}_admission_token_occupancy": resource.occupancy,
                    f"alignment_{flow}_admission_attempts": attempts,
                    f"alignment_{flow}_admission_exhausted_attempts": exhausted,
                    f"alignment_{flow}_admission_exhausted_ratio": (
                        exhausted / attempts if attempts else 0.0
                    ),
                    f"alignment_{flow}_max_pending_residence_steps": max(
                        self.alignment_max_pending_residence_steps_by_flow[flow],
                        pending_residence,
                    ),
                    f"alignment_{flow}_token_residence_steps": (
                        residence_lower_bound_steps
                    ),
                    f"alignment_{flow}_token_completed_residence_steps": (
                        completed_residence_steps
                    ),
                    f"alignment_{flow}_token_censored_residence_steps": (
                        censored_residence_steps
                    ),
                    f"alignment_{flow}_token_residence_n": len(
                        residence_lower_bound_steps
                    ),
                    f"alignment_{flow}_token_completed_residence_n": len(
                        completed_residence_steps
                    ),
                    f"alignment_{flow}_token_censored_residence_n": len(
                        censored_residence_steps
                    ),
                    f"alignment_{flow}_token_abnormal_residences": (
                        abnormal_residences
                    ),
                    f"alignment_{flow}_token_residence_p50_steps": _nearest_rank(
                        completed_residence_steps, 0.50
                    ),
                    f"alignment_{flow}_token_residence_p90_steps": _nearest_rank(
                        completed_residence_steps, 0.90
                    ),
                    f"alignment_{flow}_token_residence_p99_steps": _nearest_rank(
                        completed_residence_steps, 0.99
                    ),
                    f"alignment_{flow}_token_residence_censor_aware_p50_steps": (
                        _right_censored_nearest_rank(
                            completed_residence_steps,
                            censored_residence_steps,
                            0.50,
                        )
                    ),
                    f"alignment_{flow}_token_residence_censor_aware_p90_steps": (
                        _right_censored_nearest_rank(
                            completed_residence_steps,
                            censored_residence_steps,
                            0.90,
                        )
                    ),
                    f"alignment_{flow}_token_residence_censor_aware_p99_steps": (
                        _right_censored_nearest_rank(
                            completed_residence_steps,
                            censored_residence_steps,
                            0.99,
                        )
                    ),
                    f"alignment_{flow}_token_residence_lower_bound_p99_steps": (
                        _nearest_rank(residence_lower_bound_steps, 0.99)
                    ),
                }
            )
        return metrics

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

    def __init__(self, *args, formal_horizon_steps: int | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.formal_horizon_steps = formal_horizon_steps

    def build_model(
        self,
        request: SimulationRequest[StationSandboxScenario],
    ) -> AlignmentMetroStationModel:
        return AlignmentMetroStationModel(
            request.scenario,
            seed=request.seed,
            routing_algorithm=self.routing_algorithm,
            routing_parameters=self.routing_parameters,
            formal_horizon_steps=self.formal_horizon_steps,
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
        admission_preflight = alignment_entry_admission_preflight(request.scenario)
        if admission_preflight["status"] != "pass":
            raise AlignmentAdmissionCapacityConflict(admission_preflight)
        model = self.build_model(request)
        frames = model.run(progress_callback=progress_callback)
        return SimulationExecutionResult(frames=frames, runtime=model)
