"""Replay package and presentation-asset contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from metro_station.application.semantic_fingerprints import semantic_fingerprint

from .scene_contracts import StationScene


ASSET_MANIFEST_SCHEMA_VERSION = "asset_manifest.v1"
REPLAY_PACKAGE_SCHEMA_VERSION = "replay_package.v2"


@dataclass(frozen=True)
class AssetDescriptor:
    asset_id: str
    asset_kind: str
    semantic_kind: str
    version: str = "1"
    anchors: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_kind": self.asset_kind,
            "semantic_kind": self.semantic_kind,
            "version": self.version,
            "anchors": deepcopy(dict(self.anchors)),
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AssetDescriptor:
        return cls(
            asset_id=str(payload["asset_id"]),
            asset_kind=str(payload["asset_kind"]),
            semantic_kind=str(payload["semantic_kind"]),
            version=str(payload.get("version", "1")),
            anchors=deepcopy(dict(payload.get("anchors", {}))),
            metadata=deepcopy(dict(payload.get("metadata", {}))),
        )


@dataclass(frozen=True)
class AssetBinding:
    binding_id: str
    scene_entity_id: str
    asset_id: str
    placement: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "scene_entity_id": self.scene_entity_id,
            "asset_id": self.asset_id,
            "placement": deepcopy(dict(self.placement)),
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AssetBinding:
        return cls(
            binding_id=str(payload["binding_id"]),
            scene_entity_id=str(payload["scene_entity_id"]),
            asset_id=str(payload["asset_id"]),
            placement=deepcopy(dict(payload.get("placement", {}))),
            metadata=deepcopy(dict(payload.get("metadata", {}))),
        )


@dataclass(frozen=True)
class AssetManifest:
    assets: tuple[AssetDescriptor, ...]
    bindings: tuple[AssetBinding, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ASSET_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ASSET_MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported asset manifest schema: {self.schema_version}")
        asset_ids = _unique_ids("asset", (asset.asset_id for asset in self.assets))
        _unique_ids("asset binding", (binding.binding_id for binding in self.bindings))
        for binding in self.bindings:
            if binding.asset_id not in asset_ids:
                raise ValueError(f"asset binding {binding.binding_id} references an unknown asset")

    @property
    def semantic_fingerprint(self) -> str:
        return semantic_fingerprint(
            {
                "assets": [asset.as_dict() for asset in self.assets],
                "bindings": [binding.as_dict() for binding in self.bindings],
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "semantic_fingerprint": self.semantic_fingerprint,
            "assets": [asset.as_dict() for asset in self.assets],
            "bindings": [binding.as_dict() for binding in self.bindings],
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AssetManifest:
        manifest = cls(
            schema_version=str(payload.get("schema_version", "")),
            assets=tuple(AssetDescriptor.from_dict(item) for item in payload.get("assets", ())),
            bindings=tuple(AssetBinding.from_dict(item) for item in payload.get("bindings", ())),
            metadata=deepcopy(dict(payload.get("metadata", {}))),
        )
        expected = payload.get("semantic_fingerprint")
        if expected is not None and str(expected) != manifest.semantic_fingerprint:
            raise ValueError("asset manifest semantic fingerprint mismatch")
        return manifest


@dataclass(frozen=True)
class ReplayPackage:
    source_run_id: str
    station_scene: StationScene
    asset_manifest: AssetManifest
    simulation_trace_ref: str = "#/simulation_trace"
    visualization_bundle_ref: str = "#/visualization_bundle"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = REPLAY_PACKAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REPLAY_PACKAGE_SCHEMA_VERSION:
            raise ValueError(f"unsupported replay package schema: {self.schema_version}")
        if not self.simulation_trace_ref.startswith("#/"):
            raise ValueError("simulation trace reference must be a local JSON pointer")
        if not self.visualization_bundle_ref.startswith("#/"):
            raise ValueError("visualization bundle reference must be a local JSON pointer")
        scene_entity_ids = {entity.entity_id for entity in self.station_scene.entities}
        for binding in self.asset_manifest.bindings:
            if binding.scene_entity_id not in scene_entity_ids:
                raise ValueError(
                    f"asset binding {binding.binding_id} references an unknown scene entity"
                )

    @property
    def semantic_fingerprint(self) -> str:
        return semantic_fingerprint(
            {
                "source_run_id": self.source_run_id,
                "station_scene": self.station_scene.semantic_fingerprint,
                "asset_manifest": self.asset_manifest.semantic_fingerprint,
                "simulation_trace_ref": self.simulation_trace_ref,
                "visualization_bundle_ref": self.visualization_bundle_ref,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_run_id": self.source_run_id,
            "semantic_fingerprint": self.semantic_fingerprint,
            "station_scene": self.station_scene.as_dict(),
            "asset_manifest": self.asset_manifest.as_dict(),
            "simulation_trace_ref": self.simulation_trace_ref,
            "visualization_bundle_ref": self.visualization_bundle_ref,
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReplayPackage:
        package = cls(
            schema_version=str(payload.get("schema_version", "")),
            source_run_id=str(payload["source_run_id"]),
            station_scene=StationScene.from_dict(payload["station_scene"]),
            asset_manifest=AssetManifest.from_dict(payload["asset_manifest"]),
            simulation_trace_ref=str(payload.get("simulation_trace_ref", "")),
            visualization_bundle_ref=str(payload.get("visualization_bundle_ref", "")),
            metadata=deepcopy(dict(payload.get("metadata", {}))),
        )
        expected = payload.get("semantic_fingerprint")
        if expected is not None and str(expected) != package.semantic_fingerprint:
            raise ValueError("replay package semantic fingerprint mismatch")
        return package


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
