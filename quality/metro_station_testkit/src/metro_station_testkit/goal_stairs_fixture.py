"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metro_station.adapters.simulation.facilities.process import FacilityKind, FacilitySpec, QueueLayout
from metro_station.adapters.simulation.facilities.vertical import StairsConfig, VerticalFacilityConfig
from metro_station.adapters.simulation.planning.plan import AgentState, FacilityStage
from metro_station.adapters.simulation.runtime.simulation_clock import PHYSICAL_CLOCK

if TYPE_CHECKING:
    from .goal_stairs_micro_scene import ControllableStairsProcessAgent, GoalStairsMicroScene


CONCOURSE_LEVEL = "concourse"
PLATFORM_LEVEL = "platform"


@dataclass(frozen=True)
class GoalStairsMicroScenario:
    tick_seconds: float = 0.25
    group_size: int = 1
    walk_units_per_tick: float = 0.3
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


def make_stairs(
    model: GoalStairsMicroScene,
    short_id: str,
    y: float,
) -> ControllableStairsProcessAgent:
    from .goal_stairs_micro_scene import ControllableStairsProcessAgent

    queue_anchor = (16.0, y)
    slots = tuple((16.0 - index * 0.65, y) for index in range(12))
    spec = FacilitySpec(
        facility_id=short_id,
        stage=FacilityStage.VERTICAL_TRANSFER.value,
        label=short_id,
        kind=FacilityKind.STAIRS.value,
        direction="down",
        position=(17.0, y),
        queue_layout=QueueLayout(
            anchor=queue_anchor,
            per_row=1,
            col_step=(0.0, 0.0),
            row_step=(-0.65, 0.0),
            slots=slots,
        ),
        exit_position=(22.0, y),
        service_persons_per_min=240,
        queue_state=AgentState.QUEUEING_VERTICAL.value,
        service_state=AgentState.RIDING_VERTICAL.value,
        release_route=(),
        speed_units_per_tick=0.72,
        entry_level_id=CONCOURSE_LEVEL,
        exit_level_id=PLATFORM_LEVEL,
        traversal_width_m=1.5,
        vertical_config=VerticalFacilityConfig(
            stairs=StairsConfig(
                base_capacity_ppm=240,
                fatigue_cost_up=0.6,
                fatigue_cost_down=0.18,
                bidirectional_conflict_factor=0.0,
            )
        ),
    )
    return ControllableStairsProcessAgent(model, spec=spec)
