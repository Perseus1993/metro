from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Literal
from urllib.parse import urlparse

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
PORTABLE_DATASET_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}\Z")
WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"/\\|?*')


def is_portable_basename(name: object) -> bool:
    if (
        not isinstance(name, str)
        or not name
        or name != name.strip()
        or name in {".", ".."}
        or name.endswith((".", " "))
        or len(name.encode("utf-16-le")) // 2 > 255
        or any(ord(character) < 32 for character in name)
        or any(character in WINDOWS_INVALID_FILENAME_CHARS for character in name)
    ):
        return False
    base_name = name.split("/")[-1].split("\\")[-1]
    device_stem = base_name.rstrip(" .").split(".", 1)[0].upper()
    return name == base_name and device_stem not in WINDOWS_RESERVED_NAMES


@dataclass(frozen=True)
class FileSpec:
    name: str
    url: str
    md5: str
    size_bytes: int

    def __post_init__(self) -> None:
        if not is_portable_basename(self.name):
            raise ValueError("file name must be a non-empty basename")
        parsed = urlparse(self.url)
        try:
            port_is_valid = parsed.port is None or 0 < parsed.port <= 65535
        except ValueError:
            port_is_valid = False
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or not port_is_valid:
            raise ValueError(f"{self.name}: url must use HTTP(S)")
        if re.fullmatch(r"[0-9a-fA-F]{32}", self.md5) is None:
            raise ValueError(f"{self.name}: md5 must contain exactly 32 hex digits")
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes <= 0
        ):
            raise ValueError(f"{self.name}: size_bytes must be > 0")


@dataclass(frozen=True)
class ObservedAnalysisSpec:
    measurement_bounds_m: tuple[float, float, float, float]
    measurement_area_id: str
    comparison_frame_id: str
    coordinate_transform_id: str
    coordinate_translation_m: tuple[float, float]
    max_rows: int
    window_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.measurement_bounds_m, tuple) or len(self.measurement_bounds_m) != 4:
            raise ValueError("observed measurement bounds must contain four values")
        min_x, min_y, max_x, max_y = self.measurement_bounds_m
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in self.measurement_bounds_m
        ):
            raise ValueError("observed measurement bounds must be finite")
        if max_x <= min_x or max_y <= min_y:
            raise ValueError("observed measurement bounds must have positive area")
        if (
            not isinstance(self.coordinate_translation_m, tuple)
            or len(self.coordinate_translation_m) != 2
            or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in self.coordinate_translation_m
            )
        ):
            raise ValueError("observed coordinate translation must be finite")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.measurement_area_id,
                self.comparison_frame_id,
                self.coordinate_transform_id,
            )
        ):
            raise ValueError("observed analysis IDs must be non-empty")
        if (
            not isinstance(self.max_rows, int)
            or isinstance(self.max_rows, bool)
            or self.max_rows <= 0
            or not isinstance(self.window_count, int)
            or isinstance(self.window_count, bool)
            or self.window_count <= 0
        ):
            raise ValueError("observed sampling limits must be positive")


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    title: str
    source_url: str
    license: str
    citation: str
    files: tuple[FileSpec, ...]
    raw_loader_ref: str
    to_canonical_ref: str
    agent_id_offset: int
    coordinate_unit: str
    frame_rate_hz: float
    notes: str
    observed_analysis: ObservedAnalysisSpec | None
    status: Literal["active", "pending"] = "active"

    def __post_init__(self) -> None:
        if self.status not in {"active", "pending"}:
            raise ValueError("dataset status must be active or pending")
        if (
            not isinstance(self.dataset_id, str)
            or PORTABLE_DATASET_ID.fullmatch(self.dataset_id) is None
            or not is_portable_basename(self.dataset_id)
        ):
            raise ValueError("dataset_id must be a lowercase portable slug")
        if not isinstance(self.license, str) or not self.license.strip():
            raise ValueError(f"{self.dataset_id}: license 不能为空")
        if not isinstance(self.citation, str) or not self.citation.strip():
            raise ValueError(f"{self.dataset_id}: citation 不能为空")
        if self.coordinate_unit not in {"mm", "m"}:
            raise ValueError(f"{self.dataset_id}: 坐标单位必须是 mm 或 m")
        if not isinstance(self.raw_loader_ref, str) or not self.raw_loader_ref.strip():
            raise ValueError(f"{self.dataset_id}: raw_loader_ref 不能为空")
        if not isinstance(self.to_canonical_ref, str) or not self.to_canonical_ref.strip():
            raise ValueError(f"{self.dataset_id}: to_canonical_ref 不能为空")
        if (
            not isinstance(self.agent_id_offset, int)
            or isinstance(self.agent_id_offset, bool)
            or self.agent_id_offset < 0
        ):
            raise ValueError(f"{self.dataset_id}: agent_id_offset 不能为负")
        if (
            not isinstance(self.frame_rate_hz, (int, float))
            or isinstance(self.frame_rate_hz, bool)
            or not math.isfinite(self.frame_rate_hz)
            or self.frame_rate_hz <= 0.0
        ):
            raise ValueError(f"{self.dataset_id}: frame_rate_hz 必须是有限正数")
        if not isinstance(self.files, tuple) or any(
            not isinstance(file_spec, FileSpec) for file_spec in self.files
        ):
            raise ValueError(f"{self.dataset_id}: files must be a tuple of FileSpec")
        if self.observed_analysis is not None and not isinstance(
            self.observed_analysis, ObservedAnalysisSpec
        ):
            raise ValueError(f"{self.dataset_id}: observed_analysis has an invalid type")
        if self.status == "active" and not self.files:
            raise ValueError(f"{self.dataset_id}: active dataset requires files")
        if self.status == "active" and self.observed_analysis is None:
            raise ValueError(f"{self.dataset_id}: active dataset requires observed analysis config")


def _eindhoven_files() -> tuple[FileSpec, ...]:
    # 先填入可验证的第一批文件；更多文件按同模板补齐。
    return (
        FileSpec(
            name="Eindhoven_centraal_platform_3_4.png",
            url="https://zenodo.org/records/13784588/files/Eindhoven_centraal_platform_3_4.png?download=1",
            md5="6978659b7af6e0f813e43f5aef2c2e51",
            size_bytes=467418,
        ),
        FileSpec(
            name="Eindhoven_centraal_trajectories_days_01_10.parquet",
            url="https://zenodo.org/records/13784588/files/Eindhoven_centraal_trajectories_days_01_10.parquet?download=1",
            md5="34f1b0c41d93184f0ae30a45246f82dc",
            size_bytes=862133833,
        ),
    )


_REGISTRY: dict[str, DatasetSpec] = {
    "eindhoven_platform_v1": DatasetSpec(
        dataset_id="eindhoven_platform_v1",
        title="Eindhoven train station platform 3-4",
        source_url="https://zenodo.org/records/13784588",
        license="CC-BY-4.0",
        citation=(
            "Pouw, C.A.S., van der Vleuten, G.G.M., Corbetta, A., & Toschi, F. "
            "(2024). Data-driven physics-based modeling of pedestrian dynamics - dataset: "
            "Pedestrian trajectories at Eindhoven train station. Zenodo. "
            "https://doi.org/10.5281/zenodo.13784588"
        ),
        files=_eindhoven_files(),
        raw_loader_ref="metro_alignment.datasets.eindhoven:load_all_from_dir",
        to_canonical_ref="metro_alignment.datasets.eindhoven:to_canonical",
        agent_id_offset=10_000_000,
        coordinate_unit="mm",
        frame_rate_hz=10.0,
        notes="站台轨迹数据，先用前 10 天文件验证流程。",
        observed_analysis=ObservedAnalysisSpec(
            measurement_bounds_m=(-6.679, -9.861, 75.59, 7.736),
            measurement_area_id="eindhoven_platform_bbox_translation_v1",
            comparison_frame_id="eindhoven_platform_shared_v1",
            coordinate_transform_id="eindhoven_raw_translation_v1",
            coordinate_translation_m=(10.679, 19.861),
            max_rows=200_000,
            window_count=5,
        ),
    ),
    "julich_corridor_stub": DatasetSpec(
        dataset_id="julich_corridor_stub",
        title="Jülich corridor experiments (stub)",
        source_url="https://ped.fz-juelich.de/database",
        license="研究使用请注明数据来源",
        citation="Pedestrian Dynamics Data Archive, Forschungszentrum Jülich, IAS-7. https://doi.org/10.34735/ped.da",
        files=(),
        raw_loader_ref="metro_alignment.datasets.julich:load_julich",
        to_canonical_ref="metro_alignment.datasets.julich:to_canonical",
        agent_id_offset=20_000_000,
        coordinate_unit="m",
        frame_rate_hz=25.0,
        notes="占位条目，用于本地开发与接口预演，正式实验数据需补全文件列表。",
        observed_analysis=None,
        status="pending",
    ),
    "atc_osaka_stub": DatasetSpec(
        dataset_id="atc_osaka_stub",
        title="ATC Osaka dataset (stub)",
        source_url="https://dil.atr.jp/crest2010_HRI/ATC_dataset/",
        license="研究用途",
        citation=(
            "D. Brščić, T. Kanda, T. Ikeda, T. Miyashita. "
            '"Person position and body direction tracking in large public spaces using 3D range sensors." '
            "IEEE Transactions on Human-Machine Systems, 43(6), 522-534, 2013."
        ),
        files=(),
        raw_loader_ref="metro_alignment.datasets.atc:load_atc",
        to_canonical_ref="metro_alignment.datasets.atc:to_canonical",
        agent_id_offset=30_000_000,
        coordinate_unit="mm",
        frame_rate_hz=5.0,
        notes="占位条目，下载与字段定义需待确认。",
        observed_analysis=None,
        status="pending",
    ),
}


def _validated_registry_values() -> tuple[DatasetSpec, ...]:
    values = tuple(_REGISTRY.values())
    ids = [spec.dataset_id for spec in values]
    mismatches = [key for key, spec in _REGISTRY.items() if key != spec.dataset_id]
    if mismatches:
        raise ValueError(f"dataset registry keys must match dataset_id: {mismatches}")
    duplicates = sorted({dataset_id for dataset_id in ids if ids.count(dataset_id) > 1})
    if duplicates:
        raise ValueError(f"dataset registry contains duplicate dataset_id values: {duplicates}")
    return values


def list_dataset_specs() -> tuple[DatasetSpec, ...]:
    return _validated_registry_values()


def get_dataset_spec(dataset_id: str) -> DatasetSpec:
    _validated_registry_values()
    try:
        return _REGISTRY[dataset_id]
    except KeyError as exc:
        raise KeyError(f"未找到数据集: {dataset_id}") from exc


def by_file_name(file_name: str) -> tuple[str, DatasetSpec] | tuple[None, None]:
    for spec in _validated_registry_values():
        if any(f.name == file_name for f in spec.files):
            return spec.dataset_id, spec
    return None, None


def get_unit_scale_to_meters(dataset_spec: DatasetSpec) -> float:
    return 0.001 if dataset_spec.coordinate_unit == "mm" else 1.0


def as_mapping() -> Mapping[str, DatasetSpec]:
    _validated_registry_values()
    return dict(_REGISTRY)


def resolve_reference(ref: str):
    module_name, symbol = ref.split(":", 1)
    module = import_module(module_name)
    return getattr(module, symbol)


def main() -> None:
    payload = {
        "datasets": [
            {
                "dataset_id": spec.dataset_id,
                "title": spec.title,
                "source_url": spec.source_url,
                "license": spec.license,
                "citation": spec.citation,
                "frame_rate_hz": spec.frame_rate_hz,
                "coordinate_unit": spec.coordinate_unit,
                "notes": spec.notes,
                "status": spec.status,
                "files": [{"name": file.name, "url": file.url} for file in spec.files],
            }
            for spec in list_dataset_specs()
        ],
    }
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
