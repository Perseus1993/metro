"""
高德地铁网络数据获取与线路几何拼接。

数据流：
  高德地铁图 JSON → 站点列表 + 线路列表 → 路径规划 polyline → 完整线路几何
"""

import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from src.geo_utils import dedupe_points, meters_between

# ---------------------------------------------------------------------------
# 路径常量（相对于项目根目录）
# ---------------------------------------------------------------------------
SUBWAY_DATA_URL = "https://map.amap.com/service/subway?srhdata=6101_drw_xian.json"
RAW_CACHE_PATH = Path("cache/amap_subway_raw.json")
SEGMENT_CACHE_PATH = Path("cache/amap_subway_segment_cache.json")
DEFAULT_COLOR = "#AAAAAA"
AMAP_KEY_ENV_VARS = ("AMAP_API_KEY", "AMAP_KEY", "GAODE_API_KEY", "GAODE_KEY")


# ---------------------------------------------------------------------------
# 通用网络工具
# ---------------------------------------------------------------------------
def fetch_json(url, timeout=30, retries=3):
    """带重试的 JSON GET 请求。"""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise last_error


def get_amap_key(explicit_key=None):
    """获取高德 API Key（优先显式参数，其次环境变量）。"""
    if explicit_key:
        return explicit_key

    for env_name in AMAP_KEY_ENV_VARS:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value

    raise RuntimeError(
        "Amap API key is required. Set one of: " + ", ".join(AMAP_KEY_ENV_VARS)
    )


# ---------------------------------------------------------------------------
# 地铁图数据解析
# ---------------------------------------------------------------------------
def load_amap_subway_data(refresh=False):
    """加载高德地铁图原始 JSON（带本地缓存）。"""
    if RAW_CACHE_PATH.exists() and not refresh:
        with RAW_CACHE_PATH.open(encoding="utf-8") as handle:
            return json.load(handle)

    data = fetch_json(SUBWAY_DATA_URL, timeout=40, retries=4)
    RAW_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RAW_CACHE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    return data


def line_ref_from_name(line_name):
    match = re.search(r"(\d+)", line_name or "")
    return match.group(1) if match else line_name


def parse_station_coord(coord_text):
    """解析 '经度,纬度' 文本。返回 (lat, lon)。"""
    # 高德格式: "lon,lat"
    lon_str, lat_str = coord_text.split(",")
    return float(lat_str), float(lon_str)  # 返回 (lat, lon)


def sort_line_key(ref):
    if ref and str(ref).isdigit():
        return (0, int(ref))
    return (1, str(ref))


def build_amap_station_and_line_catalog(raw_data):
    """
    从高德地铁图 JSON 构建站点与线路目录。

    Returns:
        stations: list[dict]  — 去重后的站点列表
        lines:    list[dict]  — 线路列表（含有序站序）
    """
    station_index = {}
    lines = []

    for raw_line in raw_data.get("l", []):
        line_ref = line_ref_from_name(raw_line.get("ln", ""))
        color = raw_line.get("cl", "")
        color = f"#{color}" if color else DEFAULT_COLOR

        line_stations = []
        for raw_station in raw_line.get("st", []):
            lat, lon = parse_station_coord(raw_station["sl"])
            station_name = raw_station["n"].strip()
            station_info = station_index.setdefault(
                station_name,
                {
                    "name": station_name,
                    "display_name": station_name,
                    "lat": lat,
                    "lon": lon,
                    "coord_system": "gcj02",
                    "source": "amap_subway",
                    "source_name": station_name,
                    "line_refs": set(),
                    "line_labels": set(),
                    "poiid": raw_station.get("poiid", ""),
                },
            )
            station_info["line_refs"].add(line_ref)
            station_info["line_labels"].add(raw_line.get("kn", raw_line.get("ln", "")))

            line_stations.append(
                {
                    "name": station_name,
                    "lat": lat,
                    "lon": lon,
                    "poiid": raw_station.get("poiid", ""),
                }
            )

        lines.append(
            {
                "ref": line_ref,
                "name": raw_line.get("kn", raw_line.get("ln", "")),
                "display_name": raw_line.get("ln", ""),
                "color": color,
                "stations": line_stations,
            }
        )

    stations = []
    for station in station_index.values():
        line_refs = sorted(station["line_refs"], key=sort_line_key)
        line_labels = sorted(station["line_labels"])
        stations.append(
            {
                "name": station["name"],
                "display_name": station["display_name"],
                "lat": station["lat"],
                "lon": station["lon"],
                "coord_system": station["coord_system"],
                "source": station["source"],
                "source_name": station["source_name"],
                "line_refs": line_refs,
                "line_labels": line_labels,
                "primary_line_ref": line_refs[0] if line_refs else "",
                "poiid": station["poiid"],
            }
        )

    stations.sort(key=lambda item: (sort_line_key(item["primary_line_ref"]), item["display_name"]))
    lines.sort(key=lambda item: sort_line_key(item["ref"]))
    return stations, lines


# ---------------------------------------------------------------------------
# 线路几何拼接（使用高德路径规划 API）
# ---------------------------------------------------------------------------
def parse_polyline(polyline_text):
    """解析高德 polyline 字符串。返回 [[lat, lon], ...]。"""
    points = []
    for token in (polyline_text or "").split(";"):
        token = token.strip()
        if not token:
            continue
        lon_str, lat_str = token.split(",")
        # 返回 [lat, lon] 内部统一格式
        points.append([float(lat_str), float(lon_str)])
    return points


def match_busline_name(line, busline_name):
    text = busline_name or ""
    candidates = [
        line["name"],
        line["display_name"],
        f"地铁{line['ref']}号线",
        f"{line['ref']}号线",
    ]
    return any(candidate and candidate in text for candidate in candidates)


def orient_points(points, start_point, end_point):
    if not points:
        return points
    direct = meters_between(points[0], start_point) + meters_between(points[-1], end_point)
    reverse = meters_between(points[0], end_point) + meters_between(points[-1], start_point)
    if reverse < direct:
        return list(reversed(points))
    return points


def load_segment_cache():
    if SEGMENT_CACHE_PATH.exists():
        with SEGMENT_CACHE_PATH.open(encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def save_segment_cache(cache):
    SEGMENT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SEGMENT_CACHE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False)


def fetch_transit_segment(origin, destination, line, amap_key, cache):
    cache_key = f"{line['ref']}|{origin['name']}|{destination['name']}"
    if cache_key in cache:
        item = cache[cache_key]
        return item["points"], item["source"]

    params = urllib.parse.urlencode(
        {
            "key": amap_key,
            "origin": f"{origin['lon']},{origin['lat']}",
            "destination": f"{destination['lon']},{destination['lat']}",
            "city": "西安",
            "cityd": "西安",
            "strategy": "0",
            "extensions": "all",
            "output": "JSON",
        }
    )
    url = "https://restapi.amap.com/v3/direction/transit/integrated?" + params

    points = []
    source = "straight"
    try:
        response = fetch_json(url, timeout=25, retries=3)
        for transit in response.get("route", {}).get("transits", []):
            for segment in transit.get("segments", []):
                bus = segment.get("bus", {})
                buslines = bus.get("buslines", []) if isinstance(bus, dict) else []
                for busline in buslines:
                    if not match_busline_name(line, busline.get("name", "")):
                        continue
                    parsed = parse_polyline(busline.get("polyline", ""))
                    if parsed:
                        points = parsed
                        source = "amap_transit"
                        break
                if points:
                    break
            if points:
                break
    except Exception:
        points = []

    if not points:
        points = [
            [origin["lat"], origin["lon"]],
            [destination["lat"], destination["lon"]],
        ]
        source = "straight"

    points = orient_points(
        points,
        (origin["lat"], origin["lon"]),
        (destination["lat"], destination["lon"]),
    )
    cache[cache_key] = {"points": points, "source": source}
    time.sleep(0.12)
    return points, source


def build_amap_line_geometries(lines, amap_key):
    """为每条线路拼接完整 polyline 几何。"""
    cache = load_segment_cache()
    cache_changed = False
    built_lines = []

    for line in lines:
        merged_points = []
        segment_sources = []
        stations = line["stations"]
        for index in range(len(stations) - 1):
            origin = stations[index]
            destination = stations[index + 1]
            points, source = fetch_transit_segment(origin, destination, line, amap_key, cache)
            cache_changed = True
            segment_sources.append(source)
            if merged_points and points:
                if meters_between(merged_points[-1], points[0]) <= 2.0:
                    merged_points.extend(points[1:])
                else:
                    merged_points.extend(points)
            else:
                merged_points.extend(points)

        merged_points = dedupe_points(merged_points)
        built_lines.append(
            {
                "ref": line["ref"],
                "name": line["name"],
                "display_name": line["display_name"],
                "color": line["color"],
                "segments": [merged_points] if merged_points else [],
                "station_count": len(line["stations"]),
                "sources": segment_sources,
            }
        )

    if cache_changed:
        save_segment_cache(cache)
    return built_lines


# ---------------------------------------------------------------------------
# CSV 输出
# ---------------------------------------------------------------------------
def write_amap_station_csv(path, stations):
    """将站点列表写入 CSV。"""
    fieldnames = [
        "name",
        "display_name",
        "lat",
        "lon",
        "coord_system",
        "source",
        "source_name",
        "line_refs",
        "line_labels",
        "poiid",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for station in stations:
            writer.writerow(
                {
                    "name": station["name"],
                    "display_name": station["display_name"],
                    "lat": station["lat"],
                    "lon": station["lon"],
                    "coord_system": station["coord_system"],
                    "source": station["source"],
                    "source_name": station["source_name"],
                    "line_refs": "|".join(station["line_refs"]),
                    "line_labels": "|".join(station["line_labels"]),
                    "poiid": station["poiid"],
                }
            )
