from __future__ import annotations

from dataclasses import dataclass, field

from .visual_demo_facilities import ELEVATOR


@dataclass(frozen=True)
class LayoutElement:
    id: str
    role: str
    kind: str
    layer: str
    geometry: dict[str, object]
    label: str
    z_index: int
    locked: bool = False
    draggable: bool = True
    style: dict[str, object] = field(default_factory=dict)
    meta: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "role": self.role,
            "kind": self.kind,
            "layer": self.layer,
            "geometry": self.geometry,
            "label": self.label,
            "z_index": self.z_index,
            "locked": self.locked,
            "draggable": self.draggable,
            "style": self.style,
            "meta": self.meta,
        }


@dataclass(frozen=True)
class PolygonShape:
    id: str
    label: str
    points: tuple[tuple[float, float], ...]
    kind: str = "floor"
    blocking: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "blocking": self.blocking,
            "points": [list(point) for point in self.points],
        }


@dataclass(frozen=True)
class ConnectorChannel:
    id: str
    kind: str
    direction: str
    width_px: float
    line: tuple[tuple[float, float], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "direction": self.direction,
            "width_px": self.width_px,
            "line": [list(point) for point in self.line],
        }


@dataclass(frozen=True)
class StationLayout:
    walkable_regions: tuple[PolygonShape, ...]
    connector_channels: tuple[ConnectorChannel, ...]
    obstacles: tuple[PolygonShape, ...]
    facility_boxes: tuple[PolygonShape, ...]
    control_points: dict[str, tuple[tuple[float, float], ...]]
    decision_regions: tuple[PolygonShape, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "coordinate_system": "normalized_image_xy",
            "walkable_regions": [region.as_dict() for region in self.walkable_regions],
            "connector_channels": [channel.as_dict() for channel in self.connector_channels],
            "obstacles": [obstacle.as_dict() for obstacle in self.obstacles],
            "facility_boxes": [facility.as_dict() for facility in self.facility_boxes],
            "decision_regions": [region.as_dict() for region in self.decision_regions],
            "control_points": {
                key: [list(point) for point in points]
                for key, points in self.control_points.items()
            },
        }


def rect_points(x: float, y: float, w: float, h: float) -> tuple[tuple[float, float], ...]:
    return ((x, y), (x + w, y), (x + w, y + h), (x, y + h))


def gate_boxes() -> tuple[PolygonShape, ...]:
    boxes: list[PolygonShape] = []
    for index, x in enumerate((0.210, 0.235, 0.260, 0.285, 0.310, 0.335), start=1):
        boxes.append(
            PolygonShape(
                id=f"entry_gate_{index}",
                label=f"entry gate {index}",
                kind="gate",
                blocking=False,
                points=rect_points(x - 0.0045, 0.300, 0.009, 0.066),
            )
        )
    return tuple(boxes)


def exit_gate_boxes() -> tuple[PolygonShape, ...]:
    boxes: list[PolygonShape] = []
    for index, x in enumerate((0.744, 0.772, 0.800, 0.828), start=1):
        boxes.append(
            PolygonShape(
                id=f"exit_gate_{index}",
                label=f"exit gate {index}",
                kind="gate",
                blocking=False,
                points=rect_points(x - 0.0045, 0.252, 0.009, 0.064),
            )
        )
    return tuple(boxes)


def decision_regions() -> tuple[PolygonShape, ...]:
    return (
        PolygonShape(
            "entry_gate_decision",
            "entry gate lane decision",
            rect_points(0.205, 0.240, 0.130, 0.102),
            "entry_gate_decision",
            False,
        ),
        PolygonShape(
            "vertical_transfer_decision",
            "vertical transfer decision",
            rect_points(0.145, 0.350, 0.660, 0.085),
            "vertical_transfer_decision",
            False,
        ),
        PolygonShape(
            "platform_boarding_decision",
            "platform boarding door decision",
            rect_points(0.160, 0.705, 0.710, 0.100),
            "platform_boarding_decision",
            False,
        ),
        PolygonShape(
            "exit_vertical_decision",
            "exit vertical transfer decision",
            rect_points(0.120, 0.635, 0.760, 0.085),
            "exit_vertical_decision",
            False,
        ),
        PolygonShape(
            "exit_gate_decision",
            "exit gate lane decision",
            rect_points(0.735, 0.318, 0.130, 0.052),
            "exit_gate_decision",
            False,
        ),
    )


def fare_barrier_boxes() -> tuple[PolygonShape, ...]:
    """Collision walls separating unpaid and paid areas, with gate openings."""

    def segmented_barrier(
        *,
        prefix: str,
        label: str,
        x_start: float,
        x_end: float,
        y: float,
        height: float,
        openings: tuple[float, ...],
        opening_half_width: float,
    ) -> list[PolygonShape]:
        segments: list[PolygonShape] = []
        cursor = x_start
        for index, center in enumerate(sorted(openings), start=1):
            opening_start = max(x_start, center - opening_half_width)
            opening_end = min(x_end, center + opening_half_width)
            if opening_start > cursor:
                segments.append(
                    PolygonShape(
                        id=f"{prefix}_{index}",
                        label=f"{label} segment {index}",
                        kind="fare_barrier",
                        blocking=True,
                        points=rect_points(cursor, y, opening_start - cursor, height),
                    )
                )
            cursor = max(cursor, opening_end)
        if cursor < x_end:
            segments.append(
                PolygonShape(
                    id=f"{prefix}_{len(segments) + 1}",
                    label=f"{label} segment {len(segments) + 1}",
                    kind="fare_barrier",
                    blocking=True,
                    points=rect_points(cursor, y, x_end - cursor, height),
                )
            )
        return segments

    return tuple(
        [
            *segmented_barrier(
                prefix="entry_fare_barrier",
                label="entry fare barrier",
                x_start=0.158,
                x_end=0.710,
                y=0.346,
                height=0.012,
                openings=(0.210, 0.235, 0.260, 0.285, 0.310, 0.335),
                opening_half_width=0.0078,
            ),
            *segmented_barrier(
                prefix="exit_fare_barrier",
                label="exit fare barrier",
                x_start=0.710,
                x_end=0.875,
                y=0.303,
                height=0.013,
                openings=(0.744, 0.772, 0.800, 0.828),
                opening_half_width=0.0085,
            ),
        ]
    )


def polygon_element(shape: PolygonShape, role: str, layer: str, z_index: int) -> LayoutElement:
    return LayoutElement(
        id=shape.id,
        role=role,
        kind=shape.kind,
        layer=layer,
        geometry={
            "type": "polygon",
            "points": [list(point) for point in shape.points],
        },
        label=shape.label,
        z_index=z_index,
        locked=role == "track",
        draggable=role != "track",
        meta={
            "blocking": shape.blocking,
            "edit_handles": "vertices",
            "snap_group": "station_geometry",
        },
    )


def channel_element(channel: ConnectorChannel) -> LayoutElement:
    return LayoutElement(
        id=channel.id,
        role="connector",
        kind=channel.kind,
        layer="connectors",
        geometry={
            "type": "polyline",
            "points": [list(point) for point in channel.line],
            "width_px": channel.width_px,
        },
        label=channel.id.replace("_", " "),
        z_index=40,
        locked=False,
        draggable=True,
        meta={
            "direction": channel.direction,
            "edit_handles": "polyline_vertices",
            "snap_group": "facility_connectors",
        },
    )


STATION_LAYOUT = StationLayout(
    walkable_regions=(
        PolygonShape(
            id="b1_concourse",
            label="B1 station concourse walkable floor",
            points=(
                (0.096, 0.314),
                (0.096, 0.186),
                (0.145, 0.186),
                (0.145, 0.135),
                (0.300, 0.135),
                (0.308, 0.164),
                (0.586, 0.164),
                (0.586, 0.150),
                (0.722, 0.150),
                (0.732, 0.134),
                (0.885, 0.134),
                (0.909, 0.185),
                (0.909, 0.308),
                (0.882, 0.370),
                (0.740, 0.370),
                (0.735, 0.414),
                (0.458, 0.414),
                (0.452, 0.405),
                (0.174, 0.405),
                (0.158, 0.355),
                (0.112, 0.344),
            ),
        ),
        PolygonShape(
            id="b1_left_entry_apron",
            label="B1 left entrance external arrival buffer",
            points=rect_points(0.065, 0.070, 0.255, 0.155),
        ),
        PolygonShape(
            id="b1_right_entry_apron",
            label="B1 right entrance external arrival buffer",
            points=rect_points(0.785, 0.070, 0.180, 0.325),
        ),
        PolygonShape(
            id="b1_vertical_transfer_lobby",
            label="B1 vertical transport queue and transfer buffer",
            points=rect_points(0.145, 0.350, 0.660, 0.180),
        ),
        PolygonShape(
            id="b2_platform",
            label="B2 island platform walkable floor",
            points=(
                (0.126, 0.636),
                (0.885, 0.636),
                (0.902, 0.702),
                (0.842, 0.805),
                (0.146, 0.805),
                (0.116, 0.708),
            ),
        ),
        PolygonShape(
            id="b2_back_corridor",
            label="B2 back circulation strip behind platform screen doors",
            points=(
                (0.135, 0.575),
                (0.876, 0.575),
                (0.884, 0.625),
                (0.126, 0.625),
            ),
        ),
    ),
    connector_channels=(
        ConnectorChannel(
            "down_escalator_1", "escalator", "down", 58, ((0.184, 0.428), (0.116, 0.716))
        ),
        ConnectorChannel("up_escalator_1", "escalator", "up", 58, ((0.288, 0.716), (0.276, 0.428))),
        ConnectorChannel(
            "down_escalator_2", "escalator", "down", 58, ((0.490, 0.428), (0.540, 0.716))
        ),
        ConnectorChannel("up_escalator_2", "escalator", "up", 58, ((0.815, 0.716), (0.776, 0.428))),
        ConnectorChannel("stairs", "stairs", "both", 50, ((0.892, 0.426), (0.850, 0.708))),
        ConnectorChannel(
            "elevator_lobby_b1", "elevator_lobby", "both", 60, ((0.612, 0.383), (0.650, 0.405))
        ),
        ConnectorChannel(
            "elevator_shaft", "elevator", "both", 78, ((0.650, 0.405), (0.650, 0.628))
        ),
        ConnectorChannel(
            "elevator_lobby_b2",
            "elevator_lobby",
            "both",
            60,
            ((0.650, 0.628), (0.625, 0.654), (0.560, 0.716)),
        ),
    ),
    obstacles=(
        PolygonShape(
            "service_center_left",
            "B1 service center room",
            rect_points(0.055, 0.250, 0.083, 0.090),
            "room",
            False,
        ),
        PolygonShape(
            "ticket_machine_bank",
            "B1 vending machines and map wall",
            rect_points(0.300, 0.185, 0.132, 0.070),
            "equipment",
        ),
        PolygonShape(
            "center_ad_planter",
            "B1 central ad board and planter",
            rect_points(0.486, 0.240, 0.049, 0.093),
            "equipment",
        ),
        PolygonShape(
            "restroom_block",
            "B1 restroom/service rooms",
            rect_points(0.604, 0.176, 0.096, 0.069),
            "room",
            False,
        ),
        PolygonShape(
            "shop_block",
            "B1 convenience and cafe block",
            rect_points(0.710, 0.318, 0.165, 0.056),
            "shop",
            False,
        ),
        PolygonShape(
            "platform_sign_center",
            "B2 station sign and posts",
            rect_points(0.365, 0.637, 0.060, 0.065),
            "equipment",
            False,
        ),
        PolygonShape(
            "platform_bench_left",
            "B2 left bench",
            rect_points(0.220, 0.687, 0.064, 0.031),
            "bench",
            False,
        ),
        PolygonShape(
            "platform_bench_mid",
            "B2 middle bench",
            rect_points(0.515, 0.688, 0.060, 0.031),
            "bench",
            False,
        ),
        PolygonShape(
            "platform_bench_right",
            "B2 right bench",
            rect_points(0.768, 0.688, 0.062, 0.032),
            "bench",
            False,
        ),
        *fare_barrier_boxes(),
    ),
    facility_boxes=(
        *gate_boxes(),
        *exit_gate_boxes(),
        PolygonShape(
            "elevator_visual_envelope",
            "visual envelope shared by renderer and elevator tracks",
            tuple(tuple(point) for point in ELEVATOR.box.corners()),
            "elevator",
            False,
        ),
        PolygonShape(
            "platform_screen_edge",
            "B2 platform screen door line",
            rect_points(0.145, 0.626, 0.720, 0.010),
            "screen_door",
            False,
        ),
        PolygonShape(
            "lower_track_1",
            "lower rail track bed",
            rect_points(0.050, 0.830, 0.900, 0.048),
            "track",
            True,
        ),
        PolygonShape(
            "lower_track_2",
            "lower rail track bed",
            rect_points(0.050, 0.905, 0.900, 0.045),
            "track",
            True,
        ),
    ),
    control_points={
        "gates": (
            (0.210, 0.338),
            (0.235, 0.338),
            (0.260, 0.338),
            (0.285, 0.338),
            (0.310, 0.338),
            (0.335, 0.338),
        ),
        "exit_gates": ((0.744, 0.318), (0.772, 0.318), (0.800, 0.318), (0.828, 0.318)),
        "platform_doors": (
            (0.251, 0.785),
            (0.358, 0.785),
            (0.466, 0.785),
            (0.646, 0.785),
            (0.754, 0.785),
            (0.861, 0.785),
        ),
    },
    decision_regions=decision_regions(),
)


def layout_payload() -> dict[str, object]:
    payload = STATION_LAYOUT.as_dict()
    payload.update(
        {
            "schema_version": "metro-layout-doc/v1",
            "units": "normalized_canvas",
            "editor": {
                "pattern": "scene_graph",
                "coordinate_space": "normalized_image_xy",
                "snap": {
                    "enabled": True,
                    "grid": 0.005,
                    "point_radius": 0.012,
                },
                "editable_layers": [
                    "floors",
                    "connectors",
                    "obstacles",
                    "facilities",
                    "queues",
                ],
                "derived_layers": [
                    "walkable_geometry",
                    "collision_geometry",
                    "queue_slots",
                    "jps_stages",
                ],
            },
            "elements": layout_elements(),
        }
    )
    return payload


def layout_elements() -> list[dict[str, object]]:
    elements: list[LayoutElement] = []
    elements.extend(
        polygon_element(region, role="floor", layer="floors", z_index=10)
        for region in STATION_LAYOUT.walkable_regions
    )
    elements.extend(channel_element(channel) for channel in STATION_LAYOUT.connector_channels)
    elements.extend(
        polygon_element(obstacle, role="obstacle", layer="obstacles", z_index=50)
        for obstacle in STATION_LAYOUT.obstacles
    )
    elements.extend(
        polygon_element(facility, role=facility.kind, layer="facilities", z_index=60)
        for facility in STATION_LAYOUT.facility_boxes
    )
    elements.sort(key=lambda item: item.z_index)
    return [element.as_dict() for element in elements]
