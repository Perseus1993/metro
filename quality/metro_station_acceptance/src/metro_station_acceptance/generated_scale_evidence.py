from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .generated_scale_acceptance import GENERATED_SCALE_SHARD_SCHEMA_VERSION


def write_generated_scale_record_checkpoint(
    output_dir: Path,
    record: Mapping[str, Any],
    progress: Mapping[str, Any],
) -> None:
    case_dir = output_dir / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    _write_json(case_dir / f"{_safe_name(str(record['recipe_id']))}.json", dict(record))
    config_path = output_dir / "run_config.json"
    if not config_path.exists():
        _write_json(
            config_path,
            {
                "schema_version": GENERATED_SCALE_SHARD_SCHEMA_VERSION,
                "config": {
                    key: value
                    for key, value in progress.items()
                    if key
                    in {
                        "corpus_id",
                        "corpus_fingerprint",
                        "generator_version",
                        "corpus_size",
                        "corpus_recipe_ids",
                        "coverage",
                        "shard_index",
                        "shard_count",
                        "shard_algorithm",
                    }
                },
            },
        )
    _write_json(
        output_dir / "progress.json",
        {
            "schema_version": "generated_scale_progress.v1",
            "completed_cases": progress["completed_cases"],
            "selected_cases": progress["selected_cases"],
            "new_cases": progress["new_cases"],
            "last_recipe_id": record["recipe_id"],
            "last_attempt": progress["attempt"],
        },
    )


def write_generated_scale_evidence(payload: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for record, attempt in zip(payload.get("records", ()), payload.get("attempts", ())):
        write_generated_scale_record_checkpoint(
            output_dir,
            record,
            {
                **dict(payload["config"]),
                "completed_cases": len(tuple(payload.get("records", ()))),
                "selected_cases": len(tuple(payload.get("selected_recipe_ids", ()))),
                "new_cases": int(payload.get("metrics", {}).get("new_cases", 0)),
                "attempt": attempt,
            },
        )
    _write_json(output_dir / "report.json", dict(payload))
    _write_json(output_dir / "manifest.json", dict(payload.get("environment", {})))
    _write_json(output_dir / "coverage.json", dict(payload["config"]["coverage"]))
    (output_dir / "report.md").write_text(
        render_generated_scale_markdown(payload),
        encoding="utf-8",
    )
    for record in payload.get("records", ()):
        if record.get("status") == "ok":
            continue
        failure_dir = output_dir / "failures" / _safe_name(str(record["recipe_id"]))
        failure_dir.mkdir(parents=True, exist_ok=True)
        _write_json(failure_dir / "record.json", dict(record))


def load_generated_scale_resume(path: Path) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    report = path / "report.json"
    if report.exists():
        return json.loads(report.read_text(encoding="utf-8"))
    config_payload = json.loads((path / "run_config.json").read_text(encoding="utf-8"))
    records = tuple(
        json.loads(item.read_text(encoding="utf-8"))
        for item in sorted((path / "cases").glob("*.json"))
    )
    return {
        "schema_version": GENERATED_SCALE_SHARD_SCHEMA_VERSION,
        "run_id": f"checkpoint:{path.name}",
        "config": config_payload["config"],
        "records": records,
        "attempts": (),
    }


def render_generated_scale_markdown(payload: Mapping[str, Any]) -> str:
    metrics = payload.get("metrics", {})
    checks = payload.get("checks", {})
    lines = [
        "# Generated scale shard",
        "",
        f"- Corpus: `{payload['config']['corpus_id']}`",
        f"- Shard: `{payload['config']['shard_index'] + 1}/{payload['config']['shard_count']}`",
        f"- Completed: `{metrics.get('completed_cases', 0)}/{metrics.get('selected_cases', 0)}`",
        f"- Status: **{str(payload.get('status', 'review')).upper()}**",
        f"- Wall seconds: `{metrics.get('wall_seconds', 0)}`",
        f"- Peak traced memory MB: `{metrics.get('peak_traced_memory_mb', 0)}`",
        "",
        "## Blocking checks",
        "",
    ]
    failures = [name for name, passed in checks.items() if not passed]
    lines.extend(f"- `{name}`" for name in failures)
    if not failures:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in value)

