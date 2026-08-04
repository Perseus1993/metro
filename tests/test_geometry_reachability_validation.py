from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.compilation.geometry_reachability import (
    GeometryCompilePolicy,
    GeometryRoutingEngineBuildError,
    _ROUTING_ENGINES,
    validate_geometry_reachability,
)
from metro_station.adapters.simulation.compilation.validation import validate_station_design
from metro_station.adapters.simulation.design.schema import (
    DesignConnection,
    DesignConstraints,
    DesignElement,
    ElementGeometry,
    LevelSpec,
    StationDesignDocument,
)
from metro_station.adapters.simulation.design.templates import create_design, topology_templates
from metro_station.adapters.simulation.station.geometry import level_walkable_geometry


def test_all_formal_templates_pass_continuous_geometry_compilation() -> None:
    for template in topology_templates():
        issues = validate_station_design(create_design(template.id))
        assert not [issue for issue in issues if issue.severity == "error"], (
            template.id,
            issues,
        )


def test_obstacle_on_one_level_does_not_change_overlapping_level_domain() -> None:
    document = create_design("two_level_island_platform")
    before = level_walkable_geometry(document, "b2_platform")
    wall = _wall("b1_only_wall", "b1_concourse", 50.0, 4.0, 2.0, 42.0)
    changed = replace(document, elements=(*document.elements, wall))
    after = level_walkable_geometry(changed, "b2_platform")

    assert before.equals_exact(after, tolerance=0.0)
    assert bytes(before.wkb) == bytes(after.wkb)


def test_disconnected_body_domain_emits_one_root_cause_without_edge_flood() -> None:
    document = create_design("two_level_island_platform")
    wall = _wall("full_height_wall", "b1_concourse", 10.0, 4.0, 1.0, 42.0)
    issues = validate_station_design(replace(document, elements=(*document.elements, wall)))
    geometry_errors = [
        issue.code
        for issue in issues
        if issue.severity == "error" and issue.code.startswith("geometry.")
    ]

    assert geometry_errors == ["geometry.level_domain_disconnected"]


def test_authored_connection_endpoint_is_not_silently_projected() -> None:
    document = create_design("two_level_island_platform")
    entrance = document.element_by_id()["entrance_a"]
    ports = tuple(
        replace(port, position_m=(3.0, 3.0)) if port.id == "walk" else port
        for port in entrance.ports
    )
    changed = replace(
        document,
        elements=tuple(
            replace(element, ports=ports) if element.id == entrance.id else element
            for element in document.elements
        ),
    )
    codes = {issue.code for issue in validate_station_design(changed)}

    assert "geometry.walk_edge_not_traversable" in codes
    assert "geometry.entrance_platform_unreachable" in codes


def test_every_parallel_authored_connection_is_validated_independently() -> None:
    document = create_design("single_level_terminal")
    entrance = document.element_by_id()["entrance_a"]
    bad_port = replace(
        entrance.ports[0],
        id="bad_parallel_port",
        position_m=(3.0, 3.0),
    )
    changed_entrance = replace(
        entrance,
        ports=(*entrance.ports, bad_port),
    )
    good = next(
        connection
        for connection in document.connections
        if connection.id == "conn_entrance_to_hall"
    )
    bad = replace(
        good,
        id="zzz_bad_parallel",
        source_port_id=bad_port.id,
    )

    for connections in (
        (*document.connections, bad),
        (bad, *document.connections),
    ):
        changed = replace(
            document,
            elements=tuple(
                changed_entrance if element.id == entrance.id else element
                for element in document.elements
            ),
            connections=connections,
        )
        codes = {issue.code for issue in validate_station_design(changed)}

        assert "geometry.walk_edge_not_traversable" in codes


def test_detour_ratio_is_a_warning_not_an_error() -> None:
    document = _narrow_detour_document()
    issues = validate_geometry_reachability(document)

    assert issues
    assert {issue.code for issue in issues} == {"geometry.detour_ratio_exceeded"}
    assert all(issue.severity == "warning" for issue in issues)


def test_geometry_policy_radius_controls_body_reachability() -> None:
    document = _narrow_detour_document()

    pedestrian = validate_geometry_reachability(
        document,
        policy=GeometryCompilePolicy(agent_radius_m=0.18),
    )
    wide_body = validate_geometry_reachability(
        document,
        policy=GeometryCompilePolicy(agent_radius_m=0.45),
    )

    assert "geometry.level_domain_disconnected" not in {issue.code for issue in pedestrian}
    assert "geometry.level_domain_disconnected" in {issue.code for issue in wide_body}


def test_unused_disconnected_walkable_component_is_not_rejected() -> None:
    document = _disconnected_islands_document(cross_components=False)

    issues = validate_geometry_reachability(document)

    assert "geometry.level_domain_disconnected" not in {
        item.code for item in issues
    }


def test_walk_edge_crossing_disconnected_components_is_rejected() -> None:
    document = _disconnected_islands_document(cross_components=True)

    issues = validate_geometry_reachability(document)

    assert [
        item.code
        for item in issues
        if item.code == "geometry.level_domain_disconnected"
    ] == ["geometry.level_domain_disconnected"]


def test_navigation_mesh_build_failure_is_not_disguised_as_unreachable(
    monkeypatch,
) -> None:
    document = _narrow_detour_document()

    def fail_build(_level_id, _domain):
        raise GeometryRoutingEngineBuildError("synthetic navmesh failure")

    monkeypatch.setattr(_ROUTING_ENGINES, "get", fail_build)

    try:
        validate_geometry_reachability(document)
    except GeometryRoutingEngineBuildError as exc:
        assert "synthetic navmesh failure" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("navmesh build failure was converted into a route issue")


def _wall(
    element_id: str,
    level_id: str,
    x_m: float,
    y_m: float,
    width_m: float,
    height_m: float,
) -> DesignElement:
    return DesignElement(
        element_id,
        "obstacle",
        level_id,
        ElementGeometry("rect", x_m=x_m, y_m=y_m, width_m=width_m, height_m=height_m),
        element_id,
        "obstacle",
        False,
        True,
        metadata={"blocking": True},
    )


def _narrow_detour_document() -> StationDesignDocument:
    level_id = "l1"
    return StationDesignDocument(
        id="detour",
        label="Detour fixture",
        template_id="test",
        constraints=DesignConstraints(canvas_width_m=30.0, canvas_height_m=20.0),
        levels=(
            LevelSpec(
                level_id,
                "Level 1",
                0.0,
                4.0,
                0,
                ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)),
            ),
        ),
        elements=(
            DesignElement(
                "floor",
                "walkable_area",
                level_id,
                ElementGeometry("rect", width_m=30.0, height_m=20.0),
                "Floor",
                "floor",
                False,
                True,
            ),
            DesignElement(
                "entrance",
                "entrance",
                level_id,
                ElementGeometry("rect", x_m=13.5, y_m=9.5, width_m=1.0, height_m=1.0),
                "Entrance",
                "access",
                False,
                False,
            ),
            DesignElement(
                "platform",
                "platform_edge",
                level_id,
                ElementGeometry("rect", x_m=16.5, y_m=9.5, width_m=1.0, height_m=1.0),
                "Platform",
                "boarding",
                False,
                True,
                line_id="test",
                direction="down",
            ),
            _wall("long_wall", level_id, 15.0, 0.0, 1.0, 19.2),
        ),
        connections=(
            DesignConnection("entrance_to_platform", "entrance", "platform", "walk", False),
        ),
    )


def _disconnected_islands_document(*, cross_components: bool) -> StationDesignDocument:
    level_id = "l1"
    target_x = 21.0 if cross_components else 7.0
    return StationDesignDocument(
        id="islands",
        label="Disconnected islands fixture",
        template_id="test",
        constraints=DesignConstraints(canvas_width_m=30.0, canvas_height_m=10.0),
        levels=(
            LevelSpec(
                level_id,
                "Level 1",
                0.0,
                4.0,
                0,
                ((0.0, 0.0), (30.0, 0.0), (30.0, 10.0), (0.0, 10.0)),
            ),
        ),
        elements=(
            DesignElement(
                "left_floor",
                "walkable_area",
                level_id,
                ElementGeometry("rect", x_m=1.0, y_m=1.0, width_m=10.0, height_m=8.0),
                "Left floor",
                "floor",
                False,
                True,
            ),
            DesignElement(
                "right_floor",
                "walkable_area",
                level_id,
                ElementGeometry("rect", x_m=19.0, y_m=1.0, width_m=10.0, height_m=8.0),
                "Right floor",
                "floor",
                False,
                True,
            ),
            DesignElement(
                "entrance",
                "entrance",
                level_id,
                ElementGeometry("rect", x_m=3.0, y_m=4.0, width_m=1.0, height_m=1.0),
                "Entrance",
                "access",
                False,
                False,
            ),
            DesignElement(
                "platform",
                "platform_edge",
                level_id,
                ElementGeometry(
                    "rect", x_m=target_x, y_m=4.0, width_m=1.0, height_m=1.0
                ),
                "Platform",
                "boarding",
                False,
                True,
                line_id="test",
                direction="down",
            ),
        ),
        connections=(
            DesignConnection("entrance_to_platform", "entrance", "platform", "walk", False),
        ),
    )
