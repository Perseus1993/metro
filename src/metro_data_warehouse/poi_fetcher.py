"""
按站点缓冲区分类别抓取高德 POI（8 类建成环境变量）。
"""

import argparse
import csv
import json
import time
import urllib.parse
from pathlib import Path

from metro_data_warehouse.amap_network import fetch_json, get_amap_key
from metro_data_warehouse.geo_utils import (
    build_circle_polygon,
    distance_weight,
    meters_between,
    polygon_param,
)

DEFAULT_STATION_PATH = Path("output/xian_metro_stations_amap_subway.csv")
DEFAULT_CACHE_PATH = Path("cache/amap_station_poi_cache.json")
DEFAULT_RAW_OUTPUT_PATH = Path("output/xian_station_poi_raw_600m.csv")
DEFAULT_SUMMARY_OUTPUT_PATH = Path("output/xian_station_poi_summary_600m.csv")
DEFAULT_BUFFER_OUTPUT_PATH = Path("output/xian_station_buffers_600m.geojson")
DEFAULT_RADIUS_M = 600
DEFAULT_POLYGON_POINTS = 16
DEFAULT_OFFSET = 25
DEFAULT_SLEEP_S = 0.35
DEFAULT_DECAY_SCALE_M = 300.0


# These groups are aligned with common metro-built-environment variables in the literature.
POI_CATEGORIES = [
    {"id": "residential", "label": "住宅社区", "types": "120300"},
    {"id": "employment", "label": "办公就业", "types": "120200|170000"},
    {
        "id": "commercial_service",
        "label": "商业服务",
        "types": "050000|060000|070000|100000|160000",
    },
    {"id": "education_culture", "label": "教育文化", "types": "140000"},
    {"id": "medical", "label": "医疗健康", "types": "090000"},
    {"id": "leisure_tourism", "label": "休闲旅游", "types": "080000|110000"},
    {"id": "public_service", "label": "公共服务", "types": "130000"},
    {"id": "bus_stop", "label": "公交站点", "types": "150700"},
]


def load_stations(path):
    stations = []
    with Path(path).open(encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            # 规则 10: CSV 列名读入后必须 strip()
            row = {k.strip(): v for k, v in row.items()}
            stations.append(
                {
                    "name": row["name"].strip(),
                    "display_name": row.get("display_name", row["name"]).strip(),
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "line_refs": row.get("line_refs", ""),
                    "line_labels": row.get("line_labels", ""),
                    "poiid": row.get("poiid", ""),
                }
            )
    return stations


def normalize_station_filter(values):
    if not values:
        return set()
    return {value.strip() for value in values if value.strip()}


def load_cache(path):
    cache_path = Path(path)
    if cache_path.exists():
        with cache_path.open(encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def save_cache(path, cache):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False)


def rows_from_cache(cache, stations, radius_m):
    wanted_station_names = {station["name"] for station in stations}
    rows = []
    for item in cache.values():
        if item.get("radius_m") != radius_m:
            continue
        station_name = item.get("station_name")
        if station_name not in wanted_station_names:
            continue
        rows.extend(item.get("pois", []))
    return rows


def parse_poi(station, category, poi, radius_m):
    location = poi.get("location", "")
    if not location or "," not in location:
        return None

    lon_str, lat_str = location.split(",", 1)
    poi_lon = float(lon_str)
    poi_lat = float(lat_str)
    distance_m = meters_between((station["lat"], station["lon"]), (poi_lat, poi_lon))

    if distance_m > radius_m + 1:
        return None

    return {
        "station_name": station["name"],
        "station_display_name": station["display_name"],
        "station_lat": station["lat"],
        "station_lon": station["lon"],
        "line_refs": station["line_refs"],
        "line_labels": station["line_labels"],
        "buffer_m": radius_m,
        "category_id": category["id"],
        "category_label": category["label"],
        "query_types": category["types"],
        "poi_id": poi.get("id", ""),
        "poi_name": poi.get("name", ""),
        "poi_type": poi.get("type", ""),
        "poi_typecode": poi.get("typecode", ""),
        "poi_lat": poi_lat,
        "poi_lon": poi_lon,
        "distance_m": round(distance_m, 1),
        "address": poi.get("address", ""),
        "adname": poi.get("adname", ""),
        "cityname": poi.get("cityname", ""),
        "pname": poi.get("pname", ""),
    }


def fetch_station_category_pois(
    station, category, amap_key, radius_m, offset, sleep_s, cache, refresh=False
):
    cache_key = f"{station['name']}|{radius_m}|{category['id']}"
    if not refresh and cache_key in cache:
        return cache[cache_key]["pois"]

    polygon = polygon_param(build_circle_polygon(station["lat"], station["lon"], radius_m))
    results = []
    page = 1
    api_count = 0

    while True:
        params = urllib.parse.urlencode(
            {
                "key": amap_key,
                "polygon": polygon,
                "types": category["types"],
                "offset": offset,
                "page": page,
                "extensions": "base",
                "output": "JSON",
            }
        )
        url = "https://restapi.amap.com/v3/place/polygon?" + params
        response = fetch_json(url, timeout=30, retries=3)

        if response.get("status") != "1":
            info = response.get("info", "unknown_error")
            raise RuntimeError(f"高德 POI 查询失败: {station['name']} / {category['id']} / {info}")

        api_count = int(response.get("count") or 0)
        pois = response.get("pois") or []
        if not pois:
            break

        results.extend(pois)

        if len(pois) < offset:
            break
        if api_count and page * offset >= api_count:
            break
        if page >= 100:
            break

        page += 1
        time.sleep(sleep_s)

    deduped = []
    seen_ids = set()
    for poi in results:
        parsed = parse_poi(station, category, poi, radius_m)
        if not parsed:
            continue
        poi_id = parsed["poi_id"] or f"{parsed['poi_name']}|{parsed['poi_lon']}|{parsed['poi_lat']}"
        if poi_id in seen_ids:
            continue
        seen_ids.add(poi_id)
        deduped.append(parsed)

    cache[cache_key] = {
        "station_name": station["name"],
        "category_id": category["id"],
        "category_label": category["label"],
        "query_types": category["types"],
        "radius_m": radius_m,
        "api_count": api_count,
        "poi_count": len(deduped),
        "retrieved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pois": deduped,
    }
    return deduped


def write_raw_csv(path, rows):
    fieldnames = [
        "station_name",
        "station_display_name",
        "station_lat",
        "station_lon",
        "line_refs",
        "line_labels",
        "buffer_m",
        "category_id",
        "category_label",
        "query_types",
        "poi_id",
        "poi_name",
        "poi_type",
        "poi_typecode",
        "poi_lat",
        "poi_lon",
        "distance_m",
        "address",
        "adname",
        "cityname",
        "pname",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summarize_station_pois(stations, rows, radius_m, decay_scale_m):
    category_ids = [category["id"] for category in POI_CATEGORIES]
    station_index = {}

    for station in stations:
        summary = {
            "station_name": station["name"],
            "station_display_name": station["display_name"],
            "station_lat": station["lat"],
            "station_lon": station["lon"],
            "line_refs": station["line_refs"],
            "line_labels": station["line_labels"],
            "buffer_m": radius_m,
            "decay_scale_m": decay_scale_m,
        }
        for category_id in category_ids:
            summary[f"count_{category_id}"] = 0
            summary[f"weight_{category_id}"] = 0.0
            summary[f"nearest_{category_id}_m"] = ""
        summary["_unique_poi_ids"] = set()
        station_index[station["name"]] = summary

    for row in rows:
        summary = station_index[row["station_name"]]
        category_id = row["category_id"]
        distance_m = float(row["distance_m"])
        summary[f"count_{category_id}"] += 1
        summary[f"weight_{category_id}"] += distance_weight(distance_m, decay_scale_m)
        nearest_key = f"nearest_{category_id}_m"
        if summary[nearest_key] == "" or distance_m < float(summary[nearest_key]):
            summary[nearest_key] = round(distance_m, 1)
        summary["_unique_poi_ids"].add(
            row["poi_id"] or f"{row['poi_name']}|{row['poi_lon']}|{row['poi_lat']}"
        )

    for summary in station_index.values():
        summary["count_total"] = sum(
            summary[f"count_{category_id}"] for category_id in category_ids
        )
        summary["unique_poi_total"] = len(summary["_unique_poi_ids"])
        for category_id in category_ids:
            summary[f"weight_{category_id}"] = round(summary[f"weight_{category_id}"], 3)
        del summary["_unique_poi_ids"]

    return list(station_index.values())


def write_summary_csv(path, summary_rows):
    category_ids = [category["id"] for category in POI_CATEGORIES]
    fieldnames = [
        "station_name",
        "station_display_name",
        "station_lat",
        "station_lon",
        "line_refs",
        "line_labels",
        "buffer_m",
        "decay_scale_m",
        *[f"count_{category_id}" for category_id in category_ids],
        *[f"weight_{category_id}" for category_id in category_ids],
        *[f"nearest_{category_id}_m" for category_id in category_ids],
        "count_total",
        "unique_poi_total",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)


def write_buffer_geojson(path, stations, radius_m):
    features = []
    for station in stations:
        polygon_coords = build_circle_polygon(station["lat"], station["lon"], radius_m)
        polygon_coords.append(polygon_coords[0])
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "station_name": station["name"],
                    "display_name": station["display_name"],
                    "line_refs": station["line_refs"],
                    "line_labels": station["line_labels"],
                    "buffer_m": radius_m,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [polygon_coords],
                },
            }
        )

    payload = {"type": "FeatureCollection", "features": features}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def parse_args():
    parser = argparse.ArgumentParser(description="按西安地铁站 600m 缓冲区抓取高德 POI")
    parser.add_argument("--stations", default=str(DEFAULT_STATION_PATH), help="站点 CSV 路径")
    parser.add_argument("--radius", type=int, default=DEFAULT_RADIUS_M, help="缓冲半径（米）")
    parser.add_argument("--max-stations", type=int, default=0, help="仅抓取前 N 个站点，0 表示全部")
    parser.add_argument("--start-index", type=int, default=1, help="起始站点序号（从 1 开始）")
    parser.add_argument(
        "--end-index",
        type=int,
        default=0,
        help="结束站点序号（包含该序号，0 表示直到最后）",
    )
    parser.add_argument(
        "--station-name",
        action="append",
        default=[],
        help="仅抓指定站点，可重复传入多个",
    )
    parser.add_argument(
        "--sleep", type=float, default=DEFAULT_SLEEP_S, help="每页请求之间的暂停秒数"
    )
    parser.add_argument("--offset", type=int, default=DEFAULT_OFFSET, help="每页结果数")
    parser.add_argument(
        "--decay-scale",
        type=float,
        default=DEFAULT_DECAY_SCALE_M,
        help="距离衰减尺度（米），用于生成加权 POI 指标",
    )
    parser.add_argument("--refresh", action="store_true", help="忽略本地缓存，重新抓取")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE_PATH), help="缓存 JSON 路径")
    parser.add_argument(
        "--raw-out", default=str(DEFAULT_RAW_OUTPUT_PATH), help="原始 POI CSV 输出路径"
    )
    parser.add_argument(
        "--summary-out",
        default=str(DEFAULT_SUMMARY_OUTPUT_PATH),
        help="站点级汇总 CSV 输出路径",
    )
    parser.add_argument(
        "--buffer-out",
        default=str(DEFAULT_BUFFER_OUTPUT_PATH),
        help="600m buffer GeoJSON 输出路径",
    )
    parser.add_argument(
        "--export-cache-only",
        action="store_true",
        help="不发起新请求，只把当前缓存导出为明细/汇总文件",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    amap_key = get_amap_key()
    stations = load_stations(args.stations)
    station_filter = normalize_station_filter(args.station_name)

    if station_filter:
        stations = [station for station in stations if station["name"] in station_filter]
    else:
        start = max(args.start_index, 1) - 1
        end = args.end_index if args.end_index > 0 else len(stations)
        stations = stations[start:end]
    if args.max_stations:
        stations = stations[: args.max_stations]

    if not stations:
        raise SystemExit("没有匹配到任何站点。")

    print(f"待处理站点数: {len(stations)}")
    print(f"缓冲半径: {args.radius}m")
    print(f"POI 类别数: {len(POI_CATEGORIES)}")

    cache = load_cache(args.cache)
    if args.export_cache_only:
        all_rows = rows_from_cache(cache, stations, args.radius)
        all_rows.sort(
            key=lambda row: (
                row["station_name"],
                row["category_id"],
                row["distance_m"],
                row["poi_name"],
            )
        )
        write_raw_csv(args.raw_out, all_rows)
        print(f"原始明细已写出: {args.raw_out}")

        summary_rows = summarize_station_pois(stations, all_rows, args.radius, args.decay_scale)
        write_summary_csv(args.summary_out, summary_rows)
        print(f"站点汇总已写出: {args.summary_out}")

        write_buffer_geojson(args.buffer_out, stations, args.radius)
        print(f"缓冲区 GeoJSON 已写出: {args.buffer_out}")
        return

    all_rows = []

    for station_index, station in enumerate(stations, start=1):
        print(f"[{station_index}/{len(stations)}] {station['name']}")
        station_changed = False
        for category in POI_CATEGORIES:
            before = len(cache)
            rows = fetch_station_category_pois(
                station=station,
                category=category,
                amap_key=amap_key,
                radius_m=args.radius,
                offset=args.offset,
                sleep_s=args.sleep,
                cache=cache,
                refresh=args.refresh,
            )
            if len(cache) != before:
                station_changed = True
            print(f"  - {category['label']}: {len(rows)}")
            all_rows.extend(rows)

        if station_changed or args.refresh:
            save_cache(args.cache, cache)
            print(f"  已保存缓存: {args.cache}")

    print(f"缓存文件: {args.cache}")

    all_rows.sort(
        key=lambda row: (
            row["station_name"],
            row["category_id"],
            row["distance_m"],
            row["poi_name"],
        )
    )
    write_raw_csv(args.raw_out, all_rows)
    print(f"原始明细已写出: {args.raw_out}")

    summary_rows = summarize_station_pois(stations, all_rows, args.radius, args.decay_scale)
    write_summary_csv(args.summary_out, summary_rows)
    print(f"站点汇总已写出: {args.summary_out}")

    write_buffer_geojson(args.buffer_out, stations, args.radius)
    print(f"缓冲区 GeoJSON 已写出: {args.buffer_out}")


if __name__ == "__main__":
    main()
