from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from metro_cloud_api.store import JobStore


def _resolved() -> dict:
    return {"_derived": {"horizon_seconds": 300}}


def test_claim_is_atomic(settings) -> None:
    settings.ensure_directories()
    store = JobStore(settings.database_path)
    store.initialize()
    store.create("one", {"a": 1}, _resolved())
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: store.claim_next(), range(2)))
    assert sum(claim is not None for claim in claims) == 1


def test_cancel_queued_job(settings) -> None:
    settings.ensure_directories()
    store = JobStore(settings.database_path)
    store.initialize()
    store.create("one", {}, _resolved())
    assert store.request_cancel("one")["status"] == "cancelled"
    assert store.claim_next() is None
