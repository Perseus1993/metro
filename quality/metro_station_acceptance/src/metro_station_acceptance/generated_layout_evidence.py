from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from metro_station_testkit.layout_scenario_generator import generate_layout

from .generated_layout_acceptance import GeneratedLayoutAcceptanceReport
from .generated_simulation_acceptance import GeneratedSimulationAcceptanceReport


def write_generated_layout_evidence(
    report: GeneratedLayoutAcceptanceReport,
    output_dir: Path,
) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        _write_json(output_dir / "corpus.json", report.corpus.as_dict()),
        _write_json(output_dir / "report.json", report.as_dict()),
        _write_text(output_dir / "report.md", render_generated_layout_markdown(report)),
    ]
    recipes = {recipe.recipe_id: recipe for recipe in report.corpus.recipes}
    for record in report.layouts:
        if record.status == "ok":
            continue
        recipe = recipes[record.recipe_id]
        failure_dir = output_dir / "failures" / _safe_name(record.recipe_id)
        failure_dir.mkdir(parents=True, exist_ok=True)
        paths.append(_write_json(failure_dir / "recipe.json", recipe.as_dict()))
        paths.append(_write_json(failure_dir / "record.json", record.as_dict()))
        try:
            document = generate_layout(recipe)
        except Exception as exc:
            paths.append(
                _write_text(
                    failure_dir / "generation_error.txt",
                    f"{type(exc).__name__}: {exc}\n",
                )
            )
        else:
            paths.append(_write_json(failure_dir / "design.json", document.as_dict()))
    return tuple(paths)


def render_generated_layout_markdown(
    report: GeneratedLayoutAcceptanceReport,
) -> str:
    dimensions = report.coverage["dimensions"]
    lines = [
        "# Generated layout acceptance",
        "",
        f"- Corpus: `{report.corpus.corpus_id}`",
        f"- Recipes: `{len(report.corpus.recipes)}`",
        f"- Status: **{report.status.upper()}**",
        f"- Unique design rate: `{report.as_dict()['unique_design_rate']:.1%}`",
        "",
        "## Coverage",
        "",
    ]
    for name in ("archetype", "level_count", "elevator_count", "asset_density"):
        values = ", ".join(f"{key}={value}" for key, value in dimensions[name].items())
        lines.append(f"- `{name}`: {values}")
    lines.extend(["", "## Blocking checks", ""])
    failures = [name for name, passed in report.checks.items() if not passed]
    failures.extend(f"layout.{recipe_id}" for recipe_id in report.failed_recipe_ids)
    if failures:
        lines.extend(f"- `{failure}`" for failure in failures)
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def render_generated_simulation_markdown(
    report: GeneratedSimulationAcceptanceReport,
) -> str:
    lines = [
        "# Generated layout simulation sampling",
        "",
        f"- Tier: `{report.tier}`",
        f"- Samples: `{len(report.records)}`",
        f"- Seeds: `{', '.join(str(seed) for seed in report.seeds)}`",
        f"- Operations included: `{str(report.include_operations).lower()}`",
        f"- Status: **{report.status.upper()}**",
        "",
        "## Samples",
        "",
    ]
    lines.extend(
        f"- `{record.recipe_id}` / `{record.operation_profile}`: {record.status}"
        for record in report.records
    )
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _write_text(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _safe_name(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "-_" else "_" for character in value
    )
