from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


PUBLIC_ARTIFACTS = frozenset(
    {"submitted_spec.json", "resolved_spec.json", "summary.json", "run.log",
     "trajectories.parquet", "events.parquet"}
)


class ArtifactStore:
    def __init__(self, jobs_dir: Path) -> None:
        self.jobs_dir = jobs_dir.resolve()

    def job_dir(self, job_id: str) -> Path:
        path = (self.jobs_dir / job_id).resolve()
        if path.parent != self.jobs_dir:
            raise ValueError("invalid job id")
        return path

    def prepare(self, job_id: str) -> Path:
        path = self.job_dir(job_id)
        path.mkdir(parents=True, exist_ok=False)
        (path / "run.log").touch()
        return path

    def write_specs(
        self,
        job_id: str,
        submitted_spec: dict[str, Any],
        resolved_spec: dict[str, Any],
    ) -> None:
        path = self.job_dir(job_id)
        _write_json(path / "submitted_spec.json", submitted_spec)
        _write_json(path / "resolved_spec.json", resolved_spec)

    def write_summary(self, job_id: str, summary: dict[str, Any]) -> None:
        _write_json(self.job_dir(job_id) / "summary.json", summary)

    def remove_private_and_partial(self, job_id: str) -> None:
        path = self.job_dir(job_id)
        for candidate in path.glob("*.partial"):
            candidate.unlink(missing_ok=True)
        (path / "_result.json").unlink(missing_ok=True)

    def remove_failed_results(self, job_id: str) -> None:
        path = self.job_dir(job_id)
        for name in ("trajectories.parquet", "events.parquet", "_result.json"):
            (path / name).unlink(missing_ok=True)

    def list(self, job_id: str) -> list[dict[str, Any]]:
        path = self.job_dir(job_id)
        if not path.exists():
            return []
        result = []
        for item in sorted(path.iterdir()):
            if not item.is_file() or item.name not in PUBLIC_ARTIFACTS:
                continue
            result.append(
                {"name": item.name, "size_bytes": item.stat().st_size, "sha256": sha256(item)}
            )
        return result

    def public_path(self, job_id: str, name: str) -> Path:
        if name not in PUBLIC_ARTIFACTS:
            raise KeyError(name)
        path = self.job_dir(job_id) / name
        if not path.is_file():
            raise KeyError(name)
        return path

    def delete(self, job_id: str) -> None:
        path = self.job_dir(job_id)
        if path.exists():
            shutil.rmtree(path)

    def total_bytes(self) -> int:
        return sum(
            item.stat().st_size
            for item in self.jobs_dir.rglob("*")
            if item.is_file()
        )

    def enforce_budget(self, succeeded_job_ids: list[str], max_bytes: int) -> list[str]:
        removed: list[str] = []
        for job_id in succeeded_job_ids:
            if self.total_bytes() <= max_bytes:
                break
            self.delete(job_id)
            removed.append(job_id)
        return removed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
