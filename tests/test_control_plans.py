from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from metro_station.application.control_plans import (
    ACCESS_CLOSURE,
    CLOSE,
    DEPLOY,
    OPEN,
    REMOVE,
    WATER_BARRIER,
    ControlEvent,
    ControlMeasure,
    ControlPlan,
    control_plan_from_json,
    control_plan_to_json,
    validate_control_plan_schedule,
)


def control_plan() -> ControlPlan:
    return ControlPlan(
        plan_id="control_ab_01",
        name="Water barrier and gate closure",
        created_at="2026-07-16T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
        measures=(
            ControlMeasure(
                measure_id="water_a",
                kind=WATER_BARRIER,
                label="Water barrier A",
                level_id="l1_terminal",
                parameters={
                    "geometry": {
                        "shape": "rect",
                        "x_m": 50.0,
                        "y_m": 28.0,
                        "width_m": 2.0,
                        "height_m": 1.5,
                    }
                },
            ),
            ControlMeasure(
                measure_id="entry_lane_closure",
                kind=ACCESS_CLOSURE,
                label="Close entry lane 1",
                target_id="entry_gate:gate_bank_a:lane_1",
            ),
        ),
        events=(
            ControlEvent("deploy_water", "water_a", 10, DEPLOY),
            ControlEvent("remove_water", "water_a", 20, REMOVE),
            ControlEvent("close_lane", "entry_lane_closure", 30, CLOSE),
            ControlEvent("open_lane", "entry_lane_closure", 40, OPEN),
        ),
    )


def test_control_plan_round_trip_preserves_semantics_and_fingerprint() -> None:
    original = control_plan()

    restored = control_plan_from_json(control_plan_to_json(original))

    assert restored == original
    assert restored.semantic_fingerprint == original.semantic_fingerprint
    assert restored.as_dict()["schema_version"] == "control-plan/v1"


def test_control_plan_v1_golden_file_matches_contract() -> None:
    fixture = Path("tests/fixtures/control_plans/control_plan_v1.json").read_text(encoding="utf-8")

    restored = control_plan_from_json(fixture)

    assert restored == control_plan()
    assert control_plan_to_json(restored).strip() == fixture.strip()


def test_control_plan_display_metadata_does_not_change_semantic_fingerprint() -> None:
    original = control_plan()
    renamed = replace(original, name="Renamed", metadata={"owner": "class-a"})

    assert renamed.semantic_fingerprint == original.semantic_fingerprint


@pytest.mark.parametrize(
    "events, message",
    [
        (
            (ControlEvent("remove", "water_a", 10, REMOVE),),
            "not active",
        ),
        (
            (
                ControlEvent("deploy", "water_a", 10, DEPLOY),
                ControlEvent("deploy_again", "water_a", 20, DEPLOY),
            ),
            "already active",
        ),
        (
            (
                ControlEvent("deploy", "water_a", 15, DEPLOY),
                ControlEvent("remove", "water_a", 10, REMOVE),
            ),
            "ordered",
        ),
    ],
)
def test_schedule_rejects_invalid_lifecycle(events: tuple[ControlEvent, ...], message: str) -> None:
    plan = replace(control_plan(), events=events)

    with pytest.raises(ValueError, match=message):
        validate_control_plan_schedule(plan, horizon_seconds=60, tick_seconds=5)


def test_schedule_rejects_unaligned_and_out_of_horizon_events() -> None:
    for at_seconds, message in ((7, "align"), (60, "before")):
        plan = replace(
            control_plan(),
            events=(ControlEvent("deploy", "water_a", at_seconds, DEPLOY),),
        )
        with pytest.raises(ValueError, match=message):
            validate_control_plan_schedule(plan, horizon_seconds=60, tick_seconds=5)


def test_contract_rejects_unknown_schema_tamper_and_wrong_action() -> None:
    payload = control_plan().as_dict()
    payload["schema_version"] = "control-plan/v2"
    with pytest.raises(ValueError, match="unsupported"):
        ControlPlan.from_dict(payload)

    tampered = control_plan().as_dict()
    tampered["events"][0]["at_seconds"] = 15
    with pytest.raises(ValueError, match="fingerprint"):
        ControlPlan.from_dict(tampered)

    with pytest.raises(ValueError, match="must be one of"):
        replace(
            control_plan(),
            events=(ControlEvent("wrong", "water_a", 10, CLOSE),),
        )
