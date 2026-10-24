"""Which build this bridge process runs, and how long it has run.

When several ships land close together nobody can tell from outside which
commit is live or whether a rollout is still going. The image carries its own
commit (the Dockerfile bakes OVERSEER_COMMIT and OVERSEER_BUILT from the build
workflow); the deploy may also pass OVERSEER_PREVIOUS_COMMIT and
OVERSEER_SHIP_PR. Anything unset reads "unknown" (tests, local runs), never an
error.

The bridge logs startup_line() once at start. /api/realm reports info() as
`deploy`; `starting` is true for STARTING_SECONDS after the process begins, so
the dashboard can say "restarting" while a rollout settles.
"""

from __future__ import annotations

import os
import time

UNKNOWN = "unknown"
STARTING_SECONDS = 90
SHA_LEN = 12

_started = time.time()


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


def info(
    now: float | None = None,
    started=None,
    started_at=None,
    bridge_started=None,
    bridge_started_at=None,
) -> dict:
    base = _started
    for cand in (started, started_at, bridge_started, bridge_started_at):
        if cand is not None:
            base = cand
    up = max(0, int((time.time() if now is None else now) - base))
    return {
        "commit": _sha("OVERSEER_COMMIT"),
        "previous": _sha("OVERSEER_PREVIOUS_COMMIT"),
        "built": _env("OVERSEER_BUILT"),
        "ship_pr": _pr(),
        "started_at": int(base),
        "uptime_seconds": up,
        "starting": up < STARTING_SECONDS,
    }
