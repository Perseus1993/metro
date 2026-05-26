from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .design.schema import StationDesignDocument


@dataclass(frozen=True)
class GateSpec:
    label: str
    position: tuple[float, float]
    queue_anchor: tuple[float, float]
    exit_position: tuple[float, float]


@dataclass(frozen=True)
class VerticalTransportSpec:
    label: str
    kind: str
    direction: str
    position: tuple[float, float]
    queue_anchor: tuple[float, float]
    exit_position: tuple[float, float]
    persons_per_min: int
    speed_units_per_tick: float


@dataclass(frozen=True)
class BoardingDoorSpec:
    label: str
    position: tuple[float, float]
    queue_anchor: tuple[float, float]
    persons_per_min: int
    train_direction: str = "down"
    line_id: str = "default"


@dataclass(frozen=True)
class StationGeometry:
    """Explanatory two-level metro station layout in drawing units."""

    width: float = 120.0
    height: float = 90.0
    entrances: tuple[tuple[float, float], ...] = ((8.0, 17.0), (8.0, 30.0))
    unpaid_hall_center: tuple[float, float] = (21.0, 24.0)
    gate_decision_point: tuple[float, float] = (27.0, 24.0)
    paid_hall_center: tuple[float, float] = (55.0, 24.0)
    vertical_decision_point: tuple[float, float] = (77.0, 24.0)
    platform_transfer_hub: tuple[float, float] = (82.0, 58.0)
    platform_entry: tuple[float, float] = (89.0, 64.0)
    platform_center: tuple[float, float] = (86.0, 66.0)
    train_door: tuple[float, float] = (103.5, 74.0)
    queue_spacing: float = 0.72
    platform_spacing: float = 0.9
    gates: tuple[GateSpec, ...] = (
        GateSpec("G1", (35.0, 14.0), (29.0, 14.0), (41.0, 14.0)),
        GateSpec("G2", (35.0, 20.0), (29.0, 20.0), (41.0, 20.0)),
        GateSpec("G3", (35.0, 26.0), (29.0, 26.0), (41.0, 26.0)),
        GateSpec("G4", (35.0, 32.0), (29.0, 32.0), (41.0, 32.0)),
    )
    exit_gates: tuple[GateSpec, ...] = (
        GateSpec("X1", (35.0, 17.0), (41.0, 17.0), (29.0, 17.0)),
        GateSpec("X2", (35.0, 23.0), (41.0, 23.0), (29.0, 23.0)),
        GateSpec("X3", (35.0, 29.0), (41.0, 29.0), (29.0, 29.0)),
    )
    vertical_transports: tuple[VerticalTransportSpec, ...] = (
        VerticalTransportSpec(
            "下行扶梯1", "escalator", "down", (76.0, 14.0), (69.0, 14.0), (72.0, 55.0), 75, 2.3
        ),
        VerticalTransportSpec(
            "下行扶梯2", "escalator", "down", (83.0, 14.0), (76.0, 14.0), (84.0, 55.0), 75, 2.3
        ),
        VerticalTransportSpec(
            "上行扶梯1", "escalator", "up", (76.0, 27.0), (69.0, 27.0), (72.0, 67.0), 75, 2.3
        ),
        VerticalTransportSpec(
            "上行扶梯2", "escalator", "up", (83.0, 27.0), (76.0, 27.0), (84.0, 67.0), 75, 2.3
        ),
        VerticalTransportSpec(
            "直梯", "elevator", "both", (91.0, 18.0), (85.0, 18.0), (95.0, 58.0), 24, 4.2
        ),
        VerticalTransportSpec(
            "楼梯", "stairs", "both", (91.0, 32.0), (85.0, 32.0), (96.0, 66.0), 125, 1.55
        ),
    )
    boarding_doors: tuple[BoardingDoorSpec, ...] = (
        BoardingDoorSpec("D1", (48.0, 74.0), (48.0, 66.0), 150),
        BoardingDoorSpec("D2", (60.0, 74.0), (60.0, 66.0), 150),
        BoardingDoorSpec("D3", (72.0, 74.0), (72.0, 66.0), 150),
        BoardingDoorSpec("D4", (84.0, 74.0), (84.0, 66.0), 150),
        BoardingDoorSpec("D5", (96.0, 74.0), (96.0, 66.0), 150),
        BoardingDoorSpec("D6", (108.0, 74.0), (108.0, 66.0), 150),
    )


@dataclass(frozen=True)
class StationSandboxScenario:
    """Scenario parameters for the Mesa station sandbox."""

    station_name: str
    hour: int
    minutes: int
    tick_seconds: int
    group_size: int
    entry_count_hour: int
    exit_count_hour: int
    source_label: str
    sample_hours: int
    train_headway_seconds: int = 240
    train_dwell_seconds: int = 35
    train_capacity_persons: int = 1200
    platform_capacity_persons: int = 5000
    boarding_persons_per_min: int = 900
    gate_service_persons_per_min: int = 55
    initial_train_offset_seconds: int = 75
    walk_units_per_tick: float = 2.0
    movement_backend_name: str = "jupedsim"
    jupedsim_operational_model: str = "collision_free_speed"
    jupedsim_strict: bool = True
    audit_enabled: bool = True
    audit_print_events: bool = True
    boarding_speed_multiplier: float = 4.0
    elevator_preference_share: float = 0.08
    elevator_cabin_capacity_persons: int = 12
    elevator_boarding_seconds: float = 5.0
    elevator_cycle_seconds: float = 35.0
    stairs_preference_share: float = 0.18
    crowd_radius_units: float = 2.4
    personal_space_units: float = 0.8
    repulsion_strength: float = 0.16
    density_slowdown_strength: float = 0.035
    min_walk_speed_factor: float = 0.55
    max_repulsion_units_per_tick: float = 0.35
    interaction_sample_limit: int = 32
    crowding_sample_size: int = 300
    jupedsim_iterations_per_tick: int = 150
    jupedsim_agent_radius_units: float = 0.18
    jupedsim_target_radius_units: float = 0.45
    jupedsim_neighbor_radius_units: float = 2.4
    jupedsim_neighbor_sample_limit: int = 12
    jupedsim_clearance_multiplier: float = 2.2
    facility_choice_logit_sensitivity: float = 1.0
    replan_avoided_facility_penalty: float = 4.0
    progress_monitor_enabled: bool = True
    progress_stall_seconds: float = 20.0
    queue_replan_wait_seconds: float = 90.0
    progress_min_delta_units: float = 0.25
    replan_max_attempts_per_stage: int = 2
    admin_agent_count: int = 0
    admin_guide_radius_units: float = 18.0
    admin_patrol_speed_units_per_tick: float = 1.2
    gate_queue_slots_per_row: int = 22
    vertical_queue_slots_per_row: int = 18
    boarding_queue_slots_per_row: int = 18
    platform_boarding_release_groups_per_door_tick: int = 3
    platform_waiting_slots_per_row: int = 28
    platform_waiting_row_cycle: int = 9
    platform_waiting_x_step: float = 0.95
    platform_waiting_min_y: float = 55.0
    platform_waiting_max_y: float = 82.0
    platform_waiting_max_x: float = 102.0
    geometry: StationGeometry = StationGeometry()
    station_design: StationDesignDocument | None = None

    @property
    def horizon_steps(self) -> int:
        return max(1, int(self.minutes * 60 / self.tick_seconds))

    @property
    def entry_groups(self) -> int:
        return self._groups_for_hour_count(self.entry_count_hour)

    @property
    def exit_groups(self) -> int:
        return self._groups_for_hour_count(self.exit_count_hour)

    def _groups_for_hour_count(self, count_hour: int) -> int:
        scenario_count = max(0, int(count_hour)) * (self.minutes / 60.0)
        return max(0, round(scenario_count / self.group_size))

    def with_minutes(self, minutes: int) -> "StationSandboxScenario":
        return replace(self, minutes=minutes)

    def default_output_path(self) -> Path:
        safe_station = "".join(ch if ch.isalnum() else "_" for ch in self.station_name)
        return Path("output") / f"metro_station_sandbox_{safe_station}_{self.hour:02d}.html"
