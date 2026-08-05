from __future__ import annotations

import json

from fastapi.testclient import TestClient

from metro_cloud_api.api import create_app


MINIMAL = {
    "spec_version": "0.1",
    "entry_count_hour": 300,
    "exit_count_hour": 0,
    "transfer_count_hour": 0,
}


def test_submit_and_query(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/jobs", json=MINIMAL)
        assert response.status_code == 202
        job = response.json()
        assert job["status"] == "queued"
        assert job["resolved_spec"]["_derived"]["estimated_passenger_agents"] == 50
        assert client.get(f"/v1/jobs/{job['id']}").status_code == 200


def test_bad_spec_is_400(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/v1/jobs",
            json={
                "spec_version": "0.1",
                "entry_count_hour": 0,
                "exit_count_hour": 0,
                "transfer_count_hour": 0,
            },
        )
        assert response.status_code == 400


def test_token_when_configured(settings) -> None:
    secured = type(settings)(**{**settings.__dict__, "api_token": "secret"})
    with TestClient(create_app(secured)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/catalog").status_code == 401
        assert client.get("/v1/catalog", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_queue_limit(settings) -> None:
    limited = type(settings)(**{**settings.__dict__, "max_queue": 1})
    with TestClient(create_app(limited)) as client:
        assert client.post("/v1/jobs", json=MINIMAL).status_code == 202
        response = client.post("/v1/jobs", json=MINIMAL)
        assert response.status_code == 429


def test_cancel_queued_job_immediately_writes_fixed_shape_summary(settings) -> None:
    with TestClient(create_app(settings)) as client:
        job = client.post("/v1/jobs", json=MINIMAL).json()
        response = client.post(f"/v1/jobs/{job['id']}/cancel")
        assert response.status_code == 202
        assert response.json()["status"] == "cancelled"
        assert response.json()["error"]["kind"] == "cancelled"

        summary_response = client.get(f"/v1/jobs/{job['id']}/artifacts/summary.json")
        assert summary_response.status_code == 200
        summary = json.loads(summary_response.content)
        assert summary["status"] == "cancelled"
        assert summary["timing"]["started_at"] is None
        assert summary["timing"]["wall_seconds"] is None
        assert summary["result"]["passenger_agent_count"] is None
        assert summary["result"]["coordinate_transform"] is None
