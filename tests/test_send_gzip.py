"""Handler._send gzips a large JSON answer for a caller that accepts it (#2051),
and the quest wire drops the columns the page never reads."""

import gzip
import io
import json
import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import map_server
    import questcatalogue as qc
    from apiv2 import quests as v2quests


class Wire(map_server.Handler):
    """A Handler with the socket amputated: records headers and body."""

    def __init__(self, headers=None, command="GET"):
        self.headers = headers or {}
        self.command = command
        self.sent_headers = {}
        self.status = None
        self.wfile = io.BytesIO()

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        pass


BIG = json.dumps(
    {"rows": [{"id": i, "name": "row %d" % i} for i in range(800)]}
).encode()
SMALL = b'{"ok": true}'


def send(body, ctype="application/json", headers=None, command="GET"):
    handler = Wire(headers, command)
    handler._send(200, ctype, body)
    return handler


class GzipOnTheWire(unittest.TestCase):
    def test_a_big_json_answer_round_trips_through_gzip(self):
        got = send(BIG, headers={"Accept-Encoding": "gzip, deflate"})
        self.assertEqual(got.sent_headers["Content-Encoding"], "gzip")
        sent = got.wfile.getvalue()
        self.assertEqual(gzip.decompress(sent), BIG)
        self.assertEqual(got.sent_headers["Content-Length"], str(len(sent)))
        self.assertLess(len(sent), len(BIG) // 2)

    def test_no_header_means_no_gzip(self):
        got = send(BIG)
        self.assertNotIn("Content-Encoding", got.sent_headers)
        self.assertEqual(got.wfile.getvalue(), BIG)
        self.assertEqual(got.sent_headers["Content-Length"], str(len(BIG)))

    def test_json_always_varies_on_accept_encoding(self):
        for headers in ({}, {"Accept-Encoding": "gzip"}):
            self.assertEqual(
                send(BIG, headers=headers).sent_headers["Vary"], "Accept-Encoding"
            )
            self.assertEqual(
                send(SMALL, headers=headers).sent_headers["Vary"], "Accept-Encoding"
            )

    def test_gzip_refused_with_q_zero(self):
        got = send(BIG, headers={"Accept-Encoding": "gzip;q=0"})
        self.assertNotIn("Content-Encoding", got.sent_headers)

    def test_a_small_answer_is_not_compressed(self):
        got = send(SMALL, headers={"Accept-Encoding": "gzip"})
        self.assertNotIn("Content-Encoding", got.sent_headers)
        self.assertEqual(got.wfile.getvalue(), SMALL)

    def test_a_picture_is_never_compressed(self):
        jpeg = b"\xff\xd8" + b"\x00" * 10000
        got = send(jpeg, ctype="image/jpeg", headers={"Accept-Encoding": "gzip"})
        self.assertNotIn("Content-Encoding", got.sent_headers)
        self.assertNotIn("Vary", got.sent_headers)
        self.assertEqual(got.wfile.getvalue(), jpeg)

    def test_the_frame_route_sends_its_jpeg_as_it_is(self):
        jpeg = b"\xff\xd8" + b"\x00" * 10000
        handler = Wire({"Accept-Encoding": "gzip"})
        handler.path = "/api/frame?name=Odo"
        map_server._FRAMES["Odo"] = {"jpeg": jpeg}
        try:
            handler._frame_get({"name": ["Odo"]})
        finally:
            map_server._FRAMES.pop("Odo", None)
        self.assertNotIn("Content-Encoding", handler.sent_headers)
        self.assertEqual(handler.wfile.getvalue(), jpeg)

    def test_the_two_forms_have_different_tags_and_each_revalidates(self):
        plain = send(BIG).sent_headers["ETag"]
        packed = send(BIG, headers={"Accept-Encoding": "gzip"}).sent_headers["ETag"]
        self.assertNotEqual(plain, packed)
        again = send(BIG, headers={"Accept-Encoding": "gzip", "If-None-Match": packed})
        self.assertEqual(again.status, 304)
        self.assertEqual(again.wfile.getvalue(), b"")


class TheQuestWire(unittest.TestCase):
    def test_the_columns_the_page_never_reads_are_not_sent(self):
        row = {
            "quest": 7,
            "title": "Q",
            "level": 12,
            "min_level": 10,
            "sort": 12,
            "races": 1101,
            "classes": 8,
            "follows": 6,
        }
        (q,) = qc.build(
            [row], [{"quest": 7, "role": r, "map_id": 0} for r in ("start", "end")]
        )
        payload = v2quests.build_quest(q, [])
        self.assertEqual(
            sorted(payload["quest"]),
            sorted(
                [
                    "id",
                    "title",
                    "level",
                    "min_level",
                    "zone",
                    "zone_name",
                    "faction",
                    "status",
                    "attempts",
                    "ticket",
                ]
            ),
        )
        listed = v2quests.build_quests([q], [])["quests"][0]
        for gone in ("races", "classes", "follows"):
            self.assertNotIn(gone, listed)
