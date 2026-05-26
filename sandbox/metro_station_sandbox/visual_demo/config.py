from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / "assets"
OUTPUT_DIR = ROOT.parents[2] / "output"

BASE_IMAGE = ASSET_DIR / "station_base.png"
TRACKS_JS = ASSET_DIR / "passenger_tracks_jps.js"
GEOMETRY_PATH = ROOT / "station_geometry_annotations.json"

W = 1672.0
H = 941.0
PX_PER_METER = 20.0
SIM_DURATION = 214.0
CLEARANCE_MAX_DURATION = 600.0
SIM_DT = 0.05
SAMPLE_DT = 0.2
TRAIN_CYCLE = 38.0
PEAK_ROUTE_SPAWNS = 240
