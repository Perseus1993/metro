from __future__ import annotations

from collections import Counter, deque
from dataclasses import replace
from random import Random
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.compilation.validation import (
    validate_compiled_station_design,
)
from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.runtime.passenger_goal_region_router import (
    PassengerGoalRegionRouter,
)
from metro_station.adapters.simulation.runtime.platform_waiting_geometry import (
    platform_waiting_slot_is_intent_eligible,
)
from shapely.geometry import LineString, Point as ShapelyPoint, Polygon

from metro_alignment.metro_executor import (
    AlignmentMesaSimulationExecutor,
    AlignmentMetroStationModel,
    PendingSourceDemand,
    SourceAdmission,
    alignment_source_geometry_preflight,
)
from metro_alignment.metro_scene import build_metro_request
from metro_alignment.scenes import build_scene_config


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
    model.step_index = 0
    model.pending_alighting_groups = 0
    model.max_pending_alighting_groups = 0
    model.audit = SimpleNamespace(record=lambda *args, **kwargs: None)
    model.jupedsim_walkable_area = lambda level_id: Polygon(
        [(-5.0, 1.0), (5.0, 1.0), (5.0, -20.0), (-5.0, -20.0)]
    )
    model.clamp_position = lambda position: position
    certified_slots = tuple(
        ((candidate % 4 - 1.5) * 0.4, -(0.35 + candidate // 4 * 0.4))
        for candidate in range(67)
    )
    model.layout_graph = SimpleNamespace(
        spatial_capacity_certificate=lambda *args, **kwargs: SimpleNamespace(
            slots=certified_slots
        )
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
    )
    model.trains = [train]
    model.boarding_doors_for_train = lambda selected_train: [door]
    model._alighting_downstream_admission_evidence = lambda doors: {
        "available": True,
    }
    due = iter((1, 0))
    model.demand_scheduler = SimpleNamespace(due_alightings=lambda step: next(due))
    spawned: list[SimpleNamespace] = []

    def spawn_passenger(intent, *, initial_position, initial_level_id):
        passenger = SimpleNamespace(
            pos=initial_position,
            physical_motion_layer_id=initial_level_id,
            current_level_id=initial_level_id,
            assigned_platform_id=None,
            assigned_line_id=None,
            assigned_direction=None,
        )
        spawned.append(passenger)
        model.passengers.append(passenger)
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


@pytest.mark.skip(reason="requires the quarantined alignment geometry candidate")
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


@pytest.mark.skip(reason="requires the quarantined alignment geometry candidate")
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


@pytest.mark.skip(reason="requires the quarantined alignment geometry candidate")
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
        if region.region_id == "entry_gate_decision"
        and region.level_id == entrance.level_id
    )

    assert holding.slots
    assert all(
        ShapelyPoint(slot).distance(access_line)
        >= model.scenario.personal_space_units - 1e-6
        for slot in holding.slots
    )


@pytest.mark.skip(reason="requires the quarantined alignment geometry candidate")
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


@pytest.mark.skip(reason="requires the quarantined alignment geometry candidate")
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


@pytest.mark.skip(reason="requires the quarantined alignment geometry candidate")
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

    cross = graph.nodes[
        graph.primary_node_by_element_id["platform_exit_cross_aisle"]
    ].position
    down = graph.nodes[
        graph.primary_node_by_element_id["platform_exit_down_aisle"]
    ].position
    hall = graph.nodes[graph.primary_node_by_element_id["main_hall"]].position

    assert cross in route
    assert down in route
    assert hall in route
    assert route.index(cross) < route.index(down) < route.index(hall)


@pytest.mark.skip(reason="requires the quarantined alignment geometry candidate")
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
        ShapelyPoint(slot).distance(ingress_line)
        >= model.scenario.personal_space_units - 1e-6
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
    assert queue["source_candidate_count"] == 67
    assert queue["unique_source_candidate_count"] == 67
    assert queue["peak_scheduled_alighting_batch"] == 4
    assert queue["holding_area_overlap_candidate_count"] == 0
    assert queue["holding_clearance_overlap_candidate_count"] == 0
    assert queue["boarding_door_axis_overlap_candidate_count"] == 0
    assert queue["capacity_certificate"] is True
    assert queue["capacity_certificate_id"] == (
        "alighting_source:queue_platform_edge_a_down"
    )
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
    assert len(sources) == 1
    assert sources[0].certificate_id == (
        "alighting_source:queue_platform_edge_a_down"
    )
    assert len(sources[0].slots) == 67
    assert sources[0].required_body_capacity == 4
    assert sources[0].certified_body_capacity == 4
    errors = tuple(
        item
        for item in compiled.issues
        if item.severity == "error"
    )
    assert errors == ()


def test_executor_starts_model_after_source_geometry_passes(monkeypatch) -> None:
    executor = AlignmentMesaSimulationExecutor()
    request, _ = build_metro_request(build_scene_config("platform_boarding"))
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
    model.alignment_pending_source_demands = deque()
    model.alignment_next_source_sequence_id = 0
    model.alignment_requested_source_persons_by_intent = Counter()
    model.alignment_max_pending_source_groups = 0
    model.alignment_source_deferred_attempts = 0
    model.demand_scheduler = SimpleNamespace(
        due_by_intent=lambda step: Counter(),
        spawn_schedule={},
    )
    model.audit = SimpleNamespace(record=lambda *args, **kwargs: None)
    model.passengers = []
    model.passenger_goal_runtimes = {}
    model.spawned_persons = 0
    model.spawned_persons_by_intent = Counter()
    model.spawned_persons_by_entrance = Counter()
    model.frames = []
    model.boarding_doors = []
    model.trains = []
    return model


def test_blocked_entry_admission_has_zero_published_side_effects(monkeypatch) -> None:
    model = _source_policy_model()
    demand = model._alignment_schedule_source_demand("enter_and_board")
    model.alignment_pending_source_demands.append(demand)
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

    assert list(model.alignment_pending_source_demands) == [demand]
    assert tuple(model.passengers) == before["passengers"]
    assert dict(model.passenger_goal_runtimes) == before["goal_runtimes"]
    assert model.spawned_persons == before["spawned"]
    assert dict(model.spawned_persons_by_intent) == before["by_intent"]
    assert dict(model.spawned_persons_by_entrance) == before["by_entrance"]
    assert tuple(model.frames) == before["frames"]


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
    model.alignment_pending_source_demands = deque((first, second))
    model.alignment_requested_source_persons_by_intent["enter_and_board"] = 2
    model.demand_scheduler.due_by_intent = lambda step: Counter()
    attempted: list[int] = []

    def blocked_head(demand):
        attempted.append(demand.sequence_id)

    monkeypatch.setattr(model, "_alignment_source_admission", blocked_head)
    model.spawn_passengers()
    assert attempted == [first.sequence_id]
    assert list(model.alignment_pending_source_demands) == [first, second]

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
    assert list(model.alignment_pending_source_demands) == [first, second]


def test_source_backpressure_does_not_head_block_an_independent_source(
    monkeypatch,
) -> None:
    model = _source_policy_model()
    blocked = model._alignment_schedule_source_demand("enter_and_board")
    independent = replace(
        model._alignment_schedule_source_demand("enter_and_board"),
        source_id="entrance-b",
    )
    model.alignment_pending_source_demands = deque((blocked, independent))
    model.alignment_requested_source_persons_by_intent["enter_and_board"] = 2
    admitted: list[str] = []

    def source_admission(demand):
        if demand.source_id == blocked.source_id:
            return None
        return SourceAdmission((2.0, 2.0), demand.level_id, demand.source_id)

    def spawn_passenger(intent, *, initial_position, initial_level_id):
        admitted.append(independent.source_id)
        model.spawned_persons_by_intent[intent] += 1
        return SimpleNamespace(group_size=1)

    monkeypatch.setattr(model, "_alignment_source_admission", source_admission)
    monkeypatch.setattr(model, "_spawn_passenger", spawn_passenger)

    model.spawn_passengers()

    assert admitted == ["entrance-b"]
    assert list(model.alignment_pending_source_demands) == [blocked]


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
    model.alignment_pending_source_demands.append(demand)
    metrics = model.alignment_source_admission_metrics()
    assert metrics["alignment_pending_entry_groups"] == 1
    assert metrics["alignment_pending_entry_persons"] == model.scenario.group_size
    assert metrics["alignment_entry_demand_conserved"] is True
    assert metrics["alignment_source_demand_conserved"] is True

    model.alignment_pending_source_demands.clear()
    lost_metrics = model.alignment_source_admission_metrics()
    assert lost_metrics["alignment_entry_demand_conserved"] is False
    assert lost_metrics["alignment_source_dropped_persons"] == 1
