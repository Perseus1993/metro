"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from math import hypot
from typing import TYPE_CHECKING

from shapely.geometry import LineString, MultiPoint, Point as ShapelyPoint
from shapely.ops import unary_union

from metro_station.adapters.simulation.compilation.spatial_capacity import (
    SpatialCapacityCertificate,
)
from metro_station.adapters.simulation.facilities.process import FacilityKind, FacilitySpec, QueueLayout
from metro_station.adapters.simulation.facilities.vertical import StairsConfig, VerticalFacilityConfig
from metro_station.adapters.simulation.planning.plan import AgentState, FacilityStage
from metro_station.adapters.simulation.runtime.simulation_clock import PHYSICAL_CLOCK
from metro_station.adapters.simulation.station.facility_portal_binding import (
    FacilityPortalBinding,
    QueueSlotBinding,
)

if TYPE_CHECKING:
    from .goal_journey_micro_scene import GoalJourneyMicroScene


CONCOURSE_LEVEL = "concourse"
PLATFORM_LEVEL = "platform"
PLATFORM_ID = "platform:journey:down"


@dataclass(frozen=True)
class GoalJourneyMicroScenario:
    tick_seconds: float = 0.25
    group_size: int = 1
    walk_units_per_tick: float = 0.3
    movement_trace_sample_seconds: float = 0.2
    jupedsim_desired_speed_mps: float = 1.2
    cornering_acceleration_limit_m_s2: float = 3.2
    cornering_acceleration_window_s: float = 0.4
    initial_train_offset_seconds: float = 45.0
    train_dwell_seconds: float = 25.0
    train_headway_seconds: float = 75.0
    train_capacity_persons: int = 100
    platform_capacity_persons: int = 200
    jupedsim_dt_seconds: float = 0.01
    jupedsim_iterations_per_tick: int = 25
    jupedsim_agent_radius_units: float = 0.22
    jupedsim_target_radius_units: float = 0.38
    jupedsim_clearance_multiplier: float = 2.0
    jupedsim_neighbor_radius_units: float = 2.5
    jupedsim_neighbor_sample_limit: int = 12
    jupedsim_operational_model: str = "collision_free_speed"
    jupedsim_strict: bool = True
    simulation_clock_mode: str = PHYSICAL_CLOCK
    personal_space_units: float = 0.8


def make_gate(model: GoalJourneyMicroScene, short_id: str, y: float):
    from .goal_gate_micro_scene import ControllableGateProcessAgent

    spec = FacilitySpec(
        facility_id=short_id,
        stage=FacilityStage.ENTRY_GATE.value,
        label=short_id,
        kind=FacilityKind.GATE.value,
        direction="entry",
        position=(17.0, y),
        queue_layout=_single_lane_queue(16.0, y),
        exit_position=(19.0, y),
        service_persons_per_min=120,
        queue_state=AgentState.QUEUEING_GATE.value,
        service_state=AgentState.PASSING_GATE.value,
        release_route=(),
        entry_level_id=CONCOURSE_LEVEL,
        exit_level_id=CONCOURSE_LEVEL,
    )
    return ControllableGateProcessAgent(model, spec=spec)


def make_stairs(model: GoalJourneyMicroScene, short_id: str, y: float):
    from .goal_stairs_micro_scene import ControllableStairsProcessAgent

    spec = FacilitySpec(
        facility_id=short_id,
        stage=FacilityStage.VERTICAL_TRANSFER.value,
        label=short_id,
        kind=FacilityKind.STAIRS.value,
        direction="down",
        position=(36.0, y),
        queue_layout=_single_lane_queue(35.0, y),
        exit_position=(41.0, y),
        service_persons_per_min=240,
        queue_state=AgentState.QUEUEING_VERTICAL.value,
        service_state=AgentState.RIDING_VERTICAL.value,
        release_route=(),
        speed_units_per_tick=0.72,
        entry_level_id=CONCOURSE_LEVEL,
        exit_level_id=PLATFORM_LEVEL,
        traversal_width_m=1.5,
        vertical_config=VerticalFacilityConfig(
            stairs=StairsConfig(
                base_capacity_ppm=240,
                fatigue_cost_up=0.6,
                fatigue_cost_down=0.18,
                bidirectional_conflict_factor=0.0,
            )
        ),
    )
    return ControllableStairsProcessAgent(model, spec=spec)


def make_door(model: GoalJourneyMicroScene, short_id: str, y: float):
    from .goal_boarding_micro_scene import ControllableBoardingDoorProcessAgent

    spec = FacilitySpec(
        facility_id=short_id,
        stage=FacilityStage.BOARDING_DOOR.value,
        label=short_id,
        kind=FacilityKind.TRAIN_DOOR.value,
        direction="down",
        position=(60.0, y),
        queue_layout=_single_lane_queue(57.0, y),
        exit_position=(60.0, y),
        service_persons_per_min=240,
        queue_state=AgentState.QUEUEING_DOOR.value,
        service_state=AgentState.BOARDING_TRAIN.value,
        release_route=(),
        train_gated=True,
        train_capacity_limited=True,
        line_id="journey_line",
        platform_id=PLATFORM_ID,
        entry_level_id=PLATFORM_LEVEL,
        exit_level_id=PLATFORM_LEVEL,
    )
    return ControllableBoardingDoorProcessAgent(model, spec=spec)


def _single_lane_queue(x: float, y: float) -> QueueLayout:
    return QueueLayout(
        anchor=(x, y),
        per_row=1,
        col_step=(0.0, 0.0),
        row_step=(-0.65, 0.0),
        slots=tuple((x - index * 0.65, y) for index in range(12)),
    )


def compile_micro_facility_portal_binding(spec: FacilitySpec) -> FacilityPortalBinding:
    """Build the explicit immutable facade contract for the synthetic micro scene."""

    dx = float(spec.exit_position[0]) - float(spec.position[0])
    dy = float(spec.exit_position[1]) - float(spec.position[1])
    length = hypot(dx, dy)
    forward = (1.0, 0.0) if length <= 1e-9 else (dx / length, dy / length)
    slots = tuple(
        (float(point[0]), float(point[1])) for point in spec.queue_layout.slots
    )
    slot_bindings = tuple(
        QueueSlotBinding(
            slot_id=f"micro:{spec.facility_id}:slot:{index}",
            position=point,
            lane_id=f"micro:{spec.facility_id}:lane:0",
            row_index=index,
            position_in_row=0,
            service_rank=index,
            runtime_slot_index=index,
            role="approach",
        )
        for index, point in enumerate(slots)
    )
    indices = tuple(range(len(slots)))
    return FacilityPortalBinding(
        facility_id=spec.facility_id,
        facade_key=f"micro:{spec.facility_id}:{spec.direction}",
        source_element_id=spec.source_element_id or f"micro:{spec.facility_id}",
        stage=spec.stage,
        kind=spec.kind,
        direction=spec.direction,
        raw_entry_point=spec.position,
        entry_point=spec.position,
        entry_level_id=str(spec.entry_level_id),
        raw_exit_point=spec.exit_position,
        exit_point=spec.exit_position,
        exit_level_id=str(spec.exit_level_id),
        release_forward=forward,
        release_lateral=(-forward[1], forward[0]),
        approach_point=slots[-1] if slots else spec.queue_anchor,
        queue_slots=slots,
        queue_slot_bindings=slot_bindings,
        approach_slots=slots,
        approach_source_slot_indices=indices,
        approach_slot_indices=indices,
        queue_id=f"micro:{spec.facility_id}:queue",
        source_queue_capacity=len(slots),
        declared_queue_capacity=len(slots),
        queue_spacing_m=0.65,
        projection_distance_m=0.0,
        policy_fingerprint="goal-journey-micro-v1",
        activation_group_id=None,
        activation_variant_id=None,
        queue_topology_version=1,
        topology_fingerprint=f"goal-journey-micro:{spec.facility_id}:v1",
        fallback_used=False,
    )


def install_micro_spatial_capacity_contract(
    layout_graph,
    specs,
    bindings,
    scenario,
) -> tuple[SpatialCapacityCertificate, ...]:
    """Attach finite release proofs to a synthetic component micro-scene.

    These probes intentionally do not own a StationDesignDocument, so they
    cannot call DesignCompiler.  They still fail closed against the same
    runtime certificate API and materialise body-clear deterministic cells in
    their authored rectangular test domain.
    """

    spec_by_id = {spec.facility_id: spec for spec in specs}
    group_size = max(1, int(scenario.group_size))
    body_radius = max(0.02, float(scenario.jupedsim_agent_radius_units))
    clearance = max(
        body_radius * float(scenario.jupedsim_clearance_multiplier),
        float(scenario.personal_space_units),
    )
    certificates: list[SpatialCapacityCertificate] = []
    for binding in bindings:
        spec = spec_by_id[binding.facility_id]
        forward = binding.release_forward
        lateral = binding.release_lateral
        # Four alternatives cover the maximum concurrent service exercised by
        # these component probes while preserving an explicit finite N/N+1
        # boundary in the shared runtime admission code.
        slots = tuple(
            (
                round(binding.exit_point[0] + forward[0] * clearance * (index + 1), 6),
                round(binding.exit_point[1] + forward[1] * clearance * (index + 1), 6),
            )
            for index in range(4)
        )
        paths = tuple((tuple(binding.exit_point), slot) for slot in slots)
        release_domain = MultiPoint(slots).buffer(body_radius * 1.05)
        corridor_domain = unary_union(
            [
                (
                    ShapelyPoint(path[0]).buffer(body_radius)
                    if path[0] == path[-1]
                    else LineString(path).buffer(body_radius, cap_style="round")
                )
                for path in paths
            ]
        )
        fingerprint_seed = f"micro-capacity:{spec.facility_id}:{binding.facade_key}"
        body_fingerprint = hashlib.sha256(
            f"{fingerprint_seed}:{body_radius}:{clearance}".encode("utf-8")
        ).hexdigest()
        domain_fingerprint = hashlib.sha256(
            f"{fingerprint_seed}:{release_domain.wkb_hex}".encode("utf-8")
        ).hexdigest()
        certificates.extend(
            (
                SpatialCapacityCertificate(
                    certificate_id=f"micro:release:{binding.facade_key}",
                    resource_kind="release_apron",
                    owner_id=spec.facility_id,
                    level_id=binding.exit_level_id,
                    slots=slots,
                    swept_paths=(),
                    certified_body_capacity=len(slots),
                    certified_person_capacity=len(slots) * group_size,
                    required_body_capacity=None,
                    minimum_clearance_m=clearance,
                    density_bodies_per_m2=len(slots) / max(release_domain.area, 1e-9),
                    body_profile_fingerprint=body_fingerprint,
                    domain_fingerprint=domain_fingerprint,
                    domain=release_domain,
                ),
                SpatialCapacityCertificate(
                    certificate_id=f"micro:corridor:{binding.facade_key}",
                    resource_kind="service_corridor",
                    owner_id=spec.facility_id,
                    level_id=binding.exit_level_id,
                    slots=(),
                    swept_paths=paths,
                    certified_body_capacity=len(paths),
                    certified_person_capacity=len(paths) * group_size,
                    required_body_capacity=None,
                    minimum_clearance_m=clearance,
                    density_bodies_per_m2=len(paths) / max(corridor_domain.area, 1e-9),
                    body_profile_fingerprint=body_fingerprint,
                    domain_fingerprint=hashlib.sha256(
                        f"{fingerprint_seed}:{corridor_domain.wkb_hex}".encode("utf-8")
                    ).hexdigest(),
                    domain=corridor_domain,
                ),
            )
        )
    compiled = tuple(certificates)
    layout_graph.spatial_capacity_certificates = compiled

    def lookup(
        resource_kind: str,
        owner_id: str,
        *,
        level_id: str | None = None,
        activation_variant_id: str | None = None,
    ) -> SpatialCapacityCertificate:
        candidates = tuple(
            item
            for item in compiled
            if item.resource_kind == resource_kind
            and item.owner_id == owner_id
            and (level_id is None or item.level_id == level_id)
            and activation_variant_id is None
        )
        if len(candidates) != 1:
            raise KeyError(
                f"expected one micro {resource_kind!r} certificate for "
                f"{owner_id!r}; found {len(candidates)}"
            )
        return candidates[0]

    layout_graph.spatial_capacity_certificate = lookup
    return compiled
