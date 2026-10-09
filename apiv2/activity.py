"""GET /api/v2/activity?name=X: the commands a member was given, with the realm's answers.

Every row of overseer_command addressed to the member, newest first, as the
bridge wrote it (who asked: its `source`) and as the realm answered it (its
`status`, and `detail` when it refused). The aura probes the Family tab sends
every few seconds are left out: they are reads, not commands.

Beside them, the member's level-ups over the last week (overseer_level), the
level line the profile draws.

Gated like every v2 read that takes a name.
"""

from __future__ import annotations

from ._scope import NOT_A_MEMBER, guarded, guild_member, wanted_name

LIMIT = 60
LEVEL_DAYS = 7
COMMANDS_SQL = (
    "SELECT id, kind, source, command, status, detail, "
    "UNIX_TIMESTAMP(created_at) AS at, UNIX_TIMESTAMP(updated_at) AS answered_at "
    "FROM overseer_command WHERE target_name = %s AND kind <> 'probe' "
    "AND source <> 'api:auras' ORDER BY id DESC LIMIT %s"
)
LEVELS_SQL = (
    "SELECT old_level, new_level, UNIX_TIMESTAMP(created_at) AS at FROM overseer_level "
    "WHERE character_name = %s AND created_at > NOW() - INTERVAL %s DAY "
    "ORDER BY created_at, id"
)
LEVEL_SQL = "SELECT level, UNIX_TIMESTAMP() AS now_at FROM characters WHERE name = %s"

# The bridge's sources, in words. A source not named here is shown as written.
SOURCES = {
    "guildjobs": "guild jobs",
    "overseer:guildsocial": "guild chat",
    "overseer:guildpug": "pick-up group",
    "overseer:life": "life rules",
    "overseer:equip": "equip",
    "overseer:queue": "dungeon queue",
    "overseer:guildrun": "guild run",
    "overseer:town-errand": "town errand",
    "questshare": "quest share",
    "economy": "economy",
    "towntrip": "town trip",
}


def source_words(source: str) -> str:
    """'guildjobs:classquest-walk:Chopp' -> 'guild jobs, classquest walk'."""
    s = str(source or "")
    if s in SOURCES:
        return SOURCES[s]
    head, _, rest = s.partition(":")
    if head in SOURCES and rest:
        job = rest.split(":")[0].replace("-", " ")
        return SOURCES[head] + ", " + job
    return s


def answer_words(status: str, detail: str) -> str:
    status, detail = str(status or ""), str(detail or "")
    words = {
        "pending": "waiting to be picked up",
        "claimed": "picked up",
        "delivered": "delivered",
        "applied": "done",
        "verifying": "being checked",
        "unchanged": "changed nothing",
        "error": "refused",
    }.get(status, status)
    return words + (": " + detail if detail else "")


def build(name: str, commands, levels, level, now_at=None) -> dict:
    rows = [
        {
            "id": int(r["id"]),
            "at": int(r["at"]) if r.get("at") is not None else None,
            "kind": r.get("kind") or "",
            "source": source_words(r.get("source")),
            "command": r.get("command") or "",
            "status": r.get("status") or "",
            "answer": answer_words(r.get("status"), r.get("detail")),
        }
        for r in commands or ()
    ]
    points = [[int(r["at"]), int(r["new_level"])] for r in levels or () if r.get("at")]
    return {
        "name": name,
        "commands": rows,
        "levels": points,
        "level": level,
        "start_level": int(levels[0]["old_level"]) if levels else level,
        "days": LEVEL_DAYS,
        "checked_at": now_at,
    }


def activity(query: dict, ctx) -> tuple[int, dict]:
    name = wanted_name(query)
    if not guild_member(ctx, name):
        return 404, dict(NOT_A_MEMBER)
    conn = ctx.connect()
    try:
        with conn.cursor() as cur:
            commands = guarded(
                ctx, cur, COMMANDS_SQL, (name, LIMIT), "overseer_command"
            )
            levels = guarded(ctx, cur, LEVELS_SQL, (name, LEVEL_DAYS), "overseer_level")
            now = guarded(ctx, cur, LEVEL_SQL, (name,), "characters")
    finally:
        conn.close()
    level = int(now[0]["level"]) if now else None
    now_at = int(now[0]["now_at"]) if now and now[0].get("now_at") else None
    return 200, build(name, commands, levels, level, now_at)


ROUTES = {"/api/v2/activity": activity}
