from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class NormalizedBox:
    x: float
    y: float
    w: float
    h: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)

    def to_pixels(self, width: float, height: float) -> dict[str, float]:
        return {
            "x": self.x * width,
            "y": self.y * height,
            "w": self.w * width,
            "h": self.h * height,
        }

    def corners(self) -> list[list[float]]:
        return [
            [self.x, self.y],
            [self.x + self.w, self.y],
            [self.x + self.w, self.y + self.h],
            [self.x, self.y + self.h],
        ]


@dataclass(frozen=True)
class ElevatorLayout:
    box: NormalizedBox
    top_door: tuple[float, float]
    bottom_door: tuple[float, float]
    top_queue_origin: tuple[float, float]
    top_queue_step: tuple[float, float]
    bottom_queue_origin: tuple[float, float]
    bottom_queue_step: tuple[float, float]
    bottom_exit_origin: tuple[float, float]
    bottom_exit_step: tuple[float, float]
    bottom_approach_origin: tuple[float, float]
    bottom_approach_step: tuple[float, float]
    platform_end_origin: tuple[float, float]
    platform_end_step: tuple[float, float]
    top_exit_origin: tuple[float, float]
    top_exit_step: tuple[float, float]
    concourse_exit_origin: tuple[float, float]
    concourse_exit_step: tuple[float, float]
    cabin_padding_px: float = 7.0
    cabin_height_share: float = 0.38


ELEVATOR = ElevatorLayout(
    box=NormalizedBox(x=0.616, y=0.405, w=0.069, h=0.228),
    top_door=(0.650, 0.405),
    bottom_door=(0.650, 0.628),
    top_queue_origin=(0.612, 0.383),
    top_queue_step=(0.008, 0.012),
    bottom_queue_origin=(0.620, 0.650),
    bottom_queue_step=(0.010, 0.012),
    bottom_exit_origin=(0.625, 0.654),
    bottom_exit_step=(-0.012, 0.012),
    bottom_approach_origin=(0.500, 0.718),
    bottom_approach_step=(0.040, 0.009),
    platform_end_origin=(0.490, 0.716),
    platform_end_step=(0.045, 0.009),
    top_exit_origin=(0.612, 0.382),
    top_exit_step=(0.013, 0.010),
    concourse_exit_origin=(0.684, 0.335),
    concourse_exit_step=(0.030, 0.010),
)

ELEVATOR_BOX_N = ELEVATOR.box.as_dict()


def point_to_pixels(point: tuple[float, float], width: float, height: float) -> list[float]:
    return [point[0] * width, point[1] * height]


def elevator_payload(width: float, height: float) -> dict[str, object]:
    return {
        "box_n": ELEVATOR.box.as_dict(),
        "box_px": ELEVATOR.box.to_pixels(width, height),
        "top_door_px": point_to_pixels(ELEVATOR.top_door, width, height),
        "bottom_door_px": point_to_pixels(ELEVATOR.bottom_door, width, height),
        "cabin_padding_px": ELEVATOR.cabin_padding_px,
        "cabin_height_share": ELEVATOR.cabin_height_share,
    }
