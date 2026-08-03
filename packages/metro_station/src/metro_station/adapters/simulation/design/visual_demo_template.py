from __future__ import annotations


from .schema import (
    DesignConnection,
    DesignConstraints,
    DesignElement,
    ElementGeometry,
    LevelSpec,
    QueueSpec,
    StationDesignDocument,
)


from .template_support import (
    _with_standard_graph_ports,
    lane,
    polygon,
    polyline,
    rect,
)


def visual_demo_station() -> StationDesignDocument:
    from shapely.geometry import LineString

    from ..presets.visual_demo_config import (
        CANVAS_HEIGHT_PX as H,
        CANVAS_WIDTH_PX as W,
        PIXELS_PER_METER as PX_PER_METER,
    )
    from ..presets.visual_demo_layout import STATION_LAYOUT

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
            metadata={"traversal_width_m": 1.0},
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
            metadata={"traversal_width_m": 1.0},
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
            metadata={"traversal_width_m": 1.0},
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
            metadata={"traversal_width_m": 1.0},
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
            metadata={"traversal_width_m": 2.2},
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
            metadata={"traversal_width_m": 3.0},
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
            *n((0.735, 0.318)),
            0.13 * W / PX_PER_METER,
            0.052 * H / PX_PER_METER,
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
    return _with_standard_graph_ports(
        StationDesignDocument(
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
    )
