"""Build or verify the content-addressed manifest for ignored experiment assets.

The repository intentionally keeps experiment code, Unity text configuration,
licences, and provenance while excluding large third-party or generated binary
assets.  This script records every excluded asset with its path, byte size,
SHA-256, and a source/rebuild contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTS_ROOT = REPOSITORY_ROOT / "experiments"
MANIFEST_PATH = EXPERIMENTS_ROOT / "ASSET_MANIFEST.json"

SKIP_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "Build",
    "Builds",
    "Library",
    "Logs",
    "Temp",
    "UserSettings",
    "__pycache__",
    "venv",
}

BINARY_SUFFIXES = (
    ".bin",
    ".exr",
    ".fbx",
    ".glb",
    ".gltf",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".tga",
    ".unitypackage",
    ".wav",
    ".zip",
)

MATERIALIZED_ROOTS = (
    "experiments/station_fire_visual_lab/Assets/ThirdParty/MicrosoftRocketbox/Avatars",
    "experiments/station_fire_visual_lab/Assets/Resources/PassengerBases/Rocketbox",
    "experiments/station_fire_visual_lab/Assets/Resources/PassengerBases/RocketboxAnimations",
    "experiments/station_fire_visual_lab/Assets/Resources/PassengerBases/Generated",
    "experiments/station_fire_visual_lab/Assets/HazardVisualLab/ThirdParty/SubwayIncidentProps/Raw",
    "experiments/station_fire_visual_lab/Assets/HazardVisualLab/ThirdParty/SubwayIncidentProps/ElectricalSparks",
    "experiments/station_fire_visual_lab/Assets/HazardVisualLab/ThirdParty/SubwayIncidentProps/Materials",
    "experiments/station_fire_visual_lab/Assets/HazardVisualLab/ThirdParty/SubwayIncidentProps/Prefabs",
    "experiments/station_fire_visual_lab/Assets/Resources/MetroReplay/ThirdParty",
    "experiments/station_fire_visual_lab/Assets/Resources/MetroFire",
    "experiments/hazard_asset_lab/Assets/Solodream",
    "experiments/hazard_asset_lab/Assets/Vefects",
    "experiments/hazard_asset_lab/Assets/HazardAssetLab/ThirdParty",
    "experiments/torch_movement_p1/data",
)

SOURCES: dict[str, dict[str, Any]] = {
    "tracked_app_copy": {
        "kind": "repository_copy",
        "source": "apps/station_unity_replay",
        "version": "the Git revision containing this manifest",
        "restore": "Copy the recorded source_path to path; the manifest hash must match.",
    },
    "microsoft_rocketbox_upstream": {
        "kind": "git",
        "source": "https://github.com/microsoft/Microsoft-Rocketbox",
        "version": "0943055db6ec570bcef9f2c8b41c9e5467c808f9",
        "licence": "MIT",
        "restore": "Clone the pinned revision and copy its complete Assets/Avatars tree.",
    },
    "microsoft_rocketbox_runtime_subset": {
        "kind": "derived_copy",
        "source": "microsoft_rocketbox_upstream",
        "version": "pinned by the upstream source and per-file hashes",
        "restore": "Restore the pinned upstream library, then copy the paths enumerated by this manifest.",
    },
    "rocketbox_generated_library": {
        "kind": "generated",
        "source": "experiments/station_fire_visual_lab/Assets/MetroReplay/Editor/RocketboxPassengerPrefabBuilder.cs",
        "version": "Metro Replay/Build Rocketbox Passenger Library",
        "parameters": {"base_scope": "all restored Rocketbox base models", "lod_levels": 3},
        "restore": "Restore Rocketbox inputs and run the recorded Unity menu command.",
    },
    "subway_terminal_restricted_archive": {
        "kind": "local_archive",
        "source": "Subway_Terminal+For+Unity+URP-nextmodel.cn.zip",
        "version": "sha256:C462C74997CD21CB10C4A2872217C6B7DC8A867EF5CBFD98C3626B31D11C0093",
        "licence": "restricted research prototype; do not redistribute",
        "restore": "Obtain the authorised archive, verify its SHA-256, and copy only the manifest paths.",
    },
    "subway_incident_generated": {
        "kind": "generated",
        "source": "experiments/station_fire_visual_lab/Assets/HazardVisualLab/Editor/SubwayIncidentPropBuilder.cs",
        "version": "Hazard Visual Lab/Build Subway Incident Prop Catalog",
        "parameters": {"render_pipeline": "HDRP", "catalog": "all imported incident props"},
        "restore": "Restore the restricted raw inputs, then run the recorded Unity menu command.",
    },
    "solodream_flame_pack": {
        "kind": "unity_asset_store",
        "source": "https://assetstore.unity.com/packages/vfx/particles/free-asset-vfx-particles-flame-pack-263899",
        "version": "productId:263899; imported package revision is content-addressed per file",
        "licence": "Unity Asset Store EULA",
        "restore": "Import product 263899 into the hazard asset lab and verify every manifest hash.",
    },
    "vefects_free_fire_hdrp": {
        "kind": "unity_asset_import",
        "source": "Vefects Free Fire HDRP",
        "version": "upstream package version not recorded; this is a declared provenance gap",
        "restore": "Recover the original Vefects package and accept it only if every manifest hash matches.",
    },
    "quaternius_ual2_standard": {
        "kind": "download",
        "source": "https://quaternius.com/packs/universalanimationlibrary2.html",
        "version": "Universal Animation Library 2 Standard",
        "licence": "CC0",
        "restore": "Download the Standard pack, import/copy the enumerated paths, and verify hashes.",
    },
    "kenney_cc0": {
        "kind": "download",
        "source": "Kenney Furniture Kit / Conveyor Kit",
        "version": "selected files are content-addressed per manifest entry",
        "licence": "CC0-1.0",
        "restore": "Download the packs named in the tracked provenance documents and verify hashes.",
    },
    "poly_haven_cc0": {
        "kind": "download",
        "source": "https://polyhaven.com/models",
        "version": "1K glTF variants named in tracked provenance",
        "licence": "CC0-1.0",
        "restore": "Download the named 1K glTF variants through Poly Haven and verify hashes.",
    },
    "open_game_art_traffic_road_assets": {
        "kind": "download",
        "source": "https://opengameart.org/content/traffic-road-assets",
        "version": "archive sha256:8401078C95231677C07E1EB1639F8D2F0E222F62F9C1463C3999BDB2A0814237",
        "licence": "CC0-1.0",
        "restore": "Download the pinned archive and copy the two selected road-block models.",
    },
    "mixkit_house_02": {
        "kind": "download",
        "source": "https://assets.mixkit.co/music/744/744.mp3",
        "version": "sha256:5610BA37AB13F997F66C0A00AC1943B782D82F5C04AE1B171E40361CE8EF692F",
        "licence": "Mixkit Stock Music Free License",
        "restore": "Download the recorded track URL and verify its SHA-256.",
    },
    "unity_capture_output": {
        "kind": "generated",
        "source": "Unity editor capture/build helpers tracked beside each experiment",
        "version": "the Git revision containing this manifest",
        "parameters": {"output_paths": "recorded per manifest entry", "authority": "presentation_only"},
        "restore": "Run the matching Unity editor capture/generator under Assets/*/Editor and verify hashes.",
    },
    "institutional_brand_input": {
        "kind": "curated_input",
        "source": "Hiroshima University and Perseus project brand artwork",
        "version": "content-addressed per manifest entry",
        "restore": "Restore the approved brand originals and verify the exact per-file hashes.",
    },
    "juelich_corridor_2": {
        "kind": "research_dataset",
        "source": "Juelich pedestrian-dynamics corridor-2 trajectory export",
        "version": "camera-1 text archive and extracted files are content-addressed per entry",
        "restore": "Obtain the corridor-2 camera-1 dataset, extract it under the recorded path, and verify hashes.",
    },
}


def _relative(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _is_manifest_asset(path: str) -> bool:
    lower = path.lower()
    filename = Path(path).name.lower()
    text_record = any(
        token in filename
        for token in ("license", "licence", "readme", "provenance", "copying", "notice")
    ) and any(
        filename.endswith(suffix)
        for suffix in (".md", ".md.meta", ".txt", ".txt.meta")
    )
    if text_record:
        return False
    if any(_is_under(path, root) for root in MATERIALIZED_ROOTS):
        return True
    return any(lower.endswith(suffix) or lower.endswith(suffix + ".meta") for suffix in BINARY_SUFFIXES)


def _iter_manifest_assets() -> list[Path]:
    found: list[Path] = []
    for directory, child_directories, filenames in os.walk(EXPERIMENTS_ROOT):
        child_directories[:] = sorted(
            name for name in child_directories if name not in SKIP_DIRECTORY_NAMES
        )
        base = Path(directory)
        for filename in sorted(filenames):
            path = base / filename
            relative = _relative(path)
            if _is_manifest_asset(relative):
                found.append(path)
    return sorted(found, key=_relative)


def _tracked_app_hash_index() -> dict[tuple[int, str], str]:
    root = REPOSITORY_ROOT / "apps" / "station_unity_replay"
    index: dict[tuple[int, str], str] = {}
    if not root.is_dir():
        return index
    for directory, child_directories, filenames in os.walk(root):
        child_directories[:] = sorted(
            name for name in child_directories if name not in SKIP_DIRECTORY_NAMES
        )
        base = Path(directory)
        for filename in sorted(filenames):
            path = base / filename
            key = (path.stat().st_size, _sha256(path))
            index.setdefault(key, _relative(path))
    return index


def _classify(path: str) -> str:
    if _is_under(
        path,
        "experiments/station_fire_visual_lab/Assets/ThirdParty/MicrosoftRocketbox/Avatars",
    ):
        return "microsoft_rocketbox_upstream"
    if _is_under(
        path,
        "experiments/station_fire_visual_lab/Assets/Resources/PassengerBases/Generated",
    ):
        return "rocketbox_generated_library"
    if _is_under(
        path,
        "experiments/station_fire_visual_lab/Assets/Resources/PassengerBases/Rocketbox",
    ) or _is_under(
        path,
        "experiments/station_fire_visual_lab/Assets/Resources/PassengerBases/RocketboxAnimations",
    ):
        return "microsoft_rocketbox_runtime_subset"
    if "/SubwayIncidentProps/" in path:
        if "/Raw/" in path or "/ElectricalSparks/Source/" in path:
            return "subway_terminal_restricted_archive"
        return "subway_incident_generated"
    if _is_under(
        path,
        "experiments/station_fire_visual_lab/Assets/Resources/MetroReplay/ThirdParty",
    ):
        return "subway_terminal_restricted_archive"
    if _is_under(path, "experiments/hazard_asset_lab/Assets/Solodream"):
        return "solodream_flame_pack"
    if _is_under(path, "experiments/hazard_asset_lab/Assets/Vefects") or _is_under(
        path,
        "experiments/station_fire_visual_lab/Assets/Resources/MetroFire",
    ):
        return "vefects_free_fire_hdrp"
    if "UniversalAnimationLibrary2" in path or "AnimationLibrary_Godot_Standard" in path:
        return "quaternius_ual2_standard"
    if "/HazardAssetLab/ThirdParty/Quaternius" in path:
        return "quaternius_ual2_standard"
    if "/HazardAssetLab/ThirdParty/MetroReplayResidents" in path:
        return "microsoft_rocketbox_runtime_subset"
    if "/HazardAssetLab/ThirdParty/MetroReplayStation" in path:
        return "subway_terminal_restricted_archive"
    if "/StreamingAssets/Decor/Kenney" in path or "/KenneyTrainKit/" in path:
        return "kenney_cc0"
    if "/StreamingAssets/Decor/PolyHaven/" in path:
        return "poly_haven_cc0"
    if "/OpenGameArtTrafficRoadAssets/" in path:
        return "open_game_art_traffic_road_assets"
    if "/MetroReplay/Editor/Audio/" in path:
        return "mixkit_house_02"
    if "/Assets/Screenshots/" in path or "/HazardAssetLab/Previews/" in path:
        return "unity_capture_output"
    if "/Assets/Resources/BrandIntro/" in path:
        return "institutional_brand_input"
    if _is_under(path, "experiments/torch_movement_p1/data"):
        return "juelich_corridor_2"
    raise ValueError(f"ignored experiment asset has no source/rebuild contract: {path}")


def build_manifest() -> dict[str, Any]:
    app_index = _tracked_app_hash_index()
    entries: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    total_bytes = 0
    aggregate = hashlib.sha256()
    for asset in _iter_manifest_assets():
        path = _relative(asset)
        size = asset.stat().st_size
        sha256 = _sha256(asset)
        app_source = app_index.get((size, sha256))
        source_id = "tracked_app_copy" if app_source else _classify(path)
        entry: dict[str, Any] = {
            "path": path,
            "bytes": size,
            "sha256": sha256,
            "source_id": source_id,
        }
        if app_source:
            entry["source_path"] = app_source
        entries.append(entry)
        source_counts[source_id] += 1
        total_bytes += size
        aggregate.update(path.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(sha256.encode("ascii"))
        aggregate.update(b"\0")
    used_sources = {
        source_id: {**SOURCES[source_id], "asset_count": source_counts[source_id]}
        for source_id in sorted(source_counts)
    }
    return {
        "schema_version": "metro_experiment_asset_manifest.v1",
        "policy": "large third-party and generated experiment assets stay outside Git",
        "summary": {
            "asset_count": len(entries),
            "total_bytes": total_bytes,
            "aggregate_sha256": aggregate.hexdigest(),
        },
        "sources": used_sources,
        "assets": entries,
    }


def write_manifest() -> None:
    payload = build_manifest()
    MANIFEST_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary = payload["summary"]
    print(
        f"wrote {MANIFEST_PATH}: assets={summary['asset_count']} "
        f"bytes={summary['total_bytes']} sha256={summary['aggregate_sha256']}"
    )


def verify_manifest() -> None:
    expected = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    current = build_manifest()
    if expected != current:
        expected_by_path = {item["path"]: item for item in expected.get("assets", [])}
        current_by_path = {item["path"]: item for item in current.get("assets", [])}
        missing = sorted(set(expected_by_path) - set(current_by_path))
        extra = sorted(set(current_by_path) - set(expected_by_path))
        changed = sorted(
            path
            for path in set(expected_by_path) & set(current_by_path)
            if expected_by_path[path] != current_by_path[path]
        )
        raise SystemExit(
            "asset manifest mismatch: "
            f"missing={missing[:5]} extra={extra[:5]} changed={changed[:5]}"
        )
    summary = current["summary"]
    print(
        f"verified {MANIFEST_PATH}: assets={summary['asset_count']} "
        f"bytes={summary['total_bytes']} sha256={summary['aggregate_sha256']}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write the deterministic manifest")
    mode.add_argument("--verify", action="store_true", help="verify files against the manifest")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.write:
        write_manifest()
    else:
        verify_manifest()


if __name__ == "__main__":
    main()
