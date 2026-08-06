from __future__ import annotations

from math import ceil, floor, hypot
from typing import Any

from ..facilities.process import FacilityKind, FacilitySpec
from ..station.facility_portal_binding import FacilityPortalBinding, Point
from .geometry_reachability import GeometryCompilePolicy


def release_spacing(
    facility: FacilitySpec,
    policy: GeometryCompilePolicy,
) -> float:
    clearance = policy.two_body_clearance_m + float(facility.release_clearance_pad)
    personal = policy.personal_space_m * float(facility.release_personal_factor)
    return max(
        float(facility.release_spacing_min),
        min(float(facility.release_spacing_max), max(clearance, personal)),
    )


def required_release_bodies(
    facility: FacilitySpec,
    binding: FacilityPortalBinding,
    scenario: Any,
    spacing: float,
) -> int:
    if facility.kind == FacilityKind.ELEVATOR.value:
        elevator = None if facility.vertical_config is None else facility.vertical_config.elevator
        person_capacity = int(
            scenario.elevator_cabin_capacity_persons
            if elevator is None
            else elevator.batch_capacity
        )
        return max(1, person_capacity // max(1, int(scenario.group_size)))
    if facility.kind in {FacilityKind.ESCALATOR.value, FacilityKind.TRAIN_DOOR.value}:
        return 1
    if facility.kind == FacilityKind.STAIRS.value:
        width = max(spacing, float(facility.traversal_width_m or spacing))
        return max(1, floor(width / spacing))
    group_size = max(1, int(scenario.group_size))
    groups_per_second = max(0.0, float(facility.service_persons_per_min)) / group_size / 60.0
    groups_per_tick = groups_per_second * max(0.001, float(scenario.tick_seconds))
    distance = hypot(
        binding.entry_point[0] - binding.exit_point[0],
        binding.entry_point[1] - binding.exit_point[1],
    )
    traversal_seconds = distance / max(0.001, float(scenario.jupedsim_desired_speed_mps))
    concurrent = max(1, ceil(groups_per_second * traversal_seconds))
    return max(concurrent, ceil(groups_per_tick))


def release_candidate_grid(
    facility: FacilitySpec,
    binding: FacilityPortalBinding,
    spacing: float,
    required: int,
    *,
    minimum_clearance: float,
) -> tuple[Point, ...]:
    columns = max(1, int(facility.release_column_count))
    column_order = _centered_offsets(columns)
    # Express the finite search prefix in admissible body rows. Release lattice
    # spacing may be smaller than the body-clear certificate spacing, in which
    # case only every Nth raw row can survive validation.
    admissible_row_stride = max(1, ceil(max(0.0, minimum_clearance) / spacing - 1e-9))
    admissible_rows = max(
        max(1, int(facility.release_forward_extra) + 1),
        ceil(max(1, required) / columns) + max(4, int(facility.release_forward_extra)),
    )
    rows = admissible_rows * admissible_row_stride
    forward = binding.release_forward
    lateral = binding.release_lateral
    base = binding.exit_point
    return tuple(
        (
            round(base[0] + forward[0] * row * spacing + lateral[0] * column * spacing, 6),
            round(base[1] + forward[1] * row * spacing + lateral[1] * column * spacing, 6),
        )
        for row in range(rows)
        for column in column_order
    )


def _centered_offsets(count: int) -> tuple[int, ...]:
    values = [0]
    offset = 1
    while len(values) < max(1, int(count)):
        values.append(-offset)
        if len(values) >= count:
            break
        values.append(offset)
        offset += 1
    return tuple(values)
