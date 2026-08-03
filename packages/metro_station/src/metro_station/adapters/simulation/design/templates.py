from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .schema import (
    StationDesignDocument,
)
from .standard_templates import (
    single_level_terminal,
    three_level_transfer,
    two_level_island_platform,
)
from .template_support import (
    _with_standard_ports as _with_standard_ports,
    lane as lane,
    polygon as polygon,
    polyline as polyline,
    rect as rect,
    with_standard_graph_contract as with_standard_graph_contract,
)
from .visual_demo_template import visual_demo_station


@dataclass(frozen=True)
class TopologyTemplate:
    id: str
    label: str
    description: str
    max_levels: int
    default_levels: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "max_levels": self.max_levels,
            "default_levels": list(self.default_levels),
        }


def topology_templates() -> tuple[TopologyTemplate, ...]:
    return (
        TopologyTemplate(
            id="two_level_island_platform",
            label="Two-level island platform",
            description="Concourse above a single island platform, with gates, vertical transfer, and boarding queues.",
            max_levels=2,
            default_levels=("b1_concourse", "b2_platform"),
        ),
        TopologyTemplate(
            id="three_level_transfer",
            label="Three-level transfer station",
            description="Concourse, mezzanine transfer hall, and platform level for a deeper station.",
            max_levels=3,
            default_levels=("b1_concourse", "b2_transfer", "b3_platform"),
        ),
        TopologyTemplate(
            id="single_level_terminal",
            label="Single-level terminal hall",
            description="Compact one-level station shell for gate and platform operations in the same plane.",
            max_levels=1,
            default_levels=("l1_terminal",),
        ),
        TopologyTemplate(
            id="visual_demo_station",
            label="Visual demo station",
            description="Two-level station geometry aligned with visual_demo/animation_demo.html.",
            max_levels=2,
            default_levels=("b1_concourse", "b2_platform"),
        ),
    )


def scratch_topology_templates() -> tuple[TopologyTemplate, ...]:
    return (
        TopologyTemplate(
            id="scratch_single_level",
            label="Build: single-level station",
            description="Empty one-level floor for dragging gates, platforms, and passenger flows.",
            max_levels=1,
            default_levels=("l1_station",),
        ),
        TopologyTemplate(
            id="scratch_two_level",
            label="Build: two-level station",
            description="Empty concourse and platform floors for building a vertical station.",
            max_levels=2,
            default_levels=("b1_concourse", "b2_platform"),
        ),
        TopologyTemplate(
            id="scratch_three_level",
            label="Build: three-level station",
            description="Empty concourse, transfer, and platform floors for a deep station.",
            max_levels=3,
            default_levels=("b1_concourse", "b2_transfer", "b3_platform"),
        ),
    )


def create_design(template_id: str = "two_level_island_platform") -> StationDesignDocument:
    factories = {
        "two_level_island_platform": two_level_island_platform,
        "three_level_transfer": three_level_transfer,
        "single_level_terminal": single_level_terminal,
        "visual_demo_station": visual_demo_station,
    }
    if template_id.startswith("scratch_"):
        from .scratch_templates import SCRATCH_TEMPLATE_LEVELS, create_scratch_design

        if template_id in SCRATCH_TEMPLATE_LEVELS:
            return create_scratch_design(template_id)
    try:
        document = factories[template_id]()
    except KeyError as exc:
        from .scratch_templates import SCRATCH_TEMPLATE_LEVELS

        known = ", ".join(sorted((*factories, *SCRATCH_TEMPLATE_LEVELS)))
        raise ValueError(
            f"Unknown station topology template {template_id!r}; choose one of: {known}"
        ) from exc
    from .station_generation import with_generated_queues

    return replace(document, queues=with_generated_queues(document))
