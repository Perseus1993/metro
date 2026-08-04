from __future__ import annotations

from dataclasses import dataclass

from .base import SceneConfig

CORRIDOR_UNIDIRECTIONAL_SCENE_ID = "corridor_unidirectional"


@dataclass(frozen=True)
class CorridorUnidirectionalConfig(SceneConfig):
    scene_id: str = CORRIDOR_UNIDIRECTIONAL_SCENE_ID
    status: str = "pending"
    corridor_width_m: float = 1.5
    corridor_length_m: float = 25.0
    minutes: int = 6
    entry_count_hour: int = 4500
    demand_minutes: int = 3
    jupedsim_desired_speed_mps: float = 1.30
    pending_reason: str = (
        "Metro's current station layout contract requires >=4m gate banks and generated queues; "
        "a 1.5m controlled corridor cannot be represented faithfully inside alignment only."
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.corridor_width_m <= 0.0 or self.corridor_length_m <= 0.0:
            raise ValueError("corridor dimensions must be > 0")


def build_scene_config(
    width_m: float | None = None,
    length_m: float | None = None,
) -> CorridorUnidirectionalConfig:
    return CorridorUnidirectionalConfig(
        corridor_width_m=1.5 if width_m is None else width_m,
        corridor_length_m=25.0 if length_m is None else length_m,
    )
