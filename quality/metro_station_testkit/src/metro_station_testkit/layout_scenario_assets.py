from __future__ import annotations

from metro_station.adapters.simulation.design.schema import (
    DesignElement,
    ElementGeometry,
    StationDesignDocument,
)

from .layout_recipe import LayoutRecipe


def generated_assets(
    document: StationDesignDocument,
    recipe: LayoutRecipe,
) -> tuple[DesignElement, ...]:
    if recipe.asset_density == "sparse":
        return ()
    _, min_y, max_x, _ = top_footprint_bounds(document)
    top_level = min(document.levels, key=lambda level: level.order).id
    assets = [
        DesignElement(
            "shop_generated",
            "shop",
            top_level,
            ElementGeometry(
                "rect",
                x_m=max_x - 22.0,
                y_m=min_y + 2.0,
                width_m=18.0,
                height_m=8.0,
            ),
            "Generated retail block",
        )
    ]
    if recipe.asset_density == "dense":
        assets.append(
            DesignElement(
                "equipment_generated",
                "equipment",
                top_level,
                ElementGeometry(
                    "rect",
                    x_m=max_x - 18.0,
                    y_m=min_y + 13.0,
                    width_m=14.0,
                    height_m=4.0,
                ),
                "Generated equipment bank",
            )
        )
    return tuple(assets)


def top_footprint_bounds(
    document: StationDesignDocument,
) -> tuple[float, float, float, float]:
    level = min(document.levels, key=lambda item: item.order)
    xs = [point[0] for point in level.footprint]
    ys = [point[1] for point in level.footprint]
    return min(xs), min(ys), max(xs), max(ys)
