from __future__ import annotations

from dataclasses import dataclass

from .base import SceneConfig

BOTTLE_NECK_SCENE_ID = "bottleneck"


@dataclass(frozen=True)
class BottleneckConfig(SceneConfig):
    scene_id: str = BOTTLE_NECK_SCENE_ID
    status: str = "pending"
    corridor_width_m: float = 3.0
    corridor_length_m: float = 24.0
    bottleneck_width_m: float = 0.7
    minutes: int = 8
    entry_count_hour: int = 9000
    demand_minutes: int = 5
    jupedsim_desired_speed_mps: float = 1.35
    gate_service_persons_per_min: int = 35
    pending_reason: str = (
        "Metro's current editable-layout minimum gate width is 4m, so a 0.7m experimental "
        "bottleneck needs a main-runtime geometry adapter before it is scientifically runnable."
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        if min(self.corridor_width_m, self.corridor_length_m, self.bottleneck_width_m) <= 0.0:
            raise ValueError("bottleneck dimensions must be > 0")
        if self.bottleneck_width_m >= self.corridor_width_m:
            raise ValueError("bottleneck_width_m must be smaller than corridor_width_m")


def build_scene_config(bottleneck_width_m: float | None = None) -> BottleneckConfig:
    return BottleneckConfig(
        bottleneck_width_m=0.7 if bottleneck_width_m is None else bottleneck_width_m,
    )
