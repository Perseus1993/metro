from __future__ import annotations

import copy
import json
import random
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from sandbox.metro_station_sandbox.design import (
    apply_react_flow_nodes,
    create_design,
    to_react_flow,
    validate_design,
)
from metro_station_designer.server import (
    build_design_payload,
    compile_react_flow_payload,
    simulate_design_payload,
    start_simulation_job,
    template_catalog_payload,
)


TEMPLATE_IDS = (
    "two_level_island_platform",
    "three_level_transfer",
    "single_level_terminal",
    "visual_demo_station",
)


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_flexible_layout_contract_accepts_all_baseline_templates(template_id: str) -> None:
    issues = validate_design(create_design(template_id))

    assert issues == []


def test_palette_exposes_the_same_size_limits_as_compiled_nodes() -> None:
    catalog = template_catalog_payload()
    components = {item["kind"]: item for item in catalog["component_palette"]}
    payload = build_design_payload("single_level_terminal")
    gate_node = next(
        node for node in payload["react_flow"]["nodes"] if node["id"] == "element:gate_bank_a"
    )

    assert components["gate"]["size_limits_m"] == gate_node["data"]["size_limits_m"]
    assert components["gate"]["size_limits_m"] == {
        "min_width_m": 4.0,
        "max_width_m": 30.0,
        "min_height_m": 1.5,
        "max_height_m": 10.0,
    }


def test_gate_drag_atomically_moves_ports_queue_and_service_point() -> None:
    document = create_design("single_level_terminal")
    nodes = to_react_flow(document)["nodes"]
    gate_node = next(node for node in nodes if node["id"] == "element:gate_bank_a")
    gate_node["position"] = {
        "x": gate_node["position"]["x"] + 3.0,
        "y": gate_node["position"]["y"] + 2.0,
    }
    original_gate = document.element_by_id()["gate_bank_a"]
    original_queue = next(queue for queue in document.queues if queue.owner_element_id == "gate_bank_a")

    moved = apply_react_flow_nodes(document, nodes)
    moved_gate = moved.element_by_id()["gate_bank_a"]
    moved_queue = next(queue for queue in moved.queues if queue.id == original_queue.id)

    assert moved_gate.geometry.bounds() == pytest.approx((21.0, 22.0, 39.0, 25.5))
    for original_port, moved_port in zip(original_gate.ports, moved_gate.ports, strict=True):
        assert moved_port.id == original_port.id
        assert moved_port.position_m == pytest.approx(
            (original_port.position_m[0] + 3.0, original_port.position_m[1] + 2.0)
        )
    assert moved_queue.geometry.bounds() == pytest.approx((21.0, 26.0, 39.0, 35.0))
    assert moved_queue.service_point_m == pytest.approx((30.0, 25.5))
    assert validate_design(moved) == []


def test_explicit_resize_scales_ports_and_queue_anchor_without_resizing_queue() -> None:
    document = create_design("single_level_terminal")
    nodes = to_react_flow(document)["nodes"]
    gate_node = next(node for node in nodes if node["id"] == "element:gate_bank_a")
    gate_node["data"]["inspector_size_m"] = {"width": 20.0, "height": 4.0}
    original_queue = next(queue for queue in document.queues if queue.owner_element_id == "gate_bank_a")

    resized = apply_react_flow_nodes(document, nodes)
    resized_gate = resized.element_by_id()["gate_bank_a"]
    resized_queue = next(queue for queue in resized.queues if queue.id == original_queue.id)

    assert resized_gate.geometry.width_m == 20.0
    assert resized_gate.geometry.height_m == 4.0
    assert all(port.position_m == pytest.approx((28.0, 22.0)) for port in resized_gate.ports)
    assert resized_queue.geometry.bounds() == pytest.approx((19.0, 24.5, 37.0, 33.5))
    assert resized_queue.service_point_m == pytest.approx((28.0, 24.0))
    assert resized_queue.geometry.width_m == original_queue.geometry.width_m
    assert resized_queue.geometry.height_m == original_queue.geometry.height_m
    assert validate_design(resized) == []


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("too_small", "layout.component_width_out_of_range"),
        ("outside", "layout.component_outside_level_footprint"),
        ("overlap", "layout.components_overlap"),
    ),
)
def test_invalid_drag_or_resize_has_a_stable_reason(mutation: str, expected_code: str) -> None:
    payload = build_design_payload("single_level_terminal")
    nodes = payload["react_flow"]["nodes"]
    gate_node = next(node for node in nodes if node["id"] == "element:gate_bank_a")
    if mutation == "too_small":
        gate_node["data"]["inspector_size_m"] = {"width": 2.0, "height": 3.5}
    elif mutation == "outside":
        gate_node["position"] = {"x": 100.0, "y": 20.0}
    else:
        gate_node["position"] = {"x": 82.0, "y": 12.0}

    compiled = compile_react_flow_payload(
        {
            "template_id": "single_level_terminal",
            "nodes": nodes,
            "edges": payload["react_flow"]["edges"],
        }
    )
    issue_codes = {issue["code"] for issue in compiled["validation_issues"]}

    assert compiled["summary"]["status"] == "error"
    assert expected_code in issue_codes


def test_nonblocking_scene_annotation_does_not_trigger_physical_overlap() -> None:
    document = create_design("single_level_terminal")
    gate = document.element_by_id()["gate_bank_a"]
    decoration = next(item for item in document.elements if item.kind == "shop")
    decoration = replace(
        decoration,
        geometry=gate.geometry,
        metadata={
            **decoration.metadata,
            "presentation_only": True,
            "blocking": False,
        },
    )
    annotated = replace(
        document,
        elements=tuple(
            decoration if item.id == decoration.id else item
            for item in document.elements
        ),
    )

    issue_codes = {issue.code for issue in validate_design(annotated)}

    assert "layout.components_overlap" not in issue_codes
    assert "layout.component_clearance_too_small" not in issue_codes


def test_minimum_simulatable_layout_requires_entrance_gates_and_platform() -> None:
    document = create_design("single_level_terminal")
    incomplete = replace(
        document,
        elements=tuple(
            element
            for element in document.elements
            if element.kind not in {"entrance", "gate", "platform_edge"}
        ),
    )
    issue_codes = {issue.code for issue in validate_design(incomplete)}

    assert "layout.required_entrance_missing" in issue_codes
    assert "layout.required_entry_gate_missing" in issue_codes
    assert "layout.required_exit_gate_missing" in issue_codes
    assert "layout.required_platform_edge_missing" in issue_codes


def test_invalid_layout_is_rejected_before_a_simulation_job_is_created() -> None:
    payload = build_design_payload("single_level_terminal")
    gate_node = next(
        node
        for node in payload["react_flow"]["nodes"]
        if node["id"] == "element:gate_bank_a"
    )
    gate_node["position"] = {"x": 82.0, "y": 12.0}

    result = start_simulation_job(
        {
            "template_id": "single_level_terminal",
            "nodes": payload["react_flow"]["nodes"],
            "edges": payload["react_flow"]["edges"],
            "entry_count_hour": 30,
            "exit_count_hour": 0,
            "minutes": 1,
        }
    )

    assert result["status"] == "error"
    assert "job_id" not in result
    assert result["compile_summary"]["status"] == "error"


@pytest.mark.parametrize("seed", (41, 42, 43))
def test_valid_drag_runs_small_goal_graph_jupedsim_preview(seed: int) -> None:
    payload = build_design_payload("single_level_terminal")
    gate_node = next(
        node
        for node in payload["react_flow"]["nodes"]
        if node["id"] == "element:gate_bank_a"
    )
    gate_node["position"] = {
        "x": gate_node["position"]["x"] + 1.0,
        "y": gate_node["position"]["y"],
    }

    result = simulate_design_payload(
        {
            "template_id": "single_level_terminal",
            "nodes": payload["react_flow"]["nodes"],
            "edges": payload["react_flow"]["edges"],
            "entry_count_hour": 30,
            "exit_count_hour": 0,
            "minutes": 1,
            "tick_seconds": 10,
            "seed": seed,
            "movement_backend": "batched_jupedsim",
        }
    )

    assert result["status"] == "ok", result.get("error")
    assert result["compile_summary"]["status"] == "ok"
    assert result["trajectory_report"] is not None


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
@pytest.mark.parametrize("chunk_index", range(4))
def test_two_thousand_random_drag_payloads_are_deterministic_and_safe(
    template_id: str,
    chunk_index: int,
) -> None:
    # Sixteen independently runnable 125-payload shards keep the complete
    # 2,000-case corpus practical under the per-test watchdog.
    rng = random.Random(f"20260713:{template_id}")
    valid_count = 0
    invalid_count = 0
    document = create_design(template_id)
    flow = to_react_flow(document)
    movable_ids = [
        node["id"]
        for node in flow["nodes"]
        if node.get("draggable") and str(node["id"]).startswith("element:")
    ]
    assert movable_ids
    chunk_size = 125
    for case_index in range(500):
        nodes = copy.deepcopy(flow["nodes"])
        node_id = rng.choice(movable_ids)
        node = next(candidate for candidate in nodes if candidate["id"] == node_id)
        if rng.random() < 0.7:
            node["position"] = {
                "x": node["position"]["x"] + rng.uniform(-0.1, 0.1),
                "y": node["position"]["y"] + rng.uniform(-0.1, 0.1),
            }
        else:
            node["position"] = {
                "x": rng.uniform(-5.0, document.constraints.canvas_width_m + 5.0),
                "y": rng.uniform(-5.0, document.constraints.canvas_height_m + 5.0),
            }
        if node["data"].get("resizable") and rng.random() < 0.15:
            node["data"]["inspector_size_m"] = {
                "width": rng.uniform(0.2, 40.0),
                "height": rng.uniform(0.2, 25.0),
            }

        if case_index // chunk_size != chunk_index:
            continue

        edited = apply_react_flow_nodes(document, nodes)
        first = [issue.as_dict() for issue in validate_design(edited)]
        second = [issue.as_dict() for issue in validate_design(edited)]

        assert first == second
        assert all(issue["code"] and issue["path"] and issue["message"] for issue in first)
        if any(issue["severity"] == "error" for issue in first):
            invalid_count += 1
        else:
            valid_count += 1

    assert valid_count > 0
    assert invalid_count > 0
    assert valid_count + invalid_count == chunk_size


def test_frontend_moves_attached_queue_in_the_same_drag_change() -> None:
    module_path = (
        Path("apps/station_designer/src/metro_station_designer/flow_state.js")
        .resolve()
        .as_uri()
    )
    script = f"""
      import {{ applyInspectorDimensions, moveAttachedQueues }} from {json.dumps(module_path)};
      const nodes = [
        {{ id: 'element:gate', position: {{ x: 10, y: 10 }}, data: {{ element_id: 'gate' }} }},
        {{
          id: 'queue:q',
          position: {{ x: 10, y: 14 }},
          data: {{ owner_element_id: 'gate', service_point_m: [14, 13] }},
        }},
      ];
      const moved = moveAttachedQueues(nodes, new Map([['gate', {{ dx: 3, dy: 2 }}]]));
      const resized = moveAttachedQueues(
        nodes,
        new Map(),
        new Map([['gate', {{
          geometry: {{ x_m: 10, y_m: 10, width_m: 8, height_m: 3 }},
          oldWidth: 8,
          oldHeight: 3,
          newWidth: 10,
          newHeight: 4,
        }}]]),
      );
      const sizedNode = applyInspectorDimensions(nodes[0], {{ width: 10, height: 4 }});
      process.stdout.write(JSON.stringify({{
        moved: moved[1].position,
        resized: resized[1].position,
        sizedNode: {{
          width: sizedNode.width,
          height: sizedNode.height,
          style: sizedNode.style,
          marker: sizedNode.data.inspector_size_m,
        }},
      }}));
    """

    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "moved": {"x": 13, "y": 16},
        "resized": {"x": 11, "y": 15},
        "sizedNode": {
            "width": 10,
            "height": 4,
            "style": {"width": 10, "height": 4},
            "marker": {"width": 10, "height": 4},
        },
    }
