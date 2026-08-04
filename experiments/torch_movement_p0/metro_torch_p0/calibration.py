"""Autograd and synthetic-recovery evidence for the P0 movement kernel."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch.nn import functional as functional

from .contracts import Bounds, KernelConfig, KernelParameters, PopulationState
from .geometry import rectangular_walls
from .kernel import advance
from .state import SlotPopulation


@dataclass(frozen=True)
class CalibrationEvidence:
    autograd_gradient: float
    finite_difference_gradient: float
    relative_gradient_error: float
    true_relaxation_time_s: float
    recovered_relaxation_time_s: float
    initial_loss: float
    final_loss: float
    passed: bool


def run_calibration_evidence(device: torch.device | str) -> CalibrationEvidence:
    """Check an analytic gradient and recover one known movement parameter."""
    state, walls, config, bounds = _calibration_world(device)
    reference = _roll_positions(state, walls, config, bounds, relaxation_time=0.38).detach()
    parameter = torch.tensor(0.60, device=device, requires_grad=True)
    analytic_loss = _trajectory_loss(state, walls, config, bounds, reference, parameter)
    analytic_gradient = float(torch.autograd.grad(analytic_loss, parameter)[0].item())
    finite_difference = _finite_difference(state, walls, config, bounds, reference, 0.60)
    relative_error = abs(analytic_gradient - finite_difference) / max(abs(finite_difference), 1e-6)
    raw = torch.tensor(0.2, device=device, requires_grad=True)
    optimizer = torch.optim.Adam([raw], lr=0.08)
    initial_loss = 0.0
    final_loss = 0.0
    for step in range(160):
        relaxation = 0.10 + functional.softplus(raw)
        loss = _trajectory_loss(state, walls, config, bounds, reference, relaxation)
        if step == 0:
            initial_loss = float(loss.detach().item())
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        final_loss = float(loss.detach().item())
    recovered = float((0.10 + functional.softplus(raw)).detach().item())
    passed = relative_error < 0.03 and abs(recovered - 0.38) < 0.04 and final_loss < initial_loss * 0.03
    return CalibrationEvidence(
        autograd_gradient=analytic_gradient,
        finite_difference_gradient=finite_difference,
        relative_gradient_error=relative_error,
        true_relaxation_time_s=0.38,
        recovered_relaxation_time_s=recovered,
        initial_loss=initial_loss,
        final_loss=final_loss,
        passed=passed,
    )


def _calibration_world(device: torch.device | str):
    population = SlotPopulation(batch_size=1, capacity=1, device=device)
    population.spawn(1, position=(1.0, 5.0), target=(8.0, 5.0), desired_speed=1.1)
    walls = rectangular_walls(width=12.0, height=10.0, batch_size=1, device=device, dtype=torch.float32)
    return (
        population.state,
        walls,
        KernelConfig(max_speed_mps=4.0, max_acceleration_mps2=30.0, enable_safety_projection=False),
        Bounds(lower=(0.0, 0.0), upper=(12.0, 10.0)),
    )


def _trajectory_loss(
    state: PopulationState,
    walls,
    config: KernelConfig,
    bounds: Bounds,
    reference: torch.Tensor,
    relaxation: torch.Tensor,
) -> torch.Tensor:
    predicted = _roll_positions(state, walls, config, bounds, relaxation_time=relaxation)
    return torch.mean((predicted - reference) ** 2)


def _roll_positions(
    state: PopulationState,
    walls,
    config: KernelConfig,
    bounds: Bounds,
    *,
    relaxation_time: float | torch.Tensor,
) -> torch.Tensor:
    parameters = KernelParameters(relaxation_time_seconds=relaxation_time)
    positions = []
    for _ in range(48):
        state = advance(
            state, walls, config, parameters=parameters, bounds=bounds, collect_diagnostics=False
        ).state
        positions.append(state.position)
    return torch.stack(positions)


def _finite_difference(
    state, walls, config, bounds, reference: torch.Tensor, centre: float, step: float = 1e-3
) -> float:
    upper = _trajectory_loss(state, walls, config, bounds, reference, torch.tensor(centre + step, device=reference.device))
    lower = _trajectory_loss(state, walls, config, bounds, reference, torch.tensor(centre - step, device=reference.device))
    return float(((upper - lower) / (2.0 * step)).item())
