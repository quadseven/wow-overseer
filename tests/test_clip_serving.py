"""GET /clips/<file>: a saved clip, streamed with HTTP Range support.

These tests run a real server on a localhost port and ask it over HTTP, so the
status line, the headers and the bytes are what a browser's video element
would see. They skip where the lane sandbox denies localhost; CI runs them.
"""

import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules
from sandbox_caps import LOCALHOST, NO_LOCALHOST

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import map_server
    from clip_fakes import FakeLedger, clip_row, serving

BODY = bytes(range(256)) * 4  # 1024 bytes
NAME = "clip-1-loot.mp4"


@unittest.skipUnless(LOCALHOST, NO_LOCALHOST)
class RangeOverHttp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        (pathlib.Path(self.dir.name) / NAME).write_bytes(BODY)
        self.ledger = FakeLedger([clip_row(file_name=NAME)])

    def get(self, path, headers=None):
        with serving(self.ledger, self.dir.name) as get:
            return get(path, headers)

    def test_first_bytes(self):
        status, headers, body = self.get("/clips/" + NAME, {"Range": "bytes=0-99"})
        self.assertEqual(status, 206)
        self.assertEqual(body, BODY[:100])
        self.assertEqual(headers["content-range"], "bytes 0-99/1024")
        self.assertEqual(headers["content-length"], "100")
        self.assertEqual(headers["accept-ranges"], "bytes")
        self.assertEqual(headers["content-type"], "video/mp4")

    def test_middle_range(self):
        status, headers, body = self.get("/clips/" + NAME, {"Range": "bytes=300-399"})
        self.assertEqual(status, 206)
        self.assertEqual(body, BODY[300:400])
        self.assertEqual(headers["content-range"], "bytes 300-399/1024")

    def test_open_ended_range(self):
        status, headers, body = self.get("/clips/" + NAME, {"Range": "bytes=1000-"})
        self.assertEqual(status, 206)
        self.assertEqual(body, BODY[1000:])
        self.assertEqual(headers["content-range"], "bytes 1000-1023/1024")

    def test_suffix_range(self):
        status, headers, body = self.get("/clips/" + NAME, {"Range": "bytes=-24"})
        self.assertEqual(status, 206)
        self.assertEqual(body, BODY[-24:])
        self.assertEqual(headers["content-range"], "bytes 1000-1023/1024")

    def test_bad_range_is_416_with_the_size(self):
        status, headers, _body = self.get(
            "/clips/" + NAME, {"Range": "bytes=5000-6000"}
        )
        self.assertEqual(status, 416)
        self.assertEqual(headers["content-range"], "bytes */1024")

    def test_whole_file_without_a_range(self):
        status, headers, body = self.get("/clips/" + NAME)
        self.assertEqual(status, 200)
        self.assertEqual(body, BODY)
        self.assertEqual(headers["accept-ranges"], "bytes")
        self.assertEqual(headers["content-length"], "1024")


@unittest.skipUnless(LOCALHOST, NO_LOCALHOST)
class OnlyLedgerNamesAreServed(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = pathlib.Path(self.dir.name)
        (root / NAME).write_bytes(BODY)
        (root / "clip-2-loot.mp4").write_bytes(BODY)
        (root / "stray.mp4").write_bytes(BODY)
        self.outside = root.parent / "outside-secret.txt"
        self.outside.write_bytes(b"secret")
        self.addCleanup(self.outside.unlink)
        self.ledger = FakeLedger(
            [
                clip_row(id=1, file_name=NAME),
                clip_row(id=2, file_name="clip-2-loot.mp4", state="expired"),
            ]
        )

    def get(self, path, clips_dir=None):
        with serving(
            self.ledger, self.dir.name if clips_dir is None else clips_dir
        ) as get:
            return get(path)

    def test_a_file_the_ledger_does_not_hold_is_404(self):
        self.assertEqual(self.get("/clips/stray.mp4")[0], 404)

    def test_a_row_that_is_not_ready_is_404(self):
        self.assertEqual(self.get("/clips/clip-2-loot.mp4")[0], 404)

    def test_the_request_name_reaches_the_ledger_as_a_bound_value(self):
        self.get("/clips/stray.mp4")
        sql, params = self.ledger.asked[-1]
        self.assertEqual(params, ("stray.mp4",))
        self.assertNotIn("stray", sql)

    def test_traversal_names_are_404(self):
        for name in ("..%2Foutside-secret.txt", "%2e%2e/outside-secret.txt", "a/b.mp4"):
            self.assertEqual(self.get("/clips/" + name)[0], 404, name)

    def test_a_ledger_name_that_escapes_the_directory_is_not_opened(self):
        self.ledger.rows.append(clip_row(id=3, file_name="../outside-secret.txt"))
        status, _h, body = self.get("/clips/..%2Foutside-secret.txt")
        self.assertEqual(status, 404)
        self.assertNotIn(b"secret", body)

    def test_unset_directory_is_404_and_reads_no_ledger(self):
        status, _h, _b = self.get("/clips/" + NAME, clips_dir="")
        self.assertEqual(status, 404)
        self.assertEqual(self.ledger.asked, [])

    def test_missing_directory_is_404(self):
        self.assertEqual(
            self.get("/clips/" + NAME, clips_dir="/nonexistent-clips-dir")[0], 404
        )

    def test_a_ready_row_whose_file_is_gone_is_404(self):
        self.ledger.rows.append(clip_row(id=4, file_name="gone.mp4"))
        self.assertEqual(self.get("/clips/gone.mp4")[0], 404)

    def test_an_unreadable_ledger_is_503_not_a_crash(self):
        def boom():
            raise map_server.pymysql.err.OperationalError(2003, "down")

        self.ledger.connect = boom
        self.assertEqual(self.get("/clips/" + NAME)[0], 503)

    def test_a_dropped_connection_is_503_too(self):
        def boom():
            raise ConnectionResetError("reset")

        self.ledger.connect = boom
        self.assertEqual(self.get("/clips/" + NAME)[0], 503)

    def test_a_programming_error_surfaces_instead_of_becoming_503(self):
        def boom():
            raise RuntimeError("a bug")

        self.ledger.connect = boom
        with mock.patch.object(map_server, "_connect", boom):
            with mock.patch.object(map_server, "CLIPS_DIR", self.dir.name):
                with self.assertRaises(RuntimeError):
                    map_server._ready_clip_path(NAME)


class RangeRules(unittest.TestCase):
    def test_header_forms(self):
        import clipserve as c

        cases = [
            (None, 100, c.WHOLE),
            ("bytes=0-9", 100, (0, 9)),
            ("bytes=90-", 100, (90, 99)),
            ("bytes=90-500", 100, (90, 99)),
            ("bytes=-10", 100, (90, 99)),
            ("bytes=-500", 100, (0, 99)),
            ("bytes=100-", 100, c.UNSATISFIABLE),
            ("bytes=9-3", 100, c.UNSATISFIABLE),
            ("bytes=-0", 100, c.UNSATISFIABLE),
            ("bytes=abc", 100, c.UNSATISFIABLE),
            ("bytes=0-9", 0, c.UNSATISFIABLE),
            ("bytes=0-1,5-6", 100, c.WHOLE),
            ("items=0-9", 100, c.WHOLE),
        ]
        for header, size, want in cases:
            self.assertEqual(c.parse_range(header, size), want, (header, size))

    def test_stream_reads_in_chunks_never_the_whole_span(self):
        import io

        import clipserve as c

        reads = []

        class Spy(io.BytesIO):
            def read(self, n=-1):
                reads.append(n)
                return super().read(n)

        out = io.BytesIO()
        sent = c.stream(Spy(b"x" * 1000), out, 10, 909, chunk=100)
        self.assertEqual(sent, 900)
        self.assertEqual(out.getvalue(), b"x" * 900)
        self.assertTrue(reads and all(0 < n <= 100 for n in reads), reads)

    def test_the_server_streams_through_clipserve_in_fixed_chunks(self):
        self.assertEqual(clip_chunk(), 64 * 1024)

    def test_the_handler_never_calls_read_on_the_whole_file(self):
        src = (HERE / "map_server.py").read_text()
        body = src[src.index("def _clip_file") : src.index("def _v2(")]
        self.assertNotIn(".read()", body)


def clip_chunk():
    import clipserve

    return clipserve.CHUNK


if __name__ == "__main__":
    unittest.main()
