import json
import os
import tempfile
import unittest
from datetime import date, timedelta

from tracker import pipeline, storage
from tracker.alerts import format_alert, pending_alerts
from tracker.discogs import Discogs, clean_artist
from tracker.scoring import changes, score_release

RELEASE_JSON = {
    "id": 101,
    "title": "Rumours",
    "artists": [{"name": "Fleetwood Mac"}],
    "year": 1977,
    "country": "US",
    "formats": [{"name": "Vinyl", "qty": "1", "descriptions": ["LP", "Album"]}],
    "master_id": 5,
    "uri": "https://www.discogs.com/release/101-Rumours",
    "images": [{"uri150": "https://img/101.jpg"}],
    "community": {"have": 1000, "want": 900},
    "lowest_price": 20.0,
    "num_for_sale": 50,
}


class FakeDiscogsAPI:
    """Stands in for request_json; market numbers can be changed between 'days'."""

    def __init__(self):
        self.market = {"want": 900, "have": 1000, "price": 20.0, "for_sale": 50}
        self.calls = []

    def __call__(self, url, params=None, headers=None, **_):
        self.calls.append((url, params))
        assert headers["Authorization"] == "Discogs token=t"
        if url.endswith("/database/search"):
            results = [
                {"id": 101, "title": "Fleetwood Mac - Rumours", "year": "1977", "community": {"want": 900, "have": 1000}},
                {"id": 102, "title": "Fleetwood Mac - Rumours", "year": "2011", "community": {"want": 10, "have": 400}},
            ]
            return {"results": results}, {"X-Discogs-Ratelimit-Remaining": "50"}
        data = json.loads(json.dumps(RELEASE_JSON))
        data["community"] = {"have": self.market["have"], "want": self.market["want"]}
        data["lowest_price"] = self.market["price"]
        data["num_for_sale"] = self.market["for_sale"]
        return data, {"X-Discogs-Ratelimit-Remaining": "50"}


def series(*points):
    start = date(2026, 1, 1)
    return [
        {"date": (start + timedelta(days=d)).isoformat(), "price": p, "for_sale": s, "want": w, "have": 1000, "currency": "USD"}
        for d, p, s, w in points
    ]


class DiscogsTest(unittest.TestCase):
    def test_release_is_normalized(self):
        api = FakeDiscogsAPI()
        info = Discogs("t", min_interval=0, fetch=api).release(101)
        self.assertEqual(info["artist"], "Fleetwood Mac")
        self.assertEqual(info["formats"], "Vinyl, LP, Album")
        self.assertFalse(info["is_reissue"])
        self.assertEqual((info["want"], info["have"], info["num_for_sale"]), (900, 1000, 50))
        self.assertEqual(api.calls[0][1], {"curr_abbr": "USD"})

    def test_clean_artist_strips_disambiguation(self):
        self.assertEqual(clean_artist("Nirvana (2)"), "Nirvana")

    def test_requires_token(self):
        with self.assertRaises(ValueError):
            Discogs("")


class ScoringTest(unittest.TestCase):
    def test_changes_use_point_from_window_start(self):
        s = series((0, 20, 50, 1000), (20, 20, 45, 1050), (30, 22, 40, 1100))
        c = changes(s, "2026-01-31", 30)
        self.assertAlmostEqual(c["want"], 0.10)
        self.assertAlmostEqual(c["for_sale"], -0.20)
        self.assertAlmostEqual(c["price"], 0.10)

    def test_rising_demand_flat_price_is_buy(self):
        s = series((0, 20, 50, 2000), (30, 21, 30, 2300))  # wants +15%, supply -40%, price +5%
        result = score_release({"year": 1977}, s, {"sources": {"deezer"}, "best_rank": 5, "listener_growth": None}, "2026-01-31")
        self.assertEqual(result["signal"], "buy")
        self.assertGreaterEqual(result["score"], 80)

    def test_price_already_moved(self):
        s = series((0, 20, 50, 2000), (30, 40, 30, 2300))  # price doubled
        result = score_release({"year": 1977}, s, None, "2026-01-31")
        self.assertEqual(result["signal"], "moved")

    def test_quiet_new_release_scores_low(self):
        s = series((0, 25, 300, 100), (30, 25, 300, 100))
        result = score_release({"year": 2025, "is_reissue": True}, s, None, "2026-01-31")
        self.assertEqual(result["signal"], "")
        self.assertLess(result["score"], 10)


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        with open(os.path.join(root, "watchlist.json"), "w") as f:
            json.dump({"seeds": [{"artist": "Fleetwood Mac", "title": "Dreams"}], "releases": [{"id": 101, "note": "mine"}]}, f)
        self.paths = pipeline.Paths(root)
        self.cfg = pipeline.load_config(self.paths)
        self.api = FakeDiscogsAPI()
        self.client = Discogs("t", min_interval=0, fetch=self.api)

    def tearDown(self):
        self.tmp.cleanup()

    def run_day(self, day, chart):
        items = pipeline.collect_trends(self.cfg, self.paths, day, sources=[("deezer", lambda: chart)], log=lambda *_: None)
        discovered = pipeline.discover(self.cfg, self.paths, self.client, items, day, log=lambda *_: None)
        ids = pipeline.tracked_release_ids(self.cfg, discovered, day)
        pipeline.snapshot(self.cfg, self.paths, self.client, ids, day, log=lambda *_: None)
        return pipeline.build_site_data(self.cfg, self.paths, day)

    def test_end_to_end_over_a_month(self):
        chart = [{"source": "deezer", "rank": 3, "artist": "Fleetwood Mac", "title": "Dreams", "listeners": None, "playcount": None}]
        self.run_day("2026-01-01", chart)
        # A month later: wants up, supply down, price flat -> buy signal.
        self.api.market.update(want=1000, for_sale=30, price=21.0)
        data = self.run_day("2026-01-31", chart)

        self.assertEqual([r["id"] for r in data["releases"]], [101])  # 102 filtered by min_want
        item = data["releases"][0]
        self.assertEqual(item["signal"], "buy")
        self.assertEqual(item["note"], "mine")
        self.assertEqual(item["songs"], ["Fleetwood Mac – Dreams"])
        self.assertEqual(item["trend"]["sources"], ["deezer", "seed"])
        self.assertEqual(len(item["history"]), 2)

        searches = [c for c in self.api.calls if c[0].endswith("/database/search")]
        self.assertEqual(len(searches), 1)  # second day reuses the cached search
        self.assertEqual(len(storage.read_csv(self.paths.snapshots)), 2)

        self.assertEqual(len(pending_alerts(data["releases"], {}, "2026-01-31")), 1)
        self.assertEqual(pending_alerts(data["releases"], {"101": "2026-01-30"}, "2026-01-31"), [])
        self.assertIn("Fleetwood Mac – Rumours", format_alert(item))

    def test_rerun_same_day_is_idempotent(self):
        self.run_day("2026-01-01", [])
        self.run_day("2026-01-01", [])
        self.assertEqual(len(storage.read_csv(self.paths.snapshots)), 1)
        self.assertEqual(len(storage.read_csv(self.paths.trends)), 1)

    def test_failing_trend_source_is_skipped(self):
        def broken():
            raise OSError("down")

        items = pipeline.collect_trends(self.cfg, self.paths, "2026-01-01", sources=[("deezer", broken)], log=lambda *_: None)
        self.assertEqual([i["source"] for i in items], ["seed"])


if __name__ == "__main__":
    unittest.main()
