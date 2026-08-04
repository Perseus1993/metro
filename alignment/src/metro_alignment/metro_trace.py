from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any

import pandas as pd

from .canonical import CANONICAL_COLUMNS, normalize_frame, validate

MOVEMENT_TRACE_SCHEMA_VERSION = "movement_trace.v1"
SIMULATION_TRACE_SCHEMA_VERSION = "simulation_trace.v1"
SIMULATED_AGENT_ID_OFFSET = 90_000_000
JUPEDSIM_AUTHORITIES = frozenset({"jupedsim", "jupedsim_committed_walk"})
MAX_CANONICAL_AGENT_ID = (1 << 63) - 1


@dataclass(frozen=True)
class TraceConversionResult:
    trajectory: pd.DataFrame
    provenance: dict[str, Any]
    identity_by_agent: dict[int, tuple[int, str]]


def _unwrap_movement_trace(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    schema_version = str(payload.get("schema_version", ""))
    if schema_version == SIMULATION_TRACE_SCHEMA_VERSION:
        movement = payload.get("movement_trace")
        if not isinstance(movement, Mapping):
            raise ValueError("simulation_trace.v1 must contain a movement_trace object")
        return movement
    return payload


def _stable_episode_agent_ids(
    identities: list[tuple[int, str]],
) -> dict[tuple[int, str], int]:
    result: dict[tuple[int, str], int] = {}
    occupied: dict[int, tuple[int, str]] = {}
    namespace_size = MAX_CANONICAL_AGENT_ID - SIMULATED_AGENT_ID_OFFSET + 1
    for identity in identities:
        passenger_id, episode_id = identity
        encoded = f"{passenger_id}\0{episode_id}".encode()
        digest = hashlib.blake2b(encoded, digest_size=8, person=b"metro-align").digest()
        agent_id = SIMULATED_AGENT_ID_OFFSET + int.from_bytes(digest, "big") % namespace_size
        previous = occupied.get(agent_id)
        if previous is not None and previous != identity:
            raise ValueError(
                "movement_trace episode identity hash collision; refuse ambiguous canonical IDs"
            )
        occupied[agent_id] = identity
        result[identity] = agent_id
    return result


def movement_trace_to_canonical(
    payload: Mapping[str, Any],
    *,
    dataset_id: str,
    phases: tuple[str, ...] = ("walking",),
) -> TraceConversionResult:
    """Convert Metro's authoritative trace while preserving episode identity.

    A Metro passenger can own several movement episodes, and episode boundaries may
    share a timestamp. Canonical agent ids therefore represent ``(passenger_id,
    episode_id)`` rather than silently merging non-monotone trajectories.
    """

    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ValueError("dataset_id must be non-empty")
    trace = _unwrap_movement_trace(payload)
    if str(trace.get("schema_version", "")) != MOVEMENT_TRACE_SCHEMA_VERSION:
        raise ValueError("expected movement_trace.v1 or simulation_trace.v1 wrapper")

    metadata = trace.get("metadata")
    if not isinstance(metadata, Mapping):
        raise TypeError("movement_trace.metadata must be an object")
    if metadata.get("enabled") is False:
        raise ValueError(f"movement_trace is disabled: {metadata.get('reason', 'unknown')}")
    if metadata.get("visual_only") is not False:
        raise ValueError("movement_trace metadata must declare visual_only=false")
    authority = metadata.get("authority")
    if not isinstance(authority, str) or authority not in JUPEDSIM_AUTHORITIES:
        raise ValueError("movement_trace authority must be jupedsim")
    coverage = metadata.get("coverage")
    if not isinstance(coverage, list) or "walking" not in coverage:
        raise ValueError("movement_trace coverage must include walking")
    if metadata.get("coordinates") != "station_model_meters":
        raise ValueError("movement_trace coordinates must be station_model_meters")
    sample_interval_raw = metadata.get("sample_interval_seconds")
    if (
        not isinstance(sample_interval_raw, (int, float))
        or isinstance(sample_interval_raw, bool)
        or not isfinite(sample_interval_raw)
        or sample_interval_raw <= 0.0
    ):
        raise ValueError("movement_trace sample_interval_seconds must be finite and > 0")
    sample_interval = float(sample_interval_raw)

    points = trace.get("points")
    if not isinstance(points, list) or not points:
        raise ValueError("movement_trace.points must be a non-empty array")

    accepted: list[dict[str, Any]] = []
    rejected_phase_count = 0
    for index, point in enumerate(points):
        if not isinstance(point, Mapping):
            raise TypeError(f"movement_trace point {index} must be an object")
        if point.get("visual_only") is True:
            raise ValueError(f"movement_trace point {index} is visual_only")
        point_authority = point.get("authority", authority)
        if (
            not isinstance(point_authority, str)
            or point_authority not in JUPEDSIM_AUTHORITIES
        ):
            raise ValueError(f"movement_trace point {index} has an unsupported authority")
        if "phase" not in point:
            raise ValueError(f"movement_trace point {index} must declare phase explicitly")
        phase = point["phase"]
        if not isinstance(phase, str) or not phase.strip():
            raise ValueError(f"movement_trace point {index} has an invalid phase")
        if phases and phase not in phases:
            rejected_phase_count += 1
            continue
        try:
            passenger_id = point["passenger_id"]
            episode_id = point["episode_id"]
            numeric_values = (point["time_seconds"], point["x"], point["y"])
        except KeyError as exc:
            raise ValueError(f"movement_trace point {index} violates the point contract") from exc
        if (
            not isinstance(passenger_id, int)
            or isinstance(passenger_id, bool)
            or passenger_id < 0
            or not isinstance(episode_id, str)
            or not episode_id.strip()
        ):
            raise ValueError(f"movement_trace point {index} has invalid passenger/episode identity")
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not isfinite(value)
            for value in numeric_values
        ):
            raise ValueError(f"movement_trace point {index} contains invalid physical values")
        time_seconds, x_m, y_m = (float(value) for value in numeric_values)
        if time_seconds < 0.0:
            raise ValueError(f"movement_trace point {index} contains invalid physical values")
        accepted.append(
            {
                "passenger_id": passenger_id,
                "episode_id": episode_id,
                "t_s": time_seconds,
                "x_m": x_m,
                "y_m": y_m,
            }
        )
    if not accepted:
        raise ValueError(f"movement_trace contains no points for phases={phases!r}")

    raw = pd.DataFrame.from_records(accepted)
    raw = raw.sort_values(["passenger_id", "episode_id", "t_s"], kind="mergesort")
    identity_columns = ["passenger_id", "episode_id"]
    duplicates = raw.duplicated([*identity_columns, "t_s"], keep=False)
    if duplicates.any():
        groups = raw.loc[duplicates].groupby([*identity_columns, "t_s"], sort=False)
        conflicting = [
            key for key, group in groups if group[["x_m", "y_m"]].drop_duplicates().shape[0] > 1
        ]
        if conflicting:
            raise ValueError(
                f"movement_trace has conflicting duplicate episode samples: {conflicting[:3]}"
            )
        raw = raw.drop_duplicates([*identity_columns, "t_s"], keep="first")

    identities = sorted(
        {(int(row.passenger_id), str(row.episode_id)) for row in raw.itertuples(index=False)}
    )
    identity_to_agent = _stable_episode_agent_ids(identities)
    origin = float(raw["t_s"].min())
    scaled_frame = (raw["t_s"] - origin) / sample_interval
    rounded_frame = scaled_frame.round()
    if ((scaled_frame - rounded_frame).abs() > 1e-6).any():
        raise ValueError("movement_trace sample times are off the declared sampling grid")
    raw["canonical_frame"] = rounded_frame.astype("int64")
    if raw.duplicated([*identity_columns, "canonical_frame"]).any():
        raise ValueError("movement_trace maps distinct episode samples to the same frame")
    rows = pd.DataFrame(
        {
            "dataset_id": dataset_id,
            "agent_id": [
                identity_to_agent[(int(passenger), str(episode))]
                for passenger, episode in zip(raw["passenger_id"], raw["episode_id"], strict=True)
            ],
            "frame": raw["canonical_frame"],
            "t_s": raw["t_s"].astype("float64"),
            "x_m": raw["x_m"].astype("float64"),
            "y_m": raw["y_m"].astype("float64"),
        },
        columns=list(CANONICAL_COLUMNS),
    )
    trajectory = normalize_frame(rows)
    errors = validate(trajectory)
    if errors:
        raise ValueError("converted movement trace is invalid: " + "; ".join(errors))

    return TraceConversionResult(
        trajectory=trajectory,
        provenance={
            "source_schema_version": MOVEMENT_TRACE_SCHEMA_VERSION,
            "authority": authority,
            "coordinates": "station_model_meters",
            "sample_interval_seconds": sample_interval,
            "included_phases": list(phases),
            "excluded_phase_point_count": rejected_phase_count,
            "source_point_count": len(points),
            "canonical_point_count": len(trajectory),
            "episode_count": len(identities),
            "passenger_count": int(raw["passenger_id"].nunique()),
            "agent_id_contract": "blake2b64(passenger_id,episode_id) in signed-int64 simulation namespace",
        },
        identity_by_agent={agent: identity for identity, agent in identity_to_agent.items()},
    )
