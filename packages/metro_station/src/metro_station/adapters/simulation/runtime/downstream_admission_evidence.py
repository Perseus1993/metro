from __future__ import annotations

from typing import Any

from ..planning.goal_graph import GoalNodeKind
from ..planning.plan import AgentIntent


def downstream_admission_evidence(
    model: Any,
    intent: str,
    *,
    release_levels: set[str],
) -> dict[str, object]:
    """Describe concrete first-stage storage available to source publication."""

    graph = model.goal_graph_catalog.graph_for_intent(str(intent))
    first_facility_node = next(
        (
            node
            for node in graph.nodes
            if node.kind == GoalNodeKind.USE_FACILITY_STAGE.value
            and node.facility_stage is not None
        ),
        None,
    )
    stage = None if first_facility_node is None else first_facility_node.facility_stage
    decision_region_id = (
        None if first_facility_node is None else first_facility_node.decision_region_id
    )
    facilities = [] if stage is None else model._facilities_for_stage(stage)
    physical = [
        facility
        for facility in facilities
        if model.facility_portal_binding(facility.facility_id).entry_level_id in release_levels
    ]
    eligible = [
        facility
        for facility in physical
        if not bool(getattr(facility, "is_forced_disabled", False))
    ]
    available_slots = sum(
        len(model._available_facility_approach_slot_indices(facility))
        for facility in eligible
        if facility.is_available_for_choice
    )
    certified_approach_slots = sum(
        len(model._facility_approach_slot_indices(facility)) for facility in eligible
    )
    anchors_by_level: dict[str, list[tuple[float, float]]] = {
        level_id: [] for level_id in release_levels
    }
    for facility in eligible:
        binding = model.facility_portal_binding(facility.facility_id)
        if binding.entry_level_id in anchors_by_level:
            anchors_by_level[binding.entry_level_id].extend(
                model._facility_approach_positions(facility)
            )
    available_holding_points: tuple[tuple[float, float], ...] = ()
    available_holding_slots = 0
    certified_holding_slots = 0
    additional_region_ids = model._decision_holding_upstream_region_ids(
        str(intent),
        str(decision_region_id),
    )
    if decision_region_id is not None:
        available_holding_points = tuple(
            point
            for level_id, anchors in anchors_by_level.items()
            if anchors
            for point in model._available_decision_holding_slots(
                level_id=level_id,
                region_id=decision_region_id,
                anchors=tuple(anchors),
                additional_region_ids=additional_region_ids,
            )
        )
        available_holding_slots = len(available_holding_points)
    available_platform_staging_slots = 0
    certified_platform_staging_slots = 0
    if eligible:
        certified_holding_slots = sum(
            len(
                model._decision_holding_candidates(
                    level_id,
                    region_id=decision_region_id,
                    anchors=tuple(anchors),
                    additional_region_ids=additional_region_ids,
                )
            )
            for level_id, anchors in anchors_by_level.items()
            if anchors
        )
    if eligible and str(intent) == AgentIntent.EXIT_STATION.value:
        available_platform_staging_slots = sum(
            model._available_platform_waiting_slot_count(
                level_id=level_id,
                limit=1,
            )
            for level_id in release_levels
        )
        certified_platform_staging_slots = len(tuple(model.layout_graph.platform_waiting_slots()))
    if str(intent) == AgentIntent.EXIT_STATION.value:
        available_total = available_slots + available_platform_staging_slots
        certified_total = certified_approach_slots + certified_platform_staging_slots
    else:
        available_total = available_slots
        certified_total = certified_approach_slots
    return {
        "available": available_total > 0,
        "downstream_stage": stage,
        "decision_region_id": decision_region_id,
        "release_level_ids": sorted(release_levels),
        "eligible_facility_count": len(eligible),
        "available_approach_slots": available_slots,
        "available_holding_slots": available_holding_slots,
        "available_holding_position": (
            available_holding_points[0] if available_holding_points else None
        ),
        "certified_holding_slots": certified_holding_slots,
        "available_platform_staging_slots": available_platform_staging_slots,
        "certified_platform_staging_slots": certified_platform_staging_slots,
        "certified_downstream_slots": certified_total,
        "occupied_downstream_slots": max(0, certified_total - available_total),
    }


__all__ = ["downstream_admission_evidence"]
