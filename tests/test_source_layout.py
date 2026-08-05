from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_SOURCE = ROOT / "packages" / "metro_station" / "src" / "metro_station"
LEGACY_SOURCE = ROOT / "sandbox" / "metro_station_sandbox"
WORKSPACE_MEMBERS = {
    "apps/station_designer",
    "apps/station_visualizer",
    "experiments/metro_station_experiments",
    "packages/metro_station",
    "quality/metro_station_acceptance",
    "quality/metro_station_testkit",
}
OFFICIAL_SOURCE_SIZE_RATCHET = {
    "adapters/simulation/agents/passenger.py": 912,
    "adapters/simulation/compilation/spatial_capacity.py": 1674,
    "adapters/simulation/facilities/elevator_cabin_runtime.py": 979,
    "adapters/simulation/facilities/elevator_runtime.py": 927,
    "adapters/simulation/facilities/facility_queue.py": 805,
    "adapters/simulation/facilities/runtime_base.py": 970,
    "adapters/simulation/movement/backend.py": 1314,
    "adapters/simulation/movement/jps_adapter.py": 960,
    "adapters/simulation/runtime/decision_holding.py": 731,
    "adapters/simulation/runtime/passenger_demand.py": 765,
    "adapters/simulation/runtime/passenger_goal_region_router.py": 823,
    "adapters/simulation/simulation_outputs/visual_tracks.py": 824,
    "adapters/simulation/station/layout_facilities.py": 702,
}
NONPRODUCTION_SOURCE_SIZE_RATCHET = {
    "experiments/torch_movement_p1/metro_torch_p1/calibration.py": 1929,
    "quality/metro_station_testkit/src/metro_station_testkit/compilation_negative_cases.py": 2434,
}


def _physical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _is_generated_workspace_cache(path: Path) -> bool:
    return any(
        part
        in {
            ".venv",
            "Library",
            "PackageCache",
            "Temp",
            "obj",
            "venv",
            "__pycache__",
        }
        for part in path.parts
    )


def test_root_distribution_only_packages_the_data_warehouse_library() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_finder = configuration["tool"]["setuptools"]["packages"]["find"]
    assert package_finder["where"] == ["src"]
    assert package_finder["include"] == ["metro_data_warehouse", "metro_data_warehouse.*"]
    assert set(configuration["tool"]["uv"]["workspace"]["members"]) == WORKSPACE_MEMBERS


def test_official_distribution_has_no_legacy_dependency() -> None:
    configuration = tomllib.loads(
        (ROOT / "packages" / "metro_station" / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = configuration["project"]["dependencies"]
    assert all("sandbox" not in dependency.lower() for dependency in dependencies)

    offenders = []
    for path in OFFICIAL_SOURCE.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "sandbox.metro_station_sandbox" in source:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_legacy_namespace_contains_only_small_compatibility_modules() -> None:
    offenders = []
    for path in LEGACY_SOURCE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        if "Compatibility" not in source[:200] or _physical_lines(path) > 80:
            offenders.append((path.relative_to(ROOT).as_posix(), _physical_lines(path)))
    assert offenders == []


def test_official_source_file_size_budget() -> None:
    offenders = []
    for path in OFFICIAL_SOURCE.rglob("*.py"):
        relative = path.relative_to(OFFICIAL_SOURCE).as_posix()
        line_count = _physical_lines(path)
        limit = OFFICIAL_SOURCE_SIZE_RATCHET.get(relative, 700)
        if line_count > limit:
            offenders.append((path.relative_to(ROOT).as_posix(), line_count, limit))
    assert offenders == []


def test_nonproduction_package_file_size_ratchet() -> None:
    roots = (
        ROOT / "apps",
        ROOT / "experiments",
        ROOT / "quality",
        ROOT / "src" / "metro_data_warehouse",
    )
    offenders = []
    for package_root in roots:
        for path in package_root.rglob("*.py"):
            if _is_generated_workspace_cache(path):
                continue
            relative = path.relative_to(ROOT).as_posix()
            line_count = _physical_lines(path)
            limit = NONPRODUCTION_SOURCE_SIZE_RATCHET.get(relative, 1100)
            if line_count > limit:
                offenders.append((relative, line_count, limit))
    assert offenders == []
