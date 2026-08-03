from __future__ import annotations

from metro_station.adapters.simulation.design.templates import create_design
from metro_station.application.control_plans import ONE_WAY_CHANNEL, STAFF_GUIDANCE
from metro_station_designer.control_plan_catalog import build_control_plan_catalog


def test_catalog_unlocks_all_v02_control_measure_runtimes() -> None:
    catalog = build_control_plan_catalog(
        create_design("visual_demo_station"),
        {"hour": 18},
    )
    definitions = {item["kind"]: item for item in catalog["measure_types"]}

    assert len(definitions) == 7
    assert {item["runtime_status"] for item in definitions.values()} == {"available"}
    assert definitions[ONE_WAY_CHANNEL]["directions"] == ["forward", "reverse"]
    assert definitions[STAFF_GUIDANCE]["placement"] == "facility"
    assert any(target["kind"] == "escalator" for target in catalog["facility_targets"])
