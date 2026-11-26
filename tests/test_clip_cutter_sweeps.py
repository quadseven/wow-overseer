"""The pure rules of the cutter API and the two sweeps it adds."""

import errno
import io
import os
import pathlib
import sys
import tempfile
import threading
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

    def test_an_ordinary_note_comes_back_unchanged(self):
        for plain in (
            "no ring segment covered 21:04:10 to 21:05:02",
            "ffmpeg exit 1; retry | later (2 of 3), 50% done: a-b_c/d?",
            "x" * clipcutter.MAX_NOTE,
        ):
            self.assertEqual(clipcutter.clean_note(plain), plain)


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
        # The clip folder is a child of the test's own directory, so a file
        # written beside it never lands in the shared temp directory.
        clips = pathlib.Path(tmp.name) / "clips"
        clips.mkdir()
        self.dir = str(clips)

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


class PartialUploads(unittest.TestCase):
    """#2251: a pod killed during an upload leaves its .upload-*.part behind."""

    CLOCK = 2_000_000.0

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)

    def aged(self, name, seconds):
        path = self.dir / name
        path.write_bytes(b"x")
        os.utime(path, (self.CLOCK - seconds, self.CLOCK - seconds))
        return path

    def sweep(self):
        return clipcutter.sweep_partials(str(self.dir), now=self.CLOCK)

    def test_a_partial_upload_past_the_bound_is_removed(self):
        old = self.aged(".upload-abc123.part", clipcutter.PART_MAX_AGE + 1)
        self.assertEqual(self.sweep(), 1)
        self.assertFalse(old.exists())

    def test_a_partial_upload_at_the_bound_or_younger_is_kept(self):
        edge = self.aged(".upload-edge.part", clipcutter.PART_MAX_AGE)
        young = self.aged(".upload-young.part", 5)
        self.assertEqual(self.sweep(), 0)
        self.assertTrue(edge.exists())
        self.assertTrue(young.exists())

    def test_the_bound_outlasts_the_longest_upload(self):
        self.assertGreater(clipcutter.PART_MAX_AGE, clipcutter.UPLOAD_SECONDS)

    def test_a_finished_clip_is_never_removed_however_old(self):
        year = 365 * 24 * 3600
        kept = [
            self.aged("clip-1-loot.mp4", year),
            self.aged("clip-2-boss_kill.mp4.part", year),
            self.aged(".upload-not-a-part.mp4", year),
            self.aged("upload-abc.part", year),
            self.aged(".hidden", year),
        ]
        self.assertEqual(self.sweep(), 0)
        for path in kept:
            self.assertTrue(path.exists(), path.name)

    def test_a_folder_or_a_link_with_the_partial_name_is_left_alone(self):
        folder = self.dir / ".upload-dir.part"
        folder.mkdir()
        target = self.aged("clip-9-loot.mp4", 10)
        link = self.dir / ".upload-link.part"
        link.symlink_to(target)
        old = clipcutter.PART_MAX_AGE + 100
        os.utime(folder, (self.CLOCK - old, self.CLOCK - old))
        self.assertEqual(self.sweep(), 0)
        self.assertTrue(folder.is_dir())
        self.assertTrue(link.is_symlink())
        self.assertTrue(target.exists())

    def test_the_upload_writes_the_name_the_sweep_looks_for(self):
        made = []
        real = tempfile.mkstemp

        def spy(**kw):
            made.append(kw)
            return real(**kw)

        body = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 64
        ledger = CutterLedger([clip_row(state="cutting", file_name=None)])
        with mock.patch.object(clipcutter.tempfile, "mkstemp", spy):
            code, _p = clipcutter.upload(
                lambda: ledger, "1", io.BytesIO(body), len(body), str(self.dir), ""
            )
        self.assertEqual(code, 200)
        self.assertEqual(made[0]["prefix"], clipcutter.PART_PREFIX)
        self.assertEqual(made[0]["suffix"], clipcutter.PART_SUFFIX)

    def test_a_missing_folder_removes_nothing_and_does_not_raise(self):
        self.assertEqual(clipcutter.sweep_partials(str(self.dir / "gone")), 0)

    def test_the_tick_sweep_removes_partials_and_counts_them(self):
        old = self.dir / ".upload-dead.part"
        old.write_bytes(b"x")
        long_ago = clipcutter.PART_MAX_AGE + 60
        os.utime(old, (old.stat().st_mtime - long_ago,) * 2)
        ledger = CutterLedger([])
        with (
            mock.patch.object(map_server, "_connect", ledger.connect),
            mock.patch.object(map_server, "CLIPS_DIR", str(self.dir)),
        ):
            result = map_server.sweep_clips()
        self.assertFalse(old.exists())
        self.assertEqual(result["partial"], 1)

    def test_partials_are_swept_even_when_the_database_is_down(self):
        old = self.dir / ".upload-dead.part"
        old.write_bytes(b"x")
        long_ago = clipcutter.PART_MAX_AGE + 60
        os.utime(old, (old.stat().st_mtime - long_ago,) * 2)

        def down():
            raise OSError("database is down")

        with (
            mock.patch.object(map_server, "_connect", down),
            mock.patch.object(map_server, "CLIPS_DIR", str(self.dir)),
        ):
            with self.assertRaises(OSError):
                map_server.sweep_clips()
        self.assertFalse(old.exists())


class TheTickLine(unittest.TestCase):
    """#2251: a tick that did something logs one line; a quiet one logs none."""

    QUIET_SCAN = {"written": 0, "expired": 0, "timed_out": 0}
    QUIET_SWEEP = {"timed_out": 0, "deleted": 0, "partial": 0}

    def tick(self, scan, swept):
        with (
            mock.patch.object(map_server, "scan_clips", return_value=scan),
            mock.patch.object(map_server, "sweep_clips", return_value=swept),
        ):
            return map_server.clip_tick()

    def test_the_line_carries_every_count(self):
        self.assertEqual(
            clipledger.tick_line(
                {"written": 2, "expired": 1, "timed_out": 1},
                {"timed_out": 2, "deleted": 4, "partial": 5},
            ),
            "clip scan: planned 2, expired 1, timed out 3, files deleted 4, "
            "partial uploads removed 5",
        )

    def test_a_tick_that_planned_logs_the_line_once(self):
        scan = {"written": 1, "expired": 0, "timed_out": 0}
        with self.assertLogs(map_server.log, level="INFO") as seen:
            self.assertEqual(self.tick(scan, self.QUIET_SWEEP), scan)
        self.assertEqual(
            [r.getMessage() for r in seen.records],
            [
                "clip scan: planned 1, expired 0, timed out 0, files deleted 0, "
                "partial uploads removed 0"
            ],
        )

    def test_each_count_alone_is_enough_for_a_line(self):
        for scan, swept in (
            ({"written": 0, "expired": 1, "timed_out": 0}, self.QUIET_SWEEP),
            ({"written": 0, "expired": 0, "timed_out": 1}, self.QUIET_SWEEP),
            (self.QUIET_SCAN, {"timed_out": 1, "deleted": 0, "partial": 0}),
            (self.QUIET_SCAN, {"timed_out": 0, "deleted": 1, "partial": 0}),
            (self.QUIET_SCAN, {"timed_out": 0, "deleted": 0, "partial": 1}),
        ):
            self.assertTrue(clipledger.tick_line(scan, swept), (scan, swept))

    def test_a_quiet_tick_logs_nothing(self):
        self.assertEqual(clipledger.tick_line(self.QUIET_SCAN, self.QUIET_SWEEP), "")
        # The scan with no roster answers without a timed_out count.
        self.assertEqual(
            clipledger.tick_line({"written": 0, "expired": 0}, self.QUIET_SWEEP), ""
        )
        with self.assertNoLogs(map_server.log, level="INFO"):
            self.tick(self.QUIET_SCAN, self.QUIET_SWEEP)

    def test_a_failed_scan_still_reports_what_the_sweep_did(self):
        self.assertEqual(
            clipledger.tick_line(None, {"timed_out": 1, "deleted": 0, "partial": 2}),
            "clip sweep after a failed scan: timed out 1, files deleted 0, "
            "partial uploads removed 2",
        )
        self.assertEqual(clipledger.tick_line(None, self.QUIET_SWEEP), "")
        with (
            mock.patch.object(map_server, "scan_clips", side_effect=RuntimeError("x")),
            mock.patch.object(
                map_server,
                "sweep_clips",
                return_value={"timed_out": 0, "deleted": 3, "partial": 0},
            ),
            self.assertLogs(map_server.log, level="INFO") as seen,
            self.assertRaises(RuntimeError),
        ):
            map_server.clip_tick()
        self.assertEqual(
            [r.getMessage() for r in seen.records],
            [
                "clip sweep after a failed scan: timed out 0, files deleted 3, "
                "partial uploads removed 0"
            ],
        )


class TheTickLineReadsTheRealCounts(unittest.TestCase):
    """#2251: scan_clips and sweep_clips carry `timed_out` as time_out
    answers it, a count per new state. The line once read it as one number,
    so every live tick raised TypeError and logged "clip scan failed"."""

    class NoRows:
        rowcount = 0

        def execute(self, *_a):
            pass

        def fetchall(self):
            return []

    def test_time_out_answers_a_count_per_state(self):
        counts = clipledger.time_out(self.NoRows(), now=NOW)
        self.assertEqual(counts, {"no_view": 0, "failed": 0})

    def test_per_state_counts_add_up_in_the_line(self):
        self.assertEqual(
            clipledger.tick_line(
                {"written": 1, "expired": 0, "timed_out": {"no_view": 1, "failed": 2}},
                {"timed_out": {"no_view": 0, "failed": 1}, "deleted": 0, "partial": 0},
            ),
            "clip scan: planned 1, expired 0, timed out 4, files deleted 0, "
            "partial uploads removed 0",
        )

    def test_a_quiet_tick_in_the_real_shape_logs_nothing_and_raises_nothing(self):
        quiet = clipledger.time_out(self.NoRows(), now=NOW)
        scan = {"written": 0, "expired": 0, "timed_out": quiet}
        swept = {"timed_out": dict(quiet), "deleted": 0, "partial": 0}
        with (
            mock.patch.object(map_server, "scan_clips", return_value=scan),
            mock.patch.object(map_server, "sweep_clips", return_value=swept),
            self.assertNoLogs(map_server.log, level="INFO"),
        ):
            self.assertEqual(map_server.clip_tick(), scan)

    def test_a_sweep_that_timed_out_rows_after_a_failed_scan_is_counted(self):
        self.assertEqual(
            clipledger.tick_line(
                None,
                {"timed_out": {"no_view": 0, "failed": 2}, "deleted": 0, "partial": 0},
            ),
            "clip sweep after a failed scan: timed out 2, files deleted 0, "
            "partial uploads removed 0",
        )


class Upload(unittest.TestCase):
    def test_the_stream_is_read_in_bounded_chunks(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        body = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 200000

        class Counting(io.BytesIO):
            biggest = 0

            def read1(self, n=-1):
                Counting.biggest = max(Counting.biggest, n)
                return super().read1(n)

        ledger = CutterLedger([clip_row(state="cutting", file_name=None)])
        code, _p = clipcutter.upload(
            lambda: ledger, "1", Counting(body), len(body), tmp.name, ""
        )
        self.assertEqual(code, 200)
        self.assertTrue(0 < Counting.biggest <= clipcutter.CHUNK)
        self.assertEqual(os.listdir(tmp.name), ["clip-1-loot.mp4"])


class Conn:
    """A connection factory that counts opens and the connections live now."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.opened = 0
        self.live = 0

    def __call__(self):
        return self

    def __enter__(self):
        self.opened += 1
        self.live += 1
        return self.ledger

    def __exit__(self, *exc):
        self.live -= 1
        return False


class UploadCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.ledger = CutterLedger([clip_row(state="cutting", file_name=None)])
        self.conn = Conn(self.ledger)

    def upload(self, rfile, length, **kw):
        return clipcutter.upload(self.conn, "1", rfile, length, self.dir, "", **kw)


class TheBodyIsReadBeforeTheDatabaseIsOpened(UploadCase):
    def test_no_connection_is_live_while_the_body_is_read(self):
        body = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 200000
        seen = []

        class Watching(io.BytesIO):
            def read1(inner, n=-1):
                seen.append(self.conn.live)
                return super().read1(n)

        code, _p = self.upload(Watching(body), len(body))
        self.assertEqual(code, 200)
        self.assertTrue(seen)
        self.assertEqual(set(seen), {0})
        self.assertEqual(self.conn.opened, 2)  # the pre-check, then the commit

    def test_a_not_mp4_body_leaves_nothing(self):
        code, _p = self.upload(io.BytesIO(b"GIF89a" + b"\x00" * 40), 46)
        self.assertEqual(code, 400)
        self.assertEqual(os.listdir(self.dir), [])

    def test_a_short_body_leaves_no_temp_file(self):
        body = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 100
        code, _p = self.upload(io.BytesIO(body), len(body) + 500)
        self.assertEqual((code, self.conn.opened), (400, 1))
        self.assertEqual(os.listdir(self.dir), [])

    def test_a_stalled_sender_times_out_with_a_4xx_and_no_temp_file(self):
        class Stalls(io.BytesIO):
            def read1(self, n=-1):
                if self.tell() > 100:
                    raise TimeoutError("timed out")
                return super().read1(min(n, 50))

        body = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 5000
        code, payload = self.upload(Stalls(body), len(body))
        self.assertEqual((code, self.conn.opened), (408, 1))
        self.assertIn("error", payload)
        self.assertEqual(os.listdir(self.dir), [])

    def test_a_note_with_a_view_marker_is_refused_before_anything_is_read(self):
        class Never(io.BytesIO):
            def read1(self, n=-1):
                raise AssertionError("the body was read")

        code, payload = clipcutter.upload(
            self.conn, "1", Never(b"x"), 1, self.dir, "view:Other"
        )
        self.assertEqual((code, self.conn.opened), (400, 0))
        self.assertIn("error", payload)


class Trickle:
    """A sender that gives one byte a call and takes a fake second for each."""

    def __init__(self, body, clock):
        self.body, self.at, self.clock = body, 0, clock
        self.reads = 0

    def read1(self, n=-1):
        self.reads += 1
        self.clock.now += 1
        chunk = self.body[self.at : self.at + 1]
        self.at += len(chunk)
        return chunk


class FakeClock:
    now = 0.0

    def __call__(self):
        return self.now


class EveryReadIsBounded(UploadCase):
    def test_a_trickling_sender_is_cut_off_at_the_deadline(self):
        clock = FakeClock()
        body = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 100000
        sender = Trickle(body, clock)
        code, payload = self.upload(sender, len(body), clock=clock)
        self.assertEqual(code, 408)
        self.assertIn("error", payload)
        self.assertLessEqual(clock.now, clipcutter.UPLOAD_SECONDS + 2)
        self.assertLess(sender.reads, 700)
        self.assertEqual(os.listdir(self.dir), [])

    def test_the_socket_timeout_never_outlives_the_deadline(self):
        clock = FakeClock()
        body = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 100000
        timeouts = []

        def bound(seconds):
            timeouts.append((seconds, clipcutter.UPLOAD_SECONDS - clock.now))

        self.upload(Trickle(body, clock), len(body), clock=clock, bound=bound)
        self.assertTrue(timeouts)
        for seconds, remaining in timeouts:
            self.assertGreater(seconds, 0)
            self.assertLessEqual(seconds, clipcutter.IDLE_SECONDS)
            self.assertLessEqual(seconds, remaining + 1e-9)
        self.assertLess(timeouts[-1][0], clipcutter.IDLE_SECONDS)

    def test_an_expired_deadline_before_the_first_read_reads_nothing(self):
        clock = FakeClock()
        ticks = iter([0.0, 10**6, 10**6, 10**6])

        class Never:
            def read1(self, n=-1):
                raise AssertionError("read after the deadline")

        code, _p = self.upload(Never(), 100, clock=lambda: next(ticks))
        self.assertEqual(code, 408)
        self.assertEqual(clock.now, 0.0)


class AnUploadForTheWrongRowReadsNoBody(UploadCase):
    def refused(self, rows, expect):
        self.ledger.rows[:] = rows
        self.conn.opened = 0

        class Never:
            def read1(self, n=-1):
                raise AssertionError("the body was read")

            read = read1

        code, payload = self.upload(Never(), 4096)
        self.assertEqual(code, expect)
        self.assertIn("error", payload)
        self.assertEqual(os.listdir(self.dir), [])
        self.assertEqual(self.conn.live, 0)
        self.assertEqual(self.conn.opened, 1)

    def test_a_pending_row(self):
        self.refused([clip_row(state="pending", file_name=None)], 409)

    def test_a_ready_row_or_a_row_that_already_has_a_file(self):
        self.refused([clip_row(state="ready")], 409)
        self.refused([clip_row(state="cutting")], 409)

    def test_an_unknown_id(self):
        self.refused([clip_row(id=7, state="cutting", file_name=None)], 404)

    def test_a_file_already_on_disk(self):
        with open(os.path.join(self.dir, "clip-1-loot.mp4"), "wb") as f:
            f.write(b"original")
        self.ledger.rows[0]["file_name"] = None
        code, _p = self.upload(io.BytesIO(b"x"), 1)
        self.assertEqual(code, 409)
        self.assertEqual(os.listdir(self.dir), ["clip-1-loot.mp4"])


class ConcurrentUploadsAreCapped(UploadCase):
    def test_a_third_concurrent_upload_is_503(self):
        gate = threading.Event()
        entered = threading.Semaphore(0)
        body = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 100

        class Blocked(io.BytesIO):
            def read1(self, n=-1):
                entered.release()
                gate.wait(10)
                return super().read1(n)

        results = []
        threads = [
            threading.Thread(
                target=lambda: results.append(self.upload(Blocked(body), len(body))[0])
            )
            for _ in range(clipcutter.MAX_UPLOADS)
        ]
        for t in threads:
            t.start()
        for _ in threads:
            self.assertTrue(entered.acquire(timeout=10))

        class Never:
            def read1(self, n=-1):
                raise AssertionError("the body was read")

        code, payload = self.upload(Never(), 100)
        gate.set()
        for t in threads:
            t.join(10)
        self.assertEqual(code, 503)
        self.assertIn("error", payload)
        self.assertEqual(clipcutter.MAX_UPLOADS, 2)
        self.assertEqual(len(results), 2)

    def test_a_slot_is_given_back_after_every_outcome(self):
        for _ in range(clipcutter.MAX_UPLOADS + 3):
            code, _p = self.upload(io.BytesIO(b"GIF89a" + b"\x00" * 40), 46)
            self.assertEqual(code, 400)


class AFailureIsNamedByItsSide(UploadCase):
    BODY = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 5000

    def test_a_write_that_fails_is_507_naming_the_folder_and_leaves_nothing(self):
        real = os.fdopen

        class FullDisk:
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.f.close()
                return False

            def write(self, data):
                raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), "/secret/dir")

        with mock.patch.object(
            clipcutter.os, "fdopen", lambda fd, mode: FullDisk(real(fd, mode))
        ):
            code, payload = self.upload(io.BytesIO(self.BODY), len(self.BODY))
        self.assertEqual(code, 507)
        self.assertIn("clip folder", payload["error"])
        self.assertIn(os.strerror(errno.ENOSPC), payload["error"])
        self.assertNotIn("/secret", payload["error"])
        self.assertEqual(os.listdir(self.dir), [])

    def test_a_temp_file_that_cannot_be_made_is_507(self):
        err = OSError(errno.EACCES, os.strerror(errno.EACCES), "/secret/dir")
        with mock.patch.object(clipcutter.tempfile, "mkstemp", side_effect=err):
            code, payload = self.upload(io.BytesIO(self.BODY), len(self.BODY))
        self.assertEqual(code, 507)
        self.assertIn("clip folder", payload["error"])
        self.assertNotIn("/secret", payload["error"])
        self.assertEqual(os.listdir(self.dir), [])

    def test_a_connection_that_breaks_while_reading_is_still_408(self):
        class Broken(io.BytesIO):
            def read1(self, n=-1):
                if self.tell() > 100:
                    raise ConnectionResetError("reset")
                return super().read1(min(n, 50))

        code, payload = self.upload(Broken(self.BODY), len(self.BODY))
        self.assertEqual(code, 408)
        self.assertNotIn("folder", payload["error"])
        self.assertEqual(os.listdir(self.dir), [])


class OneBadFileDoesNotStarveTheRest(unittest.TestCase):
    def test_a_file_that_cannot_be_removed_stays_expired_and_the_pass_goes_on(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rows = []
        for i in (1, 2, 3):
            name = "clip-%d-loot.mp4" % i
            pathlib.Path(tmp.name, name).write_bytes(b"x")
            rows.append(clip_row(id=i, state="expired", file_name=name))
        ledger = CutterLedger(rows)
        real = os.unlink

        def unlink(path):
            if path.endswith("clip-2-loot.mp4"):
                raise PermissionError(13, "Permission denied")
            return real(path)

        with (
            mock.patch.object(clipledger.os, "unlink", unlink),
            self.assertLogs("clipledger", level="WARNING") as logs,
        ):
            count = clipledger.delete_expired(ledger, tmp.name)
        self.assertEqual(count, 2)
        self.assertEqual(
            [r["state"] for r in ledger.rows], ["deleted", "expired", "deleted"]
        )
        self.assertEqual(sorted(os.listdir(tmp.name)), ["clip-2-loot.mp4"])
        (line,) = logs.output
        self.assertIn("2", line)
        self.assertIn("Permission denied", line)


class AMarkerInANoteCannotMoveTheView(unittest.TestCase):
    def test_a_note_or_reason_with_view_marker_is_refused_in_any_case(self):
        for text in ("view:Other", "see VIEW: Zug (leader)", "a View:b"):
            self.assertTrue(clipcutter.spoofs_view(text), text)
        self.assertFalse(clipcutter.spoofs_view("cut late, preview ok"))

    def test_a_reason_with_a_marker_is_refused_by_result(self):
        ledger = CutterLedger([clip_row(state="cutting", file_name=None)])
        code, _p = clipcutter.result(ledger, "1", "failed", "view: Zug (leader)")
        self.assertEqual(code, 400)
        self.assertEqual(ledger.rows[0]["state"], "cutting")

    def test_only_the_planner_part_of_the_detail_names_the_owner(self):
        owner = clipledger.view_owner
        row = lambda d: {"character": "Testchar", "detail": d}  # noqa: E731
        self.assertEqual(
            owner(row("view: Grug (leader); note view: Zug (leader)")), "Grug"
        )
        self.assertEqual(
            owner(row("Blade; view: Grug (leader); view: Zug (leader)")), "Grug"
        )
        self.assertEqual(owner(row("anything view: Zug (leader)")), "Testchar")

    def test_a_marker_name_with_punctuation_or_spaces_names_nobody(self):
        owner = clipledger.view_owner
        for bad in ("Gr ug", "Grug!", "G", "Abcdefghijklm", "Gr-ug", "Gr1"):
            row = {"character": "Testchar", "detail": "view: %s (leader)" % bad}
            self.assertEqual(owner(row), "Testchar", bad)


if __name__ == "__main__":
    unittest.main()
