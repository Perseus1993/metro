from __future__ import annotations

import jupedsim as jps
from shapely.geometry import Polygon

from .entry_paths import entry_gate_approach_radius, entry_gate_decision_path, entry_start_for_side
from ..geometry import meters
from ..layout import STATION_LAYOUT
from ..queue_runtime import (
    BOARDING_EXIT_Y,
    BOARDING_SCREEN_DOOR_Y,
    BOARDING_VESTIBULE_Y,
    QUEUE_CAPTURE_APRONS_N,
    NativeQueueRuntime,
)
from ..region_flow import build_region_capture_flow
from ..specs import GATE_QUEUE_SPECS
from .constants import (
    BOARDING_SCREEN_DOOR_RADIUS_M,
    BOARDING_TRAIN_EXIT_HALF_SIZE_M,
    BOARDING_VESTIBULE_RADIUS_M,
    ELEVATOR_CHOICE_SHARE,
    ELEVATOR_LOBBY_RADIUS_M,
    EXIT_CORRIDOR_RADIUS_M,
    GATE_DECISION_RADIUS_M,
    PLATFORM_APPROACH_RADIUS_M,
    PLATFORM_DECISION_RADIUS_M,
    RIGHT_ENTRY_CORRIDOR_RADIUS_M,
    TRANSFER_DECISION_RADIUS_M,
)
from .stages import (
    add_registered_exit_stage,
    add_registered_waypoint_stage,
    entry_gate_runtimes_for_side,
    post_gate_portal_radius,
    right_entry_paid_corridor_center,
)
from .types import (
    EntryJourneyRuntime,
    QueueReplanTargets,
    SoftReleaseTargets,
    StageAdvanceTargets,
    StageRegistry,
    WaypointBandChain,
)
from .waypoints import (
    add_region_flow_chain,
    add_registered_waypoint_band,
    add_waypoint_band_sequence,
    append_unique_stage,
    record_band_chain_advance,
    record_paired_stage_advance,
    record_queue_replan_options,
    record_region_flow_advance,
    record_stage_advance,
    set_band_chain_transitions,
    set_paired_stage_transitions,
    set_region_flow_transitions,
    transition_to_stage_set,
)


def add_continuous_entry_journeys(
    sim: jps.Simulation,
    native_queues: dict[str, NativeQueueRuntime],
    boarding_runtimes: list[NativeQueueRuntime],
    stage_registry: StageRegistry,
    geometry: Polygon,
    soft_release_targets: SoftReleaseTargets,
    stage_advance_targets: StageAdvanceTargets,
    queue_replan_targets: QueueReplanTargets,
) -> list[EntryJourneyRuntime]:
    entries: list[EntryJourneyRuntime] = []
    gate_runtimes = [
        native_queues[spec.name] for spec in sorted(GATE_QUEUE_SPECS, key=lambda item: item.head[0])
    ]
    elevator_weight = max(1, round(18 * ELEVATOR_CHOICE_SHARE))
    escalator_weight = max(1, 18 - elevator_weight)
    variants = (
        ("escalator", escalator_weight),
        ("elevator", elevator_weight),
    )
    for side in ("left", "right"):
        for lane in range(3):
            for variant, weight in variants:
                journey_id, first_stage_id = add_continuous_entry_journey(
                    sim=sim,
                    side=side,
                    lane=lane,
                    transfer_variant=variant,
                    gate_runtimes=entry_gate_runtimes_for_side(side, lane, gate_runtimes),
                    native_queues=native_queues,
                    boarding_runtimes=boarding_runtimes,
                    stage_registry=stage_registry,
                    geometry=geometry,
                    soft_release_targets=soft_release_targets,
                    stage_advance_targets=stage_advance_targets,
                    queue_replan_targets=queue_replan_targets,
                )
                entries.append(
                    EntryJourneyRuntime(
                        name=f"entry_{side}_lane_{lane + 1}_{variant}_continuous",
                        color="#2f89ff",
                        weight=weight,
                        start=entry_start_for_side(side, lane),
                        journey_id=journey_id,
                        first_stage_id=first_stage_id,
                    )
                )
    return entries


def add_continuous_entry_journey(
    sim: jps.Simulation,
    side: str,
    lane: int,
    transfer_variant: str,
    gate_runtimes: list[NativeQueueRuntime],
    native_queues: dict[str, NativeQueueRuntime],
    boarding_runtimes: list[NativeQueueRuntime],
    stage_registry: StageRegistry,
    geometry: Polygon,
    soft_release_targets: SoftReleaseTargets,
    stage_advance_targets: StageAdvanceTargets,
    queue_replan_targets: QueueReplanTargets,
) -> tuple[int, int]:
    stages: list[int] = []
    seen: set[int] = set()
    local_advance_targets: dict[int, tuple[int, ...]] = {}
    journey_name = f"entry.{side}.lane{lane + 1}.{transfer_variant}"

    approach_chain = add_waypoint_band_sequence(
        sim,
        entry_gate_decision_path(side, lane),
        geometry=geometry,
        final_radius_m=GATE_DECISION_RADIUS_M,
        radius_m=entry_gate_approach_radius(side),
        band_width_m=5.0 if side == "right" else 3.2,
        lanes=5 if side == "right" else 3,
        stage_registry=stage_registry,
        label_prefix=f"{journey_name}.gate_decision",
        journey=journey_name,
        band_start_index=1,
    )
    for stage_id in approach_chain.stage_ids:
        append_unique_stage(stages, seen, stage_id)

    gate_stage_ids = [runtime.stage_id for runtime in gate_runtimes]
    for stage_id in gate_stage_ids:
        append_unique_stage(stages, seen, stage_id)

    post_gate_stages: dict[int, tuple[int, ...]] = {}
    for runtime in gate_runtimes:
        if runtime.spec is None:
            continue
        gate_x, gate_y = runtime.spec.exit
        post_gate_band = add_registered_waypoint_band(
            sim,
            stage_registry,
            f"{journey_name}.post_gate.{runtime.name}",
            (gate_x, gate_y + 0.018),
            normal_hint=(1.0, 0.0),
            geometry=geometry,
            width_m=0.0,
            lanes=1,
            radius_m=post_gate_portal_radius(runtime),
            facility=runtime.name,
            journey=journey_name,
        )
        post_gate_stages[runtime.stage_id] = post_gate_band
        for stage_id in post_gate_band:
            append_unique_stage(stages, seen, stage_id)

    downstream_decision_center = (
        (0.700, 0.385)
        if transfer_variant == "elevator" and side == "right"
        else (0.625, 0.390)
        if side == "right"
        else (0.594, 0.386)
        if transfer_variant == "elevator"
        else (0.395, 0.398)
    )
    post_gate_corridor_band: tuple[int, ...] = ()
    post_gate_corridor_center: tuple[float, float] | None = None
    if side == "right":
        post_gate_corridor_center = right_entry_paid_corridor_center(
            gate_runtimes,
            downstream_decision_center,
        )
        post_gate_corridor_band = add_registered_waypoint_band(
            sim,
            stage_registry,
            f"{journey_name}.post_gate_corridor",
            post_gate_corridor_center,
            normal_hint=(1.0, 0.0),
            geometry=geometry,
            width_m=5.0,
            lanes=4,
            radius_m=RIGHT_ENTRY_CORRIDOR_RADIUS_M,
            journey=journey_name,
        )
        for stage_id in post_gate_corridor_band:
            append_unique_stage(stages, seen, stage_id)

    all_down_runtimes = [
        native_queues["down_escalator_1_queue"],
        native_queues["down_escalator_2_queue"],
    ]
    down_runtimes = (
        [native_queues["down_escalator_2_queue"]] if side == "right" else all_down_runtimes
    )
    elevator_runtime = native_queues["down_elevator_queue"]

    transfer_decision_band: tuple[int, ...] = ()
    vertical_capture_flow: WaypointBandChain | None = None
    transfer_exit_stages: dict[int, tuple[int, ...]] = {}
    elevator_approach_band: tuple[int, ...] = ()
    elevator_exit_stage: int | None = None
    elevator_lobby_stage: int | None = None

    if transfer_variant == "elevator":
        elevator_approach_band = add_registered_waypoint_band(
            sim,
            stage_registry,
            f"{journey_name}.elevator_approach",
            downstream_decision_center,
            normal_hint=(1.0, 0.0),
            geometry=geometry,
            width_m=4.6 if side == "right" else 5.4,
            lanes=4,
            radius_m=4.4 if side == "right" else 4.8,
            facility=elevator_runtime.name,
            journey=journey_name,
        )
        for stage_id in elevator_approach_band:
            append_unique_stage(stages, seen, stage_id)
        append_unique_stage(stages, seen, elevator_runtime.stage_id)
        if elevator_runtime.spec is not None:
            elevator_exit_stage = add_registered_waypoint_stage(
                sim,
                stage_registry,
                f"{journey_name}.elevator_exit",
                meters(elevator_runtime.spec.exit),
                ELEVATOR_LOBBY_RADIUS_M,
                facility=elevator_runtime.name,
                journey=journey_name,
            )
            elevator_lobby_stage = add_registered_waypoint_stage(
                sim,
                stage_registry,
                f"{journey_name}.elevator_lower_lobby",
                meters((0.560, 0.716)),
                ELEVATOR_LOBBY_RADIUS_M,
                facility=elevator_runtime.name,
                journey=journey_name,
            )
            append_unique_stage(stages, seen, elevator_exit_stage)
            append_unique_stage(stages, seen, elevator_lobby_stage)
    else:
        if (
            side == "right"
            and len(down_runtimes) == 1
            and down_runtimes[0].spec is not None
            and post_gate_corridor_center is not None
        ):
            plan = build_region_capture_flow(
                name=f"{journey_name}.vertical_capture",
                source=post_gate_corridor_center,
                queue_spec=down_runtimes[0].spec,
                queue_stage_id=down_runtimes[0].stage_id,
                capture_aprons=QUEUE_CAPTURE_APRONS_N,
                portal_count=2,
                width_m=5.2,
                lanes=4,
                approach_radius_m=3.0,
                capture_radius_m=3.6,
            )
            vertical_capture_flow = add_region_flow_chain(
                sim,
                stage_registry,
                plan,
                geometry=geometry,
                journey=journey_name,
            )
            for stage_id in vertical_capture_flow.stage_ids:
                append_unique_stage(stages, seen, stage_id)
        else:
            transfer_decision_band = add_registered_waypoint_band(
                sim,
                stage_registry,
                f"{journey_name}.down_transfer_decision",
                downstream_decision_center,
                normal_hint=(1.0, 0.0),
                geometry=geometry,
                width_m=6.0 if side == "right" else 7.0,
                lanes=5,
                radius_m=TRANSFER_DECISION_RADIUS_M,
                journey=journey_name,
            )
            for stage_id in transfer_decision_band:
                append_unique_stage(stages, seen, stage_id)
        for runtime in down_runtimes:
            append_unique_stage(stages, seen, runtime.stage_id)
            if runtime.spec is not None:
                head_x, head_y = runtime.spec.head
                exit_x, exit_y = runtime.spec.exit
                exit_stage = add_registered_waypoint_band(
                    sim,
                    stage_registry,
                    f"{journey_name}.transfer_exit.{runtime.name}",
                    runtime.spec.exit,
                    normal_hint=(exit_y - head_y, -(exit_x - head_x)),
                    geometry=geometry,
                    width_m=0.0,
                    lanes=1,
                    radius_m=EXIT_CORRIDOR_RADIUS_M * 1.35,
                    facility=runtime.name,
                    journey=journey_name,
                )
                transfer_exit_stages[runtime.stage_id] = exit_stage
                for stage_id in exit_stage:
                    append_unique_stage(stages, seen, stage_id)

    platform_defs = {
        "left": {
            "approach": [(0.180, 0.725), (0.260, 0.725), (0.330, 0.715)],
            "doors": [0, 1, 2],
        },
        "right": {
            "approach": [(0.590, 0.724), (0.670, 0.718), (0.735, 0.710)],
            "doors": [2, 3, 4, 5],
        },
    }
    platform_chains: dict[str, WaypointBandChain] = {}
    for platform_side, definition in platform_defs.items():
        branch_chain = add_waypoint_band_sequence(
            sim,
            list(definition["approach"]),
            geometry=geometry,
            final_radius_m=PLATFORM_DECISION_RADIUS_M,
            radius_m=PLATFORM_APPROACH_RADIUS_M,
            band_width_m=4.0,
            lanes=4,
            stage_registry=stage_registry,
            label_prefix=f"{journey_name}.platform_{platform_side}",
            journey=journey_name,
            band_start_index=1,
        )
        platform_chains[platform_side] = branch_chain
        for stage_id in branch_chain.stage_ids:
            append_unique_stage(stages, seen, stage_id)

    boarding_by_index = {index: runtime for index, runtime in enumerate(boarding_runtimes)}
    boarding_door_paths: dict[int, tuple[int, int, int]] = {}
    for index, runtime in boarding_by_index.items():
        door_x = float(STATION_LAYOUT.control_points["platform_doors"][index][0])
        doorway_stage = add_registered_waypoint_stage(
            sim,
            stage_registry,
            f"{journey_name}.{runtime.name}.screen_door",
            meters((door_x, BOARDING_SCREEN_DOOR_Y)),
            BOARDING_SCREEN_DOOR_RADIUS_M,
            facility=runtime.name,
            journey=journey_name,
        )
        vestibule_stage = add_registered_waypoint_stage(
            sim,
            stage_registry,
            f"{journey_name}.{runtime.name}.vestibule",
            meters((door_x, BOARDING_VESTIBULE_Y)),
            BOARDING_VESTIBULE_RADIUS_M,
            facility=runtime.name,
            journey=journey_name,
        )
        exit_stage = add_registered_exit_stage(
            sim,
            stage_registry,
            f"{journey_name}.{runtime.name}.train_exit",
            meters((door_x, BOARDING_EXIT_Y)),
            BOARDING_TRAIN_EXIT_HALF_SIZE_M,
            facility=runtime.name,
            journey=journey_name,
        )
        boarding_door_paths[runtime.stage_id] = (doorway_stage, vestibule_stage, exit_stage)
        append_unique_stage(stages, seen, runtime.stage_id)
        append_unique_stage(stages, seen, doorway_stage)
        append_unique_stage(stages, seen, vestibule_stage)
        append_unique_stage(stages, seen, exit_stage)

    journey = jps.JourneyDescription(stages)
    set_band_chain_transitions(journey, approach_chain)
    gate_transition = transition_to_stage_set(gate_stage_ids)
    for stage_id in approach_chain.last_band:
        journey.set_transition_for_stage(stage_id, gate_transition)

    if transfer_variant == "elevator":
        assert elevator_approach_band
        post_gate_next_transition = (
            transition_to_stage_set(post_gate_corridor_band)
            if post_gate_corridor_band
            else transition_to_stage_set(elevator_approach_band)
        )
        for gate_stage, post_gate_band in post_gate_stages.items():
            journey.set_transition_for_stage(
                gate_stage,
                transition_to_stage_set(post_gate_band),
            )
            for post_gate_stage in post_gate_band:
                journey.set_transition_for_stage(
                    post_gate_stage,
                    post_gate_next_transition,
                )
        for corridor_stage in post_gate_corridor_band:
            journey.set_transition_for_stage(
                corridor_stage,
                transition_to_stage_set(elevator_approach_band),
            )
        for stage_id in elevator_approach_band:
            journey.set_transition_for_stage(
                stage_id,
                jps.Transition.create_fixed_transition(elevator_runtime.stage_id),
            )
        if elevator_exit_stage is not None and elevator_lobby_stage is not None:
            journey.set_transition_for_stage(
                elevator_runtime.stage_id,
                jps.Transition.create_fixed_transition(elevator_exit_stage),
            )
            journey.set_transition_for_stage(
                elevator_exit_stage,
                jps.Transition.create_fixed_transition(elevator_lobby_stage),
            )
            journey.set_transition_for_stage(
                elevator_lobby_stage,
                transition_to_stage_set(platform_chains["right"].first_band),
            )
    else:
        assert transfer_decision_band or vertical_capture_flow is not None
        transfer_entry_band = (
            vertical_capture_flow.first_band
            if vertical_capture_flow is not None
            else transfer_decision_band
        )
        post_gate_next_transition = (
            transition_to_stage_set(post_gate_corridor_band)
            if post_gate_corridor_band
            else transition_to_stage_set(transfer_entry_band)
        )
        for gate_stage, post_gate_band in post_gate_stages.items():
            journey.set_transition_for_stage(
                gate_stage,
                transition_to_stage_set(post_gate_band),
            )
            for post_gate_stage in post_gate_band:
                journey.set_transition_for_stage(
                    post_gate_stage,
                    post_gate_next_transition,
                )
        if vertical_capture_flow is not None:
            set_paired_stage_transitions(
                journey,
                post_gate_corridor_band,
                vertical_capture_flow.first_band,
                stage_registry,
            )
            set_region_flow_transitions(journey, vertical_capture_flow, stage_registry)
        else:
            for corridor_stage in post_gate_corridor_band:
                journey.set_transition_for_stage(
                    corridor_stage,
                    transition_to_stage_set(transfer_decision_band),
                )
        down_transition = transition_to_stage_set([runtime.stage_id for runtime in down_runtimes])
        for stage_id in (
            vertical_capture_flow.last_band
            if vertical_capture_flow is not None
            else transfer_decision_band
        ):
            journey.set_transition_for_stage(stage_id, down_transition)
        for runtime in down_runtimes:
            exit_band = transfer_exit_stages[runtime.stage_id]
            platform_side = "left" if runtime.name == "down_escalator_1_queue" else "right"
            journey.set_transition_for_stage(
                runtime.stage_id,
                transition_to_stage_set(exit_band),
            )
            for exit_stage in exit_band:
                journey.set_transition_for_stage(
                    exit_stage,
                    transition_to_stage_set(platform_chains[platform_side].first_band),
                )

    for platform_side, branch_chain in platform_chains.items():
        set_band_chain_transitions(journey, branch_chain)
        door_indices = [
            index for index in platform_defs[platform_side]["doors"] if index in boarding_by_index
        ]
        door_transition = transition_to_stage_set(
            [boarding_by_index[index].stage_id for index in door_indices]
        )
        for stage_id in branch_chain.last_band:
            journey.set_transition_for_stage(stage_id, door_transition)

    for queue_stage, (doorway_stage, vestibule_stage, exit_stage) in boarding_door_paths.items():
        journey.set_transition_for_stage(
            queue_stage,
            jps.Transition.create_fixed_transition(doorway_stage),
        )
        journey.set_transition_for_stage(
            doorway_stage,
            jps.Transition.create_fixed_transition(vestibule_stage),
        )
        journey.set_transition_for_stage(
            vestibule_stage,
            jps.Transition.create_fixed_transition(exit_stage),
        )

    journey_id = sim.add_journey(journey)
    record_queue_replan_options(queue_replan_targets, journey_id, gate_stage_ids)
    if transfer_variant != "elevator":
        record_queue_replan_options(
            queue_replan_targets,
            journey_id,
            [runtime.stage_id for runtime in down_runtimes],
        )
    for platform_side, definition in platform_defs.items():
        door_stage_ids = [
            boarding_by_index[index].stage_id
            for index in definition["doors"]
            if index in boarding_by_index
        ]
        record_queue_replan_options(queue_replan_targets, journey_id, door_stage_ids)
    record_band_chain_advance(local_advance_targets, approach_chain)
    record_stage_advance(local_advance_targets, approach_chain.last_band, gate_stage_ids)
    for gate_stage, post_gate_band in post_gate_stages.items():
        soft_release_targets[(gate_stage, journey_id)] = tuple(post_gate_band)
        record_stage_advance(local_advance_targets, (gate_stage,), post_gate_band)
    if transfer_variant == "elevator":
        if elevator_exit_stage is not None:
            soft_release_targets[(elevator_runtime.stage_id, journey_id)] = (elevator_exit_stage,)
            record_stage_advance(
                local_advance_targets, (elevator_runtime.stage_id,), (elevator_exit_stage,)
            )
        if elevator_approach_band:
            record_stage_advance(
                local_advance_targets, elevator_approach_band, (elevator_runtime.stage_id,)
            )
        if elevator_exit_stage is not None and elevator_lobby_stage is not None:
            record_stage_advance(
                local_advance_targets, (elevator_exit_stage,), (elevator_lobby_stage,)
            )
            record_stage_advance(
                local_advance_targets, (elevator_lobby_stage,), platform_chains["right"].first_band
            )
        for post_gate_band in post_gate_stages.values():
            if elevator_approach_band:
                record_stage_advance(
                    local_advance_targets,
                    post_gate_band,
                    post_gate_corridor_band or elevator_approach_band,
                )
        if post_gate_corridor_band and elevator_approach_band:
            record_stage_advance(
                local_advance_targets,
                post_gate_corridor_band,
                elevator_approach_band,
            )
    else:
        transfer_entry_band = (
            vertical_capture_flow.first_band
            if vertical_capture_flow is not None
            else transfer_decision_band
        )
        record_stage_advance(
            local_advance_targets,
            tuple(stage_id for band in post_gate_stages.values() for stage_id in band),
            post_gate_corridor_band or transfer_entry_band,
        )
        if post_gate_corridor_band and vertical_capture_flow is not None:
            record_paired_stage_advance(
                local_advance_targets,
                post_gate_corridor_band,
                vertical_capture_flow.first_band,
                stage_registry,
            )
        elif post_gate_corridor_band:
            record_stage_advance(
                local_advance_targets,
                post_gate_corridor_band,
                transfer_decision_band,
            )
        if vertical_capture_flow is not None:
            record_region_flow_advance(local_advance_targets, vertical_capture_flow, stage_registry)
        record_stage_advance(
            local_advance_targets,
            vertical_capture_flow.last_band
            if vertical_capture_flow is not None
            else transfer_decision_band,
            [runtime.stage_id for runtime in down_runtimes],
        )
        for runtime in down_runtimes:
            exit_band = transfer_exit_stages[runtime.stage_id]
            soft_release_targets[(runtime.stage_id, journey_id)] = tuple(exit_band)
            record_stage_advance(
                local_advance_targets,
                (runtime.stage_id,),
                exit_band,
            )
            platform_side = "left" if runtime.name == "down_escalator_1_queue" else "right"
            record_stage_advance(
                local_advance_targets,
                exit_band,
                platform_chains[platform_side].first_band,
            )
    for chain in platform_chains.values():
        record_band_chain_advance(local_advance_targets, chain)
    for queue_stage, (doorway_stage, _vestibule_stage, _exit_stage) in boarding_door_paths.items():
        soft_release_targets[(queue_stage, journey_id)] = (doorway_stage,)
        record_stage_advance(local_advance_targets, (queue_stage,), (doorway_stage,))
        record_stage_advance(local_advance_targets, (doorway_stage,), (_vestibule_stage,))
        record_stage_advance(local_advance_targets, (_vestibule_stage,), (_exit_stage,))
    for platform_side, branch_chain in platform_chains.items():
        door_indices = [
            index for index in platform_defs[platform_side]["doors"] if index in boarding_by_index
        ]
        record_stage_advance(
            local_advance_targets,
            branch_chain.last_band,
            [boarding_by_index[index].stage_id for index in door_indices],
        )
    for stage_id, targets in local_advance_targets.items():
        stage_advance_targets[(stage_id, journey_id)] = targets
    return journey_id, approach_chain.first_stage_id
