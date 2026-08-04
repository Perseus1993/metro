from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw


ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / "assets"
OUTPUT_DIR = ROOT.parents[2] / "output"

FRAME = 48
SCALE = 4
ACTIONS = ("walk", "queue")
DIRECTIONS = ("down", "left", "up", "right")
FRAME_COUNT = 4


PASSENGERS = [
    {
        "id": "commuter_blue_backpack",
        "coat": "#2d5c88",
        "pants": "#263241",
        "hair": "#171717",
        "skin": "#f2b47e",
        "accent": "#5a7188",
        "accessory": "backpack",
    },
    {
        "id": "tan_coat_scarf",
        "coat": "#c8a36d",
        "pants": "#293744",
        "hair": "#4a2a1a",
        "skin": "#efb987",
        "accent": "#8d2f28",
        "accessory": "scarf",
    },
    {
        "id": "business_briefcase",
        "coat": "#20242a",
        "pants": "#15181d",
        "hair": "#111111",
        "skin": "#efb27a",
        "accent": "#384455",
        "accessory": "briefcase",
    },
    {
        "id": "green_parka_beanie",
        "coat": "#497943",
        "pants": "#1d2428",
        "hair": "#362012",
        "skin": "#edb47d",
        "accent": "#ead6ae",
        "accessory": "beanie",
    },
    {
        "id": "cap_crossbag",
        "coat": "#316b9d",
        "pants": "#b79b66",
        "hair": "#2b1b12",
        "skin": "#eab07d",
        "accent": "#1d344f",
        "accessory": "cap",
    },
    {
        "id": "yellow_coat_tote",
        "coat": "#d2a43c",
        "pants": "#243954",
        "hair": "#3a2419",
        "skin": "#eeb480",
        "accent": "#f2e7c7",
        "accessory": "tote",
    },
    {
        "id": "elder_cane",
        "coat": "#806044",
        "pants": "#3a3632",
        "hair": "#cfc8bd",
        "skin": "#e8ad78",
        "accent": "#6c8247",
        "accessory": "cane",
    },
    {
        "id": "hoodie_headphones",
        "coat": "#e9dfcf",
        "pants": "#244258",
        "hair": "#161616",
        "skin": "#ecb07c",
        "accent": "#20252c",
        "accessory": "headphones",
    },
    {
        "id": "trench_skirt_bag",
        "coat": "#c4a173",
        "pants": "#343040",
        "hair": "#4a2a1f",
        "skin": "#efb681",
        "accent": "#5a3420",
        "accessory": "satchel",
    },
    {
        "id": "dark_coat_glasses",
        "coat": "#272b30",
        "pants": "#181c20",
        "hair": "#111111",
        "skin": "#e9aa78",
        "accent": "#73777f",
        "accessory": "glasses",
    },
]


def rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    return (*ImageColor.getrgb(color), alpha)


def darken(color: str, factor: float = 0.62, alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = ImageColor.getrgb(color)
    return (int(r * factor), int(g * factor), int(b * factor), alpha)


class Painter:
    def __init__(self, draw: ImageDraw.ImageDraw) -> None:
        self.draw = draw

    @staticmethod
    def n(value: float) -> int:
        return int(round(value * SCALE))

    def box(self, values: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
        return tuple(self.n(value) for value in values)

    def xy(self, values: list[tuple[float, float]]) -> list[tuple[int, int]]:
        return [(self.n(x), self.n(y)) for x, y in values]

    def ellipse(self, box: tuple[float, float, float, float], **kwargs: object) -> None:
        self.draw.ellipse(self.box(box), **kwargs)

    def rounded_rect(self, box: tuple[float, float, float, float], radius: float, **kwargs: object) -> None:
        self.draw.rounded_rectangle(self.box(box), radius=self.n(radius), **kwargs)

    def line(self, points: list[tuple[float, float]], *, width: float, **kwargs: object) -> None:
        self.draw.line(self.xy(points), width=max(1, self.n(width)), **kwargs)

    def polygon(self, points: list[tuple[float, float]], **kwargs: object) -> None:
        self.draw.polygon(self.xy(points), **kwargs)

    def arc(self, box: tuple[float, float, float, float], start: float, end: float, *, width: float, **kwargs: object) -> None:
        self.draw.arc(self.box(box), start=start, end=end, width=max(1, self.n(width)), **kwargs)


def render_frame(style: dict[str, str], action: str, direction: str, frame_index: int) -> Image.Image:
    image = Image.new("RGBA", (FRAME * SCALE, FRAME * SCALE), (0, 0, 0, 0))
    p = Painter(ImageDraw.Draw(image))

    phase = frame_index / FRAME_COUNT * math.tau
    walking = action == "walk"
    step = math.sin(phase) if walking else math.sin(phase) * 0.22
    counter = math.sin(phase + math.pi) if walking else math.cos(phase) * 0.12
    bob = abs(math.sin(phase)) * 0.75 if walking else math.sin(phase) * 0.16
    side = {"left": -1.0, "right": 1.0}.get(direction, 0.0)
    away = direction == "up"

    coat = style["coat"]
    pants = style["pants"]
    skin = style["skin"]
    accent = style["accent"]
    accessory = style["accessory"]
    outline = (16, 19, 22, 185)

    body_x = 24 + side * 1.3
    head_x = 24 + side * 3.5
    shoulder_y = 20.5 + bob * 0.45
    hip_y = 30 + bob * 0.3

    p.ellipse((12.5, 35, 35.5, 40.7), fill=(0, 0, 0, 48))

    left_foot = (20.5 - side * 0.5 + step * 1.35, 38 - counter * 0.65)
    right_foot = (27.5 - side * 0.5 - step * 1.35, 38 + counter * 0.65)
    if direction in ("left", "right"):
        left_foot = (body_x - side * (1.0 + step * 1.5), 38 - step * 0.45)
        right_foot = (body_x + side * (4.4 - step * 1.0), 36.9 + step * 0.55)

    p.line([(body_x - 3.1, hip_y), left_foot], fill=darken(pants, 0.72), width=3.4)
    p.line([(body_x + 3.1, hip_y), right_foot], fill=rgba(pants), width=3.4)
    p.ellipse((left_foot[0] - 2.8, left_foot[1] - 1.5, left_foot[0] + 2.8, left_foot[1] + 1.9), fill=darken("#f5f3ec", 0.78), outline=outline, width=p.n(0.5))
    p.ellipse((right_foot[0] - 2.8, right_foot[1] - 1.5, right_foot[0] + 2.8, right_foot[1] + 1.9), fill=rgba("#f5f3ec"), outline=outline, width=p.n(0.5))

    arm_left = 2.1 * counter
    arm_right = -2.1 * counter
    if action == "queue":
        arm_left *= 0.28
        arm_right *= 0.28

    if direction in ("left", "right"):
        p.line([(body_x - side * 5.8, shoulder_y + 1.8), (body_x - side * 9.2, 30.6 + arm_left)], fill=darken(coat, 0.82), width=3.1)
        p.line([(body_x + side * 5.0, shoulder_y + 1.6), (body_x + side * 9.6, 29.6 + arm_right)], fill=darken(coat, 0.78), width=3.1)
        p.ellipse((body_x - side * 10.8 - 1.6, 28.7 + arm_left, body_x - side * 10.8 + 1.7, 32.1 + arm_left), fill=rgba(skin), outline=outline, width=p.n(0.45))
        p.ellipse((body_x + side * 9.5 - 1.6, 27.8 + arm_right, body_x + side * 9.5 + 1.7, 31.2 + arm_right), fill=rgba(skin), outline=outline, width=p.n(0.45))
    else:
        p.line([(body_x - 8.2, shoulder_y + 1.5), (body_x - 9.2 - side * 1.2, 30.5 + arm_left)], fill=darken(coat, 0.82), width=3.2)
        p.line([(body_x + 8.2, shoulder_y + 1.5), (body_x + 9.0 - side * 1.0, 30.5 + arm_right)], fill=darken(coat, 0.78), width=3.2)
        p.ellipse((body_x - 11.1 - side * 1.2, 28.5 + arm_left, body_x - 7.8 - side * 1.2, 32 + arm_left), fill=rgba(skin), outline=outline, width=p.n(0.45))
        p.ellipse((body_x + 7.4 - side * 1.0, 28.5 + arm_right, body_x + 10.8 - side * 1.0, 32 + arm_right), fill=rgba(skin), outline=outline, width=p.n(0.45))

    if accessory == "backpack" and away:
        p.rounded_rect((body_x - 8.5, 18.5 + bob, body_x + 8.5, 34.5 + bob), 4.5, fill=darken(accent, 0.86), outline=outline, width=p.n(0.6))

    if direction in ("left", "right"):
        p.rounded_rect((body_x - 6.0, 17.8 + bob, body_x + 6.0, 34.1 + bob), 4.3, fill=rgba(coat), outline=outline, width=p.n(0.7))
        p.line([(body_x - side * 1.7, 18.6 + bob), (body_x - side * 1.7, 33.0 + bob)], fill=darken(coat, 0.72, 170), width=0.9)
    elif accessory == "trench_skirt_bag":
        p.polygon([(body_x - 8.2, 18 + bob), (body_x + 8.2, 18 + bob), (body_x + 10.2, 34.5 + bob), (body_x - 9.4, 34.5 + bob)], fill=rgba(coat), outline=outline)
        p.line([(body_x - 6.3, 21.5 + bob), (body_x + 6.3, 34 + bob)], fill=darken(coat, 0.72), width=1.0)
    else:
        p.rounded_rect((body_x - 8.6, 17.6 + bob, body_x + 8.6, 34.4 + bob), 4.8, fill=rgba(coat), outline=outline, width=p.n(0.7))
        p.line([(body_x, 18.3 + bob), (body_x, 33.4 + bob)], fill=darken(coat, 0.72, 170), width=0.9)

    if direction not in ("left", "right"):
        p.line([(body_x - 5.8, 19 + bob), (body_x - 2.4, 33 + bob)], fill=darken(coat, 0.88, 160), width=0.9)
        p.line([(body_x + 5.8, 19 + bob), (body_x + 2.2, 33 + bob)], fill=darken(coat, 0.82, 150), width=0.9)

    draw_accessory_behind_head(p, style, body_x, head_x, bob, direction)
    draw_head(p, style, head_x, bob, direction)
    draw_front_accessory(p, style, body_x, head_x, bob, action, direction)

    return image.resize((FRAME, FRAME), Image.Resampling.LANCZOS)


def draw_head(p: Painter, style: dict[str, str], head_x: float, bob: float, direction: str) -> None:
    hair = style["hair"]
    skin = style["skin"]
    accessory = style["accessory"]
    outline = (16, 19, 22, 185)
    head_y = 11.1 + bob

    if direction in ("left", "right"):
        p.ellipse((head_x - 5.7, head_y - 2.6, head_x + 5.7, head_y + 11.5), fill=rgba(skin), outline=outline, width=p.n(0.7))
        nose_x = head_x + (1 if direction == "right" else -1) * 5.2
        p.polygon(
            [
                (nose_x, head_y + 4.6),
                (nose_x + (1 if direction == "right" else -1) * 2.8, head_y + 5.7),
                (nose_x, head_y + 6.9),
            ],
            fill=rgba(skin),
        )
    else:
        p.ellipse((head_x - 7.3, head_y - 2.8, head_x + 7.3, head_y + 11.6), fill=rgba(skin), outline=outline, width=p.n(0.7))

    if accessory == "beanie":
        p.rounded_rect((head_x - 7.5, head_y - 5.2, head_x + 7.5, head_y + 2.4), 3.8, fill=rgba(style["accent"]), outline=outline, width=p.n(0.55))
        p.ellipse((head_x - 2.4, head_y - 7.4, head_x + 2.4, head_y - 2.8), fill=rgba(style["accent"]), outline=outline, width=p.n(0.4))
    elif accessory == "cap":
        p.rounded_rect((head_x - 7.7, head_y - 5.1, head_x + 7.7, head_y + 2.4), 3.7, fill=rgba(style["accent"]), outline=outline, width=p.n(0.55))
        if direction != "up":
            p.ellipse((head_x - 4.7, head_y + 0.6, head_x + 6.4, head_y + 5), fill=rgba(style["accent"]), outline=outline, width=p.n(0.4))
    else:
        if direction in ("left", "right"):
            p.ellipse((head_x - 6.6, head_y - 4.8, head_x + 6.2, head_y + 4.2), fill=rgba(hair), outline=outline, width=p.n(0.45))
            front = 1 if direction == "right" else -1
            p.polygon(
                [
                    (head_x + front * 1.0, head_y + 0.4),
                    (head_x + front * 5.6, head_y + 3.4),
                    (head_x + front * 4.0, head_y + 5.6),
                ],
                fill=rgba(hair),
            )
        else:
            p.ellipse((head_x - 7.8, head_y - 4.8, head_x + 7.6, head_y + 4.2), fill=rgba(hair), outline=outline, width=p.n(0.45))
            if direction == "up":
                p.rounded_rect((head_x - 5.7, head_y + 1.0, head_x + 5.7, head_y + 7.4), 2.8, fill=rgba(hair), outline=outline, width=p.n(0.3))
            else:
                p.polygon([(head_x - 6.2, head_y + 1.1), (head_x - 2.8, head_y + 5.4), (head_x + 0.8, head_y + 1.5)], fill=rgba(hair))
                p.polygon([(head_x + 1.2, head_y + 1.0), (head_x + 5.4, head_y + 4.8), (head_x + 6.4, head_y + 0.2)], fill=rgba(hair))

    if direction != "up":
        eye_y = head_y + 4.9
        if direction == "left":
            p.ellipse((head_x - 3.9, eye_y - 0.9, head_x - 2.3, eye_y + 1.0), fill=(18, 18, 18, 245))
        elif direction == "right":
            p.ellipse((head_x + 2.3, eye_y - 0.9, head_x + 3.9, eye_y + 1.0), fill=(18, 18, 18, 245))
        else:
            p.ellipse((head_x - 4.0, eye_y - 0.9, head_x - 2.4, eye_y + 1.0), fill=(18, 18, 18, 245))
            p.ellipse((head_x + 2.4, eye_y - 0.9, head_x + 4.0, eye_y + 1.0), fill=(18, 18, 18, 245))

    if accessory == "glasses" and direction != "up":
        p.ellipse((head_x - 5.4, head_y + 3.3, head_x - 1.6, head_y + 7.0), outline=(24, 26, 28, 230), width=p.n(0.7))
        p.ellipse((head_x + 1.6, head_y + 3.3, head_x + 5.4, head_y + 7.0), outline=(24, 26, 28, 230), width=p.n(0.7))
        p.line([(head_x - 1.6, head_y + 5.2), (head_x + 1.6, head_y + 5.2)], fill=(24, 26, 28, 220), width=0.65)


def draw_accessory_behind_head(
    p: Painter,
    style: dict[str, str],
    body_x: float,
    head_x: float,
    bob: float,
    direction: str,
) -> None:
    accessory = style["accessory"]
    outline = (16, 19, 22, 185)

    if accessory == "headphones":
        p.arc((head_x - 8.6, 4.8 + bob, head_x + 8.6, 18.5 + bob), 200, 340, width=1.2, fill=rgba(style["accent"]))
        p.ellipse((head_x - 9.6, 10.5 + bob, head_x - 6.2, 16.3 + bob), fill=rgba(style["accent"]), outline=outline, width=p.n(0.4))
        p.ellipse((head_x + 6.2, 10.5 + bob, head_x + 9.6, 16.3 + bob), fill=rgba(style["accent"]), outline=outline, width=p.n(0.4))
    if accessory == "backpack" and direction != "up":
        p.line([(body_x - 6, 18.7 + bob), (body_x - 3.2, 31.2 + bob)], fill=rgba(style["accent"], 180), width=1.0)
        p.line([(body_x + 6, 18.7 + bob), (body_x + 3.2, 31.2 + bob)], fill=rgba(style["accent"], 180), width=1.0)


def draw_front_accessory(
    p: Painter,
    style: dict[str, str],
    body_x: float,
    head_x: float,
    bob: float,
    action: str,
    direction: str,
) -> None:
    accessory = style["accessory"]
    accent = style["accent"]
    outline = (16, 19, 22, 185)

    if accessory == "scarf":
        p.rounded_rect((body_x - 7.2, 17.1 + bob, body_x + 7.2, 21.7 + bob), 2.2, fill=rgba(accent), outline=outline, width=p.n(0.45))
        p.line([(body_x + 2.4, 20.3 + bob), (body_x + 6.2, 30.2 + bob)], fill=rgba(accent), width=2.4)
    elif accessory == "briefcase":
        hand_x = body_x + 11.2
        p.rounded_rect((hand_x - 1.5, 28.4 + bob, hand_x + 6.1, 38.2 + bob), 1.6, fill=rgba("#252b31"), outline=outline, width=p.n(0.55))
        p.arc((hand_x, 25.8 + bob, hand_x + 4.8, 31.8 + bob), 180, 360, fill=rgba("#252b31"), width=0.9)
    elif accessory == "tote":
        p.rounded_rect((body_x - 16.4, 28.2 + bob, body_x - 9.0, 39.1 + bob), 2.2, fill=rgba(accent), outline=outline, width=p.n(0.45))
        p.arc((body_x - 15.5, 23.2 + bob, body_x - 9.8, 33.0 + bob), 180, 360, fill=darken(accent, 0.7), width=0.8)
    elif accessory == "cane":
        p.line([(body_x - 11.7, 29.0 + bob), (body_x - 14.2, 42.0 + bob)], fill=rgba("#5a321c"), width=1.25)
        p.arc((body_x - 15.0, 27.2 + bob, body_x - 11.0, 31.5 + bob), 180, 360, fill=rgba("#5a321c"), width=0.7)
    elif accessory in ("satchel", "cap"):
        p.line([(body_x - 5.9, 18.3 + bob), (body_x + 8.3, 34.8 + bob)], fill=rgba(accent), width=1.15)
        p.rounded_rect((body_x + 7.0, 28.2 + bob, body_x + 13.5, 35.8 + bob), 1.7, fill=rgba(accent), outline=outline, width=p.n(0.45))
    elif accessory == "headphones" and action == "queue" and direction != "up":
        p.rounded_rect((body_x - 2.0, 27.4 + bob, body_x + 2.6, 33.5 + bob), 1.0, fill=rgba("#20252c"), outline=outline, width=p.n(0.35))


def build_atlas() -> dict[str, object]:
    columns = len(ACTIONS) * len(DIRECTIONS) * FRAME_COUNT
    rows = len(PASSENGERS)
    atlas = Image.new("RGBA", (columns * FRAME, rows * FRAME), (0, 0, 0, 0))
    frames: dict[str, dict[str, object]] = {}

    for row, style in enumerate(PASSENGERS):
        for action_index, action in enumerate(ACTIONS):
            for direction_index, direction in enumerate(DIRECTIONS):
                for frame_index in range(FRAME_COUNT):
                    column = ((action_index * len(DIRECTIONS) + direction_index) * FRAME_COUNT) + frame_index
                    x = column * FRAME
                    y = row * FRAME
                    atlas.alpha_composite(render_frame(style, action, direction, frame_index), (x, y))
                    key = f"{style['id']}/{action}/{direction}/{frame_index}"
                    frames[key] = {
                        "x": x,
                        "y": y,
                        "w": FRAME,
                        "h": FRAME,
                        "anchor": [24, 37],
                    }

    metadata = {
        "schema_version": "passenger-sprite-atlas/v1",
        "image": "passenger_sprite_atlas.png",
        "frame_size_px": [FRAME, FRAME],
        "actions": list(ACTIONS),
        "directions": list(DIRECTIONS),
        "frame_count": FRAME_COUNT,
        "render_scale": 0.48,
        "types": [{"id": item["id"], "accessory": item["accessory"]} for item in PASSENGERS],
        "frames": frames,
    }

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    atlas.save(ASSET_DIR / "passenger_sprite_atlas.png")
    (ASSET_DIR / "passenger_sprite_atlas.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_preview(atlas)
    return metadata


def write_preview(atlas: Image.Image) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    columns = 8
    rows = len(PASSENGERS)
    preview = Image.new("RGBA", (columns * FRAME, rows * FRAME), (248, 247, 242, 255))
    for row in range(rows):
        source_y = row * FRAME
        # Show walk down/left/up/right, then queue down/left/up/right.
        source_columns = [0, 4, 8, 12, 16, 20, 24, 28]
        for column, source_column in enumerate(source_columns):
            preview.alpha_composite(
                atlas.crop((source_column * FRAME, source_y, (source_column + 1) * FRAME, source_y + FRAME)),
                (column * FRAME, row * FRAME),
            )
    preview.save(OUTPUT_DIR / "passenger_sprite_atlas_preview.png")


def main() -> None:
    metadata = build_atlas()
    print(f"Wrote {len(metadata['frames'])} frames to {ASSET_DIR / 'passenger_sprite_atlas.png'}")
    print(f"Wrote preview to {OUTPUT_DIR / 'passenger_sprite_atlas_preview.png'}")


if __name__ == "__main__":
    main()
