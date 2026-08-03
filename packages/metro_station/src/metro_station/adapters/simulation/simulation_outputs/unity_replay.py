"""Compact, truth-preserving replay envelope for Unity clients."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .visual_tracks import write_replay_payload_json


def unity_replay_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only simulation truth and scene contracts required by Unity.

    The legacy browser bundle contains a second, presentation-only copy of every
    trajectory. Omitting it prevents Unity from accidentally treating smoothed
    visual waypoints as simulation evidence and keeps high-frequency traces small.
    """

    required = ("schema_version", "source_run_id", "simulation_trace", "replay_package")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Unity replay payload is missing required keys: {missing}")

    result = {key: payload[key] for key in required}
    clearance_audit = payload.get("clearance_audit")
    if clearance_audit is not None:
        result["clearance_audit"] = clearance_audit
    return result


def write_unity_replay_payload_json(
    *,
    payload: Mapping[str, Any],
    output_path: Path,
) -> Path:
    return write_replay_payload_json(
        payload=unity_replay_payload(payload),
        output_path=output_path,
    )
