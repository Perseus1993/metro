from __future__ import annotations

from scripts.assess_v01_uat import assess_uat


def test_uat_gate_holds_when_target_user_sessions_are_missing() -> None:
    decision = assess_uat({"schema_version": "uat-results/v1", "sessions": []})

    assert decision["status"] == "hold"
    assert decision["completed_sessions"] == 0
    assert len(decision["issues"]) == 3


def test_uat_gate_accepts_four_of_five_independent_successes_under_budget() -> None:
    sessions = [
        _session(index, successful=index != 5, duration=10 + index) for index in range(1, 6)
    ]

    decision = assess_uat({"schema_version": "uat-results/v1", "sessions": sessions})

    assert decision == {
        "status": "pass",
        "completed_sessions": 5,
        "successful_sessions": 4,
        "success_rate": 0.8,
        "median_minutes": 13.0,
        "issues": [],
    }


def _session(index: int, *, successful: bool, duration: float) -> dict:
    return {
        "session_id": f"UAT-{index:02d}",
        "status": "completed",
        "duration_minutes": duration,
        "independent": successful,
        "task_completed": successful,
        "decision_interpretation_correct": successful,
        "limitations_understood": successful,
    }
