from __future__ import annotations

from math import isfinite

from .schema import StationDesignDocument
from .validation_issue import ValidationIssue, issue


def validate_geometry(
    geometry,
    path: str,
    document: StationDesignDocument,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isfinite(float(geometry.rotation_deg)):
        issues.append(
            issue(
                "error",
                "numbers.non_finite",
                f"{path}.rotation_deg",
                "geometry rotation must be finite",
            )
        )
    if geometry.shape in {"rect", "point"}:
        if geometry.shape == "rect" and (geometry.width_m <= 0 or geometry.height_m <= 0):
            issues.append(
                issue(
                    "error",
                    "geometry.invalid_size",
                    path,
                    "rect geometry must have positive width and height",
                )
            )
        issues.extend(
            validate_points(
                (
                    (geometry.x_m, geometry.y_m),
                    (geometry.x_m + geometry.width_m, geometry.y_m + geometry.height_m),
                ),
                path,
                document,
            )
        )
    elif geometry.shape in {"polygon", "polyline"}:
        min_points = 3 if geometry.shape == "polygon" else 2
        if len(geometry.points_m) < min_points:
            issues.append(
                issue(
                    "error",
                    "geometry.too_few_points",
                    path,
                    f"{geometry.shape} needs at least {min_points} points",
                )
            )
        issues.extend(validate_points(geometry.points_m, path, document))
    else:
        issues.append(
            issue(
                "error",
                "geometry.unknown_shape",
                path,
                f"unknown geometry shape {geometry.shape!r}",
            )
        )
    return issues


def validate_points(
    points: tuple[tuple[float, float], ...],
    path: str,
    document: StationDesignDocument,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    constraints = document.constraints
    for index, (x_m, y_m) in enumerate(points):
        if not isfinite(x_m) or not isfinite(y_m):
            issues.append(
                issue(
                    "error",
                    "geometry.non_finite",
                    f"{path}[{index}]",
                    "geometry coordinates must be finite numbers",
                )
            )
            continue
        if (
            x_m < 0
            or x_m > constraints.canvas_width_m
            or y_m < 0
            or y_m > constraints.canvas_height_m
        ):
            issues.append(
                issue(
                    "error",
                    "geometry.out_of_bounds",
                    f"{path}[{index}]",
                    f"point ({x_m}, {y_m}) is outside {constraints.canvas_width_m}m x {constraints.canvas_height_m}m canvas",
                )
            )
    return issues
