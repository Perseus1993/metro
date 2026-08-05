from __future__ import annotations

import copy
import json
import random
import subprocess
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from sandbox.metro_station_sandbox.design import create_design, validate_design
from sandbox.metro_station_sandbox.design.schema import StationDesignDocument
from metro_station_designer.server import (
    ROOT,
    DesignInspectorHandler,
    build_design_payload,
    compile_react_flow_payload,
    simulate_design_payload,
    template_catalog_payload,
)


def _component_node(
    element_id: str,
    kind: str,
    level_id: str,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    role: str = "facility",
    connects_levels: tuple[str, ...] = (),
    gate_direction: str | None = None,
    direction: str | None = None,
    line_id: str | None = None,
) -> dict:
    geometry = {
        "shape": "rect",
        "x_m": x,
        "y_m": y,
        "width_m": width,
        "height_m": height,
        "rotation_deg": 0.0,
        "points_m": [],
    }
    return {
        "id": f"element:{element_id}",
        "type": "verticalConnector" if role == "vertical_connector" else "facilityNode",
        "parentId": f"level:{level_id}",
        "position": {"x": x, "y": y},
        "width": width,
        "height": height,
        "style": {"width": width, "height": height},
        "data": {
            "inspector_created": True,
            "kind": kind,
            "level_id": level_id,
            "role": role,
            "label": element_id,
            "geometry": geometry,
            "connects_levels": list(connects_levels),
            "gate_direction": gate_direction,
            "direction": direction,
            "line_id": line_id,
            "metadata": {"inspector_created": True},
        },
    }


def _station_components(template_id: str) -> list[dict]:
    if template_id == "scratch_single_level":
        top = "l1_station"
        return [
            _component_node("entrance", "entrance", top, 10, 10, 5, 5),
            _component_node("entry_gate", "gate", top, 25, 10, 8, 5, gate_direction="entry"),
            _component_node("exit_gate", "gate", top, 40, 10, 8, 5, gate_direction="exit"),
            _component_node(
                "platform_l1", "platform_edge", top, 72, 20, 12, 3, direction="down", line_id="L1"
            ),
        ]
    if template_id == "scratch_two_level":
        top, bottom = "b1_concourse", "b2_platform"
        return [
            _component_node("entrance", "entrance", top, 10, 10, 5, 5),
            _component_node("entry_gate", "gate", top, 25, 10, 8, 5, gate_direction="entry"),
            _component_node("exit_gate", "gate", top, 40, 10, 8, 5, gate_direction="exit"),
            _component_node(
                "escalator",
                "escalator",
                top,
                50,
                35,
                7,
                12,
                role="vertical_connector",
                connects_levels=(top, bottom),
                direction="down",
            ),
            _component_node(
                "elevator",
                "elevator",
                top,
                66,
                35,
                6,
                6,
                role="vertical_connector",
                connects_levels=(top, bottom),
                direction="both",
            ),
            _component_node(
                "stairs",
                "stairs",
                top,
                82,
                35,
                8,
                12,
                role="vertical_connector",
                connects_levels=(top, bottom),
                direction="both",
            ),
            _component_node(
                "platform_l1",
                "platform_edge",
                bottom,
                72,
                20,
                12,
                3,
                direction="down",
                line_id="L1",
            ),
        ]
    top, middle, bottom = "b1_concourse", "b2_transfer", "b3_platform"
    return [
        _component_node("entrance", "entrance", top, 10, 10, 5, 5),
        _component_node("entry_gate", "gate", top, 25, 10, 8, 5, gate_direction="entry"),
        _component_node("exit_gate", "gate", top, 40, 10, 8, 5, gate_direction="exit"),
        _component_node(
            "escalator",
            "escalator",
            top,
            52,
            35,
            7,
            12,
            role="vertical_connector",
            connects_levels=(top, middle),
            direction="down",
        ),
        _component_node(
            "elevator",
            "elevator",
            top,
            68,
            35,
            6,
            6,
            role="vertical_connector",
            connects_levels=(top, middle, bottom),
            direction="both",
        ),
        _component_node(
            "stairs",
            "stairs",
            middle,
            84,
            35,
            8,
            12,
            role="vertical_connector",
            connects_levels=(middle, bottom),
            direction="both",
        ),
        _component_node(
            "platform_l1",
            "platform_edge",
            bottom,
            68,
            20,
            12,
            3,
            direction="down",
            line_id="L1",
        ),
        _component_node(
            "platform_l2",
            "platform_edge",
            bottom,
            92,
            20,
            12,
            3,
            direction="up",
            line_id="L2",
        ),
    ]


def _generated_payload(template_id: str, *, include_flow: bool = True) -> dict:
    base = build_design_payload(template_id)
    nodes = [*base["react_flow"]["nodes"], *_station_components(template_id)]
    if include_flow:
        nodes.append(
            {
                "id": "flow:default_entry",
                "type": "demandFlow",
                "data": {
                    "demand_flow": True,
                    "flow_id": "default_entry",
                    "intent": "enter_and_board",
                    "source_element_id": "entrance",
                    "rate_per_hour": 30,
                },
            }
        )
    return {
        "template_id": template_id,
        "nodes": nodes,
        "edges": [],
        "generate_station": True,
        "operations": {
            "entry_count_hour": 30,
            "exit_count_hour": 0,
            "transfer_count_hour": 0,
            "minutes": 1,
        },
        "tick_seconds": 10,
        "seed": 42,
    }


def _wizard_generated_payload(
    levels: int,
    is_transfer: bool,
    entrances: int,
    gates: int,
) -> tuple[dict, dict]:
    template_id = {
        1: "scratch_single_level",
        2: "scratch_two_level",
        3: "scratch_three_level",
    }[levels]
    setup_module = (
        Path("apps/station_designer/src/metro_station_designer/station_setup.js").resolve().as_uri()
    )
    base = build_design_payload(template_id)
    catalog = template_catalog_payload()
    script = f"""
      import {{ createStationSetupNodes }} from {json.dumps(setup_module)};
      const created = createStationSetupNodes(
        {json.dumps(base["react_flow"]["nodes"])},
        {json.dumps(catalog["component_palette"])},
        {json.dumps({"levels": levels, "isTransfer": is_transfer, "entranceCount": entrances, "gateCount": gates})},
      );
      if (created.error) throw new Error(created.error);
      process.stdout.write(JSON.stringify(created));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    setup = json.loads(completed.stdout)
    nodes = setup["nodes"]
    entrance = next(node for node in nodes if node.get("data", {}).get("kind") == "entrance")
    nodes.append(
        {
            "id": "flow:wizard_entry",
            "type": "demandFlow",
            "data": {
                "demand_flow": True,
                "flow_id": "wizard_entry",
                "intent": "enter_and_board",
                "source_element_id": entrance["data"]["element_id"],
                "rate_per_hour": 30,
            },
        }
    )
    return (
        {
            "template_id": template_id,
            "nodes": nodes,
            "edges": [],
            "generate_station": True,
            "operations": {"entry_count_hour": 30, "minutes": 1},
            "tick_seconds": 10,
            "seed": 42,
        },
        setup,
    )


def test_catalog_exposes_three_empty_station_shells_and_flow_palette() -> None:
    catalog = template_catalog_payload()
    template_ids = {template["id"] for template in catalog["templates"]}

    assert {
        "scratch_single_level",
        "scratch_two_level",
        "scratch_three_level",
    } <= template_ids
    assert catalog["default_template_id"] == "scratch_single_level"
    assert {flow["intent"] for flow in catalog["passenger_flow_palette"]} == {
        "enter_and_board",
        "exit_station",
        "transfer",
    }


@pytest.mark.parametrize(
    ("template_id", "level_count"),
    (
        ("scratch_single_level", 1),
        ("scratch_two_level", 2),
        ("scratch_three_level", 3),
    ),
)
def test_empty_shell_contains_only_locked_floor_zones(template_id: str, level_count: int) -> None:
    document = create_design(template_id)

    assert len(document.levels) == level_count
    assert len(document.elements) == level_count
    assert all(element.role == "floor" and not element.movable for element in document.elements)
    assert document.queues == ()
    assert document.connections == ()


@pytest.mark.parametrize(
    "template_id",
    ("scratch_single_level", "scratch_two_level", "scratch_three_level"),
)
def test_generate_station_compiles_custom_layout_to_valid_graph(template_id: str) -> None:
    compiled = compile_react_flow_payload(_generated_payload(template_id))
    document = StationDesignDocument.from_dict(compiled["document"])

    assert compiled["summary"]["status"] == "ok", compiled["validation_issues"]
    assert validate_design(document) == []
    assert document.metadata["generation_state"] == "generated"
    queue_owners = {queue.owner_element_id for queue in document.queues}
    expected_queue_owners = {
        node["id"].removeprefix("element:")
        for node in _station_components(template_id)
        if node["data"]["kind"] in {"gate", "escalator", "stairs", "elevator", "platform_edge"}
    }
    assert expected_queue_owners <= queue_owners
    assert compiled["graph"]["node_count"] > 0
    assert compiled["graph"]["edge_count"] > 0


def test_dragged_demand_flows_bind_sources_targets_and_drive_rates() -> None:
    payload = _generated_payload("scratch_three_level", include_flow=False)
    payload["nodes"].extend(
        [
            {
                "id": "flow:entry_a",
                "type": "demandFlow",
                "data": {
                    "demand_flow": True,
                    "flow_id": "entry_a",
                    "intent": "enter_and_board",
                    "source_element_id": "entrance",
                    "rate_per_hour": 1200,
                },
            },
            {
                "id": "flow:exit_a",
                "type": "demandFlow",
                "data": {
                    "demand_flow": True,
                    "flow_id": "exit_a",
                    "intent": "exit_station",
                    "source_element_id": "platform_l1",
                    "rate_per_hour": 700,
                },
            },
            {
                "id": "flow:transfer_a",
                "type": "demandFlow",
                "data": {
                    "demand_flow": True,
                    "flow_id": "transfer_a",
                    "intent": "transfer",
                    "source_element_id": "platform_l1",
                    "target_element_id": "platform_l2",
                    "rate_per_hour": 500,
                },
            },
        ]
    )

    compiled = compile_react_flow_payload(payload)

    assert compiled["summary"]["status"] == "ok", compiled["validation_issues"]
    assert compiled["operations"]["entry_count_hour"] == 1200
    assert compiled["operations"]["exit_count_hour"] == 700
    assert compiled["operations"]["transfer_count_hour"] == 500
    assert len(compiled["demand_flows"]) == 3


def test_invalid_demand_binding_blocks_simulation_with_a_stable_reason() -> None:
    payload = _generated_payload("scratch_single_level", include_flow=False)
    payload["nodes"].append(
        {
            "id": "flow:bad_entry",
            "type": "demandFlow",
            "data": {
                "demand_flow": True,
                "intent": "enter_and_board",
                "source_element_id": "platform_l1",
                "rate_per_hour": 100,
            },
        }
    )

    compiled = compile_react_flow_payload(payload)

    assert compiled["summary"]["status"] == "error"
    assert "demand.source_kind_invalid" in {
        issue["code"] for issue in compiled["validation_issues"]
    }


def test_generated_scratch_station_requires_explicit_demand() -> None:
    compiled = compile_react_flow_payload(
        _generated_payload("scratch_single_level", include_flow=False)
    )

    assert compiled["summary"]["status"] == "error"
    assert "demand.required_for_scratch_station" in {
        issue["code"] for issue in compiled["validation_issues"]
    }


def test_scratch_flow_definitions_zero_unspecified_demand_types() -> None:
    compiled = compile_react_flow_payload(_generated_payload("scratch_single_level"))

    assert compiled["operations"]["entry_count_hour"] == 30
    assert compiled["operations"]["exit_count_hour"] == 0
    assert compiled["operations"]["transfer_count_hour"] == 0


def test_server_rejects_malformed_and_nonfinite_react_flow_payloads() -> None:
    with pytest.raises(ValueError, match="nodes must be an array"):
        compile_react_flow_payload({"template_id": "scratch_single_level", "nodes": {}})
    with pytest.raises(ValueError, match="every nodes item must be an object"):
        compile_react_flow_payload({"template_id": "scratch_single_level", "nodes": [None]})

    payload = build_design_payload("single_level_terminal")
    nodes = copy.deepcopy(payload["react_flow"]["nodes"])
    gate = next(node for node in nodes if node["id"] == "element:gate_bank_a")
    gate["position"]["x"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        compile_react_flow_payload(
            {"template_id": "single_level_terminal", "nodes": nodes, "edges": []}
        )


def test_top_level_simulation_values_cannot_bypass_operation_limits() -> None:
    compiled = compile_react_flow_payload(
        {
            "template_id": "single_level_terminal",
            "entry_count_hour": 10**12,
            "minutes": 10**9,
            "group_size": 0,
        }
    )

    assert compiled["operations"]["entry_count_hour"] == 120_000
    assert compiled["operations"]["minutes"] == 60
    assert compiled["operations"]["group_size"] == 1


def test_invalid_connection_protocol_is_reported_without_graph_mutation() -> None:
    base = build_design_payload("single_level_terminal")
    edges = copy.deepcopy(base["react_flow"]["edges"][:2])
    edges[0]["data"]["kind"] = "teleport"
    edges[0]["data"]["bidirectional"] = "yes"
    edges[1]["id"] = edges[0]["id"]

    compiled = compile_react_flow_payload(
        {
            "template_id": "single_level_terminal",
            "nodes": base["react_flow"]["nodes"],
            "edges": edges,
        }
    )
    issue_codes = {issue["code"] for issue in compiled["validation_issues"]}

    assert compiled["summary"]["status"] == "error"
    assert "connections.invalid_kind" in issue_codes
    assert "connections.invalid_bidirectional" in issue_codes
    assert "connections.duplicate_id" in issue_codes


def test_invalid_design_simulation_endpoint_returns_422_and_no_job() -> None:
    handler = partial(DesignInspectorHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"template_id": "scratch_single_level"}).encode("utf-8")
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/simulate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request, timeout=5)
        response = exc_info.value
        response_payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.code == 422
    assert response_payload["status"] == "error"
    assert "job_id" not in response_payload


def test_queue_generation_failure_is_reported_as_a_validation_issue() -> None:
    payload = _generated_payload("scratch_two_level")
    for node in payload["nodes"]:
        if node.get("data", {}).get("inspector_created"):
            node["position"] = {"x": 50.0, "y": 35.0}

    compiled = compile_react_flow_payload(payload)

    assert compiled["summary"]["status"] == "error"
    assert any(
        issue["code"] == "spatial_capacity.queue_domain_unavailable"
        and issue["path"] == "queues"
        for issue in compiled["validation_issues"]
    )


@pytest.mark.parametrize(
    ("template_id", "sample"),
    tuple(
        (template_id, sample)
        for template_id in (
            "scratch_single_level",
            "scratch_two_level",
            "scratch_three_level",
        )
        for sample in range(30)
    ),
)
def test_random_scratch_drags_generate_deterministically_without_crashing(
    template_id: str,
    sample: int,
) -> None:
    template_index = (
        "scratch_single_level",
        "scratch_two_level",
        "scratch_three_level",
    ).index(template_id)
    rng = random.Random(20260713 + template_index * 30 + sample)
    payload = _generated_payload(template_id)
    for node in payload["nodes"]:
        if not node.get("data", {}).get("inspector_created"):
            continue
        width = float(node["width"])
        height = float(node["height"])
        if sample % 2 == 0:
            node["position"] = {
                "x": node["position"]["x"] + rng.uniform(-2.0, 2.0),
                "y": node["position"]["y"] + rng.uniform(-2.0, 2.0),
            }
        else:
            node["position"] = {
                "x": rng.uniform(4.0, 116.0 - width),
                "y": rng.uniform(4.0, 76.0 - height),
            }

    first = compile_react_flow_payload(payload)
    second = compile_react_flow_payload(copy.deepcopy(payload))
    first_signature = (
        first["summary"]["status"],
        [
            (issue["severity"], issue["code"], issue["path"])
            for issue in first["validation_issues"]
        ],
        first["document"]["queues"],
        first["document"]["connections"],
    )
    second_signature = (
        second["summary"]["status"],
        [
            (issue["severity"], issue["code"], issue["path"])
            for issue in second["validation_issues"]
        ],
        second["document"]["queues"],
        second["document"]["connections"],
    )

    assert first_signature == second_signature


def test_frontend_demand_drag_requires_the_correct_facility_and_updates_rate() -> None:
    module_path = (
        Path("apps/station_designer/src/metro_station_designer/demand_flow_palette.js")
        .resolve()
        .as_uri()
    )
    script = f"""
      import {{
        createDemandFlowNode,
        updateDemandFlowRate,
        updateDemandFlowTarget,
      }} from {json.dumps(module_path)};
      const level = {{ id: 'level:l1', type: 'levelGroup', style: {{ width: 120, height: 80 }} }};
      const entrance = {{
        id: 'element:entrance', parentId: 'level:l1', position: {{ x: 10, y: 10 }},
        width: 5, height: 5, data: {{ kind: 'entrance', label: 'Entrance' }},
      }};
      const platform = {{
        id: 'element:platform', parentId: 'level:l1', position: {{ x: 60, y: 20 }},
        width: 8, height: 3, data: {{ kind: 'platform_edge', line_id: 'L1', direction: 'down' }},
      }};
      const platform2 = {{
        id: 'element:platform2', parentId: 'level:l1', position: {{ x: 80, y: 20 }},
        width: 8, height: 3, data: {{ kind: 'platform_edge', line_id: 'L2', direction: 'up' }},
      }};
      const entry = {{
        id: 'entry', label: 'Entry', intent: 'enter_and_board', source_kind: 'entrance',
        operation_id: 'entry_count_hour', default_rate_per_hour: 2000,
      }};
      const good = createDemandFlowNode(entry, entrance, {{ entry_count_hour: 1234 }}, [level, entrance, platform]);
      const bad = createDemandFlowNode(entry, platform, {{}}, [level, entrance, platform]);
      const updated = updateDemandFlowRate([good.node], good.node.id, 4321);
      const transfer = createDemandFlowNode({{
        id: 'transfer', label: 'Transfer', intent: 'transfer', source_kind: 'platform_edge',
        operation_id: 'transfer_count_hour', default_rate_per_hour: 1000,
      }}, platform, {{}}, [level, entrance, platform, platform2]);
      const retargeted = updateDemandFlowTarget(
        [transfer.node], transfer.node.id, 'platform3',
      );
      process.stdout.write(JSON.stringify({{
        source: good.node.data.source_element_id,
        rate: good.node.data.rate_per_hour,
        updatedRate: updated[0].data.rate_per_hour,
        badError: bad.error,
        transferTarget: transfer.node.data.target_element_id,
        updatedTarget: retargeted[0].data.target_element_id,
      }}));
    """

    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )

    result = json.loads(completed.stdout)
    assert result == {
        "source": "entrance",
        "rate": 1234,
        "updatedRate": 4321,
        "badError": "Entry must be dropped on a entrance.",
        "transferTarget": "platform2",
        "updatedTarget": "platform3",
    }


def test_click_guided_builder_produces_a_valid_three_level_station() -> None:
    placement_module = (
        Path("apps/station_designer/src/metro_station_designer/guided_placement.js")
        .resolve()
        .as_uri()
    )
    demand_module = (
        Path("apps/station_designer/src/metro_station_designer/demand_flow_palette.js")
        .resolve()
        .as_uri()
    )
    progress_module = (
        Path("apps/station_designer/src/metro_station_designer/build_progress.js").resolve().as_uri()
    )
    base = build_design_payload("scratch_three_level")
    catalog = template_catalog_payload()
    components = {component["id"]: component for component in catalog["component_palette"]}
    sequence = [
        components["entrance"],
        components["entry_gate"],
        components["exit_gate"],
        components["platform_edge"],
        components["down_escalator"],
        components["up_escalator"],
        components["stairs"],
    ]
    entry_flow = next(
        flow for flow in catalog["passenger_flow_palette"] if flow["id"] == "entry_flow"
    )
    script = f"""
      import {{ createSuggestedComponentNode }} from {json.dumps(placement_module)};
      import {{ createSuggestedDemandFlowNode }} from {json.dumps(demand_module)};
      import {{ stationBuildProgress }} from {json.dumps(progress_module)};
      let nodes = {json.dumps(base["react_flow"]["nodes"])};
      const components = {json.dumps(sequence)};
      for (const component of components) {{
        const result = createSuggestedComponentNode(component, nodes);
        if (!result.node) throw new Error(result.error);
        nodes = [...nodes, result.node];
      }}
      const beforeFlow = stationBuildProgress(nodes, {{ document: {{ metadata: {{ editor_scratch: true }} }} }}, true);
      const flow = createSuggestedDemandFlowNode(
        {json.dumps(entry_flow)}, {{ entry_count_hour: 30 }}, nodes,
      );
      if (!flow.node) throw new Error(flow.error);
      nodes = [...nodes, flow.node];
      const afterFlow = stationBuildProgress(
        nodes,
        {{
          document: {{ metadata: {{ editor_scratch: true }} }},
          summary: {{ status: 'ok' }},
        }},
        true,
      );
      process.stdout.write(JSON.stringify({{
        nodes,
        beforeFlowNext: beforeFlow.next.id,
        afterFlowNext: afterFlow.next.id,
      }}));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    guided = json.loads(completed.stdout)

    compiled = compile_react_flow_payload(
        {
            "template_id": "scratch_three_level",
            "nodes": guided["nodes"],
            "edges": [],
            "generate_station": True,
            "operations": {"entry_count_hour": 30, "minutes": 1},
        }
    )
    connectors = [
        node["data"]["connects_levels"]
        for node in guided["nodes"]
        if node.get("data", {}).get("role") == "vertical_connector"
    ]

    assert guided["beforeFlowNext"] == "demand"
    assert guided["afterFlowNext"] == "done"
    assert ["b1_concourse", "b2_transfer"] in connectors
    assert ["b2_transfer", "b3_platform"] in connectors
    assert compiled["summary"]["status"] == "ok", compiled["validation_issues"]


@pytest.mark.parametrize(
    ("levels", "is_transfer", "entrances", "gates"),
    (
        (1, False, 1, 2),
        (2, False, 2, 4),
        (3, True, 3, 6),
        (3, True, 6, 12),
    ),
)
def test_setup_wizard_auto_layout_compiles_at_supported_boundaries(
    levels: int,
    is_transfer: bool,
    entrances: int,
    gates: int,
) -> None:
    payload, setup = _wizard_generated_payload(levels, is_transfer, entrances, gates)
    nodes = setup["nodes"]
    compiled = compile_react_flow_payload(payload)
    elements = [node for node in nodes if str(node["id"]).startswith("element:")]
    entry_gates = [
        node for node in elements if node.get("data", {}).get("gate_direction") == "entry"
    ]
    exit_gates = [node for node in elements if node.get("data", {}).get("gate_direction") == "exit"]

    assert setup["counts"] == {
        "entrances": entrances,
        "entryGates": (gates + 1) // 2,
        "exitGates": gates // 2,
        "platforms": 2 if is_transfer else 1,
        "downEscalators": levels - 1,
        "upEscalators": levels - 1,
        "stairs": levels - 1,
        "elevators": 1 if levels > 1 else 0,
    }
    assert (
        len([node for node in elements if node.get("data", {}).get("kind") == "entrance"])
        == entrances
    )
    assert len(entry_gates) == (gates + 1) // 2
    assert len(exit_gates) == gates // 2
    assert len(
        [node for node in elements if node.get("data", {}).get("kind") == "platform_edge"]
    ) == (2 if is_transfer else 1)
    assert all(
        node.get("data", {}).get("inspector_created")
        for node in elements
        if node.get("data", {}).get("role") != "floor"
    )
    assert compiled["summary"]["status"] == "ok", compiled["validation_issues"]


def test_setup_wizard_three_level_transfer_station_runs_goal_graph_jupedsim() -> None:
    payload, _ = _wizard_generated_payload(3, True, 3, 6)

    result = simulate_design_payload(payload)

    assert result["status"] == "ok", result.get("error")
    assert result["compile_summary"]["status"] == "ok"
    assert result["trajectory_report"] is not None


def test_setup_wizard_rejects_out_of_range_or_incomplete_configuration() -> None:
    setup_module = (
        Path("apps/station_designer/src/metro_station_designer/station_setup.js").resolve().as_uri()
    )
    invalid_configs = [
        {"levels": 0, "isTransfer": False, "entranceCount": 1, "gateCount": 2},
        {"levels": 4, "isTransfer": False, "entranceCount": 1, "gateCount": 2},
        {"levels": 1, "isTransfer": None, "entranceCount": 1, "gateCount": 2},
        {"levels": 1, "isTransfer": False, "entranceCount": 0, "gateCount": 2},
        {"levels": 1, "isTransfer": False, "entranceCount": 7, "gateCount": 2},
        {"levels": 1, "isTransfer": False, "entranceCount": 1, "gateCount": 1},
        {"levels": 1, "isTransfer": False, "entranceCount": 1, "gateCount": 13},
    ]
    script = f"""
      import {{ normalizeStationSetup }} from {json.dumps(setup_module)};
      const configs = {json.dumps(invalid_configs)};
      const results = configs.map((config) => {{
        try {{ normalizeStationSetup(config); return 'accepted'; }}
        catch (error) {{ return String(error.message || error); }}
      }});
      process.stdout.write(JSON.stringify(results));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )

    assert all(result != "accepted" for result in json.loads(completed.stdout))


def test_all_station_setup_presets_generate_valid_draggable_stations() -> None:
    presets_module = (
        Path("apps/station_designer/src/metro_station_designer/station_setup_presets.js")
        .resolve()
        .as_uri()
    )
    script = f"""
      import {{ STATION_SETUP_PRESETS }} from {json.dumps(presets_module)};
      process.stdout.write(JSON.stringify(STATION_SETUP_PRESETS));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    presets = json.loads(completed.stdout)

    assert len(presets) == 5
    assert len({preset["id"] for preset in presets}) == len(presets)
    assert {preset["config"]["levels"] for preset in presets} == {1, 2, 3}
    assert {preset["config"]["isTransfer"] for preset in presets} == {False, True}

    for preset in presets:
        config = preset["config"]
        payload, setup = _wizard_generated_payload(
            config["levels"],
            config["isTransfer"],
            config["entranceCount"],
            config["gateCount"],
        )
        compiled = compile_react_flow_payload(payload)
        created_nodes = [
            node for node in setup["nodes"] if node.get("data", {}).get("inspector_created")
        ]

        assert compiled["summary"]["status"] == "ok", (
            preset["id"],
            compiled["validation_issues"],
        )
        assert created_nodes
        assert all(node.get("draggable") is True for node in created_nodes)
        assert all(node.get("selectable") is True for node in created_nodes)


def test_generated_station_projection_preserves_inspector_created_elements() -> None:
    payload, _setup = _wizard_generated_payload(1, False, 2, 4)
    demand_nodes = [
        node for node in payload["nodes"] if node.get("data", {}).get("demand_flow")
    ]
    first = compile_react_flow_payload(payload)
    payload["nodes"] = [*first["react_flow"]["nodes"], *demand_nodes]

    second = compile_react_flow_payload(payload)

    assert second["summary"]["status"] == "ok"
    created = [
        node
        for node in second["react_flow"]["nodes"]
        if node.get("data", {}).get("inspector_created")
    ]
    assert len(created) >= 7


@pytest.mark.parametrize(
    "template_id",
    ("scratch_single_level", "scratch_two_level", "scratch_three_level"),
)
def test_generated_custom_station_runs_goal_graph_jupedsim_preview(template_id: str) -> None:
    result = simulate_design_payload(_generated_payload(template_id))

    assert result["status"] == "ok", result.get("error")
    assert result["compile_summary"]["status"] == "ok"
    assert result["trajectory_report"] is not None
