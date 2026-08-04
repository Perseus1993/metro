from __future__ import annotations

from shapely.geometry import box

from metro_station.adapters.simulation.design.geometry import element_shape
from metro_station.adapters.simulation.design.schema import (
    DesignElement,
    ElementGeometry,
    StationDesignDocument,
)

from .layout_recipe import LayoutRecipe


def generated_assets(
    document: StationDesignDocument,
    recipe: LayoutRecipe,
    *,
    occupied: tuple[DesignElement, ...] = (),
) -> tuple[DesignElement, ...]:
    if recipe.asset_density == "sparse":
        return ()
    min_x, min_y, max_x, max_y = top_footprint_bounds(document)
    top_level = min(document.levels, key=lambda level: level.order).id
    occupied_shapes = []
    for element in occupied:
        if element.level_id != top_level or element.role == "floor":
            continue
        shape = element_shape(element.geometry)
        occupied_shapes.append(shape)
        if element.kind in {"gate", "escalator", "stairs", "elevator", "platform_edge"}:
            # Reserve the service apron as well as the component body.  Queue
            # generation happens after asset generation, so without this
            # reservation a visually clear shop could occupy the only legal
            # directional facade of a gate.
            occupied_shapes.append(shape.buffer(8.0, cap_style="square"))
    shop_geometry = _place_generated_asset(
        bounds=(min_x, min_y, max_x, max_y),
        width=18.0,
        height=8.0,
        occupied=occupied_shapes,
    )
    assets = [
        DesignElement(
            "shop_generated",
            "shop",
            top_level,
            shop_geometry,
            "Generated retail block",
        )
    ]
    occupied_shapes.append(element_shape(shop_geometry))
    if recipe.asset_density == "dense":
        equipment_geometry = _place_generated_asset(
            bounds=(min_x, min_y, max_x, max_y),
            width=14.0,
            height=4.0,
            occupied=occupied_shapes,
        )
        assets.append(
            DesignElement(
                "equipment_generated",
                "equipment",
                top_level,
                equipment_geometry,
                "Generated equipment bank",
            )
        )
    return tuple(assets)


def _place_generated_asset(
    *,
    bounds: tuple[float, float, float, float],
    width: float,
    height: float,
    occupied: list[object],
) -> ElementGeometry:
    min_x, min_y, max_x, max_y = bounds
    x_span = max(0.0, max_x - min_x - width - 4.0)
    y_span = max(0.0, max_y - min_y - height - 4.0)
    candidates: list[tuple[float, float, float]] = []
    for y_fraction in (0.0, 1.0, 0.5, 0.25, 0.75):
        for x_fraction in (1.0, 0.0, 0.75, 0.25, 0.5):
            x_m = min_x + 2.0 + x_span * x_fraction
            y_m = min_y + 2.0 + y_span * y_fraction
            shape = box(x_m, y_m, x_m + width, y_m + height)
            collision = sum(
                shape.buffer(0.5).intersection(other).area for other in occupied
            )
            candidates.append((collision, x_m, y_m))
    _collision, x_m, y_m = min(candidates)
    return ElementGeometry(
        "rect",
        x_m=x_m,
        y_m=y_m,
        width_m=width,
        height_m=height,
    )


def top_footprint_bounds(
    document: StationDesignDocument,
) -> tuple[float, float, float, float]:
    level = min(document.levels, key=lambda item: item.order)
    xs = [point[0] for point in level.footprint]
    ys = [point[1] for point in level.footprint]
    return min(xs), min(ys), max(xs), max(ys)
