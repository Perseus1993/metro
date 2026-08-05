from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .catalog import Catalog


class JobSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_version: Literal["0.1"]
    station: str = "小寨"
    hour: int = Field(default=18, ge=0, le=23)
    design_template: str = "visual_demo_station"
    scenario_mode: Literal["operations", "evacuation"] = "operations"
    horizon_minutes: int = Field(default=15, ge=1, le=60)
    demand_minutes: int = Field(default=10, ge=1, le=60)
    tick_seconds: Literal[1] = 1
    entry_count_hour: int = Field(ge=0, le=6000)
    exit_count_hour: int = Field(ge=0, le=6000)
    transfer_count_hour: int = Field(ge=0, le=6000)
    group_size: int = Field(default=1, ge=1, le=10)
    admins: int = Field(default=0, ge=0, le=50)
    initial_platform_persons: int = Field(default=0, ge=0, le=500)
    alarm_delay_seconds: float = Field(default=0, ge=0, le=600)
    movement_backend: Literal["jupedsim", "batched_jupedsim", "micro_jupedsim"] = (
        "jupedsim"
    )
    jupedsim_model: Literal[
        "collision_free_speed", "anticipation_velocity", "social_force"
    ] = "collision_free_speed"
    clock_mode: Literal["physical", "legacy_scaled"] = "physical"
    routing_algorithm: Literal["builtin_shortest_path", "internal_graph"] = (
        "builtin_shortest_path"
    )
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    trajectory_sample_seconds: int = Field(default=1, ge=1, le=60)
    label: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_mode(self) -> JobSpec:
        if self.demand_minutes > self.horizon_minutes:
            raise ValueError("demand_minutes must not exceed horizon_minutes")
        flows = self.entry_count_hour + self.exit_count_hour + self.transfer_count_hour
        if self.scenario_mode == "operations":
            if flows == 0:
                raise ValueError("operations mode requires non-zero passenger demand")
            if self.initial_platform_persons != 0:
                raise ValueError("initial_platform_persons is only valid in evacuation mode")
            if self.alarm_delay_seconds != 0:
                raise ValueError("alarm_delay_seconds is only valid in evacuation mode")
            return self
        if flows != 0:
            raise ValueError("evacuation mode requires all hourly flow fields to be zero")
        if self.initial_platform_persons == 0:
            raise ValueError("evacuation mode requires initial_platform_persons > 0")
        if self.initial_platform_persons % self.group_size:
            raise ValueError("initial_platform_persons must be divisible by group_size")
        return self

    def estimated_passenger_agents(self) -> int:
        if self.scenario_mode == "evacuation":
            return self.initial_platform_persons // self.group_size
        return sum(
            round(flow * self.demand_minutes / 60 / self.group_size)
            for flow in (
                self.entry_count_hour,
                self.exit_count_hour,
                self.transfer_count_hour,
            )
        )

    def estimated_total_agents(self) -> int:
        return self.estimated_passenger_agents() + self.admins


def resolve_spec(payload: dict[str, Any], catalog: Catalog, max_agents: int) -> dict[str, Any]:
    spec = JobSpec.model_validate(payload)
    if spec.station not in catalog.stations:
        raise ValueError(f"unknown station: {spec.station}")
    if spec.design_template not in catalog.design_templates:
        raise ValueError(f"unknown design_template: {spec.design_template}")
    if spec.estimated_passenger_agents() == 0:
        raise ValueError("passenger demand rounds to zero agents")
    if spec.estimated_total_agents() > max_agents:
        raise ValueError(
            f"estimated agent count {spec.estimated_total_agents()} exceeds limit {max_agents}"
        )
    resolved = spec.model_dump(mode="json")
    resolved["_derived"] = {
        "horizon_seconds": spec.horizon_minutes * 60,
        "clearance_minutes": spec.horizon_minutes - spec.demand_minutes,
        "estimated_passenger_agents": spec.estimated_passenger_agents(),
        "estimated_total_agents": spec.estimated_total_agents(),
        "catalog_version": catalog.version,
    }
    return resolved


def runner_spec(resolved: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in resolved.items() if key != "_derived"}
    result["_estimated_passenger_agents"] = resolved["_derived"][
        "estimated_passenger_agents"
    ]
    return result
