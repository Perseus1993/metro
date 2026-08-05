from __future__ import annotations

from pathlib import Path
from typing import Any

import hashlib

import httpx

from .job import Job


class Client:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        token: str | None = None,
        timeout: float = 30,
        cache_dir: str | Path | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self._http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)
        self.cache_dir = Path(cache_dir or ".metro-cloud-cache")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def catalog(self) -> dict[str, Any]:
        return self._json(self._http.get("/v1/catalog"))

    def submit(self, spec: dict[str, Any]) -> Job:
        payload = self._json(self._http.post("/v1/jobs", json=spec))
        return Job(self, payload)

    def job(self, job_id: str) -> Job:
        return Job(self, self._json(self._http.get(f"/v1/jobs/{job_id}")))

    def jobs(self) -> list[Job]:
        payload = self._json(self._http.get("/v1/jobs"))
        return [Job(self, item) for item in payload["jobs"]]

    def _download(
        self, job_id: str, name: str, destination: Path, expected_sha256: str | None = None
    ) -> Path:
        if destination.is_file() and expected_sha256 == _sha256(destination):
            return destination
        partial = destination.with_suffix(destination.suffix + ".partial")
        headers = {"Range": f"bytes={partial.stat().st_size}-"} if partial.exists() else None
        with self._http.stream(
            "GET", f"/v1/jobs/{job_id}/artifacts/{name}", headers=headers
        ) as response:
            response.raise_for_status()
            destination.parent.mkdir(parents=True, exist_ok=True)
            mode = "ab" if response.status_code == 206 and partial.exists() else "wb"
            with partial.open(mode) as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
            if expected_sha256 is not None and _sha256(partial) != expected_sha256:
                raise IOError(f"checksum mismatch for artifact {name}")
            partial.replace(destination)
        return destination

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        response.raise_for_status()
        return response.json()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
