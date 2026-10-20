"""Tiny stdlib HTTP helper with retries, so the tracker needs no third-party packages."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "VinylTrendTracker/0.1 +https://github.com/aleksandermakowski/hello-world"


def build_url(url, params=None):
    if not params:
        return url
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return f"{url}?{query}"


def request_json(url, params=None, headers=None, data=None, retries=3, backoff=5.0):
    """GET (or POST when `data` is given) a URL and return (parsed_json, response_headers)."""
    full_url = build_url(url, params)
    body = None
    all_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        all_headers.update(headers)
    if data is not None:
        body = json.dumps(data).encode()
        all_headers["Content-Type"] = "application/json"

    for attempt in range(retries + 1):
        req = urllib.request.Request(full_url, data=body, headers=all_headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp), resp.headers
        except urllib.error.HTTPError as err:
            retryable = err.code == 429 or err.code >= 500
            if not retryable or attempt == retries:
                raise
        except urllib.error.URLError:
            if attempt == retries:
                raise
        time.sleep(backoff * (2**attempt))
    raise RuntimeError("unreachable")
