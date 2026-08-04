"""Small, reproducible throughput probes for the eager tensor kernel."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from time import perf_counter

import torch

from .contracts import Bounds, KernelConfig, PopulationState
from .geometry import rectangular_walls
from .kernel import advance


@dataclass(frozen=True)
class BenchmarkResult:
    device: str
    batch_size: int
    capacity: int
    timed_steps: int
    elapsed_seconds: float
    agent_steps_per_second: float
    peak_memory_mib: float | None


def run_benchmarks() -> list[BenchmarkResult]:
    """Run one CPU baseline and the P0's three GPU workload points."""
    results = [_measure(torch.device("cpu"), batch_size=1, capacity=300, timed_steps=30)]
    if torch.cuda.is_available():
        device = torch.device("cuda")
        results.extend(
            [
                _measure(device, batch_size=1, capacity=300, timed_steps=50),
                _measure(device, batch_size=8, capacity=300, timed_steps=50),
                _measure(device, batch_size=32, capacity=300, timed_steps=50),
                _measure(device, batch_size=1, capacity=1024, timed_steps=30),
            ]
        )
    return results


def _measure(device: torch.device, *, batch_size: int, capacity: int, timed_steps: int) -> BenchmarkResult:
    walls = rectangular_walls(width=100.0, height=100.0, batch_size=batch_size, device=device, dtype=torch.float32)
    config = KernelConfig(enable_safety_projection=True)
    bounds = Bounds(lower=(0.0, 0.0), upper=(100.0, 100.0))
    throughput_samples: list[float] = []
    elapsed_samples: list[float] = []
    peak_memory = None
    # A single GPU timing is noisy when the same device is used by calibration
    # immediately beforehand.  Three independent rollouts make the gate a
    # reproducible p50 measurement without changing the workload.
    for _ in range(3):
        state = _dense_state(device, batch_size, capacity)
        for _ in range(8):
            state = advance(state, walls, config, bounds=bounds, collect_diagnostics=False).state
        _synchronize(device)
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        started = perf_counter()
        for _ in range(timed_steps):
            state = advance(state, walls, config, bounds=bounds, collect_diagnostics=False).state
        _synchronize(device)
        elapsed = perf_counter() - started
        elapsed_samples.append(elapsed)
        throughput_samples.append(batch_size * capacity * timed_steps / elapsed)
        if device.type == "cuda":
            measured_peak = torch.cuda.max_memory_allocated(device) / 1024**2
            peak_memory = measured_peak if peak_memory is None else max(peak_memory, measured_peak)
    elapsed = float(median(elapsed_samples))
    agent_steps_per_second = float(median(throughput_samples))
    return BenchmarkResult(
        device=str(device),
        batch_size=batch_size,
        capacity=capacity,
        timed_steps=timed_steps,
        elapsed_seconds=elapsed,
        agent_steps_per_second=agent_steps_per_second,
        peak_memory_mib=peak_memory,
    )


def _dense_state(device: torch.device, batch_size: int, capacity: int) -> PopulationState:
    generator = torch.Generator(device=device).manual_seed(31)
    position = 5.0 + 90.0 * torch.rand((batch_size, capacity, 2), device=device, generator=generator)
    target = 5.0 + 90.0 * torch.rand((batch_size, capacity, 2), device=device, generator=generator)
    scalar = torch.full((batch_size, capacity, 1), 0.18, device=device)
    slots = torch.arange(capacity, device=device).repeat(batch_size, 1)
    return PopulationState(
        position=position,
        velocity=torch.zeros_like(position),
        target=target,
        radius=scalar,
        desired_speed=torch.full_like(scalar, 1.2),
        active_mask=torch.ones((batch_size, capacity), device=device, dtype=torch.bool),
        level_index=torch.zeros((batch_size, capacity), device=device, dtype=torch.int64),
        passenger_ids=slots,
    )


def _synchronize(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)
