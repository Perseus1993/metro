from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable, Mapping


def merge_emergency_evidence(payloads: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    sources = list(payloads)
    if not sources:
        raise ValueError("at least one evidence payload is required")
    versions = {
        source.get("metadata", {}).get("model_evidence_version") for source in sources
    }
    fingerprints = {
        source.get("metadata", {}).get("configuration_fingerprint") for source in sources
    }
    if len(versions) != 1 or None in versions:
        raise ValueError("evidence model versions must match and be non-empty")
    if len(fingerprints) != 1 or None in fingerprints:
        raise ValueError("evidence configuration fingerprints must match and be non-empty")

    rows: dict[str, dict[str, Any]] = {}
    for source in sources:
        for row in source.get("runs", []):
            run_id = str(row.get("run_id", ""))
            if not run_id or run_id in rows:
                raise ValueError(f"duplicate or empty emergency run_id: {run_id!r}")
            rows[run_id] = dict(row)
    merged_rows = sorted(
        rows.values(),
        key=lambda row: (int(row.get("initial_persons", 0)), int(row.get("seed", 0))),
    )
    return {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "case_count": len(merged_rows),
            "source_count": len(sources),
            "model_evidence_version": versions.pop(),
            "configuration_fingerprint": fingerprints.pop(),
        },
        "summary": {
            "runs": len(merged_rows),
            "ok": sum(row.get("status") == "ok" for row in merged_rows),
            "errors": sum(row.get("status") != "ok" for row in merged_rows),
            "acceptance_passed": sum(
                row.get("acceptance_status") == "pass" for row in merged_rows
            ),
            "acceptance_failed": sum(
                row.get("acceptance_status") == "fail" for row in merged_rows
            ),
        },
        "runs": merged_rows,
    }
