"""Stable contracts for topology-aware replay packages."""

from .package_contracts import (
    ASSET_MANIFEST_SCHEMA_VERSION,
    REPLAY_PACKAGE_SCHEMA_VERSION,
    AssetBinding,
    AssetDescriptor,
    AssetManifest,
    ReplayPackage,
)
from .scene_contracts import (
    STATION_SCENE_SCHEMA_VERSION,
    RuntimeSceneBinding,
    SceneEntity,
    SceneLevel,
    SceneRelation,
    StationScene,
)

__all__ = [
    "ASSET_MANIFEST_SCHEMA_VERSION",
    "REPLAY_PACKAGE_SCHEMA_VERSION",
    "STATION_SCENE_SCHEMA_VERSION",
    "AssetBinding",
    "AssetDescriptor",
    "AssetManifest",
    "ReplayPackage",
    "RuntimeSceneBinding",
    "SceneEntity",
    "SceneLevel",
    "SceneRelation",
    "StationScene",
]
