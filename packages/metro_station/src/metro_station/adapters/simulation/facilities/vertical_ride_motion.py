from __future__ import annotations

from dataclasses import replace
from math import hypot
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .vertical_physical_resource import ActiveVerticalRide


def _point_to_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-18:
        return hypot(point[0] - start[0], point[1] - start[1])
    projection = (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    ) / length_squared
    ratio = max(0.0, min(1.0, projection))
    closest = (start[0] + dx * ratio, start[1] + dy * ratio)
    return hypot(point[0] - closest[0], point[1] - closest[1])


class VerticalRideMotionMixin:
    """Continuous ride interpolation and connector-spacing enforcement."""

    def _ride_elapsed_ratio(
        self,
        ride: ActiveVerticalRide,
        elapsed_seconds: float,
    ) -> float:
        duration_seconds = float(ride.duration_seconds or 0.0)
        if duration_seconds <= 1e-12:
            return 1.0
        return max(0.0, min(1.0, float(elapsed_seconds) / duration_seconds))

    def _ride_position_at_elapsed(
        self,
        ride: ActiveVerticalRide,
        elapsed_seconds: float,
    ) -> tuple[float, float]:
        ratio = self._ride_elapsed_ratio(ride, elapsed_seconds)
        start_x, start_y = ride.start_position
        end_x, end_y = self._offset_vertical_position(
            self.portal_exit_position,
            ride.lateral_offset,
        )
        return (
            start_x + (end_x - start_x) * ratio,
            start_y + (end_y - start_y) * ratio,
        )

    def _cap_elapsed_for_connector_spacing(
        self,
        ride: ActiveVerticalRide,
        elapsed_before: float,
        proposed_elapsed: float,
        positions_ahead: list[tuple[float, float]],
        progress_ratios_ahead: list[float],
    ) -> float:
        if not positions_ahead or proposed_elapsed <= elapsed_before + 1e-12:
            return proposed_elapsed
        min_distance = self._release_min_distance()
        duration_seconds = float(ride.duration_seconds or 0.0)
        if progress_ratios_ahead and duration_seconds > 1e-12:
            proposed_elapsed = min(
                proposed_elapsed,
                min(progress_ratios_ahead) * duration_seconds,
            )

        position_before = self._ride_position_at_elapsed(ride, elapsed_before)

        def position_is_clear(elapsed: float) -> bool:
            position = self._ride_position_at_elapsed(ride, elapsed)
            return all(
                _point_to_segment_distance(occupied, position_before, position)
                >= min_distance - 1e-9
                for occupied in positions_ahead
            )

        if position_is_clear(proposed_elapsed):
            return proposed_elapsed
        # Progress is authoritative and monotone. Invalid pre-existing overlap
        # must hold until it clears; it must never rewind a rider.
        low = elapsed_before
        high = proposed_elapsed
        if not position_is_clear(low):
            return elapsed_before
        for _ in range(40):
            midpoint = (low + high) / 2.0
            if position_is_clear(midpoint):
                low = midpoint
            else:
                high = midpoint
        return low

    def _ride_progress_steps_per_tick(self, ride: ActiveVerticalRide) -> float:
        return 1.0

    def _update_active_ride_position(self, ride: ActiveVerticalRide) -> None:
        ride.passenger.pos = self.model.clamp_position(
            self._interpolated_individual_vertical_position(ride)
        )

    def _record_active_ride_motion(
        self,
        ride: ActiveVerticalRide,
        *,
        interval_start_time_s: float,
        interval_end_time_s: float,
        elapsed_before_s: float,
        elapsed_after_s: float,
    ) -> None:
        recorder = self.model.facility_motion_trace_recorder
        wall_duration = max(
            0.0,
            float(interval_end_time_s) - float(interval_start_time_s),
        )
        elapsed_advance = max(0.0, float(elapsed_after_s) - float(elapsed_before_s))
        episode_id = (
            f"vertical:{self.facility_id}:{int(ride.event_id)}:ride"
        )
        level_id = "connector:" + str(
            self.spec.source_element_id or self.spec.facility_id
        )
        for time_s in recorder.sample_times(
            interval_start_time_s,
            interval_end_time_s,
        ):
            wall_ratio = (
                1.0
                if wall_duration <= 1e-12
                else max(
                    0.0,
                    min(
                        1.0,
                        (float(time_s) - float(interval_start_time_s))
                        / wall_duration,
                    ),
                )
            )
            elapsed = float(elapsed_before_s) + elapsed_advance * wall_ratio
            recorder.record_positions(
                time_seconds=time_s,
                level_id=level_id,
                phase=f"{self.spec.kind}_ride",
                episode_id=episode_id,
                positions={
                    int(ride.passenger.unique_id): self.model.clamp_position(
                        self._ride_position_at_elapsed(ride, elapsed)
                    )
                },
            )

    def _interpolated_individual_vertical_position(
        self,
        ride: ActiveVerticalRide,
    ) -> tuple[float, float]:
        ratio = (
            1.0
            if (
                ride.total_steps <= 0
                or ride.progress_steps >= float(ride.total_steps) - 1e-12
                or (
                    ride.duration_seconds is not None
                    and ride.duration_seconds <= 1e-12
                )
            )
            else (
                max(
                    0.0,
                    min(
                        1.0,
                        ride.elapsed_seconds / ride.duration_seconds,
                    ),
                )
                if ride.duration_seconds is not None
                else max(
                    0.0,
                    min(1.0, ride.progress_steps / ride.total_steps),
                )
            )
        )
        start_x, start_y = ride.start_position
        end_x, end_y = self._offset_vertical_position(
            self.portal_exit_position,
            ride.lateral_offset,
        )
        return (
            start_x + (end_x - start_x) * ratio,
            start_y + (end_y - start_y) * ratio,
        )

    def _delay_ride_event(
        self,
        ride: ActiveVerticalRide,
        delay_seconds: float,
    ) -> None:
        if delay_seconds <= 0.0:
            return
        for index, event in enumerate(self.model.facility_service_events):
            if event.event_id != ride.event_id:
                continue
            self.model.facility_service_events[index] = replace(
                event,
                end_time=event.end_time + delay_seconds,
                arrive_time=(
                    None
                    if event.arrive_time is None
                    else event.arrive_time + delay_seconds
                ),
            )
            return

    def _interpolated_vertical_position(
        self,
        progress_steps: float,
        total_steps: int,
    ) -> tuple[float, float]:
        ratio = (
            1.0
            if total_steps <= 0
            else max(0.0, min(1.0, progress_steps / total_steps))
        )
        sx, sy = self.portal_entry_position
        ex, ey = self.portal_exit_position
        return (sx + (ex - sx) * ratio, sy + (ey - sy) * ratio)


__all__ = ["VerticalRideMotionMixin"]
