from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_two_arm_report(
    *,
    finite: dict[str, Any],
    enlarged: dict[str, Any],
    controlled_fields: tuple[str, ...],
) -> dict[str, Any]:
    frozen_fields = (
        "seed",
        "design_sha256",
        "entry_count_hour",
        "exit_count_hour",
        "horizon_steps",
        "demand_steps",
        "movement_model",
    )
    mismatches = [
        field for field in frozen_fields if finite.get(field) != enlarged.get(field)
    ]
    finite_config = dict(finite.get("scene_config", {}))
    enlarged_config = dict(enlarged.get("scene_config", {}))
    missing_controlled = [
        field
        for field in controlled_fields
        if field not in finite_config or field not in enlarged_config
    ]
    if missing_controlled:
        raise RuntimeError(
            "two-arm probe is missing controlled fields: "
            + ", ".join(missing_controlled)
        )
    finite_frozen_config = {
        key: value for key, value in finite_config.items() if key not in controlled_fields
    }
    enlarged_frozen_config = {
        key: value
        for key, value in enlarged_config.items()
        if key not in controlled_fields
    }
    if finite_frozen_config != enlarged_frozen_config:
        mismatches.append("scene_config_without_controlled_fields")
    if mismatches:
        raise RuntimeError(
            "two-arm probe changed frozen inputs: " + ", ".join(mismatches)
        )
    return {
        "schema_version": "alignment_round25_two_arm.v1",
        "status": "pass" if not mismatches else "fail",
        "controlled_difference": {
            "name": "admission_capacity_mode",
            "fields": list(controlled_fields),
        },
        "frozen_input_fields": [
            *frozen_fields,
            "scene_config_without_controlled_fields",
        ],
        "frozen_input_sha256": canonical_sha256(
            {
                "core": {field: finite.get(field) for field in frozen_fields},
                "scene_config_without_controlled_fields": finite_frozen_config,
            }
        ),
        "arms": {"finite": finite, "enlarged_capacity_control": enlarged},
    }


__all__ = ["build_two_arm_report", "canonical_sha256"]
