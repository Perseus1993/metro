"""Pure tensor movement kernel used by the isolated P0 experiment."""

from __future__ import annotations

from dataclasses import dataclass, replace

import torch
from torch.nn import functional as functional

from .contracts import Bounds, KernelConfig, KernelParameters, PopulationState, WallSegments


@dataclass(frozen=True)
class StepDiagnostics:
    """Constraint measurements retained outside the autograd state."""

    reached_mask: torch.Tensor
    max_speed_mps: float | None
    minimum_agent_gap_m: float | None
    minimum_wall_clearance_m: float | None
    projection_contacts: int | None


@dataclass(frozen=True)
class StepResult:
    state: PopulationState
    diagnostics: StepDiagnostics


def advance(
    state: PopulationState,
    walls: WallSegments,
    config: KernelConfig,
    *,
    parameters: KernelParameters = KernelParameters(),
    bounds: Bounds | None = None,
    collect_diagnostics: bool = True,
) -> StepResult:
    """Advance all active slots by one physical step without domain-agent access."""
    if state.batch_size != walls.batch_size:
        raise ValueError("population and wall batch sizes must match")
    desired_direction, target_distance = _direction_and_distance(state.target - state.position)
    desired_velocity = desired_direction * state.desired_speed
    agent_force, _ = _agent_repulsion(state, config, parameters)
    wall_force, _ = _wall_repulsion(state, walls, config, parameters)
    relaxation = _parameter_tensor(parameters.relaxation_time_seconds, state).clamp_min(0.05)
    acceleration = (desired_velocity - state.velocity) / relaxation + agent_force + wall_force
    acceleration = _clamp_norm(acceleration, config.max_acceleration_mps2)
    velocity = _clamp_norm(state.velocity + acceleration * config.dt_seconds, config.max_speed_mps)
    active_vector = state.active_mask.unsqueeze(-1)
    velocity = torch.where(active_vector, velocity, torch.zeros_like(velocity))
    position = state.position + velocity * config.dt_seconds
    position, wall_contacts = _apply_safety_projection(
        position, state.position, state.radius, state.active_mask, walls, config, bounds, count_contacts=collect_diagnostics
    )
    position, agent_contacts = _apply_agent_safety_projection(
        position, state.radius, state.active_mask, state.level_index, config, bounds, count_contacts=collect_diagnostics
    )
    position, final_wall_contacts = _apply_safety_projection(
        position, state.position, state.radius, state.active_mask, walls, config, bounds, count_contacts=collect_diagnostics
    )
    minimum_gap = None
    minimum_wall_clearance = None
    maximum_speed = None
    projection_contacts = None
    if collect_diagnostics:
        minimum_gap = _minimum_agent_gap(position, state.radius, state.active_mask, state.level_index)
        minimum_wall_clearance = _minimum_wall_clearance(position, state.radius, state.active_mask, walls)
        maximum_speed = float(torch.linalg.vector_norm(velocity, dim=-1).max().detach().cpu())
        projection_contacts = wall_contacts + agent_contacts + final_wall_contacts
    reached = state.active_mask & (target_distance <= config.target_radius)
    next_state = replace(state, position=position, velocity=velocity)
    return StepResult(
        state=next_state,
        diagnostics=StepDiagnostics(
            reached_mask=reached,
            max_speed_mps=maximum_speed,
            minimum_agent_gap_m=minimum_gap,
            minimum_wall_clearance_m=minimum_wall_clearance,
            projection_contacts=projection_contacts,
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
    gap = distance - radii.squeeze(-1)
    interaction_range = max(config.agent_repulsion_range_m, 1e-4)
    activation = functional.softplus((interaction_range - gap) / interaction_range)
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
    interaction_range = max(config.wall_repulsion_range_m, 1e-4)
    activation = functional.softplus((interaction_range - clearance) / interaction_range)
    valid = state.active_mask.unsqueeze(-1) & walls.active_mask.unsqueeze(1)
    strength = _parameter_tensor(parameters.wall_repulsion_strength, state)
    force = direction * (strength * activation * valid).unsqueeze(-1)
    minimum_clearance = _masked_minimum(clearance, valid)
    return force.sum(dim=2), minimum_clearance


def _apply_safety_projection(
    proposed: torch.Tensor,
    previous: torch.Tensor,
    radius: torch.Tensor,
    active_mask: torch.Tensor,
    walls: WallSegments,
    config: KernelConfig,
    bounds: Bounds | None,
    *,
    count_contacts: bool,
) -> tuple[torch.Tensor, int]:
    position = _project_to_bounds(proposed, radius, bounds)
    if not config.enable_safety_projection:
        return position, 0
    contacts = 0
    for _ in range(2):
        closest, distance = _closest_points_to_walls(position, walls)
        previous_closest, _ = _closest_points_to_walls(previous, walls)
        normal, _ = _direction_and_distance(previous.unsqueeze(2) - previous_closest)
        fallback, _ = _direction_and_distance(position.unsqueeze(2) - closest)
        normal = torch.where(torch.linalg.vector_norm(normal, dim=-1, keepdim=True) > 0.1, normal, fallback)
        valid = active_mask.unsqueeze(-1) & walls.active_mask.unsqueeze(1)
        candidate_distance = torch.where(valid, distance, torch.full_like(distance, float("inf")))
        nearest_index = candidate_distance.argmin(dim=2, keepdim=True)
        nearest_distance = torch.gather(candidate_distance, 2, nearest_index).squeeze(2)
        vector_index = nearest_index.unsqueeze(-1).expand(-1, -1, 1, 2)
        nearest_point = torch.gather(closest, 2, vector_index).squeeze(2)
        nearest_normal = torch.gather(normal, 2, vector_index).squeeze(2)
        required_distance = radius.squeeze(-1) + config.safety_clearance_m
        contact = nearest_distance < required_distance
        correction = nearest_point + nearest_normal * required_distance.unsqueeze(-1)
        position = torch.where(contact.unsqueeze(-1), correction, position)
        if count_contacts:
            contacts += int(contact.sum().detach().cpu())
    return _project_to_bounds(position, radius, bounds), contacts


def _apply_agent_safety_projection(
    position: torch.Tensor,
    radius: torch.Tensor,
    active_mask: torch.Tensor,
    level_index: torch.Tensor,
    config: KernelConfig,
    bounds: Bounds | None,
    *,
    count_contacts: bool,
) -> tuple[torch.Tensor, int]:
    if not config.enable_safety_projection:
        return position, 0
    contacts = 0
    for _ in range(2):
        delta = position.unsqueeze(2) - position.unsqueeze(1)
        direction, distance = _direction_and_distance(delta)
        required = radius + radius.transpose(1, 2) + config.safety_clearance_m
        same_level = level_index.unsqueeze(2) == level_index.unsqueeze(1)
        active_pair = active_mask.unsqueeze(2) & active_mask.unsqueeze(1) & same_level
        eye = torch.eye(position.shape[1], device=position.device, dtype=torch.bool).unsqueeze(0)
        contact = active_pair & ~eye & (distance < required.squeeze(-1))
        correction = direction * (required.squeeze(-1) - distance).clamp_min(0.0).unsqueeze(-1)
        position = position + 0.5 * (correction * contact.unsqueeze(-1)).sum(dim=2)
        position = _project_to_bounds(position, radius, bounds)
        if count_contacts:
            contacts += int(contact.sum().detach().cpu())
    return position, contacts


def _project_to_bounds(position: torch.Tensor, radius: torch.Tensor, bounds: Bounds | None) -> torch.Tensor:
    if bounds is None:
        return position
    lower = torch.tensor(bounds.lower, device=position.device, dtype=position.dtype).view(1, 1, 2)
    upper = torch.tensor(bounds.upper, device=position.device, dtype=position.dtype).view(1, 1, 2)
    return torch.maximum(torch.minimum(position, upper - radius), lower + radius)


def _closest_points_to_walls(position: torch.Tensor, walls: WallSegments) -> tuple[torch.Tensor, torch.Tensor]:
    start = walls.segments[:, None, :, 0, :]
    end = walls.segments[:, None, :, 1, :]
    segment = end - start
    relative = position.unsqueeze(2) - start
    length_squared = (segment * segment).sum(dim=-1).clamp_min(1e-8)
    fraction = ((relative * segment).sum(dim=-1) / length_squared).clamp(0.0, 1.0)
    closest = start + fraction.unsqueeze(-1) * segment
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
