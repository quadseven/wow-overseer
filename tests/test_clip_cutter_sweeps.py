"""The pure rules of the cutter API and the two sweeps it adds."""

import io
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import clipcutter
    import clipledger
    import map_server
    from clip_fakes import clip_row
    from cutter_fakes import NOW, CutterLedger


class Rules(unittest.TestCase):
    def test_ftyp_box_is_required_at_byte_four(self):
        self.assertTrue(clipcutter.is_mp4(b"\x00\x00\x00\x18ftypisom"))
        self.assertFalse(clipcutter.is_mp4(b"\x00\x00\x00\x18moovisom"))
        self.assertFalse(clipcutter.is_mp4(b"ftyp"))
        self.assertFalse(clipcutter.is_mp4(b""))

    def test_the_name_comes_from_the_row(self):
        self.assertEqual(clipcutter.file_name(7, "boss_kill"), "clip-7-boss_kill.mp4")

    def test_a_kind_that_is_not_a_plain_word_gets_no_name(self):
        self.assertIsNone(clipcutter.file_name(7, "../x"))

    def test_ids_are_ascii_digits_only(self):
        self.assertEqual(clipcutter.parse_id("12"), 12)
        for bad in ("", "x", "-1", "1.5", "²", "0", "9" * 30):
            self.assertIsNone(clipcutter.parse_id(bad), bad)

    def test_a_note_is_one_short_clean_line(self):
        self.assertEqual(clipcutter.clean_note("  a \n b\t"), "a b")
        self.assertEqual(len(clipcutter.clean_note("x" * 999)), clipcutter.MAX_NOTE)
        self.assertEqual(clipcutter.clean_note("café"), "caf?")


class TimeoutIsTenMinutes(unittest.TestCase):
    def test_cutting_over_ten_minutes_is_failed_with_the_reason(self):
        stale = [
            {
                "id": 1,
                "state": "cutting",
                "window_end": NOW,
                "updated_at": NOW - timedelta(minutes=10, seconds=1),
            }
        ]
        (change,) = clipledger.stale_changes(stale, now=NOW)
        self.assertEqual(change["to"], "failed")
        self.assertEqual(change["detail"], "cutter went silent")

    def test_cutting_at_exactly_ten_minutes_waits(self):
        fresh = [
            {
                "id": 1,
                "state": "cutting",
                "window_end": NOW,
                "updated_at": NOW - timedelta(minutes=10),
            }
        ]
        self.assertEqual(clipledger.stale_changes(fresh, now=NOW), [])


class ExpiredFiles(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def sweep(self, rows):
        self.ledger = CutterLedger(rows)
        return clipledger.delete_expired(self.ledger, self.dir)

    def test_an_expired_row_loses_its_file_and_becomes_deleted(self):
        path = pathlib.Path(self.dir) / "clip-1-loot.mp4"
        path.write_bytes(b"x")
        count = self.sweep([clip_row(state="expired", detail="kept")])
        self.assertEqual(count, 1)
        self.assertFalse(path.exists())
        self.assertEqual(self.ledger.rows[0]["state"], "deleted")
        self.assertEqual(self.ledger.rows[0]["detail"], "kept")

    def test_a_missing_file_still_becomes_deleted_with_a_note(self):
        self.sweep([clip_row(state="expired", detail="kept")])
        self.assertEqual(self.ledger.rows[0]["state"], "deleted")
        self.assertEqual(
            self.ledger.rows[0]["detail"], "kept; file was already missing"
        )

    def test_a_stored_name_that_is_a_path_removes_nothing_outside(self):
        outside = pathlib.Path(self.dir).parent / "keep-me.txt"
        outside.write_bytes(b"x")
        self.addCleanup(outside.unlink)
        self.sweep([clip_row(state="expired", file_name="../keep-me.txt")])
        self.assertTrue(outside.exists())
        self.assertEqual(self.ledger.rows[0]["state"], "deleted")

    def test_other_states_are_left_alone(self):
        path = pathlib.Path(self.dir) / "clip-1-loot.mp4"
        path.write_bytes(b"x")
        self.assertEqual(self.sweep([clip_row(state="ready")]), 0)
        self.assertTrue(path.exists())

    def test_a_row_that_moved_on_is_not_counted(self):
        path = pathlib.Path(self.dir) / "clip-1-loot.mp4"
        path.write_bytes(b"x")
        self.ledger = CutterLedger([clip_row(state="expired")])
        self.ledger.race = "ready"
        self.assertEqual(clipledger.delete_expired(self.ledger, self.dir), 0)


class TheTick(unittest.TestCase):
    def test_the_sweep_runs_with_no_roster_and_no_stream(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name) / "clip-1-loot.mp4"
        path.write_bytes(b"x")
        ledger = CutterLedger([clip_row(state="expired")])
        stale = clip_row(
            id=2,
            state="cutting",
            file_name=None,
            updated_at=NOW - timedelta(minutes=30),
            window_end=NOW,
        )
        ledger.rows.append(stale)
        with (
            mock.patch.object(map_server, "_connect", ledger.connect),
            mock.patch.object(map_server, "CLIPS_DIR", tmp.name),
        ):
            result = map_server.sweep_clips()
        self.assertFalse(path.exists())
        self.assertEqual(ledger.rows[0]["state"], "deleted")
        self.assertEqual(ledger.rows[1]["state"], "failed")
        self.assertEqual(result["deleted"], 1)

    def test_no_directory_deletes_nothing_and_marks_nothing(self):
        ledger = CutterLedger([clip_row(state="expired")])
        with (
            mock.patch.object(map_server, "_connect", ledger.connect),
            mock.patch.object(map_server, "CLIPS_DIR", ""),
        ):
            map_server.sweep_clips()
        self.assertEqual(ledger.rows[0]["state"], "expired")

    def test_the_sweep_runs_even_when_the_scan_fails(self):
        with (
            mock.patch.object(map_server, "scan_clips", side_effect=RuntimeError("x")),
            mock.patch.object(map_server, "sweep_clips") as sweep,
        ):
            with self.assertRaises(RuntimeError):
                map_server.clip_tick()
        sweep.assert_called_once()


class Upload(unittest.TestCase):
    def test_the_stream_is_read_in_bounded_chunks(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        body = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 200000

        class Counting(io.BytesIO):
            biggest = 0

            def read(self, n=-1):
                Counting.biggest = max(Counting.biggest, n)
                return super().read(n)

        ledger = CutterLedger([clip_row(state="cutting")])
        code, _p = clipcutter.upload(
            ledger, "1", Counting(body), len(body), tmp.name, ""
        )
        self.assertEqual(code, 200)
        self.assertLessEqual(Counting.biggest, clipcutter.CHUNK)
        self.assertEqual(os.listdir(tmp.name), ["clip-1-loot.mp4"])

    def test_a_short_body_leaves_no_file(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        body = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 100
        ledger = CutterLedger([clip_row(state="cutting")])
        code, payload = clipcutter.upload(
            ledger, "1", io.BytesIO(body), len(body) + 500, tmp.name, ""
        )
        self.assertEqual(code, 400)
        self.assertIn("error", payload)
        self.assertEqual(os.listdir(tmp.name), [])
        self.assertEqual(ledger.rows[0]["state"], "cutting")


if __name__ == "__main__":
    unittest.main()
