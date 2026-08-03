"""Build versioned visualization bundles from simulation snapshots."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ..facilities.process import FacilityKind
from ..facilities.service_events import FacilityServiceEvent
from ..runtime.contracts import (
    track_point_meta,
)
from ..runtime.snapshots import FrameSnapshot
from ..station.scenario import StationSandboxScenario
from ..presets.visual_demo_config import CANVAS_HEIGHT_PX as H
from ..presets.visual_demo_config import CANVAS_WIDTH_PX as W

from .visual_track_samples import _canvas_position


FrameInput = FrameSnapshot | Mapping[str, Any]


_PRESENTATION_LAYERS_KEY = "_presentation_layers"
_PRESENTATION_POINTS_KEY = "presentation_points"
_GATE_LAYER = "gate_service"
_VERTICAL_LAYER = "vertical_service"
_LAYER_PRIORITY = {_VERTICAL_LAYER: 10, _GATE_LAYER: 20}


def _insert_gate_service_waypoints(
    agents_by_id: dict[int, dict[str, object]],
    events: Sequence[FacilityServiceEvent],
    scenario: StationSandboxScenario,
) -> None:
    _reset_presentation_layer(agents_by_id, _GATE_LAYER)
    for event in sorted(events, key=_service_event_sort_key):
        if event.facility_kind != FacilityKind.GATE.value:
            continue
        service_entry_position = _canvas_position(event.start_position, scenario)
        release_position = _canvas_position(event.end_position, scenario)
        for passenger_id in event.passenger_ids:
            record = agents_by_id.get(int(passenger_id))
            if record is None:
                continue
            points = record.get("points")
            if not isinstance(points, list) or len(points) < 2:
                continue
            inserted = _gate_presentation_waypoints(
                points,
                event,
                service_entry_position,
                release_position,
            )
            _append_presentation_layer_points(record, _GATE_LAYER, inserted)


def _insert_vertical_service_waypoints(
    agents_by_id: dict[int, dict[str, object]],
    events: Sequence[FacilityServiceEvent],
    scenario: StationSandboxScenario,
) -> None:
    vertical_kinds = {
        FacilityKind.ESCALATOR.value,
        FacilityKind.ELEVATOR.value,
        FacilityKind.STAIRS.value,
    }
    visual_slots = _vertical_service_visual_slots(events, vertical_kinds)
    _reset_presentation_layer(agents_by_id, _VERTICAL_LAYER)
    for event in sorted(events, key=_service_event_sort_key):
        if event.facility_kind not in vertical_kinds:
            continue
        start_position = _canvas_position(event.start_position, scenario)
        end_position = _canvas_position(event.end_position, scenario)
        for passenger_id in event.passenger_ids:
            record = agents_by_id.get(int(passenger_id))
            if record is None:
                continue
            points = record.get("points")
            if not isinstance(points, list) or len(points) < 2:
                continue
            slot, group_size = visual_slots.get((event.event_id, int(passenger_id)), (0, 1))
            lane_offset_px, progress_offset = _vertical_service_visual_offsets(
                event,
                slot,
                group_size,
            )
            visual_points = _facility_service_presentation_points(
                points,
                event,
                start_position,
                end_position,
                lane_offset_px=lane_offset_px,
                progress_offset=progress_offset,
                reason="vertical_service_visual_smoothing",
            )
            _append_presentation_layer_points(
                record,
                _VERTICAL_LAYER,
                visual_points,
                replace_interval=_event_motion_window(event),
            )


def _finalize_presentation_service_waypoints(
    agents_by_id: dict[int, dict[str, object]],
) -> None:
    """Compose isolated presentation layers without changing source ``points``."""

    for record in agents_by_id.values():
        source_points = record.get("points")
        layers = record.pop(_PRESENTATION_LAYERS_KEY, None)
        if not isinstance(source_points, list) or not isinstance(layers, dict):
            record.pop(_PRESENTATION_POINTS_KEY, None)
            continue

        replace_intervals = [
            interval
            for layer in layers.values()
            if isinstance(layer, dict)
            for interval in layer.get("replace_intervals", [])
            if isinstance(interval, tuple) and len(interval) == 2
        ]
        candidates: list[tuple[int, list[Any]]] = []
        for point in source_points:
            if _point_in_any_interval(point, replace_intervals):
                continue
            candidates.append((0, _clone_track_point(point)))

        for layer_name in sorted(layers):
            layer = layers[layer_name]
            if not isinstance(layer, dict):
                continue
            priority = _LAYER_PRIORITY.get(layer_name, 0)
            for point in layer.get("points", []):
                if isinstance(point, list | tuple):
                    candidates.append((priority, _clone_track_point(point)))

        points_by_time: dict[float, tuple[tuple[object, ...], list[Any]]] = {}
        for priority, point in candidates:
            time_key = round(float(point[0]), 2)
            rank = (priority, *_presentation_point_sort_key(point)[1:])
            existing = points_by_time.get(time_key)
            if existing is None or rank > existing[0]:
                points_by_time[time_key] = (rank, point)
        record[_PRESENTATION_POINTS_KEY] = [
            points_by_time[time_key][1] for time_key in sorted(points_by_time)
        ]


def _reset_presentation_layer(
    agents_by_id: dict[int, dict[str, object]],
    layer_name: str,
) -> None:
    for record in agents_by_id.values():
        layers = record.get(_PRESENTATION_LAYERS_KEY)
        if isinstance(layers, dict):
            layers.pop(layer_name, None)


def _append_presentation_layer_points(
    record: dict[str, object],
    layer_name: str,
    points: Sequence[Any],
    *,
    replace_interval: tuple[float, float] | None = None,
) -> None:
    if not points:
        return
    layers = record.setdefault(_PRESENTATION_LAYERS_KEY, {})
    assert isinstance(layers, dict)
    layer = layers.setdefault(layer_name, {"points": [], "replace_intervals": []})
    assert isinstance(layer, dict)
    layer_points = layer["points"]
    assert isinstance(layer_points, list)
    layer_points.extend(_clone_track_point(point) for point in points)
    if replace_interval is None:
        return
    replace_intervals = layer["replace_intervals"]
    assert isinstance(replace_intervals, list)
    replace_intervals.append(replace_interval)


def _point_in_any_interval(
    point: Sequence[Any],
    intervals: Sequence[tuple[float, float]],
) -> bool:
    time_s = float(point[0])
    return any(start - 0.001 <= time_s <= end + 0.001 for start, end in intervals)


def _clone_track_point(point: Sequence[Any]) -> list[Any]:
    cloned = list(point)
    if len(cloned) > 9 and isinstance(cloned[9], dict):
        cloned[9] = dict(cloned[9])
    return cloned


def _presentation_point_sort_key(point: Sequence[Any]) -> tuple[object, ...]:
    meta = point[9] if len(point) > 9 and isinstance(point[9], dict) else {}
    return (
        round(float(point[0]), 2),
        str(meta.get("reason", "")),
        round(float(point[1]), 4),
        round(float(point[2]), 4),
    )


def _event_motion_window(event: FacilityServiceEvent) -> tuple[float, float]:
    move_start = event.board_end_time if event.board_end_time is not None else event.start_time
    move_end = event.arrive_time if event.arrive_time is not None else event.end_time
    return float(move_start), float(move_end)


def _service_event_sort_key(event: FacilityServiceEvent) -> tuple[object, ...]:
    move_start, move_end = _event_motion_window(event)
    return (
        move_start,
        move_end,
        event.facility_kind,
        event.facility_id,
        event.event_id,
        event.passenger_ids,
    )


def _vertical_service_visual_slots(
    events: Sequence[FacilityServiceEvent],
    vertical_kinds: set[str],
) -> dict[tuple[int, int], tuple[int, int]]:
    groups: dict[tuple[str, str, float, float], list[tuple[int, int]]] = {}
    for event in events:
        if event.facility_kind not in vertical_kinds:
            continue
        move_start, move_end = _event_motion_window(event)
        key = (event.facility_id, event.facility_kind, round(move_start, 2), round(move_end, 2))
        group = groups.setdefault(key, [])
        for passenger_id in event.passenger_ids:
            group.append((event.event_id, int(passenger_id)))

    slots: dict[tuple[int, int], tuple[int, int]] = {}
    for group in groups.values():
        group_size = len(group)
        for slot, item in enumerate(sorted(group)):
            slots[item] = (slot, group_size)
    return slots


def _vertical_service_visual_offsets(
    event: FacilityServiceEvent,
    slot: int,
    group_size: int,
) -> tuple[float, float]:
    if group_size <= 1:
        return 0.0, 0.0
    if event.facility_kind == FacilityKind.ELEVATOR.value:
        lane_count = 2
        lane_width_px = 5.5
        row_progress = 0.045
    elif event.facility_kind == FacilityKind.STAIRS.value:
        lane_count = 5
        lane_width_px = 5.5
        row_progress = 0.055
    elif event.facility_kind == FacilityKind.ESCALATOR.value:
        lane_count = 3
        lane_width_px = 4.0
        row_progress = 0.035
    else:
        return 0.0, 0.0

    active_lanes = min(group_size, lane_count)
    lane_index = slot % active_lanes
    centered_lane = lane_index - (active_lanes - 1) / 2
    row_index = slot // active_lanes
    return centered_lane * lane_width_px, min(0.16, row_index * row_progress)


def _facility_service_presentation_points(
    points: list[Any],
    event: FacilityServiceEvent,
    start_position: tuple[float, float],
    end_position: tuple[float, float],
    *,
    lane_offset_px: float = 0.0,
    progress_offset: float = 0.0,
    reason: str,
) -> list[Any]:
    move_start, move_end = _event_motion_window(event)
    if move_end <= move_start:
        return []

    heading = math.atan2(end_position[1] - start_position[1], end_position[0] - start_position[0])
    visual_points: list[Any] = []
    for point in points:
        time_s = float(point[0])
        if time_s < move_start - 0.001 or time_s > move_end + 0.001:
            continue
        fraction = max(0.0, min(1.0, (time_s - move_start) / (move_end - move_start)))
        visual_points.append(
            _service_waypoint(
                time_s,
                fraction,
                start_position,
                end_position,
                heading,
                lane_offset_px=lane_offset_px,
                progress_offset=progress_offset,
                reason=reason,
            )
        )

    for fraction in (0.25, 0.5, 0.75):
        time_s = move_start + (move_end - move_start) * fraction
        if _has_track_point_near(visual_points, time_s):
            continue
        visual_points.append(
            _service_waypoint(
                time_s,
                fraction,
                start_position,
                end_position,
                heading,
                lane_offset_px=lane_offset_px,
                progress_offset=progress_offset,
                reason=reason,
            )
        )
    visual_points.sort(key=_presentation_point_sort_key)
    return visual_points


def _service_waypoint(
    time_s: float,
    fraction: float,
    start_position: tuple[float, float],
    end_position: tuple[float, float],
    heading: float,
    *,
    lane_offset_px: float = 0.0,
    progress_offset: float = 0.0,
    reason: str,
) -> list[Any]:
    x, y = _service_visual_position(
        start_position,
        end_position,
        fraction,
        lane_offset_px=lane_offset_px,
        progress_offset=progress_offset,
    )
    target_x, target_y = _offset_point_normal(
        start_position, end_position, end_position, lane_offset_px
    )
    return [
        round(time_s, 2),
        round(x, 2),
        round(y, 2),
        round(heading, 4),
        0.94,
        round(target_x, 2),
        round(target_y, 2),
        "targeting",
        "target",
        track_point_meta("interpolation", visual_only=True, reason=reason),
    ]


def _service_visual_position(
    start_position: tuple[float, float],
    end_position: tuple[float, float],
    fraction: float,
    *,
    lane_offset_px: float,
    progress_offset: float,
) -> tuple[float, float]:
    adjusted_fraction = max(0.0, min(1.0, fraction + progress_offset))
    x, y = _lerp_point(start_position, end_position, adjusted_fraction)
    return _offset_point_normal(start_position, end_position, (x, y), lane_offset_px)


def _offset_point_normal(
    start_position: tuple[float, float],
    end_position: tuple[float, float],
    point: tuple[float, float],
    offset_px: float,
) -> tuple[float, float]:
    if abs(offset_px) <= 0.001:
        return point
    dx = end_position[0] - start_position[0]
    dy = end_position[1] - start_position[1]
    length = math.hypot(dx, dy)
    if length <= 0.001:
        return point
    x = point[0] - dy / length * offset_px
    y = point[1] + dx / length * offset_px
    return max(0.0, min(W, x)), max(0.0, min(H, y))


def _has_track_point_near(points: Sequence[Any], time_s: float) -> bool:
    return any(abs(float(point[0]) - time_s) <= 0.02 for point in points)


def _gate_presentation_waypoints(
    points: list[Any],
    event: FacilityServiceEvent,
    service_entry_position: tuple[float, float],
    release_position: tuple[float, float],
) -> list[Any]:
    segment_index = _track_segment_index(points, float(event.start_time))
    if segment_index is None:
        return []

    previous = points[segment_index - 1]
    current = points[segment_index]
    previous_time = float(previous[0])
    current_time = float(current[0])
    span = current_time - previous_time
    if span <= 0.02:
        return []
    px, py = float(previous[1]), float(previous[2])
    cx, cy = float(current[1]), float(current[2])
    previous_position = (px, py)
    current_position = (cx, cy)
    queue_front = _gate_queue_front_position(previous, service_entry_position)
    visual_points: list[tuple[float, tuple[float, float], str, str, tuple[float, float]]] = []
    if queue_front is not None:
        queue_steps = max(
            1,
            min(
                4,
                math.ceil(math.hypot(queue_front[0] - px, queue_front[1] - py) / 28.0),
            ),
        )
        for step in range(1, queue_steps + 1):
            fraction = 0.58 * step / queue_steps
            amount = step / queue_steps
            visual_points.append(
                (
                    fraction,
                    _lerp_point(previous_position, queue_front, amount),
                    "enqueued",
                    "queue",
                    queue_front,
                )
            )
    queue_reaches_service_entry = (
        queue_front is not None
        and math.hypot(
            queue_front[0] - service_entry_position[0],
            queue_front[1] - service_entry_position[1],
        )
        <= 1.0
    )
    if not queue_reaches_service_entry:
        visual_points.append(
            (
                0.66 if queue_front is not None else 0.45,
                service_entry_position,
                "targeting",
                "target",
                release_position,
            )
        )
    visual_points.extend(
        _mechanical_gate_service_points(
            queue_front is not None,
            service_entry_position,
            release_position,
        )
    )

    # A facility event can be shorter than the snapshot interval.  Compressing
    # the approach, queue advance, and mechanical crossing into only that
    # service interval creates impossible 10-20 m/s visual motion.  Distribute
    # the visual-only waypoints over the full pair of truth snapshots instead,
    # in proportion to path length.  The event timestamps remain unchanged in
    # the simulation trace and are therefore still suitable for experiments.
    candidates: list[tuple[tuple[float, float], str, str, tuple[float, float]]] = []
    last_position = previous_position
    for _, position, target_mode, diagnostic, target_position in visual_points:
        if math.hypot(position[0] - last_position[0], position[1] - last_position[1]) <= 0.01:
            continue
        if math.hypot(position[0] - current_position[0], position[1] - current_position[1]) <= 0.01:
            last_position = position
            continue
        candidates.append((position, target_mode, diagnostic, target_position))
        last_position = position

    path_positions = [previous_position, *(item[0] for item in candidates), current_position]
    segment_lengths = [
        math.hypot(right[0] - left[0], right[1] - left[1])
        for left, right in zip(path_positions, path_positions[1:], strict=False)
    ]
    total_distance = sum(segment_lengths)
    if total_distance <= 0.01:
        return []

    inserted = []
    heading_from = previous_position
    cumulative_distance = 0.0
    for index, (position, target_mode, diagnostic, target_position) in enumerate(candidates):
        cumulative_distance += segment_lengths[index]
        waypoint_time = round(previous_time + span * cumulative_distance / total_distance, 2)
        if not previous_time + 0.01 < waypoint_time < current_time - 0.01:
            continue
        heading = math.atan2(position[1] - heading_from[1], position[0] - heading_from[0])
        inserted.append(
            [
                waypoint_time,
                round(position[0], 2),
                round(position[1], 2),
                round(heading, 4),
                0.94,
                round(target_position[0], 2),
                round(target_position[1], 2),
                target_mode,
                diagnostic,
                track_point_meta(
                    "interpolation", visual_only=True, reason="gate_service_visual_smoothing"
                ),
            ]
        )
        heading_from = position
    if not inserted:
        return []
    if current_position == heading_from:
        inserted[-1][3] = float(current[3])
    return inserted


def _gate_queue_front_position(
    point: Sequence[Any],
    gate_position: tuple[float, float],
) -> tuple[float, float] | None:
    if len(point) < 9 or point[7] != "enqueued" or point[8] != "queue":
        return None
    try:
        current = (float(point[1]), float(point[2]))
        target = (float(point[5]), float(point[6]))
    except (TypeError, ValueError):
        return None
    if math.hypot(target[0] - current[0], target[1] - current[1]) <= 3.0:
        return None
    current_to_gate = math.hypot(gate_position[0] - current[0], gate_position[1] - current[1])
    target_to_gate = math.hypot(gate_position[0] - target[0], gate_position[1] - target[1])
    if target_to_gate <= 1.0:
        return target
    if target_to_gate < current_to_gate:
        return gate_position
    if current_to_gate <= 3.0:
        return None
    return gate_position


def _mechanical_gate_service_points(
    has_queue_advance: bool,
    service_entry_position: tuple[float, float],
    release_position: tuple[float, float],
) -> tuple[tuple[float, tuple[float, float], str, str, tuple[float, float]], ...]:
    midpoint = _lerp_point(service_entry_position, release_position, 0.5)
    if has_queue_advance:
        return (
            (0.74, midpoint, "targeting", "target", release_position),
            (0.86, release_position, "targeting", "target", release_position),
        )
    return (
        (0.62, midpoint, "targeting", "target", release_position),
        (0.78, release_position, "targeting", "target", release_position),
    )


def _lerp_point(
    start: tuple[float, float],
    end: tuple[float, float],
    amount: float,
) -> tuple[float, float]:
    return (
        start[0] + (end[0] - start[0]) * amount,
        start[1] + (end[1] - start[1]) * amount,
    )


def _track_segment_index(points: list[Any], event_time: float) -> int | None:
    for index in range(1, len(points)):
        current_time = float(points[index][0])
        if current_time > event_time + 0.001:
            return index
    return None
