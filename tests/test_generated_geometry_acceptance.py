from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from types import SimpleNamespace
from time import monotonic, sleep

import pytest

import scripts.run_layout_acceptance as layout_cli
from metro_station_acceptance import generated_geometry_acceptance as geometry
from metro_station_testkit.layout_corpus import generate_geometry_scenario_matrix
from metro_station_testkit.layout_recipe import ScenarioCorpus


ROOT = Path(__file__).resolve().parents[1]


def test_geometry_matrix_contract_reports_exact_coverage(monkeypatch) -> None:
    _install_fast_compile(monkeypatch)
    monkeypatch.setattr(
        geometry,
        "generate_layout",
        lambda recipe: SimpleNamespace(fingerprint=recipe.recipe_id),
    )
    monkeypatch.setattr(
        geometry,
        "_geometry_fingerprint",
        lambda document: document.fingerprint,
    )

    payload = geometry.run_generated_geometry_acceptance()

    assert payload["status"] == "ok"
    assert payload["recipe_count"] == 240
    assert payload["metrics"]["requested_cell_count"] == 120
    assert payload["metrics"]["effective_seeded_cell_count"] == 160
    assert payload["metrics"]["normalization_probe_count"] == 80
    assert payload["metrics"]["unique_geometry_fingerprint_count"] == 240
    assert payload["metrics"]["largest_geometry_clone_group"] == 1
    assert all(payload["checks"].values())


def test_geometry_gate_rejects_identity_only_document_clones(monkeypatch) -> None:
    _install_fast_compile(monkeypatch)
    monkeypatch.setattr(
        geometry,
        "generate_layout",
        lambda recipe: _IdentityOnlyDocument(recipe.recipe_id),
    )

    payload = geometry.run_generated_geometry_acceptance()

    assert payload["checks"]["matrix_requested_cells_exactly_twice"] is True
    assert payload["checks"]["matrix_has_160_feasible_seeded_cells"] is True
    assert (
        payload["checks"]["matrix_has_at_least_160_unique_physical_layouts"]
        is False
    )
    assert payload["metrics"]["unique_geometry_fingerprint_count"] == 1
    assert payload["metrics"]["largest_geometry_clone_group"] == 240
    assert (
        payload["checks"][
            "matrix_physical_clone_groups_within_normalization_budget"
        ]
        is False
    )
    assert payload["status"] == "review"


def test_geometry_gate_rejects_240_unique_ids_from_one_dimension(
    monkeypatch,
) -> None:
    source = generate_geometry_scenario_matrix().recipes[0]
    clones = tuple(
        replace(source, recipe_id=f"one-dimension-clone-{index:03d}")
        for index in range(240)
    )
    corpus = ScenarioCorpus("one-dimension-clones", source.seed, clones)
    _install_fast_compile(monkeypatch)
    monkeypatch.setattr(geometry, "generate_geometry_scenario_matrix", lambda: corpus)
    monkeypatch.setattr(
        geometry,
        "generate_layout",
        lambda recipe: SimpleNamespace(fingerprint=recipe.recipe_id),
    )
    monkeypatch.setattr(
        geometry,
        "_geometry_fingerprint",
        lambda document: document.fingerprint,
    )

    payload = geometry.run_generated_geometry_acceptance()

    assert payload["checks"]["matrix_recipe_ids_unique"] is True
    assert payload["checks"]["matrix_has_at_least_160_unique_physical_layouts"] is True
    assert payload["checks"]["matrix_requested_cells_exactly_twice"] is False
    assert payload["checks"]["matrix_has_160_feasible_seeded_cells"] is False
    assert payload["status"] == "review"


@pytest.mark.parametrize(
    "unsupported",
    (
        ("--shard-count", "0"),
        ("--generated-count", "-5"),
        ("--generated-only",),
        ("--seeds", "7"),
        ("--layouts", layout_cli.LAYOUT_IDS[0]),
    ),
)
def test_geometry_cli_rejects_unsupported_controls(
    monkeypatch,
    unsupported: tuple[str, ...],
) -> None:
    monkeypatch.setattr(
        layout_cli,
        "run_generated_geometry_acceptance",
        lambda: pytest.fail("geometry gate must not run after invalid CLI options"),
    )

    with pytest.raises(SystemExit) as raised:
        layout_cli.main(("--tier", "geometry", *unsupported))

    assert raised.value.code == 2


def test_geometry_cli_writes_requested_evidence_paths(monkeypatch, tmp_path: Path) -> None:
    output_json = tmp_path / "geometry.json"
    output_markdown = tmp_path / "geometry.md"
    monkeypatch.setattr(
        layout_cli,
        "run_generated_geometry_acceptance",
        lambda: {
            "status": "ok",
            "recipe_count": 240,
            "failed_recipes": (),
            "metrics": {"wall_seconds": 0.01},
            "checks": {"matrix_contract": True},
        },
    )

    code = layout_cli.main(
        (
            "--tier",
            "geometry",
            "--output-json",
            str(output_json),
            "--output-markdown",
            str(output_markdown),
        )
    )

    assert code == 0
    assert output_json.exists()
    assert output_markdown.exists()
    assert "matrix_contract" in output_markdown.read_text(encoding="utf-8")


def test_layout_acceptance_workflow_runs_geometry_tier() -> None:
    workflow = (ROOT / ".github" / "workflows" / "layout-acceptance.yml").read_text(
        encoding="utf-8"
    )

    assert "geometry-acceptance:" in workflow
    assert "--tier geometry" in workflow
    assert "layout-acceptance-geometry" in workflow


def test_geometry_worker_process_compiles_a_real_recipe() -> None:
    recipe = generate_geometry_scenario_matrix().recipes[0]

    records, unfinished = geometry._inspect_recipes(
        (recipe,),
        timeout_seconds=30.0,
    )

    assert unfinished == ()
    assert len(records) == 1
    assert records[0]["recipe_id"] == recipe.recipe_id
    assert records[0]["status"] == "ok"


def test_geometry_worker_deadline_terminates_late_processes() -> None:
    recipe = generate_geometry_scenario_matrix().recipes[0]
    started = monotonic()

    records, unfinished = geometry._inspect_recipes(
        (recipe,),
        timeout_seconds=0.05,
        worker=_slow_geometry_worker,
    )

    assert monotonic() - started < 2.5
    assert unfinished == (recipe.recipe_id,)
    assert records[0]["error_codes"] == ("GeometryAcceptanceTimeout",)


def test_geometry_worker_native_crash_fails_fast_with_typed_error() -> None:
    recipe = generate_geometry_scenario_matrix().recipes[0]
    started = monotonic()

    records, unfinished = geometry._inspect_recipes(
        (recipe,),
        timeout_seconds=5.0,
        worker=_crashing_geometry_worker,
    )

    assert monotonic() - started < 2.5
    assert unfinished == (recipe.recipe_id,)
    assert records[0]["error_codes"] == ("GeometryWorkerCrashed",)
    assert "exitcode=17" in records[0]["error"]


def _install_fast_compile(monkeypatch) -> None:
    monkeypatch.setattr(
        geometry,
        "_inspect_document",
        lambda document, *, case_id: {
            "status": "ok",
            "case_id": case_id,
            "facility_count": 1,
            "binding_count": 1,
            "facility_binding_rate": 1.0,
            "error_codes": (),
            "error": None,
        },
    )
    monkeypatch.setattr(
        geometry,
        "_inspect_recipes",
        lambda recipes, *, timeout_seconds: (
            [geometry._inspect_recipe(recipe) for recipe in recipes],
            (),
        ),
    )


class _IdentityOnlyDocument:
    def __init__(self, identity: str) -> None:
        self.identity = identity

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.identity,
            "label": f"identity {self.identity}",
            "metadata": {"layout_recipe": {"recipe_id": self.identity}},
            "constraints": {"canvas_width_m": 120.0, "canvas_height_m": 80.0},
            "levels": (
                {
                    "id": f"level-{self.identity}",
                    "label": self.identity,
                    "elevation_m": 0.0,
                    "floor_to_floor_height_m": 4.5,
                    "order": 0,
                    "footprint": ((0.0, 0.0), (10.0, 10.0)),
                },
            ),
            "elements": (),
            "queues": (),
            "connections": (),
        }


def _slow_geometry_worker(_recipe):
    sleep(5.0)
    raise AssertionError("deadline must terminate this worker")


def _crashing_geometry_worker(_recipe):
    os._exit(17)
