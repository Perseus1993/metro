"""PM-033 P1 tensor kernel with joint contact projection."""

from __future__ import annotations

from dataclasses import dataclass, replace

import torch
from torch.nn import functional as functional

from .contact import solve_joint_contacts
from .contracts import Bounds, KernelConfig, KernelParameters, PopulationState, StepStatistics, WallSegments


@dataclass(frozen=True)
class StepResult:
    state: PopulationState
    diagnostics: StepStatistics


def advance(
    state: PopulationState,
    walls: WallSegments,
    config: KernelConfig,
    *,
    parameters: KernelParameters = KernelParameters(),
    bounds: Bounds | None = None,
    collect_diagnostics: bool = True,
) -> StepResult:
    """Advance all active slots by one physical step."""
    if state.batch_size != walls.batch_size:
        raise ValueError("population and wall batch sizes must match")

    desired_direction, target_distance = _direction_and_distance(state.target - state.position)
    desired_speed = state.desired_speed * _parameter_tensor(parameters.desired_speed_scale, state).unsqueeze(-1)
    desired_velocity = desired_direction * desired_speed
    agent_force, _ = _agent_repulsion(state, config, parameters)
    wall_force, _ = _wall_repulsion(state, walls, config, parameters)
    relaxation = _parameter_tensor(parameters.relaxation_time_seconds, state).clamp_min(0.05)
    acceleration = (desired_velocity - state.velocity) / relaxation + agent_force + wall_force
    acceleration = _clamp_norm(acceleration, config.max_acceleration_mps2)
    velocity = _clamp_norm(state.velocity + acceleration * config.dt_seconds, config.max_speed_mps)
    active_vector = state.active_mask.unsqueeze(-1)
    velocity = torch.where(active_vector, velocity, torch.zeros_like(velocity))
    proposed_position = state.position + velocity * config.dt_seconds

    projected_position, contact_diag = solve_joint_contacts(
        proposed_position,
        state.position,
        state.radius,
        state.active_mask,
        state.level_index,
        walls,
        config,
        bounds=bounds,
        collect_diagnostics=collect_diagnostics,
    )

    if collect_diagnostics:
        minimum_gap = _minimum_agent_gap(projected_position, state.radius, state.active_mask, state.level_index)
        minimum_wall_clearance = _minimum_wall_clearance(projected_position, state.radius, state.active_mask, walls)
        max_speed = float(torch.linalg.vector_norm(velocity, dim=-1).max().detach().cpu())
    else:
        minimum_gap = None
        minimum_wall_clearance = None
        max_speed = None

    reached = state.active_mask & (target_distance <= config.target_radius)
    next_state = replace(
        state,
        position=projected_position,
        velocity=velocity,
    )
    return StepResult(
        state=next_state,
        diagnostics=StepStatistics(
            reached_mask=reached,
            max_speed_mps=max_speed,
            minimum_agent_gap_m=minimum_gap,
            minimum_wall_clearance_m=minimum_wall_clearance,
            wall_contacts=contact_diag.wall_contact_events,
            agent_contacts=contact_diag.agent_contact_events,
            projected_steps=contact_diag.projected_steps,
        ),
    )


def _agent_repulsion(
    state: PopulationState, config: KernelConfig, parameters: KernelParameters
) -> tuple[torch.Tensor, float]:
    delta = state.position.unsqueeze(2) - state.position.unsqueeze(1)
    direction, distance = _direction_and_distance(delta)
    radii = state.radius + state.radius.transpose(1, 2)
    same_level = state.level_index.unsqueeze(2) == state.level_index.unsqueeze(1)
    active_pair = state.active_mask.unsqueeze(2) & state.active_mask.unsqueeze(1) & same_level
    eye = torch.eye(state.capacity, device=state.device, dtype=torch.bool).unsqueeze(0)
    valid_pair = active_pair & ~eye
    interaction_range = torch.maximum(
        _parameter_tensor(parameters.agent_repulsion_range_m, state),
        torch.tensor(config.agent_repulsion_range_m, device=state.device, dtype=state.dtype),
    )
    gap = distance - radii.squeeze(-1)
    # Softplus avoids hard-contact kink and improves finite-difference stability.
    activation = functional.softplus((interaction_range - gap) / config.contact_smoothing)
    strength = _parameter_tensor(parameters.agent_repulsion_strength, state)
    force = direction * (strength * activation * valid_pair).unsqueeze(-1)
    minimum_gap = _masked_minimum(gap, valid_pair)
    return force.sum(dim=2), minimum_gap


def _wall_repulsion(
    state: PopulationState,
    walls: WallSegments,
    config: KernelConfig,
    parameters: KernelParameters,
) -> tuple[torch.Tensor, float]:
    closest, distance = _closest_points_to_walls(state.position, walls)
    direction, _ = _direction_and_distance(state.position.unsqueeze(2) - closest)
    clearance = distance - state.radius.squeeze(-1).unsqueeze(-1)
    interaction_range = torch.maximum(
        _parameter_tensor(parameters.agent_repulsion_range_m, state),
        torch.tensor(config.wall_repulsion_range_m, device=state.device, dtype=state.dtype),
    )
    activation = functional.softplus((interaction_range - clearance) / config.contact_smoothing)
    valid = state.active_mask.unsqueeze(-1) & walls.active_mask.unsqueeze(1)
    strength = _parameter_tensor(parameters.wall_repulsion_strength, state)
    force = direction * (strength * activation * valid).unsqueeze(-1)
    minimum_clearance = _masked_minimum(clearance, valid)
    return force.sum(dim=2), minimum_clearance


def _closest_points_to_walls(position: torch.Tensor, walls: WallSegments) -> tuple[torch.Tensor, torch.Tensor]:
    start = walls.segments[:, None, :, 0, :]
    end = walls.segments[:, None, :, 1, :]
    segment = end - start
    relative = position.unsqueeze(2) - start
    length_squared = (segment * segment).sum(dim=-1).clamp_min(1e-10)
    fraction = ((relative * segment).sum(dim=-1) / length_squared).clamp(0.0, 1.0)
    closest = start + fraction[:, :, :, None] * segment
    _, distance = _direction_and_distance(position.unsqueeze(2) - closest)
    return closest, distance


def _minimum_agent_gap(
    position: torch.Tensor, radius: torch.Tensor, active_mask: torch.Tensor, level_index: torch.Tensor
) -> float:
    delta = position.unsqueeze(2) - position.unsqueeze(1)
    _, distance = _direction_and_distance(delta)
    gap = distance - (radius + radius.transpose(1, 2)).squeeze(-1)
    same_level = level_index.unsqueeze(2) == level_index.unsqueeze(1)
    active_pair = active_mask.unsqueeze(2) & active_mask.unsqueeze(1) & same_level
    eye = torch.eye(position.shape[1], device=position.device, dtype=torch.bool).unsqueeze(0)
    return _masked_minimum(gap, active_pair & ~eye)


def _minimum_wall_clearance(
    position: torch.Tensor, radius: torch.Tensor, active_mask: torch.Tensor, walls: WallSegments
) -> float:
    _, distance = _closest_points_to_walls(position, walls)
    clearance = distance - radius.squeeze(-1).unsqueeze(-1)
    valid = active_mask.unsqueeze(-1) & walls.active_mask.unsqueeze(1)
    return _masked_minimum(clearance, valid)


def _direction_and_distance(vector: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    distance = torch.sqrt((vector * vector).sum(dim=-1).clamp_min(1e-12))
    return vector / distance.unsqueeze(-1), distance


def _clamp_norm(vector: torch.Tensor, maximum: float) -> torch.Tensor:
    norm = torch.linalg.vector_norm(vector, dim=-1, keepdim=True).clamp_min(1e-12)
    return vector * torch.clamp(torch.as_tensor(maximum, device=vector.device, dtype=vector.dtype) / norm, max=1.0)


def _parameter_tensor(value: float | torch.Tensor, state: PopulationState) -> torch.Tensor:
    if isinstance(value, torch.Tensor):
        return value.to(device=state.device, dtype=state.dtype)
    return torch.tensor(value, device=state.device, dtype=state.dtype)


def _masked_minimum(values: torch.Tensor, mask: torch.Tensor) -> float:
    if not bool(mask.any()):
        return float("inf")
    return float(torch.where(mask, values, torch.full_like(values, float("inf"))).amin().detach().cpu())
