from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import (
    DesignConnection,
    DesignConstraints,
    DesignElement,
    ElementGeometry,
    LevelSpec,
    QueueSpec,
    StationDesignDocument,
)


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


def rect(x: float, y: float, width: float, height: float) -> ElementGeometry:
    return ElementGeometry("rect", x_m=x, y_m=y, width_m=width, height_m=height)


def polygon(points: tuple[tuple[float, float], ...]) -> ElementGeometry:
    return ElementGeometry("polygon", points_m=points)


def polyline(points: tuple[tuple[float, float], ...]) -> ElementGeometry:
    return ElementGeometry("polyline", points_m=points)


def lane(
    id: str,
    owner: str,
    level: str,
    x: float,
    y: float,
    width: float,
    height: float,
    service_point: tuple[float, float],
    capacity: int,
    direction_deg: float,
    label: str,
) -> QueueSpec:
    return QueueSpec(
        id=id,
        owner_element_id=owner,
        kind="lane",
        level_id=level,
        geometry=rect(x, y, width, height),
        service_point_m=service_point,
        capacity=capacity,
        direction_deg=direction_deg,
        label=label,
    )


def two_level_island_platform() -> StationDesignDocument:
    constraints = DesignConstraints(max_levels=3, max_depth_m=28.0)
    levels = (
        LevelSpec("b1_concourse", "B1 Concourse", -6.0, 6.0, 0, _footprint(4, 4, 112, 42)),
        LevelSpec("b2_platform", "B2 Island Platform", -14.0, 8.0, 1, _footprint(10, 12, 100, 52)),
    )
    elements = (
        DesignElement(
            "b1_main_floor",
            "walkable_area",
            "b1_concourse",
            rect(4, 4, 112, 42),
            "B1 public concourse",
            "floor",
            False,
            True,
        ),
        DesignElement(
            "entrance_a",
            "entrance",
            "b1_concourse",
            rect(5, 19, 2, 7),
            "Entrance A",
            "access",
            False,
            False,
        ),
        DesignElement(
            "b2_platform_floor",
            "walkable_area",
            "b2_platform",
            rect(10, 12, 100, 20),
            "B2 island platform",
            "floor",
            False,
            True,
        ),
        DesignElement(
            "b2_back_corridor",
            "walkable_area",
            "b2_platform",
            rect(10, 4, 100, 8),
            "B2 back corridor",
            "floor",
            False,
            True,
        ),
        DesignElement(
            "gate_bank_a",
            "gate",
            "b1_concourse",
            rect(18, 20, 18, 3.5),
            "Gate bank A",
            "facility",
            True,
            True,
            capacity=6,
            queue_policy={"queue_kind": "lane"},
            gate_direction="bidirectional",
        ),
        DesignElement(
            "shop_a",
            "shop",
            "b1_concourse",
            rect(82, 12, 22, 8),
            "Retail block",
            "facility",
            True,
            True,
        ),
        DesignElement(
            "ticket_machines",
            "equipment",
            "b1_concourse",
            rect(42, 12, 16, 4),
            "Ticket machines",
            "facility",
            True,
            True,
        ),
        DesignElement(
            "down_escalator_a",
            "escalator",
            "b1_concourse",
            rect(24, 34, 7, 14),
            "Down escalator A",
            "vertical_connector",
            True,
            True,
            ("b1_concourse", "b2_platform"),
            70,
            {"queue_kind": "lane"},
            direction="down",
        ),
        DesignElement(
            "up_escalator_a",
            "escalator",
            "b1_concourse",
            rect(38, 34, 7, 14),
            "Up escalator A",
            "vertical_connector",
            True,
            True,
            ("b1_concourse", "b2_platform"),
            70,
            direction="up",
        ),
        DesignElement(
            "stairs_a",
            "stairs",
            "b1_concourse",
            rect(92, 32, 9, 15),
            "Stairs A",
            "vertical_connector",
            True,
            True,
            ("b1_concourse", "b2_platform"),
            120,
            direction="both",
        ),
        DesignElement(
            "elevator_a",
            "elevator",
            "b1_concourse",
            rect(66, 32, 7, 7),
            "Elevator A",
            "vertical_connector",
            True,
            True,
            ("b1_concourse", "b2_platform"),
            16,
            {"queue_kind": "grid"},
            direction="both",
        ),
        DesignElement(
            "platform_edge_a",
            "platform_edge",
            "b2_platform",
            rect(12, 30, 96, 1.2),
            "Platform screen doors",
            "boarding",
            False,
            True,
            line_id="default",
            direction="down",
        ),
    )
    queues = (
        lane(
            "queue_gate_bank_a",
            "gate_bank_a",
            "b1_concourse",
            18,
            24,
            18,
            9,
            (27, 23.5),
            54,
            90,
            "Gate queues",
        ),
        lane(
            "queue_down_escalator_a",
            "down_escalator_a",
            "b1_concourse",
            21,
            25,
            12,
            8,
            (27.5, 34),
            36,
            90,
            "Down escalator queue",
        ),
        QueueSpec(
            "queue_elevator_a",
            "elevator_a",
            "grid",
            "b1_concourse",
            rect(62, 24, 14, 8),
            (69.5, 32),
            42,
            direction_deg=90,
            label="Elevator waiting area",
        ),
        lane(
            "queue_boarding_a",
            "platform_edge_a",
            "b2_platform",
            18,
            21,
            84,
            8,
            (60, 30),
            96,
            90,
            "Boarding queues",
        ),
    )
    connections = (
        DesignConnection("conn_entrance_to_concourse", "entrance_a", "b1_main_floor", "walk"),
        DesignConnection("conn_concourse_to_gates", "b1_main_floor", "gate_bank_a", "walk"),
        DesignConnection("conn_entrance_to_gates", "entrance_a", "gate_bank_a", "walk"),
        DesignConnection("conn_gates_to_down", "gate_bank_a", "down_escalator_a", "walk"),
        DesignConnection("conn_gates_to_up", "gate_bank_a", "up_escalator_a", "walk"),
        DesignConnection("conn_gates_to_stairs", "gate_bank_a", "stairs_a", "walk"),
        DesignConnection("conn_gates_to_elevator", "gate_bank_a", "elevator_a", "walk"),
        DesignConnection(
            "conn_down_to_platform", "down_escalator_a", "b2_platform_floor", "vertical"
        ),
        DesignConnection("conn_up_to_platform", "up_escalator_a", "b2_platform_floor", "vertical"),
        DesignConnection(
            "conn_platform_to_boarding", "b2_platform_floor", "platform_edge_a", "walk"
        ),
        DesignConnection(
            "conn_platform_to_back_corridor", "b2_platform_floor", "b2_back_corridor", "walk"
        ),
        DesignConnection(
            "conn_elevator_to_platform", "elevator_a", "b2_platform_floor", "vertical"
        ),
        DesignConnection("conn_stairs_to_platform", "stairs_a", "b2_platform_floor", "vertical"),
    )
    return StationDesignDocument(
        id="station_design_two_level",
        label="Two-level island platform design",
        template_id="two_level_island_platform",
        constraints=constraints,
        levels=levels,
        elements=elements,
        queues=queues,
        connections=connections,
        metadata={
            "pattern": "document_model_with_editor_adapter",
            "intended_editor": "React Flow / xyflow",
            "source": "design.templates.two_level_island_platform",
        },
    )


def three_level_transfer() -> StationDesignDocument:
    base = two_level_island_platform()
    levels = (
        LevelSpec("b1_concourse", "B1 Concourse", -6.0, 6.0, 0, _footprint(4, 4, 112, 38)),
        LevelSpec("b2_transfer", "B2 Transfer Hall", -13.0, 7.0, 1, _footprint(8, 8, 104, 44)),
        LevelSpec("b3_platform", "B3 Platform", -21.0, 8.0, 2, _footprint(10, 12, 100, 52)),
    )
    remapped = tuple(_three_level_element(element) for element in base.elements)
    transfer_hall = (
        DesignElement(
            "b2_transfer_floor",
            "walkable_area",
            "b2_transfer",
            rect(8, 8, 104, 44),
            "B2 transfer hall",
            "floor",
            False,
            True,
        ),
        DesignElement(
            "transfer_escalator_a",
            "escalator",
            "b2_transfer",
            rect(56, 24, 8, 16),
            "Transfer escalator A",
            "vertical_connector",
            True,
            True,
            ("b2_transfer", "b3_platform"),
            70,
            {"queue_kind": "lane"},
            direction="down",
        ),
    )
    queues = tuple(
        _replace_queue_level(queue, "b2_platform", "b3_platform") for queue in base.queues
    ) + (
        lane(
            "queue_transfer_escalator_a",
            "transfer_escalator_a",
            "b2_transfer",
            52,
            16,
            16,
            8,
            (60, 24),
            42,
            90,
            "Transfer escalator queue",
        ),
    )
    connections = (
        DesignConnection("conn_entrance_to_concourse", "entrance_a", "b1_main_floor", "walk"),
        DesignConnection("conn_concourse_to_gates", "b1_main_floor", "gate_bank_a", "walk"),
        DesignConnection("conn_entrance_to_gates", "entrance_a", "gate_bank_a", "walk"),
        DesignConnection("conn_gates_to_down", "gate_bank_a", "down_escalator_a", "walk"),
        DesignConnection("conn_gates_to_up", "gate_bank_a", "up_escalator_a", "walk"),
        DesignConnection("conn_gates_to_stairs", "gate_bank_a", "stairs_a", "walk"),
        DesignConnection("conn_gates_to_elevator", "gate_bank_a", "elevator_a", "walk"),
        DesignConnection(
            "conn_down_to_transfer", "down_escalator_a", "b2_transfer_floor", "vertical"
        ),
        DesignConnection("conn_up_to_transfer", "up_escalator_a", "b2_transfer_floor", "vertical"),
        DesignConnection("conn_stairs_to_transfer", "stairs_a", "b2_transfer_floor", "vertical"),
        DesignConnection(
            "conn_elevator_to_transfer", "elevator_a", "b2_transfer_floor", "vertical"
        ),
        DesignConnection(
            "conn_elevator_to_platform", "elevator_a", "b3_platform_floor", "vertical"
        ),
        DesignConnection(
            "conn_transfer_floor_to_escalator", "b2_transfer_floor", "transfer_escalator_a", "walk"
        ),
        DesignConnection(
            "conn_transfer_to_platform", "transfer_escalator_a", "b3_platform_floor", "vertical"
        ),
        DesignConnection(
            "conn_platform_to_boarding", "b3_platform_floor", "platform_edge_a", "walk"
        ),
        DesignConnection(
            "conn_platform_to_back_corridor", "b3_platform_floor", "b3_back_corridor", "walk"
        ),
    )
    return StationDesignDocument(
        id="station_design_three_level",
        label="Three-level transfer station design",
        template_id="three_level_transfer",
        constraints=base.constraints,
        levels=levels,
        elements=tuple(element for element in remapped if element.id != "b2_back_corridor")
        + transfer_hall,
        queues=queues,
        connections=connections,
        metadata={
            "pattern": "document_model_with_editor_adapter",
            "intended_editor": "React Flow / xyflow",
            "source": "design.templates.three_level_transfer",
        },
    )


def single_level_terminal() -> StationDesignDocument:
    constraints = DesignConstraints(max_levels=1, max_depth_m=8.0)
    levels = (LevelSpec("l1_terminal", "L1 Terminal Hall", 0.0, 4.5, 0, _footprint(4, 4, 112, 46)),)
    elements = (
        DesignElement(
            "main_hall",
            "walkable_area",
            "l1_terminal",
            rect(4, 4, 112, 46),
            "Terminal hall",
            "floor",
            False,
            True,
        ),
        DesignElement(
            "entrance_a",
            "entrance",
            "l1_terminal",
            rect(5, 19, 2, 7),
            "Entrance A",
            "access",
            False,
            False,
        ),
        DesignElement(
            "gate_bank_a",
            "gate",
            "l1_terminal",
            rect(18, 20, 18, 3.5),
            "Gate bank A",
            capacity=6,
            gate_direction="bidirectional",
        ),
        DesignElement("shop_a", "shop", "l1_terminal", rect(82, 12, 22, 8), "Retail block"),
        DesignElement(
            "platform_edge_a",
            "platform_edge",
            "l1_terminal",
            rect(20, 42, 80, 1.2),
            "Boarding edge",
            "boarding",
            False,
            True,
            line_id="default",
            direction="down",
        ),
    )
    queues = (
        lane(
            "queue_gate_bank_a",
            "gate_bank_a",
            "l1_terminal",
            18,
            24,
            18,
            9,
            (27, 23.5),
            54,
            90,
            "Gate queues",
        ),
        lane(
            "queue_boarding_a",
            "platform_edge_a",
            "l1_terminal",
            24,
            34,
            72,
            8,
            (60, 42),
            84,
            90,
            "Boarding queues",
        ),
    )
    return StationDesignDocument(
        id="station_design_single_level",
        label="Single-level terminal design",
        template_id="single_level_terminal",
        constraints=constraints,
        levels=levels,
        elements=elements,
        queues=queues,
        connections=(
            DesignConnection("conn_entrance_to_hall", "entrance_a", "main_hall", "walk"),
            DesignConnection("conn_hall_to_gate", "main_hall", "gate_bank_a", "walk"),
            DesignConnection("conn_entrance_to_gates", "entrance_a", "gate_bank_a", "walk"),
            DesignConnection("conn_gate_to_boarding", "gate_bank_a", "platform_edge_a", "walk"),
        ),
        metadata={
            "pattern": "document_model_with_editor_adapter",
            "intended_editor": "React Flow / xyflow",
            "source": "design.templates.single_level_terminal",
        },
    )


def visual_demo_station() -> StationDesignDocument:
    from shapely.geometry import LineString

    from ..visual_demo.config import H, PX_PER_METER, W
    from ..visual_demo.layout import STATION_LAYOUT

    def n(point: tuple[float, float]) -> tuple[float, float]:
        return point[0] * W / PX_PER_METER, point[1] * H / PX_PER_METER

    def nr(
        points: tuple[tuple[float, float], ...],
    ) -> tuple[tuple[float, float], ...]:
        return tuple(n(point) for point in points)

    def nr_rect(x: float, y: float, w: float, h: float) -> ElementGeometry:
        x_m, y_m = n((x, y))
        return rect(x_m, y_m, w * W / PX_PER_METER, h * H / PX_PER_METER)

    def level_for_normalized_polygon(points: tuple[tuple[float, float], ...]) -> str:
        mean_y = sum(point[1] for point in points) / max(1, len(points))
        return "b2_platform" if mean_y >= 0.54 else "b1_concourse"

    def channel_geometry(channel) -> ElementGeometry:
        line = LineString(nr(channel.line))
        width_m = float(channel.width_px) / PX_PER_METER
        buffered = line.buffer(width_m / 2.0, cap_style="round", join_style="round")
        return polygon(tuple((float(x), float(y)) for x, y in buffered.exterior.coords))

    constraints = DesignConstraints(
        max_levels=2,
        max_depth_m=20.0,
        canvas_width_m=W / PX_PER_METER,
        canvas_height_m=H / PX_PER_METER,
    )
    levels = (
        LevelSpec(
            "b1_concourse",
            "B1 Concourse",
            -6.0,
            6.0,
            0,
            nr(((0.04, 0.04), (0.98, 0.04), (0.98, 0.54), (0.04, 0.54))),
        ),
        LevelSpec(
            "b2_platform",
            "B2 Platform",
            -14.0,
            8.0,
            1,
            nr(((0.04, 0.56), (0.98, 0.56), (0.98, 0.84), (0.04, 0.84))),
        ),
    )
    platform_door_points = (
        (0.251, 0.785),
        (0.358, 0.785),
        (0.466, 0.785),
        (0.646, 0.785),
        (0.754, 0.785),
        (0.861, 0.785),
    )
    elements = (
        DesignElement(
            "b1_main_floor",
            "walkable_area",
            "b1_concourse",
            polygon(
                nr(
                    (
                        (0.096, 0.314),
                        (0.096, 0.186),
                        (0.145, 0.186),
                        (0.145, 0.135),
                        (0.3, 0.135),
                        (0.308, 0.164),
                        (0.586, 0.164),
                        (0.586, 0.15),
                        (0.722, 0.15),
                        (0.732, 0.134),
                        (0.885, 0.134),
                        (0.909, 0.185),
                        (0.909, 0.308),
                        (0.882, 0.37),
                        (0.74, 0.37),
                        (0.735, 0.414),
                        (0.458, 0.414),
                        (0.452, 0.405),
                        (0.174, 0.405),
                        (0.158, 0.355),
                        (0.112, 0.344),
                    )
                )
            ),
            "B1 concourse",
            "floor",
            False,
            True,
        ),
        DesignElement(
            "b1_left_entry_apron",
            "walkable_area",
            "b1_concourse",
            polygon(nr(((0.065, 0.07), (0.32, 0.07), (0.32, 0.225), (0.065, 0.225)))),
            "Left entry apron",
            "floor",
            False,
            True,
        ),
        DesignElement(
            "b1_right_entry_apron",
            "walkable_area",
            "b1_concourse",
            polygon(
                nr(
                    (
                        (0.785, 0.07),
                        (0.965, 0.07),
                        (0.965, 0.395),
                        (0.785, 0.395),
                    )
                )
            ),
            "Right entry apron",
            "floor",
            False,
            True,
        ),
        DesignElement(
            "b1_vertical_lobby",
            "walkable_area",
            "b1_concourse",
            polygon(nr(((0.145, 0.35), (0.805, 0.35), (0.805, 0.53), (0.145, 0.53)))),
            "B1 vertical lobby",
            "floor",
            False,
            True,
        ),
        DesignElement(
            "b2_platform_floor",
            "walkable_area",
            "b2_platform",
            polygon(
                nr(
                    (
                        (0.126, 0.636),
                        (0.885, 0.636),
                        (0.902, 0.702),
                        (0.842, 0.805),
                        (0.146, 0.805),
                        (0.116, 0.708),
                    )
                )
            ),
            "B2 platform",
            "floor",
            False,
            True,
        ),
        DesignElement(
            "b2_back_corridor",
            "walkable_area",
            "b2_platform",
            polygon(nr(((0.135, 0.575), (0.876, 0.575), (0.884, 0.625), (0.126, 0.625)))),
            "B2 back corridor",
            "floor",
            False,
            True,
        ),
        *(
            DesignElement(
                f"connector_{channel.id}",
                "walkable_area",
                level_for_normalized_polygon(channel.line),
                channel_geometry(channel),
                channel.id.replace("_", " "),
                "floor",
                False,
                True,
                metadata={
                    "visual_kind": channel.kind,
                    "direction": channel.direction,
                    "source_id": channel.id,
                    "graph_node": False,
                },
            )
            for channel in STATION_LAYOUT.connector_channels
        ),
        DesignElement(
            "entrance_left",
            "entrance",
            "b1_concourse",
            nr_rect(0.075, 0.135, 0.04, 0.06),
            "Left entrance",
            "access",
            False,
            False,
        ),
        DesignElement(
            "entrance_right",
            "entrance",
            "b1_concourse",
            nr_rect(0.88, 0.19, 0.04, 0.07),
            "Right entrance",
            "access",
            False,
            False,
        ),
        DesignElement(
            "gate_bank_a",
            "gate",
            "b1_concourse",
            nr_rect(0.205, 0.30, 0.135, 0.066),
            "Entry gate bank",
            capacity=6,
            gate_direction="entry",
        ),
        DesignElement(
            "exit_gate_bank_a",
            "gate",
            "b1_concourse",
            nr_rect(0.7395, 0.252, 0.093, 0.064),
            "Exit gate bank",
            capacity=4,
            gate_direction="exit",
        ),
        DesignElement(
            "down_escalator_a",
            "escalator",
            "b1_concourse",
            polyline(nr(((0.184, 0.428), (0.116, 0.716)))),
            "Down escalator A",
            "vertical_connector",
            True,
            True,
            ("b1_concourse", "b2_platform"),
            75,
            {"queue_kind": "lane"},
            direction="down",
        ),
        DesignElement(
            "down_escalator_b",
            "escalator",
            "b1_concourse",
            polyline(nr(((0.49, 0.428), (0.54, 0.716)))),
            "Down escalator B",
            "vertical_connector",
            True,
            True,
            ("b1_concourse", "b2_platform"),
            75,
            {"queue_kind": "lane"},
            direction="down",
        ),
        DesignElement(
            "up_escalator_a",
            "escalator",
            "b1_concourse",
            polyline(nr(((0.276, 0.428), (0.288, 0.716)))),
            "Up escalator A",
            "vertical_connector",
            True,
            True,
            ("b1_concourse", "b2_platform"),
            75,
            direction="up",
        ),
        DesignElement(
            "up_escalator_b",
            "escalator",
            "b1_concourse",
            polyline(nr(((0.776, 0.428), (0.815, 0.716)))),
            "Up escalator B",
            "vertical_connector",
            True,
            True,
            ("b1_concourse", "b2_platform"),
            75,
            direction="up",
        ),
        DesignElement(
            "elevator_a",
            "elevator",
            "b1_concourse",
            polyline(nr(((0.65, 0.405), (0.65, 0.628)))),
            "Elevator",
            "vertical_connector",
            True,
            True,
            ("b1_concourse", "b2_platform"),
            24,
            {"queue_kind": "grid"},
            direction="both",
        ),
        DesignElement(
            "stairs_a",
            "stairs",
            "b1_concourse",
            polyline(nr(((0.892, 0.426), (0.85, 0.708)))),
            "Stairs",
            "vertical_connector",
            True,
            True,
            ("b1_concourse", "b2_platform"),
            125,
            direction="both",
        ),
        *(
            DesignElement(
                f"platform_edge_{index + 1}",
                "platform_edge",
                "b2_platform",
                nr_rect(door_x - 0.018, door_y - 0.018, 0.036, 0.036),
                f"Platform door {index + 1}",
                "boarding",
                False,
                True,
                line_id="default",
                direction="down",
            )
            for index, (door_x, door_y) in enumerate(platform_door_points)
        ),
        *(
            DesignElement(
                f"obstacle_{obstacle.id}",
                "obstacle",
                level_for_normalized_polygon(obstacle.points),
                polygon(nr(obstacle.points)),
                obstacle.label,
                "obstacle",
                False,
                True,
                metadata={
                    "blocking": obstacle.blocking,
                    "visual_kind": obstacle.kind,
                    "source_id": obstacle.id,
                },
            )
            for obstacle in STATION_LAYOUT.obstacles
        ),
    )
    queues = (
        lane(
            "queue_gate_bank_a",
            "gate_bank_a",
            "b1_concourse",
            *n((0.205, 0.24)),
            0.13 * W / PX_PER_METER,
            0.10 * H / PX_PER_METER,
            n((0.285, 0.338)),
            64,
            90,
            "Entry gate queues",
        ),
        lane(
            "queue_exit_gate_bank_a",
            "exit_gate_bank_a",
            "b1_concourse",
            *n((0.735, 0.245)),
            0.13 * W / PX_PER_METER,
            0.075 * H / PX_PER_METER,
            n((0.800, 0.318)),
            48,
            90,
            "Exit gate queues",
        ),
        lane(
            "queue_down_escalator_a",
            "down_escalator_a",
            "b1_concourse",
            *n((0.20, 0.39)),
            0.12 * W / PX_PER_METER,
            0.08 * H / PX_PER_METER,
            n((0.184, 0.428)),
            36,
            0,
            "Down escalator A queue",
        ),
        lane(
            "queue_down_escalator_b",
            "down_escalator_b",
            "b1_concourse",
            *n((0.52, 0.39)),
            0.12 * W / PX_PER_METER,
            0.08 * H / PX_PER_METER,
            n((0.49, 0.428)),
            36,
            0,
            "Down escalator B queue",
        ),
        QueueSpec(
            "queue_elevator_a",
            "elevator_a",
            "grid",
            "b1_concourse",
            nr_rect(0.59, 0.35, 0.11, 0.08),
            n((0.635, 0.405)),
            42,
            direction_deg=90,
            label="Elevator queue",
        ),
        *(
            lane(
                f"queue_boarding_{index + 1}",
                f"platform_edge_{index + 1}",
                "b2_platform",
                *n((door_x - 0.045, 0.735)),
                0.09 * W / PX_PER_METER,
                0.07 * H / PX_PER_METER,
                n((door_x, _door_y)),
                24,
                90,
                f"Boarding queue {index + 1}",
            )
            for index, (door_x, _door_y) in enumerate(platform_door_points)
        ),
    )
    connections = (
        DesignConnection(
            "conn_left_entry_to_apron",
            "entrance_left",
            "b1_left_entry_apron",
            "walk",
        ),
        DesignConnection(
            "conn_right_entry_to_apron",
            "entrance_right",
            "b1_right_entry_apron",
            "walk",
        ),
        DesignConnection("conn_left_entry_to_hall", "entrance_left", "b1_main_floor", "walk"),
        DesignConnection("conn_right_entry_to_hall", "entrance_right", "b1_main_floor", "walk"),
        DesignConnection("conn_hall_to_gate", "b1_main_floor", "gate_bank_a", "walk"),
        DesignConnection("conn_left_entry_to_gate", "entrance_left", "gate_bank_a", "walk"),
        DesignConnection("conn_right_entry_to_gate", "entrance_right", "gate_bank_a", "walk"),
        DesignConnection("conn_gate_to_lobby", "gate_bank_a", "b1_vertical_lobby", "walk"),
        DesignConnection(
            "conn_lobby_to_exit_gate", "b1_vertical_lobby", "exit_gate_bank_a", "walk"
        ),
        DesignConnection("conn_hall_to_exit_gate", "b1_main_floor", "exit_gate_bank_a", "walk"),
        DesignConnection(
            "conn_exit_gate_to_right_apron",
            "exit_gate_bank_a",
            "b1_right_entry_apron",
            "walk",
        ),
        DesignConnection("conn_gate_to_down_a", "gate_bank_a", "down_escalator_a", "walk"),
        DesignConnection("conn_gate_to_down_b", "gate_bank_a", "down_escalator_b", "walk"),
        DesignConnection("conn_gate_to_elevator", "gate_bank_a", "elevator_a", "walk"),
        DesignConnection("conn_gate_to_stairs", "gate_bank_a", "stairs_a", "walk"),
        DesignConnection(
            "conn_down_a_to_platform", "down_escalator_a", "b2_platform_floor", "vertical"
        ),
        DesignConnection(
            "conn_down_b_to_platform", "down_escalator_b", "b2_platform_floor", "vertical"
        ),
        DesignConnection(
            "conn_elevator_to_platform", "elevator_a", "b2_platform_floor", "vertical"
        ),
        DesignConnection("conn_stairs_to_platform", "stairs_a", "b2_platform_floor", "vertical"),
        *(
            DesignConnection(
                f"conn_platform_to_boarding_{index + 1}",
                "b2_platform_floor",
                f"platform_edge_{index + 1}",
                "walk",
            )
            for index, _point in enumerate(platform_door_points)
        ),
        DesignConnection("conn_platform_to_back", "b2_platform_floor", "b2_back_corridor", "walk"),
        DesignConnection("conn_up_a_to_hall", "up_escalator_a", "b1_main_floor", "vertical"),
        DesignConnection("conn_up_b_to_hall", "up_escalator_b", "b1_main_floor", "vertical"),
    )
    return StationDesignDocument(
        id="station_design_visual_demo",
        label="Visual demo aligned station design",
        template_id="visual_demo_station",
        constraints=constraints,
        levels=levels,
        elements=elements,
        queues=queues,
        connections=connections,
        metadata={
            "pattern": "mesa_jps_animation_demo_unified_pipeline",
            "source": "design.templates.visual_demo_station",
        },
    )


def create_design(template_id: str = "two_level_island_platform") -> StationDesignDocument:
    factories = {
        "two_level_island_platform": two_level_island_platform,
        "three_level_transfer": three_level_transfer,
        "single_level_terminal": single_level_terminal,
        "visual_demo_station": visual_demo_station,
    }
    try:
        return factories[template_id]()
    except KeyError as exc:
        known = ", ".join(sorted(factories))
        raise ValueError(
            f"Unknown station topology template {template_id!r}; choose one of: {known}"
        ) from exc


def _footprint(
    x: float,
    y: float,
    width: float,
    height: float,
) -> tuple[tuple[float, float], ...]:
    return ((x, y), (x + width, y), (x + width, y + height), (x, y + height))


def _replace_level(element: DesignElement, old: str, new: str) -> DesignElement:
    level_id = new if element.level_id == old else element.level_id
    connects_levels = tuple(new if level == old else level for level in element.connects_levels)
    return DesignElement(
        id=element.id.replace(old.removesuffix("_platform"), new.removesuffix("_platform")),
        kind=element.kind,
        level_id=level_id,
        geometry=element.geometry,
        label=element.label,
        role=element.role,
        movable=element.movable,
        resizable=element.resizable,
        connects_levels=connects_levels,
        capacity=element.capacity,
        queue_policy=element.queue_policy,
        metadata=element.metadata,
        gate_direction=element.gate_direction,
        direction=element.direction,
        line_id=element.line_id,
    )


def _three_level_element(element: DesignElement) -> DesignElement:
    if element.role == "vertical_connector" and element.level_id == "b1_concourse":
        connects_levels = ("b1_concourse", "b2_transfer")
        if element.kind == "elevator":
            connects_levels = ("b1_concourse", "b2_transfer", "b3_platform")
        return DesignElement(
            id=element.id,
            kind=element.kind,
            level_id=element.level_id,
            geometry=element.geometry,
            label=element.label,
            role=element.role,
            movable=element.movable,
            resizable=element.resizable,
            connects_levels=connects_levels,
            capacity=element.capacity,
            queue_policy=element.queue_policy,
            metadata=element.metadata,
            gate_direction=element.gate_direction,
            direction=element.direction,
            line_id=element.line_id,
        )
    return _replace_level(element, "b2_platform", "b3_platform")


def _replace_queue_level(queue: QueueSpec, old: str, new: str) -> QueueSpec:
    level_id = new if queue.level_id == old else queue.level_id
    return QueueSpec(
        id=queue.id,
        owner_element_id=queue.owner_element_id,
        kind=queue.kind,
        level_id=level_id,
        geometry=queue.geometry,
        service_point_m=queue.service_point_m,
        capacity=queue.capacity,
        spacing_m=queue.spacing_m,
        direction_deg=queue.direction_deg,
        label=queue.label,
    )
