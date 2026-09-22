"""The last frame of a character's own screen, and why there isn't one.

WHY THIS EXISTS. The overseer can read a character's position, bags, spells and
strategies and still have no idea what is happening to it. #2663 gives Evan
video; this gives everyone - including whatever is reading these tables - a
still. A frame is the one instrument here that SHOWS the game rather than
describing it.

WHY A STATUS AND NOT JUST "POST NOTHING WHEN IT FAILS". PrintWindow on a
Direct3D client can return a perfectly valid all-black bitmap. Rendered on the
panel that reads as a stalled bot; SILENCE reads as a stalled capture. They are
different problems with different owners, and only an explicit status tells
them apart. `detail` carries the same argument one level deeper - `failed`
alone tells a viewer exactly as much as silence did, and the reason that
matters most is "the selfbot never attached, so we refused to keep the client",
which is a deliberate stop rather than a nothing.

TRUSTED NETWORK, NOT VERIFIED SOURCE. The page is tailnet-only and these
endpoints have no auth, in step with every other endpoint here. Anything on the
tailnet can post a frame under any name, so what the panel shows is whatever
the last poster said it was. Fine for a homelab, and NOT attestation - nothing
should ever be built on a frame proving whose screen it was.
"""

from __future__ import annotations

MAX_FRAME_BYTES = 512 * 1024
MAX_DETAIL_CHARS = 200

OK = "ok"
BLACK = "black"
FAILED = "failed"
STATUSES = (OK, BLACK, FAILED)

# The first three bytes of every JPEG. Checked because a caller posting a PNG,
# an HTML error page or a truncated upload would otherwise be stored happily
# and render as a broken image with nothing anywhere saying why.
JPEG_MAGIC = b"\xff\xd8\xff"


def is_jpeg(body: bytes) -> bool:
    return len(body) >= 3 and body[:3] == JPEG_MAGIC


def clean_detail(raw) -> str:
    """A failure reason a person can read, or empty."""
    if not isinstance(raw, str):
        return ""
    return " ".join(raw.split())[:MAX_DETAIL_CHARS]


def accept(current, status: str, body: bytes, detail, now: float) -> dict:
    """The stored record after a post. `now` is passed in, so the rules are
    testable without a clock.

    A FAILURE KEEPS THE LAST GOOD FRAME. Throwing away the only picture of a
    character because the newest capture came back black replaces something
    useful with nothing, and the frame's own age already stops it passing as
    live. Two clocks are kept deliberately: `frame_at` is when the PICTURE was
    taken, `at` is when anything last tried. A viewer looking at a stale
    picture needs the second one more than the first - it is the difference
    between "nobody is looking any more" and "we are looking and it is
    failing".
    """
    prior = current or {}
    ok = status == OK
    return {
        "jpeg": body if ok else prior.get("jpeg"),
        "frame_at": now if ok else prior.get("frame_at"),
        "status": status,
        "detail": clean_detail(detail),
        "at": now,
    }


def describe(record, now: float) -> dict:
    """What the panel is told. Ages in seconds, never raw timestamps - the
    bridge and the browser need not agree on a clock, and a frame reported an
    hour stale because of a timezone would be maddening to chase.
    """
    if not record:
        return {
            "has_frame": False,
            "bytes": 0,
            "status": None,
            "detail": "",
            "captured_seconds_ago": None,
            "tried_seconds_ago": None,
        }
    jpeg = record.get("jpeg")
    frame_at = record.get("frame_at")
    at = record.get("at")
    return {
        "has_frame": bool(jpeg),
        "bytes": len(jpeg) if jpeg else 0,
        "status": record.get("status"),
        "detail": record.get("detail") or "",
        "captured_seconds_ago": None
        if frame_at is None
        else max(0, int(now - frame_at)),
        "tried_seconds_ago": None if at is None else max(0, int(now - at)),
    }


def refusal(name: str, status: str, body: bytes, detail) -> str:
    """Why a post is rejected, or empty if it is fine.

    Returned as a sentence rather than a bool: the agent posting these is on
    another machine and a 400 with no reason is the same dead end as a silent
    capture.
    """
    if status not in STATUSES:
        return f"status must be one of {', '.join(STATUSES)}"
    if len(body) > MAX_FRAME_BYTES:
        return f"frame is larger than {MAX_FRAME_BYTES} bytes"
    if isinstance(detail, str) and len(detail) > MAX_DETAIL_CHARS:
        return f"detail is longer than {MAX_DETAIL_CHARS} characters"
    if status == OK and not body:
        return "status ok needs a frame"
    if status == OK and not is_jpeg(body):
        return "frame is not a jpeg"
    return ""
