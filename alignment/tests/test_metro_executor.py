from __future__ import annotations

from collections import Counter, deque
from dataclasses import replace
from random import Random
from types import SimpleNamespace

import pytest
from metro_station.adapters.simulation.compilation.validation import (
    validate_compiled_station_design,
)
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from shapely.geometry import Polygon

from metro_alignment.metro_executor import (
    AlignmentMesaSimulationExecutor,
    AlignmentMetroStationModel,
    AlignmentSourceGeometryConflict,
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
    model.step_index = 0
    model.pending_alighting_groups = 0
    model.max_pending_alighting_groups = 0
    model.audit = SimpleNamespace(record=lambda *args, **kwargs: None)
    model.jupedsim_walkable_area = lambda level_id: Polygon(
        [(-5.0, 1.0), (5.0, 1.0), (5.0, -20.0), (-5.0, -20.0)]
    )
    model.clamp_position = lambda position: position
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


def test_source_geometry_preflight_detects_queue_lattice_conflict() -> None:
    request, _ = build_metro_request(build_scene_config("platform_boarding"))

    report = alignment_source_geometry_preflight(request.scenario)

    assert report["status"] == "fail"
    assert report["scientific_status"] == "source_geometry_conflict"
    assert report["outcome"] == "model_invalid"
    queue = report["queue_reports"][0]
    assert queue["minimum_body_clearance_m"] == pytest.approx(0.396)
    assert queue["runtime_candidate_spacing_m"] == pytest.approx(0.4)
    assert queue["maximum_candidate_projection_shift_m"] == pytest.approx(0.0)
    assert queue["source_candidate_count"] == 67
    assert queue["unique_source_candidate_count"] == 67
    assert queue["peak_scheduled_alighting_batch"] == 4
    assert queue["holding_area_overlap_candidate_count"] == 60
    assert queue["holding_clearance_overlap_candidate_count"] == 64
    assert queue["boarding_door_axis_overlap_candidate_count"] == 4
    assert queue["capacity_certificate"] is True
    assert queue["capacity_certificate_id"] == (
        "alighting_source:queue_platform_edge_a_down"
    )
    assert queue["compiler_error_codes"] == ["capacity.coactive_slot_conflict"]
    assert queue["compiler_rejection_reproduced"] is True
    assert queue["blockers"] == [
        "boarding_holding_area_overlaps_alighting_source_lattice",
        "boarding_door_axis_overlaps_alighting_source_lattice",
    ]


def test_metro_compiler_rejects_the_current_fingerprint_source_conflict() -> None:
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
    conflicts = tuple(
        item
        for item in compiled.issues
        if item.code == "capacity.coactive_slot_conflict"
    )
    assert len(conflicts) == 1
    assert "queue_platform_edge_a_down" in conflicts[0].message


def test_executor_rejects_source_geometry_before_simulation_run(monkeypatch) -> None:
    executor = AlignmentMesaSimulationExecutor()
    request, _ = build_metro_request(build_scene_config("platform_boarding"))
    monkeypatch.setattr(
        executor,
        "build_model",
        lambda selected_request: (_ for _ in ()).throw(
            AssertionError("model construction must not start")
        ),
    )

    with pytest.raises(AlignmentSourceGeometryConflict) as caught:
        executor.execute(request)

    assert caught.value.report["status"] == "fail"


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
