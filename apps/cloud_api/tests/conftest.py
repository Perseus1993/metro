from __future__ import annotations

from pathlib import Path

import pytest

from metro_cloud_api.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    catalog = Path(__file__).parents[1] / "src" / "metro_cloud_api" / "data" / "catalog.json"
    return Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "jobs.db",
        catalog_path=catalog,
        runner_kind="fake",
        job_timeout_seconds=10,
        max_rss_bytes=512 * 1024**2,
        max_agents=200,
        poll_seconds=0.01,
        api_token=None,
    )
