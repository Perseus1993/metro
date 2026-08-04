"""
公用地理计算函数。
- 距离计算（Equirectangular approximation）
- 缓冲区多边形生成
"""

import math


def meters_between(point_a, point_b):
    """两点间近似距离（米）。point = (lat, lon)。"""
    lat1 = math.radians(point_a[0])
    lon1 = math.radians(point_a[1])
    lat2 = math.radians(point_b[0])
    lon2 = math.radians(point_b[1])
    x = (lon2 - lon1) * math.cos((lat1 + lat2) / 2)
    y = lat2 - lat1
    return math.sqrt(x * x + y * y) * 6371000


def distance_weight(distance_m, scale_m):
    """指数距离衰减权重。"""
    if scale_m <= 0:
        return 1.0
    return math.exp(-float(distance_m) / float(scale_m))


def build_circle_polygon(center_lat, center_lon, radius_m, point_count=16):
    """
    围绕 (center_lat, center_lon) 生成近似圆形多边形。
    返回 [[lon, lat], ...] 列表（GeoJSON 顺序）。
    坐标系与输入一致（通常为 GCJ-02）。
    """
    coords = []
    for index in range(point_count):
        angle = 2 * math.pi * index / point_count
        lat_offset = (radius_m * math.cos(angle)) / 111320.0
        lon_offset = (radius_m * math.sin(angle)) / (111320.0 * math.cos(math.radians(center_lat)))
        # 注意: GeoJSON 顺序为 [lon, lat]
        coords.append([center_lon + lon_offset, center_lat + lat_offset])
    return coords


def polygon_param(coords):
    """将多边形坐标列表格式化为高德 API 的 polygon 参数字符串。"""
    return "|".join(f"{lon:.6f},{lat:.6f}" for lon, lat in coords)


def dedupe_points(points, tolerance_m=2.0):
    """去除连续重复坐标点。points = [[lat, lon], ...]。"""
    merged = []
    for point in points:
        if not merged or meters_between(point, merged[-1]) > tolerance_m:
            merged.append(point)
    return merged
