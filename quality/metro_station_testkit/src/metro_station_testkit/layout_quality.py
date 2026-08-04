from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from metro_station.adapters.simulation.compilation.validation import validate_station_design
from metro_station.adapters.simulation.design.geometry import element_shape
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.design.station_generation import QUEUE_COMPONENT_KINDS
from metro_station.adapters.simulation.station.graph import StationGraph


@dataclass(frozen=True)
class LayoutQualityIssue:
    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class LayoutQualityReport:
    design_id: str
    design_fingerprint: str
    level_count: int
    element_count: int
    queue_count: int
    graph_node_count: int
    graph_edge_count: int
    issues: tuple[LayoutQualityIssue, ...]
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, **asdict(self)}


def inspect_layout_quality(document: StationDesignDocument) -> LayoutQualityReport:
    validation_issues = tuple(
        LayoutQualityIssue(issue.severity, issue.code, issue.path, issue.message)
        for issue in validate_station_design(document)
    )
    queue_overlap_issues = _queue_overlap_issues(document)
    level_graph_connected = _level_graph_connected(document)
    graph, graph_issue = _compile_graph(document)
    issues = (*validation_issues, *queue_overlap_issues)
    if graph_issue is not None:
        issues = (*issues, graph_issue)
    queue_owner_ids = {queue.owner_element_id for queue in document.queues}
    expected_queue_owner_ids = {
        element.id for element in document.elements if element.kind in QUEUE_COMPONENT_KINDS
    }
    restored = StationDesignDocument.from_dict(document.as_dict())
    checks = {
        "design_valid": not validation_issues,
        "level_graph_connected": level_graph_connected,
        "queues_clear": not queue_overlap_issues,
        "all_service_components_have_queue": queue_owner_ids == expected_queue_owner_ids,
        "graph_compiles": graph is not None,
        "no_compile_diagnostics": graph is not None and not graph.compile_diagnostics,
        "no_walkable_access_fallback": graph is not None
        and not any(edge.origin == "walkable_access_fallback" for edge in graph.edges),
        "design_round_trip_stable": restored.as_dict() == document.as_dict(),
    }
    return LayoutQualityReport(
        design_id=document.id,
        design_fingerprint=design_fingerprint(document),
        level_count=len(document.levels),
        element_count=len(document.elements),
        queue_count=len(document.queues),
        graph_node_count=0 if graph is None else len(graph.nodes),
        graph_edge_count=0 if graph is None else len(graph.edges),
        issues=issues,
        checks=checks,
    )


def design_fingerprint(document: StationDesignDocument) -> str:
    encoded = json.dumps(
        document.as_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _queue_overlap_issues(
    document: StationDesignDocument,
) -> tuple[LayoutQualityIssue, ...]:
    issues: list[LayoutQualityIssue] = []
    for index, queue in enumerate(document.queues):
        queue_shape = element_shape(queue.geometry)
        for other in document.queues[index + 1 :]:
            if queue.level_id != other.level_id:
                continue
            if _queues_share_vertical_lobby(document, queue, other):
                continue
            area = queue_shape.intersection(element_shape(other.geometry)).area
            if area > 0.01:
                issues.append(_overlap_issue(queue.id, other.id, area, "quality.queues_overlap"))
        for element in document.elements:
            if not _queue_collision_candidate(queue.owner_element_id, queue.level_id, element):
                continue
            area = queue_shape.intersection(element_shape(element.geometry)).area
            if area > 0.01:
                issues.append(
                    _overlap_issue(queue.id, element.id, area, "quality.queue_blocks_component")
                )
    return tuple(issues)


def _queues_share_vertical_lobby(
    document: StationDesignDocument,
    left: Any,
    right: Any,
) -> bool:
    if left.owner_element_id != right.owner_element_id:
        return False
    if left.service_direction == right.service_direction:
        return False
    owner = document.element_by_id().get(left.owner_element_id)
    return owner is not None and owner.kind == "elevator"


def _queue_collision_candidate(owner_id: str, level_id: str, element: Any) -> bool:
    if element.id == owner_id or element.level_id != level_id:
        return False
    if element.role == "floor" or element.kind == "walkable_area":
        return False
    return not (element.kind == "obstacle" and not element.metadata.get("blocking", True))


def _overlap_issue(
    queue_id: str,
    other_id: str,
    area: float,
    code: str,
) -> LayoutQualityIssue:
    return LayoutQualityIssue(
        "error",
        code,
        f"queues.{queue_id}",
        f"{queue_id} overlaps {other_id} by {area:.2f} square meters",
    )


def _level_graph_connected(document: StationDesignDocument) -> bool:
    level_ids = {level.id for level in document.levels}
    if len(level_ids) <= 1:
        return True
    adjacency = {level_id: set() for level_id in level_ids}
    for connector in document.elements:
        if connector.role != "vertical_connector":
            continue
        connected = set(connector.connects_levels) & level_ids
        for level_id in connected:
            adjacency[level_id].update(connected - {level_id})
    seen: set[str] = set()
    stack = [next(iter(level_ids))]
    while stack:
        level_id = stack.pop()
        if level_id in seen:
            continue
        seen.add(level_id)
        stack.extend(adjacency[level_id] - seen)
    return seen == level_ids


def _compile_graph(
    document: StationDesignDocument,
) -> tuple[StationGraph | None, LayoutQualityIssue | None]:
    try:
        return StationGraph.from_design(document), None
    except Exception as exc:
        return None, LayoutQualityIssue(
            "error",
            "quality.graph_compile_failed",
            "connections",
            f"{type(exc).__name__}: {exc}",
        )
