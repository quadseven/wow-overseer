"""The cutter API at the HTTP seam: pending, claim, file, result.

A real localhost server over map_server.Handler, with a stateful fake ledger
and a real temporary CLIPS_DIR. Every refusal is a sentence and leaves no
file behind.
"""

import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules
from sandbox_caps import LOCALHOST, NO_LOCALHOST

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    from clip_fakes import clip_row
    from cutter_fakes import NOW, CutterLedger, serving_cutter
    import clipcutter

MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x01" * 64


def row(**over):
    base = dict(
        id=1,
        state="pending",
        file_name=None,
        event_at=NOW - timedelta(minutes=2),
        window_start=NOW - timedelta(minutes=3),
        window_end=NOW - timedelta(minutes=1),
        detail="",
    )
    base.update(over)
    return clip_row(**base)


@unittest.skipUnless(LOCALHOST, NO_LOCALHOST)
class CutterCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def run_with(self, rows, fn, clips_dir=None):
        self.ledger = CutterLedger(rows)
        with serving_cutter(
            self.ledger, self.dir if clips_dir is None else clips_dir
        ) as c:
            return fn(c)

    def state(self, rid=1):
        return next(r for r in self.ledger.rows if r["id"] == rid)

    def files(self):
        return sorted(os.listdir(self.dir))

    def sentence(self, body):
        text = json.loads(body)["error"]
        self.assertGreater(len(text.split()), 2, text)
        return text


class Pending(CutterCase):
    def test_only_the_asked_paths_pending_rows_oldest_first_with_the_db_clock(self):
        rows = [
            row(id=1, stream_path="camb", event_at=NOW - timedelta(minutes=1)),
            row(id=2, stream_path="cama", event_at=NOW - timedelta(minutes=5)),
            row(id=3, stream_path="camc"),
            row(id=4, stream_path="cama", state="cutting"),
            row(id=5, stream_path="cama", event_at=NOW - timedelta(minutes=9)),
        ]
        status, body = self.run_with(
            rows, lambda c: c.get("/api/clips/pending?paths=cama,camb")
        )
        got = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual([c["id"] for c in got["clips"]], [5, 2, 1])
        self.assertEqual(
            sorted(got["clips"][0]),
            ["event_at", "id", "kind", "stream_path", "window_end", "window_start"],
        )
        self.assertEqual(got["now"], NOW.isoformat())

    def test_a_failed_late_row_is_never_offered_to_a_cutter(self):
        rows = [
            row(id=1, stream_path="cama"),
            row(id=2, stream_path="cama", state="failed", detail="late"),
        ]
        _s, body = self.run_with(rows, lambda c: c.get("/api/clips/pending?paths=cama"))
        self.assertEqual([c["id"] for c in json.loads(body)["clips"]], [1])

    def test_at_most_ten_rows(self):
        rows = [row(id=i, stream_path="cama") for i in range(1, 15)]
        _s, body = self.run_with(rows, lambda c: c.get("/api/clips/pending?paths=cama"))
        self.assertEqual(len(json.loads(body)["clips"]), 10)

    def test_no_paths_is_refused_with_a_sentence(self):
        status, body = self.run_with([row()], lambda c: c.get("/api/clips/pending"))
        self.assertEqual(status, 400)
        self.sentence(body)

    def test_a_path_with_odd_characters_is_refused(self):
        status, body = self.run_with(
            [row()], lambda c: c.get("/api/clips/pending?paths=a%27%3B--")
        )
        self.assertEqual(status, 400)
        self.sentence(body)

    def test_unset_clips_dir_is_503_with_a_sentence(self):
        status, body = self.run_with(
            [row()], lambda c: c.get("/api/clips/pending?paths=cama"), clips_dir=""
        )
        self.assertEqual(status, 503)
        self.sentence(body)


class Claim(CutterCase):
    def test_a_claim_succeeds_once_and_the_second_is_409_changing_nothing(self):
        def go(c):
            return c.post("/api/clips/claim?id=1"), c.post("/api/clips/claim?id=1")

        (s1, b1), (s2, b2) = self.run_with([row()], go)
        self.assertEqual(s1, 200)
        self.assertEqual(json.loads(b1)["state"], "cutting")
        self.assertEqual(s2, 409)
        self.sentence(b2)
        self.assertEqual(self.state()["state"], "cutting")
        self.assertEqual(len(self.ledger.updates), 2)

    def test_a_lost_race_is_409_not_success(self):
        def go(c):
            self.ledger.race = "failed"
            return c.post("/api/clips/claim?id=1")

        status, body = self.run_with([row()], go)
        self.assertEqual(status, 409)
        self.sentence(body)
        self.assertEqual(self.state()["state"], "failed")

    def test_unknown_id_bad_id_and_unset_dir(self):
        s404, b404 = self.run_with([row()], lambda c: c.post("/api/clips/claim?id=99"))
        s400, b400 = self.run_with([row()], lambda c: c.post("/api/clips/claim?id=x"))
        s503, b503 = self.run_with(
            [row()], lambda c: c.post("/api/clips/claim?id=1"), clips_dir=""
        )
        self.assertEqual((s404, s400, s503), (404, 400, 503))
        for body in (b404, b400, b503):
            self.sentence(body)
        self.assertEqual(self.state()["state"], "pending")


class Upload(CutterCase):
    def up(self, body=MP4, query="id=1", rows=None):
        rows = [row(state="cutting", detail="earlier")] if rows is None else rows
        return self.run_with(rows, lambda c: c.post("/api/clips/file?" + query, body))

    def test_an_upload_lands_under_the_derived_name_and_the_shelf_lists_it(self):
        def go(c):
            return (
                c.post("/api/clips/file?id=1&note=cut%20late", MP4),
                c.get("/api/clips"),
                c.get("/clips/clip-1-loot.mp4"),
            )

        (status, body), (_s, shelf), (_s2, served) = self.run_with(
            [row(state="cutting", detail="earlier")], go
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.files(), ["clip-1-loot.mp4"])
        self.assertEqual((pathlib.Path(self.dir) / "clip-1-loot.mp4").read_bytes(), MP4)
        self.assertEqual(self.state()["state"], "ready")
        self.assertEqual(self.state()["file_name"], "clip-1-loot.mp4")
        self.assertEqual(self.state()["detail"], "earlier; cut late")
        self.assertEqual(
            [c["url"] for c in json.loads(shelf)["clips"]], ["/clips/clip-1-loot.mp4"]
        )
        self.assertEqual(served, MP4)

    def test_a_note_that_forges_a_view_marker_is_400_and_leaves_no_file(self):
        status, body = self.up(query="id=1&note=view%3AOther")
        self.assertEqual(status, 400)
        self.sentence(body)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.state()["state"], "cutting")

    def test_an_upload_without_a_note_keeps_the_detail(self):
        self.up()
        self.assertEqual(self.state()["detail"], "earlier")

    def test_a_name_in_the_request_is_ignored(self):
        self.up(query="id=1&file_name=../evil.mp4&name=x.mp4")
        self.assertEqual(self.files(), ["clip-1-loot.mp4"])

    def test_a_row_not_cutting_is_409_and_leaves_no_file(self):
        for st in ("pending", "ready", "failed"):
            status, body = self.up(rows=[row(state=st)])
            self.assertEqual(status, 409, st)
            self.sentence(body)
            self.assertEqual(self.files(), [])
            self.assertEqual(self.state()["state"], st)

    def test_unknown_id_and_bad_id(self):
        s1, b1 = self.up(query="id=99")
        s2, b2 = self.up(query="id=abc")
        self.assertEqual((s1, s2), (404, 400))
        self.sentence(b1)
        self.sentence(b2)
        self.assertEqual(self.files(), [])

    def test_an_oversize_body_is_413_and_leaves_no_file(self):
        with mock.patch.object(clipcutter, "MAX_UPLOAD", 32):
            status, body = self.up()
        self.assertEqual(status, 413)
        self.sentence(body)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.state()["state"], "cutting")

    def test_a_body_that_is_not_mp4_is_400_and_leaves_no_file(self):
        status, body = self.up(b"GIF89a" + b"\x00" * 64)
        self.assertEqual(status, 400)
        self.sentence(body)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.state()["state"], "cutting")

    def test_an_empty_body_is_400(self):
        status, body = self.up(b"")
        self.assertEqual(status, 400)
        self.sentence(body)
        self.assertEqual(self.files(), [])

    def test_an_existing_file_is_409_and_never_overwritten(self):
        target = pathlib.Path(self.dir) / "clip-1-loot.mp4"
        target.write_bytes(b"original")
        status, body = self.up()
        self.assertEqual(status, 409)
        self.sentence(body)
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(self.files(), ["clip-1-loot.mp4"])
        self.assertEqual(self.state()["state"], "cutting")

    def test_a_lost_race_is_409_and_the_new_file_is_removed(self):
        def go(c):
            self.ledger.race = "failed"
            return c.post("/api/clips/file?id=1", MP4)

        status, body = self.run_with([row(state="cutting")], go)
        self.assertEqual(status, 409)
        self.sentence(body)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.state()["state"], "failed")

    def test_unset_clips_dir_is_503(self):
        status, body = self.run_with(
            [row(state="cutting")],
            lambda c: c.post("/api/clips/file?id=1", MP4),
            clips_dir="",
        )
        self.assertEqual(status, 503)
        self.sentence(body)


class Result(CutterCase):
    def post(self, query, state="cutting", detail="earlier", dir_=None):
        return self.run_with(
            [row(state=state, detail=detail)],
            lambda c: c.post("/api/clips/result?" + query),
            clips_dir=dir_,
        )

    def test_no_view_and_failed_append_the_reason_and_keep_the_detail(self):
        for st in ("pending", "cutting"):
            for to in ("no_view", "failed"):
                status, _b = self.post(
                    "id=1&state=%s&reason=gone%%20dark" % to, state=st
                )
                self.assertEqual(status, 200, (st, to))
                self.assertEqual(self.state()["state"], to)
                self.assertEqual(self.state()["detail"], "earlier; gone dark")

    def test_an_empty_or_missing_reason_is_refused(self):
        for q in (
            "id=1&state=failed&reason=",
            "id=1&state=failed",
            "id=1&state=failed&reason=%20",
        ):
            status, body = self.post(q)
            self.assertEqual(status, 400, q)
            self.sentence(body)
            self.assertEqual(self.state()["state"], "cutting")

    def test_a_state_other_than_the_two_is_refused(self):
        for to in ("ready", "deleted", "pending", ""):
            status, body = self.post("id=1&state=%s&reason=x" % to)
            self.assertEqual(status, 400, to)
            self.sentence(body)

    def test_a_row_already_settled_is_409(self):
        status, body = self.post("id=1&state=failed&reason=late", state="ready")
        self.assertEqual(status, 409)
        self.sentence(body)
        self.assertEqual(self.state()["detail"], "earlier")

    def test_a_lost_race_is_409(self):
        def go(c):
            self.ledger.race = "ready"
            return c.post("/api/clips/result?id=1&state=failed&reason=late")

        status, _b = self.run_with([row(state="cutting")], go)
        self.assertEqual(status, 409)
        self.assertEqual(self.state()["state"], "ready")

    def test_unknown_id_and_unset_dir(self):
        s404, b404 = self.post("id=99&state=failed&reason=x")
        s503, b503 = self.post("id=1&state=failed&reason=x", dir_="")
        self.assertEqual((s404, s503), (404, 503))
        self.sentence(b404)
        self.sentence(b503)


class TheRoutes(unittest.TestCase):
    def test_the_route_table_says_the_trust_is_the_frame_agents(self):
        src = (HERE / "map_server.py").read_text()
        table = src[src.index("POST_ROUTES = {") :]
        table = table[: table.index("}")]
        for path in ("claim", "file", "result"):
            self.assertIn('"/api/clips/%s"' % path, table)
        self.assertIn("no token", src[src.index("POST_ROUTES = {") - 900 :])
        get = src[src.index("GET_ROUTES = {") :]
        self.assertIn('"/api/clips/pending"', get[: get.index("}")])

    def test_the_docs_list_the_four_routes(self):
        docs = (HERE / "docs" / "API.md").read_text()
        for head in (
            "GET /api/clips/pending",
            "POST /api/clips/claim",
            "POST /api/clips/file",
            "POST /api/clips/result",
        ):
            self.assertIn("## `%s`" % head, docs)


if __name__ == "__main__":
    unittest.main()
