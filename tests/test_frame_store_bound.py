"""The frame store is bounded by a ceiling, not only by the roster.

`_frame_post` admits any name of 2-12 letters, so "one record per roster
character" was never the bound the comment above `_FRAMES` promised: a
poster looping over invented names grew the store by a frame each until the
process was killed. Past MAX_FRAMES, the record last touched longest ago
goes, and the newest post always lands.
"""

import io
import time
import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import frames
    import map_server

JPEG = b"\xff\xd8\xff" + b"body"


class FakeHandler(map_server.Handler):
    def __init__(self, name, body=JPEG):
        self.path = f"/api/frame?name={name}&status=ok"
        self.rfile = io.BytesIO(body)
        self.headers = {"Content-Length": str(len(body))}
        self.sent = []

    def _send(self, code, ctype, body):
        self.sent.append((code, ctype, body))

    @property
    def code(self):
        return self.sent[-1][0]


def _names(count):
    # "Aaaaab", "Aaaaac", ...: distinct names the name check accepts.
    out = []
    n = 0
    while len(out) < count:
        tail = ""
        k = n
        for _ in range(4):
            tail = chr(ord("a") + k % 26) + tail
            k //= 26
        out.append("Fr" + tail)
        n += 1
    return out


class TheStoreHasACeiling(unittest.TestCase):
    def setUp(self):
        self.saved = dict(map_server._FRAMES)
        map_server._FRAMES.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        map_server._FRAMES.clear()
        map_server._FRAMES.update(self.saved)

    def test_the_ceiling_is_a_small_multiple_of_the_streams(self):
        self.assertEqual(map_server.MAX_FRAMES, 4 * map_server.stream.MAX_CHANNELS)
        self.assertGreater(map_server.MAX_FRAMES, 0)

    def test_past_the_ceiling_the_oldest_record_goes_and_the_newest_stays(self):
        names = _names(map_server.MAX_FRAMES + 5)
        for name in names:
            handler = FakeHandler(name)
            handler.do_POST()
            self.assertEqual(handler.code, 200, handler.sent)
            # Distinct `at` values, so "oldest" is well defined.
            map_server._FRAMES[name]["at"] -= len(names) - names.index(name)
        self.assertEqual(len(map_server._FRAMES), map_server.MAX_FRAMES)
        self.assertIn(names[-1], map_server._FRAMES)
        for gone in names[:5]:
            self.assertNotIn(gone, map_server._FRAMES)

    def test_a_character_posting_again_does_not_grow_the_store(self):
        name = _names(1)[0]
        for _ in range(3):
            FakeHandler(name).do_POST()
        self.assertEqual(list(map_server._FRAMES), [name])
        self.assertEqual(
            frames.describe(map_server._FRAMES[name], time.time())["status"], "ok"
        )


if __name__ == "__main__":
    unittest.main()
