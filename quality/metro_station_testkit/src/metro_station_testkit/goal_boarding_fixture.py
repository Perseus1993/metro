"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metro_station.adapters.simulation.facilities.process import FacilityKind, FacilitySpec, QueueLayout
from metro_station.adapters.simulation.planning.plan import AgentState, FacilityStage
from metro_station.adapters.simulation.runtime.simulation_clock import PHYSICAL_CLOCK

if TYPE_CHECKING:
    from .goal_boarding_micro_scene import (
        ControllableBoardingDoorProcessAgent,
        GoalBoardingMicroScene,
    )


PLATFORM_LEVEL = "platform"
PLATFORM_ID = "platform:probe:down"


@dataclass(frozen=True)
class GoalBoardingMicroScenario:
    tick_seconds: float = 0.25
    group_size: int = 1
    walk_units_per_tick: float = 0.3
    movement_trace_sample_seconds: float = 0.2
    jupedsim_desired_speed_mps: float = 1.2
    cornering_acceleration_limit_m_s2: float = 3.2
    cornering_acceleration_window_s: float = 0.4
    initial_train_offset_seconds: float = 15.0
    train_dwell_seconds: float = 20.0
    train_headway_seconds: float = 60.0
    train_capacity_persons: int = 100
    platform_capacity_persons: int = 200
    jupedsim_dt_seconds: float = 0.01
    jupedsim_iterations_per_tick: int = 25
    jupedsim_agent_radius_units: float = 0.22
    jupedsim_target_radius_units: float = 0.38
    jupedsim_clearance_multiplier: float = 2.0
    jupedsim_neighbor_radius_units: float = 2.5
    jupedsim_neighbor_sample_limit: int = 12
    jupedsim_operational_model: str = "collision_free_speed"
    jupedsim_strict: bool = True
    simulation_clock_mode: str = PHYSICAL_CLOCK
    personal_space_units: float = 0.8


def make_boarding_door(
    model: GoalBoardingMicroScene,
    short_id: str,
    y: float,
) -> ControllableBoardingDoorProcessAgent:
    from .goal_boarding_micro_scene import ControllableBoardingDoorProcessAgent

    queue_anchor = (17.0, y)
    slots = tuple((17.0 - index * 0.65, y) for index in range(12))
    spec = FacilitySpec(
        facility_id=short_id,
        stage=FacilityStage.BOARDING_DOOR.value,
        label=short_id,
        kind=FacilityKind.TRAIN_DOOR.value,
        direction="down",
        position=(19.0, y),
        queue_layout=QueueLayout(
            anchor=queue_anchor,
            per_row=1,
            col_step=(0.0, 0.0),
            row_step=(-0.65, 0.0),
            slots=slots,
        ),
        exit_position=(19.0, y),
        service_persons_per_min=240,
        queue_state=AgentState.QUEUEING_DOOR.value,
        service_state=AgentState.BOARDING_TRAIN.value,
        release_route=(),
        train_gated=True,
        train_capacity_limited=True,
        line_id="probe_line",
        platform_id=PLATFORM_ID,
        entry_level_id=PLATFORM_LEVEL,
        exit_level_id=PLATFORM_LEVEL,
    )
    return ControllableBoardingDoorProcessAgent(model, spec=spec)
