from __future__ import annotations

from collections.abc import Iterable
import math

import jupedsim as jps
from shapely.geometry import Polygon
from shapely.ops import unary_union

from ..config import SIM_DT, TRAIN_CYCLE
from ..geometry import meters
from ..layout import STATION_LAYOUT
from ..process_model import PROCESS_MODEL
from ..queue_runtime import (
    BOARDING_EXIT_Y,
    BOARDING_QUEUE_HEAD_Y,
    NativeQueueRuntime,
    boarding_queue_positions,
    facility_queue_positions,
    queue_service_distance_m,
)
from .replanning import (
    choose_least_loaded_stage,
    reachable_release_targets,
    stage_reachable_from_position,
)
from .stages import add_registered_queue_stage
from .types import ServiceRelease, SoftReleaseTargets, StageRegistry


def ease(v: float) -> float:
    v = max(0.0, min(1.0, v))
    return v * v * (3.0 - 2.0 * v)


def add_native_facility_queues(
    sim: jps.Simulation,
    geometry: Polygon,
    stage_registry: StageRegistry,
) -> dict[str, NativeQueueRuntime]:
    runtimes: dict[str, NativeQueueRuntime] = {}
    for spec in PROCESS_MODEL.native_facility_queues:
        positions = facility_queue_positions(spec, geometry)
        stage_id = add_registered_queue_stage(
            sim,
            stage_registry,
            spec.name,
            positions,
            facility=spec.name,
        )
        batch_size = 8 if spec.name == "down_elevator_queue" else 1
        runtimes[spec.name] = NativeQueueRuntime(
            name=spec.name,
            source=spec.source.replace("_state", "_native"),
            color=spec.color,
            stage_id=stage_id,
            service_interval=spec.service_interval,
            next_service=spec.first_service,
            batch_size=batch_size,
            spec=spec,
            positions_m=tuple(positions),
        )
    return runtimes


def train_door_open_fraction(local: float) -> float:
    if local < 6.0 or local > 22.8:
        return 0.0
    open_in = ease((local - 6.0) / 2.2)
    close_out = 1.0 - ease((local - 20.2) / 2.4)
    return max(0.0, min(open_in, close_out))


def train_boarding_geometry() -> Polygon:
    vestibules = []
    for point in STATION_LAYOUT.control_points["platform_doors"]:
        door_x = float(point[0])
        half_width = 0.018
        vestibules.append(
            Polygon(
                [
                    meters((door_x - half_width, BOARDING_QUEUE_HEAD_Y)),
                    meters((door_x + half_width, BOARDING_QUEUE_HEAD_Y)),
                    meters((door_x + half_width, BOARDING_EXIT_Y + 0.012)),
                    meters((door_x - half_width, BOARDING_EXIT_Y + 0.012)),
                ]
            )
        )
    return unary_union(vestibules)


def add_boarding_door_queues(
    sim: jps.Simulation,
    geometry: Polygon,
    stage_registry: StageRegistry,
) -> list[NativeQueueRuntime]:
    runtimes: list[NativeQueueRuntime] = []
    for door_index, point in enumerate(STATION_LAYOUT.control_points["platform_doors"]):
        door_x = float(point[0])
        facility = f"boarding_door_{door_index + 1}"
        positions = boarding_queue_positions(door_x, geometry)
        queue_stage = add_registered_queue_stage(
            sim,
            stage_registry,
            facility,
            positions,
            facility=facility,
        )
        runtimes.append(
            NativeQueueRuntime(
                name=facility,
                source="boarding_queue_native",
                color="#5dd45f" if door_index % 2 else "#ffd166",
                stage_id=queue_stage,
                service_interval=0.42,
                next_service=8.6 + door_index * 0.035,
                batch_size=1,
                train_service=True,
                positions_m=tuple(positions),
            )
        )
    return runtimes


def boarding_service_open(time: float) -> bool:
    local = time % TRAIN_CYCLE
    return 8.6 <= local <= 20.2 and train_door_open_fraction(local) > 0.05


def service_native_queues(
    sim: jps.Simulation,
    runtimes: Iterable[NativeQueueRuntime],
    time: float,
    soft_release_targets: SoftReleaseTargets,
    stage_registry: StageRegistry,
    geometry: Polygon,
) -> list[ServiceRelease]:
    popped_agents: list[ServiceRelease] = []
    for runtime in runtimes:
        if runtime.train_service and not boarding_service_open(time):
            runtime.next_service = max(runtime.next_service, time + runtime.service_interval)
            continue

        while time + SIM_DT * 0.5 >= runtime.next_service:
            stage = sim.get_stage(runtime.stage_id)
            queued = stage.count_enqueued()
            if queued > 0:
                count = min(runtime.batch_size, queued)
                popped = stage.enqueued()[:count]
                stage.pop(count)
                popped_agents.extend(
                    ServiceRelease(runtime=runtime, sim_id=int(agent_id), mode="enqueued")
                    for agent_id in popped
                )
            else:
                releases = soft_release_queue_agents(
                    sim=sim,
                    runtime=runtime,
                    soft_release_targets=soft_release_targets,
                    stage_registry=stage_registry,
                    geometry=geometry,
                    limit=runtime.batch_size,
                )
                popped_agents.extend(releases)
            if runtime.train_service:
                runtime.next_service = time + runtime.service_interval
                break
            runtime.next_service += runtime.service_interval
    return popped_agents


def soft_release_queue_agents(
    *,
    sim: jps.Simulation,
    runtime: NativeQueueRuntime,
    soft_release_targets: SoftReleaseTargets,
    stage_registry: StageRegistry,
    geometry: Polygon,
    limit: int,
) -> list[ServiceRelease]:
    candidates: list[tuple[int, float, int, int, tuple[int, ...]]] = []
    live_stage_ids: set[int] = set()
    radius_m = queue_soft_capture_radius_m(runtime)
    for agent in sim.agents():
        if int(agent.stage_id) != runtime.stage_id:
            continue
        sim_id = int(agent.id)
        live_stage_ids.add(sim_id)
        targets = soft_release_targets.get((runtime.stage_id, int(agent.journey_id)))
        if not targets:
            continue
        position = (float(agent.position[0]), float(agent.position[1]))
        slot_distance = queue_service_distance_m(runtime, position)
        head_distance = queue_soft_service_distance_m(runtime, position)
        if min(slot_distance, head_distance) > radius_m:
            continue
        reachable_targets = (
            targets
            if is_vertical_facility(runtime)
            else reachable_release_targets(
                position=position,
                targets=targets,
                stage_registry=stage_registry,
                geometry=geometry,
            )
        )
        if not reachable_targets:
            continue
        order = runtime.virtual_queue_order.get(sim_id)
        if order is None:
            order = runtime.next_virtual_queue_order
            runtime.virtual_queue_order[sim_id] = order
            runtime.next_virtual_queue_order += 1
        candidates.append((order, head_distance, sim_id, int(agent.journey_id), reachable_targets))

    for sim_id in list(runtime.virtual_queue_order):
        if sim_id not in live_stage_ids:
            runtime.virtual_queue_order.pop(sim_id, None)

    candidates.sort(key=lambda item: (item[0], item[1]))

    releases: list[ServiceRelease] = []
    for _order, _distance, sim_id, journey_id, targets in candidates[: max(0, limit)]:
        next_stage = choose_least_loaded_stage(sim, targets)
        position = (float(sim.agent(sim_id).position[0]), float(sim.agent(sim_id).position[1]))
        release_reachable = stage_reachable_from_position(
            position=position,
            stage_id=next_stage,
            stage_registry=stage_registry,
            geometry=geometry,
        )
        sim.switch_agent_journey(sim_id, journey_id, next_stage)
        runtime.virtual_queue_order.pop(sim_id, None)
        releases.append(
            ServiceRelease(
                runtime=runtime,
                sim_id=sim_id,
                mode="virtual_queue",
                release_reachable=release_reachable,
                release_stage_id=next_stage,
            )
        )
    return releases


def queue_soft_capture_radius_m(runtime: NativeQueueRuntime) -> float:
    if runtime.spec is None:
        return 1.45
    name = runtime.spec.name
    if name.startswith("entry_gate"):
        return 2.4
    if name.startswith("exit_gate"):
        return 10.0
    if "escalator" in name:
        return 8.0
    if "elevator" in name:
        return 10.0
    if name.startswith("stairs"):
        return 6.0
    return 1.6


def is_vertical_facility(runtime: NativeQueueRuntime) -> bool:
    if runtime.spec is None:
        return False
    return is_vertical_facility_name(runtime.spec.name)


def is_vertical_facility_name(name: str | None) -> bool:
    if name is None:
        return False
    return "escalator" in name or "elevator" in name or name.startswith("stairs")


def queue_soft_service_distance_m(
    runtime: NativeQueueRuntime,
    position: tuple[float, float],
) -> float:
    if runtime.spec is not None:
        head = meters(runtime.spec.head)
        return math.hypot(position[0] - head[0], position[1] - head[1])
    return queue_service_distance_m(runtime, position)
