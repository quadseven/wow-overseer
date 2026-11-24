"""The cutter API: what a capture host that has only HTTP needs from the ledger.

It lists pending rows, claims one, hands a file over and reports a drop. The
rules live here and the handlers in map_server stay thin. Every state change is
one conditional UPDATE that names the state it replaces, and a change that
matched no row is a 409, never a quiet success. Every refusal is a sentence.

Nothing the request writes reaches a file name, a path or a state: the name is
derived from the row, the state is one of two words, and every value is bound.
"""

from __future__ import annotations

import logging
import hmac
import os
import re
import stat
import tempfile
import threading
import time
from datetime import datetime

log = logging.getLogger(__name__)

MAX_UPLOAD = 128 * 1024 * 1024
CHUNK = 64 * 1024
MAX_PENDING = 10
MAX_PATHS = 20
MAX_NOTE = 200
# The whole body must arrive within this many seconds (wall clock).
UPLOAD_SECONDS = 600
# No single read may wait longer than this, or longer than what is left.
IDLE_SECONDS = 30
# Uploads in flight at once; one more answers 503 (as the chat route caps calls).
MAX_UPLOADS = 2
_SLOTS = threading.BoundedSemaphore(MAX_UPLOADS)

NO_DIR = "The clip folder is not set up on this site, so the cutter API is off."

# The name a body is written under until its row takes it, and how long one
# may sit unwritten before the sweep removes it. A live upload is cut off at
# UPLOAD_SECONDS, so a file twice that old belongs to a process that died.
PART_PREFIX, PART_SUFFIX = ".upload-", ".part"
PART_MAX_AGE = 2 * UPLOAD_SECONDS
_PATH = re.compile(r"[A-Za-z0-9_.-]{1,64}")
# The oldest newest-segment age a poll may report, in seconds. A recorder whose
# last segment is older than a week is reported as a week old or not at all.
MAX_SEGMENT_AGE = 7 * 24 * 3600
_BAD_AGE = (
    "A segment age is path:seconds for a path this poll names, once each, "
    "as ages=a:3,b:41, with whole seconds from 0 to %d." % MAX_SEGMENT_AGE
)
_KIND = re.compile(r"[a-z0-9_]{1,16}")
_COLUMNS = "id, kind, stream_path, event_at, window_start, window_end, state, file_name"
# S608 below: each statement joins module constants only; values are bound.
_ROW = "SELECT " + _COLUMNS + " FROM overseer_clip WHERE id = %s"  # noqa: S608
_NOW = "SELECT NOW() AS now"
_PENDING = (
    "SELECT id, kind, stream_path, event_at, window_start, window_end"  # noqa: S608
    " FROM overseer_clip WHERE state = 'pending' AND stream_path IN ({holes})"
    " ORDER BY event_at ASC, id ASC LIMIT %d" % MAX_PENDING
)
_CLAIM = (
    "UPDATE overseer_clip SET state = 'cutting' WHERE id = %s AND state = 'pending'"
)
_APPEND = "CONCAT_WS('; ', NULLIF(detail, ''), NULLIF(%s, ''))"
# A ready row keeps the planner's first part, the event's subject, in front
# even when it is empty, so a note never moves up into the subject's place.
_APPEND_AFTER_SUBJECT = "CONCAT_WS('; ', COALESCE(detail, ''), NULLIF(%s, ''))"
_READY = (
    "UPDATE overseer_clip SET state = 'ready', file_name = %s, detail = "  # noqa: S608
    + _APPEND_AFTER_SUBJECT
    + " WHERE id = %s AND state = 'cutting'"
)
_DROP = (
    "UPDATE overseer_clip SET state = %s, detail = "  # noqa: S608
    + _APPEND
    + " WHERE id = %s AND state IN ('pending', 'cutting')"
)
DROP_STATES = ("no_view", "failed")


def check_token(sent, expected: str):
    """None when `sent` (an Authorization header value) is `Bearer <expected>`,
    else a refusal. With `expected` empty every call is refused (503): the
    routes fail closed, they never open. Compared in constant time."""
    if not expected:
        return _err(
            503,
            "The cutter routes are off here: no CUTTER_TOKEN is configured.",
        )
    scheme, _, secret = (sent or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        secret.strip().encode(), expected.encode()
    ):
        return _err(403, "The cutter routes need the cutter token as a bearer header.")
    return None


def owns(row, stream_path: str):
    """None when the caller named no stream path or named the row's own, else a
    refusal: a valid caller may not write another job's file."""
    if stream_path and stream_path != row.get("stream_path"):
        return _err(403, "That stream path does not belong to the clip request.")
    return None


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


def poster_name(row_id: int, kind: str) -> str | None:
    """The poster frame name beside a row's clip: clip-<id>-<kind>.jpg, or
    None for a kind that is not a plain word. A cutter that saves a clip
    writes one frame of it under this name, next to the video."""
    if not isinstance(kind, str) or not _KIND.fullmatch(kind):
        return None
    return "clip-%d-%s.jpg" % (row_id, kind)


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


def paths_of(raw_paths: str) -> list[str]:
    """The distinct paths a poll names, in order, from its paths=a,b value."""
    return list(dict.fromkeys(p for p in (raw_paths or "").split(",") if p))


def ages_of(raw_ages: str, paths: list[str]):
    """(ages, None) or (None, refusal) for a poll's ages=path:seconds,... value.

    Each item gives the age in whole seconds of the newest segment the recorder
    for one of the poll's own paths has written. A path may be left out: the
    view then carries no segment clock. A path the poll does not name, a path
    named twice, or an age that is not a whole number of seconds from 0 to
    MAX_SEGMENT_AGE refuses the whole poll, so a bad age is never half applied.
    """
    ages: dict[str, int] = {}
    if not raw_ages:
        return ages, None
    for item in raw_ages.split(","):
        path, colon, seconds = item.partition(":")
        if not colon or path not in paths or path in ages:
            return None, _err(400, _BAD_AGE)
        if not (seconds.isascii() and seconds.isdigit()) or len(seconds) > 9:
            return None, _err(400, _BAD_AGE)
        if int(seconds) > MAX_SEGMENT_AGE:
            return None, _err(400, _BAD_AGE)
        ages[path] = int(seconds)
    return ages, None


def pending(rd, raw_paths: str):
    """GET /api/clips/pending: the pending rows on the asked paths, oldest
    first, at most MAX_PENDING, with the database clock. `rd` is a realm
    reader."""
    paths = paths_of(raw_paths)
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


def sweep_partials(root: str, now: float | None = None) -> int:
    """Remove the partial uploads in `root` a dead process left behind.

    A partial upload is a regular file directly in `root` named
    PART_PREFIX...PART_SUFFIX, which is the only name `_receive` writes a body
    under; a finished clip is renamed out of that shape, so no rule here can
    reach one. One is removed only when it was last written more than
    PART_MAX_AGE seconds before `now` (the wall clock when left out). A folder
    or a link with the name is left alone. A file that cannot be read or
    removed logs one warning and the pass goes on. Returns how many it removed.
    """
    now = time.time() if now is None else now
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    removed = 0
    for name in names:
        if not (name.startswith(PART_PREFIX) and name.endswith(PART_SUFFIX)):
            continue
        path = os.path.join(root, name)
        try:
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or now - info.st_mtime <= PART_MAX_AGE:
                continue
            os.unlink(path)
            removed += 1
        except FileNotFoundError:
            continue
        except OSError as exc:
            log.warning("partial upload %s not removed: %s", name, exc.strerror or exc)
    return removed


def _discard(path):
    if path is None:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


class _Late(TimeoutError):
    pass


def _no_bound(_seconds):
    """The default socket seam: nothing to set."""


def stage(rfile, length, root, clock=time.monotonic, bound=_no_bound):
    """Read the whole body into a temporary file in `root`, touching no
    database. Returns (path, None), or (None, refusal) with nothing left behind.

    The checks that need only the body come first: length, cap, ftyp box.
    EVERY read is bounded. Before it, `bound(seconds)` sets the socket timeout
    to the smaller of IDLE_SECONDS and what is left of UPLOAD_SECONDS, and the
    deadline is checked. A read returns once any data arrives (read1), so a
    sender trickling bytes is cut off at the deadline. A timeout answers 408."""
    if length <= 0:
        return None, _err(400, "The body is empty; send the MP4 as the request body.")
    if length > MAX_UPLOAD:
        return None, _err(
            413, "The clip is over the %d MiB limit." % (MAX_UPLOAD // (1024 * 1024))
        )
    deadline = clock() + UPLOAD_SECONDS
    pull = getattr(rfile, "read1", None) or rfile.read

    def take(n):
        left = deadline - clock()
        if left <= 0:
            raise _Late("deadline")
        bound(min(IDLE_SECONDS, left))
        try:
            return pull(n)
        except OSError as exc:
            # A read that timed out or a connection that broke is the
            # sender's side; any other OSError below is the folder's.
            raise _Late("read failed") from exc

    short = _err(400, "The body ended before its stated length.")
    tmp = None
    try:
        head = b""
        while len(head) < min(length, 8):
            got = take(min(CHUNK, length - len(head)))
            if not got:
                return None, short
            head += got
        if not is_mp4(head):
            return None, _err(
                400, "The body is not an MP4 file (no ftyp box at the start)."
            )
        fd, tmp = tempfile.mkstemp(prefix=PART_PREFIX, suffix=PART_SUFFIX, dir=root)
        with os.fdopen(fd, "wb") as out:
            out.write(head)
            left = length - len(head)
            while left > 0:
                chunk = take(min(CHUNK, left))
                if not chunk:
                    raise EOFError("short")
                out.write(chunk)
                left -= len(chunk)
    except EOFError:
        _discard(tmp)
        return None, short
    except _Late:
        _discard(tmp)
        return None, _err(
            408, "The body did not arrive in time; send it faster or in one go."
        )
    except OSError as exc:
        _discard(tmp)
        return None, _err(
            507,
            "The clip folder could not be written: %s." % (exc.strerror or "I/O error"),
        )
    except BaseException:
        _discard(tmp)
        raise
    return tmp, None


def _precheck(connect, raw_id, root, stream_path=""):
    """A short read-only look, connection closed before the body is read: the
    row exists, is cutting and has no file. A cheap filter; the conditional
    UPDATE after the body is still the gate. Returns a refusal or None."""
    with connect() as cur:
        row, refusal = _find(cur, raw_id)
    if refusal:
        return refusal
    refusal = owns(row, stream_path)
    if refusal:
        return refusal
    if row["state"] != "cutting":
        return _moved(row)
    name = file_name(row["id"], row["kind"])
    if row.get("file_name") or (name and os.path.lexists(os.path.join(root, name))):
        return _err(409, _EXISTS)
    return None


_EXISTS = "A file for that clip is already saved and is never overwritten."


def upload(
    connect,
    raw_id,
    rfile,
    length,
    root,
    raw_note,
    clock=time.monotonic,
    bound=_no_bound,
    stream_path="",
):
    """POST /api/clips/file: `length` bytes of MP4 from `rfile` into `root`
    under the name the row gives, then the row becomes ready.

    At most MAX_UPLOADS run at once (503 past that). The row is checked first
    with a short read; then the whole body lands in a temporary file with no
    connection held; then `connect()` opens a cursor only for the conditional
    UPDATE and the link into place. The link fails if the name exists, so an
    existing file is never overwritten. A row that moved on while the body
    streamed loses its new file. A `stream_path` the caller names must be the
    row's own (403 otherwise)."""
    if parse_id(raw_id) is None:
        return _err(400, "The id must be a whole number above zero, as id=N.")
    note = clean_note(raw_note)
    if spoofs_view(note):
        return _err(400, _SPOOF)
    if length > MAX_UPLOAD:
        return stage(rfile, length, root, clock, bound)[1]
    if not _SLOTS.acquire(blocking=False):
        return _err(503, "Too many uploads are running; try again shortly.")
    try:
        return _store(
            connect, raw_id, rfile, length, root, note, clock, bound, stream_path
        )
    finally:
        _SLOTS.release()


def _store(connect, raw_id, rfile, length, root, note, clock, bound, stream_path=""):
    refusal = _precheck(connect, raw_id, root, stream_path)
    if refusal:
        return refusal
    tmp, refusal = stage(rfile, length, root, clock, bound)
    if refusal:
        return refusal
    try:
        with connect() as cur:
            row, refusal = _find(cur, raw_id)
            if refusal:
                return refusal
            refusal = owns(row, stream_path)
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
            if os.path.lexists(target):
                return _err(409, _EXISTS)
            try:
                os.link(tmp, target)
            except FileExistsError:
                return _err(409, _EXISTS)
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
