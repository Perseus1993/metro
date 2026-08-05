from __future__ import annotations

from metro_cloud_api.summary import RESULT_DEFAULTS, build_summary


def test_malformed_private_result_cannot_prevent_fixed_summary(tmp_path) -> None:
    (tmp_path / "_result.json").write_text("not-json", encoding="utf-8")
    job = {
        "id": "broken",
        "status": "failed",
        "submitted_spec": {},
        "resolved_spec": {},
        "runner_kind": "fake",
        "runner_version": "0.1.0",
        "created_at": "2026-08-05T00:00:00+00:00",
        "started_at": "2026-08-05T00:00:01+00:00",
        "finished_at": "2026-08-05T00:00:02.250000+00:00",
        "error": {"kind": "invalid_artifact", "message": "bad result"},
    }

    summary = build_summary(job, tmp_path, peak_rss_bytes=123)

    assert set(summary["result"]) == set(RESULT_DEFAULTS)
    assert summary["result"]["passenger_agent_count"] is None
    assert summary["result"]["peak_rss_bytes"] == 123
    assert summary["timing"]["wall_seconds"] == 1.25
