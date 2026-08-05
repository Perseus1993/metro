from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import Client


class Job:
    def __init__(self, client: Client, payload: dict[str, Any]) -> None:
        self._client = client
        self._payload = payload

    @property
    def id(self) -> str:
        return str(self._payload["id"])

    @property
    def status(self) -> str:
        return str(self._payload["status"])

    @property
    def data(self) -> dict[str, Any]:
        return dict(self._payload)

    @property
    def submitted_spec(self) -> dict[str, Any]:
        return dict(self._payload["submitted_spec"])

    @property
    def resolved_spec(self) -> dict[str, Any]:
        return dict(self._payload["resolved_spec"])

    def refresh(self) -> Job:
        self._payload = self._client._json(self._client._http.get(f"/v1/jobs/{self.id}"))
        return self

    def wait(self, *, timeout: float = 3600, poll_seconds: float = 1) -> Job:
        deadline = time.monotonic() + timeout
        while self.status not in {"succeeded", "failed", "cancelled"}:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"job {self.id} did not finish within {timeout} seconds")
            time.sleep(poll_seconds)
            self.refresh()
        return self

    def cancel(self) -> Job:
        self._payload = self._client._json(
            self._client._http.post(f"/v1/jobs/{self.id}/cancel")
        )
        return self

    def artifacts(self) -> list[dict[str, Any]]:
        payload = self._client._json(
            self._client._http.get(f"/v1/jobs/{self.id}/artifacts")
        )
        return list(payload["artifacts"])

    def download(self, name: str, destination: str | Path | None = None) -> Path:
        target = Path(destination or (self._client.cache_dir / self.id / name))
        metadata = next((item for item in self.artifacts() if item["name"] == name), None)
        if metadata is None:
            raise KeyError(f"artifact not found: {name}")
        return self._client._download(self.id, name, target, metadata["sha256"])

    def summary(self) -> dict[str, Any]:
        return json.loads(self.download("summary.json").read_text(encoding="utf-8"))

    def trajectories(self):
        import pandas as pd

        return pd.read_parquet(self.download("trajectories.parquet"))

    def events(self):
        import pandas as pd

        return pd.read_parquet(self.download("events.parquet"))
