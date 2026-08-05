from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from math import ceil, floor, hypot
from typing import Any, Iterable

from shapely import intersects_xy
from shapely.geometry import GeometryCollection, LineString, MultiPoint, Point as ShapelyPoint
from shapely.ops import unary_union

from ..design.schema import StationDesignDocument
from ..design.validation_issue import ValidationIssue, issue
from ..facilities.process import FacilityKind, FacilitySpec
from ..planning.plan import FacilityStage
from ..station.facility_portal_binding import FacilityPortalBinding, Point
from ..station.alighting_demand import peak_alighting_batch
from ..station.alighting_source_geometry import (
    alighting_source_projection_clearance_m,
    materialize_alighting_source_candidates,
)
from ..station.geometry import grid_safe_points, level_walkable_geometry
from ..station.graph import StationGraph
from .decision_holding_regions import (
    DecisionHoldingRegionBinding,
    _facility_ingress_corridors,
)
from .facility_portal_contract import NUMERICAL_TOLERANCE_M
from .geometry_reachability import GeometryCompilePolicy
from .spatial_capacity_geometry import (
    PointSpatialIndex as _PointSpatialIndex,
    boarding_queue_access_corridors as _boarding_queue_access_corridors,
    distance as _distance,
    gate_bank_tail_aisles as _gate_bank_tail_aisles,
    point_segment_distance as _point_segment_distance,
    station_walk_flow_corridors as _station_walk_flow_corridors,
)


CAPACITY_POLICY_VERSION = 1
STORAGE_RESOURCE_KINDS = frozenset(
    {
        "queue",
        "decision_holding",
        "alighting_source",
        "platform_waiting",
        "release_apron",
        "spawn_reservoir",
    }
)
PATH_RESOURCE_KINDS = frozenset({"service_corridor"})


@dataclass(frozen=True)
class SpatialCapacityCertificate:
    """Constructive lower bound for one finite physical resource.

    ``certified_body_capacity`` is deliberately not called maximum capacity.
    It is the number of deterministic placements or swept paths that this
    compiler actually materialised and checked for the declared body profile.
    Runtime admission may consume no more than this certificate; a larger
    theoretical circle packing is irrelevant until it too is constructed.
    """

    certificate_id: str
    resource_kind: str
    owner_id: str
    level_id: str
    slots: tuple[Point, ...]
    swept_paths: tuple[tuple[Point, ...], ...]
    certified_body_capacity: int
    certified_person_capacity: int
    required_body_capacity: int | None
    minimum_clearance_m: float
    density_bodies_per_m2: float
    body_profile_fingerprint: str
    domain_fingerprint: str
    activation_group_id: str | None = None
    activation_variant_id: str | None = None
    mutex_owner_ids: tuple[str, ...] = ()
    batch_plans: tuple[tuple[Point, ...], ...] = ()
    batch_swept_paths: tuple[tuple[tuple[Point, ...], ...], ...] = ()
    policy_version: int = CAPACITY_POLICY_VERSION
    domain: Any = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.resource_kind not in STORAGE_RESOURCE_KINDS | PATH_RESOURCE_KINDS:
            raise ValueError(f"unknown spatial resource kind {self.resource_kind!r}")
        materialized = (
            max(len(plan) for plan in self.batch_plans)
            if self.batch_plans
            else len(self.swept_paths)
            if self.resource_kind in PATH_RESOURCE_KINDS
            else len(self.slots)
        )
        if int(self.certified_body_capacity) != materialized:
            raise ValueError(
                f"certificate {self.certificate_id!r} declares body capacity "
                f"{self.certified_body_capacity} but materialises {materialized}"
            )
        if self.certified_person_capacity < self.certified_body_capacity:
            raise ValueError("person capacity cannot be smaller than body capacity")
        if self.minimum_clearance_m <= 0.0:
            raise ValueError("minimum clearance must be positive")
        if self.batch_plans and tuple(len(plan) for plan in self.batch_plans) != tuple(
            range(1, len(self.batch_plans) + 1)
        ):
            raise ValueError("batch plans must prove every stable prefix 1..B")
        if self.batch_swept_paths and tuple(
            len(plan) for plan in self.batch_swept_paths
        ) != tuple(range(1, len(self.batch_swept_paths) + 1)):
            raise ValueError("batch swept paths must prove every stable prefix 1..B")
        if self.batch_swept_paths and len(self.batch_swept_paths) != len(self.batch_plans):
            raise ValueError("batch point and swept-path proofs must cover the same prefixes")

    @property
    def has_demand_contract(self) -> bool:
        return self.required_body_capacity is not None

    @property
    def demand_margin_bodies(self) -> int | None:
        if self.required_body_capacity is None:
            return None
        return self.certified_body_capacity - self.required_body_capacity


@dataclass(frozen=True)
class SpatialDemandContract:
    """Scenario-specific storage demand bound attached to certificates."""

    contract_id: str
    resource_kind: str
    stage: str
    certificate_ids: tuple[str, ...]
    forecast_method: str
    arrival_bodies: int
    required_body_capacity: int
    certified_body_capacity: int
    certified_person_capacity: int
    horizon_seconds: float
    body_profile_fingerprint: str

    @property
    def margin_bodies(self) -> int:
        return self.certified_body_capacity - self.required_body_capacity


def compile_spatial_capacity_certificates(
    document: StationDesignDocument,
    graph: StationGraph,
    facilities: Iterable[FacilitySpec],
    portal_bindings: Iterable[FacilityPortalBinding],
    holding_regions: Iterable[DecisionHoldingRegionBinding],
    *,
    scenario: Any,
    policy: GeometryCompilePolicy,
) -> tuple[SpatialCapacityCertificate, ...]:
    """Compile every finite station-space resource before model start."""

    facility_by_id = {item.facility_id: item for item in facilities}
    bindings = tuple(portal_bindings)
    holdings = tuple(holding_regions)
    body_fingerprint = _body_profile_fingerprint(policy, scenario)
    certificates: list[SpatialCapacityCertificate] = []

    for binding in bindings:
        mutex_owner_ids = _binding_mutex_owner_ids(binding, bindings)
        queue_domain = level_walkable_geometry(
            document,
            binding.entry_level_id,
        ).buffer(-policy.agent_radius_m * 1.05)
        certificates.append(
            _storage_certificate(
                certificate_id=f"queue:{binding.facade_key}",
                resource_kind="queue",
                owner_id=binding.facility_id,
                level_id=binding.entry_level_id,
                slots=binding.approach_slots,
                domain=queue_domain,
                # Shared authored queues may fan out across several facades.
                # The portal compiler already proves their aggregate source
                # capacity; this per-facade certificate owns only the slots
                # that this runtime queue can actually admit.
                required_body_capacity=len(binding.approach_slots),
                group_size=int(scenario.group_size),
                minimum_clearance_m=policy.two_body_clearance_m,
                body_profile_fingerprint=body_fingerprint,
                activation_group_id=binding.activation_group_id,
                activation_variant_id=binding.activation_variant_id,
                mutex_owner_ids=mutex_owner_ids,
            )
        )

    for region in holdings:
        certificates.append(
            _storage_certificate(
                certificate_id=f"holding:{region.level_id}:{region.region_id}",
                resource_kind="decision_holding",
                owner_id=region.region_id,
                level_id=region.level_id,
                slots=region.slots,
                domain=region.domain,
                required_body_capacity=None,
                group_size=int(scenario.group_size),
                minimum_clearance_m=max(
                    policy.two_body_clearance_m,
                    policy.personal_space_m,
                ),
                body_profile_fingerprint=body_fingerprint,
            )
        )

    release_and_corridor: list[SpatialCapacityCertificate] = []
    for binding in bindings:
        facility = facility_by_id.get(binding.facility_id)
        if facility is None:
            continue
        coactive_release_certificates = (
            tuple(release_and_corridor)
            if binding.kind == FacilityKind.ESCALATOR.value
            else ()
        )
        blockers_by_level = _stationary_blockers_by_level(
            (*certificates, *coactive_release_certificates)
        )
        release, corridor = _facility_release_certificates(
            document,
            facility,
            binding,
            scenario=scenario,
            policy=policy,
            body_profile_fingerprint=body_fingerprint,
            blocked_positions=blockers_by_level.get(binding.exit_level_id, ()),
            mutex_owner_ids=_binding_mutex_owner_ids(binding, bindings),
        )
        release_and_corridor.extend((release, corridor))
    certificates.extend(release_and_corridor)

    alighting_sources = _alighting_source_certificates(
        document,
        facility_by_id,
        bindings,
        blocked_certificates=tuple(certificates),
        scenario=scenario,
        policy=policy,
        body_profile_fingerprint=body_fingerprint,
    )
    certificates.extend(alighting_sources)

    spawn_certificates = _spawn_reservoir_certificates(
        document,
        graph,
        certificates,
        scenario=scenario,
        policy=policy,
        body_profile_fingerprint=body_fingerprint,
    )
    certificates.extend(spawn_certificates)

    platform_certificates = _platform_waiting_certificates(
        document,
        graph,
        bindings,
        certificates,
        scenario=scenario,
        policy=policy,
        body_profile_fingerprint=body_fingerprint,
    )
    certificates.extend(platform_certificates)
    return tuple(sorted(certificates, key=lambda item: item.certificate_id))


def validate_spatial_capacity_certificates(
    certificates: Iterable[SpatialCapacityCertificate],
) -> list[ValidationIssue]:
    """Validate certificate self-consistency and co-active ownership."""

    items = tuple(certificates)
    issues: list[ValidationIssue] = []
    ids = [item.certificate_id for item in items]
    if len(ids) != len(set(ids)):
        issues.append(
            issue(
                "error",
                "capacity.certificate_duplicate",
                "spatial_capacity",
                "spatial capacity certificate IDs are not unique",
            )
        )
    for certificate in items:
        path = f"spatial_capacity.{certificate.certificate_id}"
        if certificate.policy_version != CAPACITY_POLICY_VERSION:
            issues.append(
                issue(
                    "error",
                    "capacity.policy_mismatch",
                    path,
                    "certificate was built with an incompatible capacity policy",
                )
            )
        required = certificate.required_body_capacity
        if required is not None and certificate.certified_body_capacity < required:
            if certificate.resource_kind == "release_apron":
                code = (
                    "release.batch_not_placeable"
                    if certificate.owner_id.startswith("vertical:")
                    else "release.capacity_not_materialized"
                )
            else:
                code = {
                    "queue": "queues.capacity_not_materialized",
                    "decision_holding": "holding.capacity_below_required",
                    "platform_waiting": "platform.capacity_below_required",
                    "service_corridor": "release.route_not_traversable",
                }.get(certificate.resource_kind, "capacity.demand_exceeds_storage")
            issues.append(
                issue(
                    "error",
                    code,
                    path,
                    f"resource requires {required} bodies but only "
                    f"{certificate.certified_body_capacity} deterministic places "
                    "were certified",
                )
            )
        if certificate.certified_body_capacity <= 0:
            code = (
                "release.capacity_not_materialized"
                if certificate.resource_kind == "release_apron"
                else "corridors.outside_walkable_area"
                if certificate.resource_kind == "service_corridor"
                else "capacity.certificate_empty"
            )
            issues.append(
                issue(
                    "error",
                    code,
                    path,
                    "resource has no constructively certified physical capacity",
                )
            )
        issues.extend(_certificate_geometry_issues(certificate, path))
    issues.extend(_coactive_certificate_issues(items))
    return _dedupe_issues(issues)


def compile_spatial_demand_contracts(
    facilities: Iterable[FacilitySpec],
    certificates: Iterable[SpatialCapacityCertificate],
    *,
    scenario: Any,
) -> tuple[SpatialDemandContract, ...]:
    """Bind static capacities to a deterministic scenario demand envelope.

    This is a storage/admission proof, not a pedestrian trajectory forecast.
    It uses the scenario's exact total group counts and a conservative fluid
    service envelope. Runtime still measures transient dynamic blocking.
    """

    facility_set = tuple(facilities)
    certificate_set = tuple(certificates)
    group_size = max(1, int(scenario.group_size))
    body_profile = next(
        (item.body_profile_fingerprint for item in certificate_set),
        "",
    )
    arrivals_by_stage = {
        FacilityStage.ENTRY_GATE.value: int(scenario.entry_groups),
        FacilityStage.VERTICAL_TRANSFER.value: int(
            scenario.entry_groups + scenario.exit_groups + scenario.transfer_groups
        ),
        FacilityStage.BOARDING_DOOR.value: int(
            scenario.entry_groups + scenario.transfer_groups
        ),
        FacilityStage.EXIT_GATE.value: int(scenario.exit_groups),
    }
    holding_owner_by_stage = {
        FacilityStage.ENTRY_GATE.value: "entry_gate_decision",
        FacilityStage.VERTICAL_TRANSFER.value: "vertical_decision",
        FacilityStage.BOARDING_DOOR.value: "boarding_decision",
        FacilityStage.EXIT_GATE.value: "exit_gate_decision",
    }
    duration_seconds = max(1.0, float(scenario.demand_duration_seconds))
    contracts: list[SpatialDemandContract] = []
    for stage, arrivals in arrivals_by_stage.items():
        stage_facilities = tuple(item for item in facility_set if item.stage == stage)
        service_bodies_per_second = sum(
            max(0.0, float(item.service_persons_per_min)) / group_size / 60.0
            for item in stage_facilities
        )
        required = (
            0
            if not stage_facilities
            else _fluid_peak_backlog(
                arrivals,
                duration_seconds=duration_seconds,
                service_bodies_per_second=service_bodies_per_second,
                tick_seconds=float(scenario.tick_seconds),
            )
        )
        owner_ids = {item.facility_id for item in stage_facilities}
        holding_owner = holding_owner_by_stage[stage]
        storage = tuple(
            item
            for item in certificate_set
            if (
                item.resource_kind == "queue" and item.owner_id in owner_ids
            )
            or (
                item.resource_kind == "decision_holding"
                and item.owner_id == holding_owner
            )
        )
        certified = sum(item.certified_body_capacity for item in storage)
        contracts.append(
            SpatialDemandContract(
                contract_id=f"stage_storage:{stage}",
                resource_kind="stage_storage",
                stage=stage,
                certificate_ids=tuple(sorted(item.certificate_id for item in storage)),
                forecast_method="fluid_arrival_service_envelope_v1",
                arrival_bodies=arrivals,
                required_body_capacity=required,
                certified_body_capacity=certified,
                certified_person_capacity=certified * group_size,
                horizon_seconds=duration_seconds,
                body_profile_fingerprint=body_profile,
            )
        )

    platform_certificates = tuple(
        item for item in certificate_set if item.resource_kind == "platform_waiting"
    )
    platform_certified = min(
        sum(item.certified_body_capacity for item in platform_certificates),
        max(1, int(scenario.platform_capacity_persons) // group_size),
    )
    platform_arrivals = int(scenario.entry_groups + scenario.transfer_groups)
    platform_required = _platform_peak_backlog(
        platform_arrivals,
        scenario=scenario,
        group_size=group_size,
    )
    contracts.append(
        SpatialDemandContract(
            contract_id="platform_waiting:all",
            resource_kind="platform_waiting",
            stage=FacilityStage.BOARDING_DOOR.value,
            certificate_ids=tuple(
                sorted(item.certificate_id for item in platform_certificates)
            ),
            forecast_method="train_service_envelope_v1",
            arrival_bodies=platform_arrivals,
            required_body_capacity=platform_required,
            certified_body_capacity=platform_certified,
            certified_person_capacity=platform_certified * group_size,
            horizon_seconds=float(scenario.horizon_duration_seconds),
            body_profile_fingerprint=body_profile,
        )
    )
    return tuple(contracts)


def validate_spatial_demand_contracts(
    contracts: Iterable[SpatialDemandContract],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for contract in contracts:
        path = f"spatial_demand.{contract.contract_id}"
        if contract.required_body_capacity > contract.certified_body_capacity:
            code = (
                "platform.capacity_below_required"
                if contract.resource_kind == "platform_waiting"
                else "capacity.demand_exceeds_storage"
            )
            issues.append(
                issue(
                    "error",
                    code,
                    path,
                    f"scenario requires storage for {contract.required_body_capacity} "
                    f"bodies but certificates admit {contract.certified_body_capacity}",
                )
            )
        elif (
            contract.required_body_capacity > 0
            and contract.margin_bodies
            <= max(1, ceil(contract.certified_body_capacity * 0.1))
        ):
            issues.append(
                issue(
                    "warning",
                    "capacity.forecast_margin_low",
                    path,
                    f"capacity margin is only {contract.margin_bodies} bodies",
                )
            )
    return issues


def _storage_certificate(
    *,
    certificate_id: str,
    resource_kind: str,
    owner_id: str,
    level_id: str,
    slots: Iterable[Point],
    domain: Any,
    required_body_capacity: int | None,
    group_size: int,
    minimum_clearance_m: float,
    body_profile_fingerprint: str,
    activation_group_id: str | None = None,
    activation_variant_id: str | None = None,
    mutex_owner_ids: tuple[str, ...] = (),
    batch_plans: tuple[tuple[Point, ...], ...] = (),
    batch_swept_paths: tuple[tuple[tuple[Point, ...], ...], ...] = (),
) -> SpatialCapacityCertificate:
    materialized = tuple((float(point[0]), float(point[1])) for point in slots)
    area = 0.0 if domain is None or domain.is_empty else float(domain.area)
    capacity = max((len(plan) for plan in batch_plans), default=len(materialized))
    return SpatialCapacityCertificate(
        certificate_id=certificate_id,
        resource_kind=resource_kind,
        owner_id=owner_id,
        level_id=level_id,
        slots=materialized,
        swept_paths=(),
        certified_body_capacity=capacity,
        certified_person_capacity=capacity * max(1, int(group_size)),
        required_body_capacity=required_body_capacity,
        minimum_clearance_m=max(0.001, float(minimum_clearance_m)),
        density_bodies_per_m2=(0.0 if area <= 1e-9 else capacity / area),
        body_profile_fingerprint=body_profile_fingerprint,
        domain_fingerprint=_geometry_fingerprint(domain),
        activation_group_id=activation_group_id,
        activation_variant_id=activation_variant_id,
        mutex_owner_ids=tuple(sorted(set(mutex_owner_ids))),
        batch_plans=batch_plans,
        batch_swept_paths=batch_swept_paths,
        domain=domain,
    )


def _facility_release_certificates(
    document: StationDesignDocument,
    facility: FacilitySpec,
    binding: FacilityPortalBinding,
    *,
    scenario: Any,
    policy: GeometryCompilePolicy,
    body_profile_fingerprint: str,
    blocked_positions: tuple[tuple[str, Point], ...],
    mutex_owner_ids: tuple[str, ...],
) -> tuple[SpatialCapacityCertificate, SpatialCapacityCertificate]:
    raw_domain = level_walkable_geometry(document, binding.exit_level_id)
    body_radius = max(0.02, policy.agent_radius_m)
    safe_domain = raw_domain.buffer(-body_radius * 1.05)
    spacing = _release_spacing(facility, policy)
    required = _required_release_bodies(facility, binding, scenario, spacing)
    blocked = tuple(
        point
        for owner_id, point in blocked_positions
        if owner_id not in mutex_owner_ids and owner_id != binding.facility_id
    )
    batch_plans: tuple[tuple[Point, ...], ...] = ()
    if facility.kind == FacilityKind.ELEVATOR.value:
        batch_plans, batch_path_plans = _compile_elevator_batch_plans(
            facility,
            binding,
            raw_domain=raw_domain,
            safe_domain=safe_domain,
            blocked_positions=blocked,
            required_capacity=required,
            spacing=spacing,
            policy=policy,
        )
        slots, paths = _elevator_release_envelope(
            facility,
            batch_path_plans,
            raw_domain=raw_domain,
            safe_domain=safe_domain,
            blocked_positions=blocked,
            spacing=spacing,
            policy=policy,
        )
    else:
        candidates = _release_candidate_grid(facility, binding, spacing, required)
        slots = []
        paths = []
        start = (
            binding.entry_point
            if binding.kind in {FacilityKind.GATE.value, FacilityKind.TRAIN_DOOR.value}
            and binding.entry_level_id == binding.exit_level_id
            else binding.exit_point
        )
        for candidate in candidates:
            point = ShapelyPoint(candidate)
            if not safe_domain.buffer(NUMERICAL_TOLERANCE_M).covers(point):
                continue
            if any(
                hypot(candidate[0] - previous[0], candidate[1] - previous[1])
                < max(policy.two_body_clearance_m, policy.personal_space_m)
                - NUMERICAL_TOLERANCE_M
                for previous in (*slots, *blocked)
            ):
                continue
            path = (start, candidate)
            swept = (
                ShapelyPoint(start).buffer(body_radius)
                if _distance(start, candidate) <= NUMERICAL_TOLERANCE_M
                else LineString(path).buffer(body_radius, cap_style="round")
            )
            if not raw_domain.buffer(NUMERICAL_TOLERANCE_M).covers(swept):
                continue
            slots.append(candidate)
            paths.append(path)
            if len(slots) >= required:
                break
    apron = (
        MultiPoint(slots).buffer(body_radius)
        if slots
        else GeometryCollection()
    )
    release = _storage_certificate(
        certificate_id=f"release:{binding.facade_key}",
        resource_kind="release_apron",
        owner_id=binding.facility_id,
        level_id=binding.exit_level_id,
        slots=slots,
        domain=apron,
        required_body_capacity=(
            required if facility.kind == FacilityKind.ELEVATOR.value else None
        ),
        group_size=int(scenario.group_size),
        minimum_clearance_m=policy.two_body_clearance_m,
        body_profile_fingerprint=body_profile_fingerprint,
        activation_group_id=binding.activation_group_id,
        activation_variant_id=binding.activation_variant_id,
        mutex_owner_ids=mutex_owner_ids,
        batch_plans=batch_plans,
        batch_swept_paths=batch_path_plans if facility.kind == FacilityKind.ELEVATOR.value else (),
    )
    corridor_domain = (
        unary_union(
            [
                (
                    ShapelyPoint(path[0]).buffer(body_radius)
                    if _distance(path[0], path[-1]) <= NUMERICAL_TOLERANCE_M
                    else LineString(path).buffer(body_radius, cap_style="round")
                )
                for path in paths
            ]
        )
        if paths
        else GeometryCollection()
    )
    corridor_capacity = max(
        (len(plan) for plan in batch_plans),
        default=len(paths),
    )
    corridor = SpatialCapacityCertificate(
        certificate_id=f"corridor:{binding.facade_key}",
        resource_kind="service_corridor",
        owner_id=binding.facility_id,
        level_id=binding.exit_level_id,
        slots=(),
        swept_paths=tuple(paths),
        # ``paths`` is the finite set of individually safe alternatives, not
        # a set of bodies that may occupy the corridor simultaneously.  The
        # batch proof is the constructive concurrency certificate.
        certified_body_capacity=corridor_capacity,
        certified_person_capacity=corridor_capacity
        * max(1, int(scenario.group_size)),
        required_body_capacity=(
            required if facility.kind == FacilityKind.ELEVATOR.value else None
        ),
        minimum_clearance_m=policy.two_body_clearance_m,
        density_bodies_per_m2=(
            0.0
            if corridor_domain.is_empty
            else corridor_capacity / float(corridor_domain.area)
        ),
        body_profile_fingerprint=body_profile_fingerprint,
        domain_fingerprint=_geometry_fingerprint(corridor_domain),
        activation_group_id=binding.activation_group_id,
        activation_variant_id=binding.activation_variant_id,
        mutex_owner_ids=mutex_owner_ids,
        batch_plans=batch_plans,
        batch_swept_paths=batch_path_plans if facility.kind == FacilityKind.ELEVATOR.value else (),
        domain=corridor_domain,
    )
    return release, corridor


def _elevator_release_envelope(
    facility: FacilitySpec,
    batch_path_plans: tuple[tuple[tuple[Point, ...], ...], ...],
    *,
    raw_domain: Any,
    safe_domain: Any,
    blocked_positions: tuple[Point, ...],
    spacing: float,
    policy: GeometryCompilePolicy,
) -> tuple[list[Point], list[tuple[Point, ...]]]:
    """Compile every safe path the runtime batch matcher may consume."""

    starts = tuple(
        dict.fromkeys(
            path[0]
            for plan in batch_path_plans
            for path in plan
        )
    )
    if not starts:
        return [], []
    forward = None
    for plan in batch_path_plans:
        for path in plan:
            if _distance(path[0], path[-1]) > NUMERICAL_TOLERANCE_M:
                dx = path[-1][0] - path[0][0]
                dy = path[-1][1] - path[0][1]
                length = hypot(dx, dy)
                forward = dx / length, dy / length
                break
        if forward is not None:
            break
    if forward is None:
        return list(starts), [(start, start) for start in starts]
    body_radius = max(0.02, policy.agent_radius_m)
    physical_clearance = policy.two_body_clearance_m
    endpoint_clearance = max(physical_clearance, policy.personal_space_m)
    blocked_index = _PointSpatialIndex.build(
        blocked_positions,
        cell_size=max(physical_clearance, endpoint_clearance),
    )
    safe_with_tolerance = safe_domain.buffer(NUMERICAL_TOLERANCE_M)
    raw_with_tolerance = raw_domain.buffer(NUMERICAL_TOLERANCE_M)
    steps = list(range(max(0, int(facility.release_forward_extra)) + 1))
    if len(steps) > 1:
        steps = [1, 0, *steps[2:]]
    endpoints: list[Point] = []
    paths: list[tuple[Point, ...]] = []
    seen: set[tuple[Point, Point]] = set()
    for start in starts:
        for step in steps:
            endpoint = (
                round(start[0] + forward[0] * spacing * step, 6),
                round(start[1] + forward[1] * spacing * step, 6),
            )
            path = (start, endpoint)
            if path in seen:
                continue
            seen.add(path)
            point = ShapelyPoint(endpoint)
            if not safe_with_tolerance.covers(point):
                continue
            line = (
                ShapelyPoint(start)
                if _distance(start, endpoint) <= NUMERICAL_TOLERANCE_M
                else LineString(path)
            )
            if not raw_with_tolerance.covers(
                line.buffer(body_radius, cap_style="round")
            ):
                continue
            if any(
                _point_segment_distance(blocked, start, endpoint)
                < physical_clearance - NUMERICAL_TOLERANCE_M
                or _distance(endpoint, blocked)
                < endpoint_clearance - NUMERICAL_TOLERANCE_M
                for blocked in blocked_index.near_segment(
                    start,
                    endpoint,
                    radius=endpoint_clearance,
                )
            ):
                continue
            endpoints.append(endpoint)
            paths.append(path)
    return list(dict.fromkeys(endpoints)), paths


def _compile_elevator_batch_plans(
    facility: FacilitySpec,
    binding: FacilityPortalBinding,
    *,
    raw_domain: Any,
    safe_domain: Any,
    blocked_positions: tuple[Point, ...],
    required_capacity: int,
    spacing: float,
    policy: GeometryCompilePolicy,
) -> tuple[
    tuple[tuple[Point, ...], ...],
    tuple[tuple[tuple[Point, ...], ...], ...],
]:
    """Construct and prove every FIFO cabin-release prefix from 1 through B."""

    point_plans: list[tuple[Point, ...]] = []
    path_plans: list[tuple[tuple[Point, ...], ...]] = []
    forward = binding.release_forward
    lateral = binding.release_lateral
    body_radius = max(0.02, policy.agent_radius_m)
    physical_clearance = policy.two_body_clearance_m
    endpoint_clearance = max(physical_clearance, policy.personal_space_m)
    blocked_index = _PointSpatialIndex.build(
        blocked_positions,
        cell_size=max(physical_clearance, endpoint_clearance),
    )
    safe_with_tolerance = safe_domain.buffer(NUMERICAL_TOLERANCE_M)
    raw_with_tolerance = raw_domain.buffer(NUMERICAL_TOLERANCE_M)
    forward_steps = list(range(max(0, int(facility.release_forward_extra)) + 1))
    if len(forward_steps) > 1:
        forward_steps = [1, 0, *forward_steps[2:]]

    for batch_size in range(1, max(1, int(required_capacity)) + 1):
        column_count = max(1, ceil(batch_size**0.5))
        row_count = max(1, ceil(batch_size / column_count))
        starts: list[Point] = []
        for index in range(batch_size):
            row = index // column_count
            column = index % column_count
            forward_offset = (row - (row_count - 1) / 2.0) * max(
                spacing,
                policy.personal_space_m,
            )
            lateral_offset = (column - (column_count - 1) / 2.0) * max(
                spacing,
                policy.personal_space_m,
            )
            start = (
                binding.exit_point[0]
                + forward[0] * forward_offset
                + lateral[0] * lateral_offset,
                binding.exit_point[1]
                + forward[1] * forward_offset
                + lateral[1] * lateral_offset,
            )
            starts.append((round(start[0], 6), round(start[1], 6)))
        if any(
            not safe_with_tolerance.covers(ShapelyPoint(start))
            for start in starts
        ) or _first_internal_clearance_conflict(tuple(starts), endpoint_clearance):
            break
        if any(
            _distance(start, blocked) + NUMERICAL_TOLERANCE_M < endpoint_clearance
            for start in starts
            for blocked in blocked_index.near_point(
                start,
                radius=endpoint_clearance,
            )
        ):
            break

        released: list[Point] = []
        paths: list[tuple[Point, ...]] = []
        valid = True
        for passenger_index, start in enumerate(starts):
            stationary = (
                *released,
                *starts[passenger_index + 1 :],
            )
            selected: Point | None = None
            selected_path: tuple[Point, ...] | None = None
            for forward_step in forward_steps:
                endpoint = (
                    round(start[0] + forward[0] * spacing * forward_step, 6),
                    round(start[1] + forward[1] * spacing * forward_step, 6),
                )
                if not safe_with_tolerance.covers(
                    ShapelyPoint(endpoint)
                ):
                    continue
                path = (start, endpoint)
                line = (
                    ShapelyPoint(start)
                    if _distance(start, endpoint) <= NUMERICAL_TOLERANCE_M
                    else LineString(path)
                )
                swept = line.buffer(body_radius, cap_style="round")
                if not raw_with_tolerance.covers(swept):
                    continue
                if any(
                    _point_segment_distance(point, start, endpoint)
                    < physical_clearance - NUMERICAL_TOLERANCE_M
                    for point in stationary
                ):
                    continue
                if any(
                    _point_segment_distance(point, start, endpoint)
                    < physical_clearance - NUMERICAL_TOLERANCE_M
                    or _distance(endpoint, point)
                    < endpoint_clearance - NUMERICAL_TOLERANCE_M
                    for point in blocked_index.near_segment(
                        start,
                        endpoint,
                        radius=endpoint_clearance,
                    )
                ):
                    continue
                selected = endpoint
                selected_path = path
                break
            if selected is None or selected_path is None:
                valid = False
                break
            released.append(selected)
            paths.append(selected_path)
        if not valid:
            break
        point_plans.append(tuple(released))
        path_plans.append(tuple(paths))
    return tuple(point_plans), tuple(path_plans)


def _required_release_bodies(
    facility: FacilitySpec,
    binding: FacilityPortalBinding,
    scenario: Any,
    spacing: float,
) -> int:
    if facility.kind == FacilityKind.ELEVATOR.value:
        elevator = None if facility.vertical_config is None else facility.vertical_config.elevator
        person_capacity = int(
            scenario.elevator_cabin_capacity_persons
            if elevator is None
            else elevator.batch_capacity
        )
        return max(1, person_capacity // max(1, int(scenario.group_size)))
    if facility.kind in {FacilityKind.ESCALATOR.value, FacilityKind.TRAIN_DOOR.value}:
        return 1
    if facility.kind == FacilityKind.STAIRS.value:
        width = max(spacing, float(facility.traversal_width_m or spacing))
        return max(1, floor(width / spacing))
    group_size = max(1, int(scenario.group_size))
    groups_per_second = max(0.0, float(facility.service_persons_per_min)) / group_size / 60.0
    groups_per_tick = groups_per_second * max(0.001, float(scenario.tick_seconds))
    distance = _distance(binding.entry_point, binding.exit_point)
    traversal_seconds = distance / max(0.001, float(scenario.jupedsim_desired_speed_mps))
    concurrent = max(1, ceil(groups_per_second * traversal_seconds))
    return max(concurrent, ceil(groups_per_tick))


def _release_candidate_grid(
    facility: FacilitySpec,
    binding: FacilityPortalBinding,
    spacing: float,
    required: int,
) -> tuple[Point, ...]:
    columns = max(1, int(facility.release_column_count))
    column_order = _centered_offsets(columns)
    # Search a deterministic finite prefix beyond the requested body count.
    # Obstacles and co-active resources may invalidate otherwise regular grid
    # cells; limiting the lattice to exactly ``required`` candidates would
    # confuse a constructive lower bound with an area estimate.
    rows = max(
        max(1, int(facility.release_forward_extra) + 1),
        ceil(max(1, required) / columns) + max(4, int(facility.release_forward_extra)),
    )
    forward = binding.release_forward
    lateral = binding.release_lateral
    base = binding.exit_point
    return tuple(
        (
            round(base[0] + forward[0] * row * spacing + lateral[0] * column * spacing, 6),
            round(base[1] + forward[1] * row * spacing + lateral[1] * column * spacing, 6),
        )
        for row in range(rows)
        for column in column_order
    )


def _platform_waiting_certificates(
    document: StationDesignDocument,
    graph: StationGraph,
    bindings: tuple[FacilityPortalBinding, ...],
    existing: Iterable[SpatialCapacityCertificate],
    *,
    scenario: Any,
    policy: GeometryCompilePolicy,
    body_profile_fingerprint: str,
) -> tuple[SpatialCapacityCertificate, ...]:
    level_ids = {
        node.level_id for node in graph.nodes_matching(kind="platform")
    } or {
        binding.entry_level_id
        for binding in bindings
        if binding.stage == FacilityStage.BOARDING_DOOR.value
    }
    by_level = _stationary_positions_by_level(existing)
    corridor_domains_by_level: dict[str, list[Any]] = {}
    for certificate in existing:
        if certificate.resource_kind == "service_corridor" and certificate.domain is not None:
            corridor_domains_by_level.setdefault(certificate.level_id, []).append(certificate.domain)
    boarding_approaches_by_level: dict[str, tuple[Point, ...]] = {}
    for level_id in level_ids:
        boarding_approaches_by_level[level_id] = tuple(
            point
            for binding in bindings
            if binding.stage == FacilityStage.BOARDING_DOOR.value
            and binding.entry_level_id == level_id
            for point in binding.approach_slots
        )

    result: list[SpatialCapacityCertificate] = []
    spacing = max(
        policy.personal_space_m,
        policy.two_body_clearance_m,
        policy.agent_radius_m * 2.05,
    ) + 0.001
    storage_clearance = spacing
    corridor_clearance = spacing
    for level_id in sorted(level_ids):
        domain = level_walkable_geometry(document, level_id).buffer(-policy.agent_radius_m * 1.05)
        blocked = by_level.get(level_id, ())
        if blocked:
            domain = domain.difference(MultiPoint(blocked).buffer(storage_clearance))
        storage_exclusions: list[Any] = []
        for certificate in existing:
            if certificate.level_id != level_id:
                continue
            if (
                certificate.resource_kind == "decision_holding"
                and certificate.domain is not None
            ):
                # Holding is an owned area, not just a set of independently
                # clear point centres. Allowing platform storage in the gaps
                # of its lattice recreates an immobile mixed-owner wall.
                storage_exclusions.append(certificate.domain)
            elif certificate.resource_kind == "queue" and certificate.slots:
                # Queue certificates use the whole walkable level as their
                # validation domain, so exclude a continuous tube around the
                # materialised FIFO instead of that (over-broad) domain.
                storage_exclusions.append(
                    MultiPoint(certificate.slots).buffer(storage_clearance)
                )
        if storage_exclusions:
            domain = domain.difference(unary_union(storage_exclusions))
        corridors = corridor_domains_by_level.get(level_id, ())
        if corridors:
            domain = domain.difference(unary_union(corridors).buffer(policy.target_radius_m))
        flow_corridors = _station_walk_flow_corridors(
            graph,
            level_id,
            clearance=corridor_clearance,
        )
        if not flow_corridors.is_empty:
            # Waiting cells are long-lived bodies.  Point-clear certificates
            # can still pack them across a strategic station route and create
            # a wall under sustained demand, so preserve the authored walk
            # graph as a continuous aisle before materialising storage.
            domain = domain.difference(flow_corridors)
        facility_ingress_corridors = _facility_ingress_corridors(
            bindings,
            graph,
            level_id,
            spacing,
        )
        if not facility_ingress_corridors.is_empty:
            # Queue point buffers protect only materialised standing cells.
            # Long-lived platform storage must also leave the full approach
            # sweep and multi-lane tail aisle body-free, otherwise the gaps
            # between valid waiting cells can still close the only FIFO
            # ingress under sustained mixed flow.
            domain = domain.difference(facility_ingress_corridors)
        gate_tail_aisles = _gate_bank_tail_aisles(
            bindings,
            level_id,
            domain,
            clearance=spacing,
        )
        if not gate_tail_aisles.is_empty:
            domain = domain.difference(gate_tail_aisles)
        boarding_access_corridors = _boarding_queue_access_corridors(
            graph,
            bindings,
            level_id,
            clearance=corridor_clearance,
        )
        if not boarding_access_corridors.is_empty:
            # The queue tail is the only legitimate hand-off from broad
            # platform storage into a finite boarding FIFO. Keep one
            # continuous upstream lane body-free; otherwise a valid set of
            # waiting cells can form a closed arc around the tail and make
            # every owned queue slot dynamically unreachable.
            domain = domain.difference(boarding_access_corridors)
        approaches = boarding_approaches_by_level.get(level_id, ())
        slots = tuple(
            sorted(
                grid_safe_points(domain, spacing=spacing, clearance=0.0),
                key=lambda point: (
                    min(
                        (_distance(point, approach) for approach in approaches),
                        default=0.0,
                    ),
                    point[1],
                    point[0],
                ),
            )
        )
        result.append(
            _storage_certificate(
                certificate_id=f"platform_waiting:{level_id}",
                resource_kind="platform_waiting",
                owner_id=f"platform_waiting:{level_id}",
                level_id=level_id,
                slots=slots,
                domain=domain,
                required_body_capacity=None,
                group_size=int(scenario.group_size),
                minimum_clearance_m=spacing,
                body_profile_fingerprint=body_profile_fingerprint,
            )
        )
    return tuple(result)


def _alighting_source_certificates(
    document: StationDesignDocument,
    facility_by_id: dict[str, FacilitySpec],
    bindings: tuple[FacilityPortalBinding, ...],
    *,
    blocked_certificates: tuple[SpatialCapacityCertificate, ...],
    scenario: Any,
    policy: GeometryCompilePolicy,
    body_profile_fingerprint: str,
) -> tuple[SpatialCapacityCertificate, ...]:
    """Compile the runtime door-local source lattice as a finite resource."""

    peak_batch = peak_alighting_batch(scenario)
    if peak_batch <= 0:
        return ()

    result: list[SpatialCapacityCertificate] = []
    for binding in bindings:
        if binding.stage != FacilityStage.BOARDING_DOOR.value:
            continue
        facility = facility_by_id.get(binding.facility_id)
        if facility is None:
            continue
        walkable = level_walkable_geometry(document, binding.exit_level_id)
        raw_candidates = materialize_alighting_source_candidates(
            facility.exit_position,
            facility.queue_layout.anchor,
            walkable,
            agent_radius_m=policy.agent_radius_m,
            peak_batch=peak_batch,
            lateral_offset_m=float(scenario.alighting_source_lateral_offset_m),
        )
        occupied = (*blocked_certificates, *result)
        selected_candidates: list[Point] = []
        for candidate in raw_candidates:
            if not _alighting_candidate_is_clear(
                candidate,
                binding.exit_level_id,
                occupied,
                source_clearance_m=policy.two_body_clearance_m,
            ):
                continue
            if _first_cross_clearance_conflict(
                tuple(selected_candidates),
                (candidate,),
                policy.two_body_clearance_m,
            ) is not None:
                continue
            selected_candidates.append(candidate)
        candidates = tuple(selected_candidates)
        proved_capacity = min(peak_batch, len(candidates))
        batch_plans = tuple(
            tuple(candidates[:size]) for size in range(1, proved_capacity + 1)
        )
        projection_clearance = alighting_source_projection_clearance_m(
            policy.agent_radius_m
        )
        source_id = binding.queue_id or binding.facade_key
        result.append(
            _storage_certificate(
                certificate_id=f"alighting_source:{source_id}",
                resource_kind="alighting_source",
                owner_id=f"alighting_source:{binding.facility_id}",
                level_id=binding.exit_level_id,
                slots=candidates,
                domain=walkable.buffer(-projection_clearance),
                required_body_capacity=peak_batch,
                group_size=int(scenario.group_size),
                minimum_clearance_m=policy.two_body_clearance_m,
                body_profile_fingerprint=body_profile_fingerprint,
                batch_plans=batch_plans,
            )
        )
    return tuple(result)


def _alighting_candidate_is_clear(
    candidate: Point,
    level_id: str,
    blocked_certificates: tuple[SpatialCapacityCertificate, ...],
    *,
    source_clearance_m: float,
) -> bool:
    """Keep the certified runtime source pool disjoint from co-active storage."""

    for certificate in blocked_certificates:
        if (
            certificate.level_id != level_id
            or certificate.resource_kind not in STORAGE_RESOURCE_KINDS
        ):
            continue
        minimum = max(source_clearance_m, certificate.minimum_clearance_m)
        if any(
            _distance(candidate, point) + NUMERICAL_TOLERANCE_M < minimum
            for point in certificate.slots
        ):
            return False
    return True


def _spawn_reservoir_certificates(
    document: StationDesignDocument,
    graph: StationGraph,
    existing: Iterable[SpatialCapacityCertificate],
    *,
    scenario: Any,
    policy: GeometryCompilePolicy,
    body_profile_fingerprint: str,
) -> tuple[SpatialCapacityCertificate, ...]:
    """Materialise finite ingress/alighting cells before runtime spawning."""

    blocked_by_level = _stationary_positions_by_level(existing)
    corridor_by_level: dict[str, list[Any]] = {}
    for certificate in existing:
        if certificate.resource_kind == "service_corridor" and certificate.domain is not None:
            corridor_by_level.setdefault(certificate.level_id, []).append(certificate.domain)
    reserved_by_level: dict[str, list[Point]] = {}
    spacing = max(policy.two_body_clearance_m, policy.personal_space_m) + 0.001
    safe_by_level: dict[str, Any] = {}
    blocked_exclusion_by_level: dict[str, Any] = {}
    corridor_exclusion_by_level: dict[str, Any] = {}
    result: list[SpatialCapacityCertificate] = []
    nodes = tuple(
        sorted(
            (
                *graph.nodes_matching(kind="entrance"),
                *graph.nodes_matching(kind="platform"),
            ),
            key=lambda node: (node.level_id, node.kind, node.node_id),
        )
    )
    for node in nodes:
        if node.level_id not in safe_by_level:
            safe_by_level[node.level_id] = level_walkable_geometry(
                document,
                node.level_id,
            ).buffer(-policy.agent_radius_m * 1.05)
            blocked = blocked_by_level.get(node.level_id, ())
            blocked_exclusion_by_level[node.level_id] = (
                MultiPoint(blocked).buffer(spacing)
                if blocked
                else GeometryCollection()
            )
            corridors = corridor_by_level.get(node.level_id, ())
            corridor_exclusion_by_level[node.level_id] = (
                unary_union(corridors).buffer(policy.agent_radius_m)
                if corridors
                else GeometryCollection()
            )
        safe = safe_by_level[node.level_id]
        domain = safe.intersection(ShapelyPoint(node.position).buffer(3.0))
        blocked_exclusion = blocked_exclusion_by_level[node.level_id]
        if not blocked_exclusion.is_empty:
            domain = domain.difference(blocked_exclusion)
        corridor_exclusion = corridor_exclusion_by_level[node.level_id]
        if not corridor_exclusion.is_empty:
            domain = domain.difference(corridor_exclusion)
        reserved = reserved_by_level.get(node.level_id, ())
        if reserved:
            domain = domain.difference(MultiPoint(tuple(reserved)).buffer(spacing))
        slots = grid_safe_points(domain, spacing=spacing, clearance=0.0)
        reserved_by_level.setdefault(node.level_id, []).extend(slots)
        result.append(
            _storage_certificate(
                certificate_id=f"spawn:{node.level_id}:{node.node_id}",
                resource_kind="spawn_reservoir",
                owner_id=node.node_id,
                level_id=node.level_id,
                slots=slots,
                domain=domain,
                required_body_capacity=None,
                group_size=int(scenario.group_size),
                minimum_clearance_m=spacing,
                body_profile_fingerprint=body_profile_fingerprint,
            )
        )
    return tuple(result)


def _certificate_geometry_issues(
    certificate: SpatialCapacityCertificate,
    path: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if (
        certificate.domain is not None
        and certificate.resource_kind in STORAGE_RESOURCE_KINDS
        and certificate.slots
    ):
        safe_domain = certificate.domain.buffer(NUMERICAL_TOLERANCE_M)
        mask = intersects_xy(
            safe_domain,
            [slot[0] for slot in certificate.slots],
            [slot[1] for slot in certificate.slots],
        )
        for slot, included in zip(certificate.slots, mask, strict=True):
            if included:
                continue
            issues.append(
                issue(
                    "error",
                    "capacity.slot_outside_certificate_domain",
                    path,
                    f"certified slot {slot!r} lies outside its resource domain",
                )
            )
            break
    conflict = next(
        (
            found
            for plan in (
                certificate.batch_plans
                if certificate.batch_plans
                else (certificate.slots,)
            )
            if (
                found := _first_internal_clearance_conflict(
                    tuple(plan),
                    certificate.minimum_clearance_m,
                )
            )
            is not None
        ),
        None,
    )
    if conflict is not None:
        issues.append(
            issue(
                "error",
                "capacity.internal_slot_conflict",
                path,
                "certificate slots violate their declared body clearance",
            )
        )
    return issues


def _coactive_certificate_issues(
    certificates: tuple[SpatialCapacityCertificate, ...],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    storage = tuple(
        item
        for item in certificates
        if item.resource_kind in STORAGE_RESOURCE_KINDS
        and item.resource_kind != "platform_waiting"
    )
    for index, left in enumerate(storage):
        for right in storage[index + 1 :]:
            if left.level_id != right.level_id or _certificates_are_mutually_exclusive(left, right):
                continue
            if left.owner_id == right.owner_id:
                continue
            minimum = max(left.minimum_clearance_m, right.minimum_clearance_m)
            conflict = _first_cross_clearance_conflict(
                left.slots,
                right.slots,
                minimum,
            )
            if conflict is None:
                continue
            issues.append(
                issue(
                    "error",
                    "capacity.coactive_slot_conflict",
                    f"spatial_capacity.{right.certificate_id}",
                    f"co-active resources {left.certificate_id!r} and "
                    f"{right.certificate_id!r} claim body-conflicting slots "
                    f"{conflict[0]!r} and {conflict[1]!r}",
                )
            )
    return issues


def _first_internal_clearance_conflict(
    points: tuple[Point, ...],
    minimum_clearance_m: float,
) -> tuple[Point, Point] | None:
    cell_size = max(NUMERICAL_TOLERANCE_M, float(minimum_clearance_m))
    buckets: dict[tuple[int, int], list[Point]] = {}
    for point in points:
        cell_x = floor(point[0] / cell_size)
        cell_y = floor(point[1] / cell_size)
        for x_offset in (-1, 0, 1):
            for y_offset in (-1, 0, 1):
                for previous in buckets.get((cell_x + x_offset, cell_y + y_offset), ()):
                    if (
                        _distance(point, previous) + NUMERICAL_TOLERANCE_M
                        < minimum_clearance_m
                    ):
                        return previous, point
        buckets.setdefault((cell_x, cell_y), []).append(point)
    return None


def _first_cross_clearance_conflict(
    left_points: tuple[Point, ...],
    right_points: tuple[Point, ...],
    minimum_clearance_m: float,
) -> tuple[Point, Point] | None:
    cell_size = max(NUMERICAL_TOLERANCE_M, float(minimum_clearance_m))
    buckets: dict[tuple[int, int], list[Point]] = {}
    for point in left_points:
        key = floor(point[0] / cell_size), floor(point[1] / cell_size)
        buckets.setdefault(key, []).append(point)
    for point in right_points:
        cell_x = floor(point[0] / cell_size)
        cell_y = floor(point[1] / cell_size)
        for x_offset in (-1, 0, 1):
            for y_offset in (-1, 0, 1):
                for previous in buckets.get((cell_x + x_offset, cell_y + y_offset), ()):
                    if (
                        _distance(point, previous) + NUMERICAL_TOLERANCE_M
                        < minimum_clearance_m
                    ):
                        return previous, point
    return None


def _certificates_are_mutually_exclusive(
    left: SpatialCapacityCertificate,
    right: SpatialCapacityCertificate,
) -> bool:
    return bool(
        left.activation_group_id is not None
        and left.activation_group_id == right.activation_group_id
        and left.activation_variant_id != right.activation_variant_id
    ) or right.owner_id in left.mutex_owner_ids or left.owner_id in right.mutex_owner_ids


def _stationary_positions_by_level(
    certificates: Iterable[SpatialCapacityCertificate],
) -> dict[str, tuple[Point, ...]]:
    grouped: dict[str, list[Point]] = {}
    for certificate in certificates:
        if certificate.resource_kind not in STORAGE_RESOURCE_KINDS:
            continue
        grouped.setdefault(certificate.level_id, []).extend(certificate.slots)
    return {key: tuple(value) for key, value in grouped.items()}


def _stationary_blockers_by_level(
    certificates: Iterable[SpatialCapacityCertificate],
) -> dict[str, tuple[tuple[str, Point], ...]]:
    grouped: dict[str, list[tuple[str, Point]]] = {}
    for certificate in certificates:
        if certificate.resource_kind not in STORAGE_RESOURCE_KINDS:
            continue
        grouped.setdefault(certificate.level_id, []).extend(
            (certificate.owner_id, point) for point in certificate.slots
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _binding_mutex_owner_ids(
    binding: FacilityPortalBinding,
    bindings: tuple[FacilityPortalBinding, ...],
) -> tuple[str, ...]:
    """Return explicit facility-level mutual exclusion contracts.

    Opposing gate facades of the same physical bank already share one runtime
    lane arbiter.  Their release apron may therefore reuse the opposing
    queue's handoff corridor, provided admission acquires the same mutex.  No
    such assumption is made for bidirectional stairs/elevators: both landing
    directions may be active concurrently.
    """

    if binding.kind not in {FacilityKind.GATE.value, FacilityKind.ELEVATOR.value}:
        return ()
    return tuple(
        sorted(
            {
                other.facility_id
                for other in bindings
                if other.facility_id != binding.facility_id
                and other.kind == binding.kind
                and other.source_element_id == binding.source_element_id
                and (
                    binding.kind == FacilityKind.ELEVATOR.value
                    or other.stage != binding.stage
                )
            }
        )
    )


def _release_spacing(facility: FacilitySpec, policy: GeometryCompilePolicy) -> float:
    clearance = policy.two_body_clearance_m + float(facility.release_clearance_pad)
    personal = policy.personal_space_m * float(facility.release_personal_factor)
    return max(
        float(facility.release_spacing_min),
        min(float(facility.release_spacing_max), max(clearance, personal)),
    )


def _fluid_peak_backlog(
    arrival_bodies: int,
    *,
    duration_seconds: float,
    service_bodies_per_second: float,
    tick_seconds: float,
) -> int:
    arrivals = max(0, int(arrival_bodies))
    if arrivals <= 0:
        return 0
    duration = max(1e-9, float(duration_seconds))
    arrival_rate = arrivals / duration
    first_tick_burst = ceil(arrival_rate * max(0.001, float(tick_seconds)))
    end_backlog = ceil(
        max(0.0, arrivals - max(0.0, service_bodies_per_second) * duration)
    )
    return max(1, first_tick_burst, end_backlog)


def _platform_peak_backlog(
    arrival_bodies: int,
    *,
    scenario: Any,
    group_size: int,
) -> int:
    arrivals = max(0, int(arrival_bodies))
    if arrivals <= 0:
        return 0
    demand_seconds = max(1.0, float(scenario.demand_duration_seconds))
    horizon_seconds = max(demand_seconds, float(scenario.horizon_duration_seconds))
    initial = max(0.0, float(scenario.initial_train_offset_seconds))
    headway = max(0.001, float(scenario.train_headway_seconds))
    dwell = max(0.0, float(scenario.train_dwell_seconds))
    train_body_capacity = max(1, int(scenario.train_capacity_persons) // group_size)
    dwell_service_capacity = floor(
        max(0.0, float(scenario.boarding_persons_per_min))
        / group_size
        * dwell
        / 60.0
    )
    departure_capacity = max(0, min(train_body_capacity, dwell_service_capacity))
    departure_times: list[float] = []
    arrival_time = initial
    while arrival_time <= horizon_seconds + NUMERICAL_TOLERANCE_M:
        departure_times.append(arrival_time + dwell)
        arrival_time += headway

    def cumulative_arrivals(time_seconds: float) -> int:
        ratio = max(0.0, min(1.0, time_seconds / demand_seconds))
        return min(arrivals, ceil(arrivals * ratio - NUMERICAL_TOLERANCE_M))

    backlog = 0
    observed_arrivals = 0
    peak = 0
    for departure_time in departure_times:
        due = cumulative_arrivals(min(departure_time, horizon_seconds))
        backlog += max(0, due - observed_arrivals)
        observed_arrivals = due
        peak = max(peak, backlog)
        backlog = max(0, backlog - departure_capacity)
        if departure_time >= horizon_seconds:
            break
    due = cumulative_arrivals(horizon_seconds)
    backlog += max(0, due - observed_arrivals)
    return max(peak, backlog)


def _centered_offsets(count: int) -> tuple[int, ...]:
    values = [0]
    offset = 1
    while len(values) < max(1, int(count)):
        values.append(-offset)
        if len(values) >= count:
            break
        values.append(offset)
        offset += 1
    return tuple(values)


def _body_profile_fingerprint(policy: GeometryCompilePolicy, scenario: Any) -> str:
    payload = {
        "version": CAPACITY_POLICY_VERSION,
        "agent_radius_m": policy.agent_radius_m,
        "clearance_m": policy.two_body_clearance_m,
        "personal_space_m": policy.personal_space_m,
        "group_size": max(1, int(scenario.group_size)),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _geometry_fingerprint(geometry: Any) -> str:
    if geometry is None:
        return hashlib.sha256(b"none").hexdigest()
    return hashlib.sha256(bytes(geometry.wkb)).hexdigest()


def _dedupe_issues(issues: Iterable[ValidationIssue]) -> list[ValidationIssue]:
    result: list[ValidationIssue] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in issues:
        key = (item.severity, item.code, item.path, item.message)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


__all__ = [
    "CAPACITY_POLICY_VERSION",
    "SpatialCapacityCertificate",
    "SpatialDemandContract",
    "compile_spatial_capacity_certificates",
    "compile_spatial_demand_contracts",
    "validate_spatial_capacity_certificates",
    "validate_spatial_demand_contracts",
]
