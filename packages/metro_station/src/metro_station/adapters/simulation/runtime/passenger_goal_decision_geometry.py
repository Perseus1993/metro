from __future__ import annotations

from shapely.geometry import LineString, Point as ShapelyPoint
from shapely.ops import unary_union


class PassengerGoalDecisionGeometryMixin:
    """Physical catchments and reachability for tactical facility decisions."""

    def _decision_region_domain(self, model, approaches, area):
        observation_margin = self._decision_observation_margin(model)
        portal_envelope = unary_union(
            [
                ShapelyPoint(point).buffer(observation_margin)
                for point in approaches
            ]
        )
        decision_region = area.intersection(portal_envelope)
        if not decision_region.is_empty:
            return decision_region
        # Defensive fallback: approaches were already projected into the
        # walkable area, so the first portal remains a physical target.
        return ShapelyPoint(approaches[0]).buffer(
            observation_margin
        ).intersection(area)

    def _decision_observation_margin(self, model) -> float:
        return max(
            float(model.scenario.jupedsim_target_radius_units) * 4.0,
            float(getattr(model.scenario, "personal_space_units", 0.8)) * 2.0,
            float(model.scenario.jupedsim_agent_radius_units) * 4.0,
        )

    def _has_local_portal_access(self, model, position, approaches, area) -> bool:
        margin = self._decision_observation_margin(model)
        body_radius = max(
            0.02,
            float(model.scenario.jupedsim_agent_radius_units),
        )
        for approach in approaches:
            if self._distance(position, approach) > margin + 1e-9:
                continue
            if self._distance(position, approach) <= 1e-9:
                return True
            sight_line = LineString((position, approach))
            if area.buffer(1e-7).covers(
                sight_line.buffer(body_radius, cap_style="flat")
            ):
                return True
        return False

    def _representative_facility_approach(
        self,
        model,
        passenger,
        facility,
    ) -> tuple[float, float]:
        binding = model.facility_portal_binding(facility.facility_id)
        if not binding.approach_slots:
            raise RuntimeError(
                f"facility {facility.facility_id!r} has no compiled approach slots"
            )
        return binding.approach_slots[-1]

    def _facility_decision_points(self, model, passenger, facility):
        """Return the physical queue catchment represented by a facility."""

        binding = model.facility_portal_binding(facility.facility_id)
        if not binding.approach_slots:
            raise RuntimeError(
                f"facility {facility.facility_id!r} has no compiled decision points"
            )
        return binding.approach_slots

    def _facility_is_on_passenger_walkable_component(
        self,
        model,
        passenger,
        facility,
    ) -> bool:
        level_id = passenger.current_level_id
        area = model.jupedsim_walkable_area(level_id)
        passenger_point = ShapelyPoint(passenger.pos)
        approach = ShapelyPoint(
            self._representative_facility_approach(model, passenger, facility)
        )
        components = tuple(getattr(area, "geoms", (area,)))
        return any(
            component.buffer(1e-7).covers(passenger_point)
            and component.buffer(1e-7).covers(approach)
            for component in components
        )


__all__ = ["PassengerGoalDecisionGeometryMixin"]
