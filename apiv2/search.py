"""GET /api/v2/search?q=: the app's global search over the realm.

Five groups, each capped at CAP rows: members of the family guilds, items,
quests in the families' quest logs, dungeons, and guild runs. The query text
only ever reaches SQL as a bound LIKE pattern with its wildcards escaped, and
every statement carries a LIMIT, so one keystroke costs a handful of indexed or
bounded reads. Answers are kept in the process for TTL seconds, keyed by the
normalised text, so typing back over a word reads nothing twice.

Read-only, like everything under /api/v2.
"""

from __future__ import annotations

import logging
import threading
import time

import guildrun

log = logging.getLogger(__name__)

MIN_CHARS = 2
MAX_CHARS = 40
CAP = 6
TTL = 60.0
CACHE_MAX = 256
# A search answers while somebody types: no statement may hold the page up.
STATEMENT_MS = 2000
GROUPS = ("members", "items", "quests", "dungeons", "runs")

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()

# Character names compare case-sensitively in this schema, so both sides are
# lowered; the text searched for is lower case already (normalise).
_MEMBERS_SQL = (
    "SELECT c.name, c.level, c.class AS class_id, c.online, g.name AS guild "
    "FROM characters c JOIN guild_member gm ON gm.guid = c.guid "
    "JOIN guild g ON g.guildid = gm.guildid "
    "WHERE LOWER(c.name) LIKE %s AND gm.guildid IN (SELECT gm2.guildid FROM guild_member gm2 "
    "JOIN characters c2 ON c2.guid = gm2.guid WHERE c2.name IN ({holes})) "
    "ORDER BY LOWER(c.name) LIKE %s DESC, c.level DESC, c.name LIMIT %s"
)
_ITEMS_SQL = (
    "SELECT entry, name, Quality AS quality, ItemLevel AS item_level "
    "FROM acore_world.item_template WHERE name LIKE %s AND name NOT LIKE 'Monster - %%' "
    "ORDER BY name LIKE %s DESC, CHAR_LENGTH(name), Quality DESC, entry LIMIT %s"
)
# Quests somebody in a family is on: a quest log row, not every quest in the
# world. Enough rows to fill CAP quests when several members share one.
_QUESTS_SQL = (
    "SELECT t.ID AS quest, t.LogTitle AS title, t.QuestLevel AS level, c.name "
    "FROM characters c JOIN character_queststatus q ON q.guid = c.guid "
    "JOIN acore_world.quest_template t ON t.ID = q.quest "
    "WHERE c.name IN ({holes}) AND t.LogTitle LIKE %s "
    "ORDER BY t.LogTitle LIKE %s DESC, t.LogTitle, c.name LIMIT %s"
)


def normalise(text: str) -> str:
    """The cache key and the text searched for: trimmed, one space, lower case."""
    return " ".join(str(text or "").split()).lower()[:MAX_CHARS]


def like(text: str, prefix: bool = False) -> str:
    """A LIKE pattern matching `text` literally: its own % and _ are escaped."""
    body = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return body + "%" if prefix else "%" + body + "%"


def empty(q: str) -> dict:
    return {"q": q, **{g: [] for g in GROUPS}}


def _members(cur, q: str, roster: list, class_names: dict) -> list:
    if not roster:
        return []
    holes = ", ".join(["%s"] * len(roster))
    # S608: only placeholders are formatted in; every value is bound.
    sql = _MEMBERS_SQL.format(holes=holes)  # noqa: S608
    cur.execute(sql, (like(q), *roster, like(q, True), CAP))
    return [
        {
            "name": r["name"],
            "level": r.get("level"),
            "class": class_names.get(r.get("class_id"), ""),
            "guild": r.get("guild") or "",
            "online": bool(r.get("online")),
        }
        for r in cur.fetchall()[:CAP]
    ]


def _items(cur, q: str, icons: dict) -> list:
    cur.execute(_ITEMS_SQL, (like(q), like(q, True), CAP))
    return [
        {
            "entry": int(r["entry"]),
            "name": r["name"],
            "quality": r.get("quality"),
            "item_level": r.get("item_level"),
            "icon": icons.get(int(r["entry"])),
        }
        for r in cur.fetchall()[:CAP]
    ]


def _quests(cur, q: str, roster: list) -> list:
    if not roster:
        return []
    holes = ", ".join(["%s"] * len(roster))
    sql = _QUESTS_SQL.format(holes=holes)  # noqa: S608
    cur.execute(sql, (*roster, like(q), like(q, True), CAP * 10))
    out: dict[int, dict] = {}
    for r in cur.fetchall():
        quest = out.get(r["quest"])
        if quest is None:
            if len(out) >= CAP:
                continue
            quest = {
                "quest": int(r["quest"]),
                "title": r["title"],
                "level": r.get("level"),
                "holders": [],
            }
            out[quest["quest"]] = quest
        quest["holders"].append(r["name"])
    return list(out.values())


def _dungeon_maps(q: str, map_names: dict) -> list:
    hits = [(m, n) for m, n in map_names.items() if q in n.lower()]
    hits.sort(key=lambda p: (not p[1].lower().startswith(q), p[1]))
    return hits[:CAP]


def _keywords_for(q: str, maps: list, keywords: dict, place) -> list:
    """Run keywords whose map matched, or whose place names the text."""
    wanted = {m for m, _n in maps}
    return sorted(
        k for k, (m, _w) in keywords.items() if m in wanted or q in place(k).lower()
    )


def _runs(cur, q: str, keywords: list) -> list:
    """Runs at a matched dungeon or with a member named like `q`; a world
    without the table has none yet (guildrun.matching)."""
    return guildrun.matching(cur, keywords, like(q), CAP * 4)


def _run_rows(rows: list, place) -> list:
    return [
        {
            "id": r["id"],
            "guild": r.get("guild") or "",
            "place": place(r.get("keyword") or ""),
            "state": r.get("state") or "",
            "run_state": guildrun.run_state(r),
            "outcome": r.get("outcome") or "",
            "bosses_done": r.get("bosses_done"),
            "bosses_total": r.get("bosses_total"),
            "when": str(r.get("created_at") or ""),
        }
        for r in rows[:CAP]
    ]


def _dungeon_rows(
    maps: list, run_rows: list, keywords: dict, default_guild: str
) -> list:
    """Each dungeon, with the guild whose runs page shows it most recently."""
    latest: dict[int, str] = {}
    for r in run_rows:
        known = keywords.get(r.get("keyword") or "")
        if known and known[0] not in latest and r.get("guild"):
            latest[known[0]] = r["guild"]
    return [
        {"map": m, "name": n, "guild": latest.get(m, default_guild)} for m, n in maps
    ]


def _limit_statements(cur) -> None:
    try:
        cur.execute("SET SESSION MAX_EXECUTION_TIME = %s", (STATEMENT_MS,))
    except Exception:  # noqa: BLE001 - a server without the setting still answers
        log.warning(
            "search: the database refused MAX_EXECUTION_TIME; statements rely on their LIMITs"
        )


def build(q: str, conn, server) -> dict:
    """The five groups for `q` (already normalised), from one connection."""
    roster = list(server._all_roster_names())
    keywords = server.council.DUNGEON_KEYWORDS
    place = server.council.keyword_place
    guilds = list(server.guildrun.limits().guilds)
    maps = _dungeon_maps(q, server.achievements.MAP_NAMES)
    with conn.cursor() as cur:
        _limit_statements(cur)
        members = _members(cur, q, roster, server._MAP_CLASS_NAMES)
        items = _items(cur, q, server.ITEMS.icons)
        quests = _quests(cur, q, roster)
        run_rows = _runs(cur, q, _keywords_for(q, maps, keywords, place))
    return {
        "q": q,
        "members": members,
        "items": items,
        "quests": quests,
        "dungeons": _dungeon_rows(
            maps, run_rows, keywords, guilds[0] if guilds else ""
        ),
        "runs": _run_rows(run_rows, place),
    }


def _cached(q: str, now: float) -> dict | None:
    with _lock:
        hit = _cache.get(q)
        return hit[1] if hit and now - hit[0] < TTL else None


def _keep(q: str, now: float, payload: dict) -> None:
    with _lock:
        _cache.pop(q, None)
        _cache[q] = (now, payload)
        while len(_cache) > CACHE_MAX:
            _cache.pop(next(iter(_cache)))


def search(query: dict, ctx) -> tuple[int, dict]:
    q = normalise(query.get("q", [""])[0])
    if len(q) < MIN_CHARS:
        return 200, empty(q)
    now = time.monotonic()
    hit = _cached(q, now)
    if hit is not None:
        return 200, hit
    conn = ctx.connect()
    try:
        payload = build(q, conn, ctx.server)
    finally:
        conn.close()
    _keep(q, now, payload)
    return 200, payload


ROUTES = {"/api/v2/search": search}
