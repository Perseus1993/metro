"""Deterministic micro-scenarios for PM-033 blockers and regression checks."""

from __future__ import annotations

from dataclasses import dataclass, replace

import torch

from .contracts import Bounds, KernelConfig, PopulationState
from .geometry import append_segments, build_demo_station_polygon, build_polygon_walls, filter_points_in_polygon, rectangular_walls
from .kernel import advance
from .state import SlotPopulation


@dataclass(frozen=True)
class ScenarioOutcome:
    name: str
    passed: bool
    metrics: dict[str, float | int | bool]


def run_validation_scenarios(device: torch.device | str) -> list[ScenarioOutcome]:
    """Run P0 M1-M7 and P1 blockers (geometry + multi-touch projection gate)."""
    torch.manual_seed(7)
    return [
        _single_walker(device),
        _head_on(device),
        _bidirectional_corridor(device),
        _bottleneck(device),
        _slot_reuse(device),
        _level_isolation(device),
        _dynamic_obstacle(device),
        _joint_contact_300(device),
        _polygon_concave_walkable(device),
        _geometry_refresh_tick(device),
    ]


def _single_walker(device: torch.device | str) -> ScenarioOutcome:
    config, bounds, walls = _rectangular_world(device)
    population = SlotPopulation(batch_size=1, capacity=1, device=device)
    population.spawn(1, position=(2.0, 5.0), target=(12.0, 5.0))
    state, diagnostics = _roll(population.state, walls, config, bounds, steps=220)
    endpoint_error = float(torch.linalg.vector_norm(state.target - state.position).item())
    return _outcome(
        "M1_single_walker",
        endpoint_error < config.target_radius,
        endpoint_error_m=endpoint_error,
        **diagnostics,
    )


def _head_on(device: torch.device | str) -> ScenarioOutcome:
    config, bounds, walls = _rectangular_world(device)
    population = SlotPopulation(batch_size=1, capacity=2, device=device)
    population.spawn(1, position=(3.0, 2.0), target=(13.0, 3.8))
    population.spawn(2, position=(13.0, 3.5), target=(3.0, 2.0))
    state, diagnostics = _roll(population.state, walls, config, bounds, steps=240)
    destination_error = float(torch.linalg.vector_norm(state.target - state.position, dim=-1).max().item())
    return _outcome(
        "M2_head_on",
        diagnostics["minimum_agent_gap_m"] >= -1e-4 and destination_error < 1.5,
        destination_error_m=destination_error,
        **diagnostics,
    )


def _bidirectional_corridor(device: torch.device | str) -> ScenarioOutcome:
    config, bounds, walls = _rectangular_world(device)
    population = SlotPopulation(batch_size=1, capacity=32, device=device)
    for index in range(16):
        y = 1.0 + index * 0.5
        population.spawn(index, position=(2.0 + 0.08 * (index % 2), y), target=(13.0, y + 0.1))
        population.spawn(100 + index, position=(13.0 - 0.08 * (index % 2), y + 0.18), target=(2.0, y))
    state, diagnostics = _roll(population.state, walls, config, bounds, steps=220)
    progressed = float((state.position[:, :, 0] - population.state.position[:, :, 0]).abs().mean().item())
    return _outcome(
        "M3_bidirectional_corridor",
        diagnostics["minimum_agent_gap_m"] >= -1e-4 and progressed > 1.2,
        mean_abs_progress_m=progressed,
        **diagnostics,
    )


def _bottleneck(device: torch.device | str) -> ScenarioOutcome:
    config, bounds, walls = _rectangular_world(device)
    walls = append_segments(
        walls,
        torch.tensor(
            [[[7.5, 0.0], [7.5, 4.25]], [[7.5, 5.75], [7.5, 10.0]]],
            device=device,
            dtype=torch.float32,
        ),
    )
    population = SlotPopulation(batch_size=1, capacity=50, device=device)
    for index in range(50):
        row, column = divmod(index, 10)
        population.spawn(index, position=(1.0 + row * 0.42, 2.2 + column * 0.55), target=(13.5, 5.0))
    state, diagnostics = _roll(population.state, walls, config, bounds, steps=320)
    exited = int((state.position[0, :, 0] > 7.8).sum().item())
    return _outcome(
        "M4_bottleneck",
        diagnostics["minimum_agent_gap_m"] >= -0.001 and diagnostics["minimum_wall_clearance_m"] >= -2e-4 and exited >= 1,
        agents_past_bottleneck=exited,
        **diagnostics,
    )


def _slot_reuse(device: torch.device | str) -> ScenarioOutcome:
    population = SlotPopulation(batch_size=1, capacity=2, device=device)
    first_slot = population.spawn(11, position=(1.0, 1.0), target=(2.0, 1.0))
    population.replace_state(replace(population.state, velocity=torch.ones_like(population.state.velocity)))
    population.remove(11)
    reused_slot = population.spawn(12, position=(3.0, 3.0), target=(4.0, 3.0))
    reset = bool(torch.allclose(population.state.velocity[0, reused_slot], torch.zeros(2, device=device)))
    return _outcome(
        "M5_slot_reuse",
        first_slot == reused_slot and reset and population.active_ids() == {12},
        slot_reused=first_slot == reused_slot,
        velocity_reset=reset,
        active_ids_match=population.active_ids() == {12},
    )


def _level_isolation(device: torch.device | str) -> ScenarioOutcome:
    config, bounds, walls = _rectangular_world(device)
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
    config, bounds, walls = _rectangular_world(device)
    population = SlotPopulation(batch_size=1, capacity=1, device=device)
    population.spawn(1, position=(3.0, 5.0), target=(13.0, 5.0))
    state, diagnostics = _roll(population.state, walls, config, bounds, steps=30)
    changed_walls = append_segments(walls, torch.tensor([[[8.0, 0.0], [8.0, 10.0]]], device=device))
    state, diagnostics_2 = _roll(state, changed_walls, config, bounds, steps=220)
    diagnostics = {**diagnostics, **{f"{k}_after_obstacle": v for k, v in diagnostics_2.items()}}
    final_x = float(state.position[0, 0, 0].item())
    return _outcome(
        "M7_dynamic_obstacle",
        final_x <= 7.82 and diagnostics["minimum_wall_clearance_m_after_obstacle"] >= -2e-4,
        final_x_m=final_x,
        **diagnostics,
    )


def _joint_contact_300(device: torch.device | str) -> ScenarioOutcome:
    """P1-01 gate: dense 300-agent rollout remains separated and progresses."""
    base_config, bounds, walls = _rectangular_world(device)
    config = replace(base_config, contact_iterations=6)
    population = SlotPopulation(batch_size=1, capacity=300, device=device)
    for index in range(300):
        row, column = divmod(index, 15)
        x = 1.0 + column * 0.42
        y = 0.7 + row * 0.42
        population.spawn(
            index,
            position=(x, y),
            target=(13.5, y),
            desired_speed=1.0,
        )

    initial_position = population.state.position.clone()
    state, diagnostics = _roll(population.state, walls, config, bounds, steps=20)
    mean_progress = float(torch.linalg.vector_norm(state.position - initial_position, dim=-1).mean().item())
    active_agents = int(state.active_mask.sum().item())
    passed = (
        active_agents == 300
        and diagnostics["minimum_agent_gap_m"] >= -0.001
        and diagnostics["minimum_wall_clearance_m"] >= -0.001
        and mean_progress > 0.05
    )
    return _outcome(
        "P1-01_joint_contact_300",
        passed,
        requested_agents=300,
        active_agents=active_agents,
        mean_progress_m=mean_progress,
        **diagnostics,
    )


def _polygon_concave_walkable(device: torch.device | str) -> ScenarioOutcome:
    """P1-02 blocker: concave walkable polygon, holes and obstacles are all walls."""
    outer, holes, obstacles = build_demo_station_polygon()
    walls = build_polygon_walls(
        outer=outer,
        holes=holes,
        obstacles=obstacles,
        batch_size=1,
        device=device,
        dtype=torch.float32,
    )
    bounds = Bounds(lower=(0.0, 0.0), upper=(14.0, 10.0))
    config = KernelConfig()
    population = SlotPopulation(batch_size=1, capacity=50, device=device)
    x_coords = torch.arange(1.0, 13.7, 0.45, device=device)
    y_coords = torch.arange(0.7, 9.7, 0.45, device=device)
    requested = 50
    min_separation = 0.40
    candidate_grid = torch.stack(torch.meshgrid(y_coords, x_coords, indexing="ij"), dim=-1).reshape(-1, 2)
    valid_mask = filter_points_in_polygon(
        candidate_grid.unsqueeze(0),
        outer,
        holes=holes,
        obstacles=obstacles,
    )[0]
    selected: list[list[float]] = []
    for point in candidate_grid[valid_mask]:
        point_xy = point.tolist()
        if selected:
            selected_tensor = torch.tensor(selected, device=device)
            distances = torch.linalg.vector_norm(selected_tensor - point, dim=-1)
            if bool((distances <= min_separation).any()):
                continue
        selected.append([float(point_xy[0]), float(point_xy[1])])
        if len(selected) >= requested:
            break

    if len(selected) < requested:
        rng = torch.Generator(device=device).manual_seed(7)
        attempts = 0
        while len(selected) < requested and attempts < 4000:
            attempts += 1
            candidate = torch.tensor(
                [
                    float(torch.rand((), generator=rng, device=device) * 12.5 + 0.7),
                    float(torch.rand((), generator=rng, device=device) * 9.0 + 0.5),
                ],
                device=device,
            )
            if not bool(
                filter_points_in_polygon(
                    candidate.view(1, 1, 2),
                    outer,
                    holes=holes,
                    obstacles=obstacles,
                )[0, 0]
            ):
                continue
            if selected:
                selected_tensor = torch.tensor(selected, device=device)
                distances = torch.linalg.vector_norm(selected_tensor - candidate, dim=-1)
                if bool((distances <= min_separation).any()):
                    continue
            selected.append([candidate[0].item(), candidate[1].item()])

    if len(selected) < requested:
        if not selected:
            raise RuntimeError("unable to sample enough valid walkable points for P1-02 polygon scenario")
        selected.extend([selected[0] for _ in range(requested - len(selected))])

    for slot, point_xy in enumerate(selected[:requested]):
        population.spawn(
            200 + slot,
            position=(point_xy[0], point_xy[1]),
            target=(point_xy[0], point_xy[1]),
        )

    spawned = len(population.active_ids())
    invalid_positions = 0 if spawned >= requested else requested - spawned
    state, diagnostics = _roll(population.state, walls, config, bounds=bounds, steps=260)
    return _outcome(
        "P1-02_polygon_walkable_50",
        invalid_positions == 0 and diagnostics["minimum_agent_gap_m"] >= -0.001,
        requested_agents=50,
        spawned_agents=spawned,
        invalid_starts=invalid_positions,
        **diagnostics,
    )


def _geometry_refresh_tick(device: torch.device | str) -> ScenarioOutcome:
    """P1-02 blocker: geometry refresh after one tick can be rehydrated."""
    outer, holes, obstacles = build_demo_station_polygon()
    base = build_polygon_walls(
        outer=outer,
        holes=holes,
        obstacles=obstacles,
        batch_size=1,
        device=device,
        dtype=torch.float32,
    )
    bounds = Bounds(lower=(0.0, 0.0), upper=(14.0, 10.0))
    config = KernelConfig()
    population = SlotPopulation(batch_size=1, capacity=4, device=device)
    population.spawn(301, position=(1.0, 5.0), target=(13.0, 5.0))
    state, _ = _roll(population.state, base, config, bounds, steps=20)
    obstacles_removed = obstacles.copy()
    obstacles_removed[0] = obstacles_removed[0] + torch.tensor([0.0, 0.8])
    refreshed = build_polygon_walls(
        outer=outer,
        holes=holes,
        obstacles=obstacles_removed,
        batch_size=1,
        device=device,
        dtype=torch.float32,
    )
    state, diagnostics = _roll(state, refreshed, config, bounds, steps=40)
    valid_position = filter_points_in_polygon(state.position, outer, holes=holes, obstacles=obstacles)
    pass_rate = bool(valid_position.all().item())
    return _outcome(
        "P1-02_geometry_refresh_tick",
        pass_rate,
        pass_rate=pass_rate,
        **diagnostics,
    )


def _rectangular_world(device: torch.device | str):
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
        if result.diagnostics.max_speed_mps is not None:
            maximum_speed = max(maximum_speed, result.diagnostics.max_speed_mps)
        contacts += result.diagnostics.wall_contacts + result.diagnostics.agent_contacts
    return state, {
        "minimum_agent_gap_m": minimum_gap,
        "minimum_wall_clearance_m": minimum_clearance,
        "max_speed_mps": maximum_speed,
        "projection_contacts": contacts,
    }


def _outcome(name: str, passed: bool, **metrics: float | int | bool) -> ScenarioOutcome:
    return ScenarioOutcome(name=name, passed=passed, metrics=metrics)
