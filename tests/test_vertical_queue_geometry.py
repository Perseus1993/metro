from __future__ import annotations

from math import acos, cos, degrees, hypot, radians, sin

import pytest
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from metro_station.adapters.simulation.design.schema import (
    MAX_COMPILED_QUEUE_CAPACITY,
    MIN_COMPILED_QUEUE_SPACING_M,
    ElementGeometry,
    QueueSpec,
)
from metro_station.adapters.simulation.facilities.process import QueueLayout
from metro_station.adapters.simulation.station.layout_queue_geometry import (
    QUEUE_CLEARANCE_EPSILON_M,
    _queue_layout_behind_service_entry,
    _queue_layout_with_service_entry_slot,
    _queue_slots_from_geometry,
)


def _point(
    origin: tuple[float, float],
    forward: tuple[float, float],
    lateral: tuple[float, float],
    *,
    depth: float,
    offset: float,
) -> tuple[float, float]:
    return (
        origin[0] - forward[0] * depth + lateral[0] * offset,
        origin[1] - forward[1] * depth + lateral[1] * offset,
    )


@pytest.mark.parametrize("angle_degrees", (0.0, 37.0, 90.0, 173.0))
@pytest.mark.parametrize("scale", (0.5, 1.0, 2.0))
def test_vertical_queue_order_is_rotation_and_scale_invariant(
    angle_degrees: float,
    scale: float,
) -> None:
    angle = radians(angle_degrees)
    forward = (cos(angle), sin(angle))
    lateral = (-forward[1], forward[0])
    service = (10.0, -3.0)
    spacing = 0.8 * scale
    slots = tuple(
        reversed(
            [
                _point(
                    service,
                    forward,
                    lateral,
                    depth=depth * spacing,
                    offset=offset * spacing,
                )
                for depth in (1.0, 2.0, 3.0)
                for offset in (-1.0, 0.0, 1.0)
            ]
        )
    )
    layout = QueueLayout(
        anchor=slots[0],
        per_row=3,
        col_step=(lateral[0] * spacing, lateral[1] * spacing),
        row_step=(-forward[0] * spacing, -forward[1] * spacing),
        slots=slots,
    )

    ordered = _queue_layout_behind_service_entry(
        layout,
        service,
        (service[0] + forward[0], service[1] + forward[1]),
    ).slots
    depths = [
        -(
            (point[0] - service[0]) * forward[0]
            + (point[1] - service[1]) * forward[1]
        )
        for point in ordered
    ]

    assert depths == pytest.approx(sorted(depths))
    assert all(depth >= -1e-9 for depth in depths)
    assert _maximum_turn_degrees((service, *ordered)) <= 135.0001


def test_vertical_queue_without_upstream_capacity_fails_compilation() -> None:
    layout = QueueLayout(
        anchor=(1.0, 0.0),
        per_row=2,
        col_step=(0.0, 0.8),
        row_step=(0.8, 0.0),
        slots=((1.0, 0.0), (2.0, 0.0)),
    )

    with pytest.raises(ValueError, match="no slot on the approach side"):
        _queue_layout_behind_service_entry(
            layout,
            (0.0, 0.0),
            (1.0, 0.0),
        )


def test_detached_service_entry_without_walkable_bridge_fails_compilation() -> None:
    layout = QueueLayout(
        anchor=(-5.0, 0.0),
        per_row=1,
        col_step=(0.0, 0.0),
        row_step=(-0.8, 0.0),
        slots=((-5.0, 0.0), (-5.8, 0.0)),
    )

    with pytest.raises(ValueError, match="detached"):
        _queue_layout_with_service_entry_slot(layout, (0.0, 0.0))


def test_walkable_service_bridge_never_increases_declared_capacity() -> None:
    layout = QueueLayout(
        anchor=(-5.0, 0.0),
        per_row=1,
        col_step=(0.0, 0.0),
        row_step=(-0.8, 0.0),
        slots=((-5.0, 0.0), (-5.8, 0.0)),
    )

    with pytest.raises(ValueError, match="declared occupancy capacity"):
        _queue_layout_with_service_entry_slot(
            layout,
            (0.0, 0.0),
            walkable_geometry=box(-6.0, -1.0, 1.0, 1.0),
        )


def test_queue_geometry_compiler_has_a_hard_capacity_budget() -> None:
    queue = QueueSpec(
        id="over_budget",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry("rect", x_m=0.0, y_m=0.0, width_m=40.0, height_m=40.0),
        service_point_m=(1.0, 1.0),
        capacity=MAX_COMPILED_QUEUE_CAPACITY + 1,
        spacing_m=0.8,
    )

    with pytest.raises(ValueError, match="exceeds compiler limit"):
        _queue_slots_from_geometry(queue, box(0.0, 0.0, 40.0, 40.0))


@pytest.mark.parametrize("capacity", (True, 52.5))
def test_queue_geometry_compiler_rejects_non_integer_capacity(capacity) -> None:
    queue = QueueSpec(
        id="non_integer_capacity",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry("rect", x_m=0.0, y_m=0.0, width_m=10.0, height_m=10.0),
        service_point_m=(5.0, 5.0),
        capacity=capacity,
        spacing_m=0.4,
    )

    with pytest.raises(ValueError, match="must be an integer"):
        _queue_slots_from_geometry(queue, box(0.0, 0.0, 10.0, 10.0))


def test_large_open_queue_starts_at_global_service_nearest_slot() -> None:
    domain = box(0.0, 0.0, 20.0, 20.0)
    queue = QueueSpec(
        id="global_nearest",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry("rect", x_m=0.0, y_m=0.0, width_m=20.0, height_m=20.0),
        service_point_m=(10.0, 10.0),
        capacity=MAX_COMPILED_QUEUE_CAPACITY,
        spacing_m=0.4,
    )

    slots = _queue_slots_from_geometry(queue, domain)

    assert len(slots) == MAX_COMPILED_QUEUE_CAPACITY
    assert hypot(slots[0][0] - 10.0, slots[0][1] - 10.0) <= 1e-9


def test_open_queue_capacity_variants_share_one_canonical_prefix() -> None:
    domain = box(0.0, 0.0, 10.0, 10.0)
    compiled = {}
    for capacity in (53, 54, 63, 64, 71, 72, 128):
        queue = QueueSpec(
            id=f"prefix_{capacity}",
            owner_element_id="facility",
            kind="lane",
            level_id="level",
            geometry=ElementGeometry("rect", x_m=0.0, y_m=0.0, width_m=10.0, height_m=10.0),
            service_point_m=(5.0, 5.0),
            capacity=capacity,
            spacing_m=0.4,
        )
        compiled[capacity] = _queue_slots_from_geometry(queue, domain)

    longest = compiled[128]
    assert all(slots == longest[:capacity] for capacity, slots in compiled.items())


def test_comb_concourse_dead_ends_do_not_consume_the_queue_path_budget() -> None:
    main_corridor = box(0.0, 0.0, 80.0, 1.2)
    side_branches = [
        box(x_position, 1.0, x_position + 0.4, 4.0)
        for x_position in range(1, 31)
    ]
    walkable = unary_union((main_corridor, *side_branches))
    queue = QueueSpec(
        id="comb_backbone",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "rect",
            x_m=0.0,
            y_m=0.0,
            width_m=80.0,
            height_m=4.0,
        ),
        service_point_m=(0.4, 0.6),
        capacity=MAX_COMPILED_QUEUE_CAPACITY,
        spacing_m=0.4,
    )

    slots = _queue_slots_from_geometry(queue, walkable)

    assert len(slots) == MAX_COMPILED_QUEUE_CAPACITY
    assert LineString(slots).is_simple
    assert max(point[0] for point in slots) >= 50.0


def test_half_pitch_portal_misalignment_does_not_hide_a_reachable_room() -> None:
    left_room = box(0.0, 0.0, 2.0, 2.0)
    narrow_neck = box(2.0, 0.95, 12.0, 1.45)
    right_room = box(12.0, 0.0, 32.0, 4.0)
    walkable = unary_union((left_room, narrow_neck, right_room))
    queue = QueueSpec(
        id="phase_misaligned_dumbbell",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "rect",
            x_m=0.0,
            y_m=0.0,
            width_m=32.0,
            height_m=4.0,
        ),
        service_point_m=(1.0, 1.0),
        capacity=MAX_COMPILED_QUEUE_CAPACITY,
        spacing_m=0.4,
    )

    slots = _queue_slots_from_geometry(queue, walkable)
    edges = [LineString((left, right)) for left, right in zip(slots, slots[1:])]

    assert len(slots) == MAX_COMPILED_QUEUE_CAPACITY
    assert LineString(slots).is_simple
    assert max(point[0] for point in slots) >= 12.0
    assert all(walkable.buffer(1e-7).covers(edge) for edge in edges)
    assert all(
        left.distance(right)
        >= MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
        for left_index, left in enumerate(edges)
        for right in edges[left_index + 2 :]
    )


def test_curved_narrow_corridor_supports_a_body_clear_queue_chain() -> None:
    center = Point(20.0, 20.0)
    walkable = center.buffer(10.3, quad_segs=256).difference(
        center.buffer(9.7, quad_segs=256)
    )
    queue = QueueSpec(
        id="narrow_annulus",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "rect",
            x_m=9.5,
            y_m=9.5,
            width_m=21.0,
            height_m=21.0,
        ),
        service_point_m=(30.0, 20.0),
        capacity=MAX_COMPILED_QUEUE_CAPACITY,
        spacing_m=0.4,
    )

    slots = _queue_slots_from_geometry(queue, walkable)
    edges = [LineString((left, right)) for left, right in zip(slots, slots[1:])]

    assert len(slots) == MAX_COMPILED_QUEUE_CAPACITY
    assert LineString(slots).is_simple
    assert all(walkable.buffer(1e-7).covers(edge) for edge in edges)
    assert all(
        left.distance(right)
        >= MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
        for left_index, left in enumerate(edges)
        for right in edges[left_index + 2 :]
    )


def test_diagonal_phase_closes_a_one_slot_cardinal_deficit() -> None:
    centerline = LineString(
        (
            (0.0, 0.0),
            (12.4, 0.0),
            (14.718222, 0.621166),
        )
    )
    walkable = centerline.buffer(0.34)
    min_x, min_y, max_x, max_y = walkable.bounds
    queue = QueueSpec(
        id="one_slot_diagonal_deficit",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "rect",
            x_m=min_x,
            y_m=min_y,
            width_m=max_x - min_x,
            height_m=max_y - min_y,
        ),
        service_point_m=(0.0, 0.0),
        capacity=49,
        spacing_m=0.4,
    )

    slots = _queue_slots_from_geometry(queue, walkable)
    edges = [LineString((left, right)) for left, right in zip(slots, slots[1:])]
    body_clear_domain = walkable.buffer(-0.08).buffer(1e-7)

    assert len(slots) == 49
    assert LineString(slots).is_simple
    assert all(body_clear_domain.covers(edge) for edge in edges)
    assert all(
        left.distance(right)
        >= MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
        for left_index, left in enumerate(edges)
        for right in edges[left_index + 2 :]
    )


def test_half_pitch_phase_sets_small_domain_canonical_capacity() -> None:
    walkable = box(0.0, 0.0, 1.2, 0.6)
    queue = QueueSpec(
        id="small_half_pitch_capacity",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "rect",
            x_m=0.0,
            y_m=0.0,
            width_m=1.2,
            height_m=0.6,
        ),
        service_point_m=(0.0, 0.3),
        capacity=3,
        spacing_m=0.4,
    )

    slots = _queue_slots_from_geometry(queue, walkable)
    edges = [LineString((left, right)) for left, right in zip(slots, slots[1:])]
    body_clear_domain = walkable.buffer(-0.08).buffer(1e-7)

    assert len(slots) == 3
    assert LineString(slots).is_simple
    assert all(body_clear_domain.covers(edge) for edge in edges)
    assert all(
        hypot(right[0] - left[0], right[1] - left[1])
        == pytest.approx(0.4)
        for left, right in zip(slots, slots[1:])
    )


@pytest.mark.parametrize("angle_degrees", (0.0, 37.0, 90.0, 173.0))
def test_small_pillar_does_not_make_beam_search_lose_queue_capacity(
    angle_degrees: float,
) -> None:
    outer = affinity.rotate(
        box(-0.081, -0.081, 2.481, 2.481),
        angle_degrees,
        origin=(0.0, 0.0),
    )
    pillar = affinity.rotate(
        box(1.5, 1.5, 1.7, 1.7),
        angle_degrees,
        origin=(0.0, 0.0),
    )
    walkable = outer.difference(pillar)
    service = affinity.rotate(
        Point(1.2, 1.6),
        angle_degrees,
        origin=(0.0, 0.0),
    )
    queue = QueueSpec(
        id=f"small_pillar_hamiltonian_path_{angle_degrees}",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "polygon",
            points_m=tuple(outer.exterior.coords[:-1]),
        ),
        service_point_m=(float(service.x), float(service.y)),
        capacity=48,
        spacing_m=0.4,
    )

    slots = _queue_slots_from_geometry(queue, walkable)
    edges = [LineString((left, right)) for left, right in zip(slots, slots[1:])]
    body_clear_domain = walkable.buffer(-0.08).buffer(1e-7)

    assert len(slots) == 48
    assert LineString(slots).is_simple
    assert all(body_clear_domain.covers(edge) for edge in edges)
    assert all(
        left.distance(right)
        >= MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
        for left_index, left in enumerate(edges)
        for right in edges[left_index + 2 :]
    )


def test_boundary_notches_do_not_exhaust_small_graph_search_budget() -> None:
    outer = box(-0.081, -0.081, 2.881, 2.881)
    notches = unary_union(
        [
            box(
                column * 0.4 - 0.18,
                row * 0.4 - 0.18,
                column * 0.4 + 0.18,
                row * 0.4 + 0.18,
            )
            for column, row in ((6, 3), (6, 4), (7, 4), (7, 5))
        ]
    )
    walkable = outer.difference(notches)
    queue = QueueSpec(
        id="boundary_notches_hamiltonian_path",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "rect",
            x_m=-0.081,
            y_m=-0.081,
            width_m=2.962,
            height_m=2.962,
        ),
        service_point_m=(1.6, 2.0),
        capacity=60,
        spacing_m=0.4,
    )

    slots = _queue_slots_from_geometry(queue, walkable)
    edges = [LineString((left, right)) for left, right in zip(slots, slots[1:])]
    body_clear_domain = walkable.buffer(-0.08).buffer(1e-7)

    assert len(slots) == 60
    assert LineString(slots).is_simple
    assert all(body_clear_domain.covers(edge) for edge in edges)
    assert all(
        left.distance(right)
        >= MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
        for left_index, left in enumerate(edges)
        for right in edges[left_index + 2 :]
    )


def test_symmetric_exact_search_is_not_biased_by_rank_tie_order() -> None:
    grid_path = (
        (5, 2), (4, 2), (4, 3), (5, 3), (5, 4), (4, 4), (4, 5),
        (3, 5), (3, 6), (4, 6), (4, 7), (5, 7), (5, 6), (5, 5),
        (6, 5), (6, 6), (7, 6), (7, 5), (8, 5), (8, 4), (7, 4),
        (6, 4), (6, 3), (7, 3), (7, 2), (7, 1), (8, 1), (8, 0),
        (7, 0), (6, 0), (6, 1), (5, 1), (5, 0), (4, 0), (4, 1),
        (3, 1), (2, 1), (2, 0), (1, 0), (0, 0), (0, 1), (1, 1),
        (1, 2), (0, 2), (0, 3), (0, 4), (1, 4), (1, 3), (2, 3),
        (2, 2), (3, 2), (3, 3), (3, 4), (2, 4), (2, 5), (1, 5),
        (1, 6), (2, 6), (2, 7), (3, 7), (3, 8), (2, 8),
    )
    kept = set(grid_path)
    outer = box(-0.081, -0.081, 3.281, 3.281)
    holes = unary_union(
        [
            box(
                column * 0.4 - 0.18,
                row * 0.4 - 0.18,
                column * 0.4 + 0.18,
                row * 0.4 + 0.18,
            )
            for column in range(9)
            for row in range(9)
            if (column, row) not in kept
        ]
    )
    walkable = outer.difference(holes)
    queue = QueueSpec(
        id="symmetric_rank_tie_search",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "rect",
            x_m=-0.081,
            y_m=-0.081,
            width_m=3.362,
            height_m=3.362,
        ),
        service_point_m=(2.0, 0.8),
        capacity=62,
        spacing_m=0.4,
    )

    slots = _queue_slots_from_geometry(queue, walkable)
    edges = [LineString((left, right)) for left, right in zip(slots, slots[1:])]
    body_clear_domain = walkable.buffer(-0.08).buffer(1e-7)

    assert len(slots) == 62
    assert LineString(slots).is_simple
    assert all(body_clear_domain.covers(edge) for edge in edges)
    assert all(
        left.distance(right)
        >= MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
        for left_index, left in enumerate(edges)
        for right in edges[left_index + 2 :]
    )


@pytest.mark.parametrize("angle_degrees", (0.0, 0.1, 0.5, 1.0, 17.0, 37.0, 90.0, 173.0))
def test_equidistant_component_choice_is_rigid_transform_invariant(
    angle_degrees: float,
) -> None:
    small = box(-1.0, -0.6, -0.2, 0.6)
    large = box(0.2, -3.0, 8.0, 3.0)
    walkable = affinity.rotate(
        unary_union((small, large)),
        angle_degrees,
        origin=(0.0, 0.0),
    )
    queue_polygon = affinity.rotate(
        box(-1.1, -3.1, 8.1, 3.1),
        angle_degrees,
        origin=(0.0, 0.0),
    )
    queue = QueueSpec(
        id="equidistant_components",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "polygon",
            points_m=tuple(queue_polygon.exterior.coords[:-1]),
        ),
        service_point_m=(0.0, 0.0),
        capacity=50,
        spacing_m=0.4,
    )

    slots = _queue_slots_from_geometry(queue, walkable)
    unrotated_first = affinity.rotate(
        Point(slots[0]),
        -angle_degrees,
        origin=(0.0, 0.0),
    )

    assert len(slots) == 50
    assert unrotated_first.x >= 0.2 - 1e-6


def test_compiled_queue_slot_chain_is_simple_and_non_self_intersecting() -> None:
    domain = box(0.0, 0.0, 3.0, 3.0)
    queue = QueueSpec(
        id="simple_chain",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry("rect", x_m=0.0, y_m=0.0, width_m=3.0, height_m=3.0),
        service_point_m=(0.1, 0.1),
        capacity=9,
        spacing_m=0.8,
    )

    slots = _queue_slots_from_geometry(queue, domain)

    assert len(slots) >= 2
    assert LineString(slots).is_simple


def test_non_adjacent_queue_edges_keep_body_clear_distance() -> None:
    domain = box(0.0, 0.0, 3.0, 3.0)
    queue = QueueSpec(
        id="body_clear_chain",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry("rect", x_m=0.0, y_m=0.0, width_m=3.0, height_m=3.0),
        service_point_m=(0.1, 0.1),
        capacity=4,
        spacing_m=MIN_COMPILED_QUEUE_SPACING_M,
    )

    slots = _queue_slots_from_geometry(queue, domain)
    edges = [LineString((left, right)) for left, right in zip(slots, slots[1:])]

    assert all(
        left.distance(right) >= MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
        for left_index, left in enumerate(edges)
        for right in edges[left_index + 2 :]
    )


@pytest.mark.parametrize("capacity", (52, 53, 54, 63, 64, 71, 72, 128))
def test_open_queue_compilation_does_not_lose_capacity_at_search_boundaries(
    capacity: int,
) -> None:
    domain = box(0.0, 0.0, 10.0, 10.0)
    queue = QueueSpec(
        id=f"open_{capacity}",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry("rect", x_m=0.0, y_m=0.0, width_m=10.0, height_m=10.0),
        service_point_m=(0.4, 0.4),
        capacity=capacity,
        spacing_m=MIN_COMPILED_QUEUE_SPACING_M,
    )

    assert len(_queue_slots_from_geometry(queue, domain)) == capacity


@pytest.mark.parametrize("angle_degrees", (0.0, 0.1, 0.5, 1.0, 37.0, 89.999, 90.0))
@pytest.mark.parametrize("capacity", (8, 16))
def test_minimum_spacing_open_capacity_is_rigid_transform_invariant(
    angle_degrees: float,
    capacity: int,
) -> None:
    base_domain = box(0.0, 0.0, 2.0, 2.0)
    base_service = Point(0.4, 0.4)
    domain = affinity.rotate(base_domain, angle_degrees, origin=(0.0, 0.0))
    service = affinity.rotate(base_service, angle_degrees, origin=(0.0, 0.0))
    queue = QueueSpec(
        id=f"rotated_{angle_degrees}_{capacity}",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "polygon",
            points_m=tuple(domain.exterior.coords[:-1]),
        ),
        service_point_m=(float(service.x), float(service.y)),
        capacity=capacity,
        spacing_m=MIN_COMPILED_QUEUE_SPACING_M,
    )

    assert len(_queue_slots_from_geometry(queue, domain)) == capacity


@pytest.mark.parametrize("angle_degrees", (0.0, 37.0, 90.0, 173.0))
def test_queue_compilation_never_bridges_disconnected_walkable_components(
    angle_degrees: float,
) -> None:
    queue_polygon = box(0.0, 0.0, 10.0, 2.0)
    walkable = unary_union((box(0.0, 0.0, 2.0, 2.0), box(8.0, 0.0, 10.0, 2.0)))
    service = (1.0, 1.0)
    queue_polygon = affinity.translate(
        affinity.rotate(queue_polygon, angle_degrees, origin=(0.0, 0.0)),
        xoff=11.0,
        yoff=-4.0,
    )
    walkable = affinity.translate(
        affinity.rotate(walkable, angle_degrees, origin=(0.0, 0.0)),
        xoff=11.0,
        yoff=-4.0,
    )
    service_point = affinity.translate(
        affinity.rotate(Point(service), angle_degrees, origin=(0.0, 0.0)),
        xoff=11.0,
        yoff=-4.0,
    ).centroid
    exterior = tuple((float(x), float(y)) for x, y in queue_polygon.exterior.coords[:-1])
    queue = QueueSpec(
        id="disconnected",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry("polygon", points_m=exterior),
        service_point_m=(float(service_point.x), float(service_point.y)),
        capacity=40,
        spacing_m=0.8,
    )

    slots = _queue_slots_from_geometry(queue, walkable)
    service_component = min(
        walkable.geoms,
        key=lambda geometry: geometry.distance(service_point),
    ).buffer(1e-7)

    assert len(slots) >= 2
    assert all(service_component.covers(LineString((left, right))) for left, right in zip(slots, slots[1:]))
    assert all(hypot(right[0] - left[0], right[1] - left[1]) <= 1.29 for left, right in zip(slots, slots[1:]))


def test_queue_fully_inside_walkable_hole_fails_closed() -> None:
    walkable = Polygon(
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        holes=(((3, 3), (7, 3), (7, 7), (3, 7)),),
    )
    queue = QueueSpec(
        id="inside_hole",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry("rect", x_m=4.0, y_m=4.0, width_m=2.0, height_m=2.0),
        service_point_m=(5.0, 5.0),
        capacity=8,
        spacing_m=0.4,
    )

    with pytest.raises(ValueError, match="no overlap with the walkable domain"):
        _queue_slots_from_geometry(queue, walkable)


@pytest.mark.parametrize(
    "walkable",
    (box(2.0, 0.0, 4.0, 2.0), box(2.0, 2.0, 4.0, 4.0)),
)
def test_queue_without_positive_walkable_intersection_fails_closed(walkable) -> None:
    queue = QueueSpec(
        id="degenerate_touch",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry("rect", x_m=0.0, y_m=0.0, width_m=2.0, height_m=2.0),
        service_point_m=(1.0, 1.0),
        capacity=4,
        spacing_m=0.4,
    )

    with pytest.raises(ValueError, match="without usable area|no overlap"):
        _queue_slots_from_geometry(queue, walkable)


def test_queue_too_narrow_for_body_clear_slots_fails_closed() -> None:
    queue = QueueSpec(
        id="too_narrow",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry("rect", x_m=0.0, y_m=0.0, width_m=0.1, height_m=4.0),
        service_point_m=(0.05, 0.2),
        capacity=8,
        spacing_m=0.4,
    )

    with pytest.raises(ValueError, match="no body-clear area"):
        _queue_slots_from_geometry(queue, box(0.0, 0.0, 0.1, 4.0))


def test_eroded_thin_tail_cannot_authorize_a_long_raw_service_bridge() -> None:
    thin_tail = box(0.0, 0.95, 10.0, 1.05)
    room = box(10.0, 0.0, 20.0, 4.0)
    walkable = unary_union((thin_tail, room))
    queue = QueueSpec(
        id="eroded_service_tail",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "rect",
            x_m=0.0,
            y_m=0.0,
            width_m=20.0,
            height_m=4.0,
        ),
        service_point_m=(0.1, 1.0),
        capacity=8,
        spacing_m=0.4,
    )

    with pytest.raises(ValueError, match="service point cannot reach"):
        _queue_slots_from_geometry(queue, walkable)


def test_long_service_bridge_is_materialized_and_consumes_capacity() -> None:
    walkable = box(0.0, 0.0, 32.0, 2.0)

    def compile_slots(capacity: int):
        queue = QueueSpec(
            id=f"materialized_bridge_{capacity}",
            owner_element_id="facility",
            kind="lane",
            level_id="level",
            geometry=ElementGeometry(
                "rect",
                x_m=20.0,
                y_m=0.0,
                width_m=12.0,
                height_m=2.0,
            ),
            service_point_m=(-0.3, 1.0),
            capacity=capacity,
            spacing_m=0.4,
        )
        return _queue_slots_from_geometry(queue, walkable)

    with pytest.raises(ValueError, match="bridge cannot fit"):
        compile_slots(32)

    slots = compile_slots(33)
    body_clear_domain = walkable.buffer(-0.08).buffer(1e-7)

    assert len(slots) == 33
    assert sum(point[0] < 20.0 for point in slots) >= 31
    assert all(
        body_clear_domain.covers(LineString((left, right)))
        for left, right in zip(slots, slots[1:])
    )


def test_bridge_segmentation_keeps_minimum_spacing_and_capacity_prefixes() -> None:
    walkable = box(-0.28, 0.0, 4.0, 2.0)

    def compile_slots(capacity: int):
        queue = QueueSpec(
            id=f"minimum_bridge_spacing_{capacity}",
            owner_element_id="facility",
            kind="lane",
            level_id="level",
            geometry=ElementGeometry(
                "rect",
                x_m=0.4,
                y_m=0.0,
                width_m=3.6,
                height_m=2.0,
            ),
            service_point_m=(-0.3, 1.0),
            capacity=capacity,
            spacing_m=0.4,
        )
        return _queue_slots_from_geometry(queue, walkable)

    with pytest.raises(ValueError, match="bridge cannot fit"):
        compile_slots(2)

    compiled = {capacity: compile_slots(capacity) for capacity in (3, 4, 8)}
    longest = compiled[8]

    assert all(
        slots == longest[:capacity]
        for capacity, slots in compiled.items()
    )
    assert all(
        hypot(right[0] - left[0], right[1] - left[1])
        >= MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
        for left, right in zip(longest, longest[1:])
    )


def test_queue_service_point_cannot_bridge_disconnected_walkable_components() -> None:
    walkable = unary_union((box(0.0, 0.0, 4.0, 2.0), box(6.0, 0.0, 10.0, 2.0)))
    queue = QueueSpec(
        id="service_in_gap",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry("rect", x_m=0.0, y_m=0.0, width_m=10.0, height_m=2.0),
        service_point_m=(5.0, 1.0),
        capacity=12,
        spacing_m=0.4,
    )

    with pytest.raises(ValueError, match="service point cannot reach"):
        _queue_slots_from_geometry(queue, walkable)


@pytest.mark.parametrize("angle_degrees", (0.0, 37.0, 90.0, 173.0))
def test_service_inside_another_component_is_not_an_external_portal(
    angle_degrees: float,
) -> None:
    left = box(-1.0, 0.0, 0.0, 2.0)
    right = box(0.05, 0.0, 4.0, 2.0)
    walkable = affinity.rotate(
        unary_union((left, right)),
        angle_degrees,
        origin=(0.0, 0.0),
    )
    queue_polygon = affinity.rotate(
        right,
        angle_degrees,
        origin=(0.0, 0.0),
    )
    service = affinity.rotate(
        Point(-0.01, 1.0),
        angle_degrees,
        origin=(0.0, 0.0),
    )
    queue = QueueSpec(
        id="cross_component_portal",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "polygon",
            points_m=tuple(queue_polygon.exterior.coords[:-1]),
        ),
        service_point_m=(service.x, service.y),
        capacity=8,
        spacing_m=0.4,
    )

    with pytest.raises(ValueError, match="disconnected walkable component"):
        _queue_slots_from_geometry(queue, walkable)


def test_facility_portal_may_sit_just_outside_one_walkable_boundary() -> None:
    walkable = box(0.0, 0.0, 4.0, 2.0)
    queue = QueueSpec(
        id="boundary_portal",
        owner_element_id="facility",
        kind="lane",
        level_id="level",
        geometry=ElementGeometry(
            "rect",
            x_m=0.0,
            y_m=0.0,
            width_m=4.5,
            height_m=2.0,
        ),
        service_point_m=(4.4, 1.0),
        capacity=8,
        spacing_m=0.8,
    )

    slots = _queue_slots_from_geometry(queue, walkable)

    assert len(slots) == 8
    boundary_entry = Point(4.0, 1.0)
    assert walkable.buffer(1e-7).covers(
        LineString(((boundary_entry.x, boundary_entry.y), slots[0]))
    )


@pytest.mark.parametrize("domain_kind", ("u_shape", "hole"))
def test_queue_capacity_and_connectivity_are_rigid_transform_invariant(
    domain_kind: str,
) -> None:
    if domain_kind == "u_shape":
        walkable = Polygon(
            ((0, 0), (8, 0), (8, 8), (6, 8), (6, 2), (2, 2), (2, 8), (0, 8))
        )
        queue_polygon = walkable
        service = Point(4.0, 1.0)
    else:
        walkable = Polygon(
            ((0, 0), (10, 0), (10, 8), (0, 8)),
            holes=(((3, 2), (7, 2), (7, 6), (3, 6)),),
        )
        queue_polygon = box(0.0, 0.0, 10.0, 8.0)
        service = Point(1.0, 1.0)

    capacities: list[int] = []
    for angle_degrees in (0.0, 37.0, 90.0, 173.0):
        transformed_walkable = affinity.translate(
            affinity.rotate(walkable, angle_degrees, origin=(0.0, 0.0)),
            xoff=11.0,
            yoff=-4.0,
        )
        transformed_queue = affinity.translate(
            affinity.rotate(queue_polygon, angle_degrees, origin=(0.0, 0.0)),
            xoff=11.0,
            yoff=-4.0,
        )
        transformed_service = affinity.translate(
            affinity.rotate(service, angle_degrees, origin=(0.0, 0.0)),
            xoff=11.0,
            yoff=-4.0,
        )
        queue = QueueSpec(
            id="rigid_transform",
            owner_element_id="facility",
            kind="lane",
            level_id="level",
            geometry=ElementGeometry(
                "polygon",
                points_m=tuple(transformed_queue.exterior.coords[:-1]),
            ),
            service_point_m=(transformed_service.x, transformed_service.y),
            capacity=96,
            spacing_m=0.8,
        )

        slots = _queue_slots_from_geometry(queue, transformed_walkable)
        capacities.append(len(slots))
        safe_domain = transformed_walkable.buffer(1e-7)
        assert all(
            safe_domain.covers(LineString((left, right)))
            for left, right in zip(slots, slots[1:])
        )
        assert all(
            hypot(right[0] - left[0], right[1] - left[1]) <= 1.29
            for left, right in zip(slots, slots[1:])
        )

    assert len(set(capacities)) == 1


def _maximum_turn_degrees(points: tuple[tuple[float, float], ...]) -> float:
    maximum = 0.0
    for first, second, third in zip(points, points[1:], points[2:]):
        left = (second[0] - first[0], second[1] - first[1])
        right = (third[0] - second[0], third[1] - second[1])
        left_length = hypot(*left)
        right_length = hypot(*right)
        if left_length <= 1e-9 or right_length <= 1e-9:
            continue
        cosine = max(
            -1.0,
            min(1.0, (left[0] * right[0] + left[1] * right[1]) / (left_length * right_length)),
        )
        maximum = max(maximum, degrees(acos(cosine)))
    return maximum
