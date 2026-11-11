"""A fake overseer_clip table behind `map_server._connect`, and a real
localhost server over `map_server.Handler`, for the clip tests.

No database: the fake answers the few statements the clip routes send, by the
text of the statement, so a reworded or widened query fails a test instead of
reading as an empty answer.
"""

import contextlib
import http.client
import threading
from http.server import ThreadingHTTPServer
from unittest import mock

import map_server


def clip_row(**over):
    row = {
        "id": 1,
        "kind": "loot",
        "character": "Testchar",
        "stream_path": "cam1",
        "event_key": "loot:1",
        "event_at": None,
        "window_start": None,
        "window_end": None,
        "state": "ready",
        "file_name": "clip-1-loot.mp4",
        "detail": "",
        "created_at": None,
        "updated_at": None,
    }
    row.update(over)
    return row


class FakeLedger:
    """overseer_clip behind `_connect`. Every statement is kept in `asked`."""

    def __init__(self, rows=()):
        self.rows = [dict(r) for r in rows]
        self.asked = []
        self._answer = []

    def connect(self):
        return self

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass

    def execute(self, sql, params=()):
        params = tuple(params or ())
        self.asked.append((sql, params))
        rows = list(self.rows)
        if "state = 'ready'" in sql:
            rows = [r for r in rows if r["state"] == "ready"]
        if "file_name = %s" in sql:
            rows = [r for r in rows if r["file_name"] == params[0]]
        if "event_key IN" in sql:
            rows = [r for r in rows if r["event_key"] in params]
        if "ORDER BY event_at DESC" in sql:
            rows.sort(key=lambda r: r["event_at"], reverse=True)
        self._answer = rows

    def fetchall(self):
        return list(self._answer)

    def fetchone(self):
        return self._answer[0] if self._answer else None


@contextlib.contextmanager
def serving(ledger, clips_dir):
    """The map server's Handler on a localhost port, over `ledger`, reading
    clips from `clips_dir`. Yields a `get(path, headers)` helper."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), map_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def get(path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            conn.request("GET", path, headers=headers or {})
            resp = conn.getresponse()
            return (
                resp.status,
                {k.lower(): v for k, v in resp.getheaders()},
                resp.read(),
            )
        finally:
            conn.close()

    with (
        mock.patch.object(map_server, "_connect", ledger.connect),
        mock.patch.object(map_server, "CLIPS_DIR", clips_dir, create=True),
    ):
        try:
            yield get
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
