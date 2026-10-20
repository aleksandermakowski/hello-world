"""Turn price/supply/demand history into a 0-100 "buy before it moves" score.

The idea: a good buy is a record where demand (Discogs wants, trend charts) is
rising and supply is shrinking, but the price has not caught up yet.
Each component is capped so no single metric can dominate.
"""

from datetime import date, timedelta

# Max points per component (sum = 100 before penalties).
WEIGHTS = {
    "want_growth": 30,  # full points at +10% wants in 30 days
    "supply_drop": 20,  # full points at -30% copies for sale in 30 days
    "want_have": 20,  # full points at want/have ratio >= 3
    "trend": 20,  # currently on a chart / seed list
    "catalog": 10,  # older release (catalog revivals beat new pop pressings)
}
FULL_WANT_GROWTH = 0.10
FULL_SUPPLY_DROP = 0.30
FULL_WANT_HAVE = 3.0
CATALOG_MIN_AGE_YEARS = 5
REISSUE_PENALTY = 5  # reissues can simply be pressed again
# Price already moved: the window may be closing.
PRICE_MOVED_SOFT = 0.25
PRICE_MOVED_HARD = 0.50

BUY_SCORE = 55
WATCH_SCORE = 35


def _clamp(x):
    return max(0.0, min(1.0, x))


def pct_change(new, old):
    if new is None or old in (None, 0):
        return None
    return (new - old) / old


def point_at_or_before(series, day):
    """Latest point on or before `day` (ISO date string), else None."""
    best = None
    for p in series:
        if p["date"] <= day:
            best = p
        else:
            break
    return best


def changes(series, today, days):
    """Percent changes of price / wants / supply vs. `days` ago (falls back to oldest point)."""
    if not series:
        return {"price": None, "want": None, "for_sale": None, "days": 0}
    latest = series[-1]
    cutoff = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    base = point_at_or_before(series, cutoff) or series[0]
    span = (date.fromisoformat(latest["date"]) - date.fromisoformat(base["date"])).days
    return {
        "price": pct_change(latest["price"], base["price"]),
        "want": pct_change(latest["want"], base["want"]),
        "for_sale": pct_change(latest["for_sale"], base["for_sale"]),
        "days": span,
    }


def trend_points(trend):
    """`trend`: {"best_rank": int|None, "sources": [...], "listener_growth": float|None} or None."""
    if not trend or not trend.get("sources"):
        return 0.0
    rank = trend.get("best_rank")
    # Chart rank 1 -> full points, rank 100 -> ~half; seed-only entries get half.
    pts = 0.5 if rank is None else 0.5 + 0.5 * _clamp(1 - (rank - 1) / 100)
    growth = trend.get("listener_growth")
    if growth is not None and growth > 0.05:
        pts = min(1.0, pts + 0.25)
    return pts * WEIGHTS["trend"]


def score_release(meta, series, trend, today):
    month = changes(series, today, 30)
    latest = series[-1] if series else {}
    want, have = latest.get("want"), latest.get("have")
    want_have = (want / have) if want is not None and have else None

    parts = {
        "want_growth": WEIGHTS["want_growth"] * _clamp((month["want"] or 0) / FULL_WANT_GROWTH),
        "supply_drop": WEIGHTS["supply_drop"] * _clamp(-(month["for_sale"] or 0) / FULL_SUPPLY_DROP),
        "want_have": WEIGHTS["want_have"] * _clamp((want_have or 0) / FULL_WANT_HAVE),
        "trend": trend_points(trend),
        "catalog": 0.0,
    }
    year = meta.get("year")
    if year and int(today[:4]) - int(year) >= CATALOG_MIN_AGE_YEARS:
        parts["catalog"] = WEIGHTS["catalog"]

    penalty = REISSUE_PENALTY if meta.get("is_reissue") else 0
    price_move = month["price"] or 0
    if price_move >= PRICE_MOVED_HARD:
        penalty += 15
    elif price_move >= PRICE_MOVED_SOFT:
        penalty += 7

    score = max(0.0, sum(parts.values()) - penalty)

    if price_move >= PRICE_MOVED_SOFT:
        signal = "moved"  # demand may be real, but the cheap window is likely gone
    elif score >= BUY_SCORE and latest.get("price") is not None:
        signal = "buy"
    elif score >= WATCH_SCORE:
        signal = "watch"
    else:
        signal = ""

    return {
        "score": round(score, 1),
        "signal": signal,
        "parts": {k: round(v, 1) for k, v in parts.items()},
        "penalty": penalty,
        "want_have": round(want_have, 2) if want_have is not None else None,
        "change_30d": month,
        "change_7d": changes(series, today, 7),
    }
