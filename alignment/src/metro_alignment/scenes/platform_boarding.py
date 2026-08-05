from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .base import SceneConfig

PLATFORM_BOARDING_SCENE_ID = "platform_boarding"


@dataclass(frozen=True)
class PlatformBoardingConfig(SceneConfig):
    scene_id: str = PLATFORM_BOARDING_SCENE_ID
    status: str = "ready"
    observed_dataset_id: str = "eindhoven_platform_v1"
    platform_length_m: float = 82.269
    platform_width_m: float = 17.597
    train_door_x_m: float = 18.0
    alighting_source_lateral_offset_m: float = 10.0
    minutes: int = 10
    entry_count_hour: int = 2500
    exit_count_hour: int = 2200
    entry_admission_residence_seconds: float = 36.0
    entry_admission_residence_percentile: str = "p99"
    entry_admission_residence_evidence_ref: str = (
        "alignment/output/round25/T1_residence_time.json#entry.p99"
    )
    exit_admission_residence_seconds: float = 351.0
    exit_admission_residence_percentile: str = "p90"
    exit_admission_residence_evidence_ref: str = (
        "alignment/output/round25/T1_residence_time.json#exit.p90"
    )
    entry_entrance_weights: tuple[tuple[str, float], ...] = (
        ("entrance_a", 1.0),
        ("exit_a", 0.0),
    )
    demand_minutes: int = 10
    jupedsim_desired_speed_mps: float = 1.22
    measurement_bounds_m: tuple[float, float, float, float] = (
        4.0,
        10.0,
        86.269,
        27.597,
    )
    measurement_area_id: str = "eindhoven_platform_bbox_translation_v1"
    comparison_frame_id: str = "eindhoven_platform_shared_v1"
    coordinate_transform_id: str = "metro_station_identity_v1"
    coordinate_translation_m: tuple[float, float] = (0.0, 0.0)
    geometry_evidence_status: str = "proxy"
    geometry_evidence: str = (
        "Eindhoven days 01-10 trajectory bounding-box dimensions only; "
        "internal obstacles, access points, and train-door positions are not observed-matched"
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.platform_length_m < 20.0 or self.platform_width_m < 10.0:
            raise ValueError("platform dimensions are too small for Metro's gate/queue contracts")
        if not 1.0 <= self.train_door_x_m <= self.platform_length_m - 12.0:
            raise ValueError("train_door_x_m must leave room for the boarding edge")
        if (
            not isfinite(float(self.alighting_source_lateral_offset_m))
            or self.alighting_source_lateral_offset_m < 0.0
        ):
            raise ValueError("alighting_source_lateral_offset_m must be finite and non-negative")
        expected = (4.0, 10.0, 4.0 + self.platform_length_m, 10.0 + self.platform_width_m)
        if any(
            abs(actual - wanted) > 1e-9
            for actual, wanted in zip(self.measurement_bounds_m, expected, strict=True)
        ):
            raise ValueError("measurement_bounds_m must match the compiled platform footprint")


def build_scene_config(
    platform_length_m: float | None = None,
    platform_width_m: float | None = None,
) -> PlatformBoardingConfig:
    length = 82.269 if platform_length_m is None else platform_length_m
    width = 17.597 if platform_width_m is None else platform_width_m
    return PlatformBoardingConfig(
        platform_length_m=length,
        platform_width_m=width,
        measurement_bounds_m=(4.0, 10.0, 4.0 + length, 10.0 + width),
    )
