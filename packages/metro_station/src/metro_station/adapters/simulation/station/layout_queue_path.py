from __future__ import annotations

from heapq import heappop, heappush
from math import floor, hypot

from shapely.geometry import LineString

from ..design.schema import (
    MAX_COMPILED_QUEUE_CAPACITY,
    MIN_COMPILED_QUEUE_SPACING_M,
)
from .layout_types import Point


_QUEUE_COORDINATE_DECIMALS = 6
_QUEUE_COORDINATE_QUANTIZATION_M = 10.0 ** -_QUEUE_COORDINATE_DECIMALS
QUEUE_CLEARANCE_EPSILON_M = 4.0 * _QUEUE_COORDINATE_QUANTIZATION_M
QUEUE_EXACT_SEARCH_EXPANSION_BUDGET = 100_000


def connected_queue_slot_path(
    ordered_candidates: list[Point],
    *,
    domain,
    spacing: float,
    target_length: int,
    service_point: Point,
    allow_diagonal: bool = False,
    exact_search_budget: list[int] | None = None,
) -> tuple[Point, ...]:
    """Keep the maximal local slot path; never bridge a gap or obstacle."""

    if not ordered_candidates:
        return ()
    requested_length = max(1, min(int(target_length), len(ordered_candidates)))
    canonical_target_length = requested_length
    candidate_limit = min(
        len(ordered_candidates),
        MAX_COMPILED_QUEUE_CAPACITY * 2,
    )
    centroid = domain.centroid
    tail = _normalize(
        (float(centroid.x) - service_point[0], float(centroid.y) - service_point[1])
    )
    lateral = (-tail[1], tail[0])

    def intrinsic_key(point: Point) -> tuple[float, float, float]:
        dx = point[0] - service_point[0]
        dy = point[1] - service_point[1]
        return (
            round((dx * tail[0] + dy * tail[1]) / spacing, 5),
            round((dx * lateral[0] + dy * lateral[1]) / spacing, 5),
            round(_point_distance(service_point, point) / spacing, 5),
        )

    intrinsic_order = sorted(ordered_candidates, key=intrinsic_key)
    global_rank = {point: index for index, point in enumerate(intrinsic_order)}
    maximum_step = max(
        MIN_COMPILED_QUEUE_SPACING_M,
        spacing * (1.6 if allow_diagonal else 1.1),
    )
    covered_domain = domain.buffer(1e-7)

    def point_path_is_valid(points: list[Point]) -> bool:
        if not all(
            _point_distance(left, right) <= maximum_step
            and covered_domain.covers(LineString((left, right)))
            for left, right in zip(points, points[1:])
        ):
            return False
        edges = tuple(zip(points, points[1:]))
        return all(
            segment_distance(left_start, left_end, right_start, right_end)
            >= MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
            for left_edge_index, (left_start, left_end) in enumerate(edges)
            for right_start, right_end in edges[left_edge_index + 2 :]
        )

    start_point = min(
        ordered_candidates,
        key=lambda point: (
            _point_distance(service_point, point),
            global_rank[point],
        ),
    )
    start_in_full_order = ordered_candidates.index(start_point)
    direct_point_paths: list[list[Point]] = []
    if start_in_full_order + canonical_target_length <= len(ordered_candidates):
        direct_point_paths.append(
            ordered_candidates[
                start_in_full_order : start_in_full_order + canonical_target_length
            ]
        )
    if start_in_full_order - canonical_target_length + 1 >= 0:
        direct_point_paths.append(
            list(
                reversed(
                    ordered_candidates[
                        start_in_full_order
                        - canonical_target_length
                        + 1 : start_in_full_order
                        + 1
                    ]
                )
            )
        )
    direct_point_path = next(
        (path for path in direct_point_paths if point_path_is_valid(path)),
        None,
    )
    if direct_point_path is not None:
        return tuple(direct_point_path[:requested_length])

    all_buckets: dict[tuple[int, int], list[Point]] = {}
    for point in ordered_candidates:
        key = (
            int(floor(point[0] / maximum_step)),
            int(floor(point[1] / maximum_step)),
        )
        all_buckets.setdefault(key, []).append(point)
    full_adjacency: dict[Point, tuple[Point, ...]] = {}

    def valid_neighbours(point: Point) -> tuple[Point, ...]:
        cached = full_adjacency.get(point)
        if cached is not None:
            return cached
        cell_x = int(floor(point[0] / maximum_step))
        cell_y = int(floor(point[1] / maximum_step))
        neighbours = tuple(
            sorted(
                (
                    other
                    for x_offset in (-1, 0, 1)
                    for y_offset in (-1, 0, 1)
                    for other in all_buckets.get(
                        (cell_x + x_offset, cell_y + y_offset),
                        (),
                    )
                    if other != point
                    and _point_distance(point, other) <= maximum_step
                    and covered_domain.covers(LineString((point, other)))
                ),
                key=lambda other: global_rank[other],
            )
        )
        full_adjacency[point] = neighbours
        return neighbours

    search_directions = tuple(
        dict.fromkeys(
            (
                _normalize(direction)
                for direction in (
                    tail,
                    (-tail[0], -tail[1]),
                    lateral,
                    (-lateral[0], -lateral[1]),
                    (tail[0] + lateral[0], tail[1] + lateral[1]),
                    (tail[0] - lateral[0], tail[1] - lateral[1]),
                    (-tail[0] + lateral[0], -tail[1] + lateral[1]),
                    (-tail[0] - lateral[0], -tail[1] - lateral[1]),
                )
            )
        )
    )
    deepest_path: list[Point] = [start_point]
    discovery: list[Point] = [start_point]
    for direction in search_directions:
        directional_discovery: list[Point] = []
        parent: dict[Point, Point | None] = {start_point: None}
        depth = {start_point: 0}
        frontier: list[tuple[float, int, int, Point]] = []
        heappush(frontier, (0.0, 0, global_rank[start_point], start_point))
        while frontier and len(directional_discovery) < candidate_limit:
            _negative_progress, _negative_depth, _rank, point = heappop(frontier)
            directional_discovery.append(point)
            for neighbour in valid_neighbours(point):
                if neighbour in parent:
                    continue
                parent[neighbour] = point
                depth[neighbour] = depth[point] + 1
                progress = (
                    (neighbour[0] - service_point[0]) * direction[0]
                    + (neighbour[1] - service_point[1]) * direction[1]
                )
                heappush(
                    frontier,
                    (
                        -round(progress / spacing, 6),
                        -depth[neighbour],
                        global_rank[neighbour],
                        neighbour,
                    ),
                )
        farthest = max(
            directional_discovery,
            key=lambda point: (depth[point], -global_rank[point]),
        )
        directional_path: list[Point] = []
        cursor: Point | None = farthest
        while cursor is not None:
            directional_path.append(cursor)
            cursor = parent[cursor]
        directional_path.reverse()
        if (
            len(directional_path) > len(deepest_path)
            and point_path_is_valid(directional_path)
        ):
            deepest_path = directional_path
            discovery = directional_discovery
        if len(deepest_path) >= canonical_target_length:
            break

    if (
        len(deepest_path) >= canonical_target_length
        and point_path_is_valid(deepest_path[:canonical_target_length])
    ):
        return tuple(deepest_path[:requested_length])

    selected = set(deepest_path)
    for point in discovery:
        if len(selected) >= candidate_limit:
            break
        selected.add(point)

    ordered_candidates = [
        point for point in ordered_candidates if point in selected
    ]
    target_length = min(requested_length, len(ordered_candidates))
    search_goal_length = min(canonical_target_length, len(ordered_candidates))
    intrinsic_order = sorted(ordered_candidates, key=intrinsic_key)
    rank = {point: index for index, point in enumerate(intrinsic_order)}
    adjacency: dict[Point, tuple[Point, ...]] = {}
    for point in ordered_candidates:
        adjacency[point] = tuple(
            sorted(
                (other for other in valid_neighbours(point) if other in selected),
                key=lambda other: rank[other],
            )
        )

    point_index = {point: index for index, point in enumerate(ordered_candidates)}
    adjacency_indices = tuple(
        tuple(point_index[other] for other in adjacency[point])
        for point in ordered_candidates
    )
    adjacency_masks = tuple(
        sum(1 << other_index for other_index in neighbours)
        for neighbours in adjacency_indices
    )
    rank_by_index = tuple(rank[point] for point in ordered_candidates)
    start = point_index[start_point]

    def direct_path_is_valid(path: tuple[int, ...]) -> bool:
        if not path or path[0] != start:
            return False
        if not all(
            right in adjacency_indices[left]
            for left, right in zip(path, path[1:])
        ):
            return False
        edges = tuple(zip(path, path[1:]))
        return all(
            segment_distance(
                ordered_candidates[left_start],
                ordered_candidates[left_end],
                ordered_candidates[right_start],
                ordered_candidates[right_end],
            )
            >= MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
            for left_edge_index, (left_start, left_end) in enumerate(edges)
            for right_start, right_end in edges[left_edge_index + 2 :]
        )

    direct_paths = []
    if start + search_goal_length <= len(ordered_candidates):
        direct_paths.append(tuple(range(start, start + search_goal_length)))
    if start - search_goal_length + 1 >= 0:
        direct_paths.append(tuple(range(start, start - search_goal_length, -1)))
    direct_path = next(
        (path for path in direct_paths if direct_path_is_valid(path)),
        None,
    )
    if direct_path is not None:
        return tuple(
            ordered_candidates[index] for index in direct_path[:target_length]
        )
    start_state = ((start,), 1 << start)
    states: list[tuple[tuple[int, ...], int]] = [start_state]
    best = start_state[0]
    beam_width = 16

    def extension_is_clear(path: tuple[int, ...], candidate: int) -> bool:
        if not allow_diagonal:
            return True
        previous = ordered_candidates[path[-1]]
        candidate_point = ordered_candidates[candidate]
        clearance = MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
        new_min_x = min(previous[0], candidate_point[0])
        new_max_x = max(previous[0], candidate_point[0])
        new_min_y = min(previous[1], candidate_point[1])
        new_max_y = max(previous[1], candidate_point[1])
        for left, right in zip(path[:-2], path[1:-1]):
            old_left = ordered_candidates[left]
            old_right = ordered_candidates[right]
            old_min_x = min(old_left[0], old_right[0])
            old_max_x = max(old_left[0], old_right[0])
            old_min_y = min(old_left[1], old_right[1])
            old_max_y = max(old_left[1], old_right[1])
            if (
                new_min_x - old_max_x >= clearance
                or old_min_x - new_max_x >= clearance
                or new_min_y - old_max_y >= clearance
                or old_min_y - new_max_y >= clearance
            ):
                continue
            if (
                segment_distance(
                    previous,
                    candidate_point,
                    old_left,
                    old_right,
                )
                < clearance
            ):
                return False
        return True

    while states and len(best) < search_goal_length:
        expanded = []
        for path, visited in states:
            for candidate in adjacency_indices[path[-1]]:
                candidate_bit = 1 << candidate
                if visited & candidate_bit:
                    continue
                if not extension_is_clear(path, candidate):
                    continue
                new_path = (*path, candidate)
                new_visited = visited | candidate_bit
                onward_count = (
                    adjacency_masks[candidate] & ~new_visited
                ).bit_count()
                dead_end = int(
                    len(new_path) < search_goal_length and onward_count == 0
                )
                score = (
                    dead_end,
                    onward_count,
                    tuple(rank_by_index[index] for index in new_path[-4:]),
                )
                expanded.append((score, new_path, new_visited))
                if len(new_path) > len(best):
                    best = new_path
                if len(best) >= search_goal_length:
                    return tuple(
                        ordered_candidates[index] for index in best[:target_length]
                    )

        expanded.sort(key=lambda item: item[0])
        states = [(path, visited) for _score, path, visited in expanded[:beam_width]]

    exact = None
    if not allow_diagonal:
        exact = _bounded_hamiltonian_fallback(
            adjacency_indices,
            adjacency_masks,
            rank_by_index,
            start,
            search_goal_length,
            extension_is_clear,
            expansion_budget=(
                exact_search_budget or [QUEUE_EXACT_SEARCH_EXPANSION_BUDGET]
            ),
        )
    if exact is not None:
        return tuple(
            ordered_candidates[index] for index in exact[:target_length]
        )
    return tuple(
        ordered_candidates[index] for index in best[:target_length]
    )


def _bounded_hamiltonian_fallback(
    adjacency: tuple[tuple[int, ...], ...],
    adjacency_masks: tuple[int, ...],
    rank_by_index: tuple[int, ...],
    start: int,
    target_length: int,
    extension_is_clear,
    *,
    expansion_budget: list[int],
) -> tuple[int, ...] | None:
    """Resolve small obstructed cardinal lattices after the beam misses a full path.

    Hamilton search is exponential in general.  This fallback is deliberately
    limited to small graphs and a fixed expansion budget, with connectivity and
    residual-endpoint pruning.  Large concourses retain the bounded beam path;
    ordinary small rooms with pillars do not silently lose capacity merely
    because the beam discarded the necessary early turn.  Diagonal graphs are
    excluded by the caller because edge-clearance validity depends on path
    history, so ``(endpoint, visited)`` is not a sound memoization key there.
    """

    node_count = len(adjacency)
    if target_length != node_count or node_count > 64:
        return None
    full_mask = (1 << node_count) - 1
    def residual_is_viable(endpoint: int, visited: int) -> bool:
        unvisited = full_mask & ~visited
        if not unvisited:
            return True
        if adjacency_masks[endpoint] & unvisited == 0:
            return False
        # Once the path leaves its current endpoint it cannot use that endpoint
        # again as a bridge.  Therefore the graph induced by all still-
        # unvisited vertices must itself be connected; checking connectivity
        # through the endpoint is necessary but not sufficient.
        first_unvisited = unvisited & -unvisited
        frontier = first_unvisited
        seen_unvisited = 0
        while frontier:
            bit = frontier & -frontier
            frontier ^= bit
            index = bit.bit_length() - 1
            if seen_unvisited & bit:
                continue
            seen_unvisited |= bit
            frontier |= adjacency_masks[index] & unvisited & ~seen_unvisited
        if seen_unvisited != unvisited:
            return False
        allowed = unvisited | (1 << endpoint)

        residual_endpoints = 0
        residual_color_counts = [int(colors[endpoint] == 0), int(colors[endpoint] == 1)]
        remaining = unvisited
        while remaining:
            bit = remaining & -remaining
            remaining ^= bit
            index = bit.bit_length() - 1
            if bipartite:
                residual_color_counts[colors[index]] += 1
            degree = (adjacency_masks[index] & allowed).bit_count()
            if degree == 0:
                return False
            if degree == 1:
                residual_endpoints += 1
                if residual_endpoints > 1:
                    return False
        if bipartite:
            if abs(residual_color_counts[0] - residual_color_counts[1]) > 1:
                return False
            residual_node_count = residual_color_counts[0] + residual_color_counts[1]
            if (
                residual_node_count % 2 == 1
                and residual_color_counts[colors[endpoint]]
                < max(residual_color_counts)
            ):
                return False
        return True

    def search(
        path: tuple[int, ...],
        visited: int,
        *,
        reverse_rank: bool,
        order_budget: list[int],
        dead_states: set[tuple[int, int]],
        exhausted: list[bool],
    ) -> tuple[int, ...] | None:
        if len(path) == target_length:
            return path
        if expansion_budget[0] <= 0 or order_budget[0] <= 0:
            exhausted[0] = True
            return None
        state_key = (path[-1], visited)
        if state_key in dead_states:
            return None
        expansion_budget[0] -= 1
        order_budget[0] -= 1
        candidates = [
            candidate
            for candidate in adjacency[path[-1]]
            if not visited & (1 << candidate)
            and extension_is_clear(path, candidate)
        ]
        candidates.sort(
            key=lambda candidate: (
                (adjacency_masks[candidate] & ~visited & ~(1 << candidate)).bit_count(),
                -rank_by_index[candidate] if reverse_rank else rank_by_index[candidate],
            )
        )
        for candidate in candidates:
            candidate_bit = 1 << candidate
            new_visited = visited | candidate_bit
            if not residual_is_viable(candidate, new_visited):
                continue
            result = search(
                (*path, candidate),
                new_visited,
                reverse_rank=reverse_rank,
                order_budget=order_budget,
                dead_states=dead_states,
                exhausted=exhausted,
            )
            if result is not None:
                return result
        if not exhausted[0]:
            dead_states.add(state_key)
        return None

    colors = [-1] * node_count
    colors[start] = 0
    frontier = [start]
    bipartite = True
    while frontier and bipartite:
        node = frontier.pop()
        for neighbour in adjacency[node]:
            if colors[neighbour] < 0:
                colors[neighbour] = 1 - colors[node]
                frontier.append(neighbour)
            elif colors[neighbour] == colors[node]:
                bipartite = False
                break
    if bipartite:
        color_counts = (colors.count(0), colors.count(1))
        if abs(color_counts[0] - color_counts[1]) > 1:
            return None
        if node_count % 2 == 1 and color_counts[colors[start]] < max(color_counts):
            return None
    initial_visited = 1 << start
    if not residual_is_viable(start, initial_visited):
        return None
    remaining_budget = expansion_budget[0]
    order_allocations = (
        (False, (remaining_budget + 1) // 2),
        (True, remaining_budget // 2),
    )
    for reverse_rank, allocation in order_allocations:
        if allocation <= 0 or expansion_budget[0] <= 0:
            continue
        result = search(
            (start,),
            initial_visited,
            reverse_rank=reverse_rank,
            order_budget=[min(allocation, expansion_budget[0])],
            dead_states=set(),
            exhausted=[False],
        )
        if result is not None:
            return result
    return None


def segments_intersect(
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
    *,
    epsilon: float = 1e-9,
) -> bool:
    """Return whether two closed 2-D segments cross, touch, or overlap."""

    def orientation(left: Point, middle: Point, right: Point) -> float:
        return (middle[0] - left[0]) * (right[1] - left[1]) - (
            middle[1] - left[1]
        ) * (right[0] - left[0])

    def on_segment(start: Point, point: Point, end: Point) -> bool:
        return (
            min(start[0], end[0]) - epsilon
            <= point[0]
            <= max(start[0], end[0]) + epsilon
            and min(start[1], end[1]) - epsilon
            <= point[1]
            <= max(start[1], end[1]) + epsilon
        )

    first_side_a = orientation(first_start, first_end, second_start)
    first_side_b = orientation(first_start, first_end, second_end)
    second_side_a = orientation(second_start, second_end, first_start)
    second_side_b = orientation(second_start, second_end, first_end)
    if (
        (
            (first_side_a > epsilon and first_side_b < -epsilon)
            or (first_side_a < -epsilon and first_side_b > epsilon)
        )
        and (
            (second_side_a > epsilon and second_side_b < -epsilon)
            or (second_side_a < -epsilon and second_side_b > epsilon)
        )
    ):
        return True
    if abs(first_side_a) <= epsilon and on_segment(first_start, second_start, first_end):
        return True
    if abs(first_side_b) <= epsilon and on_segment(first_start, second_end, first_end):
        return True
    if abs(second_side_a) <= epsilon and on_segment(second_start, first_start, second_end):
        return True
    if abs(second_side_b) <= epsilon and on_segment(second_start, first_end, second_end):
        return True
    return False


def segment_distance(
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
) -> float:
    """Euclidean clearance between two closed 2-D segments."""

    if segments_intersect(first_start, first_end, second_start, second_end):
        return 0.0

    def point_to_segment(point: Point, start: Point, end: Point) -> float:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length_squared = dx * dx + dy * dy
        if length_squared <= 1e-18:
            return _point_distance(point, start)
        ratio = max(
            0.0,
            min(
                1.0,
                ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
                / length_squared,
            ),
        )
        projection = (start[0] + ratio * dx, start[1] + ratio * dy)
        return _point_distance(point, projection)

    return min(
        point_to_segment(first_start, second_start, second_end),
        point_to_segment(first_end, second_start, second_end),
        point_to_segment(second_start, first_start, first_end),
        point_to_segment(second_end, first_start, first_end),
    )


def _normalize(vector: Point) -> Point:
    length = hypot(vector[0], vector[1])
    if length <= 0.001:
        return (1.0, 0.0)
    return vector[0] / length, vector[1] / length


def _point_distance(a: Point, b: Point) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])
