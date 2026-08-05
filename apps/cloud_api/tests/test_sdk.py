from __future__ import annotations

from pathlib import Path

import httpx

from metro_cloud.client import Client


def test_client_default_is_loopback() -> None:
    client = Client()
    try:
        assert client._http.base_url == httpx.URL("http://127.0.0.1:8000")
    finally:
        client.close()


def test_job_exposes_both_specs(tmp_path: Path) -> None:
    from metro_cloud.job import Job

    client = Client(cache_dir=tmp_path)
    try:
        job = Job(
            client,
            {"id": "one", "status": "queued", "submitted_spec": {"seed": 1},
             "resolved_spec": {"seed": 1, "_derived": {}}},
        )
        assert job.submitted_spec == {"seed": 1}
        assert job.resolved_spec["_derived"] == {}
    finally:
        client.close()


def test_checksum_cache_avoids_redownload(tmp_path: Path) -> None:
    destination = tmp_path / "result.bin"
    destination.write_bytes(b"already here")
    client = Client()
    try:
        from metro_cloud.client import _sha256

        assert client._download("unused", "unused", destination, _sha256(destination)) == destination
    finally:
        client.close()
