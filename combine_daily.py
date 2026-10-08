#!/usr/bin/env python3
"""Combine per-station audience and schedule JSON into one CSV per day.

Each output row is one minute of audience data for one station, joined to
the schedule item that was on air at that minute.

Usage:
    python3 combine_daily.py                          # 2018-01-01 only
    python3 combine_daily.py --start 2018-01-01 --end 2018-01-31
    python3 combine_daily.py --start 2018-01-01 --end 2018-01-31 --overwrite
"""

import argparse
import csv
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUDIENCE_DIR = ROOT / "output" / "audience"
SCHEDULE_DIR = ROOT / "output" / "schedule"
OUT_DIR = ROOT / "combined-csv"

COLUMNS = [
    "timestamp",
    "current",
    "show_start",
    "show_end",
    "show_title",
    "brand_title",
    "station",
    "broadcast_pid",
    "episode_pid",
]


def iso(ms):
    """Epoch milliseconds -> 'yyyy-mm-ddTHH:MM:SS' (UTC)."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def load_json(path):
    if not path.exists():
        return None
    with path.open() as f:
        return json.load(f)


def load_schedule(station, day):
    """Schedule items for the day plus neighbours, so shows crossing midnight are covered."""
    items = {}
    for d in (day - timedelta(days=1), day, day + timedelta(days=1)):
        data = load_json(SCHEDULE_DIR / station / f"{station}_schedule_{d.isoformat()}.json")
        for item in (data or {}).get("items", []):
            items[item["broadcastPID"]] = item
    return sorted(items.values(), key=lambda i: i["startTimestamp"])


def find_show(schedule, ts):
    """Latest-starting schedule item on air at ts, or None."""
    match = None
    for item in schedule:
        if item["startTimestamp"] > ts:
            break
        if ts < item["endTimestamp"]:
            match = item
    return match


def rows_for_station(station, day):
    data = load_json(AUDIENCE_DIR / station / f"{station}_audience_{day.isoformat()}.json")
    if not data or not data.get("audience"):
        return []

    # Audience files include 00:00 of the next day; drop it so days don't overlap.
    day_end = int(datetime.fromisoformat(data["dates"]["end"].replace("Z", "+00:00")).timestamp() * 1000)
    schedule = load_schedule(station, day)

    rows = []
    for rec in sorted(data["audience"].values(), key=lambda r: r["timestamp"]):
        ts = rec["timestamp"]
        if ts >= day_end:
            continue
        show = find_show(schedule, ts) or {}
        rows.append({
            "timestamp": iso(ts),
            "current": rec.get("current", ""),
            "show_start": iso(show["startTimestamp"]) if show else "",
            "show_end": iso(show["endTimestamp"]) if show else "",
            "show_title": show.get("episodeTitle", ""),
            "brand_title": show.get("brandTitle", ""),
            "station": data.get("networkId", station),
            "broadcast_pid": show.get("broadcastPID", ""),
            "episode_pid": show.get("episodePID", ""),
        })
    return rows


def combine_day(day, overwrite):
    out_path = OUT_DIR / f"combined_{day.isoformat()}.csv"
    if out_path.exists() and not overwrite:
        print(f"{day}: exists, skipping (use --overwrite)")
        return

    stations = sorted(p.name for p in AUDIENCE_DIR.iterdir() if p.is_dir())
    rows, with_data, unmatched = [], [], 0
    for station in stations:
        station_rows = rows_for_station(station, day)
        if station_rows:
            with_data.append(station)
            unmatched += sum(1 for r in station_rows if not r["broadcast_pid"])
        rows.extend(station_rows)

    OUT_DIR.mkdir(exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{day}: {len(rows)} rows, {len(with_data)}/{len(stations)} stations with data, "
          f"{unmatched} rows with no matching show -> {out_path.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2018, 1, 1), help="first day (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, help="last day inclusive (default: same as --start)")
    parser.add_argument("--overwrite", action="store_true", help="replace existing CSVs")
    args = parser.parse_args()

    day, end = args.start, args.end or args.start
    while day <= end:
        combine_day(day, args.overwrite)
        day += timedelta(days=1)


if __name__ == "__main__":
    main()
