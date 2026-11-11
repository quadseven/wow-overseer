"""The eye read names the age of the newest frame behind every watched tile.

Tested at the API seam: GET /api/eye's handler is called with the capture
state set up the way the two reporting routes leave it (the frame-ingest
store, and the cutter poll's per-view sighting), and the `tiles` section of
the payload is read back. Expected values are literals.
"""

import pathlib
import sys
import unittest
from datetime import datetime
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules
from sandbox_caps import LOCALHOST, NO_LOCALHOST

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import eye
    import family
    import map_server
    from clip_fakes import clip_row
    from cutter_fakes import CutterLedger, serving_cutter

CLOCK = 1_000_000.0
EMPTY_READ = {
    "snapshot_rows": [],
    "family_rows": [],
    "realm_rows": [],
    "guild_rows": [],
    "now": datetime(2026, 11, 9, 12, 0, 0),
}


class EyeTiles(unittest.TestCase):
    def setUp(self):
        for store in (map_server._FRAMES, map_server._VIEW_SEEN):
            saved = dict(store)
            store.clear()
            self.addCleanup(lambda s=store, d=saved: (s.clear(), s.update(d)))
        for patch in (
            mock.patch.object(map_server, "FAMILIES"),
            mock.patch.object(family, "_STREAM_PREFIX", "cam"),
            mock.patch.object(family, "_STREAM_BASE", "https://stream.example.test"),
            mock.patch.object(map_server, "_fetch_eye", return_value=EMPTY_READ),
            mock.patch.object(map_server.time, "time", return_value=CLOCK),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        map_server.FAMILIES.families.return_value = {
            "alpha": ["Aldric", "Brenna"],
            "beta": ["Corvin"],
        }

    def tiles(self):
        status, payload = map_server.Handler._eye.__wrapped__({}, None)
        self.assertEqual(status, 200)
        return {t["name"]: t for t in payload["tiles"]}

    def test_a_member_with_a_fresh_frame_shows_its_age_in_seconds(self):
        map_server._FRAMES["Aldric"] = {"frame_at": CLOCK - 7.9, "at": CLOCK - 1}
        self.assertEqual(
            {
                "name": "Aldric",
                "live": True,
                "frame_age_seconds": 7,
                "frame_state": "fresh",
                "frame_source": "frame",
            },
            self.tiles()["Aldric"],
        )

    def test_a_live_tile_whose_newest_frame_is_minutes_old_reads_stale(self):
        map_server._FRAMES["Aldric"] = {"frame_at": CLOCK - 300, "at": CLOCK - 2}
        tile = self.tiles()["Aldric"]
        self.assertTrue(tile["live"])
        self.assertEqual(300, tile["frame_age_seconds"])
        self.assertEqual("stale", tile["frame_state"])

    def test_a_member_with_no_capture_has_an_explicit_no_frame_entry(self):
        tiles = self.tiles()
        self.assertEqual(["Aldric", "Brenna", "Corvin"], sorted(tiles))
        self.assertEqual(
            {
                "name": "Brenna",
                "live": True,
                "frame_age_seconds": None,
                "frame_state": "no_frame",
                "frame_source": None,
            },
            tiles["Brenna"],
        )

    def test_a_failed_capture_with_no_good_frame_is_no_frame(self):
        map_server._FRAMES["Brenna"] = {"frame_at": None, "at": CLOCK - 3}
        self.assertEqual("no_frame", self.tiles()["Brenna"]["frame_state"])

    def test_a_streamed_view_takes_its_clock_from_the_cutter_poll(self):
        map_server._VIEW_SEEN[family.broadcast_path("Corvin")] = CLOCK - 12
        tile = self.tiles()["Corvin"]
        self.assertEqual(12, tile["frame_age_seconds"])
        self.assertEqual("fresh", tile["frame_state"])
        self.assertEqual("recorder_report", tile["frame_source"])

    def test_the_newer_of_the_two_clocks_wins(self):
        map_server._FRAMES["Corvin"] = {"frame_at": CLOCK - 200, "at": CLOCK - 1}
        map_server._VIEW_SEEN[family.broadcast_path("Corvin")] = CLOCK - 5
        tile = self.tiles()["Corvin"]
        self.assertEqual(5, tile["frame_age_seconds"])
        self.assertEqual("recorder_report", tile["frame_source"])

    def test_the_stale_threshold_is_one_named_constant(self):
        edge = eye.STALE_AFTER_SECONDS
        map_server._FRAMES["Aldric"] = {"frame_at": CLOCK - edge, "at": CLOCK}
        map_server._FRAMES["Brenna"] = {"frame_at": CLOCK - edge - 1, "at": CLOCK}
        tiles = self.tiles()
        self.assertEqual("fresh", tiles["Aldric"]["frame_state"])
        self.assertEqual("stale", tiles["Brenna"]["frame_state"])

    def test_the_watched_set_is_the_watch_walls(self):
        with mock.patch.object(family, "_STREAMED", frozenset({"Aldric"})):
            self.assertEqual(["Aldric"], sorted(self.tiles()))


@unittest.skipUnless(LOCALHOST, NO_LOCALHOST)
class CutterPollRecordsSightings(unittest.TestCase):
    def setUp(self):
        saved = dict(map_server._VIEW_SEEN)
        map_server._VIEW_SEEN.clear()
        self.addCleanup(
            lambda: (map_server._VIEW_SEEN.clear(), map_server._VIEW_SEEN.update(saved))
        )

    def poll(self, query, clips_dir):
        with serving_cutter(CutterLedger([clip_row()]), clips_dir) as c:
            with mock.patch.object(map_server.time, "time", return_value=CLOCK):
                return c.get("/api/clips/pending" + query)[0]

    def test_a_served_poll_stamps_every_path_it_names(self):
        import tempfile

        with tempfile.TemporaryDirectory() as clips:
            self.assertEqual(200, self.poll("?paths=cama,camb", clips))
        self.assertEqual({"cama": CLOCK, "camb": CLOCK}, map_server._VIEW_SEEN)

    def test_a_refused_poll_stamps_nothing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as clips:
            self.assertEqual(400, self.poll("?paths=a%27%3B--", clips))
        self.assertEqual({}, map_server._VIEW_SEEN)


if __name__ == "__main__":
    unittest.main()
