"""The eye read names the age of the newest frame behind every watched tile.

Tested at the API seam: GET /api/eye's handler is called with the capture
state set up the way the two reporting routes leave it (the frame-ingest
store, and the cutter poll's per-view sighting), and the `tiles` section of
the payload is read back. Expected values are literals.
"""

import json
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
        for store in (
            map_server._FRAMES,
            map_server._VIEW_SEEN,
            map_server._VIEW_SEGMENT,
        ):
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

    def test_a_segment_age_is_the_streamed_views_frame_clock(self):
        # #2254: the poll was 2 seconds ago, the newest segment 9 seconds
        # before that. The tile follows the segment, not the poll.
        path = family.broadcast_path("Corvin")
        map_server._VIEW_SEEN[path] = CLOCK - 2
        map_server._VIEW_SEGMENT[path] = CLOCK - 11
        tile = self.tiles()["Corvin"]
        self.assertEqual(11, tile["frame_age_seconds"])
        self.assertEqual("fresh", tile["frame_state"])
        self.assertEqual("segment", tile["frame_source"])

    def test_a_running_recorder_with_an_old_segment_reads_stale(self):
        path = family.broadcast_path("Corvin")
        map_server._VIEW_SEEN[path] = CLOCK - 1
        map_server._VIEW_SEGMENT[path] = CLOCK - 181
        tile = self.tiles()["Corvin"]
        self.assertEqual(181, tile["frame_age_seconds"])
        self.assertEqual("stale", tile["frame_state"])
        self.assertEqual("segment", tile["frame_source"])

    def test_a_newer_ingested_frame_still_beats_the_segment(self):
        path = family.broadcast_path("Corvin")
        map_server._FRAMES["Corvin"] = {"frame_at": CLOCK - 4, "at": CLOCK - 1}
        map_server._VIEW_SEEN[path] = CLOCK - 1
        map_server._VIEW_SEGMENT[path] = CLOCK - 90
        tile = self.tiles()["Corvin"]
        self.assertEqual(4, tile["frame_age_seconds"])
        self.assertEqual("frame", tile["frame_source"])

    def test_a_segment_clock_for_another_view_changes_nothing(self):
        map_server._VIEW_SEEN[family.broadcast_path("Corvin")] = CLOCK - 12
        map_server._VIEW_SEGMENT[family.broadcast_path("Aldric")] = CLOCK - 300
        tile = self.tiles()["Corvin"]
        self.assertEqual(12, tile["frame_age_seconds"])
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
        for store in (map_server._VIEW_SEEN, map_server._VIEW_SEGMENT):
            saved = dict(store)
            store.clear()
            self.addCleanup(lambda s=store, d=saved: (s.clear(), s.update(d)))

    def poll(self, query, clips_dir, clock=CLOCK):
        return self.answer(query, clips_dir, clock)[0]

    def answer(self, query, clips_dir, clock=CLOCK):
        with serving_cutter(CutterLedger([clip_row()]), clips_dir) as c:
            with mock.patch.object(map_server.time, "time", return_value=clock):
                return c.get("/api/clips/pending" + query)

    def test_a_poll_with_a_segment_age_stamps_the_segment_clock(self):
        import tempfile

        with tempfile.TemporaryDirectory() as clips:
            self.assertEqual(200, self.poll("?paths=cama,camb&ages=cama:7", clips))
        self.assertEqual({"cama": CLOCK, "camb": CLOCK}, map_server._VIEW_SEEN)
        self.assertEqual({"cama": CLOCK - 7}, map_server._VIEW_SEGMENT)

    def test_a_later_poll_with_no_age_for_a_view_drops_its_segment_clock(self):
        # An older capture side, or a recorder that stopped saying: the view
        # goes back to the recorder report, it does not keep a frozen segment.
        import tempfile

        with tempfile.TemporaryDirectory() as clips:
            self.assertEqual(
                200, self.poll("?paths=cama,camb&ages=cama:7,camb:0", clips)
            )
            self.assertEqual(
                200, self.poll("?paths=cama,camb&ages=camb:3", clips, CLOCK + 5)
            )
        self.assertEqual({"camb": CLOCK + 2}, map_server._VIEW_SEGMENT)
        self.assertEqual({"cama": CLOCK + 5, "camb": CLOCK + 5}, map_server._VIEW_SEEN)

    def test_a_malformed_or_negative_age_is_refused_and_stamps_nothing(self):
        import tempfile

        bad = (
            "cama:-3",
            "cama:soon",
            "cama:1.5",
            "cama",
            "cama:",
            ":4",
            "cama:4,cama:5",
            "camz:4",
            "cama:99999999999",
            "cama:4,,camb:1",
        )
        with tempfile.TemporaryDirectory() as clips:
            for ages in bad:
                status, body = self.answer("?paths=cama,camb&ages=" + ages, clips)
                self.assertEqual(400, status, ages)
                self.assertIn("age", json.loads(body)["error"], ages)
                self.assertEqual({}, map_server._VIEW_SEEN, ages)
                self.assertEqual({}, map_server._VIEW_SEGMENT, ages)

    def test_a_refused_age_leaves_an_earlier_segment_clock_alone(self):
        import tempfile

        with tempfile.TemporaryDirectory() as clips:
            self.assertEqual(200, self.poll("?paths=cama&ages=cama:7", clips))
            self.assertEqual(
                400, self.poll("?paths=cama&ages=cama:-1", clips, CLOCK + 9)
            )
        self.assertEqual({"cama": CLOCK - 7}, map_server._VIEW_SEGMENT)
        self.assertEqual({"cama": CLOCK}, map_server._VIEW_SEEN)

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
