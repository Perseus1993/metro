from __future__ import annotations


from .schema import (
    DesignConnection,
    DesignConstraints,
    DesignElement,
    LevelSpec,
    QueueSpec,
    StationDesignDocument,
)


from .template_support import (
    _footprint,
    _replace_queue_level,
    _three_level_element,
    _with_standard_graph_ports,
    lane,
    rect,
)


def two_level_island_platform() -> StationDesignDocument:
    constraints = DesignConstraints(max_levels=3, max_depth_m=28.0)
    levels = (
        LevelSpec("b1_concourse", "B1 Concourse", -6.0, 6.0, 0, _footprint(4, 4, 112, 42)),
        LevelSpec("b2_platform", "B2 Island Platform", -14.0, 8.0, 1, _footprint(10, 4, 100, 60)),
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
    return _with_standard_graph_ports(
        StationDesignDocument(
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
    )


def three_level_transfer() -> StationDesignDocument:
    base = two_level_island_platform()
    levels = (
        LevelSpec("b1_concourse", "B1 Concourse", -6.0, 6.0, 0, _footprint(4, 4, 112, 38)),
        LevelSpec("b2_transfer", "B2 Transfer Hall", -13.0, 7.0, 1, _footprint(8, 8, 104, 44)),
        LevelSpec("b3_platform", "B3 Platform", -21.0, 8.0, 2, _footprint(10, 4, 100, 60)),
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
            direction="both",
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
    return _with_standard_graph_ports(
        StationDesignDocument(
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
    return _with_standard_graph_ports(
        StationDesignDocument(
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
    )
