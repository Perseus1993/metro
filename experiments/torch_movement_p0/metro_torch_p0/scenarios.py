"""Deterministic P0 micro-scenarios, independent of the Metro runtime."""

from __future__ import annotations

from dataclasses import dataclass, replace

import torch

from .contracts import Bounds, KernelConfig, PopulationState
from .geometry import append_segments, rectangular_walls
from .kernel import advance
from .state import SlotPopulation


@dataclass(frozen=True)
class ScenarioOutcome:
    name: str
    passed: bool
    metrics: dict[str, float | int | bool]


def run_validation_scenarios(device: torch.device | str) -> list[ScenarioOutcome]:
    """Run the P0's M1--M7 evidence set with a fixed seed."""
    torch.manual_seed(7)
    return [
        _single_walker(device),
        _head_on(device),
        _bidirectional_corridor(device),
        _bottleneck(device),
        _slot_reuse(device),
        _level_isolation(device),
        _dynamic_obstacle(device),
    ]


def _single_walker(device: torch.device | str) -> ScenarioOutcome:
    config, bounds, walls = _world(device)
    population = SlotPopulation(batch_size=1, capacity=1, device=device)
    population.spawn(1, position=(2.0, 5.0), target=(12.0, 5.0))
    state, diagnostics = _roll(population.state, walls, config, bounds, steps=220)
    endpoint_error = float(torch.linalg.vector_norm(state.target - state.position).item())
    return _outcome(
        "M1_single_walker",
        endpoint_error < config.target_radius and diagnostics["max_speed_mps"] <= config.max_speed_mps + 1e-5,
        endpoint_error_m=endpoint_error,
        **diagnostics,
    )


def _head_on(device: torch.device | str) -> ScenarioOutcome:
    config, bounds, walls = _world(device)
    population = SlotPopulation(batch_size=1, capacity=2, device=device)
    population.spawn(1, position=(3.0, 4.75), target=(13.0, 5.25))
    population.spawn(2, position=(13.0, 5.25), target=(3.0, 4.75))
    state, diagnostics = _roll(population.state, walls, config, bounds, steps=240)
    destination_error = float(torch.linalg.vector_norm(state.target - state.position, dim=-1).max().item())
    return _outcome(
        "M2_head_on",
        diagnostics["minimum_agent_gap_m"] >= -1e-4 and destination_error < 1.5,
        destination_error_m=destination_error,
        **diagnostics,
    )


def _bidirectional_corridor(device: torch.device | str) -> ScenarioOutcome:
    config, bounds, walls = _world(device)
    population = SlotPopulation(batch_size=1, capacity=32, device=device)
    for index in range(16):
        y = 1.0 + index * 0.5
        population.spawn(index, position=(2.0 + 0.08 * (index % 2), y), target=(13.0, y + 0.1))
        population.spawn(100 + index, position=(13.0 - 0.08 * (index % 2), y + 0.18), target=(2.0, y))
    state, diagnostics = _roll(population.state, walls, config, bounds, steps=200)
    progressed = float((state.position[:, :, 0] - population.state.position[:, :, 0]).abs().mean().item())
    return _outcome(
        "M3_bidirectional_corridor",
        diagnostics["minimum_agent_gap_m"] >= -1e-4 and progressed > 1.5,
        mean_abs_progress_m=progressed,
        **diagnostics,
    )


def _bottleneck(device: torch.device | str) -> ScenarioOutcome:
    config, bounds, walls = _world(device)
    walls = append_segments(
        walls,
        torch.tensor([[[7.5, 0.0], [7.5, 4.25]], [[7.5, 5.75], [7.5, 10.0]]], device=device),
    )
    population = SlotPopulation(batch_size=1, capacity=50, device=device)
    for index in range(50):
        row, column = divmod(index, 10)
        population.spawn(index, position=(1.0 + row * 0.42, 2.2 + column * 0.55), target=(13.5, 5.0))
    state, diagnostics = _roll(population.state, walls, config, bounds, steps=320)
    exited = int((state.position[0, :, 0] > 7.8).sum().item())
    return _outcome(
        "M4_bottleneck",
        diagnostics["minimum_agent_gap_m"] >= -0.01 and diagnostics["minimum_wall_clearance_m"] >= -1e-4 and exited >= 1,
        agents_past_bottleneck=exited,
        **diagnostics,
    )


def _slot_reuse(device: torch.device | str) -> ScenarioOutcome:
    population = SlotPopulation(batch_size=1, capacity=2, device=device)
    first_slot = population.spawn(11, position=(1.0, 1.0), target=(2.0, 1.0))
    population.replace_state(replace(population.state, velocity=torch.ones_like(population.state.velocity)))
    population.remove(11)
    reused_slot = population.spawn(12, position=(3.0, 3.0), target=(4.0, 3.0))
    state = population.state
    reset = bool(torch.allclose(state.velocity[0, reused_slot], torch.zeros(2, device=device)))
    return _outcome(
        "M5_slot_reuse",
        first_slot == reused_slot and reset and population.active_ids() == {12},
        slot_reused=first_slot == reused_slot,
        velocity_reset=reset,
        active_ids_match=population.active_ids() == {12},
    )


def _level_isolation(device: torch.device | str) -> ScenarioOutcome:
    config, bounds, walls = _world(device)
    one = SlotPopulation(batch_size=1, capacity=2, device=device)
    one.spawn(1, position=(5.0, 5.0), target=(11.0, 5.0), level_index=0)
    two = SlotPopulation(batch_size=1, capacity=2, device=device)
    two.spawn(1, position=(5.0, 5.0), target=(11.0, 5.0), level_index=0)
    two.spawn(2, position=(5.25, 5.0), target=(1.0, 5.0), level_index=1)
    first = advance(one.state, walls, config, bounds=bounds).state.position[0, 0]
    second = advance(two.state, walls, config, bounds=bounds).state.position[0, 0]
    delta = float(torch.linalg.vector_norm(first - second).item())
    return _outcome("M6_level_isolation", delta < 1e-6, first_agent_delta_m=delta)


def _dynamic_obstacle(device: torch.device | str) -> ScenarioOutcome:
    config, bounds, walls = _world(device)
    population = SlotPopulation(batch_size=1, capacity=1, device=device)
    population.spawn(1, position=(3.0, 5.0), target=(13.0, 5.0))
    state, _ = _roll(population.state, walls, config, bounds, steps=30)
    changed_walls = append_segments(walls, torch.tensor([[[8.0, 0.0], [8.0, 10.0]]], device=device))
    state, diagnostics = _roll(state, changed_walls, config, bounds, steps=220)
    final_x = float(state.position[0, 0, 0].item())
    return _outcome(
        "M7_dynamic_obstacle",
        final_x <= 7.82 and diagnostics["minimum_wall_clearance_m"] >= -1e-4,
        final_x_m=final_x,
        **diagnostics,
    )


def _world(device: torch.device | str):
    config = KernelConfig()
    bounds = Bounds(lower=(0.0, 0.0), upper=(15.0, 10.0))
    walls = rectangular_walls(width=15.0, height=10.0, batch_size=1, device=device, dtype=torch.float32)
    return config, bounds, walls


def _roll(state: PopulationState, walls, config: KernelConfig, bounds: Bounds, *, steps: int):
    minimum_gap = float("inf")
    minimum_clearance = float("inf")
    maximum_speed = 0.0
    contacts = 0
    for _ in range(steps):
        result = advance(state, walls, config, bounds=bounds)
        state = result.state
        minimum_gap = min(minimum_gap, result.diagnostics.minimum_agent_gap_m)
        minimum_clearance = min(minimum_clearance, result.diagnostics.minimum_wall_clearance_m)
        maximum_speed = max(maximum_speed, result.diagnostics.max_speed_mps)
        contacts += result.diagnostics.projection_contacts
    return state, {
        "minimum_agent_gap_m": minimum_gap,
        "minimum_wall_clearance_m": minimum_clearance,
        "max_speed_mps": maximum_speed,
        "projection_contacts": contacts,
    }


def _outcome(name: str, passed: bool, **metrics: float | int | bool) -> ScenarioOutcome:
    return ScenarioOutcome(name=name, passed=passed, metrics=metrics)
