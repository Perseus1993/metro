"""Renderer-facing compatibility facade for the versioned visualization exporter."""

from typing import Any

from metro_station.adapters.simulation.simulation_outputs.visual_tracks import mesa_frames_to_visual_tracks
from metro_station.adapters.simulation.simulation_outputs.visual_tracks import write_mesa_visual_tracks_js as _write_tracks
from .config import TRACKS_JS


def write_mesa_visual_tracks_js(
    *,
    output_path=TRACKS_JS,
    **kwargs: Any,
) -> dict[str, object]:
    return _write_tracks(output_path=output_path, **kwargs)


__all__ = ["mesa_frames_to_visual_tracks", "write_mesa_visual_tracks_js"]
