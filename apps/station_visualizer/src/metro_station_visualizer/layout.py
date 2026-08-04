"""Compatibility exports for the visual-demo station layout preset."""

try:
    from metro_station.adapters.simulation.presets.visual_demo_layout import *  # noqa: F403
except ImportError:  # pragma: no cover - direct script compatibility
    from metro_station.adapters.simulation.presets.visual_demo_layout import *  # noqa: F403
