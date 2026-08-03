from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shapely.geometry import Point as ShapelyPoint

from ..agents.passenger import PassengerAgent
from ..facilities.runtime import FacilityProcessAgent
from .physical_waypoint_routing import (
    FacilityPortals,
    PhysicalRouteUnreachableError,
    PhysicalWaypointRouter,
)


class PhysicalRoutingRuntimeMixin:
    """Convert topology anchors and facility portals into physical waypoints."""

    if TYPE_CHECKING:
        scenario: Any
        _physical_waypoint_router: PhysicalWaypointRouter

        def jupedsim_walkable_area(self, level_id: str | None = None) -> Any: ...

        def _safe_facility_queue_approach_target(
            self,
            passenger: PassengerAgent,
            facility: FacilityProcessAgent,
        ) -> tuple[float, float]: ...

    def _same_level_topology_target(
        self,
        station_graph: Any,
        start_node_id: str,
        node_ids: tuple[str, ...],
        level_id: str | None,
    ) -> tuple[float, float]:
        destination: tuple[float, float] | None = None
        previous_node_id = start_node_id
        for node_id in node_ids:
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
            destination = node.position
            previous_node_id = node_id
        if destination is None:
            raise PhysicalRouteUnreachableError("topology route has no destination portal")
        return destination

    def _physical_route_for_points(
        self,
        passenger: PassengerAgent,
        anchors: tuple[tuple[float, float], ...],
        *,
        level_id: str | None = None,
    ) -> tuple[tuple[float, float], ...]:
        route_level = level_id or passenger.current_level_id
        if (
            route_level is not None
            and passenger.current_level_id is not None
            and route_level != passenger.current_level_id
        ):
            raise PhysicalRouteUnreachableError(
                f"passenger {passenger.unique_id} is on level {passenger.current_level_id!r}, "
                f"not walking-route level {route_level!r}"
            )
        router = getattr(self, "_physical_waypoint_router", None)
        if router is None:
            router = PhysicalWaypointRouter()
            self._physical_waypoint_router = router
        return router.route(
            self.jupedsim_walkable_area(route_level),
            passenger.pos,
            anchors,
            level_id=route_level,
            clearance=max(
                0.02,
                min(
                    float(self.scenario.jupedsim_agent_radius_units),
                    float(self.scenario.jupedsim_target_radius_units) * 0.25,
                ),
            ),
        )

    def _facility_portals(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> FacilityPortals:
        entry_level_id = facility.spec.entry_level_id or passenger.current_level_id
        if (
            passenger.current_level_id is not None
            and entry_level_id is not None
            and passenger.current_level_id != entry_level_id
        ):
            raise PhysicalRouteUnreachableError(
                f"facility {facility.facility_id!r} entry portal is on level "
                f"{entry_level_id!r}, passenger is on {passenger.current_level_id!r}"
            )
        portals = FacilityPortals(
            approach=self._safe_facility_queue_approach_target(passenger, facility),
            entry=facility.spec.position,
            exit=facility.spec.exit_position,
            entry_level_id=entry_level_id,
            exit_level_id=facility.spec.exit_level_id or entry_level_id,
        )
        self._require_portal_inside_walkable_area(
            facility.facility_id,
            "entry",
            portals.entry,
            portals.entry_level_id,
        )
        self._require_portal_inside_walkable_area(
            facility.facility_id,
            "exit",
            portals.exit,
            portals.exit_level_id,
        )
        return portals

    def _require_portal_inside_walkable_area(
        self,
        facility_id: str,
        portal_kind: str,
        position: tuple[float, float],
        level_id: str | None,
    ) -> None:
        area = self.jupedsim_walkable_area(level_id)
        if area.buffer(1e-7).covers(ShapelyPoint(position)):
            return
        raise PhysicalRouteUnreachableError(
            f"facility {facility_id!r} {portal_kind} portal {position!r} is outside "
            f"the walkable area on level {level_id!r}"
        )
