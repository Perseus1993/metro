"""PM-033 experimental backend for Metro constructor injection.

This adapter remains **read-only** to Metro defaults: it only adds an alternative
movement implementation channel and does not alter JuPedSim selection.
"""

from __future__ import annotations

from dataclasses import replace
from math import hypot

import torch

from metro_station.adapters.simulation.movement.backend import (
    MovementBackend,
    MovementRequest,
    MovementResult,
)
from metro_station.adapters.simulation.planning.plan import WALKING_STATES

from .contracts import Bounds, KernelConfig
from .geometry import build_polygon_walls, build_demo_station_polygon, rectangular_walls, filter_points_in_polygon
from .kernel import advance
from .state import SlotPopulation


class ExperimentalTorchMovementBackend(MovementBackend):
    """Optional P0 backend; Metro remains the lifecycle and routing authority."""

    def __init__(self, *, capacity: int = 1024, device: str | None = None) -> None:
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.population = SlotPopulation(batch_size=1, capacity=capacity, device=self.device)
        self._base_config = KernelConfig()
        self._config = self._base_config
        self._steps_per_tick = 1
        self._walls = None
        self._bounds = None
        self._geometry_refresh_tick = 0
        self._layout_geometry = None
        self._level_indices: dict[str | None, int] = {}

    def move(self, passenger) -> MovementResult:
        results = self.step_all([passenger])
        if not results:
            return MovementResult(int(passenger.unique_id), passenger.pos, reached=False)
        return results[0][1]

    def step_all(self, passengers: list) -> list[tuple[object, MovementResult]]:
        eligible = [passenger for passenger in passengers if self._eligible(passenger)]
        retained = self.population.active_ids()
        eligible_ids = {int(passenger.unique_id) for passenger in eligible}
        for passenger_id in retained - eligible_ids:
            self.population.remove(passenger_id)
        if not eligible:
            return []
        self._ensure_world(eligible[0].model)
        for passenger in eligible:
            self._upsert(passenger, MovementRequest.from_passenger(passenger))
        state = self.population.state
        for _ in range(self._steps_per_tick):
            state = advance(
                state, self._walls, self._config, bounds=self._bounds, collect_diagnostics=False
            ).state
        self.population.replace_state(state)
        results = []
        for passenger in eligible:
            passenger_id = int(passenger.unique_id)
            slot = self.population.slot_for(passenger_id)
            assert slot is not None
            point = self.population.state.position[0, slot].detach().cpu().tolist()
            position = passenger.model.clamp_position((float(point[0]), float(point[1])))
            reached = hypot(position[0] - passenger.target[0], position[1] - passenger.target[1]) <= self._config.target_radius
            results.append((passenger, MovementResult(passenger_id, position, reached=reached)))
        return results

    def place_passenger(self, passenger, position, *, target=None, level_id=None):
        placed = passenger.model.clamp_position(position)
        self._ensure_world(passenger.model)
        request = MovementRequest(
            passenger_id=int(passenger.unique_id),
            position=placed,
            target=target or passenger.target or placed,
            radius=float(passenger.model.scenario.jupedsim_target_radius_units),
            level=level_id if level_id is not None else passenger.current_level_id,
            desired_speed_mps=float(passenger.model.desired_walk_speed_mps(passenger)),
        )
        self._upsert(passenger, request)
        return placed

    def remove_passenger(self, passenger) -> None:
        passenger_id = int(passenger.unique_id)
        if passenger_id in self.population.active_ids():
            self.population.remove(passenger_id)

    def active_passenger_ids(self) -> set[int]:
        return self.population.active_ids()

    def on_walkable_geometry_changed(self, model: object) -> None:
        del model
        self._geometry_refresh_tick += 1
        self._walls = None

    def _ensure_world(self, model) -> None:
        if self._walls is not None:
            return
        self._layout_geometry = getattr(model.layout_graph, "geometry", None)
        if self._layout_geometry is not None and hasattr(self._layout_geometry, "walkable_polygons"):
            outer = torch.tensor(self._layout_geometry.walkable_polygons[0], dtype=torch.float32)
            holes = [torch.tensor(item, dtype=torch.float32) for item in getattr(self._layout_geometry, "holes", [])]
            obstacles = [torch.tensor(item, dtype=torch.float32) for item in getattr(self._layout_geometry, "obstacles", [])]
            self._walls = build_polygon_walls(
                outer=outer,
                holes=holes,
                obstacles=obstacles,
                batch_size=1,
                device=self.device,
                dtype=torch.float32,
            )
            self._bounds = Bounds(lower=(0.0, 0.0), upper=(float(self._layout_geometry.width), float(self._layout_geometry.height)))
        else:
            try:
                geometry = model.layout_graph.geometry
                width, height = float(geometry.width), float(geometry.height)
                self._walls = rectangular_walls(
                    width=width,
                    height=height,
                    batch_size=1,
                    device=self.device,
                    dtype=torch.float32,
                )
                self._bounds = Bounds(lower=(0.0, 0.0), upper=(width, height))
            except Exception:
                outer, holes, obstacles = build_demo_station_polygon()
                self._walls = build_polygon_walls(
                    outer=outer,
                    holes=holes,
                    obstacles=obstacles,
                    batch_size=1,
                    device=self.device,
                    dtype=torch.float32,
                )
                self._bounds = Bounds(lower=(0.0, 0.0), upper=(14.0, 10.0))
        tick_seconds = float(model.scenario.tick_seconds)
        self._steps_per_tick = max(1, round(tick_seconds / self._config.dt_seconds))

    def _upsert(self, passenger, request: MovementRequest) -> None:
        slot = self.population.slot_for(request.passenger_id)
        level_index = self._level_indices.setdefault(request.level, len(self._level_indices))
        if slot is None:
            if self._layout_geometry is not None and hasattr(self._layout_geometry, "walkable_polygons"):
                outer = torch.tensor(self._layout_geometry.walkable_polygons[0], dtype=torch.float32)
            else:
                outer = build_demo_station_polygon()[0]
            layout = self._layout_geometry
            holes = getattr(layout, "holes", None) if layout is not None else None
            obstacles = getattr(layout, "obstacles", None) if layout is not None else None
            if holes is None:
                _, hole_defs, obstacle_defs = build_demo_station_polygon()
                holes = hole_defs
                obstacles = obstacle_defs
            if not bool(
                filter_points_in_polygon(
                    torch.tensor([[request.position]], dtype=torch.float32, device=self.device),
                    torch.tensor(outer, dtype=torch.float32, device=self.device) if not torch.is_tensor(outer) else outer,
                    holes=holes,
                    obstacles=obstacles,
                )[0, 0].item()
            ):
                raise ValueError(f"spawned position {request.position} is not walkable in active geometry")
            self.population.spawn(
                request.passenger_id,
                position=request.position,
                target=request.target,
                radius=request.radius,
                desired_speed=request.desired_speed_mps,
                level_index=level_index,
            )
            return
        state = self.population.state
        position, target = state.position.clone(), state.target.clone()
        radius, desired_speed, levels = state.radius.clone(), state.desired_speed.clone(), state.level_index.clone()
        position[0, slot] = torch.tensor(request.position, device=self.device)
        target[0, slot] = torch.tensor(request.target, device=self.device)
        radius[0, slot, 0] = request.radius
        desired_speed[0, slot, 0] = request.desired_speed_mps
        levels[0, slot] = level_index
        self.population.replace_state(replace(state, position=position, target=target, radius=radius, desired_speed=desired_speed, level_index=levels))

    @staticmethod
    def _eligible(passenger) -> bool:
        suppressed = getattr(passenger, "movement_suppressed_this_step", None)
        return passenger.state in WALKING_STATES and not passenger.passive_facility_service and not (callable(suppressed) and suppressed())
