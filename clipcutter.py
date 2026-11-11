"""The cutter API: what a capture host that has only HTTP needs from the ledger.

It lists pending rows, claims one, hands a file over and reports a drop. The
rules live here and the handlers in map_server stay thin. Every state change is
one conditional UPDATE that names the state it replaces, and a change that
matched no row is a 409, never a quiet success. Every refusal is a sentence.

Nothing the request writes reaches a file name, a path or a state: the name is
derived from the row, the state is one of two words, and every value is bound.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from datetime import datetime

MAX_UPLOAD = 128 * 1024 * 1024
CHUNK = 64 * 1024
MAX_PENDING = 10
MAX_PATHS = 20
MAX_NOTE = 200
# The whole body must arrive within this many seconds (wall clock).
UPLOAD_SECONDS = 600

NO_DIR = "The clip folder is not set up on this site, so the cutter API is off."

_PATH = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_KIND = re.compile(r"[a-z0-9_]{1,16}")
_COLUMNS = "id, kind, stream_path, event_at, window_start, window_end, state, file_name"
_ROW = "SELECT " + _COLUMNS + " FROM overseer_clip WHERE id = %s"
_NOW = "SELECT NOW() AS now"
_PENDING = (
    "SELECT id, kind, stream_path, event_at, window_start, window_end"
    " FROM overseer_clip WHERE state = 'pending' AND stream_path IN ({holes})"
    " ORDER BY event_at ASC, id ASC LIMIT %d" % MAX_PENDING
)
_CLAIM = (
    "UPDATE overseer_clip SET state = 'cutting' WHERE id = %s AND state = 'pending'"
)
_APPEND = "CONCAT_WS('; ', NULLIF(detail, ''), NULLIF(%s, ''))"
_READY = (
    "UPDATE overseer_clip SET state = 'ready', file_name = %s, detail = "
    + _APPEND
    + " WHERE id = %s AND state = 'cutting'"
)
_DROP = (
    "UPDATE overseer_clip SET state = %s, detail = "
    + _APPEND
    + " WHERE id = %s AND state IN ('pending', 'cutting')"
)
DROP_STATES = ("no_view", "failed")


def _err(code: int, sentence: str):
    return code, {"error": sentence}


def parse_id(raw) -> int | None:
    """A row id as the query spells it: ASCII digits, above zero."""
    if not isinstance(raw, str) or not (raw.isascii() and raw.isdigit()):
        return None
    if len(raw) > 18 or int(raw) == 0:
        return None
    return int(raw)


def is_mp4(head: bytes) -> bool:
    """An MP4 starts with a box whose type, at bytes 4 to 8, is ftyp."""
    return len(head) >= 8 and head[4:8] == b"ftyp"


def file_name(row_id: int, kind: str) -> str | None:
    """The one name a row's clip is saved under, or None for a kind that is
    not a plain word."""
    if not isinstance(kind, str) or not _KIND.fullmatch(kind):
        return None
    return "clip-%d-%s.mp4" % (row_id, kind)


def clean_note(raw) -> str:
    """One short printable ASCII line, or empty."""
    if not isinstance(raw, str):
        return ""
    plain = raw.encode("ascii", "replace").decode("ascii")
    return "".join(c if c.isprintable() else " " for c in " ".join(plain.split()))[
        :MAX_NOTE
    ].strip()


def spoofs_view(text: str) -> bool:
    """True for text that carries the planner's `view:` marker. A note or a
    reason is appended to the detail that marker is read from, so it may not
    hold one."""
    return "view:" in text.lower()


_SPOOF = "A note may not contain the text view:, which the clip planner uses."


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _public(row, *names):
    return {k: _iso(row.get(k)) for k in names}


def pending(rd, raw_paths: str):
    """GET /api/clips/pending: the pending rows on the asked paths, oldest
    first, at most MAX_PENDING, with the database clock. `rd` is a realm
    reader."""
    paths = list(dict.fromkeys(p for p in (raw_paths or "").split(",") if p))
    if not paths or len(paths) > MAX_PATHS:
        return _err(
            400, "Name between 1 and %d stream paths, as paths=a,b." % MAX_PATHS
        )
    if not all(_PATH.fullmatch(p) for p in paths):
        return _err(
            400,
            "A stream path may hold only letters, digits, dots, dashes and underscores.",
        )
    # S608: `holes` is placeholders only; every path is bound by the driver.
    sql = _PENDING.format(holes=", ".join(["%s"] * len(paths)))  # noqa: S608
    rows = rd.rows(sql, tuple(paths), what="the pending clips")
    now = rd.rows(_NOW, (), what="the database clock")[0]["now"]
    names = ("id", "kind", "stream_path", "event_at", "window_start", "window_end")
    return 200, {"now": _iso(now), "clips": [_public(r, *names) for r in rows]}


def _lookup(cur, row_id):
    cur.execute(_ROW, (row_id,))
    return cur.fetchone()


def _find(cur, raw_id):
    """(row, None) or (None, refusal)."""
    row_id = parse_id(raw_id)
    if row_id is None:
        return None, _err(400, "The id must be a whole number above zero, as id=N.")
    row = _lookup(cur, row_id)
    if row is None:
        return None, _err(404, "No clip request has that id.")
    return row, None


def _moved(row):
    return _err(
        409,
        "That clip request is %s now, not in the state this call needs." % row["state"],
    )


def claim(cur, raw_id):
    """POST /api/clips/claim: pending to cutting, or 409."""
    row, refusal = _find(cur, raw_id)
    if refusal:
        return refusal
    cur.execute(_CLAIM, (row["id"],))
    if not cur.rowcount:
        return _moved(_lookup(cur, row["id"]) or row)
    return 200, _public(_lookup(cur, row["id"]), *_COLUMNS.split(", "))


def result(cur, raw_id, state, reason):
    """POST /api/clips/result: a drop from pending or cutting, with its reason."""
    row, refusal = _find(cur, raw_id)
    if refusal:
        return refusal
    if state not in DROP_STATES:
        return _err(400, "The state must be no_view or failed.")
    why = clean_note(reason)
    if not why:
        return _err(
            400, "Say why the clip was dropped, as reason=...; it may not be empty."
        )
    if spoofs_view(why):
        return _err(400, _SPOOF)
    cur.execute(_DROP, (state, why, row["id"]))
    if not cur.rowcount:
        return _moved(_lookup(cur, row["id"]) or row)
    return 200, _public(_lookup(cur, row["id"]), *_COLUMNS.split(", "))


def _discard(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def stage(rfile, length, root, clock=time.monotonic):
    """Read the whole body into a temporary file in `root`, touching no
    database. Returns (path, None), or (None, refusal) with nothing left behind.

    The checks that need only the body come first: length, cap, ftyp box. A
    stalled or slow sender is cut off by the socket timeout (TimeoutError) or
    by the wall-clock deadline, and answers 408."""
    if length <= 0:
        return None, _err(400, "The body is empty; send the MP4 as the request body.")
    if length > MAX_UPLOAD:
        return None, _err(
            413, "The clip is over the %d MiB limit." % (MAX_UPLOAD // (1024 * 1024))
        )
    late = _err(408, "The body did not arrive in time; send it faster or in one go.")
    deadline = clock() + UPLOAD_SECONDS
    try:
        head = rfile.read(min(length, CHUNK))
    except OSError:
        return None, late
    if not is_mp4(head):
        return None, _err(
            400, "The body is not an MP4 file (no ftyp box at the start)."
        )
    fd, tmp = tempfile.mkstemp(prefix=".upload-", suffix=".part", dir=root)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(head)
            left = length - len(head)
            while left > 0:
                if clock() > deadline:
                    raise TimeoutError("deadline")
                chunk = rfile.read(min(CHUNK, left))
                if not chunk:
                    _discard(tmp)
                    return None, _err(400, "The body ended before its stated length.")
                out.write(chunk)
                left -= len(chunk)
    except OSError:
        _discard(tmp)
        return None, late
    except BaseException:
        _discard(tmp)
        raise
    return tmp, None


def upload(connect, raw_id, rfile, length, root, raw_note, clock=time.monotonic):
    """POST /api/clips/file: `length` bytes of MP4 from `rfile` into `root`
    under the name the row gives, then the row becomes ready.

    `connect()` opens a database cursor as a context manager. It is called only
    after the whole body is on disk, so a slow sender never holds a connection.
    The temporary file is linked into place, which fails if the name exists, so
    an existing file is never overwritten. A row that moved on while the body
    streamed loses its new file."""
    if parse_id(raw_id) is None:
        return _err(400, "The id must be a whole number above zero, as id=N.")
    note = clean_note(raw_note)
    if spoofs_view(note):
        return _err(400, _SPOOF)
    tmp, refusal = stage(rfile, length, root, clock)
    if refusal:
        return refusal
    try:
        with connect() as cur:
            row, refusal = _find(cur, raw_id)
            if refusal:
                return refusal
            if row["state"] != "cutting":
                return _moved(row)
            name = file_name(row["id"], row["kind"])
            if name is None:
                return _err(
                    409, "That clip request has a kind that cannot be saved as a file."
                )
            target = os.path.join(root, name)
            exists = _err(
                409, "A file for that clip is already saved and is never overwritten."
            )
            if os.path.lexists(target):
                return exists
            try:
                os.link(tmp, target)
            except FileExistsError:
                return exists
            try:
                cur.execute(_READY, (name, note, row["id"]))
                landed = cur.rowcount
            except BaseException:
                _discard(target)
                raise
            if not landed:
                _discard(target)
                return _moved(_lookup(cur, row["id"]) or row)
            return 200, _public(_lookup(cur, row["id"]), *_COLUMNS.split(", "))
    finally:
        _discard(tmp)
