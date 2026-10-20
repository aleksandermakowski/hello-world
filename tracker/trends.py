"""Trend sources: songs that are getting attention right now.

TikTok has no public API for trending sounds, so the tracker uses sources that
correlate with it plus a hand-curated seed list (songs you spot on TikTok or in
TikTok Creative Center's "Top Songs" page).
"""

from .http import request_json


def lastfm_top_tracks(api_key, limit=100, fetch=request_json):
    """Global Last.fm chart. Free API key: https://www.last.fm/api/account/create"""
    data, _ = fetch(
        "https://ws.audioscrobbler.com/2.0/",
        params={"method": "chart.gettoptracks", "api_key": api_key, "format": "json", "limit": limit},
    )
    tracks = (data.get("tracks") or {}).get("track") or []
    return [
        {
            "source": "lastfm",
            "rank": i + 1,
            "artist": (t.get("artist") or {}).get("name", ""),
            "title": t.get("name", ""),
            "listeners": int(t.get("listeners") or 0),
            "playcount": int(t.get("playcount") or 0),
        }
        for i, t in enumerate(tracks)
    ]


def deezer_chart(limit=100, fetch=request_json):
    """Global Deezer chart. No key needed."""
    data, _ = fetch("https://api.deezer.com/chart/0/tracks", params={"limit": limit})
    return [
        {
            "source": "deezer",
            "rank": t.get("position") or i + 1,
            "artist": (t.get("artist") or {}).get("name", ""),
            "title": t.get("title", ""),
            "listeners": None,
            "playcount": None,
        }
        for i, t in enumerate(data.get("data") or [])
    ]


def seed_tracks(seeds):
    """Songs from watchlist.json you added by hand (e.g. spotted going viral on TikTok)."""
    return [
        {
            "source": "seed",
            "rank": None,
            "artist": s["artist"],
            "title": s["title"],
            "listeners": None,
            "playcount": None,
        }
        for s in seeds
    ]


def track_key(artist, title):
    return f"{artist.strip().lower()}|{title.strip().lower()}"
