"""Typed value contracts for the isolated tensor movement experiment."""

from __future__ import annotations

from dataclasses import dataclass

import torch


@dataclass(frozen=True)
class Bounds:
    """Axis-aligned physical limits used only by the safety projection."""

    lower: tuple[float, float]
    upper: tuple[float, float]


@dataclass(frozen=True)
class KernelConfig:
    """Static numerical settings for one movement rollout."""

    dt_seconds: float = 0.05
    target_radius: float = 0.25
    max_speed_mps: float = 1.8
    max_acceleration_mps2: float = 3.0
    agent_repulsion_range_m: float = 0.55
    wall_repulsion_range_m: float = 0.35
    safety_clearance_m: float = 0.001
    enable_safety_projection: bool = True


@dataclass(frozen=True)
class KernelParameters:
    """Continuous parameters that can be ordinary numbers or autograd tensors."""

    agent_repulsion_strength: float | torch.Tensor = 2.4
    wall_repulsion_strength: float | torch.Tensor = 3.5
    relaxation_time_seconds: float | torch.Tensor = 0.45


@dataclass(frozen=True)
class WallSegments:
    """Read-only line segments, padded with a boolean mask per batch item."""

    segments: torch.Tensor
    active_mask: torch.Tensor

    def __post_init__(self) -> None:
        if self.segments.ndim != 4 or self.segments.shape[-2:] != (2, 2):
            raise ValueError("segments must have shape [batch, wall, 2, 2]")
        if self.active_mask.shape != self.segments.shape[:2]:
            raise ValueError("wall active_mask must have shape [batch, wall]")
        if self.active_mask.dtype is not torch.bool:
            raise TypeError("wall active_mask must be bool")

    @property
    def batch_size(self) -> int:
        return int(self.segments.shape[0])


@dataclass(frozen=True)
class PopulationState:
    """Tensor state. The kernel never receives a Mesa or domain agent object."""

    position: torch.Tensor
    velocity: torch.Tensor
    target: torch.Tensor
    radius: torch.Tensor
    desired_speed: torch.Tensor
    active_mask: torch.Tensor
    level_index: torch.Tensor
    passenger_ids: torch.Tensor

    def __post_init__(self) -> None:
        batch_size, capacity, dimensions = self.position.shape
        if dimensions != 2:
            raise ValueError("position must have shape [batch, slot, 2]")
        expected_vector = (batch_size, capacity, 2)
        expected_scalar = (batch_size, capacity, 1)
        expected_slot = (batch_size, capacity)
        if self.velocity.shape != expected_vector or self.target.shape != expected_vector:
            raise ValueError("velocity and target must match position shape")
        if self.radius.shape != expected_scalar or self.desired_speed.shape != expected_scalar:
            raise ValueError("radius and desired_speed must have shape [batch, slot, 1]")
        if self.active_mask.shape != expected_slot or self.active_mask.dtype is not torch.bool:
            raise ValueError("active_mask must be bool with shape [batch, slot]")
        if self.level_index.shape != expected_slot or self.passenger_ids.shape != expected_slot:
            raise ValueError("level_index and passenger_ids must match active_mask")

    @property
    def batch_size(self) -> int:
        return int(self.position.shape[0])

    @property
    def capacity(self) -> int:
        return int(self.position.shape[1])

    @property
    def device(self) -> torch.device:
        return self.position.device

    @property
    def dtype(self) -> torch.dtype:
        return self.position.dtype
