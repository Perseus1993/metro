"""Versioned, renderer-neutral station scene contract."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from metro_station.application.semantic_fingerprints import semantic_fingerprint


STATION_SCENE_SCHEMA_VERSION = "station_scene.v1"


def _point(payload: object) -> tuple[float, float] | None:
    if payload is None:
        return None
    values = tuple(payload)  # type: ignore[arg-type]
    if len(values) != 2:
        raise ValueError("scene point must contain exactly two coordinates")
    return float(values[0]), float(values[1])


@dataclass(frozen=True)
class SceneLevel:
    level_id: str
    label: str
    elevation: float = 0.0
    footprint: tuple[tuple[float, float], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "level_id": self.level_id,
            "label": self.label,
            "elevation": self.elevation,
            "footprint": [list(point) for point in self.footprint],
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SceneLevel:
        return cls(
            level_id=str(payload["level_id"]),
            label=str(payload.get("label", payload["level_id"])),
            elevation=float(payload.get("elevation", 0.0)),
            footprint=tuple(_point(point) for point in payload.get("footprint", ())),  # type: ignore[arg-type]
            metadata=deepcopy(dict(payload.get("metadata", {}))),
        )


@dataclass(frozen=True)
class SceneEntity:
    entity_id: str
    kind: str
    label: str
    geometry: Mapping[str, Any]
    level_ids: tuple[str, ...] = ()
    source_element_id: str | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "kind": self.kind,
            "label": self.label,
            "geometry": deepcopy(dict(self.geometry)),
            "level_ids": list(self.level_ids),
            "source_element_id": self.source_element_id,
            "properties": deepcopy(dict(self.properties)),
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SceneEntity:
        return cls(
            entity_id=str(payload["entity_id"]),
            kind=str(payload["kind"]),
            label=str(payload.get("label", payload["entity_id"])),
            geometry=deepcopy(dict(payload.get("geometry", {}))),
            level_ids=tuple(str(value) for value in payload.get("level_ids", ())),
            source_element_id=(
                str(payload["source_element_id"])
                if payload.get("source_element_id") is not None
                else None
            ),
            properties=deepcopy(dict(payload.get("properties", {}))),
            metadata=deepcopy(dict(payload.get("metadata", {}))),
        )


@dataclass(frozen=True)
class SceneRelation:
    relation_id: str
    relation_type: str
    source_entity_id: str
    target_entity_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "relation_type": self.relation_type,
            "source_entity_id": self.source_entity_id,
            "target_entity_id": self.target_entity_id,
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SceneRelation:
        return cls(
            relation_id=str(payload["relation_id"]),
            relation_type=str(payload["relation_type"]),
            source_entity_id=str(payload["source_entity_id"]),
            target_entity_id=str(payload["target_entity_id"]),
            metadata=deepcopy(dict(payload.get("metadata", {}))),
        )


@dataclass(frozen=True)
class RuntimeSceneBinding:
    runtime_id: str
    scene_entity_id: str
    kind: str
    stage: str
    direction: str | None = None
    entry_level_id: str | None = None
    exit_level_id: str | None = None
    position: tuple[float, float] | None = None
    exit_position: tuple[float, float] | None = None
    queue_anchor: tuple[float, float] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtime_id": self.runtime_id,
            "scene_entity_id": self.scene_entity_id,
            "kind": self.kind,
            "stage": self.stage,
            "direction": self.direction,
            "entry_level_id": self.entry_level_id,
            "exit_level_id": self.exit_level_id,
            "position": list(self.position) if self.position is not None else None,
            "exit_position": (
                list(self.exit_position) if self.exit_position is not None else None
            ),
            "queue_anchor": list(self.queue_anchor) if self.queue_anchor is not None else None,
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RuntimeSceneBinding:
        return cls(
            runtime_id=str(payload["runtime_id"]),
            scene_entity_id=str(payload["scene_entity_id"]),
            kind=str(payload["kind"]),
            stage=str(payload["stage"]),
            direction=str(payload["direction"]) if payload.get("direction") else None,
            entry_level_id=(
                str(payload["entry_level_id"])
                if payload.get("entry_level_id") is not None
                else None
            ),
            exit_level_id=(
                str(payload["exit_level_id"])
                if payload.get("exit_level_id") is not None
                else None
            ),
            position=_point(payload.get("position")),
            exit_position=_point(payload.get("exit_position")),
            queue_anchor=_point(payload.get("queue_anchor")),
            metadata=deepcopy(dict(payload.get("metadata", {}))),
        )


@dataclass(frozen=True)
class StationScene:
    scene_id: str
    source_design_id: str
    coordinate_system: Mapping[str, Any]
    levels: tuple[SceneLevel, ...]
    entities: tuple[SceneEntity, ...]
    relations: tuple[SceneRelation, ...] = ()
    runtime_bindings: tuple[RuntimeSceneBinding, ...] = ()
    topology: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = STATION_SCENE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != STATION_SCENE_SCHEMA_VERSION:
            raise ValueError(f"unsupported station scene schema: {self.schema_version}")
        level_ids = _unique_ids("level", (level.level_id for level in self.levels))
        entity_ids = _unique_ids("entity", (entity.entity_id for entity in self.entities))
        _unique_ids("relation", (relation.relation_id for relation in self.relations))
        _unique_ids("runtime binding", (item.runtime_id for item in self.runtime_bindings))
        for entity in self.entities:
            unknown_levels = set(entity.level_ids) - level_ids
            if unknown_levels:
                raise ValueError(f"entity {entity.entity_id} references unknown levels {unknown_levels}")
        for relation in self.relations:
            if relation.source_entity_id not in entity_ids or relation.target_entity_id not in entity_ids:
                raise ValueError(f"relation {relation.relation_id} references an unknown entity")
        for binding in self.runtime_bindings:
            if binding.scene_entity_id not in entity_ids:
                raise ValueError(f"runtime binding {binding.runtime_id} references an unknown entity")

    @property
    def semantic_fingerprint(self) -> str:
        return semantic_fingerprint(self._semantic_payload())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scene_id": self.scene_id,
            "source_design_id": self.source_design_id,
            "semantic_fingerprint": self.semantic_fingerprint,
            "coordinate_system": deepcopy(dict(self.coordinate_system)),
            "levels": [level.as_dict() for level in self.levels],
            "entities": [entity.as_dict() for entity in self.entities],
            "relations": [relation.as_dict() for relation in self.relations],
            "runtime_bindings": [binding.as_dict() for binding in self.runtime_bindings],
            "topology": deepcopy(dict(self.topology)),
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StationScene:
        scene = cls(
            schema_version=str(payload.get("schema_version", "")),
            scene_id=str(payload["scene_id"]),
            source_design_id=str(payload["source_design_id"]),
            coordinate_system=deepcopy(dict(payload.get("coordinate_system", {}))),
            levels=tuple(SceneLevel.from_dict(item) for item in payload.get("levels", ())),
            entities=tuple(SceneEntity.from_dict(item) for item in payload.get("entities", ())),
            relations=tuple(SceneRelation.from_dict(item) for item in payload.get("relations", ())),
            runtime_bindings=tuple(
                RuntimeSceneBinding.from_dict(item) for item in payload.get("runtime_bindings", ())
            ),
            topology=deepcopy(dict(payload.get("topology", {}))),
            metadata=deepcopy(dict(payload.get("metadata", {}))),
        )
        expected = payload.get("semantic_fingerprint")
        if expected is not None and str(expected) != scene.semantic_fingerprint:
            raise ValueError("station scene semantic fingerprint mismatch")
        return scene

    def _semantic_payload(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "source_design_id": self.source_design_id,
            "coordinate_system": deepcopy(dict(self.coordinate_system)),
            "levels": [level.as_dict() for level in self.levels],
            "entities": [entity.as_dict() for entity in self.entities],
            "relations": [relation.as_dict() for relation in self.relations],
            "runtime_bindings": [binding.as_dict() for binding in self.runtime_bindings],
            "topology": deepcopy(dict(self.topology)),
        }


def _unique_ids(label: str, values: object) -> set[str]:
    seen: set[str] = set()
    for raw_value in values:  # type: ignore[union-attr]
        value = str(raw_value)
        if not value:
            raise ValueError(f"{label} id cannot be empty")
        if value in seen:
            raise ValueError(f"duplicate {label} id: {value}")
        seen.add(value)
    return seen
