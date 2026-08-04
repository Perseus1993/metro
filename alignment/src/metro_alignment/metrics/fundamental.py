from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from itertools import pairwise
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd
import pedpy
from shapely.geometry import box

from metro_alignment.canonical import validate as validate_canonical

METRIC_SCHEMA_VERSION = "alignment_metrics.v5"
WALKING_SPEED_PROXY_KEY = "low_global_density_walking_speed_proxy_m_s"
DEFAULT_DENSITY_BIN_EDGES = (0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
FUNDAMENTAL_MIN_BIN_N = 30


@dataclass(frozen=True)
class MetricSummary:
    n: int
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    mean: float
    std: float


@dataclass(frozen=True)
class MetricConfig:
    frame_rate_hz: float | None = None
    speed_window_seconds: float = 0.4
    free_flow_density_max_p_m2: float = 0.3
    walking_speed_min_m_s: float = 0.5
    max_valid_speed_m_s: float = 3.0
    measurement_bounds_m: tuple[float, float, float, float] | None = None
    measurement_area_id: str | None = None
    comparison_frame_id: str | None = None
    coordinate_transform_id: str | None = None
    coordinate_translation_m: tuple[float, float] | None = None
    density_bin_edges: tuple[float, ...] = DEFAULT_DENSITY_BIN_EDGES

    def __post_init__(self) -> None:
        if self.frame_rate_hz is not None and (
            not isfinite(self.frame_rate_hz) or self.frame_rate_hz <= 0.0
        ):
            raise ValueError("frame_rate_hz must be finite and > 0")
        if not isfinite(self.speed_window_seconds) or self.speed_window_seconds <= 0.0:
            raise ValueError("speed_window_seconds must be finite and > 0")
        if self.free_flow_density_max_p_m2 <= 0.0:
            raise ValueError("free_flow_density_max_p_m2 must be > 0")
        if not 0.0 <= self.walking_speed_min_m_s < self.max_valid_speed_m_s:
            raise ValueError("walking speed bounds are invalid")
        if len(self.density_bin_edges) < 3 or any(
            right <= left
            for left, right in zip(
                self.density_bin_edges,
                self.density_bin_edges[1:],
            )
        ):
            raise ValueError("density_bin_edges must be strictly increasing")
        if self.measurement_bounds_m is not None:
            min_x, min_y, max_x, max_y = self.measurement_bounds_m
            if not all(isfinite(value) for value in self.measurement_bounds_m):
                raise ValueError("measurement bounds must be finite")
            if max_x <= min_x or max_y <= min_y:
                raise ValueError("measurement bounds must have positive area")
        if self.measurement_area_id is not None and self.measurement_bounds_m is None:
            raise ValueError("measurement_area_id requires explicit measurement_bounds_m")
        comparison_fields = (
            self.measurement_area_id,
            self.comparison_frame_id,
            self.coordinate_transform_id,
            self.coordinate_translation_m,
        )
        if any(value is not None for value in comparison_fields) and not all(
            value is not None for value in comparison_fields
        ):
            raise ValueError(
                "comparable measurements require area, comparison frame, transform, and translation"
            )
        if self.coordinate_translation_m is not None and (
            len(self.coordinate_translation_m) != 2
            or not all(isfinite(value) for value in self.coordinate_translation_m)
        ):
            raise ValueError("coordinate translation must contain two finite meter values")


@dataclass(frozen=True)
class MetricContributorIds:
    walking_proxy_agent_ids: tuple[int, ...]
    walking_proxy_frame_ids: tuple[int, ...]
    fundamental_agent_ids: tuple[int, ...]
    fundamental_frame_ids: tuple[int, ...]


@dataclass(frozen=True)
class MetricComputation:
    table: dict[str, Any]
    contributors: MetricContributorIds


def _speed_stats(series: pd.Series) -> MetricSummary:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return MetricSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return MetricSummary(
        n=len(values),
        p5=float(values.quantile(0.05)),
        p25=float(values.quantile(0.25)),
        p50=float(values.quantile(0.50)),
        p75=float(values.quantile(0.75)),
        p95=float(values.quantile(0.95)),
        mean=float(values.mean()),
        std=float(values.std(ddof=0)),
    )


def _infer_frame_rate_hz(df: pd.DataFrame) -> float:
    ordered = df.sort_values(["agent_id", "t_s"], kind="mergesort")
    delta = ordered.groupby("agent_id", sort=False)["t_s"].diff()
    positive = delta[(delta > 0.0) & np.isfinite(delta)]
    if positive.empty:
        raise ValueError("cannot infer frame rate from a trajectory without positive time deltas")
    return float(1.0 / positive.median())


def _speed_frame_step(frame_rate_hz: float, window_seconds: float) -> int:
    raw_step = window_seconds * frame_rate_hz / 2.0
    step = round(raw_step)
    if step < 1 or abs(raw_step - step) > 1e-9:
        raise ValueError(
            "speed_window_seconds must map to an integer PedPy frame step: "
            f"window={window_seconds}, frame_rate={frame_rate_hz}"
        )
    return step


def _measurement_geometry(
    bounds: tuple[float, float, float, float],
    translation: tuple[float, float],
) -> tuple[tuple[float, float, float, float], dict[str, Any], str]:
    min_x, min_y, max_x, max_y = bounds
    shared_bounds = (
        min_x + translation[0],
        min_y + translation[1],
        max_x + translation[0],
        max_y + translation[1],
    )
    width = max_x - min_x
    height = max_y - min_y
    shape = {
        "bounds_m_rounded": [f"{value:.9f}" for value in shared_bounds],
        "width_m": f"{width:.9f}",
        "height_m": f"{height:.9f}",
        "area_m2": f"{width * height:.9f}",
    }
    digest = hashlib.sha256(
        json.dumps(shape, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return shared_bounds, shape, digest


def _measurement_contract(
    df: pd.DataFrame,
    config: MetricConfig,
) -> tuple[tuple[float, float, float, float], dict[str, Any]]:
    if config.measurement_bounds_m is not None:
        bounds = tuple(float(value) for value in config.measurement_bounds_m)
        translation = config.coordinate_translation_m or (0.0, 0.0)
        shared_bounds, polygon_contract, polygon_sha256 = _measurement_geometry(
            bounds, translation
        )
        return bounds, {
            "id": config.measurement_area_id,
            "bounds_m": list(bounds),
            "comparison_bounds_m": list(shared_bounds),
            "comparison_frame_id": config.comparison_frame_id,
            "comparison_polygon_sha256": polygon_sha256,
            "shape": polygon_contract,
            "coordinate_transform": {
                "id": config.coordinate_transform_id,
                "translation_m": list(translation),
            },
            "source": "explicit",
            "comparable": all(
                value is not None
                for value in (
                    config.measurement_area_id,
                    config.comparison_frame_id,
                    config.coordinate_transform_id,
                    config.coordinate_translation_m,
                )
            ),
        }

    min_x = float(df["x_m"].min())
    min_y = float(df["y_m"].min())
    max_x = float(df["x_m"].max())
    max_y = float(df["y_m"].max())
    if max_x <= min_x:
        min_x -= 0.5
        max_x += 0.5
    if max_y <= min_y:
        min_y -= 0.5
        max_y += 0.5
    bounds = (min_x, min_y, max_x, max_y)
    return bounds, {
        "id": None,
        "bounds_m": list(bounds),
        "comparison_bounds_m": None,
        "comparison_frame_id": None,
        "comparison_polygon_sha256": None,
        "shape": None,
        "coordinate_transform": None,
        "source": "trajectory_bounds_inferred",
        "comparable": False,
    }


def _pedpy_tables(
    df: pd.DataFrame,
    *,
    config: MetricConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, float, int, dict[str, Any]]:
    errors = validate_canonical(df)
    if errors:
        raise ValueError("metrics require valid canonical data: " + "; ".join(errors))
    frame_rate_hz = config.frame_rate_hz or _infer_frame_rate_hz(df)
    speed_frame_step = _speed_frame_step(frame_rate_hz, config.speed_window_seconds)
    if df.duplicated(["agent_id", "frame"]).any():
        raise ValueError("PedPy requires unique (agent_id, frame) samples")

    trajectory_frame = df.rename(columns={"agent_id": "id", "x_m": "x", "y_m": "y"})[
        ["id", "frame", "x", "y"]
    ]
    trajectory = pedpy.TrajectoryData(trajectory_frame, frame_rate=frame_rate_hz)
    individual_speed = pedpy.compute_individual_speed(
        traj_data=trajectory,
        frame_step=speed_frame_step,
        speed_calculation=pedpy.SpeedCalculation.BORDER_SINGLE_SIDED,
    )

    bounds, contract = _measurement_contract(df, config)
    measurement_area = pedpy.MeasurementArea(box(*bounds))
    density = pedpy.compute_classic_density(
        traj_data=trajectory,
        measurement_area=measurement_area,
    )
    mean_speed = pedpy.compute_mean_speed_per_frame(
        traj_data=trajectory,
        individual_speed=individual_speed,
        measurement_area=measurement_area,
    )
    frame_metrics = density.merge(mean_speed, on="frame", how="inner", validate="one_to_one")
    frame_metrics = frame_metrics.rename(columns={"density": "density_p_m2", "speed": "speed_m_s"})

    positions = trajectory_frame.merge(individual_speed, on=["id", "frame"], validate="one_to_one")
    min_x, min_y, max_x, max_y = bounds
    positions = positions[
        positions["x"].between(min_x, max_x, inclusive="both")
        & positions["y"].between(min_y, max_y, inclusive="both")
    ]
    positions = positions.merge(density, on="frame", how="inner", validate="many_to_one")
    positions = positions.rename(columns={"density": "density_p_m2"})
    return positions, frame_metrics, frame_rate_hz, speed_frame_step, contract


def compute_walking_speed_proxy_summary(
    df: pd.DataFrame,
    *,
    config: MetricConfig | None = None,
) -> MetricSummary:
    active_config = config or MetricConfig()
    positions, _, _, _, _ = _pedpy_tables(df, config=active_config)
    selected = positions[
        (positions["density_p_m2"] <= active_config.free_flow_density_max_p_m2)
        & (positions["speed"] >= active_config.walking_speed_min_m_s)
        & (positions["speed"] <= active_config.max_valid_speed_m_s)
    ]
    return _speed_stats(selected["speed"])


def _build_profile_from_frames(
    frame_metrics: pd.DataFrame,
    *,
    density_bin_edges: tuple[float, ...],
    max_valid_speed_m_s: float,
) -> list[dict[str, float | int]]:
    table = _eligible_profile_frames(
        frame_metrics,
        density_bin_edges=density_bin_edges,
        max_valid_speed_m_s=max_valid_speed_m_s,
    )
    table["bin_index"] = pd.cut(
        table["density_p_m2"],
        bins=list(density_bin_edges),
        include_lowest=True,
        right=True,
        labels=False,
    )
    rows: list[dict[str, float | int]] = []
    for bin_index, group in table.groupby("bin_index", sort=True):
        index = int(bin_index)
        speeds = group["speed_m_s"]
        rows.append(
            {
                "density_low_p_m2": float(density_bin_edges[index]),
                "density_high_p_m2": float(density_bin_edges[index + 1]),
                "density_p_m2": float(group["density_p_m2"].mean()),
                "speed_p50": float(speeds.quantile(0.50)),
                "speed_p5": float(speeds.quantile(0.05)),
                "speed_p95": float(speeds.quantile(0.95)),
                "n": len(speeds),
            }
        )
    return rows


def fundamental_profile_errors(
    fundamental: dict[str, Any],
    *,
    density_bin_edges: list[Any],
    max_valid_speed_m_s: float,
) -> list[str]:
    bins = fundamental.get("bins")
    if not isinstance(bins, list):
        return ["fundamental bins must be an array"]
    try:
        edges = [float(value) for value in density_bin_edges]
    except (TypeError, ValueError):
        return ["fundamental density-bin edges must be numeric"]
    allowed = set(pairwise(edges))
    seen: set[tuple[float, float]] = set()
    previous_index = -1
    errors: list[str] = []
    for row_index, row in enumerate(bins):
        if not isinstance(row, dict):
            errors.append(f"fundamental bin {row_index} must be an object")
            continue
        required = (
            "density_low_p_m2",
            "density_high_p_m2",
            "density_p_m2",
            "speed_p5",
            "speed_p50",
            "speed_p95",
            "n",
        )
        try:
            values = [row[key] for key in required[:-1]]
            if any(isinstance(value, bool) for value in values):
                raise TypeError
            low, high, density, p5, p50, p95 = (float(value) for value in values)
            count = row["n"]
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or count <= 0
                or not all(isfinite(value) for value in (low, high, density, p5, p50, p95))
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            errors.append(f"fundamental bin {row_index} has invalid numeric fields")
            continue
        interval = (low, high)
        if interval not in allowed:
            errors.append(f"fundamental bin {row_index} is not a declared density interval")
            continue
        edge_index = edges.index(low)
        if interval in seen:
            errors.append(f"fundamental bin {row_index} duplicates a density interval")
        if edge_index <= previous_index:
            errors.append("fundamental bins must be strictly ordered and non-overlapping")
        seen.add(interval)
        previous_index = edge_index
        if not low <= density <= high:
            errors.append(f"fundamental bin {row_index} mean density is outside its interval")
        if not 0.0 <= p5 <= p50 <= p95 <= max_valid_speed_m_s:
            errors.append(f"fundamental bin {row_index} speed quantiles are invalid")
    return errors


def _eligible_profile_frames(
    frame_metrics: pd.DataFrame,
    *,
    density_bin_edges: tuple[float, ...],
    max_valid_speed_m_s: float,
) -> pd.DataFrame:
    table = frame_metrics.replace([np.inf, -np.inf], np.nan).dropna()
    return table[
        (table["density_p_m2"] >= density_bin_edges[0])
        & (table["density_p_m2"] <= density_bin_edges[-1])
        & (table["speed_m_s"] >= 0.0)
        & (table["speed_m_s"] <= max_valid_speed_m_s)
    ].copy()


def build_fundamental_profile(
    df: pd.DataFrame,
    *,
    config: MetricConfig | None = None,
) -> list[dict[str, float | int]]:
    active_config = config or MetricConfig()
    _, frame_metrics, _, _, _ = _pedpy_tables(df, config=active_config)
    return _build_profile_from_frames(
        frame_metrics,
        density_bin_edges=active_config.density_bin_edges,
        max_valid_speed_m_s=active_config.max_valid_speed_m_s,
    )


def fundamental_in_band_fraction(
    observed_profile: list[dict[str, Any]],
    simulated_profile: list[dict[str, Any]] | None = None,
) -> dict[str, float | int]:
    if not observed_profile or not simulated_profile:
        return {
            "fraction": 0.0,
            "conditional_in_band_fraction": 0.0,
            "support_coverage": 0.0,
            "matched_n": 0,
            "overlap_n": 0,
            "total_n": int(sum(int(row.get("n", 0)) for row in simulated_profile or [])),
            "unmatched_n": int(sum(int(row.get("n", 0)) for row in simulated_profile or [])),
            "matched_bin_count": 0,
            "supported_bin_count": 0,
            "total_bin_count": int(
                sum(int(row.get("n", 0)) > 0 for row in simulated_profile or [])
            ),
            "max_supported_density_high_p_m2": 0.0,
        }

    total = 0
    overlap = 0
    supported = 0
    hit = 0
    total_bins = 0
    matched_bins = 0
    supported_bins = 0
    max_supported_density_high = 0.0
    for simulated in simulated_profile:
        sample_n = int(simulated.get("n", 0))
        if sample_n <= 0:
            continue
        total_bins += 1
        total += sample_n
        low = float(simulated.get("density_low_p_m2", simulated.get("density_p_m2", 0.0)))
        high = float(simulated.get("density_high_p_m2", simulated.get("density_p_m2", 0.0)))
        candidates = [
            row
            for row in observed_profile
            if float(row.get("density_low_p_m2", row.get("density_p_m2", 0.0))) <= low + 1e-12
            and float(row.get("density_high_p_m2", row.get("density_p_m2", 0.0))) >= high - 1e-12
        ]
        if not candidates:
            continue
        observed = candidates[0]
        lower = float(observed["speed_p5"])
        upper = float(observed["speed_p95"])
        overlap += sample_n
        matched_bins += 1
        is_supported = (
            int(observed.get("n", 0)) >= FUNDAMENTAL_MIN_BIN_N and sample_n >= FUNDAMENTAL_MIN_BIN_N
        )
        if is_supported:
            supported_bins += 1
            supported += sample_n
            max_supported_density_high = max(max_supported_density_high, high)
            if lower <= float(simulated["speed_p50"]) <= upper:
                hit += sample_n
    return {
        "fraction": hit / supported if supported else 0.0,
        "conditional_in_band_fraction": hit / supported if supported else 0.0,
        "support_coverage": supported / total if total else 0.0,
        "matched_n": supported,
        "overlap_n": overlap,
        "total_n": total,
        "unmatched_n": total - supported,
        "matched_bin_count": matched_bins,
        "supported_bin_count": supported_bins,
        "total_bin_count": total_bins,
        "max_supported_density_high_p_m2": max_supported_density_high,
    }


def analysis_contract_consistency_errors(payload: object) -> list[str]:
    """Cross-check a normalized contract against the method payload that claims it."""

    if not isinstance(payload, dict):
        return ["metric payload must be an object"]
    errors: list[str] = []
    contract = payload.get("analysis_contract")
    method = payload.get("method")
    fundamental = payload.get("fundamental_diagram")
    if not isinstance(contract, dict) or not isinstance(method, dict):
        return ["analysis contract and method must be objects"]
    if not isinstance(fundamental, dict):
        return ["fundamental diagram must be an object"]

    library = contract.get("library", {})
    if (method.get("library"), method.get("library_version")) != (
        library.get("name"),
        library.get("version"),
    ):
        errors.append("PedPy library/version contradicts analysis contract")
    speed_contract = contract.get("speed", {})
    if method.get("speed") != speed_contract.get("method"):
        errors.append("speed method contradicts analysis contract")
    if method.get("frame_mean_speed") != speed_contract.get("frame_mean_method"):
        errors.append("frame mean speed method contradicts analysis contract")
    try:
        frame_rate_raw = method["frame_rate_hz"]
        frame_step_raw = method["speed_frame_step"]
        if isinstance(frame_rate_raw, bool) or isinstance(frame_step_raw, bool):
            raise TypeError
        frame_rate = float(frame_rate_raw)
        if not isinstance(frame_step_raw, (int, float)) or not float(
            frame_step_raw
        ).is_integer():
            raise TypeError
        frame_step = int(frame_step_raw)
        method_window = float(method["physical_speed_window_s"])
        contract_window = float(speed_contract["physical_window_s"])
        if (
            not all(isfinite(value) for value in (frame_rate, method_window, contract_window))
            or frame_rate <= 0.0
            or frame_step <= 0
            or abs(2.0 * frame_step / frame_rate - method_window) > 1e-12
            or abs(method_window - contract_window) > 1e-12
        ):
            errors.append("speed frame step/rate/window are internally inconsistent")
    except (KeyError, TypeError, ValueError):
        errors.append("speed frame step/rate/window are incomplete")

    density_contract = contract.get("density", {})
    if method.get("density") != density_contract.get("method"):
        errors.append("density method contradicts analysis contract")
    config = method.get("config", {})
    proxy = contract.get("walking_speed_proxy", {})
    proxy_pairs = (
        ("free_flow_density_max_p_m2", "density_max_p_m2"),
        ("walking_speed_min_m_s", "speed_min_m_s"),
        ("max_valid_speed_m_s", "speed_max_m_s"),
    )
    for config_key, contract_key in proxy_pairs:
        try:
            if float(config[config_key]) != float(proxy[contract_key]):
                errors.append(f"{config_key} contradicts walking-speed proxy contract")
        except (KeyError, TypeError, ValueError):
            errors.append(f"{config_key} is incomplete")
    try:
        if float(config["speed_window_seconds"]) != float(speed_contract["physical_window_s"]):
            errors.append("configured speed window contradicts analysis contract")
    except (KeyError, TypeError, ValueError):
        errors.append("configured speed window is incomplete")

    contract_edges = contract.get("density_bin_edges")
    try:
        if not isinstance(contract_edges, list) or any(
            isinstance(value, bool) for value in contract_edges
        ):
            raise TypeError
        numeric_edges = [float(value) for value in contract_edges]
        if (
            len(numeric_edges) < 3
            or not all(isfinite(value) for value in numeric_edges)
            or any(right <= left for left, right in pairwise(numeric_edges))
        ):
            raise ValueError
    except (TypeError, ValueError):
        numeric_edges = []
        errors.append("analysis-contract density bins are invalid")
    if list(config.get("density_bin_edges", [])) != contract_edges:
        errors.append("configured density bins contradict analysis contract")
    if list(fundamental.get("density_bin_edges", [])) != contract_edges:
        errors.append("fundamental density bins contradict analysis contract")
    if fundamental.get("method") != contract.get("fundamental_diagram", {}).get("method"):
        errors.append("fundamental method contradicts analysis contract")
    try:
        max_valid_speed = float(config["max_valid_speed_m_s"])
    except (KeyError, TypeError, ValueError):
        max_valid_speed = 0.0
        errors.append("max_valid_speed_m_s is incomplete")
    errors.extend(
        fundamental_profile_errors(
            fundamental,
            density_bin_edges=numeric_edges,
            max_valid_speed_m_s=max_valid_speed,
        )
    )

    area = method.get("measurement_area", {})
    normalized = contract.get("measurement", {})
    try:
        raw_bounds = area["bounds_m"]
        config_bounds = config["measurement_bounds_m"]
        transform = area["coordinate_transform"]
        raw_translation = transform["translation_m"]
        config_translation = config["coordinate_translation_m"]
        raw_values = [*raw_bounds, *raw_translation]
        config_values = [*config_bounds, *config_translation]
        if any(isinstance(value, bool) for value in [*raw_values, *config_values]):
            raise TypeError
        bounds = tuple(float(value) for value in raw_bounds)
        translation = tuple(float(value) for value in raw_translation)
        if len(bounds) != 4 or len(translation) != 2:
            raise ValueError
        if not all(isfinite(value) for value in (*bounds, *translation)):
            raise ValueError
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            raise ValueError
        expected_shared, expected_shape, expected_hash = _measurement_geometry(
            bounds, translation
        )
        if tuple(float(value) for value in config_bounds) != bounds:
            errors.append("configured measurement bounds contradict method geometry")
        if tuple(float(value) for value in config_translation) != translation:
            errors.append("configured coordinate translation contradicts method geometry")
        if config.get("measurement_area_id") != area.get("id"):
            errors.append("configured measurement area ID contradicts method geometry")
        if config.get("comparison_frame_id") != area.get("comparison_frame_id"):
            errors.append("configured comparison frame contradicts method geometry")
        if config.get("coordinate_transform_id") != transform.get("id"):
            errors.append("configured coordinate transform ID contradicts method geometry")
        if tuple(float(value) for value in area["comparison_bounds_m"]) != expected_shared:
            errors.append("comparison bounds do not equal raw bounds plus translation")
        if area.get("shape") != expected_shape:
            errors.append("measurement shape does not reconstruct from raw geometry")
        if area.get("comparison_polygon_sha256") != expected_hash:
            errors.append("measurement polygon hash does not reconstruct from raw geometry")
    except (KeyError, TypeError, ValueError):
        errors.append("measurement raw/config geometry is incomplete")
        expected_shape = None
        expected_hash = None
    if area.get("source") != "explicit" or area.get("comparable") is not True:
        errors.append("measurement geometry must be explicit and comparable")
    measurement_pairs = (
        (area.get("id"), normalized.get("area_id"), "area ID"),
        (
            area.get("comparison_frame_id"),
            normalized.get("comparison_frame_id"),
            "comparison frame",
        ),
        (expected_hash, normalized.get("comparison_polygon_sha256"), "polygon hash"),
        (expected_shape, normalized.get("shape"), "normalized shape"),
    )
    for method_value, contract_value, name in measurement_pairs:
        if method_value != contract_value:
            errors.append(f"measurement {name} contradicts analysis contract")
    return errors


def compute_metric_bundle(
    df: pd.DataFrame,
    *,
    config: MetricConfig | None = None,
) -> MetricComputation:
    active_config = config or MetricConfig()
    positions, frame_metrics, frame_rate_hz, speed_frame_step, measurement_contract = _pedpy_tables(
        df,
        config=active_config,
    )
    free_flow_rows = positions[
        (positions["density_p_m2"] <= active_config.free_flow_density_max_p_m2)
        & (positions["speed"] >= active_config.walking_speed_min_m_s)
        & (positions["speed"] <= active_config.max_valid_speed_m_s)
    ]
    free_flow = _speed_stats(free_flow_rows["speed"])
    eligible_profile_frames = _eligible_profile_frames(
        frame_metrics,
        density_bin_edges=active_config.density_bin_edges,
        max_valid_speed_m_s=active_config.max_valid_speed_m_s,
    )
    fundamental_frame_ids = tuple(
        sorted(int(value) for value in eligible_profile_frames["frame"].unique())
    )
    fundamental_positions = positions[positions["frame"].isin(fundamental_frame_ids)]
    profile = _build_profile_from_frames(
        frame_metrics,
        density_bin_edges=active_config.density_bin_edges,
        max_valid_speed_m_s=active_config.max_valid_speed_m_s,
    )
    quality_status = "comparable" if measurement_contract["comparable"] else "provisional"
    analysis_contract = {
        "schema_version": "alignment_analysis_contract.v1",
        "library": {"name": "PedPy", "version": str(getattr(pedpy, "__version__", "unknown"))},
        "speed": {
            "method": "compute_individual_speed:BORDER_SINGLE_SIDED",
            "frame_mean_method": "compute_mean_speed_per_frame",
            "physical_window_s": float(active_config.speed_window_seconds),
        },
        "density": {"method": "compute_classic_density"},
        "walking_speed_proxy": {
            "semantics": "low_global_density_speed_truncated_proxy",
            "density_max_p_m2": float(active_config.free_flow_density_max_p_m2),
            "speed_min_m_s": float(active_config.walking_speed_min_m_s),
            "speed_max_m_s": float(active_config.max_valid_speed_m_s),
            "desired_speed_release_eligible": False,
        },
        "density_bin_edges": [float(value) for value in active_config.density_bin_edges],
        "fundamental_diagram": {"method": "PedPy classic density + mean speed per frame"},
        "measurement": {
            "area_id": measurement_contract["id"],
            "comparison_frame_id": measurement_contract["comparison_frame_id"],
            "comparison_polygon_sha256": measurement_contract["comparison_polygon_sha256"],
            "shape": measurement_contract["shape"],
        },
    }
    table = {
        "schema_version": METRIC_SCHEMA_VERSION,
        "analysis_contract": analysis_contract,
        "method": {
            "library": "PedPy",
            "library_version": str(getattr(pedpy, "__version__", "unknown")),
            "speed": "compute_individual_speed:BORDER_SINGLE_SIDED",
            "speed_frame_step": speed_frame_step,
            "physical_speed_window_s": float(active_config.speed_window_seconds),
            "density": "compute_classic_density",
            "frame_mean_speed": "compute_mean_speed_per_frame",
            "frame_rate_hz": frame_rate_hz,
            "measurement_area": measurement_contract,
            "config": json.loads(
                json.dumps(asdict(active_config), ensure_ascii=False, allow_nan=False)
            ),
        },
        WALKING_SPEED_PROXY_KEY: asdict(free_flow),
        "metric_support": {
            WALKING_SPEED_PROXY_KEY: {
                "point_n": len(free_flow_rows),
                "agent_n": int(free_flow_rows["id"].nunique()),
                "frame_n": int(free_flow_rows["frame"].nunique()),
            },
            "fundamental_diagram": {
                "point_n": len(fundamental_positions),
                "agent_n": int(fundamental_positions["id"].nunique()),
                "frame_n": len(fundamental_frame_ids),
            },
        },
        "fundamental_diagram": {
            "method": "PedPy classic density + mean speed per frame",
            "density_unit": "persons/m^2",
            "speed_unit": "m/s",
            "density_bin_edges": list(active_config.density_bin_edges),
            "bins": profile,
        },
        "fundamental_in_band_fraction": {
            "value": None,
            "status": "requires_observed_reference",
        },
        "quality": {
            "status": quality_status,
            "limitations": (
                []
                if quality_status == "comparable"
                else [
                    "measurement area inferred from trajectory bounds; do not use for cross-run gates"
                ]
            ),
        },
    }
    return MetricComputation(
        table=table,
        contributors=MetricContributorIds(
            walking_proxy_agent_ids=tuple(
                sorted(int(value) for value in free_flow_rows["id"].unique())
            ),
            walking_proxy_frame_ids=tuple(
                sorted(int(value) for value in free_flow_rows["frame"].unique())
            ),
            fundamental_agent_ids=tuple(
                sorted(int(value) for value in fundamental_positions["id"].unique())
            ),
            fundamental_frame_ids=fundamental_frame_ids,
        ),
    )


def compute_metric_table(
    df: pd.DataFrame,
    *,
    config: MetricConfig | None = None,
) -> dict[str, Any]:
    return compute_metric_bundle(df, config=config).table
