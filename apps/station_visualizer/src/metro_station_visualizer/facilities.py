"""Compatibility exports for visual-demo facility coordinates."""

try:
    from metro_station.adapters.simulation.presets.visual_demo_facilities import *  # noqa: F403
except ImportError:  # pragma: no cover - direct script compatibility
    from metro_station.adapters.simulation.presets.visual_demo_facilities import *  # noqa: F403
