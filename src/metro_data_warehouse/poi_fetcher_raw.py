"""
按站点缓冲区抓取全部高德 POI（不分类别）。
"""

import argparse
import csv
import json
import time
import urllib.parse
from pathlib import Path

from metro_data_warehouse.amap_network import fetch_json, get_amap_key
from metro_data_warehouse.geo_utils import build_circle_polygon, meters_between, polygon_param
from metro_data_warehouse.poi_fetcher import load_stations, write_buffer_geojson

DEFAULT_STATION_PATH = Path("output/xian_metro_stations_amap_subway.csv")
DEFAULT_CACHE_PATH = Path("cache/amap_station_poi_all_cache.json")
DEFAULT_RAW_OUTPUT_PATH = Path("output/xian_station_poi_all_raw_600m.csv")
DEFAULT_SUMMARY_OUTPUT_PATH = Path("output/xian_station_poi_all_summary_600m.csv")
DEFAULT_BUFFER_OUTPUT_PATH = Path("output/xian_station_buffers_600m.geojson")
DEFAULT_RADIUS_M = 600
DEFAULT_POLYGON_POINTS = 16
DEFAULT_OFFSET = 25
DEFAULT_SLEEP_S = 0.1


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


def normalize_station_filter(values):
    if not values:
        return set()
    return {value.strip() for value in values if value.strip()}


def split_type_levels(type_text):
    parts = [part.strip() for part in (type_text or "").split(";")]
    while len(parts) < 3:
        parts.append("")
    return parts[:3]


def parse_poi(station, poi, radius_m):
    location = poi.get("location", "")
    if not location or "," not in location:
        return None

    lon_str, lat_str = location.split(",", 1)
    poi_lon = float(lon_str)
    poi_lat = float(lat_str)
    distance_m = meters_between((station["lat"], station["lon"]), (poi_lat, poi_lon))
    if distance_m > radius_m + 1:
        return None

    type_l1, type_l2, type_l3 = split_type_levels(poi.get("type", ""))
    return {
        "station_name": station["name"],
        "station_display_name": station["display_name"],
        "station_lat": station["lat"],
        "station_lon": station["lon"],
        "line_refs": station["line_refs"],
        "line_labels": station["line_labels"],
        "buffer_m": radius_m,
        "poi_id": poi.get("id", ""),
        "poi_name": poi.get("name", ""),
        "poi_type": poi.get("type", ""),
        "poi_typecode": poi.get("typecode", ""),
        "poi_type_l1": type_l1,
        "poi_type_l2": type_l2,
        "poi_type_l3": type_l3,
        "poi_lat": poi_lat,
        "poi_lon": poi_lon,
        "distance_m": round(distance_m, 1),
        "address": poi.get("address", ""),
        "adname": poi.get("adname", ""),
        "cityname": poi.get("cityname", ""),
        "pname": poi.get("pname", ""),
    }


def fetch_station_pois(station, amap_key, radius_m, offset, sleep_s, cache, refresh=False):
    cache_key = f"{station['name']}|{radius_m}|all"
    if not refresh and cache_key in cache:
        return cache[cache_key]["pois"]

    polygon = polygon_param(
        build_circle_polygon(
            station["lat"], station["lon"], radius_m, point_count=DEFAULT_POLYGON_POINTS
        )
    )
    results = []
    page = 1
    api_count = 0

    while True:
        params = urllib.parse.urlencode(
            {
                "key": amap_key,
                "polygon": polygon,
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
            raise RuntimeError(f"高德 POI 查询失败: {station['name']} / {info}")

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
        parsed = parse_poi(station, poi, radius_m)
        if not parsed:
            continue
        poi_id = parsed["poi_id"] or f"{parsed['poi_name']}|{parsed['poi_lon']}|{parsed['poi_lat']}"
        if poi_id in seen_ids:
            continue
        seen_ids.add(poi_id)
        deduped.append(parsed)

    truncated = api_count > len(deduped)
    cache[cache_key] = {
        "station_name": station["name"],
        "radius_m": radius_m,
        "api_count": api_count,
        "poi_count": len(deduped),
        "truncated": truncated,
        "retrieved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pois": deduped,
    }
    return deduped


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


def write_raw_csv(path, rows):
    fieldnames = [
        "station_name",
        "station_display_name",
        "station_lat",
        "station_lon",
        "line_refs",
        "line_labels",
        "buffer_m",
        "poi_id",
        "poi_name",
        "poi_type",
        "poi_typecode",
        "poi_type_l1",
        "poi_type_l2",
        "poi_type_l3",
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


def summarize_station_pois(stations, rows, radius_m, cache):
    station_index = {}
    for station in stations:
        cache_item = cache.get(f"{station['name']}|{radius_m}|all", {})
        station_index[station["name"]] = {
            "station_name": station["name"],
            "station_display_name": station["display_name"],
            "station_lat": station["lat"],
            "station_lon": station["lon"],
            "line_refs": station["line_refs"],
            "line_labels": station["line_labels"],
            "buffer_m": radius_m,
            "api_count": cache_item.get("api_count", ""),
            "poi_total": 0,
            "nearest_poi_m": "",
            "truncated": "",
            "_unique_poi_ids": set(),
        }

    for row in rows:
        summary = station_index[row["station_name"]]
        distance_m = float(row["distance_m"])
        poi_id = row["poi_id"] or f"{row['poi_name']}|{row['poi_lon']}|{row['poi_lat']}"
        if poi_id in summary["_unique_poi_ids"]:
            continue
        summary["_unique_poi_ids"].add(poi_id)
        summary["poi_total"] += 1
        if summary["nearest_poi_m"] == "" or distance_m < float(summary["nearest_poi_m"]):
            summary["nearest_poi_m"] = round(distance_m, 1)

    output = []
    for summary in station_index.values():
        summary["unique_poi_total"] = len(summary["_unique_poi_ids"])
        api_count = int(summary["api_count"]) if summary["api_count"] not in ("", None) else 0
        summary["truncated"] = int(api_count > summary["unique_poi_total"]) if api_count else ""
        del summary["_unique_poi_ids"]
        output.append(summary)
    return output


def write_summary_csv(path, summary_rows):
    fieldnames = [
        "station_name",
        "station_display_name",
        "station_lat",
        "station_lon",
        "line_refs",
        "line_labels",
        "buffer_m",
        "api_count",
        "poi_total",
        "unique_poi_total",
        "nearest_poi_m",
        "truncated",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)


def parse_args():
    parser = argparse.ArgumentParser(
        description="按西安地铁站 600m 缓冲区抓取全部高德 POI 原始明细"
    )
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
    parser.add_argument("--refresh", action="store_true", help="忽略本地缓存，重新抓取")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE_PATH), help="缓存 JSON 路径")
    parser.add_argument(
        "--raw-out", default=str(DEFAULT_RAW_OUTPUT_PATH), help="原始 POI CSV 输出路径"
    )
    parser.add_argument(
        "--summary-out",
        default=str(DEFAULT_SUMMARY_OUTPUT_PATH),
        help="站点汇总 CSV 输出路径",
    )
    parser.add_argument(
        "--buffer-out",
        default=str(DEFAULT_BUFFER_OUTPUT_PATH),
        help="buffer GeoJSON 输出路径",
    )
    parser.add_argument(
        "--export-cache-only",
        action="store_true",
        help="不发起新请求，只导出当前缓存",
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

    cache = load_cache(args.cache)
    if args.export_cache_only:
        all_rows = rows_from_cache(cache, stations, args.radius)
        all_rows.sort(key=lambda row: (row["station_name"], row["distance_m"], row["poi_name"]))
        write_raw_csv(args.raw_out, all_rows)
        print(f"原始明细已写出: {args.raw_out}")
        summary_rows = summarize_station_pois(stations, all_rows, args.radius, cache)
        write_summary_csv(args.summary_out, summary_rows)
        print(f"站点汇总已写出: {args.summary_out}")
        write_buffer_geojson(args.buffer_out, stations, args.radius)
        print(f"缓冲区 GeoJSON 已写出: {args.buffer_out}")
        return

    all_rows = []
    for station_index, station in enumerate(stations, start=1):
        print(f"[{station_index}/{len(stations)}] {station['name']}")
        before = len(cache)
        rows = fetch_station_pois(
            station=station,
            amap_key=amap_key,
            radius_m=args.radius,
            offset=args.offset,
            sleep_s=args.sleep,
            cache=cache,
            refresh=args.refresh,
        )
        print(f"  - POI: {len(rows)}")
        all_rows.extend(rows)
        if len(cache) != before or args.refresh:
            save_cache(args.cache, cache)
            print(f"  已保存缓存: {args.cache}")

    print(f"缓存文件: {args.cache}")
    all_rows.sort(key=lambda row: (row["station_name"], row["distance_m"], row["poi_name"]))
    write_raw_csv(args.raw_out, all_rows)
    print(f"原始明细已写出: {args.raw_out}")
    summary_rows = summarize_station_pois(stations, all_rows, args.radius, cache)
    write_summary_csv(args.summary_out, summary_rows)
    print(f"站点汇总已写出: {args.summary_out}")
    write_buffer_geojson(args.buffer_out, stations, args.radius)
    print(f"缓冲区 GeoJSON 已写出: {args.buffer_out}")


if __name__ == "__main__":
    main()
