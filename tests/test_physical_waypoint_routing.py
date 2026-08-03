from __future__ import annotations

from dataclasses import replace
from math import hypot

import pytest
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from metro_station.adapters.routing_plugins import BaselineEvacuationRouter
from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.design import create_design
from metro_station.adapters.simulation.design.station_generation import with_generated_queues
from metro_station.adapters.simulation.facilities.process import FacilityKind
from metro_station.adapters.simulation.planning.plan import AgentIntent, RouteKey
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.runtime.physical_waypoint_routing import (
    PhysicalRouteUnreachableError,
    PhysicalWaypointRouter,
)
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_testkit.instant_movement_backend import InstantMovementBackend


def _model(
    template_id: str = "visual_demo_station",
    *,
    routing_algorithm=None,
    station_design=None,
) -> MetroStationModel:
    scenario = StationSandboxScenario(
        station_name="physical-waypoint-routing-test",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="unit",
        sample_hours=1,
        station_design=station_design or create_design(template_id),
        audit_enabled=False,
        audit_print_events=False,
    )
    return MetroStationModel(
        scenario,
        seed=7,
        movement_backend=InstantMovementBackend(),
        routing_algorithm=routing_algorithm,
    )


def test_rotated_rect_connector_changes_physical_portal_and_queue_axis() -> None:
    base_design = create_design("two_level_island_platform")
    rotated_without_stale_queue = replace(
        base_design,
        elements=tuple(
            replace(
                element,
                geometry=replace(element.geometry, rotation_deg=90.0),
            )
            if element.id == "up_escalator_a"
            else element
            for element in base_design.elements
        ),
        queues=tuple(
            queue
            for queue in base_design.queues
            if queue.owner_element_id != "up_escalator_a"
        ),
    )
    rotated_design = replace(
        rotated_without_stale_queue,
        queues=with_generated_queues(rotated_without_stale_queue),
    )
    baseline = _model(
        "two_level_island_platform",
        station_design=base_design,
    )
    rotated = _model(
        "two_level_island_platform",
        station_design=rotated_design,
    )
    baseline_facility = next(
        facility
        for facility in baseline.vertical_transports
        if facility.spec.source_element_id == "up_escalator_a"
        and facility.spec.direction == "up"
    )
    rotated_facility = next(
        facility
        for facility in rotated.vertical_transports
        if facility.spec.source_element_id == "up_escalator_a"
        and facility.spec.direction == "up"
    )

    assert rotated_facility.spec.position != pytest.approx(
        baseline_facility.spec.position
    )
    assert (
        rotated_facility.spec.queue_layout.slots[:2]
        != baseline_facility.spec.queue_layout.slots[:2]
    )
    entry_area = rotated.jupedsim_walkable_area(
        rotated_facility.spec.entry_level_id
    )
    assert entry_area.buffer(1e-7).covers(Point(rotated_facility.spec.position))
    assert all(
        entry_area.buffer(1e-7).covers(Point(slot))
        for slot in rotated_facility.spec.queue_layout.slots
    )


def test_navigation_mesh_route_detours_around_blocking_geometry() -> None:
    walkable = Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        holes=[[(4.0, 0.0), (6.0, 0.0), (6.0, 8.0), (4.0, 8.0)]],
    )

    route = PhysicalWaypointRouter().route(
        walkable,
        (2.0, 5.0),
        ((8.0, 5.0),),
        level_id="concourse",
        clearance=0.1,
    )

    assert len(route) >= 3
    assert route[-1] == pytest.approx((8.0, 5.0))
    assert walkable.buffer(1e-7).covers(LineString(((2.0, 5.0), *route)))


def test_unreachable_or_outside_physical_target_fails_explicitly() -> None:
    disconnected = MultiPolygon(
        [
            Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]),
            Polygon([(4.0, 0.0), (6.0, 0.0), (6.0, 2.0), (4.0, 2.0)]),
        ]
    )
    router = PhysicalWaypointRouter()

    with pytest.raises(PhysicalRouteUnreachableError, match="connected walking domain"):
        router.route(
            disconnected,
            (1.0, 1.0),
            ((5.0, 1.0),),
            level_id="concourse",
            clearance=0.1,
        )

    with pytest.raises(PhysicalRouteUnreachableError, match="outside the walkable area"):
        router.route(
            Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]),
            (1.0, 1.0),
            ((5.0, 1.0),),
            level_id="concourse",
            clearance=0.1,
        )


def test_facility_queue_route_is_walkable_and_gate_portals_face_forward() -> None:
    model = _model()
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    passenger.current_level_id = "b1_concourse"
    passenger.pos = (10.0, 10.0)
    facility = getattr(model, "gates")[0]

    route = model.route_to_facility_queue(passenger, facility)
    portals = model._facility_portals(passenger, facility)
    walkable = model.jupedsim_walkable_area(passenger.current_level_id)

    assert route
    assert route[-1] == pytest.approx(portals.approach)
    assert all(walkable.covers(Point(point)) for point in route)
    assert walkable.buffer(1e-7).covers(LineString((passenger.pos, *route)))
    approach_to_entry = (
        portals.entry[0] - portals.approach[0],
        portals.entry[1] - portals.approach[1],
    )
    entry_to_exit = (
        portals.exit[0] - portals.entry[0],
        portals.exit[1] - portals.entry[1],
    )
    assert approach_to_entry[0] * entry_to_exit[0] + approach_to_entry[1] * entry_to_exit[1] > 0
    assert hypot(*approach_to_entry) > 0


def test_topology_level_change_is_not_accepted_as_a_walking_route() -> None:
    model = _model()
    graph = getattr(model, "layout_graph").station_graph
    facility = next(
        item for item in getattr(model, "vertical_transports") if item.spec.direction == "down"
    )
    element_id = facility.spec.source_element_id
    assert element_id is not None
    start_node_id = f"vertical:{element_id}:{facility.spec.entry_level_id}"
    exit_node_id = f"vertical:{element_id}:{facility.spec.exit_level_id}"

    with pytest.raises(PhysicalRouteUnreachableError, match="without a facility portal"):
        model._same_level_topology_target(
            graph,
            start_node_id,
            (exit_node_id,),
            facility.spec.entry_level_id,
        )


@pytest.mark.parametrize(
    "template_id",
    (
        "single_level_terminal",
        "two_level_island_platform",
        "three_level_transfer",
        "visual_demo_station",
    ),
)
def test_compiled_facility_portals_belong_to_their_declared_levels(
    template_id: str,
) -> None:
    model = _model(template_id)
    vertical_kinds = {
        FacilityKind.ESCALATOR.value,
        FacilityKind.ELEVATOR.value,
        FacilityKind.STAIRS.value,
    }

    for facility in getattr(model, "facilities"):
        entry_area = model.jupedsim_walkable_area(facility.spec.entry_level_id)
        exit_area = model.jupedsim_walkable_area(facility.spec.exit_level_id)
        assert entry_area.buffer(1e-7).covers(Point(facility.spec.position))
        assert exit_area.buffer(1e-7).covers(Point(facility.spec.exit_position))
        assert all(entry_area.buffer(1e-7).covers(Point(slot)) for slot in facility.spec.queue_layout.slots)
        if facility.spec.entry_level_id != facility.spec.exit_level_id:
            assert facility.spec.kind in vertical_kinds


def test_semantic_route_keys_resolve_to_same_level_walkable_waypoints() -> None:
    model = _model()
    graph = getattr(model, "layout_graph").station_graph
    gate = getattr(model, "gates")[0]
    downward = next(
        item for item in getattr(model, "vertical_transports") if item.spec.direction == "down"
    )
    upward = next(
        item for item in getattr(model, "vertical_transports") if item.spec.direction == "up"
    )
    platform = graph.nodes_matching(kind="platform")[0]
    entrance = graph.nodes_matching(kind="entrance")[0]
    cases = (
        (RouteKey.ENTRY_GATE_DECISION, entrance.level_id, entrance.position),
        (RouteKey.AFTER_GATE, gate.spec.exit_level_id, gate.spec.exit_position),
        (
            RouteKey.AFTER_VERTICAL,
            downward.spec.exit_level_id,
            downward.spec.exit_position,
        ),
        (RouteKey.PLATFORM_TO_VERTICAL, platform.level_id, platform.position),
        (
            RouteKey.AFTER_EXIT_VERTICAL,
            upward.spec.exit_level_id,
            upward.spec.exit_position,
        ),
    )

    for route_key, level_id, position in cases:
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        passenger.pos = position
        passenger.current_level_id = level_id
        passenger.assigned_line_id = "default"
        passenger.assigned_direction = "down"
        route = model.route_for_key(route_key, passenger)
        walkable = model.jupedsim_walkable_area(level_id)

        assert route
        assert all(walkable.covers(Point(point)) for point in route)
        assert walkable.buffer(1e-7).covers(LineString((position, *route)))


def test_facility_walking_route_does_not_invoke_evacuation_plugin() -> None:
    model = _model(routing_algorithm=BaselineEvacuationRouter())
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.EVACUATE_STATION,
    )
    facility = next(
        item
        for item in getattr(model, "vertical_transports")
        if item.spec.entry_level_id == passenger.current_level_id
    )
    decision_count = len(getattr(model, "routing_decision_logs"))

    route = model.facility_walking_route(passenger, facility)

    assert route
    assert len(getattr(model, "routing_decision_logs")) == decision_count


def test_every_selectable_facility_has_a_walkable_approach_route() -> None:
    model = _model()

    for facility in getattr(model, "facilities"):
        walkable = model.jupedsim_walkable_area(facility.spec.entry_level_id)
        start = walkable.representative_point()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        passenger.current_level_id = facility.spec.entry_level_id
        passenger.pos = (float(start.x), float(start.y))

        route = model.facility_walking_route(passenger, facility)

        assert route, facility.facility_id
        assert all(walkable.covers(Point(point)) for point in route), facility.facility_id
        assert walkable.buffer(1e-7).covers(
            LineString((passenger.pos, *route))
        ), facility.facility_id


def test_all_gate_approach_portals_face_the_service_exit() -> None:
    model = _model()
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )

    for facility in (*getattr(model, "gates"), *getattr(model, "exit_gates")):
        passenger.current_level_id = facility.spec.entry_level_id
        portals = model._facility_portals(passenger, facility)
        approach_to_entry = (
            portals.entry[0] - portals.approach[0],
            portals.entry[1] - portals.approach[1],
        )
        entry_to_exit = (
            portals.exit[0] - portals.entry[0],
            portals.exit[1] - portals.entry[1],
        )

        assert hypot(*approach_to_entry) > 0, facility.facility_id
        assert (
            approach_to_entry[0] * entry_to_exit[0]
            + approach_to_entry[1] * entry_to_exit[1]
            > 0
        ), facility.facility_id
