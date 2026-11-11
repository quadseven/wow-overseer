"""Serving a saved clip: the Range header, and a file streamed in chunks.

Pure apart from the file it is handed: no database, no request object. The map
server decides WHICH file (only a name the ledger holds as ready) and passes an
open file here; nothing in this module sees a request path.
"""

from __future__ import annotations

import re
from typing import BinaryIO, Callable

# One read, one write: a clip is never held in memory whole.
CHUNK = 64 * 1024

CONTENT_TYPE = "video/mp4"

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")

# parse_range answers one of these three kinds of thing.
WHOLE = None  # no usable Range header: send the whole file, 200
UNSATISFIABLE = "unsatisfiable"  # 416


def parse_range(header: str | None, size: int):
    """The (first, last) byte span a Range header asks for, inclusive.

    - no header, a unit other than bytes, or a list of ranges: WHOLE (a server
      may ignore a Range it does not support, and the player copes);
    - `a-b`, `a-` and the suffix `-n` (the last n bytes) inside the file:
      (first, last), with last clamped to the end;
    - anything that names no byte of this file (`a` past the end, `b` before
      `a`, `-0`, an empty file): UNSATISFIABLE.
    """
    if not header:
        return WHOLE
    found = _RANGE.match(header.strip())
    if not found:
        return (
            WHOLE
            if "," in header or not header.strip().startswith("bytes=")
            else UNSATISFIABLE
        )
    first, last = found.groups()
    if not first and not last:
        return UNSATISFIABLE
    if size <= 0:
        return UNSATISFIABLE
    if not first:  # suffix: the last n bytes
        count = int(last)
        if count == 0:
            return UNSATISFIABLE
        return max(0, size - count), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if start >= size or end < start:
        return UNSATISFIABLE
    return start, min(end, size - 1)


def stream(
    source: BinaryIO, out: BinaryIO, start: int, end: int, chunk: int = CHUNK
) -> int:
    """Copy bytes start..end (inclusive) of `source` to `out`, `chunk` at a
    time. Returns how many were sent; a file that ends early sends fewer."""
    source.seek(start)
    left = end - start + 1
    sent = 0
    while left > 0:
        data = source.read(min(chunk, left))
        if not data:
            break
        out.write(data)
        sent += len(data)
        left -= len(data)
    return sent


def headers(size: int, span, *, send: Callable[[str, str], None]) -> int:
    """Send the entity headers for `span` (None = whole file). Returns the
    status: 200 whole, 206 partial."""
    send("Content-Type", CONTENT_TYPE)
    send("Accept-Ranges", "bytes")
    if span is None:
        send("Content-Length", str(size))
        return 200
    start, end = span
    send("Content-Range", "bytes %d-%d/%d" % (start, end, size))
    send("Content-Length", str(end - start + 1))
    return 206
