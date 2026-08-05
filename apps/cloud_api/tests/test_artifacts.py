from __future__ import annotations

from metro_cloud_api.artifacts import ArtifactStore


def test_budget_removes_oldest_candidates(settings) -> None:
    settings.ensure_directories()
    artifacts = ArtifactStore(settings.jobs_dir)
    for job_id in ("old", "new"):
        path = artifacts.prepare(job_id)
        (path / "run.log").write_bytes(b"12345")
    removed = artifacts.enforce_budget(["old", "new"], max_bytes=6)
    assert removed == ["old"]
    assert not artifacts.job_dir("old").exists()
    assert artifacts.job_dir("new").exists()
