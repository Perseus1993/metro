from __future__ import annotations

from math import hypot
from typing import TYPE_CHECKING, Any

from ..agents.passenger import PassengerAgent
from ..facilities.process import FacilityKind
from ..facilities.runtime import FacilityProcessAgent
from ..planning.plan import AgentState, FacilityStage
from .physical_waypoint_routing import PhysicalRouteUnreachableError


class StationGraphRoutingMixin:
    """Translate passenger positions and facility targets into topology routes."""

    if TYPE_CHECKING:
        layout_graph: Any
        evacuation_routing: Any
        scenario: Any

        def _same_level_topology_target(
            self,
            station_graph: Any,
            start_node_id: str,
            node_ids: tuple[str, ...],
            level_id: str | None,
        ) -> tuple[float, float]: ...

        def _physical_route_for_points(
            self,
            passenger: PassengerAgent,
            anchors: tuple[tuple[float, float], ...],
            *,
            level_id: str | None = None,
            include_navigation_waypoints: bool = False,
        ) -> tuple[tuple[float, float], ...]: ...

        def _safe_facility_queue_approach_target(
            self,
            passenger: PassengerAgent,
            facility: FacilityProcessAgent,
        ) -> tuple[float, float]: ...

    def _station_graph_route_to_facility(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
        *,
        invoke_evacuation_router: bool = True,
        final_target_override: tuple[float, float] | None = None,
        final_approach_anchors: tuple[tuple[float, float], ...] = (),
        include_navigation_waypoints: bool = False,
        preserve_gate_tactical_anchors: bool = False,
    ) -> tuple[tuple[float, float], ...]:
        station_graph = getattr(self.layout_graph, "station_graph", None)
        if station_graph is None:
            return ()

        element_id = self._facility_element_id(facility.facility_id)
        binding = self.facility_portal_binding(facility.facility_id)
        if facility.spec.kind == FacilityKind.TRAIN_DOOR.value:
            # Platform-edge train doors are represented by the platform node
            # in the strategic graph rather than one facility-entry node per
            # runtime door.  Treat that node as the tactical destination so
            # a passenger coming from an entry gate retains paid-hall egress
            # anchors instead of falling back to a direct cross-bank line.
            target_nodes = [
                node
                for node_id in station_graph.node_ids_for_element(element_id)
                if (node := station_graph.nodes.get(node_id)) is not None
                and node.kind == "platform"
                and node.level_id == binding.entry_level_id
            ]
        else:
            target_nodes = [
                node
                for node_id in station_graph.node_ids_for_element(element_id)
                if (node := station_graph.nodes.get(node_id)) is not None
                and node.kind == "facility_entry"
                and node.facility_stage == facility.spec.stage
                and node.level_id == binding.entry_level_id
            ]
        if not target_nodes:
            if facility.spec.kind == FacilityKind.TRAIN_DOOR.value:
                return ()
            raise PhysicalRouteUnreachableError(
                f"facility {facility.facility_id!r} has no entry portal in the station graph"
            )

        level_id = binding.entry_level_id or passenger.current_level_id
        destination = min(target_nodes, key=lambda item: item.node_id)
        start_candidates = self._station_graph_route_start_candidates(
            passenger,
            facility,
            station_graph,
            level_id,
        )
        try:
            start_node = station_graph.nearest_node(passenger.pos, start_candidates or None)
            if invoke_evacuation_router and self.evacuation_routing.enabled_for(passenger):
                node_ids = self.evacuation_routing.route_node_ids(
                    self,
                    passenger,
                    start_node.node_id,
                    destination.node_id,
                )
            else:
                path = station_graph.shortest_path(
                    start_node.node_id,
                    {node.node_id for node in target_nodes},
                    allowed_kinds={"walk"},
                )
                node_ids = () if path is None else path.node_ids[1:]
        except ValueError as exc:
            raise PhysicalRouteUnreachableError(
                f"cannot locate a station-graph route to facility {facility.facility_id!r}"
            ) from exc
        final_target = (
            self._safe_facility_queue_approach_target(passenger, facility)
            if final_target_override is None
            else tuple(final_target_override)
        )
        if not node_ids:
            return self._physical_route_for_points(
                passenger,
                self._dedupe_route_points(
                    (*final_approach_anchors, final_target)
                ),
                level_id=level_id,
                include_navigation_waypoints=include_navigation_waypoints,
            )

        # The Station Graph (or evacuation plugin) owns the tactical topology.
        # Preserve every intermediate same-level node as a required anchor, but
        # replace the final mechanical entry node with the passenger's reserved
        # queue-approach portal. Walking to the entry and then back out to the
        # queue would create an artificial U-turn.
        anchors: list[tuple[float, float]] = []
        previous_node_id = start_node.node_id
        for index, node_id in enumerate(node_ids):
            node = station_graph.nodes.get(node_id)
            if node is None:
                raise PhysicalRouteUnreachableError(
                    f"topology route references missing node {node_id!r}"
                )
            if level_id is not None and node.level_id != level_id:
                raise PhysicalRouteUnreachableError(
                    f"walking route crossed from level {level_id!r} to {node.level_id!r} "
                    "without a facility portal"
                )
            edge = station_graph.edge_between(previous_node_id, node_id, kind="walk")
            if edge is None or edge.level_change:
                raise PhysicalRouteUnreachableError(
                    f"walking route used non-walk edge {previous_node_id!r}->{node_id!r}"
                )
            if (
                index < len(node_ids) - 1
                and node.tactical_anchor
                and (
                    preserve_gate_tactical_anchors
                    or facility.spec.stage
                    not in {
                        FacilityStage.ENTRY_GATE.value,
                        FacilityStage.EXIT_GATE.value,
                    }
                )
            ):
                anchors.append(node.position)
            previous_node_id = node_id
        anchors.extend(final_approach_anchors)
        anchors.append(final_target)
        return self._physical_route_for_points(
            passenger,
            self._dedupe_route_points(tuple(anchors)),
            level_id=level_id,
            include_navigation_waypoints=include_navigation_waypoints,
        )

    def _station_graph_route_to_exit(
        self,
        passenger: PassengerAgent,
    ) -> tuple[tuple[float, float], ...]:
        station_graph = getattr(self.layout_graph, "station_graph", None)
        if station_graph is None:
            return ()
        level_id = passenger.current_level_id
        targets = station_graph.nodes_matching(kind="entrance", level_id=level_id)
        if not targets:
            raise PhysicalRouteUnreachableError(
                f"station graph has no exit portal on level {level_id!r}"
            )
        start_candidates = [
            node
            for node in station_graph.nodes.values()
            if node.level_id == level_id and node.kind != "entrance"
        ]
        try:
            start_node = station_graph.nearest_node(passenger.pos, start_candidates or None)
            path = station_graph.shortest_path(
                start_node.node_id,
                {node.node_id for node in targets},
                allowed_kinds={"walk"},
            )
        except ValueError as exc:
            raise PhysicalRouteUnreachableError(
                f"cannot locate a station exit route on level {level_id!r}"
            ) from exc
        if path is None:
            candidates: list[tuple[float, str, tuple[tuple[float, float], ...]]] = []
            for target in sorted(targets, key=lambda item: item.node_id):
                try:
                    route = self._physical_route_for_points(
                        passenger,
                        (target.position,),
                        level_id=level_id,
                    )
                except PhysicalRouteUnreachableError:
                    continue
                candidates.append((self._route_length(passenger.pos, route), target.node_id, route))
            if candidates:
                return min(candidates, key=lambda item: (item[0], item[1]))[2]
            raise PhysicalRouteUnreachableError(
                f"no physical route reaches an exit on level {level_id!r}"
            )
        target = self._same_level_topology_target(
            station_graph,
            start_node.node_id,
            path.node_ids[1:],
            level_id,
        )
        tactical_anchors = tuple(
            node.position
            for node_id in path.node_ids[1:-1]
            if (node := station_graph.nodes.get(node_id)) is not None
            and node.tactical_anchor
            and node.element_id != start_node.element_id
        )
        return self._physical_route_for_points(
            passenger,
            self._dedupe_route_points((*tactical_anchors, target)),
            level_id=level_id,
            include_navigation_waypoints=True,
        )

    def _station_graph_route_start_candidates(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
        station_graph: Any,
        level_id: str | None,
    ) -> list[Any]:
        level_candidates = [
            node
            for node in station_graph.nodes.values()
            if level_id is None or node.level_id == level_id
        ]
        target_element_id = self._facility_element_id(facility.facility_id)
        routable_candidates = [
            node
            for node in level_candidates
            if station_graph.can_start_same_level_walk(node.node_id)
            or (
                node.element_id == target_element_id
                and node.kind == "facility_entry"
                and node.facility_stage == facility.spec.stage
            )
        ]
        if routable_candidates:
            level_candidates = routable_candidates
        if not self._should_start_vertical_route_from_entry_gate_exit(passenger, facility):
            return level_candidates

        gate_exit_candidates = [
            node
            for node in level_candidates
            if node.kind == "facility_exit"
            and node.facility_stage == FacilityStage.ENTRY_GATE.value
        ]
        if not gate_exit_candidates:
            return level_candidates

        try:
            nearest_gate_exit = station_graph.nearest_node(
                passenger.pos,
                gate_exit_candidates,
            )
        except ValueError:
            return level_candidates

        distance_to_gate_exit = hypot(
            passenger.pos[0] - nearest_gate_exit.position[0],
            passenger.pos[1] - nearest_gate_exit.position[1],
        )
        if distance_to_gate_exit <= self._post_entry_gate_graph_start_radius():
            return gate_exit_candidates
        return level_candidates

    def _should_start_vertical_route_from_entry_gate_exit(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> bool:
        if facility.spec.stage != FacilityStage.VERTICAL_TRANSFER.value:
            return False
        if passenger.state not in {
            AgentState.PASSING_GATE.value,
            AgentState.WALKING_TO_VERTICAL.value,
        }:
            return False
        return passenger.current_level_id == self.facility_portal_binding(
            facility.facility_id
        ).entry_level_id

    def _post_entry_gate_graph_start_radius(self) -> float:
        return max(8.0, float(self.scenario.jupedsim_target_radius_units) * 12.0)

    @staticmethod
    def _route_length(
        start: tuple[float, float],
        route: tuple[tuple[float, float], ...],
    ) -> float:
        points = (start, *route)
        return sum(
            hypot(right[0] - left[0], right[1] - left[1])
            for left, right in zip(points, points[1:])
        )

    @staticmethod
    def _facility_element_id(facility_id: str) -> str:
        parts = facility_id.split(":")
        if len(parts) >= 2:
            return parts[1]
        return facility_id

    @staticmethod
    def _dedupe_route_points(
        points: tuple[tuple[float, float], ...],
    ) -> tuple[tuple[float, float], ...]:
        route: list[tuple[float, float]] = []
        for point in points:
            if route and hypot(route[-1][0] - point[0], route[-1][1] - point[1]) <= 0.001:
                continue
            route.append(point)
        return tuple(route)
