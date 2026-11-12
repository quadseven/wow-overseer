"""Every response tells the browser not to leak the page's address.

WHY THIS SUITE EXISTS. The site can be mounted under an unguessable path, and
that path is the whole access control: whoever holds the link can open the
site. Two things would quietly give the link away. A link followed from the
page sends the page's address as a referrer, and a crawler that finds the link
once indexes it. So every response says `Referrer-Policy: no-referrer` and
`X-Robots-Tag: noindex, nofollow`, whatever kind of response it is: a page,
JSON, an error, or a 304.
"""

import io
import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

with stub_modules(pymysql=PYMYSQL):
    import basepath
    import map_server


class FakeSocketHandler(map_server.Handler):
    """The real Handler with the socket replaced by a buffer."""

    def __init__(self, if_none_match=""):
        self.wfile = io.BytesIO()
        self.rfile = io.BytesIO()
        self.request_version = "HTTP/1.1"
        self.requestline = "GET / HTTP/1.1"
        self.command = "GET"
        self.client_address = ("127.0.0.1", 0)
        self.close_connection = True
        self.headers = {"If-None-Match": if_none_match} if if_none_match else {}

    def log_message(self, *args):
        return None


def headers_of(raw: bytes) -> dict:
    head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1")
    lines = head.split("\r\n")[1:]
    return {k.lower(): v.strip() for k, v in (ln.split(":", 1) for ln in lines)}


class PrivacyHeadersTest(unittest.TestCase):
    def assert_private(self, raw: bytes):
        got = headers_of(raw)
        self.assertEqual(got.get("referrer-policy"), "no-referrer")
        self.assertEqual(got.get("x-robots-tag"), "noindex, nofollow")

    def test_the_policy_is_named_in_one_place(self):
        self.assertIn(("Referrer-Policy", "no-referrer"), basepath.PRIVACY_HEADERS)
        self.assertIn(("X-Robots-Tag", "noindex, nofollow"), basepath.PRIVACY_HEADERS)

    def test_a_page_carries_them(self):
        h = FakeSocketHandler()
        h._send(200, "text/html; charset=utf-8", b"<html></html>")
        self.assert_private(h.wfile.getvalue())

    def test_a_json_answer_carries_them(self):
        h = FakeSocketHandler()
        h._send(200, "application/json", b'{"a": 1}')
        self.assert_private(h.wfile.getvalue())

    def test_an_error_carries_them(self):
        for code in (404, 500, 503):
            with self.subTest(code=code):
                h = FakeSocketHandler()
                h._send(code, "application/json", b'{"error": "x"}')
                self.assert_private(h.wfile.getvalue())

    def test_a_not_modified_answer_carries_them(self):
        first = FakeSocketHandler()
        first._send(200, "application/json", b'{"a": 1}')
        etag = headers_of(first.wfile.getvalue())["etag"]
        again = FakeSocketHandler(if_none_match=etag)
        again._send(200, "application/json", b'{"a": 1}')
        raw = again.wfile.getvalue()
        self.assertTrue(b" 304 " in raw.split(b"\r\n", 1)[0], raw[:40])
        self.assert_private(raw)

    def test_the_stock_error_page_carries_them(self):
        h = FakeSocketHandler()
        h.send_error(400, "bad request")
        self.assert_private(h.wfile.getvalue())

    def test_each_header_is_sent_once(self):
        h = FakeSocketHandler()
        h._send(200, "application/json", b"{}")
        raw = h.wfile.getvalue().split(b"\r\n\r\n", 1)[0].lower()
        self.assertEqual(raw.count(b"referrer-policy:"), 1)
        self.assertEqual(raw.count(b"x-robots-tag:"), 1)


if __name__ == "__main__":
    unittest.main()
