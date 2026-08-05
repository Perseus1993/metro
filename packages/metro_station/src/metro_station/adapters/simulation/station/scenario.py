from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING

from metro_station.application.control_plans import ControlPlan, validate_control_plan_schedule
from metro_station.domain.time_boundaries import first_step_not_before

from ..calibration.contracts import CalibrationProfile
from .demand import DemandSegment, validate_demand_segments, validate_entrance_weights
from .disruptions import (
    FacilityAvailabilityEvent,
    validate_facility_availability_events,
)
from .evacuation import (
    EVACUATION_MODE,
    OPERATIONS_MODE,
    SUPPORTED_SCENARIO_MODES,
    EvacuationScenarioConfig,
)
from .train_disruptions import (
    TrainCapacityEvent,
    TrainServiceAvailabilityEvent,
    validate_train_capacity_events,
    validate_train_service_events,
)

if TYPE_CHECKING:
    from ..design.schema import StationDesignDocument


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
    concourse_level_id: str = "B1"
    platform_level_id: str = "B2"
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
    scenario_mode: str = OPERATIONS_MODE
    evacuation: EvacuationScenarioConfig | None = None
    calibration_profile: CalibrationProfile = field(default_factory=CalibrationProfile)
    transfer_count_hour: int = 0
    demand_segments: tuple[DemandSegment, ...] = ()
    entry_entrance_weights: tuple[tuple[str, float], ...] = ()
    disabled_facility_ids: tuple[str, ...] = ()
    facility_availability_events: tuple[FacilityAvailabilityEvent, ...] = ()
    train_service_events: tuple[TrainServiceAvailabilityEvent, ...] = ()
    train_capacity_events: tuple[TrainCapacityEvent, ...] = ()
    control_plan: ControlPlan | None = None
    demand_minutes: int | None = None
    train_headway_seconds: int = 240
    train_dwell_seconds: int = 35
    train_capacity_persons: int = 1200
    platform_capacity_persons: int = 5000
    boarding_persons_per_min: int = 900
    gate_service_persons_per_min: int = 55
    entry_admission_residence_seconds: float | None = None
    entry_admission_residence_percentile: str | None = None
    entry_admission_residence_evidence_ref: str | None = None
    exit_admission_residence_seconds: float | None = None
    exit_admission_residence_percentile: str | None = None
    exit_admission_residence_evidence_ref: str | None = None
    admission_residence_evidence_seed: int | None = None
    entry_admission_burst_sigma: float = 3.0
    entry_admission_token_capacity: int | None = None
    exit_admission_token_capacity: int | None = None
    initial_train_offset_seconds: int = 75
    walk_units_per_tick: float = 2.0
    movement_backend_name: str = "jupedsim"
    # JuPedSim's collision-free speed model is its reference choice for
    # corners, bottlenecks, and queue stages.  The force model can settle into
    # a wall equilibrium even for one pedestrian in a concave station domain.
    jupedsim_operational_model: str = "collision_free_speed"
    jupedsim_desired_speed_mps: float = 1.2
    jupedsim_free_speed_std_mps: float = 0.12
    jupedsim_free_speed_min_mps: float = 0.75
    jupedsim_free_speed_max_mps: float = 1.65
    jupedsim_strict: bool = True
    simulation_clock_mode: str = "legacy_scaled"
    goal_graph_mode: str = "active"
    goal_graph_catalog_path: str | None = None
    jupedsim_dt_seconds: float = 0.01
    movement_trace_sample_seconds: float = 0.2
    cornering_acceleration_limit_m_s2: float = 3.2
    cornering_acceleration_window_s: float = 0.4
    cornering_lookahead_m: float = 2.5
    cornering_recovery_m: float = 1.2
    cornering_min_speed_mps: float = 0.35
    cornering_unknown_transition_speed_mps: float = 0.65
    cornering_min_turn_degrees: float = 30.0
    audit_enabled: bool = True
    audit_print_events: bool = True
    boarding_speed_multiplier: float = 4.0
    elevator_preference_share: float = 0.08
    elevator_preference_mismatch_penalty_seconds: float = 72.0
    stairs_preference_mismatch_penalty_seconds: float = 48.0
    nonpreferred_elevator_penalty_seconds: float = 15.0
    escalator_speed_units_per_tick: float = 2.3
    stairs_speed_units_per_tick: float = 1.55
    elevator_speed_units_per_tick: float = 4.2
    escalator_speed_m_s: float = 0.5
    stopped_escalator_walk_speed_m_s: float = 0.35
    stairs_speed_m_s: float = 0.7
    elevator_speed_m_s: float = 0.8
    elevator_cabin_capacity_persons: int = 12
    elevator_min_dispatch_persons: int = 8
    elevator_max_dispatch_wait_seconds: float = 18.0
    elevator_boarding_seconds: float = 5.0
    elevator_cycle_seconds: float = 35.0
    elevator_unload_seconds: float = 0.0
    stairs_preference_share: float = 0.18
    stair_fatigue_cost_up: float = 0.6
    stair_fatigue_cost_down: float = 0.15
    stair_bidirectional_conflict_factor: float = 0.3
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
    alighting_source_lateral_offset_m: float = 0.0
    gate_lane_edge_inset_max: float = 0.45
    facility_choice_logit_sensitivity: float = 1.0
    replan_avoided_facility_penalty: float = 4.0
    facility_commitment_seconds: float = 15.0
    facility_replan_cooldown_seconds: float = 30.0
    facility_replan_minimum_improvement_seconds: float = 5.0
    progress_monitor_enabled: bool = True
    progress_stall_seconds: float = 20.0
    queue_replan_wait_seconds: float = 90.0
    progress_min_delta_units: float = 0.25
    liveness_fail_fast_seconds: float = 120.0
    liveness_min_displacement_units: float = 0.05
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

    def __post_init__(self) -> None:
        if self.scenario_mode not in SUPPORTED_SCENARIO_MODES:
            choices = ", ".join(sorted(SUPPORTED_SCENARIO_MODES))
            raise ValueError(f"scenario_mode must be one of {choices}; got {self.scenario_mode!r}")
        if self.scenario_mode == EVACUATION_MODE and self.evacuation is None:
            raise ValueError("evacuation config is required when scenario_mode='evacuation'")
        if self.evacuation is not None:
            self.evacuation.validate_for_group_size(self.group_size)
        _require_int_at_least("minutes", self.minutes, 1)
        _require_int_at_least("tick_seconds", self.tick_seconds, 1)
        if (int(self.minutes) * 60) % int(self.tick_seconds) != 0:
            raise ValueError(
                "scenario horizon must be an integer number of fixed process ticks; "
                f"got {self.minutes * 60}s / {self.tick_seconds}s"
            )
        _require_int_at_least("group_size", self.group_size, 1)
        _require_int_at_least("sample_hours", self.sample_hours, 1)
        _require_int_at_least("entry_count_hour", self.entry_count_hour, 0)
        _require_int_at_least("exit_count_hour", self.exit_count_hour, 0)
        _require_int_at_least("transfer_count_hour", self.transfer_count_hour, 0)
        validate_demand_segments(
            self.demand_segments,
            horizon_seconds=self.horizon_duration_seconds,
        )
        validate_entrance_weights(self.entry_entrance_weights)
        if any(not str(facility_id).strip() for facility_id in self.disabled_facility_ids):
            raise ValueError("disabled_facility_ids must not contain blank ids")
        if len(set(self.disabled_facility_ids)) != len(self.disabled_facility_ids):
            raise ValueError("disabled_facility_ids must not contain duplicates")
        validate_facility_availability_events(
            self.facility_availability_events,
            horizon_seconds=self.horizon_duration_seconds,
            tick_seconds=self.tick_seconds,
            statically_disabled_ids=self.disabled_facility_ids,
        )
        validate_train_service_events(
            self.train_service_events,
            horizon_seconds=self.horizon_duration_seconds,
            tick_seconds=self.tick_seconds,
        )
        validate_train_capacity_events(
            self.train_capacity_events,
            horizon_seconds=self.horizon_duration_seconds,
            tick_seconds=self.tick_seconds,
        )
        if self.control_plan is not None:
            validate_control_plan_schedule(
                self.control_plan,
                horizon_seconds=self.horizon_duration_seconds,
                tick_seconds=self.tick_seconds,
            )
        if self.demand_minutes is not None:
            _require_int_at_least("demand_minutes", self.demand_minutes, 1)
            if int(self.demand_minutes) > int(self.minutes):
                raise ValueError(f"demand_minutes must be <= minutes; got {self.demand_minutes!r}")
        _require_int_at_least("train_headway_seconds", self.train_headway_seconds, 1)
        _require_int_at_least("train_dwell_seconds", self.train_dwell_seconds, 1)
        _require_int_at_least(
            "initial_train_offset_seconds",
            self.initial_train_offset_seconds,
            0,
        )
        _require_int_at_least("train_capacity_persons", self.train_capacity_persons, 1)
        _require_int_at_least("platform_capacity_persons", self.platform_capacity_persons, 1)
        _require_int_at_least("boarding_persons_per_min", self.boarding_persons_per_min, 0)
        _require_int_at_least("gate_service_persons_per_min", self.gate_service_persons_per_min, 0)
        for name in (
            "entry_admission_residence_seconds",
            "exit_admission_residence_seconds",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_positive(name, value)
        for name in (
            "entry_admission_residence_percentile",
            "exit_admission_residence_percentile",
        ):
            value = getattr(self, name)
            if value is not None and value not in {"p90", "p99"}:
                raise ValueError(f"{name} must be p90 or p99 when provided")
        if (
            not isfinite(float(self.entry_admission_burst_sigma))
            or self.entry_admission_burst_sigma < 0.0
        ):
            raise ValueError("entry_admission_burst_sigma must be finite and non-negative")
        for name in (
            "entry_admission_token_capacity",
            "exit_admission_token_capacity",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_int_at_least(name, value, 1)
        _require_positive("walk_units_per_tick", self.walk_units_per_tick)
        _require_positive("escalator_speed_m_s", self.escalator_speed_m_s)
        _require_positive(
            "stopped_escalator_walk_speed_m_s",
            self.stopped_escalator_walk_speed_m_s,
        )
        _require_positive("stairs_speed_m_s", self.stairs_speed_m_s)
        _require_positive("elevator_speed_m_s", self.elevator_speed_m_s)
        _require_positive("boarding_speed_multiplier", self.boarding_speed_multiplier)
        _require_positive("crowd_radius_units", self.crowd_radius_units)
        _require_positive("personal_space_units", self.personal_space_units)
        _require_positive("jupedsim_agent_radius_units", self.jupedsim_agent_radius_units)
        _require_positive("jupedsim_target_radius_units", self.jupedsim_target_radius_units)
        _require_positive("jupedsim_neighbor_radius_units", self.jupedsim_neighbor_radius_units)
        _require_positive("liveness_fail_fast_seconds", self.liveness_fail_fast_seconds)
        _require_positive(
            "liveness_min_displacement_units",
            self.liveness_min_displacement_units,
        )
        _require_non_negative(
            "alighting_source_lateral_offset_m",
            self.alighting_source_lateral_offset_m,
        )
        _require_positive("jupedsim_dt_seconds", self.jupedsim_dt_seconds)
        _require_positive("movement_trace_sample_seconds", self.movement_trace_sample_seconds)
        _require_positive(
            "cornering_acceleration_limit_m_s2",
            self.cornering_acceleration_limit_m_s2,
        )
        _require_positive(
            "cornering_acceleration_window_s",
            self.cornering_acceleration_window_s,
        )
        _require_positive("cornering_lookahead_m", self.cornering_lookahead_m)
        _require_positive("cornering_recovery_m", self.cornering_recovery_m)
        _require_positive("cornering_min_speed_mps", self.cornering_min_speed_mps)
        _require_positive(
            "cornering_unknown_transition_speed_mps",
            self.cornering_unknown_transition_speed_mps,
        )
        if not 0.0 < float(self.cornering_min_turn_degrees) <= 180.0:
            raise ValueError("cornering_min_turn_degrees must be in (0, 180]")
        trace_ratio = self.movement_trace_sample_seconds / self.jupedsim_dt_seconds
        if abs(trace_ratio - round(trace_ratio)) > 1e-9:
            raise ValueError(
                "movement_trace_sample_seconds must be an integer multiple of "
                "jupedsim_dt_seconds"
            )
        if self.movement_trace_sample_seconds > self.tick_seconds:
            raise ValueError("movement_trace_sample_seconds must not exceed tick_seconds")
        if self.jupedsim_operational_model not in {
            "collision_free_speed",
            "anticipation_velocity",
            "social_force",
        }:
            raise ValueError(
                "jupedsim_operational_model must be collision_free_speed, "
                "anticipation_velocity, or social_force"
            )
        _require_positive("jupedsim_desired_speed_mps", self.jupedsim_desired_speed_mps)
        _require_non_negative("jupedsim_free_speed_std_mps", self.jupedsim_free_speed_std_mps)
        _require_positive("jupedsim_free_speed_min_mps", self.jupedsim_free_speed_min_mps)
        _require_positive("jupedsim_free_speed_max_mps", self.jupedsim_free_speed_max_mps)
        if self.jupedsim_free_speed_min_mps > self.jupedsim_free_speed_max_mps:
            raise ValueError("jupedsim_free_speed_min_mps must not exceed max_mps")
        if not (
            self.jupedsim_free_speed_min_mps
            <= self.jupedsim_desired_speed_mps
            <= self.jupedsim_free_speed_max_mps
        ):
            raise ValueError("jupedsim_desired_speed_mps must lie within the free-speed bounds")
        _require_non_negative(
            "elevator_preference_mismatch_penalty_seconds",
            self.elevator_preference_mismatch_penalty_seconds,
        )
        _require_non_negative(
            "stairs_preference_mismatch_penalty_seconds",
            self.stairs_preference_mismatch_penalty_seconds,
        )
        _require_non_negative(
            "nonpreferred_elevator_penalty_seconds",
            self.nonpreferred_elevator_penalty_seconds,
        )
        if self.simulation_clock_mode not in {"legacy_scaled", "physical"}:
            raise ValueError(
                "simulation_clock_mode must be 'legacy_scaled' or 'physical'; "
                f"got {self.simulation_clock_mode!r}"
            )
        if self.goal_graph_mode != "active":
            raise ValueError(
                "legacy and shadow behavior runtimes have been removed; "
                "goal_graph_mode must be 'active'; "
                f"got {self.goal_graph_mode!r}"
            )
        if self.goal_graph_catalog_path is not None and not self.goal_graph_catalog_path.strip():
            raise ValueError("goal_graph_catalog_path cannot be blank")
        _require_int_at_least("jupedsim_iterations_per_tick", self.jupedsim_iterations_per_tick, 1)
        _require_int_at_least(
            "jupedsim_neighbor_sample_limit", self.jupedsim_neighbor_sample_limit, 0
        )
        _require_non_negative("gate_lane_edge_inset_max", self.gate_lane_edge_inset_max)
        _require_non_negative("facility_commitment_seconds", self.facility_commitment_seconds)
        _require_non_negative(
            "facility_replan_cooldown_seconds",
            self.facility_replan_cooldown_seconds,
        )
        _require_non_negative(
            "facility_replan_minimum_improvement_seconds",
            self.facility_replan_minimum_improvement_seconds,
        )
        _require_int_at_least("interaction_sample_limit", self.interaction_sample_limit, 0)
        _require_int_at_least("crowding_sample_size", self.crowding_sample_size, 1)
        _require_int_at_least("gate_queue_slots_per_row", self.gate_queue_slots_per_row, 1)
        _require_int_at_least("vertical_queue_slots_per_row", self.vertical_queue_slots_per_row, 1)
        _require_int_at_least("boarding_queue_slots_per_row", self.boarding_queue_slots_per_row, 1)
        _require_int_at_least(
            "platform_boarding_release_groups_per_door_tick",
            self.platform_boarding_release_groups_per_door_tick,
            1,
        )
        _require_int_at_least(
            "platform_waiting_slots_per_row", self.platform_waiting_slots_per_row, 1
        )
        _require_int_at_least("platform_waiting_row_cycle", self.platform_waiting_row_cycle, 1)
        _require_int_at_least(
            "elevator_cabin_capacity_persons", self.elevator_cabin_capacity_persons, 1
        )
        _require_int_at_least(
            "elevator_min_dispatch_persons", self.elevator_min_dispatch_persons, 1
        )
        _require_non_negative(
            "elevator_max_dispatch_wait_seconds",
            self.elevator_max_dispatch_wait_seconds,
        )
        _require_non_negative("elevator_boarding_seconds", self.elevator_boarding_seconds)
        _require_positive("elevator_cycle_seconds", self.elevator_cycle_seconds)
        _require_non_negative("elevator_unload_seconds", self.elevator_unload_seconds)

    @property
    def horizon_steps(self) -> int:
        return max(1, int(self.minutes * 60 / self.tick_seconds))

    @property
    def demand_duration_minutes(self) -> int:
        return int(self.minutes if self.demand_minutes is None else self.demand_minutes)

    @property
    def clearance_minutes(self) -> int:
        return max(0, int(self.minutes) - self.demand_duration_minutes)

    @property
    def demand_steps(self) -> int:
        if self.scenario_mode == EVACUATION_MODE:
            assert self.evacuation is not None
            return min(self.horizon_steps, self.evacuation.alarm_step(self.tick_seconds) + 1)
        if self.demand_segments:
            steps = first_step_not_before(
                max(item.end_seconds for item in self.demand_segments),
                self.tick_seconds,
            )
        else:
            steps = first_step_not_before(
                self.demand_duration_minutes * 60,
                self.tick_seconds,
            )
        return max(1, min(self.horizon_steps, steps))

    @property
    def horizon_duration_seconds(self) -> float:
        return float(self.minutes) * 60.0

    @property
    def demand_duration_seconds(self) -> float:
        return float(self.demand_duration_minutes) * 60.0

    @property
    def entry_groups(self) -> int:
        if self.demand_segments:
            return sum(
                item.groups(item.entry_count_hour, self.group_size)
                for item in self.demand_segments
            )
        return self._groups_for_hour_count(self.entry_count_hour)

    @property
    def exit_groups(self) -> int:
        if self.demand_segments:
            return sum(
                item.groups(item.exit_count_hour, self.group_size)
                for item in self.demand_segments
            )
        return self._groups_for_hour_count(self.exit_count_hour)

    @property
    def transfer_groups(self) -> int:
        if self.demand_segments:
            return sum(
                item.groups(item.transfer_count_hour, self.group_size)
                for item in self.demand_segments
            )
        return self._groups_for_hour_count(self.transfer_count_hour)

    def _groups_for_hour_count(self, count_hour: int) -> int:
        scenario_count = max(0, int(count_hour)) * (self.demand_duration_minutes / 60.0)
        return max(0, round(scenario_count / self.group_size))

    def with_minutes(self, minutes: int) -> StationSandboxScenario:
        demand_minutes = self.demand_minutes
        if demand_minutes is not None:
            demand_minutes = min(int(demand_minutes), int(minutes))
        return replace(self, minutes=minutes, demand_minutes=demand_minutes)

    def default_output_path(self) -> Path:
        safe_station = "".join(ch if ch.isalnum() else "_" for ch in self.station_name)
        return Path("output") / f"metro_station_sandbox_{safe_station}_{self.hour:02d}.html"


def _require_int_at_least(name: str, value: int, minimum: int) -> None:
    parsed = float(value)
    if not isfinite(parsed) or not parsed.is_integer():
        raise ValueError(f"{name} must be an integer; got {value!r}")
    if int(parsed) < minimum:
        raise ValueError(f"{name} must be >= {minimum}; got {value!r}")


def _require_positive(name: str, value: float) -> None:
    parsed = float(value)
    if not isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{name} must be > 0; got {value!r}")


def _require_non_negative(name: str, value: float) -> None:
    parsed = float(value)
    if not isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{name} must be >= 0; got {value!r}")
