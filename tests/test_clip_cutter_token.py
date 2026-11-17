"""The cutter routes need the shared CUTTER_TOKEN, and refuse when it is unset.

A real localhost server over map_server.Handler, as test_clip_cutter_api does.
A refused call changes no row and leaves no file.
"""

import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import timedelta

from _stub_modules import PYMYSQL, stub_modules
from sandbox_caps import LOCALHOST, NO_LOCALHOST

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    from clip_fakes import clip_row
    from cutter_fakes import NOW, TOKEN, CutterLedger, serving_cutter
    import clipcutter

MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x01" * 64

ROUTES = (
    ("GET", "/api/clips/pending?paths=cama"),
    ("POST", "/api/clips/claim?id=1"),
    ("POST", "/api/clips/file?id=1"),
    ("POST", "/api/clips/result?id=1&state=failed&reason=because%20nothing%20showed"),
)


def row(**over):
    base = dict(
        id=1,
        state="pending",
        stream_path="cama",
        file_name=None,
        event_at=NOW - timedelta(minutes=2),
        window_start=NOW - timedelta(minutes=3),
        window_end=NOW - timedelta(minutes=1),
        detail="",
    )
    base.update(over)
    return clip_row(**base)


class TheGate(unittest.TestCase):
    def test_a_matching_bearer_passes(self):
        self.assertIsNone(clipcutter.check_token("Bearer " + TOKEN, TOKEN))

    def test_unset_refuses_even_an_empty_header(self):
        for sent in ("", "Bearer ", "Bearer x"):
            code, _ = clipcutter.check_token(sent, "")
            self.assertEqual(code, 503)

    def test_missing_wrong_and_oddly_shaped_headers_are_refused(self):
        for sent in ("", None, "Bearer wrong", TOKEN, "Basic " + TOKEN, "Bearer"):
            code, payload = clipcutter.check_token(sent, TOKEN)
            self.assertEqual(code, 403, sent)
            self.assertGreater(len(payload["error"].split()), 2)


@unittest.skipUnless(LOCALHOST, NO_LOCALHOST)
class OverHttp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def serve(self, fn, token=TOKEN, rows=None):
        self.ledger = CutterLedger(rows or [row(state="cutting")])
        with serving_cutter(self.ledger, self.dir, token=token) as c:
            return fn(c)

    def call(self, c, method, path):
        body = MP4 if path.startswith("/api/clips/file") else b""
        return c.request(method, path, body=body if method == "POST" else None)

    def test_every_route_refuses_without_the_token(self):
        def go(c):
            c.token = None
            return [self.call(c, m, p)[0] for m, p in ROUTES]

        self.assertEqual(self.serve(go), [403] * 4)
        self.assertEqual(self.ledger.updates, [])
        self.assertEqual(os.listdir(self.dir), [])

    def test_every_route_refuses_a_wrong_token(self):
        def go(c):
            c.token = TOKEN + "x"
            return [self.call(c, m, p)[0] for m, p in ROUTES]

        self.assertEqual(self.serve(go), [403] * 4)
        self.assertEqual(self.ledger.updates, [])

    def test_with_the_token_unset_every_route_refuses_and_fails_closed(self):
        def go(c):
            return [self.call(c, m, p)[0] for m, p in ROUTES]

        self.assertEqual(self.serve(go, token=""), [503] * 4)
        self.assertEqual(self.ledger.updates, [])
        self.assertEqual(os.listdir(self.dir), [])

    def test_unset_does_not_accept_an_empty_bearer(self):
        def go(c):
            c.token = ""
            return self.call(c, "POST", "/api/clips/claim?id=1")[0]

        self.assertEqual(self.serve(go, token=""), 503)

    def test_the_right_token_still_works(self):
        def go(c):
            return self.call(c, "POST", "/api/clips/claim?id=1")

        status, _ = self.serve(go, rows=[row()])
        self.assertEqual(status, 200)

    def test_the_public_shelf_needs_no_token(self):
        def go(c):
            c.token = None
            return c.get("/api/clips")[0]

        self.assertEqual(self.serve(go), 200)


@unittest.skipUnless(LOCALHOST, NO_LOCALHOST)
class UploadOwnership(OverHttp):
    def up(self, query):
        def go(c):
            return c.post("/api/clips/file?" + query, MP4)

        return self.serve(go)

    def test_an_upload_naming_another_jobs_stream_path_is_refused(self):
        status, body = self.up("id=1&path=camb")
        self.assertEqual(status, 403)
        self.assertGreater(len(json.loads(body)["error"].split()), 2)
        self.assertEqual(os.listdir(self.dir), [])
        self.assertEqual(self.ledger.updates, [])

    def test_an_upload_naming_its_own_stream_path_lands(self):
        status, _ = self.up("id=1&path=cama")
        self.assertEqual(status, 200)
        self.assertEqual(os.listdir(self.dir), ["clip-1-loot.mp4"])

    def test_an_upload_naming_no_path_still_lands(self):
        status, _ = self.up("id=1")
        self.assertEqual(status, 200)

    def test_a_path_with_path_components_is_refused(self):
        status, _ = self.up("id=1&path=..%2Fcama")
        self.assertEqual(status, 403)
        self.assertEqual(os.listdir(self.dir), [])


if __name__ == "__main__":
    unittest.main()
