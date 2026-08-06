from __future__ import annotations

from collections import Counter
from dataclasses import replace
from random import Random
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.compilation.validation import (
    validate_compiled_station_design,
)
from metro_station.adapters.simulation.facilities.admission_resource import (
    AdmissionTokenResource,
)
from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.runtime.external_demand_reservoir import (
    DemandSourceKind,
    ExternalDemandReservoir,
)
from metro_station.adapters.simulation.runtime.train_exchange_manifest import (
    TrainExchangeManifest,
    TrainRunId,
)
from metro_station.adapters.simulation.runtime.passenger_goal_region_router import (
    PassengerGoalRegionRouter,
)
from metro_station.adapters.simulation.runtime.platform_waiting_geometry import (
    platform_waiting_slot_is_intent_eligible,
)
from shapely.geometry import LineString, Polygon
from shapely.geometry import Point as ShapelyPoint

from metro_alignment.metro_executor import (
    AlignmentMesaSimulationExecutor,
    AlignmentMetroStationModel,
    PendingSourceDemand,
    SourceAdmission,
    alignment_entry_admission_preflight,
    alignment_source_geometry_preflight,
)
from metro_alignment.metro_scene import build_metro_request
from metro_alignment.scenes import build_scene_config

FA2555_GEOMETRY_QUARANTINE = pytest.mark.skip(
    reason=(
        "expires when frozen-design entry-only reaches admitted=417/417, "
        "pending=0, dropped=0; fa2555 must then enter the proxy geometry "
        "change process or be closed, and all seven quarantines removed"
    )
)


def _model_with_neighbor(
    distance: float,
    *,
    radius: float = 0.18,
    multiplier: float = 2.2,
) -> AlignmentMetroStationModel:
    model = object.__new__(AlignmentMetroStationModel)
    model.scenario = SimpleNamespace(
        jupedsim_agent_radius_units=radius,
        jupedsim_clearance_multiplier=multiplier,
    )
    model.passengers = [
        SimpleNamespace(
            pos=(distance, 0.0),
            physical_motion_layer_id="platform",
            current_level_id="platform",
        )
    ]
    return model


def test_alignment_alighting_admission_closes_metro_clearance_gap() -> None:
    model = _model_with_neighbor(0.365)

    assert MetroStationModel._alighting_spawn_cell_is_clear(
        model,
        (0.0, 0.0),
        "platform",
        [],
    )
    assert not model._alighting_spawn_cell_is_clear(
        (0.0, 0.0),
        "platform",
        [],
    )


@pytest.mark.parametrize(
    ("radius", "multiplier"),
    [(0.18, 2.2), (0.25, 2.4)],
)
def test_alignment_alighting_admission_uses_parameterized_shared_clearance(
    radius: float,
    multiplier: float,
) -> None:
    shared_clearance = radius * multiplier
    conservative_gap_position = radius * ((2.05 + multiplier) / 2.0)
    model = _model_with_neighbor(
        conservative_gap_position,
        radius=radius,
        multiplier=multiplier,
    )

    assert MetroStationModel._alighting_spawn_cell_is_clear(
        model,
        (0.0, 0.0),
        "platform",
        [],
    )
    assert not model._alighting_spawn_cell_is_clear(
        (0.0, 0.0),
        "platform",
        [],
    )

    model.passengers[0].pos = (shared_clearance - 1e-9, 0.0)
    assert not model._alighting_spawn_cell_is_clear(
        (0.0, 0.0),
        "platform",
        [],
    )

    model.passengers[0].pos = (shared_clearance, 0.0)
    assert model._alighting_spawn_cell_is_clear(
        (0.0, 0.0),
        "platform",
        [],
    )


def test_alignment_alighting_admission_applies_to_reserved_batch_positions() -> None:
    model = _model_with_neighbor(1.0)

    assert not model._alighting_spawn_cell_is_clear(
        (0.0, 0.0),
        "platform",
        [((0.365, 0.0), "platform")],
    )
    assert model._alighting_spawn_cell_is_clear(
        (0.0, 0.0),
        "platform",
        [((0.365, 0.0), "other-level")],
    )


def test_alignment_admission_cannot_override_a_metro_rejection() -> None:
    model = _model_with_neighbor(0.36)

    assert not MetroStationModel._alighting_spawn_cell_is_clear(
        model,
        (0.0, 0.0),
        "platform",
        [],
    )
    assert not model._alighting_spawn_cell_is_clear(
        (0.0, 0.0),
        "platform",
        [],
    )


def _backpressure_model() -> tuple[AlignmentMetroStationModel, SimpleNamespace, list]:
    model = _model_with_neighbor(1.0)
    model.scenario.jupedsim_agent_radius_units = 0.18
    model.scenario.jupedsim_clearance_multiplier = 2.2
    model.scenario.alighting_source_lateral_offset_m = 0.0
    model.scenario.group_size = 1
    model.step_index = 0
    model.max_pending_alighting_groups = 0
    model.external_demand_reservoir = ExternalDemandReservoir()
    model.train_exchange_manifests = {}
    model.train_exchange_results = []
    model.train_exchange_failure_rows = []
    model.unbound_not_alighted_persons = 0
    model.run_outcome_code = None
    model.running = True
    model.alignment_requested_alighting_persons = 0
    model.alignment_max_pending_residence_steps_by_flow = Counter()
    model.spawned_persons_by_intent = Counter()
    model.spawned_persons_by_entrance = Counter()
    model.spawned_persons = 0
    model.passenger_goal_runtimes = {}
    model.audit = SimpleNamespace(record=lambda *args, **kwargs: None)
    model.jupedsim_walkable_area = lambda level_id: Polygon(
        [(-5.0, 1.0), (5.0, 1.0), (5.0, -20.0), (-5.0, -20.0)]
    )
    model.clamp_position = lambda position: position
    certified_slots = tuple(
        ((candidate % 4 - 1.5) * 0.4, -(0.35 + candidate // 4 * 0.4)) for candidate in range(67)
    )
    model.layout_graph = SimpleNamespace(
        spatial_capacity_certificate=lambda *args, **kwargs: SimpleNamespace(slots=certified_slots)
    )
    door = SimpleNamespace(
        facility_id="door-a",
        spec=SimpleNamespace(
            exit_position=(0.0, 0.0),
            queue_anchor=(0.0, -1.0),
            exit_level_id="platform",
            entry_level_id=None,
        ),
    )
    train = SimpleNamespace(
        is_boarding=True,
        departed_trains=0,
        unique_id="train-a",
        platform_id="platform-a",
        line_id="line-a",
        direction="outbound",
        arrival_sequence=1,
        arrival_step=0,
        close_step=10,
    )
    model.trains = [train]
    run_ref = model._train_run_ref(train)
    model.train_exchange_manifests[run_ref] = TrainExchangeManifest(
        train_run_id=TrainRunId("platform-a", 1),
        arrival_step=0,
        scheduled_close_step=10,
        capacity_persons=10,
        inbound_load_persons=1,
        planned_alight_persons=1,
        through_load_persons=0,
    )
    model.boarding_doors_for_train = lambda selected_train: [door]
    model._alighting_downstream_admission_evidence = lambda doors: {
        "available": True,
    }
    model._alighting_source_admission_reservation = lambda doors: {
        "available": True,
    }
    model._release_alighting_source_admission_reservation = lambda reservation, *, reason: None
    model._commit_alighting_source_admission_reservation = lambda reservation, passenger: None
    model.movement_backend = SimpleNamespace(remove_passenger=lambda passenger: None)
    model._clear_all_facility_targeting_reservations = lambda passenger: None
    model._clear_all_decision_holding_reservations = lambda passenger: None
    model._remove_from_station_holding_areas = lambda passenger: None
    due = iter((1, 0))
    model.demand_scheduler = SimpleNamespace(due_alightings=lambda step: next(due))
    spawned: list[SimpleNamespace] = []

    def spawn_passenger(intent, *, initial_position, initial_level_id):
        passenger = SimpleNamespace(
            unique_id=len(spawned) + 1,
            pos=initial_position,
            physical_motion_layer_id=initial_level_id,
            current_level_id=initial_level_id,
            assigned_platform_id=None,
            assigned_line_id=None,
            assigned_direction=None,
            group_size=1,
            intent=AgentIntent.EXIT_STATION.value,
            spawn_source_element_id=None,
            remove=lambda: None,
        )
        spawned.append(passenger)
        model.passengers.append(passenger)
        model.spawned_persons_by_intent[str(intent.value)] += 1
        model.spawned_persons += 1
        return passenger

    model._spawn_passenger = spawn_passenger
    return model, train, spawned


def test_blocked_alighting_lattice_defers_then_retries_exactly_once() -> None:
    model, _, spawned = _backpressure_model()
    spacing = 0.4
    model.passengers = [
        SimpleNamespace(
            pos=((candidate % 4 - 1.5) * spacing, -(0.35 + candidate // 4 * spacing)),
            physical_motion_layer_id="platform",
            current_level_id="platform",
        )
        for candidate in range(64)
    ]

    model.spawn_alighting_passengers()

    assert model.pending_alighting_groups == 1
    assert model.max_pending_alighting_groups == 1
    assert spawned == []

    model.passengers = []
    model.spawn_alighting_passengers()

    assert model.pending_alighting_groups == 0
    assert len(spawned) == 1
    assert spawned[0].pos == pytest.approx((-0.6, -0.35))


def test_alighting_without_mapped_doors_remains_pending_and_conserved() -> None:
    model, _, spawned = _backpressure_model()
    model.boarding_doors_for_train = lambda selected_train: []

    with pytest.raises(RuntimeError, match="model_invalid"):
        model.spawn_alighting_passengers()

    assert model.pending_alighting_groups == 1
    assert model.alignment_requested_alighting_persons == 1
    assert spawned == []


def test_alighting_placement_exception_restores_pending_and_token() -> None:
    model, _, _ = _backpressure_model()
    for name in (
        "_alighting_source_admission_reservation",
        "_release_alighting_source_admission_reservation",
        "_commit_alighting_source_admission_reservation",
    ):
        delattr(model, name)
    model.alignment_admission_resources = {
        "entry": AdmissionTokenResource("entry", 1),
        "exit": AdmissionTokenResource("exit", 1),
    }
    model.alignment_admission_attempts = Counter()
    model.alignment_admission_exhausted_attempts = Counter()
    model.alignment_next_source_sequence_id = 0
    model._alignment_inflight_admission_owner_by_intent = {}
    model._alighting_spawn_position = Mock(side_effect=RuntimeError("placement failed"))

    with pytest.raises(RuntimeError, match="placement failed"):
        model.spawn_alighting_passengers()

    assert model.pending_alighting_groups == 1
    assert model.alignment_admission_resources["exit"].occupancy == 0
    model._require_alighting_spawn_conservation()


def test_alighting_transfer_exception_retires_published_fifo_owner(
    monkeypatch,
) -> None:
    model, _, spawned = _backpressure_model()
    for name in (
        "_alighting_source_admission_reservation",
        "_release_alighting_source_admission_reservation",
        "_commit_alighting_source_admission_reservation",
    ):
        delattr(model, name)
    resource = AdmissionTokenResource("exit", 1)
    model.alignment_admission_resources = {
        "entry": AdmissionTokenResource("entry", 1),
        "exit": resource,
    }
    model.alignment_admission_attempts = Counter()
    model.alignment_admission_exhausted_attempts = Counter()
    model.alignment_next_source_sequence_id = 0
    model._alignment_inflight_admission_owner_by_intent = {}
    monkeypatch.setattr(
        resource,
        "transfer",
        Mock(side_effect=RuntimeError("transfer failed")),
    )

    with pytest.raises(RuntimeError, match="transfer failed"):
        model.spawn_alighting_passengers()

    assert len(spawned) == 1
    assert spawned[0] not in model.passengers
    assert model.pending_alighting_groups == 1
    assert model.external_demand_reservoir.pending_groups(
        DemandSourceKind.TRAIN_ALIGHTING
    ) == 1
    assert resource.occupancy == 0
    model._require_alighting_spawn_conservation()


def test_alighting_reservoir_commit_failure_rolls_back_manifest_and_token(
    monkeypatch,
) -> None:
    model, train, spawned = _backpressure_model()
    for name in (
        "_alighting_source_admission_reservation",
        "_release_alighting_source_admission_reservation",
        "_commit_alighting_source_admission_reservation",
    ):
        delattr(model, name)
    resource = AdmissionTokenResource("exit", 1)
    model.alignment_admission_resources = {
        "entry": AdmissionTokenResource("entry", 1),
        "exit": resource,
    }
    model.alignment_admission_attempts = Counter()
    model.alignment_admission_exhausted_attempts = Counter()
    model.alignment_next_source_sequence_id = 0
    model._alignment_inflight_admission_owner_by_intent = {}
    monkeypatch.setattr(
        model.external_demand_reservoir,
        "commit",
        Mock(side_effect=RuntimeError("reservoir commit failed")),
    )

    with pytest.raises(RuntimeError, match="reservoir commit failed"):
        model.spawn_alighting_passengers()

    manifest = model.train_exchange_manifests[model._train_run_ref(train)]
    assert len(spawned) == 1
    assert spawned[0] not in model.passengers
    assert model.pending_alighting_groups == 1
    assert resource.occupancy == 0
    assert manifest.released_alight_persons == 0
    assert manifest.not_alighted_persons == manifest.planned_alight_persons
    model._require_alighting_spawn_conservation()


def test_alignment_executor_is_a_drop_in_metro_executor() -> None:
    executor = AlignmentMesaSimulationExecutor()

    assert executor.routing_algorithm is None
    assert executor.routing_parameters == {}
    assert issubclass(AlignmentMetroStationModel, MetroStationModel)


def test_formal_scene_keeps_registered_demand_contract() -> None:
    request, _ = build_metro_request(build_scene_config("platform_boarding"))

    assert request.scenario.entry_count_hour == 2500
    assert request.scenario.exit_count_hour == 2200
    assert request.scenario.demand_steps == 600
    assert request.scenario.horizon_steps == 600
    assert request.scenario.alighting_source_lateral_offset_m == pytest.approx(10.0)


def _registered_admission_probe_config():
    return replace(
        build_scene_config("platform_boarding"),
        minutes=3,
        demand_minutes=2,
    )


def test_post_entry_route_starts_from_fixed_entry_bank_paid_portal() -> None:
    config = _registered_admission_probe_config()
    request, _ = build_metro_request(config)
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    entry_gate = model.gates[1]
    boarding_door = model.boarding_doors[0]
    with patch.object(model.goal_coordinator, "initialize"):
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
            initial_position=entry_gate.portal_exit_position,
            initial_level_id=entry_gate.portal_exit_level_id,
        )
    passenger.last_completed_facility_id = entry_gate.facility_id
    passenger.last_completed_facility_position = passenger.pos
    passenger.last_completed_facility_event_id = "accepted-entry-gate-completion"
    passenger.last_completed_facility_level_id = passenger.current_level_id
    graph = model.layout_graph.station_graph
    binding = model.facility_portal_binding(boarding_door.facility_id)

    candidates = model._station_graph_route_start_candidates(
        passenger,
        boarding_door,
        graph,
        binding.entry_level_id,
    )

    assert [node.node_id for node in candidates] == ["gate:entry_gate_bank_a:paid"]
    route = model._station_graph_route_to_facility(
        passenger,
        boarding_door,
        final_target_override=boarding_door.portal_entry_position,
        include_navigation_waypoints=True,
    )
    opposing_entry = graph.nodes["gate:exit_gate_bank_a:exit"].position
    assert route
    assert opposing_entry not in route


def test_formal_gate_bank_uses_three_fixed_lanes_per_direction() -> None:
    request, _ = build_metro_request(_registered_admission_probe_config())
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)

    assert len(model.gates) == 3
    assert len(model.exit_gates) == 3
    assert {gate.portal_direction for gate in model.gates} == {"in"}
    assert {gate.portal_direction for gate in model.exit_gates} == {"out"}
    assert {gate.spec.source_element_id for gate in model.gates} == {"entry_gate_bank_a"}
    assert {gate.spec.source_element_id for gate in model.exit_gates} == {"exit_gate_bank_a"}
    assert not {gate._physical_lane_key() for gate in model.gates} & {
        gate._physical_lane_key() for gate in model.exit_gates
    }


def test_formal_entry_and_exit_access_are_physically_separated() -> None:
    request, _ = build_metro_request(_registered_admission_probe_config())
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    graph = model.layout_graph.station_graph
    entrances = {node.element_id: node for node in graph.nodes_matching(kind="entrance")}

    assert request.scenario.entry_entrance_weights == (
        ("entrance_a", 1.0),
        ("exit_a", 0.0),
    )
    assert set(entrances) == {"entrance_a", "exit_a"}
    assert entrances["entrance_a"].position != entrances["exit_a"].position

    exit_gate = model.exit_gates[0]
    with patch.object(model.goal_coordinator, "initialize"):
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EXIT_STATION,
            initial_position=exit_gate.portal_exit_position,
            initial_level_id=exit_gate.portal_exit_level_id,
        )
    passenger.last_completed_facility_id = exit_gate.facility_id
    passenger.last_completed_facility_position = passenger.pos
    passenger.last_completed_facility_event_id = "accepted-exit-gate-completion"
    passenger.last_completed_facility_level_id = passenger.current_level_id

    route = model._station_graph_route_to_exit(passenger)

    assert route
    assert route[-1] == entrances["exit_a"].position
    assert entrances["entrance_a"].position not in route


def test_formal_fixed_exit_bank_is_reachable_from_platform() -> None:
    request, _ = build_metro_request(_registered_admission_probe_config())
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    graph = model.layout_graph.station_graph
    platform = graph.nodes[graph.primary_node_by_element_id["platform_edge_a"]]

    for gate in model.exit_gates:
        with patch.object(model.goal_coordinator, "initialize"):
            passenger = PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.EXIT_STATION,
                initial_position=platform.position,
                initial_level_id=platform.level_id,
            )

        route = model.route_to_facility_queue_slot(passenger, gate, 0)

        assert route
        assert route[-1] == model._facility_approach_slot_position(gate, 0)
        assert gate.spec.source_element_id == "exit_gate_bank_a"
        assert gate.portal_direction == "out"


def test_formal_boarding_edge_uses_seven_parallel_train_doors() -> None:
    request, _ = build_metro_request(_registered_admission_probe_config())
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)

    assert len(model.boarding_doors) == 7
    assert len(model.platforms) == 1
    assert {door.spec.source_element_id for door in model.boarding_doors} == {
        f"platform_edge_{suffix}" for suffix in "abcdefg"
    }
    assert {door.spec.platform_id for door in model.boarding_doors} == {"platform:default:down"}
    assert request.scenario.station_design.metadata["boarding_door_count"] == 7


@FA2555_GEOMETRY_QUARANTINE
def test_formal_boarding_backpressure_stays_on_paid_side_after_gate() -> None:
    request, _ = build_metro_request(build_scene_config("platform_boarding"))
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    gate = model.gates[0]
    platform = model.platforms[0]
    with patch.object(model.goal_coordinator, "initialize"):
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
            initial_position=gate.portal_exit_position,
            initial_level_id=gate.portal_exit_level_id,
        )

    target = model._reserve_platform_waiting_slot(passenger, platform)
    router = PassengerGoalRegionRouter()
    with patch.object(router, "_tactical_facility_selection", return_value=None):
        route = router.route(model, passenger, "boarding_decision")

    paid_side_y = max(item.portal_exit_position[1] for item in model.gates)
    assert target[1] > paid_side_y
    assert platform_waiting_slot_is_intent_eligible(
        model,
        target,
        level_id=passenger.current_level_id,
        passenger=passenger,
    )
    assert not platform_waiting_slot_is_intent_eligible(
        model,
        (target[0], paid_side_y - 1.0),
        level_id=passenger.current_level_id,
        passenger=passenger,
    )
    paid_egress = model.layout_graph.station_graph.nodes[
        model.layout_graph.station_graph.primary_node_by_element_id["main_hall"]
    ]
    exit_queue_head_y = min(
        point[1]
        for gate_candidate in model.exit_gates
        for point in gate_candidate.queue.layout.slots
    )
    assert paid_egress.position in route
    assert paid_egress.position[1] < exit_queue_head_y
    assert route[-1] == target
    assert not passenger.decision_holding_target_by_region
    assert not passenger.facility_approach_facility_ids_by_stage


@FA2555_GEOMETRY_QUARANTINE
def test_formal_entry_gate_approach_uses_bank_tail_aisle() -> None:
    request, _ = build_metro_request(build_scene_config("platform_boarding"))
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    gate = model.gates[-2]
    with patch.object(model.goal_coordinator, "initialize"):
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
            initial_position=(13.82, 15.65),
            initial_level_id=gate.portal_entry_level_id,
        )
    selection = SimpleNamespace(facility_id=gate.facility_id)
    executor = model.goal_coordinator.executor
    with patch.object(
        executor.region_router,
        "_tactical_facility_selection",
        return_value=selection,
    ):
        events = executor._walk_to_region(
            model,
            passenger,
            SimpleNamespace(
                target_region_id="entry_gate_decision",
                stage=None,
            ),
        )
    route = (passenger.target, *passenger.route)

    slot_index = passenger.facility_approach_slots_by_stage["entry_gate"]
    ingress = model._gate_queue_ingress_anchors(passenger, gate, slot_index)
    assert ingress[0][0] == pytest.approx(passenger.pos[0])
    assert passenger.route_waypoint_radius_override == pytest.approx(0.8)
    assert events == ()
    tactical_zone_positions = {
        node.position
        for node in model.layout_graph.station_graph.nodes.values()
        if node.kind == "zone" and node.tactical_anchor
    }
    assert tactical_zone_positions.isdisjoint(route)
    assert set(gate.queue.layout.slots).isdisjoint(route)
    assert route[-1] == ingress[-1]
    passenger.pos = (ingress[-1][0] + 0.6, ingress[-1][1])
    assert executor.region_router.reached(passenger, route)
    passenger.pos = ingress[-1]
    assert executor._captures_queue_at_decision_boundary(
        model,
        passenger,
        gate,
    )


@FA2555_GEOMETRY_QUARANTINE
def test_formal_entry_holding_preserves_entrance_to_gate_ingress() -> None:
    request, _ = build_metro_request(build_scene_config("platform_boarding"))
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    graph = model.layout_graph.station_graph
    entrance = graph.nodes_matching(kind="entrance")[0]
    gate = model.gates[-2]
    with patch.object(model.goal_coordinator, "initialize"):
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
            initial_position=entrance.position,
            initial_level_id=entrance.level_id,
        )

    ingress = model._gate_queue_ingress_anchors(passenger, gate, 0)
    access_line = LineString((entrance.position, ingress[0]))
    holding = next(
        region
        for region in model.layout_graph.decision_holding_regions
        if region.region_id == "entry_gate_decision" and region.level_id == entrance.level_id
    )

    assert holding.slots
    assert all(
        ShapelyPoint(slot).distance(access_line) >= model.scenario.personal_space_units - 1e-6
        for slot in holding.slots
    )


@FA2555_GEOMETRY_QUARANTINE
def test_formal_exit_route_uses_unpaid_egress_aisle() -> None:
    request, _ = build_metro_request(build_scene_config("platform_boarding"))
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    gate = model.exit_gates[-2]
    with patch.object(model.goal_coordinator, "initialize"):
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EXIT_STATION,
            initial_position=gate.portal_exit_position,
            initial_level_id=gate.portal_exit_level_id,
        )

    route = model._station_graph_route_to_exit(passenger)
    graph = model.layout_graph.station_graph
    aisle = graph.nodes[graph.primary_node_by_element_id["exit_aisle"]]
    entrance = graph.nodes_matching(kind="entrance")[0]

    assert aisle.position in route
    assert route[0] == aisle.position
    assert route[-1] == entrance.position


@FA2555_GEOMETRY_QUARANTINE
def test_formal_exit_gate_approach_omits_broad_hall_detour() -> None:
    request, _ = build_metro_request(build_scene_config("platform_boarding"))
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    gate = model.exit_gates[-2]
    with patch.object(model.goal_coordinator, "initialize"):
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EXIT_STATION,
            initial_position=(32.0, 25.8),
            initial_level_id=gate.portal_entry_level_id,
        )

    route = model.route_to_facility_queue_slot(passenger, gate, 0)
    tactical_zone_positions = {
        node.position
        for node in model.layout_graph.station_graph.nodes.values()
        if node.kind == "zone" and node.tactical_anchor
    }

    assert route
    assert tactical_zone_positions.isdisjoint(route)
    assert route[-1] == model._facility_approach_slot_position(gate, 0)


def test_exit_gate_ingress_fans_outer_approach_by_lane() -> None:
    config = replace(
        build_scene_config("platform_boarding"),
        entry_admission_token_capacity=100_000,
        exit_admission_token_capacity=100_000,
    )
    request, _ = build_metro_request(config)
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    origin = (32.0, 25.8)
    first_anchors = []

    for gate in model.exit_gates:
        with patch.object(model.goal_coordinator, "initialize"):
            passenger = PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.EXIT_STATION,
                initial_position=origin,
                initial_level_id=gate.portal_entry_level_id,
            )
        ingress = model._gate_queue_ingress_anchors(passenger, gate, 0)
        assert ingress
        first_anchors.append(ingress[0])

    minimum_body_clearance = (
        model.scenario.jupedsim_agent_radius_units
        * model.scenario.jupedsim_clearance_multiplier
    )
    assert all(
        ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5
        >= minimum_body_clearance
        for index, left in enumerate(first_anchors)
        for right in first_anchors[index + 1 :]
    )


@FA2555_GEOMETRY_QUARANTINE
def test_formal_exit_decision_routes_around_boarding_fifo() -> None:
    request, _ = build_metro_request(build_scene_config("platform_boarding"))
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    graph = model.layout_graph.station_graph
    platform_node = graph.nodes[graph.primary_node_by_element_id["platform_edge_a"]]
    gate = model.exit_gates[-2]
    with patch.object(model.goal_coordinator, "initialize"):
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EXIT_STATION,
            initial_position=platform_node.position,
            initial_level_id=platform_node.level_id,
        )
    router = PassengerGoalRegionRouter()
    selection = SimpleNamespace(facility_id=gate.facility_id)
    with patch.object(
        router,
        "_tactical_facility_selection",
        return_value=selection,
    ):
        route = router.route(model, passenger, "exit_gate_decision")

    cross = graph.nodes[graph.primary_node_by_element_id["platform_exit_cross_aisle"]].position
    down = graph.nodes[graph.primary_node_by_element_id["platform_exit_down_aisle"]].position
    hall = graph.nodes[graph.primary_node_by_element_id["main_hall"]].position

    assert cross in route
    assert down in route
    assert hall in route
    assert route.index(cross) < route.index(down) < route.index(hall)


@FA2555_GEOMETRY_QUARANTINE
def test_formal_platform_waiting_preserves_exit_gate_tail_ingress() -> None:
    request, _ = build_metro_request(build_scene_config("platform_boarding"))
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    gate = model.exit_gates[-1]
    with patch.object(model.goal_coordinator, "initialize"):
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EXIT_STATION,
            initial_position=(32.0, 25.8),
            initial_level_id=gate.portal_entry_level_id,
        )

    ingress = model._gate_queue_ingress_anchors(passenger, gate, 0)
    ingress_line = LineString((passenger.pos, *ingress))
    waiting_slots = model.layout_graph.platform_waiting_slots()

    assert waiting_slots
    assert all(
        ShapelyPoint(slot).distance(ingress_line) >= model.scenario.personal_space_units - 1e-6
        for slot in waiting_slots
    )


def test_source_geometry_preflight_accepts_decoupled_queue_lattice() -> None:
    request, _ = build_metro_request(build_scene_config("platform_boarding"))

    report = alignment_source_geometry_preflight(request.scenario)

    assert report["status"] == "pass"
    assert report["runtime_status"] == "ready"
    assert report["scientific_status"] == "eligible"
    assert report["outcome"] == "eligible"
    queue = report["queue_reports"][0]
    assert queue["minimum_body_clearance_m"] == pytest.approx(0.396)
    assert queue["runtime_candidate_spacing_m"] == pytest.approx(0.4)
    assert queue["maximum_candidate_projection_shift_m"] == pytest.approx(0.0)
    assert queue["source_candidate_count"] == 66
    assert queue["unique_source_candidate_count"] == 66
    assert queue["peak_scheduled_alighting_batch"] == 3
    assert queue["holding_area_overlap_candidate_count"] == 0
    assert queue["holding_clearance_overlap_candidate_count"] == 0
    assert queue["boarding_door_axis_overlap_candidate_count"] == 0
    assert queue["capacity_certificate"] is True
    assert queue["capacity_certificate_id"] == ("alighting_source:queue_platform_edge_a_down")
    assert queue["compiler_error_codes"] == []
    assert queue["compiler_rejection_reproduced"] is False
    assert queue["blockers"] == []


def test_metro_compiler_accepts_the_decoupled_source_lattice() -> None:
    request, _ = build_metro_request(build_scene_config("platform_boarding"))

    compiled = validate_compiled_station_design(
        request.scenario.station_design,
        request.scenario,
    )

    sources = tuple(
        certificate
        for certificate in compiled.spatial_capacity_certificates
        if certificate.resource_kind == "alighting_source"
    )
    assert len(sources) == 7
    assert {source.certificate_id for source in sources} == {
        f"alighting_source:queue_platform_edge_{suffix}_down" for suffix in "abcdefg"
    }
    assert all(len(source.slots) >= 3 for source in sources)
    assert all(source.required_body_capacity == 3 for source in sources)
    assert all(source.certified_body_capacity == 3 for source in sources)
    errors = tuple(item for item in compiled.issues if item.severity == "error")
    assert errors == ()


def test_executor_starts_model_after_source_geometry_passes(monkeypatch) -> None:
    executor = AlignmentMesaSimulationExecutor()
    request, _ = build_metro_request(_registered_admission_probe_config())
    model = SimpleNamespace(run=lambda *, progress_callback=None: [{"step": 1}])
    monkeypatch.setattr(
        executor,
        "build_model",
        lambda selected_request: model,
    )

    result = executor.execute(request)

    assert result.runtime is model
    assert result.frames == [{"step": 1}]


def test_source_geometry_preflight_still_fails_closed_without_lateral_offset() -> None:
    config = replace(
        build_scene_config("platform_boarding"),
        alighting_source_lateral_offset_m=0.0,
    )
    request, _ = build_metro_request(config)

    report = alignment_source_geometry_preflight(request.scenario)

    assert report["status"] == "fail"
    assert report["runtime_status"] == "not_started"
    assert report["outcome"] == "model_invalid"
    assert report["queue_reports"][0]["blockers"] == [
        "boarding_holding_area_overlaps_alighting_source_lattice",
        "boarding_door_axis_overlaps_alighting_source_lattice",
    ]


def _source_policy_model() -> AlignmentMetroStationModel:
    model = object.__new__(AlignmentMetroStationModel)
    node = SimpleNamespace(
        position=(1.0, 1.0),
        element_id="entrance-a",
        node_id="entrance-node-a",
        level_id="l1",
    )
    station_graph = SimpleNamespace(
        nodes_matching=lambda *, kind: [node] if kind == "entrance" else [],
    )
    model.layout_graph = SimpleNamespace(station_graph=station_graph)
    model.scenario = SimpleNamespace(
        group_size=1,
        entry_entrance_weights=(),
        jupedsim_agent_radius_units=0.18,
        jupedsim_clearance_multiplier=2.2,
        horizon_steps=600,
    )
    model.step_index = 0
    model.random = Random(42)
    model.external_demand_reservoir = ExternalDemandReservoir()
    model.alignment_source_spec_by_ticket = {}
    model.alignment_next_source_sequence_id = 0
    model.alignment_requested_source_persons_by_intent = Counter()
    model.alignment_max_pending_source_groups = 0
    model.alignment_source_deferred_attempts = 0
    model.alignment_admission_resources = {
        "entry": AdmissionTokenResource("entry", 30),
        "exit": AdmissionTokenResource("exit", 30),
    }
    model.alignment_admission_attempts = Counter()
    model.alignment_admission_exhausted_attempts = Counter()
    model.alignment_max_pending_residence_steps_by_flow = Counter()
    model._alignment_inflight_admission_owner_by_intent = {}
    model.alignment_requested_alighting_persons = 0
    model.demand_scheduler = SimpleNamespace(
        due_by_intent=lambda step: Counter(),
        spawn_schedule={},
        alighting_schedule={},
    )
    model.audit = SimpleNamespace(record=lambda *args, **kwargs: None)
    model.spatial_capacity_event_counts = Counter()
    model.service_chain_event_counts = Counter()
    model.alignment_time_attribution = SimpleNamespace(metrics=dict)
    model.passengers = []
    model.passenger_goal_runtimes = {}
    model.spawned_persons = 0
    model.spawned_persons_by_intent = Counter()
    model.spawned_persons_by_entrance = Counter()
    model.frames = []
    model.boarding_doors = []
    model.trains = []
    model.movement_backend = SimpleNamespace(remove_passenger=lambda passenger: None)
    model._clear_all_facility_targeting_reservations = lambda passenger: None
    model._clear_all_decision_holding_reservations = lambda passenger: None
    model._remove_from_station_holding_areas = lambda passenger: None
    return model


def _enqueue_source_demand(
    model: AlignmentMetroStationModel,
    demand: PendingSourceDemand,
):
    ticket = model.external_demand_reservoir.enqueue(
        scheduled_step=demand.scheduled_step,
        intent=demand.intent,
        group_size=demand.group_size,
        source_kind=DemandSourceKind.ENTRY,
        source_ref=demand.intent,
    )
    model.alignment_source_spec_by_ticket[ticket.sequence_id] = replace(
        demand,
        sequence_id=ticket.sequence_id,
    )
    return ticket


def test_blocked_entry_admission_has_zero_published_side_effects(monkeypatch) -> None:
    model = _source_policy_model()
    demand = model._alignment_schedule_source_demand("enter_and_board")
    ticket = _enqueue_source_demand(model, demand)
    model.alignment_requested_source_persons_by_intent["enter_and_board"] = 1
    model.demand_scheduler.due_by_intent = lambda step: Counter()
    monkeypatch.setattr(model, "_alignment_source_admission", lambda pending: None)
    before = {
        "passengers": tuple(model.passengers),
        "goal_runtimes": dict(model.passenger_goal_runtimes),
        "spawned": model.spawned_persons,
        "by_intent": dict(model.spawned_persons_by_intent),
        "by_entrance": dict(model.spawned_persons_by_entrance),
        "frames": tuple(model.frames),
    }

    model.spawn_passengers()

    assert model.external_demand_reservoir.pending_tickets(DemandSourceKind.ENTRY) == (
        ticket,
    )
    assert tuple(model.passengers) == before["passengers"]
    assert dict(model.passenger_goal_runtimes) == before["goal_runtimes"]
    assert model.spawned_persons == before["spawned"]
    assert dict(model.spawned_persons_by_intent) == before["by_intent"]
    assert dict(model.spawned_persons_by_entrance) == before["by_entrance"]
    assert tuple(model.frames) == before["frames"]


def test_entry_admission_exception_restores_pending_and_token(monkeypatch) -> None:
    model = _source_policy_model()
    model.demand_scheduler.due_by_intent = lambda step: Counter(
        {AgentIntent.ENTER_AND_BOARD.value: 1}
    )
    monkeypatch.setattr(
        model,
        "_alignment_source_admission",
        Mock(side_effect=RuntimeError("admission failed")),
    )

    with pytest.raises(RuntimeError, match="admission failed"):
        model.spawn_passengers()

    assert model.external_demand_reservoir.pending_groups(DemandSourceKind.ENTRY) == 1
    assert model.alignment_admission_resources["entry"].occupancy == 0
    model._require_alignment_source_conservation()


def test_source_resolution_exception_retains_unresolved_due_group() -> None:
    model = _source_policy_model()
    model.layout_graph = SimpleNamespace(station_graph=None)
    model.demand_scheduler.due_by_intent = lambda step: Counter(
        {AgentIntent.ENTER_AND_BOARD.value: 1}
    )

    with pytest.raises(RuntimeError, match="compiled station graph"):
        model.spawn_passengers()

    assert model.alignment_requested_source_persons_by_intent["enter_and_board"] == 1
    assert model.external_demand_reservoir.pending_groups(DemandSourceKind.ENTRY) == 1
    model._require_alignment_source_conservation()


def test_entry_transfer_exception_retains_only_unprocessed_tail(monkeypatch) -> None:
    model = _source_policy_model()
    model.demand_scheduler.due_by_intent = lambda step: Counter(
        {AgentIntent.ENTER_AND_BOARD.value: 2}
    )
    monkeypatch.setattr(
        model,
        "_alignment_source_admission",
        lambda demand: SourceAdmission((0.0, 0.0), "l1", "entrance-a"),
    )

    def publish(intent, *, initial_position, initial_level_id):
        del initial_position, initial_level_id
        model.spawned_persons_by_intent[str(intent)] += 1
        model.spawned_persons += 1
        passenger = SimpleNamespace(
            unique_id=41,
            group_size=1,
            intent=str(intent),
            spawn_source_element_id=None,
            remove=lambda: None,
        )
        model.passengers.append(passenger)
        return passenger

    monkeypatch.setattr(model, "_spawn_passenger", publish)
    resource = model.alignment_admission_resources["entry"]
    monkeypatch.setattr(
        resource,
        "transfer",
        Mock(side_effect=RuntimeError("transfer failed")),
    )

    with pytest.raises(RuntimeError, match="transfer failed"):
        model.spawn_passengers()

    assert model.external_demand_reservoir.pending_groups(DemandSourceKind.ENTRY) == 2
    assert resource.occupancy == 0
    model._require_alignment_source_conservation()


def test_failed_source_sampling_restores_rng_and_uses_512_attempts(monkeypatch) -> None:
    model = _source_policy_model()
    demand = model._alignment_schedule_source_demand("enter_and_board")
    attempts = 0

    def failed_sampling(node, *, local_radius):
        nonlocal attempts
        for _ in range(512):
            attempts += 1
            model.random.random()

    monkeypatch.setattr(model, "_alignment_sample_source_position", failed_sampling)
    before_rng = model.random.getstate()

    assert model._alignment_source_admission(demand) is None
    assert attempts == 512
    assert model.random.getstate() == before_rng


def test_source_backpressure_is_fifo_and_constructor_errors_propagate(monkeypatch) -> None:
    model = _source_policy_model()
    first = model._alignment_schedule_source_demand("enter_and_board")
    second = model._alignment_schedule_source_demand("enter_and_board")
    first_ticket = _enqueue_source_demand(model, first)
    second_ticket = _enqueue_source_demand(model, second)
    model.alignment_requested_source_persons_by_intent["enter_and_board"] = 2
    model.demand_scheduler.due_by_intent = lambda step: Counter()
    attempted: list[int] = []

    def blocked_head(demand):
        attempted.append(demand.sequence_id)

    monkeypatch.setattr(model, "_alignment_source_admission", blocked_head)
    model.spawn_passengers()
    assert attempted == [first_ticket.sequence_id]
    assert model.external_demand_reservoir.pending_tickets(DemandSourceKind.ENTRY) == (
        first_ticket,
        second_ticket,
    )

    monkeypatch.setattr(
        model,
        "_alignment_source_admission",
        lambda demand: SourceAdmission((0.0, 0.0), demand.level_id, demand.source_id),
    )
    monkeypatch.setattr(
        model,
        "_spawn_passenger",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("constructor defect")),
    )
    with pytest.raises(RuntimeError, match="constructor defect"):
        model.spawn_passengers()
    assert model.external_demand_reservoir.pending_tickets(DemandSourceKind.ENTRY) == (
        first_ticket,
        second_ticket,
    )


def test_source_backpressure_preserves_global_fifo_across_sources(
    monkeypatch,
) -> None:
    model = _source_policy_model()
    blocked = model._alignment_schedule_source_demand("enter_and_board")
    independent = replace(
        model._alignment_schedule_source_demand("enter_and_board"),
        source_id="entrance-b",
    )
    blocked_ticket = _enqueue_source_demand(model, blocked)
    independent_ticket = _enqueue_source_demand(model, independent)
    model.alignment_requested_source_persons_by_intent["enter_and_board"] = 2
    admitted: list[str] = []

    def source_admission(demand):
        if demand.source_id == blocked.source_id:
            return None
        return SourceAdmission((2.0, 2.0), demand.level_id, demand.source_id)

    def spawn_passenger(intent, *, initial_position, initial_level_id):
        admitted.append(independent.source_id)
        model.spawned_persons_by_intent[intent] += 1
        return SimpleNamespace(unique_id=len(admitted), group_size=1)

    monkeypatch.setattr(model, "_alignment_source_admission", source_admission)
    monkeypatch.setattr(model, "_spawn_passenger", spawn_passenger)

    model.spawn_passengers()

    assert admitted == []
    assert model.external_demand_reservoir.pending_tickets(DemandSourceKind.ENTRY) == (
        blocked_ticket,
        independent_ticket,
    )


def test_source_pending_record_is_stable_and_metrics_expose_conservation() -> None:
    model = _source_policy_model()
    demand = model._alignment_schedule_source_demand("enter_and_board")
    assert isinstance(demand, PendingSourceDemand)
    assert demand.scheduled_step == model.step_index
    assert demand.intent == "enter_and_board"
    assert demand.source_id
    assert demand.group_size == model.scenario.group_size

    model.demand_scheduler.spawn_schedule = {
        0: Counter({"enter_and_board": 1}),
    }
    model.alignment_requested_source_persons_by_intent["enter_and_board"] = 1
    ticket = _enqueue_source_demand(model, demand)
    metrics = model.alignment_source_admission_metrics()
    assert metrics["alignment_pending_entry_groups"] == 1
    assert metrics["alignment_pending_entry_persons"] == model.scenario.group_size
    assert metrics["alignment_entry_demand_conserved"] is True
    assert metrics["alignment_source_demand_conserved"] is True
    assert metrics["alignment_placement_retry_ratio"] == 0.0
    assert metrics["alignment_waiting_capacity_retry_ratio"] == 0.0
    assert metrics["alignment_stalled_platform_parking_ratio"] == 0.0
    assert metrics["alignment_service_time_attribution"] == {}

    claim = model.external_demand_reservoir.claim_next(
        DemandSourceKind.ENTRY,
        ticket.source_ref,
        step=model.step_index,
    )
    assert claim is not None
    model.external_demand_reservoir.commit(
        claim,
        passenger_id=999,
        published_step=model.step_index,
    )
    lost_metrics = model.alignment_source_admission_metrics()
    assert lost_metrics["alignment_entry_demand_conserved"] is False
    assert lost_metrics["alignment_source_dropped_persons"] == 1


def test_source_conservation_fails_on_first_unowned_demand() -> None:
    model = _source_policy_model()
    model.alignment_requested_source_persons_by_intent[AgentIntent.ENTER_AND_BOARD.value] = 1

    with pytest.raises(
        RuntimeError,
        match="requested=1, admitted=0, pending=0",
    ):
        model._require_alignment_source_conservation()


def test_admission_preflight_keeps_stale_counting_capacity_diagnostic() -> None:
    request, _ = build_metro_request(_registered_admission_probe_config())

    report = alignment_entry_admission_preflight(request.scenario)

    assert report["status"] == "pass"
    by_flow = {item["flow_id"]: item for item in report["flows"]}
    assert by_flow["entry"]["required_capacity"] is None
    assert by_flow["entry"]["configured_capacity"] == 26
    assert by_flow["entry"]["evidence_status"] == "stale_or_unavailable"
    assert any(
        item["code"] == "admission_residence_evidence_metro_runtime_mismatch"
        for item in by_flow["entry"]["diagnostics"]
    )
    assert by_flow["exit"]["required_capacity"] is None
    assert by_flow["exit"]["configured_capacity"] == 73
    assert (
        by_flow["exit"]["resource_semantics"]
        == "diagnostic_counting_credit_not_physical_storage"
    )


def test_stale_token_sizing_does_not_block_external_source_runtime() -> None:
    config = replace(
        build_scene_config("platform_boarding"),
        minutes=3,
        demand_minutes=2,
        entry_admission_token_capacity=25,
    )
    request, _ = build_metro_request(config)
    executor = AlignmentMesaSimulationExecutor(formal_horizon_steps=1)

    result = executor.execute(request)
    entry = next(
        item
        for item in alignment_entry_admission_preflight(request.scenario)["flows"]
        if item["flow_id"] == "entry"
    )

    assert result.runtime.step_index == 1
    assert entry["required_capacity"] is None
    assert entry["configured_capacity"] == 25


def test_exceptional_run_finalizes_active_admission_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(
        _registered_admission_probe_config(),
        entry_admission_token_capacity=100_000,
        exit_admission_token_capacity=100_000,
    )
    request, _ = build_metro_request(config)
    model = AlignmentMetroStationModel(request.scenario, seed=request.seed)
    resource = model.alignment_admission_resources["entry"]
    assert resource.acquire("exception-owner", model.step_index)

    def fail_step() -> None:
        raise RuntimeError("injected step failure")

    monkeypatch.setattr(model, "step", fail_step)

    with pytest.raises(RuntimeError, match="injected step failure"):
        model.run()

    assert resource.occupancy == 0
    assert resource.completed_residences[-1].owner_id == "exception-owner"
    assert resource.completed_residences[-1].right_censored is True
