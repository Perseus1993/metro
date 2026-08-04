from __future__ import annotations

import heapq
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry


GridCell = tuple[int, int]
MeterPoint = tuple[float, float]


@dataclass(frozen=True)
class GridDistanceField:
    grid: GridFloorField
    costs: Mapping[GridCell, float]

    def cost_at(self, point: MeterPoint) -> float:
        cell = self.grid.cell_at(point)
        if cell is None:
            return float("inf")
        return float(self.costs.get(cell, float("inf")))

    def next_cell(self, point: MeterPoint) -> GridCell | None:
        cell = self.grid.cell_at(point)
        if cell is None:
            return None
        current_cost = self.costs.get(cell, float("inf"))
        best = cell
        best_cost = current_cost
        for neighbor, _step_cost in self.grid.neighbors(cell):
            cost = self.costs.get(neighbor, float("inf"))
            if cost < best_cost:
                best = neighbor
                best_cost = cost
        return best if best != cell else None

    def descent_vector(self, point: MeterPoint) -> MeterPoint:
        next_cell = self.next_cell(point)
        if next_cell is None:
            return (0.0, 0.0)
        target = self.grid.center(next_cell)
        dx = target[0] - point[0]
        dy = target[1] - point[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            return (0.0, 0.0)
        return (dx / length, dy / length)


@dataclass(frozen=True)
class GridFloorField:
    """Walkable grid used for fast portal/facility potential fields.

    Static cells are built once from station geometry. Dynamic crowding is a
    per-cell penalty applied when a distance field is recomputed, which can be
    done at a low frequency without changing the underlying grid.
    """

    geometry: BaseGeometry
    cell_size_m: float
    min_x: float
    min_y: float
    rows: int
    cols: int
    walkable_cells: frozenset[GridCell]
    adjacency: Mapping[GridCell, tuple[tuple[GridCell, float], ...]]

    @classmethod
    def from_geometry(
        cls,
        geometry: BaseGeometry,
        *,
        cell_size_m: float = 1.0,
    ) -> GridFloorField:
        if cell_size_m <= 0.0:
            raise ValueError("cell_size_m must be positive")
        min_x, min_y, max_x, max_y = geometry.bounds
        cols = max(1, math.ceil((max_x - min_x) / cell_size_m))
        rows = max(1, math.ceil((max_y - min_y) / cell_size_m))
        walkable: set[GridCell] = set()
        for row in range(rows):
            for col in range(cols):
                center = (
                    min_x + (col + 0.5) * cell_size_m,
                    min_y + (row + 0.5) * cell_size_m,
                )
                if geometry.covers(Point(center)):
                    walkable.add((row, col))
        frozen_walkable = frozenset(walkable)
        adjacency: dict[GridCell, tuple[tuple[GridCell, float], ...]] = {}
        for cell in frozen_walkable:
            adjacency[cell] = cls._build_neighbors(
                geometry=geometry,
                cell=cell,
                walkable_cells=frozen_walkable,
                min_x=float(min_x),
                min_y=float(min_y),
                cell_size_m=float(cell_size_m),
            )
        return cls(
            geometry=geometry,
            cell_size_m=float(cell_size_m),
            min_x=float(min_x),
            min_y=float(min_y),
            rows=rows,
            cols=cols,
            walkable_cells=frozen_walkable,
            adjacency=adjacency,
        )

    def cell_at(self, point: MeterPoint) -> GridCell | None:
        col = math.floor((point[0] - self.min_x) / self.cell_size_m)
        row = math.floor((point[1] - self.min_y) / self.cell_size_m)
        cell = (row, col)
        if cell not in self.walkable_cells:
            return None
        return cell

    def center(self, cell: GridCell) -> MeterPoint:
        row, col = cell
        return (
            self.min_x + (col + 0.5) * self.cell_size_m,
            self.min_y + (row + 0.5) * self.cell_size_m,
        )

    def neighbors(self, cell: GridCell) -> tuple[tuple[GridCell, float], ...]:
        return self.adjacency.get(cell, ())

    @staticmethod
    def _build_neighbors(
        *,
        geometry: BaseGeometry,
        cell: GridCell,
        walkable_cells: frozenset[GridCell],
        min_x: float,
        min_y: float,
        cell_size_m: float,
    ) -> tuple[tuple[GridCell, float], ...]:
        source = (
            min_x + (cell[1] + 0.5) * cell_size_m,
            min_y + (cell[0] + 0.5) * cell_size_m,
        )
        neighbors: list[tuple[GridCell, float]] = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                candidate = (cell[0] + dr, cell[1] + dc)
                if candidate not in walkable_cells:
                    continue
                if dr != 0 and dc != 0:
                    if (cell[0] + dr, cell[1]) not in walkable_cells:
                        continue
                    if (cell[0], cell[1] + dc) not in walkable_cells:
                        continue
                target = (
                    min_x + (candidate[1] + 0.5) * cell_size_m,
                    min_y + (candidate[0] + 0.5) * cell_size_m,
                )
                if not geometry.covers(LineString([source, target])):
                    continue
                neighbors.append(
                    (
                        candidate,
                        math.hypot(
                            (target[0] - source[0]),
                            (target[1] - source[1]),
                        ),
                    )
                )
        return tuple(neighbors)

    def distance_field(
        self,
        targets: Iterable[MeterPoint],
        *,
        dynamic_penalty: Mapping[GridCell, float] | None = None,
    ) -> GridDistanceField:
        penalties = dynamic_penalty or {}
        costs: dict[GridCell, float] = {}
        heap: list[tuple[float, GridCell]] = []
        for target in targets:
            cell = self.cell_at(target)
            if cell is None:
                continue
            if costs.get(cell, float("inf")) <= 0.0:
                continue
            costs[cell] = 0.0
            heapq.heappush(heap, (0.0, cell))

        while heap:
            cost, cell = heapq.heappop(heap)
            if cost > costs.get(cell, float("inf")):
                continue
            for neighbor, step_cost in self.neighbors(cell):
                multiplier = 1.0 + max(0.0, float(penalties.get(neighbor, 0.0)))
                next_cost = cost + step_cost * multiplier
                if next_cost < costs.get(neighbor, float("inf")):
                    costs[neighbor] = next_cost
                    heapq.heappush(heap, (next_cost, neighbor))
        return GridDistanceField(grid=self, costs=costs)

    def density_penalty(
        self,
        positions: Iterable[MeterPoint],
        *,
        radius_cells: int = 1,
        weight: float = 1.0,
    ) -> dict[GridCell, float]:
        penalties: dict[GridCell, float] = {}
        radius = max(0, int(radius_cells))
        for position in positions:
            cell = self.cell_at(position)
            if cell is None:
                continue
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    candidate = (cell[0] + dr, cell[1] + dc)
                    if candidate not in self.walkable_cells:
                        continue
                    distance = math.hypot(dr, dc)
                    if distance > radius + 1e-9:
                        continue
                    contribution = weight / (1.0 + distance)
                    penalties[candidate] = penalties.get(candidate, 0.0) + contribution
        return penalties
