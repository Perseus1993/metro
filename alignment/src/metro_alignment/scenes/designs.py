from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.design.schema import (
    DesignConnection,
    DesignConstraints,
    DesignElement,
    LevelSpec,
    StationDesignDocument,
)
from metro_station.adapters.simulation.design.station_generation import with_generated_queues
from metro_station.adapters.simulation.design.template_support import (
    rect,
    with_standard_graph_contract,
)
from metro_station.adapters.simulation.design.validation import validate_design

from .base import SceneConfig
from .platform_boarding import PlatformBoardingConfig


def build_station_design(config: SceneConfig) -> StationDesignDocument:
    if config.status != "ready":
        raise RuntimeError(f"scene {config.scene_id} is pending: {config.pending_reason}")
    if not isinstance(config, PlatformBoardingConfig):
        raise TypeError(f"no design compiler registered for {type(config).__name__}")
    design = _build_platform_design(config)
    issues = validate_design(design)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in errors)
        raise ValueError(f"compiled alignment design is invalid: {details}")
    return design


def _build_platform_design(config: PlatformBoardingConfig) -> StationDesignDocument:
    x_m, y_m = 4.0, 10.0
    length = float(config.platform_length_m)
    width = float(config.platform_width_m)
    max_x, max_y = x_m + length, y_m + width
    gate_width = max(4.0, min(10.0, length * 0.22))
    edge_width = max(12.0, min(length - config.train_door_x_m - 2.0, 40.0))
    edge_x = x_m + float(config.train_door_x_m)
    footprint = ((x_m, y_m), (max_x, y_m), (max_x, max_y), (x_m, max_y))

    elements = (
        DesignElement(
            "main_hall",
            "walkable_area",
            "l1_platform",
            rect(x_m, y_m, length, width),
            "Eindhoven-sized platform proxy",
            "floor",
            False,
            True,
        ),
        DesignElement(
            "entrance_a",
            "entrance",
            "l1_platform",
            rect(x_m + 0.5, y_m + width * 0.35, 2.0, min(4.0, width * 0.3)),
            "Platform access",
            "access",
            False,
            False,
        ),
        DesignElement(
            "gate_bank_a",
            "gate",
            "l1_platform",
            rect(x_m + 8.0, y_m + 8.0, gate_width, 2.0),
            "Gate bank",
            capacity=max(1, int(gate_width // 1.5)),
            gate_direction="bidirectional",
        ),
        DesignElement(
            "platform_edge_a",
            "platform_edge",
            "l1_platform",
            rect(edge_x, max_y - 1.2, edge_width, 1.2),
            "Boarding edge",
            "boarding",
            False,
            True,
            line_id="default",
            direction="down",
        ),
    )
    document = StationDesignDocument(
        id=f"alignment_{config.scene_id}",
        label="Alignment platform proxy",
        template_id="alignment_platform_proxy_v1",
        constraints=DesignConstraints(
            max_levels=1,
            max_depth_m=8.0,
            canvas_width_m=max(120.0, max_x + 4.0),
            canvas_height_m=max(40.0, max_y + 4.0),
        ),
        levels=(LevelSpec("l1_platform", "L1 Platform", 0.0, 4.5, 0, footprint),),
        elements=elements,
        connections=(
            DesignConnection("conn_access_hall", "entrance_a", "main_hall"),
            DesignConnection("conn_hall_gate", "main_hall", "gate_bank_a"),
            DesignConnection("conn_gate_boarding", "gate_bank_a", "platform_edge_a"),
        ),
        metadata={
            "alignment_scene_id": config.scene_id,
            "geometry_evidence": "Eindhoven bounding-box dimensions; internal obstacles are a proxy",
            "platform_length_m": length,
            "platform_width_m": width,
            "train_door_x_m": float(config.train_door_x_m),
        },
    )
    document = with_standard_graph_contract(document)
    return replace(document, queues=with_generated_queues(document))
