from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.design.station_generation import generate_station
from metro_station.adapters.simulation.design.validation import validate_design
from metro_station.adapters.simulation.station.graph import StationGraph
from metro_station_testkit.layout_transforms import mirror_design_horizontally
from metro_station_testkit.metamorphic_projection import canonical_topology_projection

from .metamorphic_artifacts import MetamorphicArtifacts


def run_sensitivity_injection(
    baseline: MetamorphicArtifacts,
    injection: str,
    *,
    seed: int,
) -> tuple[bool, str, str]:
    if injection == "I1-DELETE-EDGE":
        return _delete_edge_detected(baseline)
    if injection == "I2-WRONG-RUNTIME-BINDING":
        return _wrong_runtime_binding_detected(baseline)
    if injection == "I3-DELETE-ASSET-BINDING":
        return _missing_asset_binding_detected(baseline)
    if injection == "I4-WRONG-QUEUE-OWNER":
        return _wrong_queue_owner_detected(baseline, seed)
    if injection == "I5-PARTIAL-MIRROR":
        return _partial_mirror_detected(baseline, seed)
    raise ValueError(f"unknown sensitivity injection {injection!r}")


def _delete_edge_detected(baseline: MetamorphicArtifacts) -> tuple[bool, str, str]:
    before = canonical_topology_projection(baseline.graph)
    for index in range(len(baseline.document.connections)):
        connections = (
            baseline.document.connections[:index] + baseline.document.connections[index + 1 :]
        )
        mutated = replace(baseline.document, connections=connections)
        after = canonical_topology_projection(StationGraph.from_design(mutated))
        if after != before:
            return True, "topology", "sensitivity.i1-delete-edge"
    return False, "topology", "sensitivity.i1-delete-edge"


def _wrong_runtime_binding_detected(
    baseline: MetamorphicArtifacts,
) -> tuple[bool, str, str]:
    elevator_entities = [item for item in baseline.scene.entities if item.kind == "elevator"]
    elevator_bindings = [
        item for item in baseline.scene.runtime_bindings if item.kind == "elevator"
    ]
    if len(elevator_entities) < 2 or not elevator_bindings:
        return False, "replay", "sensitivity.i2-wrong-runtime-binding"
    binding = elevator_bindings[0]
    wrong = next(
        entity for entity in elevator_entities if entity.entity_id != binding.scene_entity_id
    )
    mutated = replace(binding, scene_entity_id=wrong.entity_id)
    expected_source = next(
        entity.source_element_id
        for entity in elevator_entities
        if entity.entity_id == binding.scene_entity_id
    )
    detected = (
        wrong.source_element_id != expected_source
        and mutated.scene_entity_id != binding.scene_entity_id
    )
    return detected, "replay", "sensitivity.i2-wrong-runtime-binding"


def _missing_asset_binding_detected(
    baseline: MetamorphicArtifacts,
) -> tuple[bool, str, str]:
    remaining = baseline.manifest.bindings[1:]
    entity_ids = {entity.entity_id for entity in baseline.scene.entities}
    detected = {item.scene_entity_id for item in remaining} != entity_ids
    return detected, "asset", "sensitivity.i3-delete-asset-binding"


def _wrong_queue_owner_detected(
    baseline: MetamorphicArtifacts,
    seed: int,
) -> tuple[bool, str, str]:
    queue = baseline.document.queues[0]
    wrong_owner = next(
        element.id
        for element in baseline.document.elements
        if element.id != queue.owner_element_id and element.role == "floor"
    )
    mutated_queue = replace(queue, owner_element_id=wrong_owner)
    mutated = replace(
        baseline.document,
        queues=(mutated_queue, *baseline.document.queues[1:]),
    )
    issues = validate_design(mutated)
    detected = bool(issues) or _queue_owner_signature(mutated) != _queue_owner_signature(
        baseline.document
    )
    return detected, "design", "sensitivity.i4-wrong-queue-owner"


def _partial_mirror_detected(
    baseline: MetamorphicArtifacts,
    seed: int,
) -> tuple[bool, str, str]:
    mirrored = mirror_design_horizontally(baseline.document)
    partial = replace(mirrored, queues=baseline.document.queues)
    full = generate_station(replace(mirrored, queues=()))
    detected = _queue_geometry_signature(partial) != _queue_geometry_signature(full)
    return detected, "geometry", "sensitivity.i5-partial-mirror"


def _queue_owner_signature(document: StationDesignDocument) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((queue.id, queue.owner_element_id) for queue in document.queues))


def _queue_geometry_signature(document: StationDesignDocument) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                queue.id,
                queue.geometry.x_m,
                queue.geometry.y_m,
                queue.service_point_m,
            )
            for queue in document.queues
        )
    )
