"""Default filesystem targets for optional renderer replay artifacts."""

from __future__ import annotations

from pathlib import Path


RENDERER_ROOT = Path(__file__).resolve().parents[1] / "visual_demo"
EXPERIMENT_REPLAY_DIR = RENDERER_ROOT / "assets" / "experiment_tracks"
EXPERIMENT_REPLAY_URL_PREFIX = "assets/experiment_tracks"
