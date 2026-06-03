from __future__ import annotations

import unittest
from random import Random
from dataclasses import replace
from types import SimpleNamespace

from shapely.geometry import LineString, Point

from sandbox.metro_station_sandbox.planning.plan import (
    AgentIntent,
    AgentState,
    FacilityStage,
    RouteKey,
)
from sandbox.metro_station_sandbox.agents import PassengerAgent
from sandbox.metro_station_sandbox.planning.behavior import (
    BehaviorActionKind,
    behavior_status_for_passenger,
)
from sandbox.metro_station_sandbox.design import (
    DesignConnection,
    DesignPort,
    StationDesignDocument,
    apply_react_flow_edges,
    create_design,
    to_react_flow,
    validate_design,
)
from sandbox.metro_station_sandbox.design_inspector.server import (
    build_design_payload,
    compile_react_flow_payload,
    template_catalog_payload,
)
from sandbox.metro_station_sandbox.station.payload import geometry_payload
from sandbox.metro_station_sandbox.facilities.filters import (
    filter_boarding_doors_for_passenger,
    filter_platforms_for_passenger,
)
from sandbox.metro_station_sandbox.facilities.process import QueueLayout
from sandbox.metro_station_sandbox.facilities.runtime import (
    BoardingDoorProcessAgent,
    ElevatorProcessAgent,
    EscalatorProcessAgent,
    FacilityProcessAgent,
    GateProcessAgent,
    StairsProcessAgent,
)
from sandbox.metro_station_sandbox.movement.jps_adapter import JuPedSimAdapter
from sandbox.metro_station_sandbox.movement.backend import (
    BatchedJuPedSimMovementBackend,
    MovementBackend,
    MovementResult,
)
from sandbox.metro_station_sandbox.planning.selection import pick_least_loaded, pick_logit
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel
from sandbox.metro_station_sandbox.station.graph import StationGraph
from sandbox.metro_station_sandbox.station.geometry import (
    document_walkable_geometry,
    level_walkable_geometry,
)
from sandbox.metro_station_sandbox.station.scenario import StationSandboxScenario
from sandbox.metro_station_sandbox.visual_demo.geometry import load_station_geometry, meters
from sandbox.metro_station_sandbox.visual_demo.layout import layout_payload
from sandbox.metro_station_sandbox.visual_demo.field_routing import (
    QueueAttractivenessField,
    QueueFieldCandidate,
)
from sandbox.metro_station_sandbox.visual_demo.floor_field import GridFloorField
from sandbox.metro_station_sandbox.visual_demo.generate_jps_tracks import (
    ENTRY_GATE_PORTAL_RADIUS_M,
    POST_GATE_RADIUS_M,
    post_gate_portal_radius,
    queue_field_switching_is_enabled,
)
from sandbox.metro_station_sandbox.visual_demo.queue_runtime import (
    QUEUE_CAPTURE_APRONS_N,
    NativeQueueRuntime,
)
from sandbox.metro_station_sandbox.visual_demo.mesa_export import mesa_frames_to_visual_tracks
from sandbox.metro_station_sandbox.visual_demo.region_flow import (
    build_point_capture_flow,
    build_region_capture_flow,
)
from sandbox.metro_station_sandbox.visual_demo.specs import FACILITY_QUEUES, GATE_QUEUE_SPECS


class InstantMovementBackend(MovementBackend):
    def move(self, passenger: PassengerAgent) -> MovementResult:
        return MovementResult(passenger.unique_id, passenger.target, reached=True)


def scenario_for(template_id: str, *, minutes: int = 1, admins: int = 0) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="unit_test",
        hour=18,
        minutes=minutes,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=1,
        exit_count_hour=1,
        source_label="unit",
        sample_hours=1,
        station_design=create_design(template_id),
        audit_enabled=False,
        audit_print_events=False,
        admin_agent_count=admins,
    )


class VisualExportPayloadTests(unittest.TestCase):
    def test_export_includes_scenario_and_train_context(self) -> None:
        scenario = scenario_for("visual_demo_station", minutes=2)
        frames = [
            {
                "time_seconds": 0.0,
                "passengers": [],
                "trains": [
                    {
                        "id": 1,
                        "line_id": "default",
                        "direction": "down",
                        "platform_id": "platform:default:down",
                        "state": "away",
                        "current_load_persons": 0,
                        "last_departed_load_persons": 0,
                        "departure_elapsed_seconds": None,
                        "departed_trains": 0,
                    }
                ],
                "metrics": {
                    "station_persons": 0,
                    "movement_backend": "UnitMovementBackend",
                    "jupedsim_operational_model": "collision_free_speed",
                },
            }
        ]

        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=[],
        )

        self.assertEqual("unit_test", payload["scenario"]["station_name"])
        self.assertEqual(18 * 3600, payload["scenario"]["clock_start_seconds"])
        self.assertEqual("UnitMovementBackend", payload["scenario"]["movement_backend"])
        self.assertEqual(240, payload["train_service"]["headway_seconds"])
        self.assertEqual("away", payload["train_samples"][0]["trains"][0]["state"])


class StationGraphTests(unittest.TestCase):
    def test_templates_validate_and_compile_without_graph_fallbacks(self) -> None:
        for template_id in (
            "single_level_terminal",
            "two_level_island_platform",
            "three_level_transfer",
            "visual_demo_station",
        ):
            with self.subTest(template_id=template_id):
                document = create_design(template_id)
                issues = validate_design(document)
                self.assertEqual([], [issue.as_dict() for issue in issues])
                graph = StationGraph.from_design(document)
                self.assertGreater(len(graph.nodes), 0)
                self.assertGreater(len(graph.edges), 0)
                self.assertEqual([], [item.as_dict() for item in graph.compile_diagnostics])
                self.assertFalse(
                    any(edge.origin == "walkable_access_fallback" for edge in graph.edges)
                )

    def test_template_gate_ports_are_directional(self) -> None:
        document = create_design("single_level_terminal")
        gate = document.element_by_id()["gate_bank_a"]
        ports_by_id = {port.id: port for port in gate.ports}
        entrance_to_gate = next(
            connection
            for connection in document.connections
            if connection.id == "conn_entrance_to_gates"
        )
        gate_to_boarding = next(
            connection
            for connection in document.connections
            if connection.id == "conn_gate_to_boarding"
        )

        self.assertEqual("in", ports_by_id["service"].direction)
        self.assertEqual("out", ports_by_id["release"].direction)
        self.assertEqual("out", ports_by_id["unpaid"].direction)
        self.assertEqual("service", entrance_to_gate.target_port_id)
        self.assertFalse(entrance_to_gate.bidirectional)
        self.assertEqual("release", gate_to_boarding.source_port_id)
        self.assertFalse(gate_to_boarding.bidirectional)

    def test_validation_reports_missing_explicit_connection(self) -> None:
        document = create_design("single_level_terminal")
        broken = replace(
            document,
            connections=tuple(
                connection
                for connection in document.connections
                if connection.id != "conn_gate_to_boarding"
            ),
        )
        issue_codes = {issue.code for issue in validate_design(broken)}
        self.assertIn("graph.enter_path_missing", issue_codes)

    def test_route_uses_current_level_for_overlapping_vertical_nodes(self) -> None:
        graph = StationGraph.from_design(create_design("three_level_transfer"))
        current_position = graph.nodes["vertical:down_escalator_a:b2_transfer"].position
        nearest_on_level = graph.nearest_node(
            current_position,
            graph.nodes_matching(level_id="b2_transfer"),
        )
        self.assertEqual("vertical:down_escalator_a:b2_transfer", nearest_on_level.node_id)
        route = graph.route_from_position_to(
            current_position,
            kind="facility_entry",
            facility_stage="vertical_transfer",
            direction="down",
            start_level_id="b2_transfer",
        )
        self.assertTrue(route)

    def test_vertical_direction_can_fall_back_to_chinese_labels(self) -> None:
        document = create_design("two_level_island_platform")
        document = replace(
            document,
            elements=tuple(
                replace(element, label="下行扶梯 A", direction=None, metadata={})
                if element.id == "down_escalator_a"
                else replace(element, label="上行扶梯 A", direction=None, metadata={})
                if element.id == "up_escalator_a"
                else element
                for element in document.elements
            ),
        )
        graph = StationGraph.from_design(document)

        self.assertEqual(
            "down",
            graph.nodes["vertical:down_escalator_a:b1_concourse"].direction,
        )
        self.assertEqual(
            "up",
            graph.nodes["vertical:up_escalator_a:b1_concourse"].direction,
        )

    def test_design_ports_round_trip_and_project_to_react_flow_handles(self) -> None:
        document = create_design("single_level_terminal")
        elements = tuple(
            replace(
                element,
                ports=(
                    *element.ports,
                    DesignPort(
                        "public_exit",
                        "walk",
                        level_id="l1_terminal",
                        position_m=(6.0, 22.5),
                    ),
                ),
            )
            if element.id == "entrance_a"
            else replace(
                element,
                ports=(
                    *element.ports,
                    DesignPort(
                        "hall_entry",
                        "walk",
                        level_id="l1_terminal",
                        position_m=(10.0, 22.5),
                    ),
                ),
            )
            if element.id == "main_hall"
            else element
            for element in document.elements
        )
        connections = tuple(
            replace(
                connection,
                source_port_id="public_exit",
                target_port_id="hall_entry",
            )
            if connection.id == "conn_entrance_to_hall"
            else connection
            for connection in document.connections
        )
        document = replace(document, elements=elements, connections=connections)

        self.assertEqual([], [issue.as_dict() for issue in validate_design(document)])

        round_tripped = StationDesignDocument.from_dict(document.as_dict())
        self.assertTrue(
            any(port.id == "public_exit" for port in round_tripped.elements[1].ports)
        )
        flow = to_react_flow(round_tripped)
        edge = next(edge for edge in flow["edges"] if edge["id"] == "edge:conn_entrance_to_hall")

        self.assertEqual("public_exit", edge["sourceHandle"])
        self.assertEqual("hall_entry", edge["targetHandle"])

        applied = apply_react_flow_edges(round_tripped, flow["edges"])
        applied_connection = next(
            connection
            for connection in applied.connections
            if connection.id == "conn_entrance_to_hall"
        )
        self.assertEqual("public_exit", applied_connection.source_port_id)
        self.assertEqual("hall_entry", applied_connection.target_port_id)

    def test_design_inspector_reports_clean_template_compile(self) -> None:
        catalog = template_catalog_payload()
        self.assertIn("xyflow / React Flow", [item["name"] for item in catalog["reference_wheels"]])
        self.assertIn("equipment", [item["id"] for item in catalog["component_palette"]])

        payload = build_design_payload("single_level_terminal")
        self.assertEqual("ok", payload["summary"]["status"])
        self.assertEqual(0, payload["summary"]["fallback_edges"])
        self.assertGreater(len(payload["react_flow"]["nodes"]), 0)
        self.assertTrue(
            any(node.get("data", {}).get("ports") for node in payload["react_flow"]["nodes"])
        )

    def test_design_inspector_compile_accepts_dropped_component_node(self) -> None:
        payload = build_design_payload("single_level_terminal")
        level_node = next(
            node for node in payload["react_flow"]["nodes"] if node["id"].startswith("level:")
        )
        draft_node = {
            "id": "element:draft_equipment_test",
            "type": "facilityNode",
            "parentId": level_node["id"],
            "position": {"x": 42.0, "y": 16.0},
            "width": 4.0,
            "height": 3.0,
            "style": {"width": 4.0, "height": 3.0},
            "data": {
                "inspector_created": True,
                "palette_id": "equipment",
                "kind": "equipment",
                "level_id": level_node["data"]["level_id"],
                "role": "facility",
                "label": "Equipment",
                "geometry": {
                    "shape": "rect",
                    "x_m": 42.0,
                    "y_m": 16.0,
                    "width_m": 4.0,
                    "height_m": 3.0,
                    "rotation_deg": 0.0,
                    "points_m": [],
                },
                "metadata": {"inspector_created": True},
            },
        }

        draft = compile_react_flow_payload(
            {
                "template_id": "single_level_terminal",
                "nodes": [*payload["react_flow"]["nodes"], draft_node],
                "edges": payload["react_flow"]["edges"],
            }
        )
        elements_by_id = {
            element["id"]: element for element in draft["document"]["elements"]
        }

        self.assertIn("draft_equipment_test", elements_by_id)
        self.assertEqual("equipment", elements_by_id["draft_equipment_test"]["kind"])
        self.assertEqual(
            {"x_m": 42.0, "y_m": 16.0, "width_m": 4.0, "height_m": 3.0},
            {
                key: elements_by_id["draft_equipment_test"]["geometry"][key]
                for key in ("x_m", "y_m", "width_m", "height_m")
            },
        )

    def test_design_inspector_compile_exposes_broken_edge_state(self) -> None:
        payload = build_design_payload("single_level_terminal")
        draft = compile_react_flow_payload(
            {
                "template_id": "single_level_terminal",
                "nodes": payload["react_flow"]["nodes"],
                "edges": [],
            }
        )
        issue_codes = {issue["code"] for issue in draft["validation_issues"]}

        self.assertEqual("error", draft["summary"]["status"])
        self.assertIn("graph.enter_path_missing", issue_codes)
        self.assertGreater(draft["summary"]["fallback_edges"], 0)

    def test_graph_marks_legacy_endpoint_inference_and_walkable_fallback(self) -> None:
        document = create_design("single_level_terminal")
        legacy_document = replace(
            document,
            elements=tuple(replace(element, ports=()) for element in document.elements),
            connections=tuple(
                replace(connection, source_port_id=None, target_port_id=None)
                for connection in document.connections
                if not connection.id.startswith("conn_access_")
            ),
        )
        graph = StationGraph.from_design(legacy_document)
        diagnostic_codes = {diagnostic.code for diagnostic in graph.compile_diagnostics}
        fallback_edges = [
            edge for edge in graph.edges if edge.origin == "walkable_access_fallback"
        ]

        self.assertIn("graph.connection_endpoint_inferred", diagnostic_codes)
        self.assertIn("graph.same_level_access_fallback", diagnostic_codes)
        self.assertTrue(fallback_edges)
        self.assertTrue(
            all(
                edge.detail_id is not None
                for edge in graph.edges
                if edge.origin == "design_connection"
            )
        )

    def test_graph_uses_explicit_port_refs_without_endpoint_inference(self) -> None:
        document = create_design("single_level_terminal")
        elements = tuple(
            replace(
                element,
                ports=(
                    *element.ports,
                    DesignPort("public_exit", "walk", level_id="l1_terminal"),
                ),
            )
            if element.id == "entrance_a"
            else replace(
                element,
                ports=(
                    *element.ports,
                    DesignPort("hall_entry", "walk", level_id="l1_terminal"),
                ),
            )
            if element.id == "main_hall"
            else element
            for element in document.elements
        )
        connections = tuple(
            replace(
                connection,
                source_port_id="public_exit",
                target_port_id="hall_entry",
            )
            if connection.id == "conn_entrance_to_hall"
            else connection
            for connection in document.connections
        )
        graph = StationGraph.from_design(
            replace(document, elements=elements, connections=connections)
        )
        connection_diagnostics = [
            diagnostic
            for diagnostic in graph.compile_diagnostics
            if diagnostic.connection_id == "conn_entrance_to_hall"
        ]
        connection_edges = [
            edge for edge in graph.edges if edge.detail_id == "conn_entrance_to_hall"
        ]

        self.assertNotIn(
            "graph.connection_endpoint_inferred",
            {diagnostic.code for diagnostic in connection_diagnostics},
        )
        self.assertTrue(connection_edges)
        self.assertTrue(all(edge.origin == "design_connection" for edge in connection_edges))

    def test_validation_reports_invalid_design_port_references(self) -> None:
        document = create_design("single_level_terminal")
        elements = tuple(
            replace(
                element,
                ports=(
                    DesignPort(
                        "entry_only",
                        "walk",
                        direction="in",
                        level_id="l1_terminal",
                    ),
                ),
            )
            if element.id == "entrance_a"
            else element
            for element in document.elements
        )
        connections = (
            DesignConnection(
                "conn_bad_port",
                "entrance_a",
                "main_hall",
                "walk",
                bidirectional=False,
                source_port_id="entry_only",
                target_port_id="missing",
            ),
        )
        document = replace(document, elements=elements, connections=connections)
        issue_codes = {issue.code for issue in validate_design(document)}

        self.assertIn("connections.source_port_not_output", issue_codes)
        self.assertIn("connections.unknown_target_port", issue_codes)


class PassengerFlowTests(unittest.TestCase):
    def test_visual_demo_initial_positions_stay_on_intent_level(self) -> None:
        scenario = scenario_for("visual_demo_station")
        model = MetroStationModel(
            scenario,
            seed=13,
            movement_backend=InstantMovementBackend(),
        )
        document = scenario.station_design
        self.assertIsNotNone(document)
        assert document is not None
        walkable = document_walkable_geometry(document)
        b1_domain = level_walkable_geometry(document, "b1_concourse", walkable)
        b2_domain = level_walkable_geometry(document, "b2_platform", walkable)
        b2_platform_y = document.constraints.canvas_height_m * 0.60

        entry_passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(8)
        ]
        exit_passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.EXIT_STATION,
            )
            for _ in range(8)
        ]

        self.assertTrue(all(item.current_level_id == "b1_concourse" for item in entry_passengers))
        self.assertTrue(all(b1_domain.covers(Point(item.pos)) for item in entry_passengers))
        self.assertTrue(all(item.current_level_id == "b2_platform" for item in exit_passengers))
        self.assertTrue(all(b2_domain.covers(Point(item.pos)) for item in exit_passengers))
        self.assertTrue(all(item.pos[1] >= b2_platform_y for item in exit_passengers))

    def test_jupedsim_walkable_area_can_be_scoped_to_level(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=14,
            movement_backend=InstantMovementBackend(),
        )

        platform_point = Point(meters((0.251, 0.785)))

        self.assertTrue(model.jupedsim_walkable_area().covers(platform_point))
        self.assertFalse(model.jupedsim_walkable_area("b1_concourse").covers(platform_point))
        self.assertTrue(model.jupedsim_walkable_area("b2_platform").covers(platform_point))

    def test_behavior_status_describes_region_goal_and_queue_mode(self) -> None:
        model = MetroStationModel(scenario_for("single_level_terminal"), seed=11)
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )

        initial = behavior_status_for_passenger(passenger)
        self.assertEqual(BehaviorActionKind.WALK_TO_REGION.value, initial.action)
        self.assertEqual("station_entrance", initial.region_goal.origin_region)
        self.assertEqual("train_interior", initial.region_goal.destination_region)

        model.gates[0].join_queue(passenger)
        queued = behavior_status_for_passenger(passenger)
        self.assertEqual(BehaviorActionKind.WAIT_IN_QUEUE.value, queued.action)
        self.assertEqual("enqueued", queued.queue_mode)
        self.assertEqual("entry_gate", queued.facility_stage)

    def test_three_level_exit_station_completes_without_boarding(self) -> None:
        scenario = scenario_for("three_level_transfer")
        model = MetroStationModel(scenario, seed=7)
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EXIT_STATION,
        )
        model.passengers.append(passenger)

        for _ in range(220):
            model.step()
            if passenger.state == AgentState.DEPARTED.value:
                break

        self.assertEqual(AgentState.DEPARTED.value, passenger.state)
        self.assertEqual(0, model.boarded_persons)
        self.assertEqual(1, sum(gate.served_persons for gate in model.exit_gates))

    def test_single_platform_transfer_selects_platform_and_boards(self) -> None:
        scenario = scenario_for("two_level_island_platform")
        model = MetroStationModel(scenario, seed=9)
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.TRANSFER,
        )
        model.passengers.append(passenger)

        for _ in range(220):
            model.step()
            if passenger.state == AgentState.DEPARTED.value:
                break

        self.assertEqual(AgentState.DEPARTED.value, passenger.state)
        self.assertEqual("platform:default:down", passenger.assigned_platform_id)
        self.assertEqual(1, model.boarded_persons)


class IntegrationSurfaceTests(unittest.TestCase):
    def test_render_payload_includes_compiled_station_graph(self) -> None:
        payload = geometry_payload(scenario_for("single_level_terminal"))
        self.assertEqual("design_document", payload["source"])
        self.assertTrue(payload["graph_nodes"])
        self.assertTrue(payload["graph_edges"])
        self.assertTrue(any(edge["kind"] == "service" for edge in payload["graph_edges"]))

    def test_jupedsim_backend_name_maps_to_batched_backend_when_available(self) -> None:
        scenario = replace(scenario_for("single_level_terminal"), movement_backend_name="jupedsim")
        model = MetroStationModel(scenario, seed=3)
        if model.jupedsim.status.available:
            self.assertIsInstance(model.movement_backend, BatchedJuPedSimMovementBackend)
        else:
            self.assertNotIsInstance(model.movement_backend, BatchedJuPedSimMovementBackend)

    def test_jupedsim_social_force_tick_moves_agent_when_available(self) -> None:
        adapter = JuPedSimAdapter()
        if not adapter.status.available:
            self.skipTest(adapter.status.message)

        positions = adapter.simulate_walk_tick(
            starts=[(1.0, 2.5)],
            target=(9.0, 2.5),
            width=10.0,
            height=5.0,
            iterations=150,
            radius=0.18,
            target_radius=0.45,
            operational_model="social_force",
        )

        self.assertEqual(1, len(positions))
        self.assertGreater(positions[0][0], 1.5)
        self.assertAlmostEqual(2.5, positions[0][1], delta=0.2)

    def test_frame_metrics_include_jupedsim_operational_model(self) -> None:
        scenario = replace(
            scenario_for("single_level_terminal"),
            jupedsim_operational_model="social_force",
        )
        model = MetroStationModel(scenario, seed=3)
        frame = model.snapshot()

        self.assertEqual("social_force", frame["metrics"]["jupedsim_operational_model"])

    def test_admin_agent_uses_staff_policy_surface(self) -> None:
        model = MetroStationModel(scenario_for("single_level_terminal", admins=1), seed=5)
        self.assertEqual(1, len(model.admin_agents))
        self.assertTrue(hasattr(model.facility_choice_policy, "guide_passenger"))

    def test_spawn_schedule_includes_entry_and_exit_demands(self) -> None:
        scenario = replace(
            scenario_for("visual_demo_station", minutes=5),
            entry_count_hour=12,
            exit_count_hour=12,
        )
        model = MetroStationModel(scenario, seed=4)

        entry_groups = sum(
            due.get(AgentIntent.ENTER_AND_BOARD.value, 0) for due in model.spawn_schedule.values()
        )
        exit_groups = sum(
            due.get(AgentIntent.EXIT_STATION.value, 0) for due in model.spawn_schedule.values()
        )

        self.assertEqual(1, entry_groups)
        self.assertEqual(1, exit_groups)

    def test_facility_specs_instantiate_concrete_runtime_classes(self) -> None:
        model = MetroStationModel(scenario_for("two_level_island_platform"), seed=4)

        self.assertTrue(
            all(isinstance(facility, FacilityProcessAgent) for facility in model.facilities)
        )
        self.assertTrue(all(isinstance(gate, GateProcessAgent) for gate in model.gates))
        self.assertTrue(all(isinstance(gate, GateProcessAgent) for gate in model.exit_gates))
        self.assertTrue(
            any(
                isinstance(transport, EscalatorProcessAgent)
                for transport in model.vertical_transports
            )
        )
        self.assertTrue(
            any(
                isinstance(transport, ElevatorProcessAgent)
                for transport in model.vertical_transports
            )
        )
        self.assertTrue(
            any(
                isinstance(transport, StairsProcessAgent)
                for transport in model.vertical_transports
            )
        )
        self.assertTrue(
            all(isinstance(door, BoardingDoorProcessAgent) for door in model.boarding_doors)
        )
        with self.assertRaises(TypeError):
            FacilityProcessAgent(model, spec=model.gates[0].spec)

    def test_elevator_runtime_batches_passengers_by_cabin_cycle(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            elevator_cabin_capacity_persons=2,
            elevator_cycle_seconds=20.0,
        )
        model = MetroStationModel(scenario, seed=8, movement_backend=InstantMovementBackend())
        elevator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, ElevatorProcessAgent)
        )
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(3)
        ]
        model.passengers.extend(passengers)
        for passenger in passengers:
            elevator.join_queue(passenger)

        elevator.step()

        self.assertEqual(1, len(elevator.queue))
        self.assertEqual(2, elevator.cabin_load_persons)
        self.assertEqual(0, elevator.served_persons)
        self.assertEqual(0, elevator.departed_cabins)
        self.assertEqual("boarding", elevator.cabin_state)

        elevator.step()

        self.assertEqual(1, len(elevator.queue))
        self.assertEqual(2, elevator.served_persons)
        self.assertEqual(1, elevator.departed_cabins)
        self.assertEqual("moving", elevator.cabin_state)

        for _ in range(elevator.cycle_steps):
            elevator.step()

        self.assertEqual(0, len(elevator.queue))
        self.assertEqual(1, elevator.cabin_load_persons)
        self.assertEqual(2, elevator.served_persons)
        self.assertEqual(1, elevator.departed_cabins)
        self.assertEqual("boarding", elevator.cabin_state)

        elevator.step()

        self.assertEqual(3, elevator.served_persons)
        self.assertEqual(2, elevator.departed_cabins)
        self.assertEqual("moving", elevator.cabin_state)


class ExtractedUtilityTests(unittest.TestCase):
    def test_logit_picker_prefers_lower_generalized_cost(self) -> None:
        picks = [
            pick_logit(
                ["cheap", "expensive"],
                Random(seed),
                lambda item: 0.0 if item == "cheap" else 10.0,
                sensitivity=2.0,
            )
            for seed in range(20)
        ]

        self.assertEqual(["cheap"] * 20, picks)

    def test_progress_monitor_replans_overdue_queue_to_alternative_facility(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            audit_enabled=True,
            audit_print_events=False,
            queue_replan_wait_seconds=5.0,
        )
        model = MetroStationModel(scenario, seed=13)
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        model.vertical_transports[0].join_queue(passenger)
        old_facility_id = passenger.assigned_facility_id

        model.progress_monitor.observe(model, [passenger])
        model.step_index = 2
        model.progress_monitor.observe(model, [passenger])

        self.assertNotEqual(old_facility_id, passenger.assigned_facility_id)
        self.assertNotIn(passenger, model.facilities_by_id[old_facility_id].queue)
        self.assertIn("passenger_replanned_facility", model.audit.summary())
        self.assertEqual("queue_wait_timeout", passenger.last_replan_reason)

    def test_boarding_door_filter_prefers_assigned_platform(self) -> None:
        passenger = SimpleNamespace(
            assigned_platform_id="platform:a:down",
            assigned_line_id="a",
            assigned_direction="down",
        )
        matching = SimpleNamespace(
            spec=SimpleNamespace(
                platform_id="platform:a:down",
                line_id="a",
                direction="down",
                entry_level_id=None,
            )
        )
        other = SimpleNamespace(
            spec=SimpleNamespace(
                platform_id="platform:b:up",
                line_id="b",
                direction="up",
                entry_level_id=None,
            )
        )

        self.assertEqual(
            [matching], filter_boarding_doors_for_passenger(passenger, [other, matching])
        )

    def test_platform_filter_and_least_loaded_picker_share_tie_breaking(self) -> None:
        passenger = SimpleNamespace(target_line_id="line_2", target_direction="up")
        platforms = [
            SimpleNamespace(
                platform_id="p1", line_id="line_1", direction="down", waiting_persons=0
            ),
            SimpleNamespace(platform_id="p2", line_id="line_2", direction="up", waiting_persons=3),
            SimpleNamespace(platform_id="p3", line_id="line_2", direction="up", waiting_persons=1),
        ]

        filtered = filter_platforms_for_passenger(passenger, platforms)
        self.assertEqual(["p2", "p3"], [platform.platform_id for platform in filtered])
        self.assertEqual(
            "p3",
            pick_least_loaded(filtered, Random(3), lambda item: item.waiting_persons).platform_id,
        )


class VisualDemoGeometryTests(unittest.TestCase):
    def test_explicit_queue_slots_extend_instead_of_reusing_fixed_points(self) -> None:
        layout = QueueLayout(
            anchor=(0.0, 0.0),
            per_row=2,
            col_step=(0.0, 0.0),
            row_step=(0.0, 1.0),
            slots=((0.0, 0.0), (1.0, 0.0)),
        )

        self.assertEqual(layout.slot(0), (0.0, 0.0))
        self.assertEqual(layout.slot(1), (1.0, 0.0))
        self.assertEqual(layout.slot(2), (0.0, 1.0))
        self.assertEqual(layout.slot(3), (1.0, 1.0))

    def test_fare_barrier_blocks_between_gate_openings(self) -> None:
        geometry = load_station_geometry()

        self.assertFalse(geometry.covers(Point(meters((0.190, 0.352)))))
        self.assertTrue(geometry.covers(Point(meters((0.210, 0.352)))))
        self.assertFalse(
            geometry.buffer(0.02).covers(
                LineString([meters((0.500, 0.330)), meters((0.500, 0.375))])
            )
        )

    def test_visual_demo_vertical_graph_nodes_are_level_specific_and_walkable(self) -> None:
        graph = StationGraph.from_design(create_design("visual_demo_station"))
        geometry = load_station_geometry()

        self.assertNotEqual(
            graph.nodes["vertical:down_escalator_a:b1_concourse"].position,
            graph.nodes["vertical:down_escalator_a:b2_platform"].position,
        )
        for node in graph.nodes_matching(facility_stage=FacilityStage.VERTICAL_TRANSFER.value):
            with self.subTest(node=node.node_id):
                self.assertTrue(geometry.covers(Point(node.position)))

    def test_visual_demo_zone_graph_nodes_are_walkable(self) -> None:
        graph = StationGraph.from_design(create_design("visual_demo_station"))
        geometry = load_station_geometry()

        for node in graph.nodes_matching(kind="zone"):
            with self.subTest(node=node.node_id):
                self.assertTrue(geometry.covers(Point(node.position)))

    def test_visual_demo_platform_waiting_slots_are_walkable(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        geometry = load_station_geometry()

        for index in range(120):
            with self.subTest(index=index):
                self.assertTrue(
                    geometry.covers(Point(model.layout_graph.platform_waiting_position(index)))
                )

    def test_visual_demo_platform_waiting_slots_are_near_train_doors(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        document = create_design("visual_demo_station")
        door_points = [
            element.geometry.center()
            for element in document.elements
            if element.kind == "platform_edge"
        ]
        train_edge_min_y = meters((0.0, 0.72))[1]

        for index in range(120):
            slot = model.layout_graph.platform_waiting_position(index)
            nearest_door_distance = min(abs(slot[0] - door[0]) for door in door_points)
            with self.subTest(index=index, slot=slot):
                self.assertGreaterEqual(slot[1], train_edge_min_y)
                self.assertLessEqual(nearest_door_distance, 4.6)

    def test_visual_demo_platform_waiting_slots_do_not_repeat_under_load(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        positions = [model.layout_graph.platform_waiting_position(index) for index in range(260)]
        rounded = {(round(x, 3), round(y, 3)) for x, y in positions}

        self.assertEqual(len(rounded), len(positions))

    def test_visual_demo_facility_queue_slots_are_walkable(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        geometry = load_station_geometry()

        for facility in model.facilities:
            slots = facility.spec.queue_layout.slots
            with self.subTest(facility=facility.spec.facility_id):
                self.assertTrue(slots)
            for slot in slots[:32]:
                with self.subTest(facility=facility.spec.facility_id, slot=slot):
                    self.assertTrue(geometry.covers(Point(slot)))

    def test_visual_demo_gate_banks_compile_to_individual_lanes(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)

        self.assertEqual(6, len(model.gates))
        self.assertEqual(4, len(model.exit_gates))
        self.assertEqual(
            6,
            len({round(gate.spec.position[0], 3) for gate in model.gates}),
        )
        self.assertEqual(
            4,
            len({round(gate.spec.position[0], 3) for gate in model.exit_gates}),
        )

    def test_visual_demo_queue_payload_exports_gate_lanes(self) -> None:
        scenario = scenario_for("visual_demo_station")
        model = MetroStationModel(scenario, seed=2)

        payload = mesa_frames_to_visual_tracks(
            frames=[],
            scenario=scenario,
            facilities=model.facilities,
        )
        entry_queues = [
            queue for queue in payload["queue_layouts"] if queue["kind"] == "entry_gate"
        ]
        exit_queues = [
            queue for queue in payload["queue_layouts"] if queue["kind"] == "exit_gate"
        ]

        self.assertEqual(6, len(entry_queues))
        self.assertEqual(4, len(exit_queues))
        self.assertTrue(all("_lane_" in queue["id"] for queue in entry_queues))
        self.assertEqual(6, len({tuple(queue["exit"]) for queue in entry_queues}))
        self.assertTrue(all(queue["exit"][1] >= 0.318 for queue in exit_queues))

    def test_visual_demo_decision_regions_are_exported(self) -> None:
        payload = layout_payload()
        geometry = load_station_geometry()
        regions = payload["decision_regions"]
        by_id = {region["id"]: region for region in regions}

        self.assertIn("entry_gate_decision", by_id)
        self.assertIn("vertical_transfer_decision", by_id)
        self.assertIn("platform_boarding_decision", by_id)
        self.assertIn("exit_gate_decision", by_id)
        self.assertGreaterEqual(by_id["exit_gate_decision"]["points"][0][1], 0.318)
        for region in regions:
            points = region["points"]
            centroid = (
                sum(point[0] for point in points) / len(points),
                sum(point[1] for point in points) / len(points),
            )
            with self.subTest(region=region["id"]):
                self.assertTrue(geometry.covers(Point(meters(centroid))))

    def test_visual_demo_exit_gate_decision_route_stays_on_paid_side(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)

        route = model.layout_graph.route_for_key(
            RouteKey.AFTER_EXIT_VERTICAL.value,
            meters((0.600, 0.430)),
        )

        self.assertGreaterEqual(route[-1][1], meters((0.0, 0.330))[1])
        for facility in model.vertical_transports:
            if facility.spec.direction not in {"up", "both"}:
                continue
            with self.subTest(facility=facility.facility_id):
                route = model.layout_graph.route_for_key(
                    RouteKey.AFTER_EXIT_VERTICAL.value,
                    facility.spec.exit_position,
                )
                self.assertEqual(1, len(route))
                self.assertGreaterEqual(route[-1][1], meters((0.0, 0.330))[1])

    def test_visual_demo_after_entry_gate_route_stays_in_paid_area(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        context = SimpleNamespace(current_level_id="b1_concourse")

        for facility in model.gates:
            with self.subTest(facility=facility.facility_id):
                route = model.layout_graph.route_for_key(
                    RouteKey.AFTER_GATE.value,
                    facility.spec.exit_position,
                    context,
                )

                self.assertTrue(route)
                self.assertTrue(all(point[1] >= meters((0.0, 0.350))[1] for point in route))
                self.assertTrue(all(point[0] >= meters((0.145, 0.0))[0] for point in route))

    def test_platform_boarding_release_is_limited_by_door_frontage(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        platform = model.platforms[0]
        platform.waiting = [SimpleNamespace(group_size=1) for _ in range(80)]

        self.assertEqual(
            platform._boarding_release_limit(),
            len(model.boarding_doors_for_platform(platform))
            * model.scenario.platform_boarding_release_groups_per_door_tick,
        )

    def test_jupedsim_start_position_projects_from_boundary_to_walkable_core(self) -> None:
        geometry = load_station_geometry()
        adapter = JuPedSimAdapter()
        boundary_near = (20.51583939244577, 29.94093838319245)

        projected = adapter._safe_agent_position(geometry, boundary_near, 0.18)

        self.assertTrue(geometry.buffer(-0.18).covers(Point(projected)))

    def test_region_flow_compiles_source_to_queue_capture_apron(self) -> None:
        queue = next(item for item in FACILITY_QUEUES if item.name == "down_escalator_2_queue")
        plan = build_region_capture_flow(
            name="test.right.vertical_capture",
            source=(0.720, 0.360),
            queue_spec=queue,
            queue_stage_id=42,
            capture_aprons=QUEUE_CAPTURE_APRONS_N,
        )

        self.assertEqual(42, plan.target_queue_stage_id)
        self.assertEqual("down_escalator_2_queue", plan.target_facility)
        self.assertGreaterEqual(len(plan.portals), 1)
        self.assertEqual("down_escalator_2_queue", plan.portals[-1].facility)
        self.assertLess(plan.portals[-1].center[0], 0.620)
        self.assertGreater(plan.portals[-1].radius_m, plan.portals[0].radius_m)

    def test_point_capture_flow_supports_runtime_queue_without_spec(self) -> None:
        plan = build_point_capture_flow(
            name="test.boarding.capture",
            source=(0.330, 0.715),
            capture=(0.360, 0.735),
            target_queue_stage_id=99,
            target_facility="boarding_door_1",
            portal_count=1,
        )

        self.assertEqual(99, plan.target_queue_stage_id)
        self.assertEqual("boarding_door_1", plan.target_facility)
        self.assertEqual(1, len(plan.portals))
        self.assertEqual("boarding_door_1", plan.portals[-1].facility)

    def test_queue_attractiveness_field_ranks_reachable_lower_cost_option(self) -> None:
        field = QueueAttractivenessField()
        current = QueueFieldCandidate(
            stage_id=1,
            facility="boarding_door_1",
            distance_m=2.0,
            load=10,
            service_interval_s=0.5,
            current=True,
            reachable=True,
        )
        alternative = QueueFieldCandidate(
            stage_id=2,
            facility="boarding_door_2",
            distance_m=3.0,
            load=1,
            service_interval_s=0.5,
            current=False,
            reachable=True,
        )
        blocked = QueueFieldCandidate(
            stage_id=3,
            facility="boarding_door_3",
            distance_m=1.0,
            load=0,
            service_interval_s=0.5,
            current=False,
            reachable=False,
        )

        scores = field.rank((current, alternative, blocked))

        self.assertEqual(2, scores[0].stage_id)
        self.assertEqual(float("inf"), scores[-1].cost)

    def test_grid_floor_field_routes_around_fare_barrier(self) -> None:
        geometry = load_station_geometry()
        grid = GridFloorField.from_geometry(geometry, cell_size_m=1.0)
        source = meters((0.500, 0.330))
        target = meters((0.500, 0.375))
        field = grid.distance_field((target,))

        direct = Point(source).distance(Point(target))
        cost = field.cost_at(source)

        self.assertGreater(cost, direct * 2.0)
        self.assertNotEqual((0.0, 0.0), field.descent_vector(source))

    def test_grid_floor_field_dynamic_penalty_raises_cost(self) -> None:
        geometry = load_station_geometry()
        grid = GridFloorField.from_geometry(geometry, cell_size_m=1.0)
        source = meters((0.500, 0.330))
        target = meters((0.500, 0.375))
        baseline = grid.distance_field((target,)).cost_at(source)
        penalty = grid.density_penalty((meters((0.500, 0.345)),), radius_cells=3, weight=6.0)
        crowded = grid.distance_field((target,), dynamic_penalty=penalty).cost_at(source)

        self.assertGreater(crowded, baseline)

    def test_entry_gate_release_uses_narrow_service_portal(self) -> None:
        runtime = NativeQueueRuntime(
            name="entry_gate_1_queue",
            source="gate_queue_state",
            color="#2f89ff",
            stage_id=1,
            service_interval=1.65,
            next_service=0.0,
            spec=GATE_QUEUE_SPECS[0],
        )

        self.assertEqual(ENTRY_GATE_PORTAL_RADIUS_M, post_gate_portal_radius(runtime))
        self.assertLess(ENTRY_GATE_PORTAL_RADIUS_M, POST_GATE_RADIUS_M)

    def test_queue_field_switching_is_limited_to_boarding_doors(self) -> None:
        boarding = NativeQueueRuntime(
            name="boarding_door_1",
            source="boarding_queue_native",
            color="#ffd166",
            stage_id=1,
            service_interval=0.42,
            next_service=0.0,
        )
        gate = NativeQueueRuntime(
            name="entry_gate_1_queue",
            source="gate_queue_state",
            color="#2f89ff",
            stage_id=2,
            service_interval=1.65,
            next_service=0.0,
            spec=GATE_QUEUE_SPECS[0],
        )

        self.assertTrue(queue_field_switching_is_enabled(boarding))
        self.assertFalse(queue_field_switching_is_enabled(gate))


if __name__ == "__main__":
    unittest.main()
