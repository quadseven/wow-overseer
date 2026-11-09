"""GET /api/v2/chat (#2159): recent in-game chat lines, bounded and read only.

    /api/v2/chat?channel=party&family=<key>
    /api/v2/chat?channel=guild&guild=<name>

WHY. The realm's chat reactions could only be checked by reading a stream
screenshot. This answers "did the party react" and "is guild chat alive" from
data.

SCOPE. overseer_chat records the speaker's name and guid, the listener and
the channel, but no guild or family id, and guild_member has no join date. So
party, raid and say lines are scoped by the names of one family (the roster,
never the request), and guild lines by the speaker's guid AND the listener
both being CURRENT members of one family guild. A family or guild outside the
families answers 404. Officer chat is never readable.

KNOWN LIMITATION. Membership is judged as of now, not as of the line. A line
from a member who has since left, or heard only by a listener who has since
left, is not returned; a line spoken before a member joined may still be.
The realm records nothing that tells those apart.

BOUNDS. At most MAX_LIMIT lines (default DEFAULT_LIMIT) from the last
MAX_HOURS hours (default DEFAULT_HOURS), newest first. Both bounds and the
caps are in the payload. A bad number is a 400, never a silent default.

PRIVACY. Whispers, yells and custom channels are not readable: CHANNELS is the
closed list. Each line carries the speaker's name, the channel, the text and
the time, nothing else. Text is returned with game markup stripped, as the
Discord relay does ("markup": "stripped"); addon traffic is dropped.

overseer_chat holds one row per listener, so identical lines are grouped into
one utterance in SQL. READ ONLY: one parameterized SELECT.
"""

from __future__ import annotations

import relay

from . import _scope
from ._scope import holes

CHANNELS = ("party", "raid", "say", "guild")
FAMILY_CHANNELS = ("party", "raid", "say")
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
DEFAULT_HOURS = 24
MAX_HOURS = 72

_HEAD = (
    "SELECT MAX(id) AS line_id, sender_name, channel, text, created_at "
    "FROM overseer_chat WHERE channel = %s AND "
)
_TAIL = (
    " AND created_at > NOW() - INTERVAL %s HOUR "
    "GROUP BY sender_name, channel, text, created_at "
    "ORDER BY line_id DESC LIMIT %s"
)
# {scope} is either a run of placeholders (a family) or a guild subquery.
CHAT_SQL = _HEAD + "{scope}" + _TAIL
_GUILD_SCOPE = (
    "sender_guid IN (SELECT gm.guid FROM guild_member gm "
    "JOIN guild g ON g.guildid = gm.guildid WHERE g.name = %s) "
    "AND heard_by IN (SELECT c.name FROM characters c "
    "JOIN guild_member gm ON gm.guid = c.guid "
    "JOIN guild g ON g.guildid = gm.guildid WHERE g.name = %s)"
)


def _bounded(query: dict, key: str, default: int, cap: int):
    raw = (query.get(key) or [""])[0].strip()
    if not raw:
        return default, None
    if not raw.isdigit() or int(raw) < 1:
        return None, {"error": f"bad {key}"}
    return min(int(raw), cap), None


def _at(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def chat(query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/chat?channel=party&family=X&guild=X&limit=N&hours=N - recent party, raid, say or guild lines, bounded and read only."""
    channel = (query.get("channel") or [""])[0].strip().lower()
    if channel not in CHANNELS:
        return 400, {"error": "bad channel", "channels": list(CHANNELS)}
    limit, err = _bounded(query, "limit", DEFAULT_LIMIT, MAX_LIMIT)
    if err:
        return 400, err
    hours, err = _bounded(query, "hours", DEFAULT_HOURS, MAX_HOURS)
    if err:
        return 400, err

    out = {"channel": channel}
    if channel in FAMILY_CHANNELS:
        asked = (query.get("family") or [""])[0].strip()
        if not asked:
            return 400, {"error": "say family="}
        families = ctx.families.families()
        key = next((k for k in families if k.lower() == asked.lower()), None)
        if key is None:
            return 404, {"error": "no such family", "families": sorted(families)}
        names = list(families[key])
        sql = CHAT_SQL.format(scope="sender_name IN (" + holes(len(names)) + ")")  # noqa: S608
        scope = tuple(names)
        out["family"] = key
    else:
        asked = (query.get("guild") or [""])[0].strip()
        if not asked:
            return 400, {"error": "say guild="}
        name = _scope.guild(ctx, asked)
        if name is None:
            return 404, _scope.no_such_guild(ctx)
        sql = CHAT_SQL.format(scope=_GUILD_SCOPE)  # noqa: S608
        scope = (name, name)
        out["guild"] = name

    rows = ctx.read.rows(sql, (channel, *scope, hours, limit), what="overseer_chat")
    spoken, _ = relay.partition_addon([{**r, "id": r["line_id"]} for r in rows])
    out.update(
        {
            "limit": limit,
            "hours": hours,
            "max_limit": MAX_LIMIT,
            "max_hours": MAX_HOURS,
            "order": "newest first",
            "markup": "stripped",
            "lines": [
                {
                    "id": int(r["line_id"]),
                    "speaker": r["sender_name"],
                    "channel": r["channel"],
                    "text": relay.sanitize(str(r["text"] or "")),
                    "at": _at(r["created_at"]),
                }
                for r in spoken
            ],
        }
    )
    return 200, out


ROUTES = {"/api/v2/chat": chat}
