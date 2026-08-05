from __future__ import annotations

from pathlib import Path

import hashlib
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


def test_partial_download_resumes_with_range(tmp_path: Path) -> None:
    destination = tmp_path / "result.bin"
    partial = destination.with_suffix(".bin.partial")
    partial.write_bytes(b"abc")
    expected = hashlib.sha256(b"abcdef").hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["range"] == "bytes=3-"
        return httpx.Response(
            206,
            content=b"def",
            headers={"Content-Range": "bytes 3-5/6"},
            request=request,
        )

    client = Client()
    client._http.close()
    client._http = httpx.Client(
        base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(handler)
    )
    try:
        assert client._download("job", "result.bin", destination, expected) == destination
        assert destination.read_bytes() == b"abcdef"
        assert not partial.exists()
    finally:
        client.close()
