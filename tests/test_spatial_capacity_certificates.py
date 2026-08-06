from __future__ import annotations

from dataclasses import replace
from math import hypot
from types import SimpleNamespace

import pytest
from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.compilation.geometry_reachability import (
    GeometryCompilePolicy,
)
from metro_station.adapters.simulation.compilation.release_capacity_geometry import (
    release_spacing,
    required_release_bodies,
)
from metro_station.adapters.simulation.compilation.spatial_capacity import (
    CAPACITY_POLICY_VERSION,
    SpatialCapacityCertificate,
    validate_spatial_capacity_certificates,
)
from metro_station.adapters.simulation.compilation.validation import (
    validate_compiled_station_design,
)
from metro_station.adapters.simulation.design.templates import (
    create_design,
    topology_templates,
)
from metro_station.adapters.simulation.movement.contracts import MovementResult
from metro_station.adapters.simulation.movement.movement_backend_contract import MovementBackend
from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.spatial_capacity_admission import (
    CertifiedPlacementTemporarilyBlocked,
    SpatialCapacityExhausted,
)
from metro_station.adapters.simulation.station.alighting_source_geometry import (
    alighting_source_raw_candidate,
)
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.geometry import grid_safe_points
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from shapely.geometry import LineString, MultiPoint, Point, box


def test_formal_templates_compile_every_finite_spatial_resource() -> None:
    required_kinds = {
        "queue",
        "decision_holding",
        "platform_waiting",
        "release_apron",
        "service_corridor",
        "spawn_reservoir",
    }
    for template in topology_templates():
        document = create_design(template.id)
        compiled = validate_compiled_station_design(document, _scenario(document))

        assert not [item for item in compiled.issues if item.severity == "error"]
        certificates = compiled.spatial_capacity_certificates
        assert required_kinds <= {item.resource_kind for item in certificates}
        assert all(item.certified_body_capacity > 0 for item in certificates)
        assert all(
            item.certified_person_capacity
            == item.certified_body_capacity * _scenario(document).group_size
            for item in certificates
        )
        assert all(item.policy_version == CAPACITY_POLICY_VERSION for item in certificates)
        assert all(len(item.body_profile_fingerprint) == 64 for item in certificates)
        assert all(len(item.domain_fingerprint) == 64 for item in certificates)


def test_runtime_platform_waiting_positions_are_compiler_certificate_slots() -> None:
    document = create_design("two_level_island_platform")
    layout = DesignCompiler.compile(document, _scenario(document))
    certificates = tuple(
        item
        for item in layout.spatial_capacity_certificates
        if item.resource_kind == "platform_waiting"
    )

    assert certificates
    assert layout.platform_waiting_slots() == tuple(
        point
        for certificate in sorted(certificates, key=lambda item: item.certificate_id)
        for point in certificate.slots
    )


def test_platform_waiting_excludes_queue_and_holding_storage_domains() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    waiting = tuple(
        item
        for item in layout.spatial_capacity_certificates
        if item.resource_kind == "platform_waiting"
    )
    queues = tuple(
        item
        for item in layout.spatial_capacity_certificates
        if item.resource_kind == "queue"
    )
    holdings = tuple(
        item
        for item in layout.spatial_capacity_certificates
        if item.resource_kind == "decision_holding"
    )
    body_clearance = max(
        scenario.jupedsim_agent_radius_units
        * scenario.jupedsim_clearance_multiplier,
        scenario.jupedsim_agent_radius_units * 2.05,
    )

    assert waiting
    for certificate in waiting:
        same_level_queues = tuple(
            queue for queue in queues if queue.level_id == certificate.level_id
        )
        same_level_holdings = tuple(
            holding for holding in holdings if holding.level_id == certificate.level_id
        )
        assert all(
            all(
                (point[0] - queue_point[0]) ** 2
                + (point[1] - queue_point[1]) ** 2
                >= body_clearance**2 - 1e-9
                for queue in same_level_queues
                for queue_point in queue.slots
            )
            and all(
                holding.domain is None
                or not holding.domain.covers(MultiPoint((point,)).geoms[0])
                for holding in same_level_holdings
            )
            for point in certificate.slots
        )


def test_platform_waiting_excludes_train_door_boarding_crossings() -> None:
    document = create_design("visual_demo_station")
    scenario = _scenario(document)
    model = MetroStationModel(scenario, seed=17)
    platform = model.platforms[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    passenger.current_level_id = model.boarding_doors[0].portal_entry_level_id
    model.passengers.append(passenger)
    slot = model._reserve_platform_waiting_slot(passenger, platform)
    required_clearance = max(
        scenario.jupedsim_agent_radius_units
        * scenario.jupedsim_clearance_multiplier,
        scenario.personal_space_units * 0.75,
    )

    for binding in model.layout_graph.facility_portal_bindings:
        if binding.stage != "boarding_door" or not binding.approach_slots:
            continue
        crossing = LineString((binding.approach_slots[0], binding.entry_point))
        assert crossing.distance(Point(slot)) >= required_clearance - 1e-9


def test_overlapping_holding_regions_consume_one_shared_level_ledger() -> None:
    document = create_design("two_level_island_platform")
    compiled = validate_compiled_station_design(document, _scenario(document))
    holdings = tuple(
        item
        for item in compiled.spatial_capacity_certificates
        if item.resource_kind == "decision_holding"
    )

    for index, left in enumerate(holdings):
        for right in holdings[index + 1 :]:
            if left.level_id != right.level_id:
                continue
            assert all(
                (left_point[0] - right_point[0]) ** 2
                + (left_point[1] - right_point[1]) ** 2
                >= max(left.minimum_clearance_m, right.minimum_clearance_m) ** 2
                - 1e-9
                for left_point in left.slots
                for right_point in right.slots
            )


def test_body_profile_change_invalidates_certificate_fingerprint() -> None:
    document = create_design("single_level_terminal")
    base = _scenario(document)
    larger_body = replace(base, jupedsim_agent_radius_units=0.24)

    base_certificates = validate_compiled_station_design(
        document,
        base,
    ).spatial_capacity_certificates
    changed_certificates = validate_compiled_station_design(
        document,
        larger_body,
    ).spatial_capacity_certificates

    assert {item.body_profile_fingerprint for item in base_certificates}
    assert {item.body_profile_fingerprint for item in base_certificates}.isdisjoint(
        {item.body_profile_fingerprint for item in changed_certificates}
    )


def test_constructed_capacity_below_demand_is_a_compile_error() -> None:
    certificate = _certificate(
        certificate_id="holding:test",
        owner_id="holding:test",
        slots=((1.0, 1.0),),
        required=2,
    )

    assert "holding.capacity_below_required" in {
        item.code for item in validate_spatial_capacity_certificates((certificate,))
    }


def test_coactive_overlap_requires_an_explicit_mutex_contract() -> None:
    left = _certificate(
        certificate_id="queue:left",
        owner_id="left",
        slots=((1.0, 1.0),),
    )
    right = _certificate(
        certificate_id="queue:right",
        owner_id="right",
        slots=((1.0, 1.0),),
    )
    assert "capacity.coactive_slot_conflict" in {
        item.code for item in validate_spatial_capacity_certificates((left, right))
    }

    locked = replace(left, mutex_owner_ids=("right",))
    assert "capacity.coactive_slot_conflict" not in {
        item.code for item in validate_spatial_capacity_certificates((locked, right))
    }


def test_alighting_source_pool_excludes_coactive_queue_slots_before_model_start() -> None:
    document = create_design("visual_demo_station")
    compiled = validate_compiled_station_design(
        document,
        replace(_scenario(document), minutes=5, demand_minutes=5, exit_count_hour=12),
    )

    sources = tuple(
        item
        for item in compiled.spatial_capacity_certificates
        if item.resource_kind == "alighting_source"
    )
    assert sources
    assert all(item.required_body_capacity == 1 for item in sources)
    assert "capacity.coactive_slot_conflict" not in {
        item.code for item in compiled.issues if item.severity == "error"
    }
    queues = tuple(
        item
        for item in compiled.spatial_capacity_certificates
        if item.resource_kind in {"queue", "decision_holding"}
    )
    assert all(
        (source_point[0] - queue_point[0]) ** 2
        + (source_point[1] - queue_point[1]) ** 2
        >= max(source.minimum_clearance_m, queue.minimum_clearance_m) ** 2 - 1e-9
        for source in sources
        for queue in queues
        if source.level_id == queue.level_id
        for source_point in source.slots
        for queue_point in queue.slots
    )


def test_alighting_source_lateral_offset_moves_the_complete_door_local_lattice() -> None:
    base = (0.0, 0.0)
    queue_anchor = (0.0, -1.0)

    centered = alighting_source_raw_candidate(
        base,
        queue_anchor,
        0,
        agent_radius_m=0.18,
    )
    shifted = alighting_source_raw_candidate(
        base,
        queue_anchor,
        0,
        agent_radius_m=0.18,
        lateral_offset_m=10.0,
    )

    assert centered == pytest.approx((-0.6, -0.35))
    assert shifted == pytest.approx((9.4, -0.35))


def test_grid_safe_points_preserve_declared_sub_metre_spacing() -> None:
    spacing = 0.801
    points = grid_safe_points(box(0.0, 0.0, 4.0, 4.0), spacing=spacing, clearance=0.0)

    assert points
    assert all(
        (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2
        >= spacing**2 - 1e-9
        for index, left in enumerate(points)
        for right in points[index + 1 :]
    )


def test_elevator_certificate_proves_every_batch_prefix() -> None:
    document = create_design("visual_demo_station")
    compiled = validate_compiled_station_design(document, _scenario(document))
    elevator_releases = tuple(
        item
        for item in compiled.spatial_capacity_certificates
        if item.resource_kind == "release_apron"
        and item.owner_id.startswith("vertical:elevator")
    )

    assert elevator_releases
    for certificate in elevator_releases:
        assert certificate.required_body_capacity == 12
        assert tuple(len(plan) for plan in certificate.batch_plans) == tuple(
            range(1, 13)
        )
        assert set(certificate.batch_plans[-1]) <= set(certificate.slots)


def test_elevator_person_capacity_is_not_confused_with_body_capacity() -> None:
    document = create_design("visual_demo_station")
    scenario = replace(
        _scenario(document),
        group_size=3,
        elevator_cabin_capacity_persons=12,
    )
    compiled = validate_compiled_station_design(document, scenario)
    elevator_releases = tuple(
        item
        for item in compiled.spatial_capacity_certificates
        if item.resource_kind == "release_apron"
        and item.owner_id.startswith("vertical:elevator")
    )

    assert elevator_releases
    assert all(item.required_body_capacity == 4 for item in elevator_releases)
    assert all(item.certified_person_capacity == 12 for item in elevator_releases)


def test_unplaceable_elevator_batch_fails_before_runtime() -> None:
    document = create_design("visual_demo_station")
    compiled = validate_compiled_station_design(
        document,
        replace(_scenario(document), elevator_cabin_capacity_persons=60),
    )

    assert "release.batch_not_placeable" in {
        item.code for item in compiled.issues if item.severity == "error"
    }


def test_scenario_demand_exceeding_certified_storage_fails_compilation() -> None:
    document = create_design("visual_demo_station")
    compiled = validate_compiled_station_design(
        document,
        replace(_scenario(document), entry_count_hour=100_000),
    )

    assert "capacity.demand_exceeds_storage" in {
        item.code for item in compiled.issues if item.severity == "error"
    }
    assert any(
        contract.required_body_capacity > contract.certified_body_capacity
        for contract in compiled.spatial_demand_contracts
    )


def test_gate_release_cells_are_exclusive_with_decision_holding() -> None:
    document = create_design("visual_demo_station")
    model = MetroStationModel(_scenario(document))

    certificates = tuple(gate._release_capacity_certificate() for gate in model.gates)
    holding_slots = tuple(
        point
        for region in model.layout_graph.decision_holding_regions
        for point in region.slots
    )

    assert certificates
    assert all(certificate is not None for certificate in certificates)
    policy = GeometryCompilePolicy.from_scenario(model.scenario)
    assert all(
        certificate.certified_body_capacity
        >= required_release_bodies(
            gate.spec,
            gate.portal_binding,
            model.scenario,
            release_spacing(gate.spec, policy),
        )
        + max(2, int(gate.spec.release_column_count))
        for gate, certificate in zip(model.gates, certificates, strict=True)
    )
    assert all(
        hypot(release[0] - holding[0], release[1] - holding[1])
        >= model.scenario.personal_space_units - 1e-6
        for certificate in certificates
        for release in certificate.slots
        for holding in holding_slots
    )


def test_n_plus_one_release_is_rejected_before_backend_placement() -> None:
    document = create_design("visual_demo_station")
    backend = _ExactPlacementBackend()
    model = MetroStationModel(_scenario(document), movement_backend=backend)
    gate = model.gates[0]
    certificate = gate._release_capacity_certificate()
    assert certificate is not None
    passengers = [
        model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        for _ in range(certificate.certified_body_capacity + 1)
    ]
    backend.resolve_calls = 0

    reservations = [
        gate._reserve_certified_release_slot(
            passenger,
            preferred_index=index,
            persistent=True,
        )
        for index, passenger in enumerate(passengers[:-1])
    ]
    calls_after_capacity = backend.resolve_calls
    with pytest.raises(SpatialCapacityExhausted):
        gate._reserve_certified_release_slot(
            passengers[-1],
            preferred_index=0,
            persistent=True,
        )

    assert backend.resolve_calls == calls_after_capacity
    gate._release_certified_slot(passengers[0], reservations[0][1])
    gate._reserve_certified_release_slot(
        passengers[-1],
        preferred_index=0,
        persistent=True,
    )


def test_dynamic_release_blocker_defers_and_is_counted() -> None:
    document = create_design("visual_demo_station")
    model = MetroStationModel(
        _scenario(document),
        movement_backend=_ExactPlacementBackend(),
    )
    gate = model.gates[0]
    owner = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
    certificate = gate._release_capacity_certificate()
    assert certificate is not None
    blockers = [
        model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        for _ in certificate.slots
    ]
    for blocker, slot in zip(blockers, certificate.slots, strict=True):
        blocker.current_level_id = certificate.level_id
        blocker.pos = slot

    with pytest.raises(CertifiedPlacementTemporarilyBlocked):
        gate._reserve_certified_release_slot(
            owner,
            preferred_index=0,
            persistent=True,
        )

    assert model.spatial_capacity_event_counts["placement.dynamic_blocked"] == 1


def test_explicit_source_position_is_rejected_before_publication() -> None:
    document = create_design("visual_demo_station")
    backend = _BlockingExactPlacementBackend()
    model = MetroStationModel(_scenario(document), movement_backend=backend)
    platform = model.layout_graph.station_graph.nodes_matching(kind="platform")[0]

    with pytest.raises(CertifiedPlacementTemporarilyBlocked):
        model._spawn_passenger(
            AgentIntent.EXIT_STATION,
            initial_position=tuple(platform.position),
            initial_level_id=platform.level_id,
        )

    assert backend.resolve_calls == 1
    assert model.passengers == []
    assert model.spawned_persons == 0
    assert model.spatial_capacity_event_counts["spawn.dynamic_blocked"] == 1


def test_platform_waiting_has_no_coordinate_overflow_fallback() -> None:
    document = create_design("visual_demo_station")
    layout = DesignCompiler.compile(document, _scenario(document))
    with pytest.raises(SpatialCapacityExhausted):
        layout.platform_waiting_position(len(layout.platform_waiting_slots()))


def test_full_spawn_reservoir_defers_demand_before_creating_passenger() -> None:
    document = create_design("single_level_terminal")
    model = MetroStationModel(
        _scenario(document),
        movement_backend=_ExactPlacementBackend(),
    )
    certificate = next(
        item
        for item in model.layout_graph.spatial_capacity_certificates
        if item.resource_kind == "spawn_reservoir"
        and item.owner_id.startswith("entrance:")
    )
    model.passengers = [
        SimpleNamespace(current_level_id=certificate.level_id, pos=slot)
        for slot in certificate.slots
    ]
    model.pending_spawn_groups[AgentIntent.ENTER_AND_BOARD.value] = 1

    model.spawn_passengers()

    assert model.pending_spawn_groups[AgentIntent.ENTER_AND_BOARD.value] == 1
    assert model.spatial_capacity_event_counts["capacity.admission_exhausted"] == 1


def _certificate(
    *,
    certificate_id: str,
    owner_id: str,
    slots: tuple[tuple[float, float], ...],
    required: int | None = None,
) -> SpatialCapacityCertificate:
    domain = MultiPoint(slots).buffer(1.0) if slots else box(0.0, 0.0, 1.0, 1.0)
    return SpatialCapacityCertificate(
        certificate_id=certificate_id,
        resource_kind=(
            "decision_holding" if certificate_id.startswith("holding:") else "queue"
        ),
        owner_id=owner_id,
        level_id="l1",
        slots=slots,
        swept_paths=(),
        certified_body_capacity=len(slots),
        certified_person_capacity=len(slots),
        required_body_capacity=required,
        minimum_clearance_m=0.4,
        density_bodies_per_m2=len(slots) / max(domain.area, 1e-9),
        body_profile_fingerprint="a" * 64,
        domain_fingerprint="b" * 64,
        domain=domain,
    )


def _scenario(document) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name=f"capacity_{document.id}",
        hour=18,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="spatial_capacity_test",
        sample_hours=1,
        station_design=document,
        audit_enabled=False,
        audit_print_events=False,
    )


class _ExactPlacementBackend(MovementBackend):
    def __init__(self) -> None:
        self.resolve_calls = 0

    def move(self, passenger) -> MovementResult:
        return MovementResult(
            passenger_id=int(passenger.unique_id),
            position=tuple(passenger.pos),
            reached=False,
        )

    def resolve_placement(self, passenger, position, *, level_id=None):
        del passenger, level_id
        self.resolve_calls += 1
        return tuple(position)


class _BlockingExactPlacementBackend(_ExactPlacementBackend):
    def resolve_placement(self, passenger, position, *, level_id=None):
        del passenger, position, level_id
        self.resolve_calls += 1
        raise RuntimeError("native placement blocked")
