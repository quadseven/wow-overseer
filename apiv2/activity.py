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

import json
import re

import commandwords

from ._scope import NOT_A_MEMBER, guild_member, wanted_name

LIMIT = 60
LEVEL_DAYS = 7
COMMANDS_SQL = (
    "SELECT id, kind, source, command, target_arg, status, detail, result, "
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


_WHY_IN_RESULT = re.compile(r'"(?:why|reason)":\s*"((?:[^"\\]|\\.)*)"')


def _result_why(result) -> str:
    """The reason a command's JSON `result` gives (its `why`, else `reason`),
    from the whole object or, for a read cut short, the first such field."""
    # str() of bytes would be "b'...'": a BLOB result is decoded first, so
    # json.loads always gets text and only a ValueError can come back.
    if isinstance(result, (bytes, bytearray)):
        result = result.decode("utf-8", "replace")
    text = str(result or "")
    try:
        said = json.loads(text) if text else None
    except ValueError:
        said = None
    if isinstance(said, dict) and (said.get("why") or said.get("reason")):
        return str(said.get("why") or said.get("reason"))
    found = _WHY_IN_RESULT.search(text)
    return found.group(1).replace('\\"', '"') if found else ""


_STATUS_WORDS = {
    "pending": "waiting to be picked up",
    "claimed": "picked up",
    "delivered": "delivered",
    "applied": "done",
    "verifying": "being checked",
    "unchanged": "changed nothing",
    "error": "refused",
}


def answer_words(status: str, detail: str, result=None) -> str:
    """The realm's answer in words. A detail that only points at the result
    ("refused: see result") is replaced by the reason the result gives, and a
    detail that repeats the answer is said once: never "refused: refused"."""
    status, detail = str(status or ""), str(detail or "")
    words = _STATUS_WORDS.get(status, status)
    if detail.endswith("see result"):
        detail = _result_why(result) or "the result row gives no reason"
    if detail == words:
        detail = ""
    elif detail.startswith(words + ": "):
        detail = detail[len(words) + 2 :]
    return words + (": " + detail if detail else "")


def build(
    name: str, commands, levels, level, now_at=None, names: dict | None = None
) -> dict:
    """The activity payload. `names` is table -> id -> name for the ids the
    commands carry (commandwords.wanted), read by the handler."""
    rows = [
        {
            "id": int(r["id"]),
            "at": int(r["at"]) if r.get("at") is not None else None,
            "kind": r.get("kind") or "",
            "source": source_words(r.get("source")),
            "command": r.get("command") or "",
            "said": commandwords.say(r, names),
            "status": r.get("status") or "",
            "answer": answer_words(r.get("status"), r.get("detail"), r.get("result")),
        }
        for r in commands or ()
    ]
    levels = [r for r in levels or () if r.get("at")]
    points = [[int(r["at"]), int(r["new_level"])] for r in levels]
    return {
        "name": name,
        "commands": rows,
        "levels": points,
        "level": level,
        "start_level": int(levels[0]["old_level"]) if levels else level,
        "days": LEVEL_DAYS,
        "checked_at": now_at,
    }


def _names(rd, commands) -> dict:
    """The names of the creatures, items, quests and objects the commands
    name by id: one bounded read per table (commandwords.NAMES_SQL)."""
    out = {}
    for table, ids in commandwords.wanted(commands).items():
        sql = commandwords.NAMES_SQL[table].format(holes=", ".join(["%s"] * len(ids)))
        rows = rd.rows(sql, tuple(ids), what=table)
        out[table] = {int(r["id"]): str(r["name"]) for r in rows if r.get("name")}
    return out


def activity(query: dict, ctx) -> tuple[int, dict]:
    name = wanted_name(query)
    if not guild_member(ctx, name):
        return 404, dict(NOT_A_MEMBER)
    rd = ctx.read
    commands = rd.rows(COMMANDS_SQL, (name, LIMIT), what="overseer_command")
    levels = rd.rows(LEVELS_SQL, (name, LEVEL_DAYS), what="overseer_level")
    now = rd.rows(LEVEL_SQL, (name,), what="characters")
    names = _names(rd, commands)
    level = int(now[0]["level"]) if now else None
    now_at = int(now[0]["now_at"]) if now and now[0].get("now_at") else None
    return 200, build(name, commands, levels, level, now_at, names)


ROUTES = {"/api/v2/activity": activity}
