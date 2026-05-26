from __future__ import annotations

from typing import Any

from .scenario import StationSandboxScenario
from .station_graph import StationGraph


def geometry_payload(scenario: StationSandboxScenario) -> dict[str, Any]:
    if scenario.station_design is not None:
        document = scenario.station_design
        station_graph = StationGraph.from_design(document)
        return {
            "source": "design_document",
            "width": document.constraints.canvas_width_m,
            "height": document.constraints.canvas_height_m,
            "levels": [
                {
                    "id": level.id,
                    "label": level.label,
                    "elevation_m": level.elevation_m,
                    "order": level.order,
                    "footprint": level.footprint,
                }
                for level in document.levels
            ],
            "elements": [
                {
                    "id": element.id,
                    "kind": element.kind,
                    "role": element.role,
                    "level_id": element.level_id,
                    "label": element.label,
                    "metadata": element.metadata,
                    "gate_direction": element.gate_direction,
                    "direction": element.direction,
                    "line_id": element.line_id,
                    "geometry": element.geometry.as_dict(),
                }
                for element in document.elements
            ],
            "queues": [
                {
                    "id": queue.id,
                    "owner_element_id": queue.owner_element_id,
                    "kind": queue.kind,
                    "label": queue.label,
                    "geometry": queue.geometry.as_dict(),
                    "service_point_m": queue.service_point_m,
                }
                for queue in document.queues
            ],
            "connections": [
                {
                    "id": connection.id,
                    "source_id": connection.source_id,
                    "target_id": connection.target_id,
                    "kind": connection.kind,
                    "bidirectional": connection.bidirectional,
                }
                for connection in document.connections
            ],
            "element_centers": {
                element.id: element.geometry.center() for element in document.elements
            },
            "graph_nodes": [
                {
                    "id": node.node_id,
                    "level_id": node.level_id,
                    "position": node.position,
                    "kind": node.kind,
                    "element_id": node.element_id,
                    "line_id": node.line_id,
                    "direction": node.direction,
                    "facility_stage": node.facility_stage,
                }
                for node in station_graph.nodes.values()
            ],
            "graph_edges": [
                {
                    "from": edge.from_node,
                    "to": edge.to_node,
                    "kind": edge.kind,
                    "facility_stage": edge.facility_stage,
                    "level_change": edge.level_change,
                }
                for edge in station_graph.edges
            ],
        }

    geometry = scenario.geometry
    return {
        "source": "station_geometry",
        "width": geometry.width,
        "height": geometry.height,
        "entrances": geometry.entrances,
        "unpaid_hall_center": geometry.unpaid_hall_center,
        "gate_decision_point": geometry.gate_decision_point,
        "paid_hall_center": geometry.paid_hall_center,
        "vertical_decision_point": geometry.vertical_decision_point,
        "platform_transfer_hub": geometry.platform_transfer_hub,
        "platform_entry": geometry.platform_entry,
        "train_door": geometry.train_door,
        "gates": [
            {
                "label": gate.label,
                "position": gate.position,
                "queue_anchor": gate.queue_anchor,
                "exit_position": gate.exit_position,
            }
            for gate in geometry.gates
        ],
        "exit_gates": [
            {
                "label": gate.label,
                "position": gate.position,
                "queue_anchor": gate.queue_anchor,
                "exit_position": gate.exit_position,
            }
            for gate in geometry.exit_gates
        ],
        "vertical_transports": [
            {
                "label": item.label,
                "kind": item.kind,
                "direction": item.direction,
                "position": item.position,
                "queue_anchor": item.queue_anchor,
                "exit_position": item.exit_position,
                "speed_units_per_tick": item.speed_units_per_tick,
            }
            for item in geometry.vertical_transports
        ],
        "boarding_doors": [
            {
                "label": door.label,
                "position": door.position,
                "queue_anchor": door.queue_anchor,
                "persons_per_min": door.persons_per_min,
                "train_direction": door.train_direction,
                "line_id": door.line_id,
            }
            for door in geometry.boarding_doors
        ],
    }
