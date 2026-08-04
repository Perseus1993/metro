from __future__ import annotations

from dataclasses import replace
from math import ceil, hypot, sqrt
from typing import TYPE_CHECKING, Callable

from shapely.geometry import LineString, Point as ShapelyPoint

from .process_motion import minimum_jerk_progress
from ..spatial_capacity_admission import (
    SpatialCapacityCertificateViolation,
    SpatialCapacityEvidence,
    record_spatial_capacity_event,
)

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent


class ElevatorCabinCompletionMixin:
    """Cabin release ownership, return transition, and individual poses."""

    def _depart_cabin(self) -> None:
        self.boarding_remaining_seconds = 0.0
        self.last_departure_load_persons = self.cabin_load_persons
        self.last_departure_step = self.model.step_index
        self.departed_cabins += 1
        self.cabin_state = "moving"
        self._update_cabin_positions()

    def _arrive_cabin(self, arrival_time_s: float | None = None) -> bool:
        self.travel_remaining_seconds = 0.0
        self._set_cabin_positions(self.portal_exit_position)
        # Release endpoints depend on live landing occupancy.  If the landing
        # is blocked, retain connector authority and retry instead of opening
        # an unloading event with no exit-level collision body.
        configured = self._configure_unloading_motion_profile(
            float(self.model.current_time_seconds if arrival_time_s is None else arrival_time_s)
        )
        if not configured:
            self.cabin_state = "moving"
            return False
        self.cabin_state = "unloading"
        return True

    def _finish_unloading(self) -> bool:
        self._service_release_positions_this_tick = []
        remaining_passengers: list[PassengerAgent] = []
        for release_index, passenger in enumerate(list(self.cabin_passengers)):
            planned_release = self._unloading_release_positions.get(int(passenger.unique_id))
            if self._finish_vertical_service(
                passenger,
                release_index=release_index,
                event_id=self.active_event_id,
                preferred_release_position=(
                    planned_release
                    if planned_release is not None
                    else (
                        float(passenger.pos[0]),
                        float(passenger.pos[1]),
                    )
                ),
                prefer_forward_clearance=planned_release is None,
                resolved_release_position=planned_release,
            ):
                self._release_certified_slot(
                    passenger,
                    getattr(self, "_unloading_certificate_slot_indices", {}).get(
                        int(passenger.unique_id)
                    ),
                )
                continue
            remaining_passengers.append(passenger)
        if remaining_passengers:
            remaining_ids = {int(passenger.unique_id) for passenger in remaining_passengers}
            self.cabin_passengers = remaining_passengers
            self.cabin_load_persons = sum(
                passenger.group_size for passenger in remaining_passengers
            )
            self._cabin_offsets_by_passenger = {
                passenger_id: offset
                for passenger_id, offset in self._cabin_offsets_by_passenger.items()
                if passenger_id in remaining_ids
            }
            self._boarding_start_positions = {
                passenger_id: position
                for passenger_id, position in self._boarding_start_positions.items()
                if passenger_id in remaining_ids
            }
            self.boarding_remaining_seconds = 0.0
            self.travel_remaining_seconds = 0.0
            self.unload_remaining_seconds = 0.0
            self.cabin_state = "unloading"
            self._unloading_start_positions = {}
            self._unloading_release_positions = {}
            self._unloading_segment_durations_seconds = ()
            self._unloading_certificate_slot_indices = {
                passenger_id: slot_index
                for passenger_id, slot_index in getattr(
                    self,
                    "_unloading_certificate_slot_indices",
                    {},
                ).items()
                if passenger_id in remaining_ids
            }
            self._sync_legacy_step_counters()
            return False
        self.unload_remaining_seconds = 0.0
        self.cabin_state = "returning" if self.return_remaining_seconds > 1e-9 else "idle"
        if self.cabin_state == "idle":
            self.physical_resource.release_retention(self.facility_id)
        self.boarding_remaining_seconds = 0.0
        self.travel_remaining_seconds = 0.0
        if self.cabin_state != "returning":
            self.return_remaining_seconds = 0.0
        self.cabin_passengers = []
        self._cabin_offsets_by_passenger = {}
        self._boarding_start_positions = {}
        self._unloading_start_positions = {}
        self._unloading_release_positions = {}
        self._unloading_segment_durations_seconds = ()
        self._unloading_certificate_slot_indices = {}
        self.cabin_load_persons = 0
        self.active_event_id = None
        self._sync_legacy_step_counters()
        return True

    def _finish_returning(self) -> None:
        self.physical_resource.release_retention(self.facility_id)
        self.cabin_state = "idle"
        self.boarding_wait_remaining_seconds = 0.0
        self.return_remaining_seconds = 0.0
        self._sync_legacy_step_counters()

    def _update_cabin_positions(self) -> None:
        if not self.cabin_passengers:
            return
        duration = max(0.0, float(self._elevator_config.travel_seconds))
        ratio = (
            1.0
            if duration <= 1e-9
            else max(0.0, min(1.0, 1.0 - self.travel_remaining_seconds / duration))
        )
        self._set_cabin_positions(self._interpolated_vertical_position(ratio, 1))

    def _travel_positions_at_ratio(
        self,
        ratio: float,
    ) -> dict[int, tuple[float, float]]:
        return self._cabin_positions_at_center(
            self._interpolated_vertical_position(
                max(0.0, min(1.0, float(ratio))),
                1,
            )
        )

    def _record_travel_motion(
        self,
        *,
        interval_start_time_s: float,
        interval_end_time_s: float,
        remaining_before_s: float,
    ) -> None:
        if not self.cabin_passengers or self.active_event_id is None:
            return
        recorder = self.model.facility_motion_trace_recorder
        duration = max(0.0, float(self._elevator_config.travel_seconds))
        episode_id = f"elevator:{self.facility_id}:{self.active_event_id}:travel"
        level_id = "connector:" + str(self.spec.source_element_id or self.spec.facility_id)
        for time_s in recorder.sample_times(
            interval_start_time_s,
            interval_end_time_s,
        ):
            elapsed_in_interval = max(0.0, time_s - interval_start_time_s)
            remaining = max(0.0, float(remaining_before_s) - elapsed_in_interval)
            ratio = 1.0 if duration <= 1e-9 else max(0.0, min(1.0, 1.0 - remaining / duration))
            recorder.record_positions(
                time_seconds=time_s,
                level_id=level_id,
                phase="elevator_travel",
                episode_id=episode_id,
                positions=self._travel_positions_at_ratio(ratio),
            )

    def _record_stationary_cabin_motion(
        self,
        *,
        interval_start_time_s: float,
        interval_end_time_s: float,
        phase: str,
    ) -> None:
        if not self.cabin_passengers or self.active_event_id is None:
            return
        positions = {
            int(passenger.unique_id): tuple(passenger.pos) for passenger in self.cabin_passengers
        }
        recorder = self.model.facility_motion_trace_recorder
        episode_id = (
            f"elevator:{self.facility_id}:{self.active_event_id}:{phase.removeprefix('elevator_')}"
        )
        level_id = "connector:" + str(self.spec.source_element_id or self.spec.facility_id)
        for time_s in recorder.sample_times(
            interval_start_time_s,
            interval_end_time_s,
        ):
            recorder.record_positions(
                time_seconds=time_s,
                level_id=level_id,
                phase=phase,
                episode_id=episode_id,
                positions=positions,
            )

    def _configure_unloading_motion_profile(self, phase_start_time_s: float) -> bool:
        if not self.cabin_passengers:
            return False
        self._service_release_positions_this_tick = []
        starts = {
            int(passenger.unique_id): tuple(passenger.pos) for passenger in self.cabin_passengers
        }
        external_positions = self._external_landing_positions()
        releases = self._plan_self_clear_unloading_releases(
            self.cabin_passengers,
            starts,
            external_stationary_positions=external_positions,
        )
        if releases is None:
            self._service_release_positions_this_tick = []
            return False
        slot_indices = self._certified_elevator_unloading_slot_indices(
            starts,
            releases,
        )
        if not self._unloading_plan_clears_external_occupancy(starts, releases):
            self._record_elevator_release_defer(
                "release.temporarily_blocked",
                len(releases),
            )
            self._service_release_positions_this_tick = []
            return False

        certificate = self._release_capacity_certificate()
        if certificate is None:
            raise RuntimeError("compiled elevator release certificate is unavailable")
        owners_by_certificate = self.model._spatial_capacity_slot_owners
        owners = owners_by_certificate.setdefault(certificate.certificate_id, {})
        passenger_ids = {int(passenger.unique_id) for passenger in self.cabin_passengers}
        if any(
            slot_index in owners and owners[slot_index] not in passenger_ids
            for slot_index in slot_indices.values()
        ):
            self._record_elevator_release_defer(
                "capacity.admission_exhausted",
                len(releases),
            )
            self._service_release_positions_this_tick = []
            return False
        for passenger_id, slot_index in slot_indices.items():
            owners[slot_index] = passenger_id

        durations = self._unloading_durations_for(starts, releases)
        self._unloading_start_positions = starts
        self._unloading_release_positions = releases
        self._unloading_certificate_slot_indices = slot_indices
        self._unloading_segment_durations_seconds = tuple(durations)
        self._effective_unloading_duration_seconds = sum(durations)
        self.unload_remaining_seconds = self._effective_unloading_duration_seconds
        self._update_active_event_unloading_deadline(phase_start_time_s)
        self._service_release_positions_this_tick = []
        self._sync_legacy_step_counters()
        return True

    def _certified_elevator_unloading_slot_indices(
        self,
        starts: dict[int, tuple[float, float]],
        releases: dict[int, tuple[float, float]],
    ) -> dict[int, int]:
        certificate = self._release_capacity_certificate()
        if certificate is None:
            raise RuntimeError("compiled elevator release certificate is unavailable")
        corridor = self._service_corridor_capacity_certificate()
        if corridor is None:
            raise RuntimeError("compiled elevator service-corridor certificate is unavailable")
        batch_size = len(releases)
        if batch_size <= 0 or batch_size > len(certificate.batch_plans):
            raise SpatialCapacityCertificateViolation(
                f"elevator batch {batch_size} is outside certificate prefixes",
                self._elevator_capacity_evidence(certificate, batch_size),
            )
        # The prefix plans prove that every load 1..B has a simultaneous safe
        # placement.  Runtime cabin ordering may choose a different member of
        # the finite, statically validated release envelope, so matching only
        # the single constructive witness would reject valid mirror/order
        # variants.
        allowed_paths = corridor.swept_paths
        if not allowed_paths:
            raise SpatialCapacityCertificateViolation(
                "elevator service-corridor certificate has no admissible paths",
                self._elevator_capacity_evidence(corridor, batch_size),
            )
        unused_paths = set(range(len(allowed_paths)))
        slot_indices: dict[int, int] = {}
        for passenger in self.cabin_passengers:
            passenger_id = int(passenger.unique_id)
            start = starts[passenger_id]
            end = releases[passenger_id]
            path_index = min(
                unused_paths,
                key=lambda index: (
                    hypot(start[0] - allowed_paths[index][0][0], start[1] - allowed_paths[index][0][1])
                    + hypot(end[0] - allowed_paths[index][-1][0], end[1] - allowed_paths[index][-1][1]),
                    index,
                ),
            )
            allowed_start = allowed_paths[path_index][0]
            allowed_end = allowed_paths[path_index][-1]
            mismatch = max(
                hypot(start[0] - allowed_start[0], start[1] - allowed_start[1]),
                hypot(end[0] - allowed_end[0], end[1] - allowed_end[1]),
            )
            if mismatch > 0.02:
                record_spatial_capacity_event(
                    self.model,
                    "placement.certificate_violation",
                    self._elevator_capacity_evidence(certificate, batch_size),
                )
                raise SpatialCapacityCertificateViolation(
                    f"runtime elevator path differs from certified batch path by "
                    f"{mismatch:.3f} m",
                    self._elevator_capacity_evidence(certificate, batch_size),
                )
            unused_paths.remove(path_index)
            slot_index = min(
                range(len(certificate.slots)),
                key=lambda index: hypot(
                    end[0] - certificate.slots[index][0],
                    end[1] - certificate.slots[index][1],
                ),
            )
            if hypot(
                end[0] - certificate.slots[slot_index][0],
                end[1] - certificate.slots[slot_index][1],
            ) > 0.02:
                raise SpatialCapacityCertificateViolation(
                    "runtime elevator endpoint is outside the certified release apron",
                    self._elevator_capacity_evidence(certificate, batch_size),
                )
            slot_indices[passenger_id] = slot_index
        return slot_indices

    def _elevator_capacity_evidence(self, certificate, requested: int):
        owners = getattr(self.model, "_spatial_capacity_slot_owners", {}).get(
            certificate.certificate_id,
            {},
        )
        return SpatialCapacityEvidence(
            certificate_id=certificate.certificate_id,
            resource_kind=certificate.resource_kind,
            owner_id=certificate.owner_id,
            certified_body_capacity=certificate.certified_body_capacity,
            current_occupancy_bodies=len(owners),
            requested_bodies=int(requested),
            passenger_id=None,
        )

    def _record_elevator_release_defer(self, code: str, requested: int) -> None:
        certificate = self._release_capacity_certificate()
        if certificate is None:
            return
        record_spatial_capacity_event(
            self.model,
            code,
            self._elevator_capacity_evidence(certificate, requested),
        )

    def _predicted_unloading_duration_seconds(self) -> float:
        """Return the batch's kinematic unload floor before departure."""

        if not self.cabin_passengers:
            return max(0.0, float(self._elevator_config.unload_seconds))
        starts = self._cabin_positions_at_center(self.portal_exit_position)
        releases = self._plan_self_clear_unloading_releases(
            self.cabin_passengers,
            starts,
        )
        if releases is None:
            return max(0.0, float(self._elevator_config.unload_seconds))
        return sum(self._unloading_durations_for(starts, releases))

    def _unloading_durations_for(
        self,
        starts: dict[int, tuple[float, float]],
        releases: dict[int, tuple[float, float]],
    ) -> list[float]:
        scenario = self.model.scenario
        count = max(1, len(self.cabin_passengers))
        base_segment_duration = (
            max(0.0, float(self._elevator_config.unload_seconds)) / count
        )
        max_speed = max(0.1, float(scenario.jupedsim_desired_speed_mps))
        max_acceleration = max(
            0.1,
            float(getattr(scenario, "cornering_acceleration_limit_m_s2", 3.2)),
        )
        durations: list[float] = []
        for passenger in self.cabin_passengers:
            passenger_id = int(passenger.unique_id)
            start = starts[passenger_id]
            end = releases[passenger_id]
            distance = hypot(end[0] - start[0], end[1] - start[1])
            durations.append(
                max(
                    base_segment_duration,
                    1.875 * distance / max_speed,
                    sqrt(5.774 * distance / max_acceleration),
                )
            )
        return durations

    def _update_active_event_unloading_deadline(self, phase_start_time_s: float) -> None:
        if self.active_event_id is None:
            return
        for index, event in enumerate(self.model.facility_service_events):
            if event.event_id != self.active_event_id:
                continue
            self.model.facility_service_events[index] = replace(
                event,
                end_time=(phase_start_time_s + self._effective_unloading_duration_seconds),
            )
            return

    def _unloading_paths_are_clear(self) -> bool:
        starts = {
            int(passenger.unique_id): tuple(passenger.pos) for passenger in self.cabin_passengers
        }
        return self._unloading_plan_clears_external_occupancy(
            starts,
            self._unloading_release_positions,
        )

    def _unloading_plan_clears_external_occupancy(
        self,
        starts: dict[int, tuple[float, float]],
        releases: dict[int, tuple[float, float]],
    ) -> bool:
        """Validate live landing blockers without double-counting cabin mates.

        ``_plan_self_clear_unloading_releases`` has already proved the FIFO
        swept geometry under its sequential occupancy model: earlier riders
        occupy release endpoints while later riders remain in their cabin
        cells.  Cabin riders must therefore not also appear as live landing
        obstacles here.  Ordinary landing occupants remain dynamic blockers.
        """

        external_positions = self._external_landing_positions()
        minimum_distance = self._release_min_distance()
        for passenger in self.cabin_passengers:
            passenger_id = int(passenger.unique_id)
            start = starts.get(passenger_id)
            end = releases.get(passenger_id)
            if start is None or end is None:
                return False
            path = (
                ShapelyPoint(start)
                if hypot(end[0] - start[0], end[1] - start[1]) <= 1e-9
                else LineString((start, end))
            )
            if any(
                path.distance(ShapelyPoint(position)) < minimum_distance - 1e-9
                for position in external_positions
            ):
                return False
        return True

    def _external_landing_positions(self) -> tuple[tuple[float, float], ...]:
        cabin_ids = {int(passenger.unique_id) for passenger in self.cabin_passengers}
        level_id = self.portal_exit_level_id
        return tuple(
            (float(other.pos[0]), float(other.pos[1]))
            for other in self.model.passengers
            if int(other.unique_id) not in cabin_ids
            and (level_id is None or other.current_level_id == level_id)
        )

    def _unloading_positions_at_ratio(
        self,
        ratio: float,
    ) -> dict[int, tuple[float, float]]:
        duration = max(0.0, float(self._effective_unloading_duration_seconds))
        elapsed = max(0.0, min(duration, float(ratio) * duration))
        segment_start = 0.0
        result: dict[int, tuple[float, float]] = {}
        for passenger_index, passenger in enumerate(self.cabin_passengers):
            passenger_id = int(passenger.unique_id)
            start = self._unloading_start_positions[passenger_id]
            end = self._unloading_release_positions[passenger_id]
            segment_duration = self._unloading_segment_durations_seconds[passenger_index]
            linear_ratio = max(
                0.0,
                min(
                    1.0,
                    (elapsed - segment_start) / max(1e-9, segment_duration),
                ),
            )
            passenger_ratio = minimum_jerk_progress(linear_ratio)
            result[passenger_id] = self.model.clamp_position(
                (
                    start[0] + (end[0] - start[0]) * passenger_ratio,
                    start[1] + (end[1] - start[1]) * passenger_ratio,
                )
            )
            segment_start += segment_duration
        return result

    def _update_unloading_positions(self) -> None:
        duration = max(0.0, float(self._effective_unloading_duration_seconds))
        ratio = (
            1.0
            if duration <= 1e-9
            else max(0.0, min(1.0, 1.0 - self.unload_remaining_seconds / duration))
        )
        positions = self._unloading_positions_at_ratio(ratio)
        for passenger in self.cabin_passengers:
            passenger.pos = positions[int(passenger.unique_id)]

    def _record_unloading_motion(
        self,
        *,
        interval_start_time_s: float,
        interval_end_time_s: float,
        remaining_before_s: float,
    ) -> None:
        if not self.cabin_passengers or self.active_event_id is None:
            return
        recorder = self.model.facility_motion_trace_recorder
        duration = max(0.0, float(self._effective_unloading_duration_seconds))
        episode_id = f"elevator:{self.facility_id}:{self.active_event_id}:unloading"
        level_id = "connector:" + str(self.spec.source_element_id or self.spec.facility_id)
        for time_s in recorder.sample_times(
            interval_start_time_s,
            interval_end_time_s,
        ):
            elapsed_in_interval = max(0.0, time_s - interval_start_time_s)
            remaining = max(0.0, float(remaining_before_s) - elapsed_in_interval)
            ratio = 1.0 if duration <= 1e-9 else max(0.0, min(1.0, 1.0 - remaining / duration))
            recorder.record_positions(
                time_seconds=time_s,
                level_id=level_id,
                phase="elevator_unloading",
                episode_id=episode_id,
                positions=self._unloading_positions_at_ratio(ratio),
            )

    def _update_boarding_positions(self) -> None:
        if not self.cabin_passengers:
            return
        if self.boarding_remaining_steps <= 0:
            self.boarding_remaining_seconds = 0.0
        duration = max(0.0, float(self._effective_boarding_duration_seconds))
        ratio = (
            1.0
            if duration <= 1e-9
            else max(0.0, min(1.0, 1.0 - self.boarding_remaining_seconds / duration))
        )
        positions = self._boarding_positions_at_ratio(ratio)
        for passenger in self.cabin_passengers:
            passenger.pos = positions[int(passenger.unique_id)]

    def _boarding_positions_at_ratio(
        self,
        ratio: float,
    ) -> dict[int, tuple[float, float]]:
        center = self.model.clamp_position(self.portal_entry_position)
        result: dict[int, tuple[float, float]] = {}
        duration = max(0.0, float(self._effective_boarding_duration_seconds))
        elapsed = max(0.0, min(duration, float(ratio) * duration))
        segment_start = 0.0
        for passenger_index, passenger in enumerate(self.cabin_passengers):
            passenger_id = int(passenger.unique_id)
            start = self._boarding_start_positions[passenger_id]
            offset = self._cabin_offsets_by_passenger[passenger_id]
            destination = (center[0] + offset[0], center[1] + offset[1])
            segment_duration = self._boarding_segment_duration(passenger_index)
            linear_ratio = (
                1.0
                if segment_duration <= 1e-9 and elapsed >= segment_start
                else max(
                    0.0,
                    min(1.0, (elapsed - segment_start) / max(1e-9, segment_duration)),
                )
            )
            passenger_ratio = minimum_jerk_progress(linear_ratio)
            result[passenger_id] = self.model.clamp_position(
                (
                    start[0] + (destination[0] - start[0]) * passenger_ratio,
                    start[1] + (destination[1] - start[1]) * passenger_ratio,
                )
            )
            segment_start += segment_duration
        return result

    def _record_boarding_motion(
        self,
        *,
        interval_start_time_s: float,
        interval_end_time_s: float,
        remaining_before_s: float,
    ) -> None:
        if not self.cabin_passengers or self.active_event_id is None:
            return
        recorder = self.model.facility_motion_trace_recorder
        duration = max(0.0, float(self._effective_boarding_duration_seconds))
        episode_id = f"elevator:{self.facility_id}:{self.active_event_id}:boarding"
        level_id = "connector:" + str(self.spec.source_element_id or self.spec.facility_id)
        for time_s in recorder.sample_times(
            interval_start_time_s,
            interval_end_time_s,
        ):
            elapsed_in_interval = max(0.0, time_s - interval_start_time_s)
            remaining = max(0.0, float(remaining_before_s) - elapsed_in_interval)
            ratio = 1.0 if duration <= 1e-9 else max(0.0, min(1.0, 1.0 - remaining / duration))
            recorder.record_positions(
                time_seconds=time_s,
                level_id=level_id,
                phase="elevator_boarding",
                episode_id=episode_id,
                positions=self._boarding_positions_at_ratio(ratio),
            )

    def _set_cabin_positions(self, position: tuple[float, float]) -> None:
        if len(self._cabin_offsets_by_passenger) != len(self.cabin_passengers):
            self._assign_cabin_offsets()
        positions = self._cabin_positions_at_center(position)
        for passenger in self.cabin_passengers:
            passenger.pos = positions[int(passenger.unique_id)]

    def _cabin_positions_at_center(
        self,
        position: tuple[float, float],
    ) -> dict[int, tuple[float, float]]:
        if len(self._cabin_offsets_by_passenger) != len(self.cabin_passengers):
            self._assign_cabin_offsets()
        center = self.model.clamp_position(position)
        return {
            int(passenger.unique_id): self.model.clamp_position(
                (
                    center[0] + self._cabin_offsets_by_passenger[int(passenger.unique_id)][0],
                    center[1] + self._cabin_offsets_by_passenger[int(passenger.unique_id)][1],
                )
            )
            for passenger in self.cabin_passengers
        }

    def _assign_cabin_offsets(self) -> None:
        self._cabin_offsets_by_passenger = self._plan_cabin_offsets(
            self.cabin_passengers,
        )

    def _configure_boarding_motion_profile(self) -> None:
        """Allocate FIFO motion time from speed and acceleration limits."""

        passenger_count = len(self.cabin_passengers)
        if passenger_count <= 0:
            self._boarding_segment_durations_seconds = ()
            self._effective_boarding_duration_seconds = 0.0
            return
        scenario = self.model.scenario
        base_duration = max(0.0, float(self._elevator_config.boarding_seconds))
        base_segment_duration = base_duration / passenger_count
        max_speed = max(0.1, float(scenario.jupedsim_desired_speed_mps))
        max_acceleration = max(
            0.1,
            float(getattr(scenario, "cornering_acceleration_limit_m_s2", 3.2)),
        )
        center = self.model.clamp_position(self.portal_entry_position)
        durations: list[float] = []
        for passenger in self.cabin_passengers:
            passenger_id = int(passenger.unique_id)
            start = self._boarding_start_positions[passenger_id]
            offset = self._cabin_offsets_by_passenger[passenger_id]
            end = (center[0] + offset[0], center[1] + offset[1])
            distance = hypot(end[0] - start[0], end[1] - start[1])
            # Quintic minimum-jerk progress has max normalized speed 1.875
            # and max normalized acceleration about 5.774.  Sizing each FIFO
            # segment from both limits prevents the process-owned path from
            # introducing a start/stop acceleration spike at 5 Hz sampling.
            speed_duration = 1.875 * distance / max_speed
            acceleration_duration = sqrt(5.774 * distance / max_acceleration)
            durations.append(
                max(
                    base_segment_duration,
                    speed_duration,
                    acceleration_duration,
                )
            )
        self._boarding_segment_durations_seconds = tuple(durations)
        self._effective_boarding_duration_seconds = sum(durations)

    def _boarding_segment_duration(self, passenger_index: int) -> float:
        if passenger_index < len(self._boarding_segment_durations_seconds):
            return float(self._boarding_segment_durations_seconds[passenger_index])
        passenger_count = max(1, len(self.cabin_passengers))
        return max(0.0, float(self._elevator_config.boarding_seconds)) / passenger_count

    def _plan_cabin_offsets(
        self,
        passengers: list[PassengerAgent],
    ) -> dict[int, tuple[float, float]]:
        """Plan a safe FIFO boarding sweep without mutating cabin state."""

        passenger_count = len(passengers)
        if passenger_count <= 0:
            return {}
        scenario = self.model.scenario
        # These are native JuPedSim waiting targets, not merely geometric body
        # placements.  Targets separated by only 2r can be collision-free yet
        # unreachable because a rider approaching a stationary cabin mate
        # settles at the operational model's personal-space equilibrium.  Use
        # the declared personal-space contract so every FIFO member can reach
        # its own centimetre-audited endpoint without pushing its predecessor.
        spacing = max(
            self._release_spacing(),
            float(scenario.jupedsim_agent_radius_units) * 2.2,
            float(getattr(scenario, "personal_space_units", 0.8)),
        )
        column_count = max(1, ceil(sqrt(passenger_count)))
        row_count = max(1, ceil(passenger_count / column_count))
        forward, lateral = self._release_axes()
        candidate_offsets: list[tuple[float, float]] = []
        for index in range(passenger_count):
            row = index // column_count
            column = index % column_count
            forward_offset = (row - (row_count - 1) / 2.0) * spacing
            lateral_offset = (column - (column_count - 1) / 2.0) * spacing
            candidate_offsets.append(
                (
                    forward[0] * forward_offset + lateral[0] * lateral_offset,
                    forward[1] * forward_offset + lateral[1] * lateral_offset,
                )
            )
        center = self.model.clamp_position(self.portal_entry_position)
        start_positions = {
            int(passenger.unique_id): self._boarding_start_positions.get(
                int(passenger.unique_id),
                (float(passenger.pos[0]), float(passenger.pos[1])),
            )
            for passenger in passengers
        }
        selected_ids = {int(passenger.unique_id) for passenger in passengers}
        stationary_queue_positions = tuple(
            (float(passenger.pos[0]), float(passenger.pos[1]))
            for passenger in self.queue
            if int(passenger.unique_id) not in selected_ids
        )
        return _collision_free_offset_assignment(
            passengers,
            start_positions=start_positions,
            center=center,
            candidate_offsets=tuple(candidate_offsets),
            minimum_distance=self._release_min_distance(),
            external_stationary_positions=stationary_queue_positions,
            final_assignment_validator=lambda offsets: self._static_unloading_sweep_is_feasible(
                passengers, offsets
            ),
        )

    def _static_unloading_sweep_is_feasible(
        self,
        passengers: list[PassengerAgent],
        offsets_by_passenger: dict[int, tuple[float, float]],
    ) -> bool:
        """Prove a boarded FIFO can leave without blocking itself at arrival.

        Live landing occupants are deliberately excluded: they may move before
        arrival and remain a runtime hold condition. Cabin mates and passengers
        already released by this batch are structural constraints, so they
        must be satisfiable before the cabin accepts the group.
        """

        center = self.model.clamp_position(self.portal_exit_position)
        starts = {
            int(passenger.unique_id): self.model.clamp_position(
                (
                    center[0] + offsets_by_passenger[int(passenger.unique_id)][0],
                    center[1] + offsets_by_passenger[int(passenger.unique_id)][1],
                )
            )
            for passenger in passengers
        }
        return self._plan_self_clear_unloading_releases(passengers, starts) is not None

    def _plan_self_clear_unloading_releases(
        self,
        passengers: list[PassengerAgent],
        starts: dict[int, tuple[float, float]],
        *,
        external_stationary_positions: tuple[tuple[float, float], ...] = (),
    ) -> dict[int, tuple[float, float]] | None:
        """Plan the exact FIFO endpoints later used by cabin unloading."""

        try:
            area = self.model.jupedsim_walkable_area(self.portal_exit_level_id).buffer(1e-7)
        except (AttributeError, LookupError, TypeError, ValueError):
            return None
        body_radius = max(
            0.02,
            float(self.model.scenario.jupedsim_agent_radius_units),
        )
        minimum_distance = self._release_min_distance()
        # JuPedSim's collision-free-speed model can settle before a target
        # that lies inside a stationary pedestrian's personal-space disc even
        # though the bodies remain geometrically collision-free.  A landing
        # release endpoint is therefore viable only outside that operational
        # disc.  The swept path still uses the physical body clearance below,
        # allowing a rider that arrives near a queue to move away from it.
        endpoint_clearance = max(
            minimum_distance,
            float(getattr(self.model.scenario, "personal_space_units", 0.8)),
        )
        forward, _lateral = self._release_axes()
        spacing = self._release_spacing()
        projection_limit = max(0.05, body_radius)
        forward_steps = list(range(max(0, int(self.spec.release_forward_extra)) + 1))
        if len(forward_steps) > 1:
            forward_steps = [1, 0, *forward_steps[2:]]
        released_positions: list[tuple[float, float]] = []
        releases: dict[int, tuple[float, float]] = {}
        passenger_ids = tuple(int(passenger.unique_id) for passenger in passengers)
        for passenger_index, passenger_id in enumerate(passenger_ids):
            start = starts[passenger_id]
            stationary_positions = [
                *released_positions,
                *(starts[other_id] for other_id in passenger_ids[passenger_index + 1 :]),
            ]
            selected: tuple[float, float] | None = None
            for forward_step in forward_steps:
                candidate = (
                    start[0] + forward[0] * spacing * forward_step,
                    start[1] + forward[1] * spacing * forward_step,
                )
                projected = self._project_release_position(candidate)
                if (
                    hypot(
                        projected[0] - candidate[0],
                        projected[1] - candidate[1],
                    )
                    > projection_limit
                ):
                    continue
                path = (
                    ShapelyPoint(start)
                    if hypot(projected[0] - start[0], projected[1] - start[1]) <= 1e-9
                    else LineString((start, projected))
                )
                if not area.covers(path.buffer(body_radius, cap_style="round")):
                    continue
                if any(
                    path.distance(ShapelyPoint(position)) < minimum_distance - 1e-9
                    for position in (*stationary_positions, *external_stationary_positions)
                ):
                    continue
                if any(
                    hypot(
                        projected[0] - position[0],
                        projected[1] - position[1],
                    )
                    < endpoint_clearance - 1e-9
                    for position in external_stationary_positions
                ):
                    continue
                selected = projected
                break
            if selected is None:
                return None
            released_positions.append(selected)
            releases[passenger_id] = selected
        return releases


def _collision_free_offset_assignment(
    passengers: list[PassengerAgent],
    *,
    start_positions: dict[int, tuple[float, float]],
    center: tuple[float, float],
    candidate_offsets: tuple[tuple[float, float], ...],
    minimum_distance: float,
    external_stationary_positions: tuple[tuple[float, float], ...] = (),
    final_assignment_validator: Callable[[dict[int, tuple[float, float]]], bool] | None = None,
) -> dict[int, tuple[float, float]]:
    """Assign cabin cells for a FIFO, one-body-at-a-time boarding phase.

    During passenger ``i``'s sub-interval, earlier bodies are stationary in
    their cabin cells and later bodies are stationary in their queue poses.
    An arbitrary row-major assignment can route a body through either set even
    though all endpoints are clear.  This deterministic matcher only accepts
    cabin cells whose entire swept segment clears both stationary sets.
    """

    if len(passengers) != len(candidate_offsets):
        raise ValueError("cabin offset assignment requires one cell per passenger")
    passenger_ids = tuple(int(passenger.unique_id) for passenger in passengers)
    final_positions = tuple(
        (center[0] + offset[0], center[1] + offset[1]) for offset in candidate_offsets
    )
    assigned_slots: dict[int, int] = {}
    used_slots: set[int] = set()

    def search(passenger_index: int) -> bool:
        if passenger_index >= len(passenger_ids):
            if final_assignment_validator is None:
                return True
            offsets = {
                passenger_id: candidate_offsets[assigned_slots[passenger_id]]
                for passenger_id in passenger_ids
            }
            return bool(final_assignment_validator(offsets))
        passenger_id = passenger_ids[passenger_index]
        start = start_positions[passenger_id]
        options = sorted(
            (index for index in range(len(candidate_offsets)) if index not in used_slots),
            key=lambda index: (
                hypot(
                    final_positions[index][0] - start[0],
                    final_positions[index][1] - start[1],
                ),
                index,
            ),
        )
        for slot_index in options:
            end = final_positions[slot_index]
            stationary_positions = [
                final_positions[other_slot] for other_slot in assigned_slots.values()
            ]
            stationary_positions.extend(
                start_positions[other_id] for other_id in passenger_ids[passenger_index + 1 :]
            )
            stationary_positions.extend(external_stationary_positions)
            if any(
                _point_to_segment_distance(position, start, end) < minimum_distance - 1e-9
                for position in stationary_positions
            ):
                continue
            assigned_slots[passenger_id] = slot_index
            used_slots.add(slot_index)
            if search(passenger_index + 1):
                return True
            used_slots.remove(slot_index)
            assigned_slots.pop(passenger_id, None)
        return False

    if not search(0):
        raise RuntimeError("elevator boarding has no collision-free passenger-to-cabin assignment")
    return {
        passenger_id: candidate_offsets[assigned_slots[passenger_id]]
        for passenger_id in passenger_ids
    }


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
    ratio = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared,
        ),
    )
    return hypot(
        point[0] - (start[0] + dx * ratio),
        point[1] - (start[1] + dy * ratio),
    )
