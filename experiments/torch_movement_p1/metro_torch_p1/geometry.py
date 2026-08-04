"""Polygon geometry tensorisation for walkable domains in P1 blocking work."""

from __future__ import annotations

from dataclasses import dataclass

import torch

from .contracts import WallSegments


@dataclass(frozen=True)
class PolygonGeometry:
    """Closed polygon + holes + internal obstacle polygons."""

    outer: torch.Tensor
    holes: list[torch.Tensor] | None = None
    obstacles: list[torch.Tensor] | None = None


def rectangular_walls(
    *,
    width: float,
    height: float,
    batch_size: int,
    device: torch.device | str,
    dtype: torch.dtype,
) -> WallSegments:
    """Fallback rectangle envelope retained for compatibility."""
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


def polygon_to_segments(
    polygon: list[tuple[float, float]] | torch.Tensor,
    *,
    clockwise_hole: bool = False,
) -> torch.Tensor:
    """Convert one polygon into a closed [segments, 2, 2] tensor."""
    if isinstance(polygon, torch.Tensor):
        vertices = polygon.to(dtype=torch.float32, device=polygon.device)
    else:
        vertices = torch.tensor(polygon, dtype=torch.float32)
    if vertices.ndim != 2 or vertices.shape[-1] != 2:
        raise ValueError("polygon must be [N,2]")
    if vertices.shape[0] < 3:
        raise ValueError("polygon must have at least 3 vertices")
    oriented = _ensure_polygon_orientation(vertices, clockwise_expected=clockwise_hole)
    return torch.stack([oriented, torch.roll(oriented, shifts=-1, dims=0)], dim=1)


def append_segments(walls: WallSegments, segments: torch.Tensor) -> WallSegments:
    """Append segments that are shared by all batch items."""
    if segments.ndim != 3 or segments.shape[-2:] != (2, 2):
        raise ValueError("segments must be [wall,2,2]")
    repeated = segments.to(device=walls.segments.device, dtype=walls.segments.dtype).unsqueeze(0).repeat(
        walls.batch_size, 1, 1, 1
    )
    active = torch.ones(repeated.shape[:2], device=walls.segments.device, dtype=torch.bool)
    return WallSegments(
        segments=torch.cat((walls.segments, repeated), dim=1),
        active_mask=torch.cat((walls.active_mask, active), dim=1),
    )


def build_polygon_walls(
    *,
    outer: torch.Tensor,
    batch_size: int,
    device: torch.device | str,
    dtype: torch.dtype,
    holes: list[torch.Tensor] | None = None,
    obstacles: list[torch.Tensor] | None = None,
) -> WallSegments:
    """Convert walkable polygon + holes + obstacle polygons to wall segments."""
    segments = [polygon_to_segments(outer, clockwise_hole=False)]
    for hole in holes or []:
        segments.append(polygon_to_segments(hole, clockwise_hole=True))
    for obstacle in obstacles or []:
        segments.append(polygon_to_segments(obstacle, clockwise_hole=True))
    stacked = torch.cat([s.to(device=device, dtype=dtype) for s in segments], dim=0)
    return WallSegments(
        segments=stacked.unsqueeze(0).repeat(batch_size, 1, 1, 1),
        active_mask=torch.ones((batch_size, stacked.shape[0]), device=device, dtype=torch.bool),
    )


def filter_points_in_polygon(
    points: torch.Tensor,
    polygon: torch.Tensor,
    holes: list[torch.Tensor] | None = None,
    obstacles: list[torch.Tensor] | None = None,
) -> torch.Tensor:
    """Ray-cast point-in-polygon for multiple points.

    Returns mask [batch, slots] of valid points.
    """
    if points.ndim != 3:
        raise ValueError("points must be [batch, slots, 2]")
    valid = _point_in_polygon(points, polygon)
    for hole in holes or []:
        valid = valid & (~_point_in_polygon(points, hole))
    for obstacle in obstacles or []:
        valid = valid & (~_point_in_polygon(points, obstacle))
    return valid


def build_demo_station_polygon() -> tuple[torch.Tensor, list[torch.Tensor], list[torch.Tensor]]:
    """A concise polygon+hole geometry for the visual-demo thin slice case."""
    outer = torch.tensor(
        [
            [0.0, 0.0],
            [14.0, 0.0],
            [14.0, 10.0],
            [11.0, 10.0],
            [11.0, 6.0],
            [3.0, 6.0],
            [3.0, 10.0],
            [0.0, 10.0],
        ],
        dtype=torch.float32,
    )
    holes = [
        torch.tensor([[4.8, 0.0], [8.4, 0.0], [8.4, 3.0], [4.8, 3.0]], dtype=torch.float32),
    ]
    obstacles = [
        torch.tensor([[5.2, 3.5], [7.6, 3.5], [7.6, 4.0], [5.2, 4.0]], dtype=torch.float32),
    ]
    return outer, holes, obstacles


def _point_in_polygon(points: torch.Tensor, polygon: torch.Tensor) -> torch.Tensor:
    """Vectorized ray casting."""
    if polygon.shape[0] < 3:
        raise ValueError("polygon must have at least three vertices")
    batch, slots, _ = points.shape
    v = polygon.to(device=points.device, dtype=points.dtype)
    x = points[:, :, 0]
    y = points[:, :, 1]
    x1, y1 = v[:, 0], v[:, 1]
    x2, y2 = torch.roll(v, shifts=-1, dims=0)[:, 0], torch.roll(v, shifts=-1, dims=0)[:, 1]
    intersects = ((y1[None, None, :] > y[:, :, None]) != (y2[None, None, :] > y[:, :, None])) & (
        x[:, :, None]
        < x1[None, None, :] + (y[:, :, None] - y1[None, None, :]) * (x2[None, None, :] - x1[None, None, :]) / (
            y2[None, None, :] - y1[None, None, :] + 1e-12
        )
    )
    return intersects.sum(dim=2) % 2 == 1


def _polygon_area2(vertices: torch.Tensor) -> float:
    shifted = torch.roll(vertices, shifts=-1, dims=0)
    signed_area2 = float(torch.sum(vertices[:, 0] * shifted[:, 1] - shifted[:, 0] * vertices[:, 1]).item())
    return signed_area2


def _ensure_polygon_orientation(vertices: torch.Tensor, *, clockwise_expected: bool) -> torch.Tensor:
    area2 = _polygon_area2(vertices)
    clockwise = area2 < 0
    if clockwise == clockwise_expected:
        return vertices
    return torch.flip(vertices, dims=[0])
