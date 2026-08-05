from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from . import __version__
from .artifacts import ArtifactStore
from .catalog import Catalog
from .config import Settings
from .spec import resolve_spec
from .store import JobStore
from .summary import build_summary


def create_app(settings: Settings | None = None) -> FastAPI:
    active = settings or Settings.from_env()
    store = JobStore(active.database_path)
    artifacts = ArtifactStore(active.jobs_dir)
    catalog = Catalog.load(active.catalog_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        active.ensure_directories()
        store.initialize()
        yield

    app = FastAPI(title="Metro Cloud API", version=__version__, lifespan=lifespan)
    app.state.settings = active
    app.state.store = store
    app.state.artifacts = artifacts
    app.state.catalog = catalog

    @app.middleware("http")
    async def authenticate(request: Request, call_next: Any) -> Any:
        if active.api_token is None or request.url.path == "/health":
            return await call_next(request)
        if request.headers.get("authorization") != f"Bearer {active.api_token}":
            return JSONResponse(status_code=401, content={"detail": "invalid bearer token"})
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "runner_kind": active.runner_kind}

    @app.get("/v1/catalog")
    def get_catalog() -> dict[str, Any]:
        return {**catalog.raw, "max_agents": active.max_agents}

    @app.post("/v1/jobs", status_code=202)
    def create_job(payload: dict[str, Any]) -> dict[str, Any]:
        if store.count_active() >= active.max_queue:
            raise HTTPException(status_code=429, detail="job queue is full")
        try:
            resolved = resolve_spec(payload, catalog, active.max_agents)
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=_validation_detail(exc)) from exc
        job_id = uuid4().hex
        try:
            artifacts.prepare(job_id)
            artifacts.write_specs(job_id, payload, resolved)
            job = store.create(job_id, payload, resolved)
        except Exception:
            artifacts.delete(job_id)
            raise
        return _job_response(job, store)

    @app.get("/v1/jobs")
    def list_jobs(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        return {"jobs": [_job_response(job, store) for job in store.list(limit=limit)]}

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return _job_response(_get_job(store, job_id), store)

    @app.post("/v1/jobs/{job_id}/cancel", status_code=202)
    def cancel_job(job_id: str) -> dict[str, Any]:
        before = _get_job(store, job_id)
        job = store.request_cancel(job_id)
        if before["status"] == "queued" and job["status"] == "cancelled":
            artifacts.write_summary(job_id, build_summary(job, artifacts.job_dir(job_id)))
        return _job_response(job, store)

    @app.get("/v1/jobs/{job_id}/artifacts")
    def list_artifacts(job_id: str) -> dict[str, Any]:
        _get_job(store, job_id)
        return {"job_id": job_id, "artifacts": artifacts.list(job_id)}

    @app.get("/v1/jobs/{job_id}/artifacts/{name}")
    def download_artifact(job_id: str, name: str) -> FileResponse:
        _get_job(store, job_id)
        try:
            path = artifacts.public_path(job_id, name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="artifact not found") from exc
        return FileResponse(path, filename=name)

    return app


def _get_job(store: JobStore, job_id: str) -> dict[str, Any]:
    try:
        return store.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


def _job_response(job: dict[str, Any], store: JobStore) -> dict[str, Any]:
    return {
        "id": job["id"], "status": job["status"],
        "submitted_spec": job["submitted_spec"], "resolved_spec": job["resolved_spec"],
        "created_at": job["created_at"], "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "progress": {"current": job["progress_current"], "total": job["progress_total"]},
        "queue_position": store.queue_position(job["id"]),
        "runner": {"kind": job["runner_kind"], "version": job["runner_version"]},
        "error": job["error"],
    }


def _validation_detail(exc: ValidationError | ValueError) -> Any:
    if isinstance(exc, ValidationError):
        return exc.errors(include_url=False, include_context=False)
    return str(exc)


app = create_app()
