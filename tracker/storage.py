"""Plain-file storage under data/: CSV time series + JSON metadata, committed to git as history."""

import csv
import json
import os
from collections import defaultdict

SNAPSHOT_FIELDS = ["date", "release_id", "lowest_price", "currency", "num_for_sale", "have", "want"]
TREND_FIELDS = ["date", "source", "rank", "artist", "title", "listeners", "playcount"]


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def upsert_rows(path, fields, new_rows, key_fields):
    """Replace rows sharing a key with `new_rows` (so re-running on the same day is idempotent)."""
    new_keys = {tuple(str(r[k]) for k in key_fields) for r in new_rows}
    kept = [r for r in read_csv(path) if tuple(r[k] for k in key_fields) not in new_keys]
    write_csv(path, fields, kept + new_rows)


def _num(value, cast=float):
    if value in (None, ""):
        return None
    try:
        return cast(value)
    except ValueError:
        return None


def snapshot_series(path):
    """{release_id: [ {date, price, for_sale, have, want}, ... ] sorted by date}"""
    series = defaultdict(list)
    for row in read_csv(path):
        series[int(row["release_id"])].append(
            {
                "date": row["date"],
                "price": _num(row["lowest_price"]),
                "currency": row.get("currency") or "",
                "for_sale": _num(row["num_for_sale"], int),
                "have": _num(row["have"], int),
                "want": _num(row["want"], int),
            }
        )
    for points in series.values():
        points.sort(key=lambda p: p["date"])
    return dict(series)


def trend_rows(path):
    rows = read_csv(path)
    for r in rows:
        r["rank"] = _num(r["rank"], int)
        r["listeners"] = _num(r["listeners"], int)
        r["playcount"] = _num(r["playcount"], int)
    return rows
