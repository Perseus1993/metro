from __future__ import annotations

from dataclasses import replace

import pytest

from metro_alignment.datasets import get_dataset_spec, registry
from metro_alignment.datasets.registry import (
    FileSpec,
    ObservedAnalysisSpec,
    list_dataset_specs,
)


def test_registry_has_required_fields() -> None:
    for spec in list_dataset_specs():
        assert spec.license.strip()
        assert spec.citation.strip()
        assert spec.coordinate_unit in {"mm", "m"}


def test_known_dataset_lookup() -> None:
    spec = get_dataset_spec("eindhoven_platform_v1")
    assert spec.dataset_id == "eindhoven_platform_v1"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "../escape.bin"},
        {"name": "."},
        {"name": ".."},
        {"name": "CON"},
        {"name": "CON "},
        {"name": "COM1::$DATA"},
        {"name": "data.bin:evil"},
        {"name": "ok."},
        {"name": "ok "},
        {"name": "\tbad.bin"},
        {"name": "a" * 256},
        {"url": "file:///tmp/data"},
        {"url": "https://"},
        {"url": "https://example.test:not-a-port/data.bin"},
        {"md5": "not-a-digest"},
        {"size_bytes": 0},
    ],
)
def test_file_spec_rejects_malformed_contracts(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "name": "data.bin",
        "url": "https://example.test/data.bin",
        "md5": "0" * 32,
        "size_bytes": 1,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        FileSpec(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "dataset_id",
    ["../escape", "UPPER", "bad/name", "bad.id", "", "con", "nul", "com1", "lpt9"],
)
def test_dataset_id_must_be_a_portable_slug(dataset_id: str) -> None:
    with pytest.raises(ValueError, match="portable slug"):
        replace(get_dataset_spec("eindhoven_platform_v1"), dataset_id=dataset_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "future"),
        ("agent_id_offset", True),
        ("agent_id_offset", 1.5),
        ("frame_rate_hz", True),
        ("observed_analysis", "foreign"),
    ],
)
def test_dataset_contract_rejects_runtime_type_and_enum_errors(field, value) -> None:
    with pytest.raises(ValueError):
        replace(get_dataset_spec("eindhoven_platform_v1"), **{field: value})


@pytest.mark.parametrize("translation", [(1.0,), (1.0, 2.0, 3.0)])
def test_observed_analysis_requires_two_translation_coordinates(translation) -> None:
    current = get_dataset_spec("eindhoven_platform_v1").observed_analysis
    assert current is not None
    with pytest.raises(ValueError, match="translation"):
        ObservedAnalysisSpec(
            measurement_bounds_m=current.measurement_bounds_m,
            measurement_area_id=current.measurement_area_id,
            comparison_frame_id=current.comparison_frame_id,
            coordinate_transform_id=current.coordinate_transform_id,
            coordinate_translation_m=translation,
            max_rows=current.max_rows,
            window_count=current.window_count,
        )


def test_registry_rejects_key_mismatch_and_duplicate_dataset_ids(monkeypatch) -> None:
    current = get_dataset_spec("eindhoven_platform_v1")
    monkeypatch.setitem(registry._REGISTRY, "wrong_key", current)
    with pytest.raises(ValueError, match="keys must match"):
        list_dataset_specs()
    monkeypatch.delitem(registry._REGISTRY, "wrong_key")
    duplicate = replace(current, dataset_id="eindhoven_platform_v1")
    monkeypatch.setitem(registry._REGISTRY, "eindhoven_platform_v1_duplicate", duplicate)
    with pytest.raises(ValueError, match="keys must match|duplicate"):
        list_dataset_specs()
