"""Compile design and runtime facilities into a renderer-neutral replay scene."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any, Iterable

from metro_station.application.replay import (
    AssetBinding,
    AssetDescriptor,
    AssetManifest,
    RuntimeSceneBinding,
    SceneEntity,
    SceneLevel,
    SceneRelation,
    StationScene,
)

from ..station.payload import geometry_payload
from ..station.scenario import StationSandboxScenario


def compile_station_scene(
    scenario: StationSandboxScenario,
    facilities: Iterable[Any] | None,
) -> StationScene:
    """Compile physical entities and runtime-to-physical bindings for replay."""
    specs = _facility_specs(facilities)
    raw_geometry = geometry_payload(scenario)
    if scenario.station_design is None:
        return _legacy_station_scene(scenario, raw_geometry, specs)

    document = scenario.station_design
    runtime_levels = _runtime_levels_by_source(specs)
    levels = tuple(
        SceneLevel(
            level_id=str(item["id"]),
            label=str(item.get("label", item["id"])),
            elevation=float(item.get("elevation_m", 0.0)),
            footprint=tuple(_point(point) for point in item.get("footprint", ())),
            metadata={"order": item.get("order")},
        )
        for item in raw_geometry.get("levels", ())
    )
    entities = [_element_entity(item, runtime_levels) for item in raw_geometry.get("elements", ())]
    element_levels = {
        entity.source_element_id: entity.level_ids
        for entity in entities
        if entity.source_element_id is not None
    }
    entities.extend(
        _queue_entity(item, element_levels) for item in raw_geometry.get("queues", ())
    )
    relations = _scene_relations(raw_geometry)
    bindings, fallback_entities = _runtime_bindings(specs, {item.entity_id for item in entities})
    entities.extend(fallback_entities)
    return StationScene(
        scene_id=f"station-scene:{document.id}",
        source_design_id=document.id,
        coordinate_system={
            "units": document.units,
            "origin": "top_left",
            "x_axis": "right",
            "y_axis": "down",
            "width": float(raw_geometry.get("width", 0.0)),
            "height": float(raw_geometry.get("height", 0.0)),
        },
        levels=levels,
        entities=tuple(entities),
        relations=tuple(relations),
        runtime_bindings=tuple(bindings),
        topology={
            "nodes": deepcopy(raw_geometry.get("graph_nodes", [])),
            "edges": deepcopy(raw_geometry.get("graph_edges", [])),
            "diagnostics": deepcopy(raw_geometry.get("graph_diagnostics", [])),
        },
        metadata={
            "source": raw_geometry.get("source"),
            "station_name": scenario.station_name,
            "template_id": document.template_id,
        },
    )


def compile_procedural_asset_manifest(scene: StationScene) -> AssetManifest:
    """Bind each semantic entity kind to a reusable procedural placeholder asset."""
    semantic_kinds = sorted({entity.kind for entity in scene.entities})
    assets = tuple(
        AssetDescriptor(
            asset_id=f"procedural:{kind}:v1",
            asset_kind="procedural_placeholder",
            semantic_kind=kind,
            anchors={"origin": "geometry_center", "scale_mode": "fit_geometry"},
            metadata={"render_policy": "renderer_generated", "binary_asset_required": False},
        )
        for kind in semantic_kinds
    )
    bindings = tuple(
        AssetBinding(
            binding_id=f"asset-binding:{entity.entity_id}",
            scene_entity_id=entity.entity_id,
            asset_id=f"procedural:{entity.kind}:v1",
            placement={
                "mode": "fit_geometry",
                "geometry": deepcopy(dict(entity.geometry)),
                "level_ids": list(entity.level_ids),
            },
        )
        for entity in scene.entities
    )
    return AssetManifest(
        assets=assets,
        bindings=bindings,
        metadata={"fallback_policy": "procedural_by_semantic_kind"},
    )


def _element_entity(
    item: dict[str, Any],
    runtime_levels: dict[str, set[str]],
) -> SceneEntity:
    source_id = str(item["id"])
    level_ids = {str(item["level_id"])} if item.get("level_id") else set()
    level_ids.update(runtime_levels.get(source_id, set()))
    properties = {
        key: deepcopy(item.get(key))
        for key in ("role", "gate_direction", "direction", "line_id", "ports")
        if item.get(key) is not None
    }
    return SceneEntity(
        entity_id=f"element:{source_id}",
        source_element_id=source_id,
        kind=str(item["kind"]),
        label=str(item.get("label", source_id)),
        geometry=deepcopy(dict(item.get("geometry", {}))),
        level_ids=tuple(sorted(level_ids)),
        properties=properties,
        metadata=deepcopy(dict(item.get("metadata", {}))),
    )


def _queue_entity(
    item: dict[str, Any],
    element_levels: dict[str, tuple[str, ...]],
) -> SceneEntity:
    queue_id = str(item["id"])
    owner_id = str(item["owner_element_id"])
    return SceneEntity(
        entity_id=f"queue:{queue_id}",
        kind=f"queue:{item.get('kind', 'generic')}",
        label=str(item.get("label", queue_id)),
        geometry=deepcopy(dict(item.get("geometry", {}))),
        level_ids=element_levels.get(owner_id, ()),
        properties={
            "owner_element_id": owner_id,
            "service_point": deepcopy(item.get("service_point_m")),
        },
    )


def _scene_relations(raw_geometry: dict[str, Any]) -> list[SceneRelation]:
    relations = [
        SceneRelation(
            relation_id=f"connection:{item['id']}",
            relation_type=str(item.get("kind", "connects")),
            source_entity_id=f"element:{item['source_id']}",
            target_entity_id=f"element:{item['target_id']}",
            metadata={
                "bidirectional": bool(item.get("bidirectional", False)),
                "source_port_id": item.get("source_port_id"),
                "target_port_id": item.get("target_port_id"),
            },
        )
        for item in raw_geometry.get("connections", ())
    ]
    relations.extend(
        SceneRelation(
            relation_id=f"queue-owner:{item['id']}",
            relation_type="queue_for",
            source_entity_id=f"queue:{item['id']}",
            target_entity_id=f"element:{item['owner_element_id']}",
        )
        for item in raw_geometry.get("queues", ())
    )
    return relations


def _runtime_bindings(
    specs: tuple[Any, ...],
    known_entity_ids: set[str],
) -> tuple[list[RuntimeSceneBinding], list[SceneEntity]]:
    bindings: list[RuntimeSceneBinding] = []
    fallback_entities: list[SceneEntity] = []
    for spec in specs:
        source_id = _source_element_id(spec)
        entity_id = f"element:{source_id}" if source_id else f"runtime:{spec.facility_id}"
        if entity_id not in known_entity_ids:
            fallback_entities.append(_runtime_entity(spec, entity_id, source_id))
            known_entity_ids.add(entity_id)
        bindings.append(
            RuntimeSceneBinding(
                runtime_id=str(spec.facility_id),
                scene_entity_id=entity_id,
                kind=str(spec.kind),
                stage=str(spec.stage),
                direction=str(spec.direction) if getattr(spec, "direction", None) else None,
                entry_level_id=getattr(spec, "entry_level_id", None),
                exit_level_id=getattr(spec, "exit_level_id", None),
                position=_point(spec.position),
                exit_position=_point(spec.exit_position),
                queue_anchor=_point(spec.queue_anchor),
                metadata={
                    "label": str(spec.label),
                    "line_id": getattr(spec, "line_id", None),
                    "platform_id": getattr(spec, "platform_id", None),
                },
            )
        )
    return bindings, fallback_entities


def _runtime_entity(
    spec: Any,
    entity_id: str,
    source_element_id: str | None,
) -> SceneEntity:
    levels = tuple(
        sorted(
            {
                str(level_id)
                for level_id in (spec.entry_level_id, spec.exit_level_id)
                if level_id is not None
            }
        )
    )
    return SceneEntity(
        entity_id=entity_id,
        source_element_id=source_element_id,
        kind=str(spec.kind),
        label=str(spec.label),
        geometry={"shape": "point", "position": list(_point(spec.position))},
        level_ids=levels,
        metadata={"fallback": True, "runtime_generated": True},
    )


def _legacy_station_scene(
    scenario: StationSandboxScenario,
    raw_geometry: dict[str, Any],
    specs: tuple[Any, ...],
) -> StationScene:
    level_ids = sorted(
        {
            str(level_id)
            for spec in specs
            for level_id in (spec.entry_level_id, spec.exit_level_id)
            if level_id is not None
        }
    ) or ["legacy"]
    levels = tuple(SceneLevel(level_id=item, label=item) for item in level_ids)
    bindings, entities = _runtime_bindings(specs, set())
    return StationScene(
        scene_id=f"station-scene:legacy:{scenario.station_name}",
        source_design_id=f"legacy:{scenario.station_name}",
        coordinate_system={
            "units": "simulation_units",
            "origin": "top_left",
            "x_axis": "right",
            "y_axis": "down",
            "width": float(raw_geometry.get("width", 0.0)),
            "height": float(raw_geometry.get("height", 0.0)),
        },
        levels=levels,
        entities=tuple(entities),
        runtime_bindings=tuple(bindings),
        metadata={"source": raw_geometry.get("source"), "compatibility_mode": "legacy"},
    )


def _facility_specs(facilities: Iterable[Any] | None) -> tuple[Any, ...]:
    if facilities is None:
        return ()
    return tuple(getattr(item, "spec", item) for item in facilities)


def _runtime_levels_by_source(specs: tuple[Any, ...]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for spec in specs:
        source_id = _source_element_id(spec)
        if source_id is None:
            continue
        for level_id in (spec.entry_level_id, spec.exit_level_id):
            if level_id is not None:
                result[source_id].add(str(level_id))
    return result


def _source_element_id(spec: Any) -> str | None:
    explicit = getattr(spec, "source_element_id", None)
    if explicit:
        return str(explicit)
    parts = str(spec.facility_id).split(":")
    return parts[1] if len(parts) > 1 else None


def _point(value: Any) -> tuple[float, float]:
    return float(value[0]), float(value[1])
