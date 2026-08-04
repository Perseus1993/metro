from __future__ import annotations

from math import ceil, hypot
from typing import TYPE_CHECKING

from shapely.geometry import LineString, Point as ShapelyPoint

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent


class VerticalReleaseGeometryMixin:
    """Body-clear release corridors and connector lane geometry."""

    def _vertical_release_position(
        self,
        passenger: PassengerAgent,
        release_index: int,
        *,
        preferred_release_position: tuple[float, float] | None = None,
        prefer_forward_clearance: bool = False,
    ) -> tuple[float, float]:
        if preferred_release_position is not None:
            forward, _lateral = self._release_axes()
            spacing = self._release_spacing()
            projection_limit = max(
                0.05,
                float(self.model.scenario.jupedsim_agent_radius_units),
            )
            forward_steps = list(
                range(max(0, int(self.spec.release_forward_extra)) + 1)
            )
            if prefer_forward_clearance and len(forward_steps) > 1:
                # Elevator unloading first clears the doorway by one body
                # spacing. A following cabin may then use the portal position
                # behind that passenger without overtaking them. Every option
                # still uses the same full swept-body contract.
                forward_steps = [1, 0, *forward_steps[2:]]
            for forward_step in forward_steps:
                candidate = (
                    preferred_release_position[0] + forward[0] * spacing * forward_step,
                    preferred_release_position[1] + forward[1] * spacing * forward_step,
                )
                projected = self._project_release_position(candidate)
                if hypot(
                    projected[0] - candidate[0],
                    projected[1] - candidate[1],
                ) > projection_limit:
                    continue
                if not self._has_release_clearance(
                    projected,
                    self._release_min_distance(),
                    passenger=passenger,
                ):
                    continue
                if not self._continuous_release_path_is_clear(
                    passenger,
                    preferred_release_position,
                    projected,
                ):
                    continue
                self._service_release_positions_this_tick.append(projected)
                return projected
            raise RuntimeError(
                f"Continuous release corridor for {self.facility_id} is physically blocked"
            )
        try:
            return self._release_position(passenger, release_index)
        except RuntimeError:
            return self._fallback_vertical_release_position(passenger, release_index)

    def _continuous_release_path_is_clear(
        self,
        passenger: PassengerAgent,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> bool:
        level_id = self.portal_exit_level_id
        area = self.model.jupedsim_walkable_area(level_id)
        body_radius = max(
            0.02,
            float(self.model.scenario.jupedsim_agent_radius_units),
        )
        if hypot(end[0] - start[0], end[1] - start[1]) <= 1e-9:
            path = ShapelyPoint(start)
            swept_body = path.buffer(body_radius)
        else:
            path = LineString((start, end))
            swept_body = path.buffer(body_radius, cap_style="round")
        if not area.buffer(1e-7).covers(swept_body):
            return False

        min_distance = self._release_min_distance()
        for other in self.model.passengers:
            if other is passenger:
                continue
            if level_id is not None and other.current_level_id != level_id:
                continue
            if path.distance(ShapelyPoint(other.pos)) < min_distance - 1e-9:
                return False
        return all(
            path.distance(ShapelyPoint(existing)) >= min_distance - 1e-9
            for existing in self._service_release_positions_this_tick
        )

    def _fallback_vertical_release_position(
        self,
        passenger: PassengerAgent,
        release_index: int,
    ) -> tuple[float, float]:
        base = self.portal_exit_position
        forward, lateral = self._release_axes()
        spacing = self._release_spacing()
        column_order = (0, -1, 1)[release_index % 3]
        row = release_index // 3
        min_distance = self._release_min_distance()
        for candidate in self._release_candidates(
            base,
            forward,
            lateral,
            spacing,
            column_order,
            row,
        ):
            projected = self._project_release_position(candidate)
            if not self._has_release_clearance(
                projected,
                min_distance,
                passenger=passenger,
            ):
                continue
            self._service_release_positions_this_tick.append(projected)
            return projected

        raise RuntimeError(f"No body-clear vertical release for {self.facility_id}")


    def _ride_lateral_offset(
        self,
        passenger: PassengerAgent,
        *,
        release_index: int,
        release_count: int,
    ) -> float:
        """Assign body-clear lanes derived from the connector cross-section."""

        del passenger
        count = max(1, int(release_count))
        scenario = self.model.scenario
        spacing = max(
            float(scenario.jupedsim_agent_radius_units) * 2.2,
            float(getattr(scenario, "personal_space_units", 0.8)) * 0.5,
        )
        lane_capacity = self._physical_lane_capacity(spacing)
        count = min(count, lane_capacity)
        if int(release_index) >= count:
            raise RuntimeError(
                f"connector {self.facility_id!r} has no physical lane for "
                f"release_index={release_index}"
            )
        layout = self._physical_lane_layout(count, spacing)
        return layout[max(0, int(release_index))]

    def _physical_lane_capacity(self, spacing: float | None = None) -> int:
        scenario = self.model.scenario
        body_radius = float(scenario.jupedsim_agent_radius_units)
        lane_spacing = spacing or max(
            body_radius * 2.2,
            float(getattr(scenario, "personal_space_units", 0.8)) * 0.5,
        )
        width = self.spec.traversal_width_m
        if width is None:
            raise RuntimeError(
                f"vertical connector {self.facility_id!r} has no traversal_width_m"
            )
        grids = self._body_clear_lane_grids(lane_spacing)
        capacity = max((len(grid) for grid in grids), default=0)
        if capacity <= 0:
            raise RuntimeError(
                f"vertical connector {self.facility_id!r} has no body-clear exit lane"
            )
        return capacity

    def _physical_lane_layout(self, count: int, spacing: float) -> tuple[float, ...]:
        candidates: list[tuple[tuple[float, float, float], tuple[float, ...]]] = []
        for grid in self._body_clear_lane_grids(spacing):
            ordered = tuple(sorted(grid, key=lambda offset: (abs(offset), offset > 0.0)))
            if len(ordered) < count:
                continue
            selected = ordered[:count]
            score = (
                max(abs(offset) for offset in selected),
                sum(abs(offset) for offset in selected),
                abs(sum(selected)),
            )
            candidates.append((score, selected))
        if not candidates:
            raise RuntimeError(
                f"vertical connector {self.facility_id!r} cannot fit {count} body-clear lanes"
            )
        return min(candidates, key=lambda item: item[0])[1]

    def _body_clear_lane_grids(self, spacing: float) -> tuple[tuple[float, ...], ...]:
        width = self.spec.traversal_width_m
        if width is None:
            raise RuntimeError(
                f"vertical connector {self.facility_id!r} has no traversal_width_m"
            )
        body_radius = float(self.model.scenario.jupedsim_agent_radius_units)
        max_offset = max(0.0, float(width) / 2.0 - body_radius)
        extent = max(1, ceil(max_offset / spacing) + 1)
        raw_grids = (
            tuple(index * spacing for index in range(-extent, extent + 1)),
            tuple((index + 0.5) * spacing for index in range(-extent, extent + 1)),
        )
        grids: list[tuple[float, ...]] = []
        for raw_grid in raw_grids:
            valid = tuple(
                offset
                for offset in raw_grid
                if abs(offset) <= max_offset + 1e-9
                and self._lane_exit_is_body_clear(offset, body_radius)
            )
            grids.append(valid)
        return tuple(grids)

    def _lane_exit_is_body_clear(self, offset: float, body_radius: float) -> bool:
        level_id = self.portal_exit_level_id
        registered = getattr(self.model, "facilities_by_id", {}).get(self.facility_id)
        if registered is not self:
            # Hand-built unit/plugin facilities do not own the station's
            # compiled geometry. Their explicit traversal width remains the
            # only valid cross-section contract.
            return True
        try:
            area = self.model.jupedsim_walkable_area(level_id)
        except (AttributeError, LookupError, TypeError, ValueError):
            return True
        endpoint = self._offset_vertical_position(self.portal_exit_position, offset)
        return area.buffer(1e-7).covers(ShapelyPoint(endpoint).buffer(body_radius))

    def _offset_vertical_position(
        self,
        position: tuple[float, float],
        lateral_offset: float,
    ) -> tuple[float, float]:
        if abs(lateral_offset) <= 1e-12:
            return position
        _forward, lateral = self._release_axes()
        return (
            position[0] + lateral[0] * lateral_offset,
            position[1] + lateral[1] * lateral_offset,
        )
