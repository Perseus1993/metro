from __future__ import annotations

import copy
import json
from dataclasses import replace

import pandas as pd
import pytest

from metro_alignment.canonical import CANONICAL_SCHEMA_VERSION, canonicalize
from metro_alignment.metrics.comparison import (
    build_comparison_payload,
    compare_metric_tables,
    geometry_release_blockers,
    relative_error,
)
from metro_alignment.metrics.fundamental import (
    METRIC_SCHEMA_VERSION,
    WALKING_SPEED_PROXY_KEY,
    MetricConfig,
    analysis_contract_consistency_errors,
    compute_metric_table,
    fundamental_in_band_fraction,
)
from metro_alignment.metro_contract import SCENE_CONFIG_SCHEMA_VERSION


def _walking_trajectory() -> pd.DataFrame:
    records = []
    for agent_id, y_m in ((1, 0.5), (2, 1.5)):
        for frame in range(5):
            records.append(
                {
                    "id": agent_id,
                    "frame": frame,
                    "t": float(frame),
                    "x": float(frame),
                    "y": y_m,
                }
            )
    raw = pd.DataFrame.from_records(records)
    return canonicalize(
        raw,
        dataset_id="synthetic",
        source_time_col="t",
        source_x_col="x",
        source_y_col="y",
        source_agent_col="id",
        source_frame_col="frame",
        x_to_m_scale=1.0,
        t_to_s_scale=1.0,
        agent_id_offset=0,
    )


def _config(area_id: str = "area-v1") -> MetricConfig:
    return MetricConfig(
        frame_rate_hz=1.0,
        speed_window_seconds=2.0,
        measurement_bounds_m=(0.0, 0.0, 10.0, 2.0),
        measurement_area_id=area_id,
        comparison_frame_id="test-shared-frame",
        coordinate_transform_id="identity",
        coordinate_translation_m=(0.0, 0.0),
        free_flow_density_max_p_m2=0.2,
    )


def _as_observed(metrics: dict) -> dict:
    result = copy.deepcopy(metrics)
    for support in result["metric_support"].values():
        support.update(
            {
                "window_n": 1,
                "source_canonical_row_n": 10,
                "unit": "correlated_observed_metric_contributors",
            }
        )
    return result


def _as_simulated(metrics: dict) -> dict:
    result = copy.deepcopy(metrics)
    for support in result["metric_support"].values():
        episode_n = support.pop("agent_n")
        support.update(
            {
                "episode_n": episode_n,
                "passenger_n": episode_n,
                "seed_n": 1,
                "seed_values": [42],
                "unit": "correlated_simulated_metric_contributors",
            }
        )
    return result


def test_metric_table_uses_pedpy_and_explicit_geometry() -> None:
    metrics = compute_metric_table(_walking_trajectory(), config=_config())
    assert metrics["schema_version"] == METRIC_SCHEMA_VERSION
    assert metrics["method"]["library"] == "PedPy"
    assert metrics["method"]["measurement_area"]["id"] == "area-v1"
    assert metrics[WALKING_SPEED_PROXY_KEY]["p50"] == pytest.approx(1.0)
    assert metrics[WALKING_SPEED_PROXY_KEY]["n"] > 0
    assert metrics["fundamental_diagram"]["bins"]
    assert json.loads(json.dumps(metrics, allow_nan=False)) == metrics


def test_fundamental_band_rejects_outliers_and_weights_samples() -> None:
    observed = [
        {
            "density_low_p_m2": 0.0,
            "density_high_p_m2": 0.1,
            "speed_p5": 1.0,
            "speed_p95": 2.0,
            "speed_p50": 1.5,
            "n": 50,
        }
    ]
    outside = [{**observed[0], "speed_p50": 99.0, "n": 50}]
    inside = [{**observed[0], "speed_p50": 1.4, "n": 50}]
    assert fundamental_in_band_fraction(observed, outside)["fraction"] == 0.0
    assert fundamental_in_band_fraction(observed, inside)["fraction"] == 1.0
    assert fundamental_in_band_fraction(observed, inside + outside)["fraction"] == 0.5


def test_fundamental_fit_and_support_are_separate() -> None:
    observed = [
        {
            "density_low_p_m2": 0.0,
            "density_high_p_m2": 0.1,
            "speed_p5": 1.0,
            "speed_p95": 2.0,
            "speed_p50": 1.5,
            "n": 50,
        }
    ]
    simulation = [
        {**observed[0], "n": 50},
        {
            "density_low_p_m2": 0.1,
            "density_high_p_m2": 0.2,
            "speed_p5": 1.0,
            "speed_p95": 2.0,
            "speed_p50": 1.5,
            "n": 50,
        },
    ]
    result = fundamental_in_band_fraction(observed, simulation)
    assert result["conditional_in_band_fraction"] == 1.0
    assert result["support_coverage"] == 0.5


def test_relative_error_zero_baseline_is_never_silent_success() -> None:
    with pytest.raises(ValueError, match="undefined"):
        relative_error(0.0, 999.0)


def test_comparison_marks_zero_and_mismatched_geometry_unavailable() -> None:
    observed = _as_observed(
        compute_metric_table(_walking_trajectory(), config=_config("observed-area"))
    )
    simulated = _as_simulated(
        compute_metric_table(_walking_trajectory(), config=_config("simulated-area"))
    )
    observed[WALKING_SPEED_PROXY_KEY]["p50"] = 0.0
    result = compare_metric_tables(observed, simulated)
    assert result[WALKING_SPEED_PROXY_KEY].verdict == "unavailable"
    assert result["fundamental_support_coverage"].verdict == "unavailable"
    assert result["fundamental_conditional_in_band_fraction"].verdict == "unavailable"


def test_comparison_rejects_same_area_label_with_different_contract_content() -> None:
    observed = _as_observed(
        compute_metric_table(_walking_trajectory(), config=_config("same-area"))
    )
    simulated = _as_simulated(
        compute_metric_table(
            _walking_trajectory(),
            config=replace(_config("same-area"), measurement_bounds_m=(0.0, 0.0, 100.0, 20.0)),
        )
    )
    result = compare_metric_tables(observed, simulated)
    assert all(metric.verdict == "unavailable" for metric in result.values())


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    [
        ("speed", "physical_window_s", 99.0),
        ("density", "method", "unrelated-density"),
        ("walking_speed_proxy", "speed_min_m_s", 2.9),
    ],
)
def test_comparison_rejects_analysis_contract_mutations(section, field, replacement) -> None:
    base = compute_metric_table(_walking_trajectory(), config=_config())
    observed = _as_observed(base)
    simulated = _as_simulated(base)
    simulated["analysis_contract"][section][field] = replacement
    result = compare_metric_tables(observed, simulated)
    assert all(metric.verdict == "unavailable" for metric in result.values())


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("method", "frame_rate_hz"), 123.0),
        (("method", "speed_frame_step"), 99),
        (("method", "speed_frame_step"), 2.5),
        (("method", "speed_frame_step"), True),
        (("method", "speed_frame_step"), "2"),
        (("method", "density"), "unrelated-density"),
        (("method", "config", "walking_speed_min_m_s"), 2.9),
        (("fundamental_diagram", "density_bin_edges"), [0.0, 1.0, 2.0]),
        (("method", "measurement_area", "comparison_polygon_sha256"), "0" * 64),
        (("method", "measurement_area", "bounds_m"), [1e-9, 0.0, 10.0, 2.0]),
        (("method", "config", "measurement_bounds_m"), [1e-9, 0.0, 10.0, 2.0]),
        (
            ("method", "measurement_area", "coordinate_transform", "translation_m"),
            [1e-9, 0.0],
        ),
    ],
)
def test_comparison_rejects_method_payload_that_contradicts_contract(
    path: tuple[str, ...], replacement: object
) -> None:
    base = compute_metric_table(_walking_trajectory(), config=_config())
    observed = _as_observed(base)
    simulated = _as_simulated(base)
    target = simulated
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    result = compare_metric_tables(observed, simulated)
    assert all(metric.verdict == "unavailable" for metric in result.values())


def test_integral_float_frame_step_preserves_exact_pedpy_invocation() -> None:
    metrics = compute_metric_table(_walking_trajectory(), config=_config())
    metrics["method"]["speed_frame_step"] = float(metrics["method"]["speed_frame_step"])
    assert analysis_contract_consistency_errors(metrics) == []


def test_fd_high_density_qualification_requires_supported_bin() -> None:
    def row(low: float, high: float, n: int) -> dict[str, float | int]:
        return {
            "density_low_p_m2": low,
            "density_high_p_m2": high,
            "speed_p5": 1.0,
            "speed_p50": 1.5,
            "speed_p95": 2.0,
            "n": n,
        }

    observed = [row(0.0, 0.1, 30), row(0.1, 0.2, 30), row(0.2, 0.3, 30), row(0.3, 0.5, 1)]
    unsupported = fundamental_in_band_fraction(observed, copy.deepcopy(observed))
    assert unsupported["supported_bin_count"] == 3
    assert unsupported["max_supported_density_high_p_m2"] == 0.3
    observed[-1]["n"] = 30
    supported = fundamental_in_band_fraction(observed, copy.deepcopy(observed))
    assert supported["max_supported_density_high_p_m2"] == 0.5


@pytest.mark.parametrize(
    ("side", "mutation"),
    [
        ("observed", lambda support: support.pop("window_n")),
        ("simulated", lambda support: support.__setitem__("episode_n", 10_000)),
        ("simulated", lambda support: support.__setitem__("seed_values", [])),
        ("simulated", lambda support: support.__setitem__("seed_values", ["bad-seed"])),
    ],
)
def test_comparison_rejects_malformed_metric_contributor_support(side, mutation) -> None:
    base = compute_metric_table(_walking_trajectory(), config=_config())
    observed = _as_observed(base)
    simulated = _as_simulated(base)
    target = observed if side == "observed" else simulated
    mutation(target["metric_support"][WALKING_SPEED_PROXY_KEY])
    result = compare_metric_tables(observed, simulated)
    assert all(metric.verdict == "unavailable" for metric in result.values())


def test_comparison_rejects_duplicate_fundamental_intervals() -> None:
    base = compute_metric_table(_walking_trajectory(), config=_config())
    observed = _as_observed(base)
    simulated = _as_simulated(base)
    row = {
        "density_low_p_m2": 0.3,
        "density_high_p_m2": 0.5,
        "density_p_m2": 0.4,
        "speed_p5": 1.0,
        "speed_p50": 1.5,
        "speed_p95": 2.0,
        "n": 30,
    }
    observed["fundamental_diagram"]["bins"] = [row]
    simulated["fundamental_diagram"]["bins"] = [copy.deepcopy(row) for _ in range(3)]
    observed["metric_support"]["fundamental_diagram"].update(
        {"point_n": 30, "frame_n": 30, "source_canonical_row_n": 100}
    )
    simulated["metric_support"]["fundamental_diagram"].update(
        {"point_n": 90, "frame_n": 90}
    )
    result = compare_metric_tables(observed, simulated)
    assert result["fundamental_support_coverage"].verdict == "unavailable"


def test_comparison_rejects_off_edge_and_unordered_fundamental_intervals() -> None:
    base = compute_metric_table(_walking_trajectory(), config=_config())
    observed = _as_observed(base)
    simulated = _as_simulated(base)
    valid = copy.deepcopy(simulated["fundamental_diagram"]["bins"][0])
    off_edge = {**valid, "density_low_p_m2": 0.05}
    simulated["fundamental_diagram"]["bins"] = [off_edge]
    assert all(
        metric.verdict == "unavailable"
        for metric in compare_metric_tables(observed, simulated).values()
    )
    simulated = _as_simulated(base)
    first = copy.deepcopy(simulated["fundamental_diagram"]["bins"][0])
    second = {**first, "density_low_p_m2": 0.1, "density_high_p_m2": 0.2}
    simulated["fundamental_diagram"]["bins"] = [second, first]
    simulated["metric_support"]["fundamental_diagram"]["frame_n"] = (
        second["n"] + first["n"]
    )
    assert all(
        metric.verdict == "unavailable"
        for metric in compare_metric_tables(observed, simulated).values()
    )


def test_comparison_support_seed_must_match_simulation_manifest_context() -> None:
    base = compute_metric_table(_walking_trajectory(), config=_config())
    observed = _as_observed(base)
    simulated = _as_simulated(base)
    result = compare_metric_tables(
        observed,
        simulated,
        simulated_support_context={"expected_seed": 99},
    )
    assert all(metric.verdict == "unavailable" for metric in result.values())


def test_proxy_geometry_is_always_a_release_blocker() -> None:
    proxy = {
        "scientific_comparability": {
            "release_eligible": False,
            "geometry_evidence": "bounding-box proxy",
            "geometry_evidence_status": "proxy",
            "geometry_evidence_sha256": None,
        }
    }
    assert geometry_release_blockers(
        proxy, trusted_geometry_status="proxy", trusted_evidence_sha256=None
    ) == ["simulation geometry is not observed-matched: bounding-box proxy"]
    forged = {
        "scientific_comparability": {
            "release_eligible": True,
            "geometry_evidence_status": "observed_matched",
            "geometry_evidence_sha256": "a" * 64,
        }
    }
    assert geometry_release_blockers(
        forged, trusted_geometry_status="proxy", trusted_evidence_sha256=None
    )
    assert (
        geometry_release_blockers(
            forged,
            trusted_geometry_status="observed_matched",
            trusted_evidence_sha256="a" * 64,
        )
        == []
    )


def test_comparison_artifact_is_a_deterministic_trusted_input_rebuild() -> None:
    base = compute_metric_table(_walking_trajectory(), config=_config())
    observed = {
        "schema_version": "alignment_observed_metrics.v5",
        "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
        "metric_schema_version": METRIC_SCHEMA_VERSION,
        "dataset_id": "observed-v1",
        "metrics": _as_observed(base),
    }
    simulation = {
        "schema_version": "alignment_simulation_metrics.v5",
        "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
        "metric_schema_version": METRIC_SCHEMA_VERSION,
        "scene_config_schema_version": SCENE_CONFIG_SCHEMA_VERSION,
        "scene_id": "scene-v1",
        "metrics": _as_simulated(base),
        "scientific_comparability": {
            "release_eligible": False,
            "geometry_evidence": "bounding-box proxy",
            "geometry_evidence_status": "proxy",
            "geometry_evidence_sha256": None,
        },
    }
    payload = build_comparison_payload(
        scene_id="scene-v1",
        observed_artifact=observed,
        simulation_artifact=simulation,
        trusted_observed_dataset_id="observed-v1",
        trusted_desired_speed_mps=1.22,
        trusted_geometry_status="proxy",
        trusted_evidence_sha256=None,
        observed_input={"path": "observed.json", "sha256": "a" * 64},
        simulation_input={"path": "simulation.json", "sha256": "b" * 64},
    )
    assert payload["overall_verdict"] == "hold"
    forged = copy.deepcopy(payload)
    forged["overall_verdict"] = "pass"
    assert forged != build_comparison_payload(
        scene_id="scene-v1",
        observed_artifact=observed,
        simulation_artifact=simulation,
        trusted_observed_dataset_id="observed-v1",
        trusted_desired_speed_mps=1.22,
        trusted_geometry_status="proxy",
        trusted_evidence_sha256=None,
        observed_input={"path": "observed.json", "sha256": "a" * 64},
        simulation_input={"path": "simulation.json", "sha256": "b" * 64},
    )
    with pytest.raises(ValueError, match="trusted scene binding"):
        build_comparison_payload(
            scene_id="scene-v1",
            observed_artifact=observed,
            simulation_artifact=simulation,
            trusted_observed_dataset_id="different-observed",
            trusted_desired_speed_mps=1.22,
            trusted_geometry_status="proxy",
            trusted_evidence_sha256=None,
            observed_input={"path": "observed.json", "sha256": "a" * 64},
            simulation_input={"path": "simulation.json", "sha256": "b" * 64},
        )


@pytest.mark.parametrize("side", ["observed", "simulation"])
def test_comparison_builder_rejects_stale_wrapper_schema(side: str) -> None:
    base = compute_metric_table(_walking_trajectory(), config=_config())
    observed = {
        "schema_version": "alignment_observed_metrics.v5",
        "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
        "metric_schema_version": METRIC_SCHEMA_VERSION,
        "dataset_id": "observed-v1",
        "metrics": _as_observed(base),
    }
    simulation = {
        "schema_version": "alignment_simulation_metrics.v5",
        "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
        "metric_schema_version": METRIC_SCHEMA_VERSION,
        "scene_config_schema_version": SCENE_CONFIG_SCHEMA_VERSION,
        "scene_id": "scene-v1",
        "metrics": _as_simulated(base),
        "scientific_comparability": {},
    }
    (observed if side == "observed" else simulation)["schema_version"] = "stale"
    with pytest.raises(ValueError, match=f"{side} artifact wrapper"):
        build_comparison_payload(
            scene_id="scene-v1",
            observed_artifact=observed,
            simulation_artifact=simulation,
            trusted_observed_dataset_id="observed-v1",
            trusted_desired_speed_mps=1.22,
            trusted_geometry_status="proxy",
            trusted_evidence_sha256=None,
            observed_input={"path": "observed.json", "sha256": "a" * 64},
            simulation_input={"path": "simulation.json", "sha256": "b" * 64},
        )
