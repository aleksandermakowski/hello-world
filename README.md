# Vinyl Trend Tracker

Finds vinyl (and optionally CD) pressings of songs that are trending on charts or
TikTok, then follows their Discogs market every day to spot records whose
**demand is rising and supply is shrinking before the price moves**.

It runs on GitHub Actions once a day, commits its history to `data/`, and posts its
results privately: a ranked table on each workflow run's summary page and a
downloadable dashboard. Optional Telegram alerts are sent to your phone.

## How it works

```
trend sources ──► discover pressings ──► daily Discogs snapshot ──► score ──► dashboard + alerts
(seeds, Deezer,    (Discogs search,       (lowest price, copies     (0–100,     (run summary,
 Last.fm charts)    most-wanted N)         for sale, have, want)     signal)     Telegram)
```

1. **Trends.** TikTok has no public API for trending sounds, so the tracker combines:
   - `seeds` in `watchlist.json`: songs you add by hand, for example from
     [TikTok Creative Center → Top Songs](https://ads.tiktok.com/business/creativecenter/inspiration/popular/music/).
   - The Deezer global chart (no key needed).
   - The Last.fm global chart (optional, free API key). It also stores listener counts, so listener growth counts toward the score.
2. **Discovery.** For each trending song, the tracker searches Discogs for vinyl
   releases containing the track. It keeps the 3 most-wanted pressings, skipping
   ones with fewer than 25 wants. Searches are cached and refreshed every 30 days.
   Songs that leave every chart stop being tracked after 60 days.
3. **Snapshot.** For every tracked pressing, plus any release IDs you pin in
   `watchlist.json`, it records the lowest price, copies for sale, haves and wants
   in `data/snapshots.csv`. Discogs's API has no sales history, so this file
   becomes your history. The longer it runs, the better the signals get.
4. **Score** (`tracker/scoring.py`), 0–100:

   | Component | Max | Full points when |
   |---|---|---|
   | Want growth (30d) | 30 | wants +10% |
   | Supply drop (30d) | 20 | copies for sale −30% |
   | Want/have ratio | 20 | ratio ≥ 3 |
   | Trending now | 20 | top of a chart this week (seed-only = half) |
   | Catalog release | 10 | released ≥ 5 years ago |

   Penalties: −5 for reissues/represses (they can simply be pressed again), and −7
   or −15 if the price is already up 25% or 50% over 30 days.
   Signals: **Buy** (score ≥ 55, price not yet up 25%), **Watch** (≥ 35),
   **Already moved** (price up ≥ 25% in 30 days).

## Setup

1. **Discogs token (required).** Go to https://www.discogs.com/settings/developers →
   *Generate new token*. In this repo, go to **Settings → Secrets and variables → Actions → New
   repository secret** and add it as `DISCOGS_TOKEN`.
2. **Optional secrets:**
   - `LASTFM_API_KEY`: get one from https://www.last.fm/api/account/create
   - `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`: create a bot with @BotFather to get
     "Buy" alerts on your phone. Each release alerts at most once every 14 days.
3. **Merge to the default branch.** Scheduled workflows only run there. Then go to
   **Actions → Track vinyl prices → Run workflow** to start the first run now.

## Seeing the results (privately)

- **Run summary:** open the latest run under **Actions → Track vinyl prices** to see the top-25 table.
  Only people with access to the repo can see it.
- **Full dashboard:** on the same page, download the `dashboard` artifact, unzip it and
  open `index.html` in your browser. It works offline and includes charts.
- **Phone:** Telegram alerts (see the optional secrets above).

A GitHub Pages site is **public even when the repo is private**, so Pages is off by
default. To publish the dashboard anyway, set **Settings → Pages → Source: GitHub
Actions** and add the repository variable `ENABLE_PAGES` = `true`
(**Settings → Secrets and variables → Actions → Variables**).

The first day only has one data point, so scores rely on want/have, trends and
catalog age. Growth and supply signals start showing after a few days and are
meaningful after about a month.

## Customising `watchlist.json`

```json
{
  "currency": "EUR",
  "formats": ["Vinyl", "CD"],
  "releases": [{"id": 249504, "note": "original UK pressing I'm eyeing"}],
  "seeds": [{"artist": "Mazzy Star", "title": "Fade Into You", "note": "seen on TikTok"}]
}
```

- `releases` pins specific pressings by their Discogs release ID (the number in
  `discogs.com/release/<id>`). Pinned releases are always tracked. Track pressings,
  not albums: an original pressing and a 2020 reissue are different markets.
- Adding `"CD"` to `formats` doubles the number of searches.
- `discovery` controls the limits: pressings per song, minimum wants, search budget
  per run, and refresh/drop windows.

## Run locally

Python 3.10+ only, no dependencies.

```sh
DISCOGS_TOKEN=... python -m tracker run   # full run
python -m tracker build                   # rebuild site/data.js from data/ (offline)
open site/index.html                      # or just double-click it
python -m unittest discover -s tests      # tests
```

## Caveats

- **Viral songs often trigger reissues**, and a reissue can drop the price of
  existing copies. Check for announced represses before you buy.
- Discogs fees and shipping take 10–20% or more, so cheap records rarely leave margin.
- Charts are only a proxy for TikTok. Your hand-picked seeds are the strongest
  TikTok signal.
- This is a research tool, not financial advice.
