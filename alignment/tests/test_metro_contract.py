from __future__ import annotations

import copy

import pytest

from metro_alignment.metro_contract import (
    SCENE_CONFIG_SCHEMA_VERSION,
    scene_config_payload,
    scene_config_sha256,
    verify_scene_config_record,
)
from metro_alignment.scenes import build_scene_config


def _manifest() -> tuple[dict, object]:
    config = build_scene_config("platform_boarding")
    return (
        {
            "scene_config_schema_version": SCENE_CONFIG_SCHEMA_VERSION,
            "scene_config": scene_config_payload(config),
            "scene_config_sha256": scene_config_sha256(config),
        },
        config,
    )


def test_scene_config_replay_requires_exact_payload_and_hash() -> None:
    manifest, config = _manifest()
    verify_scene_config_record(manifest, config)  # type: ignore[arg-type]

    missing = copy.deepcopy(manifest)
    del missing["scene_config"]["seed"]
    with pytest.raises(ValueError, match="missing=.*seed"):
        verify_scene_config_record(missing, config)  # type: ignore[arg-type]

    extra = copy.deepcopy(manifest)
    extra["scene_config"]["future_key"] = True
    with pytest.raises(ValueError, match="extra=.*future_key"):
        verify_scene_config_record(extra, config)  # type: ignore[arg-type]

    different = copy.deepcopy(manifest)
    different["scene_config"]["seed"] += 1
    with pytest.raises(ValueError, match="different=.*seed"):
        verify_scene_config_record(different, config)  # type: ignore[arg-type]

    bad_hash = copy.deepcopy(manifest)
    bad_hash["scene_config_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_scene_config_record(bad_hash, config)  # type: ignore[arg-type]
