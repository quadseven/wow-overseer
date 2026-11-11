"""A stateful overseer_clip behind `map_server._connect`, and a localhost
server that can POST, for the cutter API tests.

It extends clip_fakes.FakeLedger, which already answers the shelf and the file
lookup. The statements it adds are told apart by their text, and every UPDATE
is applied only when the row's state is one the statement's WHERE names, so a
statement without that condition cannot pass a test by accident.
"""

import contextlib
import http.client
import re
import threading
from datetime import datetime
from http.server import ThreadingHTTPServer
from unittest import mock

import map_server
from clip_fakes import FakeLedger

NOW = datetime(2026, 11, 9, 12, 0, 0)
_STATES = re.compile(r"WHERE .*?state (?:IN \(([^)]*)\)|= '(\w+)')")


def _allowed(sql):
    found = _STATES.search(sql)
    if not found:
        raise AssertionError("an UPDATE with no state condition: " + sql)
    text = found.group(1) or "'%s'" % found.group(2)
    return {s.strip().strip("'") for s in text.split(",")}


def _joined(old, *parts):
    return "; ".join(p for p in (old, *parts) if p)


class CutterLedger(FakeLedger):
    """`race` names a state the next UPDATE finds its row already moved to."""

    def __init__(self, rows=(), now=NOW):
        super().__init__(rows)
        self.now = now
        self.rowcount = 0
        self.race = None
        self.updates = []

    def _row(self, rid):
        return next((r for r in self.rows if r["id"] == rid), None)

    def execute(self, sql, params=()):
        params = tuple(params or ())
        text = " ".join(sql.split())
        if text.startswith("UPDATE overseer_clip"):
            return self._update(text, params)
        if text.startswith("SELECT NOW()"):
            self.asked.append((sql, params))
            self._answer = [{"now": self.now}]
        elif "WHERE state = 'pending' AND stream_path IN" in text:
            self.asked.append((sql, params))
            rows = [
                r
                for r in self.rows
                if r["state"] == "pending" and r["stream_path"] in params
            ]
            rows.sort(key=lambda r: (r["event_at"], r["id"]))
            cap = re.search(r"LIMIT (\d+)$", text)
            self._answer = rows[: int(cap.group(1))] if cap else rows
        elif "WHERE state = 'expired'" in text:
            self.asked.append((sql, params))
            self._answer = [r for r in self.rows if r["state"] == "expired"]
        elif re.search(r"FROM overseer_clip WHERE id = %s$", text):
            self.asked.append((sql, params))
            row = self._row(params[0])
            self._answer = [dict(row)] if row else []
        else:
            super().execute(sql, params)

    def _update(self, text, params):
        self.asked.append((text, params))
        self.updates.append((text, params))
        if text.endswith("AND state = %s"):
            # the timeout sweep's own form: the expected state is the last value
            *vals, rid, was = params
            row = self._row(rid)
            self.rowcount = 0
            if row and row["state"] == was:
                row["state"] = vals[0]
                if "detail" in text:
                    row["detail"] = vals[1]
                self.rowcount = 1
            return
        allowed = _allowed(text)
        if "SET state = 'deleted'" in text:
            note, rid = params
            change = {"state": "deleted", "detail": note}
        elif "SET state = 'cutting'" in text:
            (rid,) = params
            change = {"state": "cutting"}
        elif "SET state = 'ready'" in text:
            name, note, rid = params
            change = {"state": "ready", "file_name": name, "detail": note}
        elif "SET state = %s" in text:
            state, reason, rid = params
            change = {"state": state, "detail": reason}
        else:
            raise AssertionError("an UPDATE the fake does not know: " + text)
        row = self._row(rid)
        if self.race and row:
            row["state"], self.race = self.race, None
        self.rowcount = 0
        if row and row["state"] in allowed:
            if "detail" in change:
                if change["state"] == "ready":
                    # mirrors clipcutter._READY: the first part is kept even if empty
                    old, note = row.get("detail") or "", change["detail"]
                    change["detail"] = "%s; %s" % (old, note) if note else old
                else:
                    change["detail"] = _joined(row.get("detail"), change["detail"])
            row.update(change)
            self.rowcount = 1


class Client:
    def __init__(self, port):
        self.port = port

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=b""):
        return self.request("POST", path, body=body)


@contextlib.contextmanager
def serving_cutter(ledger, clips_dir):
    """The map server's Handler on a localhost port over `ledger`, with
    CLIPS_DIR set to `clips_dir`. Yields a Client."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), map_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with (
        mock.patch.object(map_server, "_connect", ledger.connect),
        mock.patch.object(map_server, "CLIPS_DIR", clips_dir, create=True),
    ):
        try:
            yield Client(server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
