"""Joint position-level projection for agent-agent and wall constraints."""

from __future__ import annotations

from dataclasses import dataclass

import torch

from .contracts import Bounds, KernelConfig, WallSegments


@dataclass(frozen=True)
class ContactDiagnostics:
    wall_contact_events: int
    agent_contact_events: int
    projected_steps: int


def solve_joint_contacts(
    proposed_position: torch.Tensor,
    previous_position: torch.Tensor,
    radius: torch.Tensor,
    active_mask: torch.Tensor,
    level_index: torch.Tensor,
    walls: WallSegments,
    config: KernelConfig,
    bounds: Bounds | None = None,
    collect_diagnostics: bool = True,
) -> tuple[torch.Tensor, ContactDiagnostics]:
    """Solve wall + agent constraints in one coupled iterative stage.

    The step is differentiable and uses smooth overlap surrogates. The result is
    not physically exact but is deterministic, low-cost, and avoids the P0
    sequential projection drift that caused measurable wall/agent overlap in M4.
    """
    if not config.enable_safety_projection:
        return _project_to_bounds(proposed_position, radius, bounds), ContactDiagnostics(0, 0, 0)
    position = _project_to_bounds(proposed_position, radius, bounds)
    radius_scalar = radius.squeeze(-1)
    wall_penetration_total = 0
    agent_penetration_total = 0
    for _ in range(max(1, int(config.contact_iterations))):
        wall_delta, wall_contacts = _wall_corrections(
            position,
            previous_position,
            radius_scalar,
            active_mask,
            walls,
            config,
            collect_diagnostics=collect_diagnostics,
        )
        agent_delta, agent_contacts = _agent_corrections(
            position,
            radius_scalar,
            active_mask,
            level_index,
            config,
            collect_diagnostics=collect_diagnostics,
        )
        if config.contact_projection_relaxation <= 0.0:
            break
        position = _project_to_bounds(
            position + config.contact_projection_relaxation * (wall_delta + agent_delta),
            radius,
            bounds,
        )
        wall_penetration_total += wall_contacts
        agent_penetration_total += agent_contacts
    return position, ContactDiagnostics(wall_penetration_total, agent_penetration_total, int(config.contact_iterations))


def _wall_corrections(
    position: torch.Tensor,
    _previous: torch.Tensor,
    radius: torch.Tensor,
    active_mask: torch.Tensor,
    walls: WallSegments,
    config: KernelConfig,
    *,
    collect_diagnostics: bool,
) -> tuple[torch.Tensor, int]:
    closest, distance, closest_normal = _closest_points_to_walls(position, walls)
    active = active_mask[:, :, None] & walls.active_mask[:, None, :]
    required = radius[:, :, None] + config.safety_clearance_m
    penetration = (required - distance).clamp(min=0.0)
    # Softplus keeps the projection differentiable at the hinge while preserving
    # zero overlap when no penetration is present.
    overlap = _smooth_penetration_overlap(penetration, config.contact_smoothing)
    masked_overlap = overlap * active
    wall_hits = int(active[masked_overlap > 0].sum().detach().cpu()) if collect_diagnostics else 0
    correction = closest_normal * masked_overlap[..., None]
    # Use nearest wall only to avoid over-pulling an agent towards multiple walls.
    nearest_distance = torch.where(masked_overlap > 0, distance, torch.full_like(distance, float("inf")))
    nearest_index = nearest_distance.argmin(dim=2)
    gather_index = nearest_index[:, :, None, None].expand(-1, -1, 1, 2)
    nearest_correction = torch.gather(correction, 2, gather_index).squeeze(2)
    return nearest_correction, wall_hits


def _agent_corrections(
    position: torch.Tensor,
    radius: torch.Tensor,
    active_mask: torch.Tensor,
    level_index: torch.Tensor,
    config: KernelConfig,
    *,
    collect_diagnostics: bool,
) -> tuple[torch.Tensor, int]:
    delta = position.unsqueeze(2) - position.unsqueeze(1)
    distance = torch.linalg.vector_norm(delta, dim=-1).clamp_min(1e-7)
    required = radius[:, :, None] + radius[:, None, :] + config.safety_clearance_m
    same_level = level_index.unsqueeze(2) == level_index.unsqueeze(1)
    pair_active = active_mask[:, :, None] & active_mask[:, None, :] & same_level
    eye = torch.eye(position.shape[1], device=position.device, dtype=torch.bool).unsqueeze(0)
    valid = pair_active & ~eye
    penetration = (required - distance).clamp(min=0.0)
    overlap = _smooth_penetration_overlap(penetration, config.contact_smoothing)
    direction = delta / distance.unsqueeze(-1)
    pair_correction = direction * (overlap * valid).unsqueeze(-1)
    # Move half-distance per contact to keep pair updates symmetric.
    correction = 0.5 * pair_correction.sum(dim=2)
    contacts = int(valid[overlap > 0].sum().detach().cpu()) if collect_diagnostics else 0
    return correction, contacts


def _smooth_penetration_overlap(penetration: torch.Tensor, contact_smoothing: float) -> torch.Tensor:
    """Return differentiable overlap magnitude, zero when penetration is non-positive."""
    smoothing = max(float(contact_smoothing), 1e-6)
    # Keep the softplus in distance units.  Omitting the scale factor turns a
    # centimetre-level penetration into an order-one displacement, which can
    # push dense batches into the outer bounds and create artificial lock-up.
    smooth_overlap = torch.nn.functional.softplus(penetration / smoothing) * smoothing
    return torch.where(penetration > 0, smooth_overlap, torch.zeros_like(penetration))


def _closest_points_to_walls(position: torch.Tensor, walls: WallSegments) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    start = walls.segments[:, :, 0, :]
    end = walls.segments[:, :, 1, :]
    segment = end - start
    relative = position[:, :, None, :] - start[:, None, :, :]
    length_squared = (segment[:, None, :, :] * segment[:, None, :, :]).sum(dim=-1).clamp_min(1e-10)
    fraction = (relative * segment[:, None, :, :]).sum(dim=-1) / length_squared
    fraction = fraction.clamp(0.0, 1.0)
    closest = start[:, None, :, :] + fraction[:, :, :, None] * segment[:, None, :, :]
    diff = position[:, :, None, :] - closest
    distance = torch.linalg.vector_norm(diff, dim=-1)
    normal = torch.where(distance[:, :, :, None] > 1e-12, diff / distance[:, :, :, None], torch.zeros_like(diff))
    return closest, distance, normal


def _project_to_bounds(position: torch.Tensor, radius: torch.Tensor, bounds: Bounds | None) -> torch.Tensor:
    if bounds is None:
        return position
    lower = torch.as_tensor(bounds.lower, device=position.device, dtype=position.dtype).view(1, 1, 2)
    upper = torch.as_tensor(bounds.upper, device=position.device, dtype=position.dtype).view(1, 1, 2)
    radius_tensor = radius[:, :, None] if radius.ndim == 2 else radius
    return torch.maximum(torch.minimum(position, upper - radius_tensor), lower + radius_tensor)
