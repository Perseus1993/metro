from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


from ..planning.plan import AgentState, FacilityStage, RouteKey
from ..design.schema import StationDesignDocument
from ..compilation.validation import validate_station_design
from ..compilation.facility_portals import (
    compile_facility_portal_bindings,
    validate_facility_portals,
)
from ..compilation.geometry_reachability import GeometryCompilePolicy
from ..facilities.process import (
    FacilityKind,
    FacilitySpec,
    QueueLayout,
)
from .scenario import StationGeometry, StationSandboxScenario
from .graph import StationGraph
from .facility_portal_binding import FacilityPortalBinding
from ..compilation.decision_holding_regions import DecisionHoldingRegionBinding
from ..compilation.spatial_capacity import SpatialCapacityCertificate, SpatialDemandContract


from .layout_facilities import (
    _facility_specs_from_station_graph,
    _layout_edges_from_station_graph,
    _layout_nodes_from_station_graph,
    _legacy_vertical_config,
    _route_registry_from_station_graph,
)
from .layout_gate_queues import _gate_queue_crossing_guard
from .layout_queue_geometry import _queue_steps_from_facility_geometry
from .layout_types import LayoutEdge, LayoutNode, Point


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
    facility_portal_bindings: tuple[FacilityPortalBinding, ...] = ()
    facility_portal_binding_variants: tuple[FacilityPortalBinding, ...] = ()
    decision_holding_regions: tuple[DecisionHoldingRegionBinding, ...] = ()
    spatial_capacity_certificates: tuple[SpatialCapacityCertificate, ...] = ()
    spatial_demand_contracts: tuple[SpatialDemandContract, ...] = ()
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
        concourse_level_id = geom.concourse_level_id
        platform_level_id = geom.platform_level_id
        facilities: list[FacilitySpec] = []

        for index, gate in enumerate(geom.gates):
            col_step, row_step = _queue_steps_from_facility_geometry(
                gate.position,
                gate.queue_anchor,
                gate.exit_position,
                col_spacing=geom.queue_spacing,
                row_spacing=1.0,
            )
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
                        col_step=col_step,
                        row_step=row_step,
                    ),
                    exit_position=gate.exit_position,
                    service_persons_per_min=scenario.gate_service_persons_per_min,
                    queue_state=AgentState.QUEUEING_GATE.value,
                    service_state=AgentState.PASSING_GATE.value,
                    release_route=(gate.position, gate.exit_position),
                    entry_level_id=concourse_level_id,
                    exit_level_id=concourse_level_id,
                    queue_crossing_guard=_gate_queue_crossing_guard(
                        scenario,
                        enabled=True,
                    ),
                )
            )

        for index, gate in enumerate(geom.exit_gates):
            col_step, row_step = _queue_steps_from_facility_geometry(
                gate.position,
                gate.queue_anchor,
                gate.exit_position,
                col_spacing=geom.queue_spacing,
                row_spacing=1.0,
            )
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
                        col_step=col_step,
                        row_step=row_step,
                    ),
                    exit_position=gate.exit_position,
                    service_persons_per_min=scenario.gate_service_persons_per_min,
                    queue_state=AgentState.QUEUEING_EXIT_GATE.value,
                    service_state=AgentState.PASSING_EXIT_GATE.value,
                    release_route=(gate.position, gate.exit_position),
                    entry_level_id=concourse_level_id,
                    exit_level_id=concourse_level_id,
                )
            )

        for index, transport in enumerate(geom.vertical_transports):
            col_step, row_step = _queue_steps_from_facility_geometry(
                transport.position,
                transport.queue_anchor,
                transport.exit_position,
                col_spacing=geom.queue_spacing,
                row_spacing=0.9,
            )
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
                        col_step=col_step,
                        row_step=row_step,
                    ),
                    exit_position=transport.exit_position,
                    service_persons_per_min=transport.persons_per_min,
                    queue_state=AgentState.QUEUEING_VERTICAL.value,
                    service_state=AgentState.RIDING_VERTICAL.value,
                    release_route=(transport.position, transport.exit_position),
                    speed_units_per_tick=transport.speed_units_per_tick,
                    travel_speed_m_s=(
                        scenario.elevator_speed_m_s
                        if transport.kind == FacilityKind.ELEVATOR.value
                        else scenario.stairs_speed_m_s
                        if transport.kind == FacilityKind.STAIRS.value
                        else scenario.escalator_speed_m_s
                    ),
                    entry_level_id=(
                        concourse_level_id
                        if transport.direction in {"down", "both"}
                        else platform_level_id
                    ),
                    exit_level_id=(
                        platform_level_id
                        if transport.direction in {"down", "both"}
                        else concourse_level_id
                    ),
                    vertical_config=_legacy_vertical_config(transport, scenario),
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
                    line_id=door.line_id,
                    platform_id=f"platform:{door.line_id}:{door.train_direction}",
                    entry_level_id=platform_level_id,
                    exit_level_id=platform_level_id,
                )
            )

        nodes = {
            "unpaid_hall": LayoutNode(
                "unpaid_hall", "unpaid concourse", geom.unpaid_hall_center, concourse_level_id
            ),
            "gate_decision": LayoutNode(
                "gate_decision", "entry gate decision", geom.gate_decision_point, concourse_level_id
            ),
            "paid_hall": LayoutNode(
                "paid_hall",
                "paid concourse",
                geom.paid_hall_center,
                concourse_level_id,
            ),
            "vertical_decision": LayoutNode(
                "vertical_decision",
                "vertical facility decision",
                geom.vertical_decision_point,
                concourse_level_id,
            ),
            "platform_hub": LayoutNode(
                "platform_hub",
                "platform transfer hub",
                geom.platform_transfer_hub,
                platform_level_id,
            ),
            "platform_entry": LayoutNode(
                "platform_entry", "platform waiting entry", geom.platform_entry, platform_level_id
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
        issues = validate_station_design(
            document,
            geometry_policy=GeometryCompilePolicy.from_scenario(scenario),
        )
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
        *,
        compiled_facilities: tuple[FacilitySpec, ...] | None = None,
        compiled_portal_bindings: tuple[FacilityPortalBinding, ...] | None = None,
        compiled_portal_binding_variants: tuple[FacilityPortalBinding, ...] | None = None,
        compiled_decision_holding_regions: tuple[DecisionHoldingRegionBinding, ...] | None = None,
        compiled_spatial_capacity_certificates: tuple[SpatialCapacityCertificate, ...] | None = None,
        compiled_spatial_demand_contracts: tuple[SpatialDemandContract, ...] | None = None,
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
        facilities = (
            tuple(_facility_specs_from_station_graph(station_graph, scenario))
            if compiled_facilities is None
            else compiled_facilities
        )
        portal_policy = GeometryCompilePolicy.from_scenario(scenario)
        portal_bindings = (
            compile_facility_portal_bindings(
                document,
                facilities,
                policy=portal_policy,
                graph=station_graph,
            )
            if document is not None and compiled_portal_bindings is None
            else compiled_portal_bindings or ()
        )
        portal_issues = (
            validate_facility_portals(
                document,
                facilities,
                portal_bindings,
                policy=portal_policy,
            )
            if document is not None
            else []
        )
        portal_errors = [item for item in portal_issues if item.severity == "error"]
        if portal_errors:
            summary = "; ".join(
                f"{item.code}: {item.message}" for item in portal_errors[:8]
            )
            raise ValueError(f"Facility portal compilation failed: {summary}")
        return cls(
            geometry=geometry,
            nodes=_layout_nodes_from_station_graph(station_graph.nodes),
            edges=_layout_edges_from_station_graph(station_graph.edges),
            facilities=facilities,
            facility_portal_bindings=portal_bindings,
            facility_portal_binding_variants=compiled_portal_binding_variants or (),
            decision_holding_regions=compiled_decision_holding_regions or (),
            spatial_capacity_certificates=compiled_spatial_capacity_certificates or (),
            spatial_demand_contracts=compiled_spatial_demand_contracts or (),
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
            RouteKey.AFTER_VERTICAL.value: lambda _start, _passenger=None: (
                self.after_vertical_route()
            ),
            RouteKey.PLATFORM_TO_VERTICAL.value: lambda _start, _passenger=None: (
                self.platform_to_vertical_route()
            ),
            RouteKey.AFTER_EXIT_VERTICAL.value: lambda _start, _passenger=None: (
                self.after_exit_vertical_route()
            ),
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
