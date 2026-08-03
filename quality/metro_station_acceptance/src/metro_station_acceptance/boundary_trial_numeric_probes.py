from __future__ import annotations

from dataclasses import replace
from math import inf, nan

from metro_station.adapters.simulation.compilation.validation import validate_station_design
from metro_station.adapters.simulation.design.schema import DesignElement, ElementGeometry
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario

from .boundary_trial_baseline import boundary_baseline


def run_numeric_probe(field: str, injection: str) -> tuple[bool, tuple[str, ...]]:
    if field == "id":
        return _id_probe(injection)
    value = _injected_value(injection)
    if field == "service_rate":
        valid = _service_rate_valid(value)
    else:
        valid = _design_numeric_valid(field, value)
    if valid:
        return True, ()
    return False, (_normalized_code(field, injection),)


def _design_numeric_valid(field: str, value: float) -> bool:
    document = boundary_baseline()
    if field == "coordinate":
        points = ((0.0, 2.0), (118.0, 2.0), (118.0, 72.0), (0.0, 72.0))
        marker = DesignElement(
            "numeric_coordinate",
            "obstacle",
            document.levels[0].id,
            ElementGeometry("point", x_m=value, y_m=70.0),
            "Numeric coordinate",
        )
        document = replace(
            document,
            levels=tuple(replace(level, footprint=points) for level in document.levels),
            elements=(*document.elements, marker),
        )
    elif field in {"dimension", "rotation"}:
        element = next(item for item in document.elements if item.kind == "shop")
        geometry = element.geometry
        changes = {
            "coordinate": {"x_m": value},
            "dimension": {"width_m": value},
            "rotation": {"rotation_deg": value},
        }[field]
        changed = replace(element, geometry=replace(geometry, **changes))
        document = replace(
            document,
            elements=tuple(changed if item.id == element.id else item for item in document.elements),
        )
    elif field == "floor_height":
        levels = list(document.levels)
        levels[-1] = replace(levels[-1], floor_to_floor_height_m=value)
        document = replace(document, levels=tuple(levels))
    else:
        queue = document.queues[0]
        changed = (
            replace(queue, capacity=value)
            if field == "queue_capacity"
            else replace(queue, spacing_m=value)
        )
        document = replace(document, queues=(changed, *document.queues[1:]))
    issues = validate_station_design(document)
    return not any(issue.severity == "error" for issue in issues)


def _service_rate_valid(value: float) -> bool:
    try:
        StationSandboxScenario(
            station_name="numeric_service_rate",
            hour=18,
            minutes=1,
            tick_seconds=5,
            group_size=1,
            entry_count_hour=0,
            exit_count_hour=0,
            source_label="boundary_trial",
            sample_hours=1,
            gate_service_persons_per_min=value,
            station_design=boundary_baseline(),
        )
    except (OverflowError, TypeError, ValueError):
        return False
    return True


def _id_probe(injection: str) -> tuple[bool, tuple[str, ...]]:
    value = "" if injection == "EMPTY" else "x" * 256
    document = replace(boundary_baseline(), id=value)
    issues = validate_station_design(document)
    return not any(issue.severity == "error" for issue in issues), tuple(
        issue.code for issue in issues
    )


def _injected_value(injection: str) -> float:
    return {
        "NAN": nan,
        "POS_INF": inf,
        "NEG_INF": -inf,
        "NEG_ZERO": -0.0,
        "HUGE": 1e300,
    }[injection]


def _normalized_code(field: str, injection: str) -> str:
    if injection in {"NAN", "POS_INF", "NEG_INF"}:
        return "numbers.non_finite"
    if injection == "NEG_ZERO":
        return "numbers.non_positive"
    return "numbers.out_of_range"
