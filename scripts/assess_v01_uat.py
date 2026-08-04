from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any


REQUIRED_SESSIONS = 5
REQUIRED_SUCCESSES = 4
MAX_MEDIAN_MINUTES = 30.0


def assess_uat(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != "uat-results/v1":
        raise ValueError("unsupported UAT results schema")
    sessions = payload.get("sessions", [])
    if not isinstance(sessions, list):
        raise ValueError("sessions must be an array")
    completed = [session for session in sessions if session.get("status") == "completed"]
    successful = [session for session in completed if _successful(session)]
    durations = [float(session["duration_minutes"]) for session in completed]
    median_minutes = None if not durations else round(median(durations), 2)
    issues = _issues(len(completed), len(successful), median_minutes)
    return {
        "status": "pass" if not issues else "hold",
        "completed_sessions": len(completed),
        "successful_sessions": len(successful),
        "success_rate": None if not completed else round(len(successful) / len(completed), 3),
        "median_minutes": median_minutes,
        "issues": issues,
    }


def _successful(session: dict[str, Any]) -> bool:
    return all(
        session.get(key) is True
        for key in (
            "independent",
            "task_completed",
            "decision_interpretation_correct",
            "limitations_understood",
        )
    )


def _issues(completed: int, successful: int, median_minutes: float | None) -> list[str]:
    issues = []
    if completed < REQUIRED_SESSIONS:
        issues.append(f"need {REQUIRED_SESSIONS - completed} more completed target-user sessions")
    if successful < REQUIRED_SUCCESSES:
        issues.append(f"need {REQUIRED_SUCCESSES - successful} more successful sessions")
    if median_minutes is None:
        issues.append("median completion time is unavailable")
    elif median_minutes > MAX_MEDIAN_MINUTES:
        issues.append(f"median completion time {median_minutes} exceeds {MAX_MEDIAN_MINUTES}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess V0.1 target-user task evidence.")
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.results.read_text(encoding="utf-8"))
    decision = assess_uat(payload)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
