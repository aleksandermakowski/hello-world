"""The daily run: collect trends -> find matching pressings -> snapshot prices -> score -> publish."""

import os
from datetime import date, datetime, timedelta, timezone

from . import storage, trends
from .scoring import score_release

DEFAULT_DISCOVERY = {
    "releases_per_track": 3,  # keep the N most-wanted pressings per trending song and format
    "min_want": 25,  # ignore obscure pressings nobody is looking for
    "max_searches_per_run": 40,  # Discogs searches per run (rate limit: 60 requests/min)
    "research_after_days": 30,  # refresh a song's pressings this often
    "drop_after_days": 60,  # stop tracking songs that left the charts this long ago
}
HISTORY_POINTS = 120  # days of history shipped to the website per release


class Paths:
    def __init__(self, root):
        self.root = root
        self.config = os.path.join(root, "watchlist.json")
        self.snapshots = os.path.join(root, "data", "snapshots.csv")
        self.trends = os.path.join(root, "data", "trends.csv")
        self.discovered = os.path.join(root, "data", "discovered.json")
        self.releases = os.path.join(root, "data", "releases.json")
        self.alerts = os.path.join(root, "data", "alerts.json")
        self.site_data = os.path.join(root, "site", "data.js")


def load_config(paths):
    cfg = storage.load_json(paths.config, {})
    cfg.setdefault("currency", "USD")
    cfg.setdefault("formats", ["Vinyl"])
    cfg.setdefault("releases", [])
    cfg.setdefault("seeds", [])
    cfg["discovery"] = {**DEFAULT_DISCOVERY, **cfg.get("discovery", {})}
    return cfg


def _days_ago(day, n):
    return (date.fromisoformat(day) - timedelta(days=n)).isoformat()


def collect_trends(cfg, paths, today, lastfm_key=None, sources=None, log=print):
    """Fetch every trend source (a failing source is logged and skipped) and store today's rows."""
    if sources is None:
        sources = [("deezer", trends.deezer_chart)]
        if lastfm_key:
            sources.append(("lastfm", lambda: trends.lastfm_top_tracks(lastfm_key)))
    items = trends.seed_tracks(cfg["seeds"])
    for name, fetch in sources:
        try:
            got = fetch()
            log(f"trends: {name} returned {len(got)} tracks")
            items.extend(got)
        except Exception as err:  # one broken source shouldn't stop the run
            log(f"trends: {name} failed: {err}")
    rows = [{"date": today, **item} for item in items]
    storage.upsert_rows(
        paths.trends, storage.TREND_FIELDS, rows, ["date", "source", "artist", "title"]
    )
    return items


def discover(cfg, paths, client, items, today, log=print):
    """Map trending songs to specific Discogs pressings worth tracking."""
    opts = cfg["discovery"]
    discovered = storage.load_json(paths.discovered, {})
    # Seeds first, then best-ranked chart entries, so the search budget goes to what matters most.
    ordered = sorted(items, key=lambda i: (i["source"] != "seed", i["rank"] or 0))
    searches = 0
    for item in ordered:
        key = trends.track_key(item["artist"], item["title"])
        entry = discovered.setdefault(
            key, {"artist": item["artist"], "title": item["title"], "releases": [], "searched": None}
        )
        entry["last_seen"] = today
        stale = not entry["searched"] or entry["searched"] < _days_ago(today, opts["research_after_days"])
        if not stale or searches >= opts["max_searches_per_run"]:
            continue
        found = []
        for fmt in cfg["formats"]:
            searches += 1
            try:
                results = client.search_releases(item["artist"], item["title"], fmt=fmt)
            except Exception as err:
                log(f"discover: search failed for {key} ({fmt}): {err}")
                continue
            popular = sorted(
                (r for r in results if (r["want"] or 0) >= opts["min_want"]),
                key=lambda r: r["want"],
                reverse=True,
            )
            found.extend(r["id"] for r in popular[: opts["releases_per_track"]])
        entry["releases"] = found
        entry["searched"] = today
    storage.save_json(paths.discovered, discovered)
    log(f"discover: {searches} searches, {len(discovered)} songs known")
    return discovered


def tracked_release_ids(cfg, discovered, today):
    ids = {int(r["id"]) for r in cfg["releases"]}
    cutoff = _days_ago(today, cfg["discovery"]["drop_after_days"])
    for entry in discovered.values():
        if entry.get("last_seen", "") >= cutoff:
            ids.update(int(i) for i in entry["releases"])
    return sorted(ids)


def snapshot(cfg, paths, client, release_ids, today, log=print):
    """Record today's lowest price, copies for sale and have/want for every tracked pressing."""
    meta_all = storage.load_json(paths.releases, {})
    rows = []
    for rid in release_ids:
        try:
            info = client.release(rid)
        except Exception as err:
            log(f"snapshot: release {rid} failed: {err}")
            continue
        rows.append(
            {
                "date": today,
                "release_id": rid,
                "lowest_price": info["lowest_price"],
                "currency": cfg["currency"],
                "num_for_sale": info["num_for_sale"],
                "have": info["have"],
                "want": info["want"],
            }
        )
        market = ("lowest_price", "num_for_sale", "have", "want")
        meta_all[str(rid)] = {k: v for k, v in info.items() if k not in market}
    storage.upsert_rows(paths.snapshots, storage.SNAPSHOT_FIELDS, rows, ["date", "release_id"])
    storage.save_json(paths.releases, meta_all)
    log(f"snapshot: {len(rows)}/{len(release_ids)} releases recorded")
    return rows


def trend_info_by_track(trend_rows, today):
    """{track_key: {sources, best_rank, listener_growth}} for the last 7 days of charts."""
    week_ago = _days_ago(today, 7)
    info = {}
    listeners = {}
    for row in trend_rows:
        key = trends.track_key(row["artist"], row["title"])
        if row["source"] == "lastfm" and row["listeners"]:
            listeners.setdefault(key, []).append((row["date"], row["listeners"]))
        if row["date"] < week_ago:
            continue
        entry = info.setdefault(key, {"sources": set(), "best_rank": None, "listener_growth": None})
        entry["sources"].add(row["source"])
        if row["rank"] is not None and (entry["best_rank"] is None or row["rank"] < entry["best_rank"]):
            entry["best_rank"] = row["rank"]
    for key, points in listeners.items():
        if key not in info or len(points) < 2:
            continue
        points.sort()
        base = next((p for p in reversed(points) if p[0] <= week_ago), points[0])
        if base[1]:
            info[key]["listener_growth"] = (points[-1][1] - base[1]) / base[1]
    return info


def build_site_data(cfg, paths, today):
    """Score everything we have history for and write site/data.js for the dashboard."""
    series = storage.snapshot_series(paths.snapshots)
    meta_all = storage.load_json(paths.releases, {})
    discovered = storage.load_json(paths.discovered, {})
    track_info = trend_info_by_track(storage.trend_rows(paths.trends), today)
    notes = {int(r["id"]): r.get("note", "") for r in cfg["releases"]}
    tracked = set(tracked_release_ids(cfg, discovered, today))

    songs_by_release = {}
    for key, entry in discovered.items():
        for rid in entry["releases"]:
            songs_by_release.setdefault(int(rid), []).append((key, entry))

    items = []
    for rid, points in series.items():
        if rid not in tracked or str(rid) not in meta_all:
            continue
        meta = meta_all[str(rid)]
        songs = songs_by_release.get(rid, [])
        trend = _merge_trends([track_info.get(key) for key, _ in songs])
        result = score_release(meta, points, trend, today)
        latest = points[-1]
        items.append(
            {
                **meta,
                "note": notes.get(rid, ""),
                "songs": [f"{e['artist']} – {e['title']}" for _, e in songs],
                "trend": {**trend, "sources": sorted(trend["sources"])} if trend else None,
                "lowest_price": latest["price"],
                "currency": latest["currency"] or cfg["currency"],
                "num_for_sale": latest["for_sale"],
                "have": latest["have"],
                "want": latest["want"],
                "last_seen": latest["date"],
                **result,
                "history": [
                    {k: p[k] for k in ("date", "price", "for_sale", "want")}
                    for p in points[-HISTORY_POINTS:]
                ],
            }
        )
    items.sort(key=lambda i: i["score"], reverse=True)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "today": today,
        "currency": cfg["currency"],
        "releases": items,
    }
    storage.save_js(paths.site_data, "TRACKER_DATA", data)
    return data


def _merge_trends(infos):
    infos = [i for i in infos if i]
    if not infos:
        return None
    ranks = [i["best_rank"] for i in infos if i["best_rank"] is not None]
    growths = [i["listener_growth"] for i in infos if i["listener_growth"] is not None]
    return {
        "sources": set().union(*(i["sources"] for i in infos)),
        "best_rank": min(ranks) if ranks else None,
        "listener_growth": max(growths) if growths else None,
    }
