"""GET /api/v2/raidteams?guild=<cave|bonkers>: the approved Molten Core seats.

The shape the app's Raid view draws its eight groups from:

    {guild, groups: [[name | null] x 5] x 8, gaps: {tanks, healers, damage},
     seats: [[seat] x 5] x 8, members: {name: {...}}, consumable_items: [...]}

WHO SITS WHERE is raidteams.py's approved lineup, matched against the guild
the way raidlineup._approved_lineup matches it: a seat is filled by the
character of its approved name, or of the name it has until the rename, when
that character is in the guild. Any other seat is open and stays null: an
open seat is never filled with a guess.

THE RAID FIELDS PER MEMBER are read, never inferred:
- `attuned`: Attunement to the Core rewarded (raidready.ATTUNEMENT_QUESTS);
- `fire_resistance`: fire resistance summed over worn items, as raidready
  counts it (enchants and auras are not counted);
- `consumables`: {item entry: count} of the Molten Core night's consumables
  (raidsupply.SUPPLIES) in the member's bags and bank.
A read the realm cannot answer (a missing table or column) leaves that field
null for every member, which the app shows as "not measured". Zero is only
ever a measured zero.

Read-only, one connection, four reads bound to the seat names.
"""

from __future__ import annotations

import armory
import raidlineup
import raidready
import raidroles
import raidsupply
import raidteams

GROUPS = 8
GROUP_SIZE = 5

# Every consumable a Molten Core night wants, in raidsupply's order.
CONSUMABLES = tuple(dict.fromkeys(s.entry for s in raidsupply.SUPPLIES))
_NAMES = {s.entry: s.name for s in raidsupply.SUPPLIES}

_GAP_KEY = {
    raidroles.SEAT_TANK: "tanks",
    raidroles.SEAT_HEALER: "healers",
    raidroles.SEAT_DAMAGE: "damage",
}

# Characters of the seat names and the guild each is in. The guild is decided
# from the answer (the guild holding most of them), not from its name.
MEMBERS_SQL = (
    "SELECT c.name, c.level, c.class AS class_id, c.online, gm.guildid "
    "FROM characters c JOIN guild_member gm ON gm.guid = c.guid "
    "WHERE c.name IN ({holes})"
)
ATTUNED_SQL = (
    "SELECT DISTINCT c.name FROM characters c "
    "JOIN character_queststatus_rewarded q ON q.guid = c.guid "
    "WHERE c.name IN ({holes}) AND q.quest IN ({quests})"
)
WORN_SQL = (
    "SELECT c.name, it.fire_res FROM characters c "
    "JOIN character_inventory ci ON ci.guid = c.guid AND ci.bag = 0 "
    "AND ci.slot < %s JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN ({holes})"
)
CONSUMABLES_SQL = (
    "SELECT c.name, ii.itemEntry AS entry, SUM(ii.count) AS count "
    "FROM characters c JOIN character_inventory ci ON ci.guid = c.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "WHERE c.name IN ({holes}) AND ii.itemEntry IN ({entries}) "
    "GROUP BY c.name, ii.itemEntry"
)

# A schema this realm does not carry: no such table (1146) or column (1054).
_UNREADABLE = (1054, 1146)


def guild_key(query: dict) -> str:
    """The approved guild the query names, matched without case, or ""."""
    asked = ((query.get("guild") or [""])[0] or "").strip().lower()
    for key in raidteams.GROUPS:
        if key.lower() == asked:
            return key
    return ""


def unreadable(exc: BaseException) -> bool:
    """A driver error saying the table or column is not there. Matched by the
    driver's module and error code, so this module does not import it."""
    return (
        type(exc).__module__.split(".")[0] == "pymysql"
        and bool(exc.args)
        and exc.args[0] in _UNREADABLE
    )


def _holes(n: int) -> str:
    return ", ".join(["%s"] * n)


def _read(cur, sql: str, params: tuple):
    """The rows, or None when this realm cannot answer the read at all."""
    try:
        cur.execute(sql, params)
        return list(cur.fetchall())
    except Exception as exc:
        if unreadable(exc):
            return None
        raise


def seat_names(guild: str) -> list:
    """Every name a seat of `guild` may be found under, approved or current."""
    out = []
    for seat in raidteams.seats(guild):
        out.append(seat.name)
        if seat.was:
            out.append(seat.was)
    return list(dict.fromkeys(out))


def fetch(cur, guild: str) -> dict:
    """The four reads for `guild`, each None when the realm cannot answer."""
    names = seat_names(guild)
    members = _read(cur, MEMBERS_SQL.format(holes=_holes(len(names))), tuple(names))  # noqa: S608
    found = sorted({r["name"] for r in in_guild(members or [])})
    out = {"members": members, "attuned": [], "worn": [], "consumables": []}
    if not found:
        return out
    holes = _holes(len(found))
    quests = raidready.ATTUNEMENT_QUESTS
    # S608: every format argument is a run of placeholders sized by a list
    # this module owns; every value is bound by the driver.
    out["attuned"] = _read(
        cur,
        ATTUNED_SQL.format(holes=holes, quests=_holes(len(quests))),  # noqa: S608
        (*found, *quests),
    )
    out["worn"] = _read(
        cur,
        WORN_SQL.format(holes=holes),  # noqa: S608
        (len(armory.EQUIPPED_SLOTS), *found),
    )
    out["consumables"] = _read(
        cur,
        CONSUMABLES_SQL.format(holes=holes, entries=_holes(len(CONSUMABLES))),  # noqa: S608
        (*found, *CONSUMABLES),
    )
    return out


def in_guild(rows: list) -> list:
    """The rows of the one guild holding most of the seat names."""
    count: dict = {}
    for row in rows:
        gid = row.get("guildid")
        if gid is not None:
            count[gid] = count.get(gid, 0) + 1
    if not count:
        return []
    best = max(sorted(count), key=lambda g: count[g])
    return [r for r in rows if r.get("guildid") == best]


def _seat(seat, row: dict | None) -> dict:
    return {
        "name": row["name"] if row else None,
        "approved": seat.name,
        "seat": seat.seat,
        "class_id": seat.class_id,
        "class": raidlineup.CLASS_NAMES.get(seat.class_id, ""),
        "tree": seat.tree,
        "fire_aura": seat.fire_resistance,
        "level": row.get("level") if row else None,
    }


def _per_name(rows, value) -> dict | None:
    """{name: value(rows of that name)} or None when the read failed."""
    if rows is None:
        return None
    out: dict = {}
    for row in rows:
        out.setdefault(row.get("name"), []).append(row)
    return {name: value(group) for name, group in out.items()}


def _consumables(rows: list) -> dict:
    return {str(int(r["entry"])): int(r.get("count") or 0) for r in rows}


def _member(row: dict, attuned, fire, carried) -> dict:
    name = row["name"]
    return {
        "level": row.get("level"),
        "class_id": row.get("class_id"),
        "class": raidlineup.CLASS_NAMES.get(row.get("class_id"), ""),
        "online": bool(row.get("online")),
        "attuned": None if attuned is None else name in attuned,
        "fire_resistance": None if fire is None else fire.get(name, 0),
        "consumables": None if carried is None else carried.get(name, {}),
    }


def seat_grid(guild: str, rows: dict) -> tuple:
    """(groups, seats, gaps): each approved seat filled by the member found
    under its approved or current name, or left open and counted as a gap."""
    groups, seats = [], []
    gaps = {"tanks": 0, "healers": 0, "damage": 0}
    for approved in raidteams.GROUPS[guild]:
        placed = []
        for seat in approved:
            row = rows.get(seat.name) or (rows.get(seat.was) if seat.was else None)
            placed.append(_seat(seat, row))
            if row is None:
                gaps[_GAP_KEY[seat.seat]] += 1
        seats.append(placed)
        groups.append([s["name"] for s in placed])
    return groups, seats, gaps


def raid_fields(fetched: dict) -> tuple:
    """(attuned names, fire by name, consumables by name), each None when its
    read could not be answered."""
    attuned_rows = fetched.get("attuned")
    attuned = None if attuned_rows is None else {r.get("name") for r in attuned_rows}
    worn = fetched.get("worn")
    fire = None if worn is None else raidready.fire_resistance(worn)
    return attuned, fire, _per_name(fetched.get("consumables"), _consumables)


def build(guild: str, fetched: dict) -> dict:
    """The payload for `guild` from fetch()'s rows. Pure."""
    rows = {r["name"]: r for r in in_guild(fetched.get("members") or [])}
    groups, seats, gaps = seat_grid(guild, rows)
    seated = [s["name"] for group in seats for s in group if s["name"]]
    attuned, fire, carried = raid_fields(fetched)
    return {
        "guild": guild,
        "groups": groups,
        "gaps": gaps,
        "seats": seats,
        "seated": len(seated),
        "members": {n: _member(rows[n], attuned, fire, carried) for n in seated},
        "consumable_items": [{"entry": e, "name": _NAMES[e]} for e in CONSUMABLES],
    }


def raidteams_read(query: dict, ctx) -> tuple[int, dict]:
    guild = guild_key(query)
    if not guild:
        return 400, {
            "error": "guild must be one of the approved guilds",
            "guilds": [g.lower() for g in raidteams.GROUPS],
        }
    conn = ctx.connect()
    try:
        with conn.cursor() as cur:
            fetched = fetch(cur, guild)
    finally:
        conn.close()
    return 200, build(guild, fetched)


ROUTES = {"/api/v2/raidteams": raidteams_read}
