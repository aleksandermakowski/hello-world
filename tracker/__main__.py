"""CLI.

    python -m tracker run     # full daily run (needs DISCOGS_TOKEN)
    python -m tracker build   # rebuild site/data.json from stored data only (no network)
"""

import argparse
import os
import sys
from datetime import date

from . import pipeline
from .alerts import send_alerts
from .discogs import Discogs


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tracker")
    parser.add_argument("command", choices=["run", "build"])
    parser.add_argument("--root", default=os.getcwd(), help="repo root (contains watchlist.json)")
    args = parser.parse_args(argv)

    paths = pipeline.Paths(args.root)
    cfg = pipeline.load_config(paths)
    today = date.today().isoformat()

    if args.command == "run":
        token = os.environ.get("DISCOGS_TOKEN")
        if not token:
            print("DISCOGS_TOKEN is not set; see README.md", file=sys.stderr)
            return 1
        client = Discogs(token, currency=cfg["currency"])
        items = pipeline.collect_trends(cfg, paths, today, lastfm_key=os.environ.get("LASTFM_API_KEY"))
        discovered = pipeline.discover(cfg, paths, client, items, today)
        ids = pipeline.tracked_release_ids(cfg, discovered, today)
        pipeline.snapshot(cfg, paths, client, ids, today)

    data = pipeline.build_site_data(cfg, paths, today)
    print(f"site: {len(data['releases'])} releases scored")

    if args.command == "run":
        send_alerts(
            data["releases"],
            paths.alerts,
            today,
            os.environ.get("TELEGRAM_BOT_TOKEN"),
            os.environ.get("TELEGRAM_CHAT_ID"),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
