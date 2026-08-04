"""Geometry conversion for the P0 kernel; Shapely is intentionally not required."""

from __future__ import annotations

import torch

from .contracts import WallSegments


def rectangular_walls(
    *,
    width: float,
    height: float,
    batch_size: int,
    device: torch.device | str,
    dtype: torch.dtype,
) -> WallSegments:
    """Return counter-clockwise outer walls for a [0,width] x [0,height] domain."""
    base = torch.tensor(
        [
            [[0.0, 0.0], [width, 0.0]],
            [[width, 0.0], [width, height]],
            [[width, height], [0.0, height]],
            [[0.0, height], [0.0, 0.0]],
        ],
        device=device,
        dtype=dtype,
    )
    return WallSegments(
        segments=base.unsqueeze(0).repeat(batch_size, 1, 1, 1),
        active_mask=torch.ones((batch_size, 4), device=device, dtype=torch.bool),
    )


def append_segments(walls: WallSegments, segments: torch.Tensor) -> WallSegments:
    """Append the same one or more segments to every batch item."""
    if segments.ndim != 3 or segments.shape[-2:] != (2, 2):
        raise ValueError("segments must have shape [wall, 2, 2]")
    repeated = segments.to(device=walls.segments.device, dtype=walls.segments.dtype)
    repeated = repeated.unsqueeze(0).repeat(walls.batch_size, 1, 1, 1)
    active = torch.ones(repeated.shape[:2], device=walls.segments.device, dtype=torch.bool)
    return WallSegments(
        segments=torch.cat((walls.segments, repeated), dim=1),
        active_mask=torch.cat((walls.active_mask, active), dim=1),
    )


def bottleneck_walls(walls: WallSegments, *, x: float, gap_center_y: float, gap_width: float) -> WallSegments:
    """Create an internal vertical barrier with one passable gap."""
    height = float(walls.segments[0, 1, 1, 1].item())
    lower_gap = gap_center_y - gap_width / 2.0
    upper_gap = gap_center_y + gap_width / 2.0
    additions = torch.tensor(
        [
            [[x, 0.0], [x, lower_gap]],
            [[x, upper_gap], [x, height]],
        ],
        device=walls.segments.device,
        dtype=walls.segments.dtype,
    )
    return append_segments(walls, additions)
