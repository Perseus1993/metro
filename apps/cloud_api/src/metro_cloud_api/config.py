from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    catalog_path: Path
    runner_kind: str
    job_timeout_seconds: float
    max_rss_bytes: int
    max_agents: int
    poll_seconds: float
    api_token: str | None
    max_queue: int = 50
    max_artifact_bytes: int = 2 * 1024**3

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = _env_path("METRO_DATA_DIR", "./data")
        package_catalog = Path(__file__).parent / "data" / "catalog.json"
        return cls(
            data_dir=data_dir,
            database_path=_env_path("METRO_DATABASE_PATH", str(data_dir / "jobs.db")),
            catalog_path=_env_path("METRO_CATALOG_PATH", str(package_catalog)),
            runner_kind=os.environ.get("METRO_RUNNER", "fake"),
            job_timeout_seconds=float(os.environ.get("METRO_JOB_TIMEOUT_SECONDS", "14400")),
            max_rss_bytes=int(os.environ.get("METRO_MAX_RSS_BYTES", str(3 * 1024**3))),
            max_agents=int(os.environ.get("METRO_MAX_AGENTS", "50")),
            poll_seconds=float(os.environ.get("METRO_WORKER_POLL_SECONDS", "1")),
            api_token=os.environ.get("METRO_API_TOKEN") or None,
            max_queue=int(os.environ.get("METRO_MAX_QUEUE", "50")),
            max_artifact_bytes=int(
                os.environ.get("METRO_MAX_ARTIFACT_BYTES", str(2 * 1024**3))
            ),
        )

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
