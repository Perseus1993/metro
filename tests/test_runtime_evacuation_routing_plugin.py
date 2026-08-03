from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from metro_station.adapters.routing_plugins import (
    BaselineEvacuationRouter,
    RoutingPluginProcessHost,
)
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.movement.backend import MovementBackend, MovementResult
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.planning.plan import AgentState, FacilityStage
from metro_station.adapters.simulation.station.evacuation import (
    EVACUATION_MODE,
    EvacuationScenarioConfig,
)
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.application.routing_plugins import RoutingDecisionLog, manifest_from_json


EXAMPLE_DIRECTORY = Path("examples/evacuation_routing_plugin")


class StationaryMovementBackend(MovementBackend):
    def move(self, passenger) -> MovementResult:
        return MovementResult(int(passenger.unique_id), passenger.pos, reached=False)


def _scenario() -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="routing-plugin-test",
        hour=18,
        minutes=2,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="routing-plugin-test",
        sample_hours=1,
        scenario_mode=EVACUATION_MODE,
        evacuation=EvacuationScenarioConfig(initial_platform_persons=1),
        station_design=create_design("visual_demo_station"),
        movement_backend_name="jupedsim",
        simulation_clock_mode="physical",
        goal_graph_mode="active",
        audit_enabled=False,
        audit_print_events=False,
    )


def _route_once(
    model: MetroStationModel,
) -> tuple[tuple[tuple[float, float], ...], tuple[RoutingDecisionLog, ...]]:
    model.spawn_passengers()
    passenger = model.passengers[0]
    upward = [
        facility
        for facility in model.vertical_transports
        if facility.spec.entry_level_id == passenger.current_level_id
    ][-1]
    decision_count = len(model.routing_decision_logs)
    route = model._station_graph_route_to_facility(passenger, upward)
    return route, tuple(model.routing_decision_logs[decision_count:])


def test_builtin_router_is_injected_into_real_evacuation_station_routing() -> None:
    model = MetroStationModel(
        _scenario(),
        seed=42,
        movement_backend=StationaryMovementBackend(),
        routing_algorithm=BaselineEvacuationRouter(),
        routing_parameters={"cost_multiplier": 1.0},
    )

    route, decisions = _route_once(model)

    assert route
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.plugin_id == "metro.shortest_path"
    assert decision.status == "success"
    assert decision.parameters == {"cost_multiplier": 1.0}


def test_external_process_router_is_injected_without_core_imports() -> None:
    manifest = manifest_from_json((EXAMPLE_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
    host = RoutingPluginProcessHost(manifest, working_directory=EXAMPLE_DIRECTORY)
    model = MetroStationModel(
        _scenario(),
        seed=42,
        movement_backend=StationaryMovementBackend(),
        routing_algorithm=host,
    )

    route, decisions = _route_once(model)

    assert route
    assert decisions[0].plugin_id == "example.dijkstra"
    assert decisions[0].status == "success"
    assert host.active_process_count == 0


def test_plugin_intermediate_nodes_only_constrain_physical_route_when_explicitly_anchored(
    monkeypatch,
) -> None:
    model = MetroStationModel(
        _scenario(),
        seed=42,
        movement_backend=StationaryMovementBackend(),
        routing_algorithm=BaselineEvacuationRouter(),
    )
    captured_anchors: list[tuple[tuple[float, float], ...]] = []
    original = model._physical_route_for_points

    def capture(passenger, anchors, *, level_id=None):
        captured_anchors.append(tuple(anchors))
        return original(passenger, anchors, level_id=level_id)

    monkeypatch.setattr(model, "_physical_route_for_points", capture)
    route, decisions = _route_once(model)
    decision = decisions[0]
    intermediate_ids = decision.node_ids[1:-1]
    graph = model.layout_graph.station_graph

    assert route
    assert intermediate_ids
    assert captured_anchors
    semantic_zone_id = next(
        node_id for node_id in intermediate_ids if graph.nodes[node_id].kind == "zone"
    )
    semantic_zone = graph.nodes[semantic_zone_id]
    assert not semantic_zone.tactical_anchor
    assert semantic_zone.position not in captured_anchors[-1]

    graph.nodes[semantic_zone_id] = replace(semantic_zone, tactical_anchor=True)
    rerouted, _decisions = _route_once(model)

    assert rerouted
    assert graph.nodes[semantic_zone_id].position in captured_anchors[-1]


def test_replanning_start_does_not_snap_to_an_unrelated_directed_facility_sink() -> None:
    model = MetroStationModel(
        _scenario(),
        seed=42,
        movement_backend=StationaryMovementBackend(),
        routing_algorithm=BaselineEvacuationRouter(),
    )
    model.spawn_passengers()
    passenger = model.passengers[0]
    graph = model.layout_graph.station_graph
    exit_sink = next(
        node
        for node in graph.nodes.values()
        if node.kind == "facility_entry"
        and node.facility_stage == FacilityStage.EXIT_GATE.value
    )
    upward = next(
        facility
        for facility in model.vertical_transports
        if facility.spec.entry_level_id == exit_sink.level_id
    )
    passenger.pos = exit_sink.position
    passenger.current_level_id = exit_sink.level_id
    passenger.state = AgentState.WALKING_TO_EXIT_GATE.value

    candidates = model._station_graph_route_start_candidates(
        passenger,
        upward,
        graph,
        exit_sink.level_id,
    )

    assert exit_sink not in candidates
    assert graph.nearest_node(passenger.pos, candidates).node_id != exit_sink.node_id
