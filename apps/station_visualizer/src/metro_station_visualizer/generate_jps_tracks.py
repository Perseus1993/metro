from __future__ import annotations

from .tracks.builder import build_tracks
from .tracks.cli import main
from .tracks.constants import (
    DOWNSTREAM_BOARDING_QUEUES,
    ENTRY_GATE_PORTAL_RADIUS_M,
    GATE_QUEUE_NAMES,
    POST_GATE_RADIUS_M,
    STATION_EXIT_BAND_HALF_SIZE_M,
    UPSTREAM_EXIT_QUEUES,
)
from .tracks.replanning import queue_field_switching_is_enabled
from .tracks.stages import post_gate_portal_radius
from .tracks.waypoints import routing_area_half_size

__all__ = [
    "DOWNSTREAM_BOARDING_QUEUES",
    "ENTRY_GATE_PORTAL_RADIUS_M",
    "GATE_QUEUE_NAMES",
    "POST_GATE_RADIUS_M",
    "STATION_EXIT_BAND_HALF_SIZE_M",
    "UPSTREAM_EXIT_QUEUES",
    "build_tracks",
    "main",
    "post_gate_portal_radius",
    "queue_field_switching_is_enabled",
    "routing_area_half_size",
]


if __name__ == "__main__":
    main()
