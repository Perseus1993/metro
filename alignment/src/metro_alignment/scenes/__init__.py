"""Registered, evidence-scoped alignment scenarios."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .base import SceneConfig
from .bottleneck import BOTTLE_NECK_SCENE_ID, BottleneckConfig
from .corridor_unidirectional import (
    CORRIDOR_UNIDIRECTIONAL_SCENE_ID,
    CorridorUnidirectionalConfig,
)
from .platform_boarding import PLATFORM_BOARDING_SCENE_ID, PlatformBoardingConfig

SceneFactory = Callable[[], SceneConfig]
SCENE_FACTORIES: dict[str, SceneFactory] = {
    CORRIDOR_UNIDIRECTIONAL_SCENE_ID: CorridorUnidirectionalConfig,
    BOTTLE_NECK_SCENE_ID: BottleneckConfig,
    PLATFORM_BOARDING_SCENE_ID: PlatformBoardingConfig,
}


def list_scene_configs() -> tuple[tuple[str, SceneConfig], ...]:
    items: list[tuple[str, SceneConfig]] = []
    scene_ids: list[str] = []
    for key, factory in SCENE_FACTORIES.items():
        config = factory()
        if not isinstance(config, SceneConfig):
            raise TypeError(f"scene factory {key!r} must return SceneConfig")
        if key != config.scene_id:
            raise ValueError(f"scene registry key {key!r} must equal scene_id {config.scene_id!r}")
        items.append((key, config))
        scene_ids.append(config.scene_id)
    duplicates = sorted({scene_id for scene_id in scene_ids if scene_ids.count(scene_id) > 1})
    if duplicates:
        raise ValueError(f"scene registry contains duplicate scene_id values: {duplicates}")
    return tuple(items)


def build_scene_config(scene_id: str, **overrides: Any) -> SceneConfig:
    list_scene_configs()
    try:
        config = SCENE_FACTORIES[scene_id]()
    except KeyError as exc:
        raise ValueError(f"unknown scene_id: {scene_id}") from exc
    return replace(config, **overrides) if overrides else config


__all__ = [
    "BOTTLE_NECK_SCENE_ID",
    "CORRIDOR_UNIDIRECTIONAL_SCENE_ID",
    "PLATFORM_BOARDING_SCENE_ID",
    "SCENE_FACTORIES",
    "BottleneckConfig",
    "CorridorUnidirectionalConfig",
    "PlatformBoardingConfig",
    "SceneConfig",
    "build_scene_config",
    "list_scene_configs",
]
