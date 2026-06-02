from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from math import cos, hypot, radians, sin

from shapely.geometry import Point as ShapelyPoint

from ..planning.plan import AgentState, FacilityStage, RouteKey
from ..design.helpers import (
    gate_direction as _gate_direction,
    platform_direction as _platform_direction,
    platform_line_id as _platform_line_id,
    vertical_direction as _vertical_direction,
)
from ..design.schema import DesignElement, QueueSpec, StationDesignDocument
from ..design.validation import validate_design
from ..facilities.process import FacilityKind, FacilitySpec, QueueLayout
from .geometry import (
    dedupe_points,
    document_walkable_geometry,
    element_shape,
    project_to_safe_point,
    safe_core,
)
from .scenario import StationGeometry, StationSandboxScenario
from .graph import GraphEdge, GraphNode, StationGraph


Point = tuple[float, float]


@dataclass(frozen=True)
class LayoutNode:
    node_id: str
    label: str
    position: Point
    level: str


@dataclass(frozen=True)
class LayoutEdge:
    from_node: str
    to_node: str
    label: str


@dataclass(frozen=True)
class LayoutGraph:
    """Derived station process graph used by the Mesa model.

    StationGeometry remains the compact source of truth for this sandbox. This
    graph turns it into named nodes, facility process specs, and common route
    fragments so passenger state code does not hand-roll facility coordinates.
    """

    geometry: StationGeometry
    nodes: dict[str, LayoutNode]
    edges: tuple[LayoutEdge, ...]
    facilities: tuple[FacilitySpec, ...]
    station_graph: StationGraph | None = field(default=None, compare=False, repr=False)
    route_registry: dict[str, Callable[[Point, object | None], tuple[Point, ...]]] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )
    platform_waiting_slots_per_row: int = 28
    platform_waiting_row_cycle: int = 9
    platform_waiting_x_step: float = 0.95
    platform_waiting_min_y: float = 55.0
    platform_waiting_max_y: float = 82.0
    platform_waiting_max_x: float = 102.0

    @classmethod
    def from_scenario(cls, scenario: StationSandboxScenario) -> "LayoutGraph":
        geom = scenario.geometry
        facilities: list[FacilitySpec] = []

        for index, gate in enumerate(geom.gates):
            facilities.append(
                FacilitySpec(
                    facility_id=f"entry_gate:{index}",
                    stage=FacilityStage.ENTRY_GATE.value,
                    label=gate.label,
                    kind=FacilityKind.GATE.value,
                    direction="in",
                    position=gate.position,
                    queue_layout=QueueLayout(
                        anchor=gate.queue_anchor,
                        per_row=scenario.gate_queue_slots_per_row,
                        col_step=(-geom.queue_spacing, 0.0),
                        row_step=(0.0, 1.0),
                    ),
                    exit_position=gate.exit_position,
                    service_persons_per_min=scenario.gate_service_persons_per_min,
                    queue_state=AgentState.QUEUEING_GATE.value,
                    service_state=AgentState.PASSING_GATE.value,
                    release_route=(gate.position, gate.exit_position),
                    legacy_index=index,
                    entry_level_id="B1",
                    exit_level_id="B1",
                )
            )

        for index, gate in enumerate(geom.exit_gates):
            facilities.append(
                FacilitySpec(
                    facility_id=f"exit_gate:{index}",
                    stage=FacilityStage.EXIT_GATE.value,
                    label=gate.label,
                    kind=FacilityKind.GATE.value,
                    direction="out",
                    position=gate.position,
                    queue_layout=QueueLayout(
                        anchor=gate.queue_anchor,
                        per_row=scenario.gate_queue_slots_per_row,
                        col_step=(geom.queue_spacing, 0.0),
                        row_step=(0.0, 1.0),
                    ),
                    exit_position=gate.exit_position,
                    service_persons_per_min=scenario.gate_service_persons_per_min,
                    queue_state=AgentState.QUEUEING_EXIT_GATE.value,
                    service_state=AgentState.PASSING_EXIT_GATE.value,
                    release_route=(gate.position, gate.exit_position),
                    legacy_index=index,
                    entry_level_id="B1",
                    exit_level_id="B1",
                )
            )

        for index, transport in enumerate(geom.vertical_transports):
            facilities.append(
                FacilitySpec(
                    facility_id=f"vertical:{index}",
                    stage=FacilityStage.VERTICAL_TRANSFER.value,
                    label=transport.label,
                    kind=transport.kind,
                    direction=transport.direction,
                    position=transport.position,
                    queue_layout=QueueLayout(
                        anchor=transport.queue_anchor,
                        per_row=scenario.vertical_queue_slots_per_row,
                        col_step=(-geom.queue_spacing, 0.0),
                        row_step=(0.0, 0.9),
                    ),
                    exit_position=transport.exit_position,
                    service_persons_per_min=transport.persons_per_min,
                    queue_state=AgentState.QUEUEING_VERTICAL.value,
                    service_state=AgentState.RIDING_VERTICAL.value,
                    release_route=(transport.position, transport.exit_position),
                    speed_units_per_tick=transport.speed_units_per_tick,
                    legacy_index=index,
                    entry_level_id="B1" if transport.direction in {"down", "both"} else "B2",
                    exit_level_id="B2" if transport.direction in {"down", "both"} else "B1",
                )
            )

        for index, door in enumerate(geom.boarding_doors):
            facilities.append(
                FacilitySpec(
                    facility_id=f"boarding_door:{index}",
                    stage=FacilityStage.BOARDING_DOOR.value,
                    label=door.label,
                    kind=FacilityKind.TRAIN_DOOR.value,
                    direction=door.train_direction,
                    position=door.position,
                    queue_layout=QueueLayout(
                        anchor=door.queue_anchor,
                        per_row=scenario.boarding_queue_slots_per_row,
                        col_step=(-geom.queue_spacing, 0.0),
                        row_step=(0.0, 0.75),
                    ),
                    exit_position=door.position,
                    service_persons_per_min=door.persons_per_min,
                    queue_state=AgentState.QUEUEING_DOOR.value,
                    service_state=AgentState.BOARDING_TRAIN.value,
                    release_route=(door.queue_anchor, door.position),
                    train_gated=True,
                    train_capacity_limited=True,
                    legacy_index=index,
                    line_id=door.line_id,
                    platform_id=f"platform:{door.line_id}:{door.train_direction}",
                    entry_level_id="B2",
                    exit_level_id="B2",
                )
            )

        nodes = {
            "unpaid_hall": LayoutNode(
                "unpaid_hall", "unpaid concourse", geom.unpaid_hall_center, "B1"
            ),
            "gate_decision": LayoutNode(
                "gate_decision", "entry gate decision", geom.gate_decision_point, "B1"
            ),
            "paid_hall": LayoutNode("paid_hall", "paid concourse", geom.paid_hall_center, "B1"),
            "vertical_decision": LayoutNode(
                "vertical_decision",
                "vertical facility decision",
                geom.vertical_decision_point,
                "B1",
            ),
            "platform_hub": LayoutNode(
                "platform_hub", "platform transfer hub", geom.platform_transfer_hub, "B2"
            ),
            "platform_entry": LayoutNode(
                "platform_entry", "platform waiting entry", geom.platform_entry, "B2"
            ),
        }
        edges = (
            LayoutEdge("unpaid_hall", "gate_decision", "approach entry gates"),
            LayoutEdge("gate_decision", "paid_hall", "pass entry gate"),
            LayoutEdge("paid_hall", "vertical_decision", "approach vertical transfer"),
            LayoutEdge("vertical_decision", "platform_hub", "use vertical transfer"),
            LayoutEdge("platform_hub", "platform_entry", "enter platform"),
        )
        return cls(
            geometry=geom,
            nodes=nodes,
            edges=edges,
            facilities=tuple(facilities),
            platform_waiting_slots_per_row=scenario.platform_waiting_slots_per_row,
            platform_waiting_row_cycle=scenario.platform_waiting_row_cycle,
            platform_waiting_x_step=scenario.platform_waiting_x_step,
            platform_waiting_min_y=scenario.platform_waiting_min_y,
            platform_waiting_max_y=scenario.platform_waiting_max_y,
            platform_waiting_max_x=scenario.platform_waiting_max_x,
        )

    @classmethod
    def from_design_document(
        cls,
        document: StationDesignDocument,
        scenario: StationSandboxScenario,
    ) -> "LayoutGraph":
        issues = validate_design(document)
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            summary = "; ".join(f"{issue.code}: {issue.message}" for issue in errors[:5])
            raise ValueError(f"Station design validation failed: {summary}")
        return cls.from_station_graph(StationGraph.from_design(document), scenario)

    @classmethod
    def from_station_graph(
        cls,
        station_graph: StationGraph,
        scenario: StationSandboxScenario,
    ) -> "LayoutGraph":
        document = station_graph.source_document
        geometry = StationGeometry(
            width=(
                scenario.geometry.width if document is None else document.constraints.canvas_width_m
            ),
            height=(
                scenario.geometry.height
                if document is None
                else document.constraints.canvas_height_m
            ),
        )
        return cls(
            geometry=geometry,
            nodes=_layout_nodes_from_station_graph(station_graph.nodes),
            edges=_layout_edges_from_station_graph(station_graph.edges),
            facilities=tuple(_facility_specs_from_station_graph(station_graph, scenario)),
            station_graph=station_graph,
            route_registry=_route_registry_from_station_graph(station_graph),
            platform_waiting_slots_per_row=scenario.platform_waiting_slots_per_row,
            platform_waiting_row_cycle=scenario.platform_waiting_row_cycle,
            platform_waiting_x_step=scenario.platform_waiting_x_step,
            platform_waiting_min_y=scenario.platform_waiting_min_y,
            platform_waiting_max_y=min(
                scenario.platform_waiting_max_y,
                geometry.height - 1.0,
            ),
            platform_waiting_max_x=min(
                scenario.platform_waiting_max_x,
                geometry.width - 1.0,
            ),
        )

    def entry_route(self, start: Point) -> tuple[Point, ...]:
        return (
            (self.geometry.unpaid_hall_center[0], start[1]),
            self.geometry.unpaid_hall_center,
            self.geometry.gate_decision_point,
        )

    def after_gate_route(self) -> tuple[Point, ...]:
        return (self.geometry.paid_hall_center, self.geometry.vertical_decision_point)

    def after_vertical_route(self) -> tuple[Point, ...]:
        return (self.geometry.platform_transfer_hub, self.geometry.platform_entry)

    def platform_to_vertical_route(self) -> tuple[Point, ...]:
        return (self.geometry.platform_transfer_hub, self.geometry.vertical_decision_point)

    def after_exit_vertical_route(self) -> tuple[Point, ...]:
        return (self.geometry.paid_hall_center, self.geometry.gate_decision_point)

    def route_builders(self) -> dict[str, Callable[[Point, object | None], tuple[Point, ...]]]:
        if self.route_registry:
            return self.route_registry
        return {
            RouteKey.CURRENT_POSITION.value: lambda start, _passenger=None: (start,),
            RouteKey.ENTRY_GATE_DECISION.value: lambda start, _passenger=None: self.entry_route(
                start
            ),
            RouteKey.AFTER_GATE.value: lambda _start, _passenger=None: self.after_gate_route(),
            RouteKey.AFTER_VERTICAL.value: lambda _start,
            _passenger=None: self.after_vertical_route(),
            RouteKey.PLATFORM_TO_VERTICAL.value: lambda _start,
            _passenger=None: self.platform_to_vertical_route(),
            RouteKey.AFTER_EXIT_VERTICAL.value: lambda _start,
            _passenger=None: self.after_exit_vertical_route(),
        }

    def route_for_key(
        self,
        route_key: str | RouteKey,
        start: Point,
        passenger: object | None = None,
    ) -> tuple[Point, ...]:
        key = route_key.value if isinstance(route_key, RouteKey) else str(route_key)
        try:
            return self.route_builders()[key](start, passenger)
        except KeyError as exc:
            raise KeyError(f"Unknown layout route key: {key}") from exc

    def platform_waiting_position(self, index: int) -> Point:
        geom = self.geometry
        per_row = self._platform_slots_per_row()
        row = index // per_row
        col = index % per_row
        row_cycle = self._platform_row_cycle()
        y_offset = (row % row_cycle - (row_cycle - 1) / 2.0) * geom.platform_spacing
        x_offset = (col % per_row) * self._platform_x_step()
        return (
            min(self._platform_max_x(), geom.platform_entry[0] + 1.0 + x_offset),
            max(
                self._platform_min_y(),
                min(self._platform_max_y(), geom.platform_center[1] + y_offset),
            ),
        )

    def facilities_for_stage(self, stage: str | FacilityStage) -> tuple[FacilitySpec, ...]:
        stage_value = stage.value if isinstance(stage, FacilityStage) else str(stage)
        return tuple(facility for facility in self.facilities if facility.stage == stage_value)

    def platform_descriptors(self) -> tuple[tuple[str, str, str], ...]:
        descriptors = {
            (facility.platform_id, facility.line_id, facility.direction)
            for facility in self.facilities
            if facility.stage == FacilityStage.BOARDING_DOOR.value
            and facility.platform_id is not None
        }
        if not descriptors:
            return (("platform:default:down", "default", "down"),)
        return tuple(sorted(descriptors))

    def _platform_slots_per_row(self) -> int:
        return self.platform_waiting_slots_per_row

    def _platform_row_cycle(self) -> int:
        return self.platform_waiting_row_cycle

    def _platform_x_step(self) -> float:
        return self.platform_waiting_x_step

    def _platform_min_y(self) -> float:
        return self.platform_waiting_min_y

    def _platform_max_y(self) -> float:
        return self.platform_waiting_max_y

    def _platform_max_x(self) -> float:
        return self.platform_waiting_max_x


def _layout_nodes_from_station_graph(nodes: dict[str, GraphNode]) -> dict[str, LayoutNode]:
    return {
        node_id: LayoutNode(node.node_id, node.node_id, node.position, node.level_id)
        for node_id, node in nodes.items()
    }


def _layout_edges_from_station_graph(edges: tuple[GraphEdge, ...]) -> tuple[LayoutEdge, ...]:
    return tuple(
        LayoutEdge(edge.from_node, edge.to_node, edge.kind)
        for edge in edges
        if edge.kind in {"walk", "vertical"}
    )


def _facility_specs_from_station_graph(
    station_graph: StationGraph,
    scenario: StationSandboxScenario,
) -> list[FacilitySpec]:
    document = station_graph.source_document
    if document is None:
        return []

    queues_by_owner = {queue.owner_element_id: queue for queue in document.queues}
    levels_by_id = document.level_by_id()
    walkable_geometry = document_walkable_geometry(document)
    facilities: list[FacilitySpec] = []

    for element in document.elements:
        queue = queues_by_owner.get(element.id)
        if element.kind == "gate":
            facilities.extend(
                _gate_facility_specs(
                    element,
                    queue,
                    station_graph,
                    scenario,
                    walkable_geometry=walkable_geometry,
                )
            )
        elif element.role == "vertical_connector":
            ordered_levels = sorted(
                element.connects_levels,
                key=lambda level_id: levels_by_id[level_id].elevation_m,
                reverse=True,
            )
            direction = _vertical_direction(element)
            for upper, lower in zip(ordered_levels, ordered_levels[1:]):
                upper_position = _node_position(station_graph, f"vertical:{element.id}:{upper}")
                lower_position = _node_position(station_graph, f"vertical:{element.id}:{lower}")
                if direction in {"down", "both"}:
                    facilities.append(
                        _vertical_facility_spec(
                            element,
                            queue if queue is not None and queue.level_id == upper else None,
                            scenario,
                            direction="down",
                            position=upper_position,
                            exit_position=lower_position,
                            level_pair=(upper, lower),
                            walkable_geometry=walkable_geometry,
                        )
                    )
                if direction in {"up", "both"}:
                    facilities.append(
                        _vertical_facility_spec(
                            element,
                            queue if queue is not None and queue.level_id == lower else None,
                            scenario,
                            direction="up",
                            position=lower_position,
                            exit_position=upper_position,
                            level_pair=(lower, upper),
                            walkable_geometry=walkable_geometry,
                        )
                    )
        elif element.kind == "platform_edge":
            position = _node_position(station_graph, f"platform:{element.id}")
            line_id = _platform_line_id(element)
            direction = _platform_direction(element)
            queue_layout = _queue_layout(
                queue,
                default_anchor=position,
                per_row=scenario.boarding_queue_slots_per_row,
                walkable_geometry=walkable_geometry,
            )
            facilities.append(
                FacilitySpec(
                    facility_id=f"boarding_door:{element.id}",
                    stage=FacilityStage.BOARDING_DOOR.value,
                    label=element.label,
                    kind=FacilityKind.TRAIN_DOOR.value,
                    direction=direction,
                    position=position,
                    queue_layout=queue_layout,
                    exit_position=position,
                    service_persons_per_min=scenario.boarding_persons_per_min,
                    queue_state=AgentState.QUEUEING_DOOR.value,
                    service_state=AgentState.BOARDING_TRAIN.value,
                    release_route=(queue_layout.anchor, position),
                    train_gated=True,
                    train_capacity_limited=True,
                    line_id=line_id,
                    platform_id=f"platform:{line_id}:{direction}",
                    entry_level_id=element.level_id,
                    exit_level_id=element.level_id,
                )
            )

    return facilities


def _gate_facility_specs(
    element: DesignElement,
    queue: QueueSpec | None,
    station_graph: StationGraph,
    scenario: StationSandboxScenario,
    *,
    walkable_geometry,
) -> list[FacilitySpec]:
    gate_direction = _gate_direction(element)
    facilities: list[FacilitySpec] = []
    if gate_direction in {"entry", "bidirectional"}:
        position = _node_position(station_graph, f"gate:{element.id}:entry")
        exit_position = _node_position(station_graph, f"gate:{element.id}:paid")
        facilities.extend(
            _gate_lane_facility_specs(
                element,
                queue if gate_direction == "entry" else None,
                scenario,
                stage=FacilityStage.ENTRY_GATE.value,
                facility_prefix="entry_gate",
                direction="in",
                position=position,
                exit_position=exit_position,
                queue_state=AgentState.QUEUEING_GATE.value,
                service_state=AgentState.PASSING_GATE.value,
                walkable_geometry=walkable_geometry,
            )
        )
    if gate_direction in {"exit", "bidirectional"}:
        position = _node_position(station_graph, f"gate:{element.id}:unpaid")
        exit_position = _node_position(station_graph, f"gate:{element.id}:exit")
        facilities.extend(
            _gate_lane_facility_specs(
                element,
                queue,
                scenario,
                stage=FacilityStage.EXIT_GATE.value,
                facility_prefix="exit_gate",
                direction="out",
                position=position,
                exit_position=exit_position,
                queue_state=AgentState.QUEUEING_EXIT_GATE.value,
                service_state=AgentState.PASSING_EXIT_GATE.value,
                walkable_geometry=walkable_geometry,
            )
        )
    return facilities


def _gate_lane_facility_specs(
    element: DesignElement,
    queue: QueueSpec | None,
    scenario: StationSandboxScenario,
    *,
    stage: str,
    facility_prefix: str,
    direction: str,
    position: Point,
    exit_position: Point,
    queue_state: str,
    service_state: str,
    walkable_geometry,
) -> list[FacilitySpec]:
    lane_count = _gate_lane_count(element)
    base_layout = _queue_layout(
        queue,
        default_anchor=position,
        per_row=scenario.gate_queue_slots_per_row,
        walkable_geometry=walkable_geometry,
    )
    lane_positions = _gate_lane_positions(element, lane_count, position, exit_position)
    facilities: list[FacilitySpec] = []
    for lane_index, (lane_position, lane_exit_position) in enumerate(lane_positions):
        facility_id = (
            f"{facility_prefix}:{element.id}"
            if lane_count == 1
            else f"{facility_prefix}:{element.id}:lane_{lane_index + 1}"
        )
        label = (
            element.label
            if lane_count == 1
            else f"{element.label} lane {lane_index + 1}"
        )
        facilities.append(
            FacilitySpec(
                facility_id=facility_id,
                stage=stage,
                label=label,
                kind=FacilityKind.GATE.value,
                direction=direction,
                position=lane_position,
                queue_layout=_gate_lane_queue_layout(
                    base_layout,
                    element,
                    queue=queue,
                    lane_index=lane_index,
                    lane_count=lane_count,
                    lane_position=lane_position,
                    walkable_geometry=walkable_geometry,
                ),
                exit_position=lane_exit_position,
                service_persons_per_min=scenario.gate_service_persons_per_min,
                queue_state=queue_state,
                service_state=service_state,
                release_route=(lane_position, lane_exit_position),
                entry_level_id=element.level_id,
                exit_level_id=element.level_id,
            )
        )
    return facilities


def _route_registry_from_station_graph(
    station_graph: StationGraph,
) -> dict[str, Callable[[Point, object | None], tuple[Point, ...]]]:
    gate_decision_points = _gate_decision_points_by_stage(station_graph)
    return {
        RouteKey.CURRENT_POSITION.value: lambda start, _passenger=None: (start,),
        RouteKey.ENTRY_GATE_DECISION.value: lambda start,
        _passenger=None: _gate_decision_route(
            station_graph,
            start,
            FacilityStage.ENTRY_GATE.value,
            gate_decision_points.get(FacilityStage.ENTRY_GATE.value, ()),
            start_level_id=_route_start_level(_passenger),
        ),
        RouteKey.AFTER_GATE.value: lambda start,
        _passenger=None: station_graph.route_from_position_to(
            start,
            kind="facility_entry",
            facility_stage=FacilityStage.VERTICAL_TRANSFER.value,
            direction=("down", "both"),
            start_level_id=_route_start_level(_passenger),
            start_kind="facility_exit",
            start_facility_stage=FacilityStage.ENTRY_GATE.value,
        ),
        RouteKey.AFTER_VERTICAL.value: lambda start, passenger=None: _after_vertical_route(
            station_graph, start, passenger
        ),
        RouteKey.PLATFORM_TO_VERTICAL.value: lambda start,
        _passenger=None: station_graph.route_from_position_to(
            start,
            kind="facility_entry",
            facility_stage=FacilityStage.VERTICAL_TRANSFER.value,
            direction=("up", "both"),
            start_level_id=_route_start_level(_passenger),
        ),
        RouteKey.AFTER_EXIT_VERTICAL.value: lambda start,
        _passenger=None: _gate_decision_route(
            station_graph,
            start,
            FacilityStage.EXIT_GATE.value,
            gate_decision_points.get(FacilityStage.EXIT_GATE.value, ()),
            start_level_id=_route_start_level(_passenger),
        ),
    }


def _gate_decision_points_by_stage(
    station_graph: StationGraph,
) -> dict[str, tuple[Point, ...]]:
    document = station_graph.source_document
    if document is None:
        return {}

    queues_by_owner = {queue.owner_element_id: queue for queue in document.queues}
    walkable_geometry = document_walkable_geometry(document)
    points_by_stage: dict[str, list[Point]] = {
        FacilityStage.ENTRY_GATE.value: [],
        FacilityStage.EXIT_GATE.value: [],
    }
    for element in document.elements:
        if element.kind != "gate":
            continue
        queue = queues_by_owner.get(element.id)
        if queue is None:
            continue

        point = _queue_approach_point(queue, walkable_geometry)
        gate_direction = _gate_direction(element)
        if gate_direction in {"entry", "bidirectional"}:
            points_by_stage[FacilityStage.ENTRY_GATE.value].append(point)
        if gate_direction in {"exit", "bidirectional"}:
            points_by_stage[FacilityStage.EXIT_GATE.value].append(point)

    return {stage: tuple(dedupe_points(points)) for stage, points in points_by_stage.items()}


def _queue_approach_point(
    queue: QueueSpec,
    walkable_geometry,
) -> Point:
    shape = element_shape(queue.geometry)
    domain = shape
    if walkable_geometry is not None:
        clipped = shape.intersection(walkable_geometry)
        if not clipped.is_empty:
            domain = clipped

    core = safe_core(domain, min(0.18, max(0.05, queue.spacing_m * 0.2)))
    min_x, min_y, max_x, max_y = core.bounds
    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    service_x, service_y = queue.service_point_m
    span_x = max_x - min_x
    span_y = max_y - min_y

    if abs(service_x - center[0]) >= abs(service_y - center[1]):
        offset = min(max(0.15, queue.spacing_m * 0.5), max(0.0, span_x / 2.0))
        x = min_x + offset if service_x > center[0] else max_x - offset
        raw = (x, center[1])
    else:
        offset = min(max(0.15, queue.spacing_m * 0.5), max(0.0, span_y / 2.0))
        y = min_y + offset if service_y > center[1] else max_y - offset
        raw = (center[0], y)

    return project_to_safe_point(core, raw, clearance=0.0, require_inside=False)


def _gate_decision_route(
    station_graph: StationGraph,
    start: Point,
    stage: str,
    decision_points: tuple[Point, ...],
    *,
    start_level_id: str | None,
) -> tuple[Point, ...]:
    if not decision_points:
        return station_graph.route_from_position_to(
            start,
            kind="facility_entry",
            facility_stage=stage,
            start_level_id=start_level_id,
        )

    decision_point = min(decision_points, key=lambda point: _point_distance(start, point))
    return (decision_point,)


def _route_platform_line_id(passenger: object | None) -> str | None:
    return getattr(passenger, "assigned_line_id", None)


def _after_vertical_route(
    station_graph: StationGraph,
    start: Point,
    passenger: object | None,
) -> tuple[Point, ...]:
    try:
        return station_graph.route_from_position_to(
            start,
            kind="platform",
            direction=_route_platform_direction(passenger),
            line_id=_route_platform_line_id(passenger),
            start_level_id=_route_start_level(passenger),
        )
    except ValueError:
        return station_graph.route_from_position_to(
            start,
            kind="zone",
            start_level_id=_route_start_level(passenger),
        )


def _route_platform_direction(passenger: object | None) -> str | tuple[str | None, ...] | None:
    direction = getattr(passenger, "assigned_direction", None)
    return direction if direction is not None else ("down", None)


def _route_start_level(passenger: object | None) -> str | None:
    return getattr(passenger, "current_level_id", None)


def _vertical_facility_spec(
    element: DesignElement,
    queue: QueueSpec | None,
    scenario: StationSandboxScenario,
    *,
    direction: str,
    position: Point,
    exit_position: Point,
    level_pair: tuple[str, str],
    walkable_geometry,
) -> FacilitySpec:
    queue_layout = _queue_layout(
        queue,
        default_anchor=position,
        per_row=scenario.vertical_queue_slots_per_row,
        walkable_geometry=walkable_geometry,
    )
    return FacilitySpec(
        facility_id=f"vertical:{element.id}:{direction}:{level_pair[0]}:{level_pair[1]}",
        stage=FacilityStage.VERTICAL_TRANSFER.value,
        label=element.label,
        kind=_facility_kind_for_element(element),
        direction=direction,
        position=position,
        queue_layout=queue_layout,
        exit_position=exit_position,
        service_persons_per_min=element.capacity or _default_vertical_service_rate(element),
        queue_state=AgentState.QUEUEING_VERTICAL.value,
        service_state=AgentState.RIDING_VERTICAL.value,
        release_route=(position, exit_position),
        speed_units_per_tick=_vertical_speed(element),
        entry_level_id=level_pair[0],
        exit_level_id=level_pair[1],
    )


def _gate_lane_count(element: DesignElement) -> int:
    return max(1, int(element.capacity or 1))


def _gate_lane_positions(
    element: DesignElement,
    lane_count: int,
    position: Point,
    exit_position: Point,
) -> tuple[tuple[Point, Point], ...]:
    if lane_count <= 1:
        return ((position, exit_position),)

    min_x, min_y, max_x, max_y = element.geometry.bounds()
    split_axis = _gate_split_axis(element)
    positions: list[tuple[Point, Point]] = []
    for lane_index in range(lane_count):
        coordinate = _lane_coordinate(
            min_x if split_axis == "x" else min_y,
            max_x if split_axis == "x" else max_y,
            lane_index,
            lane_count,
        )
        if split_axis == "x":
            lane_position = (coordinate, position[1])
            lane_exit_position = (coordinate, exit_position[1])
        else:
            lane_position = (position[0], coordinate)
            lane_exit_position = (exit_position[0], coordinate)
        positions.append((lane_position, lane_exit_position))
    return tuple(positions)


def _gate_lane_queue_layout(
    base_layout: QueueLayout,
    element: DesignElement,
    *,
    queue: QueueSpec | None,
    lane_index: int,
    lane_count: int,
    lane_position: Point,
    walkable_geometry,
) -> QueueLayout:
    if lane_count <= 1:
        return base_layout

    slots = (
        _queue_slots_from_geometry_for_lane(
            queue,
            element,
            lane_index=lane_index,
            lane_count=lane_count,
            service_point=lane_position,
            walkable_geometry=walkable_geometry,
        )
        if queue is not None
        else _layout_slots_for_lane(base_layout, element, lane_index, lane_count)
    )
    if not slots:
        slots = _default_queue_slots(
            lane_position,
            per_row=1,
            spacing=0.8,
            walkable_geometry=walkable_geometry,
        )[:8]

    if slots:
        ordered = tuple(sorted(slots, key=lambda slot: _point_distance(slot, lane_position)))
        return QueueLayout(
            anchor=ordered[0],
            per_row=1,
            col_step=(0.0, 0.0),
            row_step=(0.0, 0.0),
            slots=ordered,
        )

    return QueueLayout(
        anchor=lane_position,
        per_row=1,
        col_step=(0.0, 0.0),
        row_step=(0.0, 0.8),
    )


def _layout_slots_for_lane(
    layout: QueueLayout,
    element: DesignElement,
    lane_index: int,
    lane_count: int,
) -> tuple[Point, ...]:
    slots = layout.slots or tuple(layout.slot(index) for index in range(max(8, lane_count * 4)))
    if not slots:
        return ()
    return _points_for_gate_lane(slots, element, lane_index, lane_count)


def _queue_slots_from_geometry_for_lane(
    queue: QueueSpec,
    element: DesignElement,
    *,
    lane_index: int,
    lane_count: int,
    service_point: Point,
    walkable_geometry,
) -> tuple[Point, ...]:
    candidates, domain = _queue_slot_candidates(queue, walkable_geometry)
    lane_candidates = _points_for_gate_lane(candidates, element, lane_index, lane_count)
    if not lane_candidates:
        lane_candidates = tuple(sorted(candidates, key=lambda point: _point_distance(point, service_point)))
    capacity = max(4, (queue.capacity + lane_count - 1) // lane_count)
    return tuple(
        dedupe_points(
            _sort_queue_slots_from_service(
                list(lane_candidates),
                service_point,
                queue.direction_deg,
                queue.spacing_m,
                domain,
            )
        )
    )[:capacity]


def _points_for_gate_lane(
    points: tuple[Point, ...],
    element: DesignElement,
    lane_index: int,
    lane_count: int,
) -> tuple[Point, ...]:
    min_x, min_y, max_x, max_y = element.geometry.bounds()
    split_axis = _gate_split_axis(element)
    min_value = min_x if split_axis == "x" else min_y
    max_value = max_x if split_axis == "x" else max_y
    lane_values = tuple(
        _lane_coordinate(min_value, max_value, index, lane_count)
        for index in range(lane_count)
    )

    selected: list[Point] = []
    axis_index = 0 if split_axis == "x" else 1
    for point in points:
        slot_value = point[axis_index]
        nearest_lane = min(
            range(lane_count),
            key=lambda index: abs(slot_value - lane_values[index]),
        )
        if nearest_lane == lane_index:
            selected.append(point)
    return tuple(selected)


def _gate_split_axis(element: DesignElement) -> str:
    min_x, min_y, max_x, max_y = element.geometry.bounds()
    return "x" if max_x - min_x >= max_y - min_y else "y"


def _lane_coordinate(min_value: float, max_value: float, lane_index: int, lane_count: int) -> float:
    if lane_count <= 1:
        return (min_value + max_value) / 2.0
    span = max_value - min_value
    if abs(span) <= 0.001:
        return min_value
    return min_value + (lane_index + 0.5) * span / lane_count


def _queue_layout(
    queue: QueueSpec | None,
    *,
    default_anchor: Point,
    per_row: int,
    walkable_geometry=None,
) -> QueueLayout:
    if queue is None:
        spacing = 0.8
        slots = _default_queue_slots(
            default_anchor,
            per_row=per_row,
            spacing=spacing,
            walkable_geometry=walkable_geometry,
        )
        if slots:
            return QueueLayout(
                anchor=slots[0],
                per_row=max(1, min(per_row, len(slots))),
                col_step=(0.0, 0.0),
                row_step=(0.0, 0.0),
                slots=slots,
            )
        return QueueLayout(
            anchor=default_anchor,
            per_row=max(1, per_row),
            col_step=(-spacing, 0.0),
            row_step=(0.0, spacing),
        )

    spacing = queue.spacing_m
    slots = _queue_slots_from_geometry(queue, walkable_geometry)
    if slots:
        return QueueLayout(
            anchor=slots[0],
            per_row=max(1, min(per_row, len(slots))),
            col_step=(0.0, 0.0),
            row_step=(0.0, 0.0),
            slots=slots,
        )

    angle = radians(queue.direction_deg)
    col_step = (cos(angle) * spacing, sin(angle) * spacing)
    row_step = (-sin(angle) * spacing, cos(angle) * spacing)
    return QueueLayout(
        anchor=queue.service_point_m,
        per_row=max(1, min(per_row, queue.capacity)),
        col_step=col_step,
        row_step=row_step,
    )


def _queue_slots_from_geometry(
    queue: QueueSpec,
    walkable_geometry,
) -> tuple[Point, ...]:
    candidates, domain = _queue_slot_candidates(queue, walkable_geometry)
    return tuple(dedupe_points(_sort_queue_slots(list(candidates), queue, domain)))[: queue.capacity]


def _queue_slot_candidates(
    queue: QueueSpec,
    walkable_geometry,
) -> tuple[tuple[Point, ...], object]:
    shape = element_shape(queue.geometry)
    domain = shape
    if walkable_geometry is not None:
        clipped = shape.intersection(walkable_geometry)
        if not clipped.is_empty:
            domain = clipped

    spacing = max(0.2, float(queue.spacing_m))
    core = safe_core(domain, min(0.18, spacing * 0.2))
    min_x, min_y, max_x, max_y = core.bounds
    candidates: list[Point] = []
    y = min_y + spacing / 2.0
    while y <= max_y + 0.001:
        x = min_x + spacing / 2.0
        while x <= max_x + 0.001:
            point = (round(x, 4), round(y, 4))
            if core.covers(ShapelyPoint(point)):
                candidates.append(point)
            x += spacing
        y += spacing

    if not candidates:
        representative = core.representative_point()
        candidates = [(float(representative.x), float(representative.y))]

    return tuple(dedupe_points(candidates)), domain


def _sort_queue_slots(
    candidates: list[Point],
    queue: QueueSpec,
    domain,
) -> list[Point]:
    return _sort_queue_slots_from_service(
        candidates,
        queue.service_point_m,
        queue.direction_deg,
        queue.spacing_m,
        domain,
    )


def _sort_queue_slots_from_service(
    candidates: list[Point],
    service: Point,
    direction_deg: float,
    spacing_m: float,
    domain,
) -> list[Point]:
    centroid = domain.centroid
    tail = (float(centroid.x) - service[0], float(centroid.y) - service[1])
    if hypot(*tail) < 0.001:
        angle = radians(direction_deg)
        tail = (cos(angle), sin(angle))
    tail = _normalize(tail)
    lateral_axis = (-tail[1], tail[0])
    spacing = max(0.2, float(spacing_m))

    def key(point: Point) -> tuple[float, float, float, float]:
        dx = point[0] - service[0]
        dy = point[1] - service[1]
        depth = dx * tail[0] + dy * tail[1]
        lateral = dx * lateral_axis[0] + dy * lateral_axis[1]
        return (
            max(0.0, round(depth / spacing)),
            abs(lateral),
            max(0.0, depth),
            lateral,
        )

    return sorted(candidates, key=key)


def _normalize(vector: Point) -> Point:
    length = hypot(vector[0], vector[1])
    if length <= 0.001:
        return (1.0, 0.0)
    return vector[0] / length, vector[1] / length


def _default_queue_slots(
    anchor: Point,
    *,
    per_row: int,
    spacing: float,
    walkable_geometry,
) -> tuple[Point, ...]:
    if walkable_geometry is None:
        return ()
    local_domain = walkable_geometry.intersection(ShapelyPoint(anchor).buffer(5.0))
    if local_domain.is_empty:
        local_domain = walkable_geometry
    core = safe_core(local_domain, min(0.18, spacing * 0.2))
    min_x, min_y, max_x, max_y = core.bounds
    candidates: list[Point] = []
    y = min_y + spacing / 2.0
    while y <= max_y + 0.001:
        x = min_x + spacing / 2.0
        while x <= max_x + 0.001:
            point = (round(x, 4), round(y, 4))
            if core.covers(ShapelyPoint(point)):
                candidates.append(point)
            x += spacing
        y += spacing

    candidates.sort(key=lambda point: _point_distance(point, anchor))
    count = max(8, min(96, per_row * 4))
    return tuple(dedupe_points(candidates))[:count]


def _jitter_waiting_slots(
    domain,
    slots: tuple[Point, ...],
    *,
    clearance: float,
) -> tuple[Point, ...]:
    if not slots:
        return ()

    jittered: list[Point] = []
    for index, slot in enumerate(slots):
        # Deterministic low-discrepancy offsets keep the waiting distribution natural
        # without changing between runs or pushing people outside the walkable area.
        angle = radians((index * 137.50776405) % 360.0)
        radius = 0.08 + 0.24 * ((index * 37) % 11) / 10.0
        candidate = (
            round(slot[0] + cos(angle) * radius, 4),
            round(slot[1] + sin(angle) * radius, 4),
        )
        if not domain.covers(ShapelyPoint(candidate)):
            candidate = slot
        jittered.append(
            project_to_safe_point(
                domain,
                candidate,
                clearance=clearance,
                require_inside=False,
            )
        )
    return tuple(dedupe_points(jittered))


def _point_distance(a: Point, b: Point) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])


def _node_position(station_graph: StationGraph, node_id: str) -> Point:
    return station_graph.nodes[node_id].position


def _facility_kind_for_element(element: DesignElement) -> str:
    if element.kind == FacilityKind.ELEVATOR.value:
        return FacilityKind.ELEVATOR.value
    if element.kind == FacilityKind.STAIRS.value:
        return FacilityKind.STAIRS.value
    return FacilityKind.ESCALATOR.value


def _default_vertical_service_rate(element: DesignElement) -> int:
    if element.kind == FacilityKind.ELEVATOR.value:
        return 24
    if element.kind == FacilityKind.STAIRS.value:
        return 125
    return 75


def _vertical_speed(element: DesignElement) -> float:
    if element.kind == FacilityKind.ELEVATOR.value:
        return 4.2
    if element.kind == FacilityKind.STAIRS.value:
        return 1.55
    return 2.3
