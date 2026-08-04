from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from .scenes import SceneConfig

SCENE_CONFIG_SCHEMA_VERSION = "alignment_scene_config.v1"


def scene_config_payload(config: SceneConfig) -> dict[str, Any]:
    """Return the JSON-normalized, complete scene configuration."""

    return json.loads(json.dumps(asdict(config), ensure_ascii=False))


def scene_config_sha256(config: SceneConfig) -> str:
    encoded = json.dumps(
        scene_config_payload(config),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_scene_config_record(manifest: Mapping[str, Any], config: SceneConfig) -> None:
    """Reject any stale, partial, extended, or re-hashed replay configuration."""

    if manifest.get("scene_config_schema_version") != SCENE_CONFIG_SCHEMA_VERSION:
        raise ValueError("trace replay scene config schema is missing or stale")
    existing = manifest.get("scene_config")
    if not isinstance(existing, Mapping):
        raise TypeError("trace replay scene config must be an object")
    current = scene_config_payload(config)
    missing = sorted(set(current) - set(existing))
    extra = sorted(set(existing) - set(current))
    different = sorted(key for key in set(current) & set(existing) if current[key] != existing[key])
    if missing or extra or different:
        raise ValueError(
            "trace replay configuration mismatch: "
            f"missing={missing}, extra={extra}, different={different}"
        )
    if manifest.get("scene_config_sha256") != scene_config_sha256(config):
        raise ValueError("trace replay scene config hash mismatch")
