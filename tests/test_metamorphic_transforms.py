from __future__ import annotations

from metro_station.adapters.simulation.station.graph import StationGraph
from metro_station_testkit.layout_quality import inspect_layout_quality
from metro_station_testkit.metamorphic_bases import generate_metamorphic_base
from metro_station_testkit.metamorphic_catalog import TRANSFORMS
from metro_station_testkit.metamorphic_projection import (
    canonical_design_projection,
    canonical_topology_projection,
)
from metro_station_testkit.metamorphic_transforms import apply_metamorphic_transform


def test_all_100_transformed_designs_remain_valid() -> None:
    for base_index in range(20):
        baseline = generate_metamorphic_base(base_index)
        for transform in TRANSFORMS:
            transformed = apply_metamorphic_transform(
                baseline,
                transform,
                seed=20260800 + base_index,
            )
            report = inspect_layout_quality(transformed)
            assert report.status == "ok", (base_index, transform, report)


def test_order_mirror_decoration_and_translation_preserve_canonical_topology() -> None:
    invariant_transforms = {"M1-REORDER", "M2-MIRROR", "M3-REMOVE-DECOR", "M5-TRANSLATE"}
    for base_index in range(20):
        baseline = generate_metamorphic_base(base_index)
        baseline_graph = StationGraph.from_design(baseline)
        for transform in invariant_transforms:
            transformed = apply_metamorphic_transform(
                baseline,
                transform,
                seed=20260800 + base_index,
            )
            assert canonical_design_projection(transformed) == canonical_design_projection(baseline)
            assert canonical_topology_projection(
                StationGraph.from_design(transformed)
            ) == canonical_topology_projection(baseline_graph)


def test_redundant_elevator_preserves_original_entities_and_adds_one_when_applicable() -> None:
    for base_index in range(20):
        baseline = generate_metamorphic_base(base_index)
        transformed = apply_metamorphic_transform(
            baseline,
            "M4-ADD-ELEVATOR",
            seed=20260800 + base_index,
        )
        before = {element.id for element in baseline.elements}
        after = {element.id for element in transformed.elements}
        if "metamorphic_not_applicable" in transformed.metadata:
            assert before == after
            continue
        assert before <= after
        assert (
            sum(element.kind == "elevator" for element in transformed.elements)
            == sum(element.kind == "elevator" for element in baseline.elements) + 1
        )
