"""Fetch hourly historical weather data from Open-Meteo.

The default location is central Xi'an and the default period matches the
current metro operations reports: 2025-01-01 through 2025-06-30.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.etl.paths import RAW_WEATHER_DIR  # noqa: E402


DEFAULT_HOURLY = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "weather_code",
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
]


def build_url(args: argparse.Namespace) -> str:
    params = {
        "latitude": args.latitude,
        "longitude": args.longitude,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "hourly": ",".join(DEFAULT_HOURLY),
        "timezone": args.timezone,
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
        "timeformat": "iso8601",
    }
    if args.models:
        params["models"] = args.models
    return f"https://archive-api.open-meteo.com/v1/archive?{urlencode(params)}"


def fetch_json(url: str) -> dict:
    with urlopen(url, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def write_hourly_csv(payload: dict, csv_path: Path) -> int:
    hourly = payload["hourly"]
    times = hourly["time"]
    value_columns = [name for name in DEFAULT_HOURLY if name in hourly]
    fields = ["time"] + value_columns

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for idx, timestamp in enumerate(times):
            row = {"time": timestamp}
            for column in value_columns:
                row[column] = hourly[column][idx]
            writer.writerow(row)

    return len(times)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latitude", type=float, default=34.3416)
    parser.add_argument("--longitude", type=float, default=108.9398)
    parser.add_argument("--label", default="xian_center")
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default="2025-06-30")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--models", default="era5")
    parser.add_argument(
        "--output-dir",
        default=str(RAW_WEATHER_DIR),
        help="Directory for raw JSON and cleaned CSV outputs.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    stem = f"open_meteo_{args.label}_{args.start_date}_{args.end_date}_hourly"
    raw_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}.csv"

    url = build_url(args)
    payload = fetch_json(url)

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rows = write_hourly_csv(payload, csv_path)

    print(f"url={url}")
    print(f"raw_json={raw_path}")
    print(f"csv={csv_path}")
    print(f"rows={rows}")
    print(f"timezone={payload.get('timezone')}")
    print(f"latitude={payload.get('latitude')}")
    print(f"longitude={payload.get('longitude')}")
    print(f"elevation={payload.get('elevation')}")


if __name__ == "__main__":
    main()
