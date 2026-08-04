from __future__ import annotations

from PIL import Image, ImageDraw

try:  # Support both package execution and direct script execution.
    from .config import H, OUTPUT_DIR, PX_PER_METER, W
    from .geometry import load_station_geometry
    from .layout import STATION_LAYOUT
except ImportError:  # pragma: no cover
    from config import H, OUTPUT_DIR, PX_PER_METER, W
    from geometry import load_station_geometry
    from layout import STATION_LAYOUT


OUTPUT_IMAGE = OUTPUT_DIR / "metro_station_geometry_preview.png"


def to_canvas(point: tuple[float, float]) -> tuple[float, float]:
    return point[0] * PX_PER_METER, point[1] * PX_PER_METER


def norm_to_canvas(point: tuple[float, float], width: int, height: int) -> tuple[float, float]:
    return float(point[0]) * width, float(point[1]) * height


def draw_geometry(
    draw: ImageDraw.ImageDraw,
    geometry,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int],
) -> None:
    geoms = geometry.geoms if hasattr(geometry, "geoms") else [geometry]
    for geom in geoms:
        if geom.geom_type == "MultiPolygon":
            draw_geometry(draw, geom, fill, outline)
            continue
        if geom.geom_type != "Polygon":
            continue
        exterior = [to_canvas((float(x), float(y))) for x, y in geom.exterior.coords]
        draw.polygon(exterior, fill=fill)
        draw.line(exterior, fill=outline, width=3, joint="curve")
        for interior in geom.interiors:
            hole = [to_canvas((float(x), float(y))) for x, y in interior.coords]
            draw.polygon(hole, fill=(255, 80, 80, 90))
            draw.line(hole, fill=(255, 80, 80, 190), width=2, joint="curve")


def main() -> None:
    result = Image.new("RGBA", (int(W), int(H)), (8, 22, 31, 255))
    draw = ImageDraw.Draw(result, "RGBA")

    track_fill = (22, 28, 31, 255)
    for facility in STATION_LAYOUT.facility_boxes:
        if facility.kind != "track":
            continue
        points = [norm_to_canvas(point, int(W), int(H)) for point in facility.points]
        draw.polygon(points, fill=track_fill)

    for region in STATION_LAYOUT.walkable_regions:
        points = [norm_to_canvas(point, int(W), int(H)) for point in region.points]
        fill = (205, 218, 214, 245) if region.id.startswith("b1") else (194, 213, 204, 245)
        outline = (95, 121, 123, 255)
        draw.polygon(points, fill=fill)
        draw.line(points + [points[0]], fill=outline, width=3, joint="curve")

    geometry = load_station_geometry()
    draw_geometry(draw, geometry, fill=(66, 180, 112, 68), outline=(50, 220, 120, 210))

    for obstacle in STATION_LAYOUT.obstacles:
        points = [norm_to_canvas(point, int(W), int(H)) for point in obstacle.points]
        if obstacle.blocking:
            fill = (255, 90, 80, 88)
            outline = (255, 90, 80, 220)
        else:
            fill = (255, 190, 80, 44)
            outline = (255, 190, 80, 170)
        draw.polygon(points, fill=fill)
        draw.line(points + [points[0]], fill=outline, width=2)

    for channel in STATION_LAYOUT.connector_channels:
        points = [norm_to_canvas(point, int(W), int(H)) for point in channel.line]
        width = max(3, round(channel.width_px * 0.18))
        fill = (255, 213, 102, 225)
        if channel.kind == "escalator":
            fill = (74, 143, 255, 225) if channel.direction == "down" else (255, 138, 39, 225)
        elif channel.kind == "stairs":
            fill = (213, 226, 230, 225)
        elif channel.kind.startswith("elevator"):
            fill = (255, 209, 102, 225)
        draw.line(points, fill=fill, width=width)

    for facility in STATION_LAYOUT.facility_boxes:
        if facility.kind == "track":
            continue
        points = [norm_to_canvas(point, int(W), int(H)) for point in facility.points]
        draw.polygon(points, fill=(124, 104, 238, 38))
        draw.line(points + [points[0]], fill=(124, 104, 238, 230), width=3)

    OUTPUT_IMAGE.parent.mkdir(parents=True, exist_ok=True)
    result.save(OUTPUT_IMAGE)
    print(f"[GEOMETRY PREVIEW] output={OUTPUT_IMAGE}")


if __name__ == "__main__":
    main()
