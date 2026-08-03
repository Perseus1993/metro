from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from metro_station_testkit.layout_corpus import corpus_coverage
from metro_station_testkit.layout_quality import LayoutQualityReport, inspect_layout_quality
from metro_station_testkit.layout_recipe import ScenarioCorpus
from metro_station_testkit.layout_scenario_generator import generate_layout

from .generated_replay_contract import (
    GeneratedReplayContractReport,
    inspect_generated_replay_contract,
)
from .invalid_layout_diagnostics import (
    InvalidLayoutDiagnosticsReport,
    inspect_invalid_layout_diagnostics,
)


@dataclass(frozen=True)
class GeneratedLayoutAcceptanceRecord:
    recipe_id: str
    recipe_fingerprint: str
    design_fingerprint: str | None
    quality: LayoutQualityReport | None
    replay: GeneratedReplayContractReport | None
    error: str | None
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "recipe_id": self.recipe_id,
            "recipe_fingerprint": self.recipe_fingerprint,
            "design_fingerprint": self.design_fingerprint,
            "quality": None if self.quality is None else self.quality.as_dict(),
            "replay": None if self.replay is None else self.replay.as_dict(),
            "error": self.error,
            "checks": self.checks,
        }


@dataclass(frozen=True)
class GeneratedLayoutAcceptanceReport:
    corpus: ScenarioCorpus
    coverage: dict[str, Any]
    layouts: tuple[GeneratedLayoutAcceptanceRecord, ...]
    invalid_diagnostics: InvalidLayoutDiagnosticsReport
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    @property
    def failed_recipe_ids(self) -> tuple[str, ...]:
        return tuple(layout.recipe_id for layout in self.layouts if layout.status != "ok")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "generated_layout_acceptance.v1",
            "status": self.status,
            "corpus": self.corpus.as_dict(),
            "coverage": self.coverage,
            "unique_design_rate": _unique_design_rate(self.layouts),
            "layouts": [layout.as_dict() for layout in self.layouts],
            "invalid_diagnostics": self.invalid_diagnostics.as_dict(),
            "failed_recipe_ids": self.failed_recipe_ids,
            "checks": self.checks,
        }


def run_generated_layout_acceptance(
    corpus: ScenarioCorpus,
) -> GeneratedLayoutAcceptanceReport:
    layouts = tuple(inspect_generated_recipe(recipe) for recipe in corpus.recipes)
    invalid_diagnostics = inspect_invalid_layout_diagnostics()
    design_fingerprints = tuple(
        layout.design_fingerprint for layout in layouts if layout.design_fingerprint is not None
    )
    restored = ScenarioCorpus.from_dict(corpus.as_dict())
    checks = {
        "all_recipes_reported": tuple(layout.recipe_id for layout in layouts)
        == tuple(recipe.recipe_id for recipe in corpus.recipes),
        "recipe_ids_unique": len({recipe.recipe_id for recipe in corpus.recipes})
        == len(corpus.recipes),
        "all_layouts_pass": bool(layouts) and all(layout.status == "ok" for layout in layouts),
        "design_fingerprints_unique": len(set(design_fingerprints)) == len(layouts),
        "corpus_round_trip_stable": restored.as_dict() == corpus.as_dict(),
        "invalid_layouts_rejected_with_expected_codes": invalid_diagnostics.status == "ok",
    }
    return GeneratedLayoutAcceptanceReport(
        corpus=corpus,
        coverage=corpus_coverage(corpus),
        layouts=layouts,
        invalid_diagnostics=invalid_diagnostics,
        checks=checks,
    )


def inspect_generated_recipe(recipe: Any) -> GeneratedLayoutAcceptanceRecord:
    try:
        document = generate_layout(recipe)
        quality = inspect_layout_quality(document)
        replay = inspect_generated_replay_contract(document)
        checks = {
            "quality_pass": quality.status == "ok",
            "replay_contract_pass": replay.status == "ok",
            "level_count_matches_recipe": quality.level_count == recipe.level_count,
            "elevator_count_matches_recipe": replay.elevator_entity_count == recipe.elevator_count,
            "recipe_embedded_in_design": document.metadata.get("layout_recipe") == recipe.as_dict(),
        }
        return GeneratedLayoutAcceptanceRecord(
            recipe_id=recipe.recipe_id,
            recipe_fingerprint=recipe.semantic_fingerprint,
            design_fingerprint=quality.design_fingerprint,
            quality=quality,
            replay=replay,
            error=None,
            checks=checks,
        )
    except Exception as exc:
        return GeneratedLayoutAcceptanceRecord(
            recipe_id=recipe.recipe_id,
            recipe_fingerprint=recipe.semantic_fingerprint,
            design_fingerprint=None,
            quality=None,
            replay=None,
            error=f"{type(exc).__name__}: {exc}",
            checks={"generation_completed": False},
        )


# Compatibility for callers that used the original private helper during the migration.
_inspect_recipe = inspect_generated_recipe


def _unique_design_rate(layouts: tuple[GeneratedLayoutAcceptanceRecord, ...]) -> float:
    fingerprints = [
        layout.design_fingerprint for layout in layouts if layout.design_fingerprint is not None
    ]
    if not layouts:
        return 0.0
    return round(len(set(fingerprints)) / len(layouts), 6)
