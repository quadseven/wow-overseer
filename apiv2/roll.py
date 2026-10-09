"""GET /api/v2/roll: the last roll this realm took, as far as the realm says.

    {build, when, channel, shipped: [string], ...}

Everything here is read from the realm's own database, the same rule the realm
banner follows (realm.py): a site pointed at a database shows that database's
build, never one taken from its own configuration.

What the realm can and cannot tell:

- build    overseer_build's module version and AzerothCore's own revision
           (acore_world.version when the module has not reported), through the
           realm banner's own reader, so the two never disagree.
- when     the time the worldserver wrote that report, which it does once at
           every start. A roll restarts the worldserver, so this is when the
           running build took over; a restart without a roll moves it too.
- channel  null. The roller's channel and release names live in the
           deployment's own files, and the realm does not record them.
- shipped  null, for the same reason: what a release changed is written in its
           release file, not in the realm.

Beside those, `uptime_seconds` is the worldserver's uptime from
acore_auth.uptime, which the Now strip shows next to the build. Any field that
cannot be read is null and `unmeasured` says why, so the app can say "not
measured" instead of inventing a value.
"""

from __future__ import annotations

from datetime import datetime

import realm

BUILD_SQL = "SELECT name, value, source, reported_at FROM overseer_build"
VERSION_SQL = "SELECT core_version FROM acore_world.version LIMIT 1"
UPTIME_SQL = "SELECT UNIX_TIMESTAMP() - MAX(starttime) AS up FROM acore_auth.uptime"

WHY = {
    "build": "The realm has reported neither its module version nor its core revision.",
    "when": "The worldserver has not written its build report (overseer_build).",
    "channel": "The realm does not record which roller channel it runs; that "
    "lives in the deployment's channel file.",
    "shipped": "The realm does not record what a roll changed; that lives in "
    "the deployment's release files.",
    "uptime_seconds": "The worldserver's uptime table (acore_auth.uptime) has no row.",
}


def _build(banner: dict) -> str | None:
    parts = []
    if banner.get("core_revision"):
        parts.append("core " + banner["core_revision"])
    if banner.get("module_version"):
        parts.append("module " + banner["module_version"])
    return ", ".join(parts) or None


def _uptime(uptime_rows: list) -> int | None:
    if not uptime_rows:
        return None
    row = uptime_rows[0]
    up = row.get("up") if isinstance(row, dict) else (row[0] if row else None)
    if up is None:
        return None
    return max(0, int(up))


def build_roll(
    build_rows: list,
    version_rows: list,
    uptime_rows: list,
    now: datetime | None = None,
) -> dict:
    """Rows in, the roll's JSON out. Pure: every input may be empty."""
    banner = realm.build_realm(build_rows, version_rows, [], now=now)
    payload = {
        "build": _build(banner),
        "when": banner["reported_at"],
        "when_seconds": banner["reported_seconds"],
        "channel": None,
        "shipped": None,
        "uptime_seconds": _uptime(uptime_rows),
        "module_version": banner["module_version"] or None,
        "core_revision": banner["core_revision"] or None,
    }
    payload["unmeasured"] = {k: why for k, why in WHY.items() if payload[k] is None}
    return payload


def roll(_query: dict, ctx) -> tuple[int, dict]:
    guarded = ctx.server._realm_guarded
    conn = ctx.connect()
    try:
        with conn.cursor() as cur:
            build_rows = guarded(cur, BUILD_SQL, "overseer_build")
            version_rows = guarded(cur, VERSION_SQL, "acore_world.version")
            uptime_rows = guarded(cur, UPTIME_SQL, "acore_auth.uptime")
    finally:
        conn.close()
    return 200, build_roll(build_rows, version_rows, uptime_rows)


ROUTES = {"/api/v2/roll": roll}
