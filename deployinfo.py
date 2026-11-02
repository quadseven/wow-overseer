"""Which build this bridge process runs, and how long it has run.

When several ships land close together nobody can tell from outside which
commit is live or whether a rollout is still going. The image carries its own
commit (the Dockerfile bakes OVERSEER_COMMIT and OVERSEER_BUILT from the build
workflow); the deploy may also pass OVERSEER_PREVIOUS_COMMIT and
OVERSEER_SHIP_PR. Anything unset reads "unknown" (tests, local runs), never an
error.

The bridge logs startup_line() once at start. The site is a separate process
that can outlive a bridge crash, so the bridge renews a memo row carrying its
own start time every BEAT_SECONDS, and /api/realm reports info(started) from
that row as `deploy`. `starting` is true for STARTING_SECONDS after the bridge
begins, so the dashboard can say "restarting" while a rollout settles. A bridge
that stops renewing loses the row after KEEP_SECONDS, and then the uptime is
null rather than a count over a dead process.
"""

from __future__ import annotations

import os
import time

UNKNOWN = "unknown"
STARTING_SECONDS = 90
SHA_LEN = 12

# The bridge's row in its memo store (overseer_bridge_memo); `since` is its start.
MEMO_KIND = "deploy"
MEMO_SUBJECT = "bridge"
BEAT_SECONDS = 30
KEEP_SECONDS = 3 * BEAT_SECONDS
BRIDGE_READ_SQL = (
    "SELECT since FROM overseer_bridge_memo "
    "WHERE kind = %s AND subject = %s AND expires > UNIX_TIMESTAMP()"
)

PROCESS_STARTED = time.time()


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip() or UNKNOWN


def _sha(name: str) -> str:
    value = _env(name).lower()
    ok = value != UNKNOWN and all(c in "0123456789abcdef" for c in value)
    return value[:SHA_LEN] if ok else UNKNOWN


def _pr() -> int | None:
    raw = (os.environ.get("OVERSEER_SHIP_PR") or "").strip().lstrip("#")
    return int(raw) if raw.isdigit() else None


def startup_line() -> str:
    return "bridge up: commit %s, previous %s, built %s" % (
        _sha("OVERSEER_COMMIT"),
        _sha("OVERSEER_PREVIOUS_COMMIT"),
        _env("OVERSEER_BUILT"),
    )


def info(started: float | None, now: float | None = None) -> dict:
    """The `deploy` field for a bridge that began at `started`, None if unknown."""
    up = None
    if started is not None:
        up = max(0, int((time.time() if now is None else now) - started))
    return {
        "commit": _sha("OVERSEER_COMMIT"),
        "previous": _sha("OVERSEER_PREVIOUS_COMMIT"),
        "built": _env("OVERSEER_BUILT"),
        "ship_pr": _pr(),
        "started_at": None if started is None else int(started),
        "uptime_seconds": up,
        "starting": up is not None and up < STARTING_SECONDS,
    }
