from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.design.schema import (
    DesignConnection,
    StationDesignDocument,
)
from metro_station.adapters.simulation.design.station_generation import generate_station

from .layout_exploration_case import LayoutExplorationCase, validate_case_catalog
from .topology_trial_catalog import TOPOLOGY_TRIAL_GENERATOR_VERSION
from .topology_trial_designs import generate_topology_trial_design


def topology_probe_cases() -> tuple[LayoutExplorationCase, ...]:
    cases = (*_u_footprint_cases(), *_platform_cases(), *_invalid_cases())
    validate_case_catalog(cases)
    return cases


def generate_topology_probe_design(case: LayoutExplorationCase) -> StationDesignDocument:
    probe = str(case.factors["probe"])
    if probe == "u_footprint":
        document = generate_topology_trial_design(_u_core_case(case))
        return _with_probe_metadata(document, case)
    baseline = generate_topology_trial_design(_baseline_core_case(case))
    if probe == "platform":
        document = _platform_variant(baseline, str(case.factors["variant"]))
        return _with_probe_metadata(document, case)
    return _invalid_variant(baseline, str(case.factors["variant"]))


def _u_footprint_cases() -> tuple[LayoutExplorationCase, ...]:
    values = (("FULL", False), ("FULL", True), ("DUAL_CLUSTER", False), ("DUAL_CLUSTER", True))
    return tuple(
        LayoutExplorationCase(
            "PM028-E1",
            f"E1-PROBE-U-{vertical}-M{int(mirror)}",
            TOPOLOGY_TRIAL_GENERATOR_VERSION,
            "VALID",
            {"probe": "u_footprint", "vertical": vertical, "mirror": mirror},
            20260800 + index,
        )
        for index, (vertical, mirror) in enumerate(values)
    )


def _platform_cases() -> tuple[LayoutExplorationCase, ...]:
    variants = ("ISLAND", "PAIRED_SIDE", "DUAL_DIRECTION", "TWO_LINE_TRANSFER")
    return tuple(
        LayoutExplorationCase(
            "PM028-E1",
            f"E1-PROBE-PLATFORM-{variant}",
            TOPOLOGY_TRIAL_GENERATOR_VERSION,
            "VALID",
            {"probe": "platform", "variant": variant},
            20260810 + index,
            notes="Static topology and replay support; journey semantics remain model-scoped.",
        )
        for index, variant in enumerate(variants)
    )


def _invalid_cases() -> tuple[LayoutExplorationCase, ...]:
    values = (
        ("PLATFORM_DISCONNECTED", "graph.unreachable_node"),
        ("CONNECTOR_UNKNOWN_LEVEL", "connectors.unknown_level"),
        ("NO_VERTICAL_CONNECTOR", "layout.vertical_connector_required"),
        ("PARTICIPATING_LEVEL_DISCONNECTED", "layout.participating_level_not_connected"),
        ("ONLY_ENTRY_GATES", "layout.required_exit_gate_missing"),
        ("ONLY_EXIT_GATES", "layout.required_entry_gate_missing"),
        ("INVALID_GATE_DIRECTION", "gates.invalid_direction"),
        ("HANGING_PORT", "connections.unknown_source_port"),
    )
    return tuple(
        LayoutExplorationCase(
            "PM028-E1",
            f"E1-PROBE-INVALID-{variant}",
            TOPOLOGY_TRIAL_GENERATOR_VERSION,
            "INVALID",
            {"probe": "invalid", "variant": variant},
            20260820 + index,
            "layout",
            (code,),
        )
        for index, (variant, code) in enumerate(values)
    )


def _baseline_core_case(case: LayoutExplorationCase) -> LayoutExplorationCase:
    return LayoutExplorationCase(
        "PM028-E1",
        f"{case.case_id}-BASE",
        TOPOLOGY_TRIAL_GENERATOR_VERSION,
        "VALID",
        {
            "footprint": "RECT",
            "vertical": "FULL",
            "fare": "BIDIRECTIONAL",
            "mirror": False,
        },
        case.seed,
    )


def _u_core_case(case: LayoutExplorationCase) -> LayoutExplorationCase:
    return replace(
        _baseline_core_case(case),
        factors={
            "footprint": "U",
            "vertical": case.factors["vertical"],
            "fare": "BIDIRECTIONAL",
            "mirror": case.factors["mirror"],
        },
    )


def _platform_variant(
    document: StationDesignDocument,
    variant: str,
) -> StationDesignDocument:
    if variant == "ISLAND":
        return replace(document, metadata={**document.metadata, "platform_variant": variant})
    prototype = next(element for element in document.elements if element.kind == "platform_edge")
    levels = tuple(level.id for level in sorted(document.levels, key=lambda item: item.order))
    level_id = levels[1] if variant == "TWO_LINE_TRANSFER" else levels[-1]
    floor_id = next(
        element.id
        for element in document.elements
        if element.role == "floor" and element.level_id == level_id
    )
    clone = replace(
        prototype,
        id=f"platform_edge_{variant.lower()}",
        label=variant.replace("_", " ").title(),
        level_id=level_id,
        geometry=prototype.geometry.moved_to(12.0, 52.0 if level_id == levels[1] else 38.0),
        direction="up" if prototype.direction == "down" else "down",
        line_id="L2" if variant == "TWO_LINE_TRANSFER" else prototype.line_id,
        ports=(),
    )
    connection = DesignConnection(
        f"conn_{clone.id}_floor",
        floor_id,
        clone.id,
        "walk",
        True,
    )
    mutated = replace(
        document,
        elements=(*document.elements, clone),
        connections=(*document.connections, connection),
        queues=(),
        metadata={**document.metadata, "platform_variant": variant},
    )
    return generate_station(mutated)


def _with_probe_metadata(
    document: StationDesignDocument,
    case: LayoutExplorationCase,
) -> StationDesignDocument:
    return replace(
        document,
        metadata={**document.metadata, "layout_exploration_case": case.as_dict()},
    )


def _invalid_variant(
    document: StationDesignDocument,
    variant: str,
) -> StationDesignDocument:
    if variant == "PLATFORM_DISCONNECTED":
        ids = {element.id for element in document.elements if element.kind == "platform_edge"}
        return replace(
            document,
            connections=tuple(
                item
                for item in document.connections
                if item.source_id not in ids and item.target_id not in ids
            ),
        )
    if variant == "CONNECTOR_UNKNOWN_LEVEL":
        target = next(element for element in document.elements if element.kind == "elevator")
        return replace(
            document,
            elements=tuple(
                replace(item, connects_levels=(*item.connects_levels, "missing_level"))
                if item.id == target.id
                else item
                for item in document.elements
            ),
        )
    if variant in {"NO_VERTICAL_CONNECTOR", "PARTICIPATING_LEVEL_DISCONNECTED"}:
        return _remove_vertical_connectors(document, keep_one=variant.endswith("DISCONNECTED"))
    if variant in {"ONLY_ENTRY_GATES", "ONLY_EXIT_GATES"}:
        direction = "entry" if variant == "ONLY_ENTRY_GATES" else "exit"
        return replace(
            document,
            elements=tuple(
                replace(item, gate_direction=direction) if item.kind == "gate" else item
                for item in document.elements
            ),
        )
    if variant == "INVALID_GATE_DIRECTION":
        gate = next(element for element in document.elements if element.kind == "gate")
        return replace(
            document,
            elements=tuple(
                replace(item, gate_direction="sideways") if item.id == gate.id else item
                for item in document.elements
            ),
        )
    first = document.connections[0]
    return replace(
        document,
        connections=(replace(first, source_port_id="missing_port"), *document.connections[1:]),
    )


def _remove_vertical_connectors(
    document: StationDesignDocument,
    *,
    keep_one: bool,
) -> StationDesignDocument:
    connectors = tuple(item for item in document.elements if item.role == "vertical_connector")
    kept_ids = {connectors[0].id} if keep_one else set()
    removed_ids = {item.id for item in connectors if item.id not in kept_ids}
    elements = tuple(item for item in document.elements if item.id not in removed_ids)
    queues = tuple(item for item in document.queues if item.owner_element_id not in removed_ids)
    connections = tuple(
        item
        for item in document.connections
        if item.source_id not in removed_ids and item.target_id not in removed_ids
    )
    if keep_one:
        only = connectors[0]
        elements = tuple(
            replace(item, connects_levels=only.connects_levels[:2]) if item.id == only.id else item
            for item in elements
        )
    return replace(document, elements=elements, queues=queues, connections=connections)
