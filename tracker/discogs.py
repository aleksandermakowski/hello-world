"""Discogs API client: release stats (price, supply, have/want) and vinyl/CD search.

Docs: https://www.discogs.com/developers
Authenticated requests are limited to 60/minute, so calls are spaced out.
"""

import re
import time

from .http import request_json

API = "https://api.discogs.com"
_NAME_SUFFIX = re.compile(r"\s\(\d+\)$")  # Discogs disambiguates artists as "Name (2)"


def clean_artist(name):
    return _NAME_SUFFIX.sub("", name or "").strip()


class Discogs:
    def __init__(self, token, currency="USD", min_interval=1.1, fetch=request_json):
        if not token:
            raise ValueError("DISCOGS_TOKEN is required (create one at discogs.com/settings/developers)")
        self.token = token
        self.currency = currency
        self.min_interval = min_interval
        self._fetch = fetch
        self._last_call = 0.0

    def _get(self, path, **params):
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        data, headers = self._fetch(
            API + path, params=params, headers={"Authorization": f"Discogs token={self.token}"}
        )
        self._last_call = time.monotonic()
        remaining = headers.get("X-Discogs-Ratelimit-Remaining") if headers else None
        if remaining is not None and int(remaining) <= 2:
            time.sleep(60)
        return data

    def release(self, release_id):
        """Current market + community stats for one specific pressing."""
        data = self._get(f"/releases/{release_id}", curr_abbr=self.currency)
        formats = []
        for fmt in data.get("formats") or []:
            formats.append(", ".join([fmt.get("name", "")] + list(fmt.get("descriptions") or [])))
        format_text = "; ".join(formats)
        community = data.get("community") or {}
        images = data.get("images") or []
        return {
            "id": data["id"],
            "title": data.get("title", ""),
            "artist": " / ".join(clean_artist(a.get("name")) for a in data.get("artists") or []),
            "year": data.get("year") or None,
            "country": data.get("country", ""),
            "formats": format_text,
            "is_reissue": bool(re.search(r"\b(Reissue|Repress)\b", format_text)),
            "master_id": data.get("master_id"),
            "url": data.get("uri", f"https://www.discogs.com/release/{release_id}"),
            "thumb": (images[0].get("uri150") if images else None) or data.get("thumb"),
            "lowest_price": data.get("lowest_price"),
            "num_for_sale": data.get("num_for_sale"),
            "have": community.get("have"),
            "want": community.get("want"),
        }

    def search_releases(self, artist, track, fmt="Vinyl", per_page=15):
        """Releases of a given format that contain the track. Each result has community have/want."""
        data = self._get(
            "/database/search",
            type="release",
            artist=artist,
            track=track,
            format=fmt,
            per_page=per_page,
        )
        results = []
        for item in data.get("results") or []:
            community = item.get("community") or {}
            results.append(
                {
                    "id": item["id"],
                    "title": item.get("title", ""),
                    "year": int(item["year"]) if str(item.get("year", "")).isdigit() else None,
                    "want": community.get("want", 0),
                    "have": community.get("have", 0),
                }
            )
        return results
