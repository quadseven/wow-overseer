"""GET /api/v2/audit: six player-level facts for every member worth watching (#374).

WHY THIS EXISTS. The playing realm sends almost no player-level signal: stalls,
death loops, empty gear slots and unopened mail go unnoticed until someone
reads the tables by hand. The metrics backend is off, so the signal comes from
the site API, and this read is the one place those six facts sit side by side.

WHO. Every roster member (families.Families.names), online or not, and every
other member of a family guild that presence.of reads as online now. Nothing
from the request reaches the SQL: the read takes no parameter.

THE SIX FIELDS, per member:

  since_moved_s      seconds since the last progress event (a quest, a level,
                     a gear change off overseer_event, or a boss credit off
                     overseer_dungeon_run_event: the Now page's
                     agenda.MOVEMENT_KINDS, by the database's own clock).
                     A family member reads its FAMILY's newest movement, as
                     the Now page judges a stall per family (agenda.compose,
                     members._stalled_leaders): a follower with no event of
                     its own is as quiet as its family, not unknown, and a
                     family whose only progress is boss credits on a repeated
                     clear is moving. A guildmate outside the families reads
                     its own events. None when no such event is kept:
                     unknown is not stalled (agenda.stalled).
  deaths_last_hour   overseer_death rows in the last DEATH_WINDOW_SECONDS.
  slots_filled       worn stat slots out of `slots` (the 17 guildgear counts:
                     every equipment slot but the shirt and the tabard), beside
  wearable_in_bags   weapons and armour carried in the backpack or a carried
                     bag that the member's level allows (RequiredLevel).
  item_level         the average item level of what is worn in those slots,
                     beside `level`, the character's level. None when nothing
                     is worn.
  mail_uncollected   delivered letters that still hold an item or money.
  hours_at_level     characters.leveltime in hours: PLAYED time at the current
                     level, not wall-clock time (digest.py says why).

`stalled` and `empty_slots` name the members a reader looks for first: a
member quiet longer than agenda.STALL_AFTER (every member of a stalled
family), and a member with any empty stat slot.

READ ONLY. Every statement here is a SELECT through the request's realm
reader; nothing is written, and tests/test_apiv2_audit.py runs the handler and
fails on any statement that is not one.
"""

from __future__ import annotations

import agenda
import guildgear
from panel import _BACKPACK_SLOTS, _BAG_SLOTS, _EQUIPMENT_SLOT_NAMES

from ._scope import holes
from .members import BOSS_SQL, MOVED_SQL

DEATH_WINDOW_SECONDS = 3600
STAT_SLOTS = len(guildgear.STAT_SLOTS)
_COSMETIC_SLOTS = frozenset(
    i for i, s in enumerate(_EQUIPMENT_SLOT_NAMES) if s in guildgear.COSMETIC
)

CHARS_SQL = "SELECT name, level, leveltime FROM characters WHERE name IN ({holes})"
# One row per worn item (bag 0, the paper doll). LEFT on the item tables so a
# custom or removed item still counts as a filled slot.
WORN_SQL = (
    "SELECT c.name, ci.slot, it.ItemLevel AS item_level FROM characters c "
    "JOIN character_inventory ci ON ci.guid = c.guid "
    "AND ci.bag = 0 AND ci.slot < {slots} "
    "LEFT JOIN item_instance ii ON ii.guid = ci.item "
    "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN ({holes})"
)
# Weapons (class 2) and armour (class 4) that go in an equipment slot, carried
# in the backpack or inside one of the four carried bags, and allowed at the
# member's level. The slot bounds are panel's ranges.
BAGS_SQL = (
    "SELECT c.name, COUNT(*) AS wearable FROM characters c "
    "JOIN character_inventory ci ON ci.guid = c.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN ({holes}) AND it.class IN (2, 4) "
    "AND it.InventoryType <> 0 AND it.RequiredLevel <= c.level "
    "AND ((ci.bag = 0 AND ci.slot BETWEEN {pack_first} AND {pack_last}) "
    "OR ci.bag IN (SELECT bag.item FROM character_inventory bag "
    "WHERE bag.guid = ci.guid AND bag.bag = 0 "
    "AND bag.slot BETWEEN {bag_first} AND {bag_last})) "
    "GROUP BY c.name"
)
MAIL_SQL = (
    "SELECT r.name, COUNT(*) AS letters FROM mail m "
    "JOIN characters r ON r.guid = m.receiver "
    "WHERE r.name IN ({holes}) AND m.deliver_time <= UNIX_TIMESTAMP() "
    "AND (m.has_items <> 0 OR m.money > 0) GROUP BY r.name"
)
DEATHS_SQL = (
    "SELECT character_name AS name, COUNT(*) AS deaths FROM overseer_death "
    "WHERE character_name IN ({holes}) "
    "AND created_at > NOW() - INTERVAL %s SECOND GROUP BY character_name"
)
CLOCK_SQL = "SELECT UNIX_TIMESTAMP() AS now_at"

BASIS = (
    "Every roster member and every online member of a family guild. Moved is "
    "the last quest, level, gear change or boss credit, of the whole family "
    "for a family member; deaths are the last "
    "hour's; slots are the 17 stat slots (not shirt or tabard) against "
    "weapons and armour carried in bags that the level allows; item level is "
    "the average worn; mail is delivered letters still holding an item or "
    "money; hours at level is played time. Stalled is quiet for more than "
    "%d minutes; empty slots is any stat slot empty."
    % (agenda.STALL_AFTER.total_seconds() // 60)
)


# --------------------------------------------------------------------- reads --


def fetch(ctx) -> dict:
    """Every row build() reads. Only SELECTs, through the request's reader."""
    rd = ctx.read
    names = list(ctx.families.names())
    empty = {
        "roster": names,
        "families": {},
        "guild": [],
        "readings": {},
        "chars": [],
        "worn": [],
        "bags": [],
        "mail": [],
        "deaths": [],
        "moved": [],
        "credits": [],
        "now_at": 0,
    }
    if not names:
        return empty
    # S608 on every statement below: `holes` is a run of placeholders sized
    # by the member count, and the slot bounds are module constants; every
    # value is bound by the driver.
    guild = rd.rows(
        ctx.server._LINEUP_GUILD.format(holes=holes(len(names))),
        tuple(names),
        what="guild_member",
    )
    everyone = sorted(set(names) | {r["name"] for r in guild})
    readings = ctx.presence(everyone)
    roster = set(names)
    audited = [n for n in everyone if n in roster or readings[n]["online"]]
    h, values = holes(len(audited)), tuple(audited)
    kinds = sorted(agenda.MOVEMENT_KINDS)
    return {
        "roster": names,
        "families": ctx.families.families(),
        "guild": guild,
        "readings": readings,
        "chars": rd.must(CHARS_SQL.format(holes=h), values),
        "worn": rd.must(
            WORN_SQL.format(holes=h, slots=len(_EQUIPMENT_SLOT_NAMES)), values
        ),
        "bags": rd.must(
            BAGS_SQL.format(
                holes=h,
                pack_first=_BACKPACK_SLOTS.start,
                pack_last=_BACKPACK_SLOTS.stop - 1,
                bag_first=_BAG_SLOTS.start,
                bag_last=_BAG_SLOTS.stop - 1,
            ),
            values,
        ),
        "mail": rd.must(MAIL_SQL.format(holes=h), values),
        "deaths": rd.rows(
            DEATHS_SQL.format(holes=h),
            (*values, DEATH_WINDOW_SECONDS),
            what="overseer_death",
        ),
        "moved": rd.rows(
            MOVED_SQL.format(holes=h, kinds=holes(len(kinds))),
            (*values, *kinds),
            what="overseer_event",
        ),
        # Each family leader's newest boss credit, as the Now page reads it.
        "credits": rd.rows(
            BOSS_SQL.format(holes=holes(len(names))),
            (*names, agenda.BOSS_KIND),
            what="overseer_dungeon_run_event",
        ),
        "now_at": int((rd.must(CLOCK_SQL) or [{}])[0].get("now_at") or 0),
    }


# --------------------------------------------------------------------- build --


def _counts(rows, key: str) -> dict:
    return {r["name"]: int(r.get(key) or 0) for r in rows or ()}


def _worn(rows) -> dict:
    """name -> item levels of what is worn in the stat slots (None: unknown)."""
    out: dict = {}
    for r in rows or ():
        slot = r.get("slot")
        if slot is None or int(slot) in _COSMETIC_SLOTS:
            continue
        level = r.get("item_level")
        out.setdefault(r["name"], []).append(None if level is None else int(level))
    return out


def _average(levels: list) -> float | None:
    known = [lv for lv in levels if lv is not None]
    return round(sum(known) / len(known), 1) if known else None


def _moved(rows: dict) -> dict:
    """name -> when it last moved (Unix seconds), judged as the Now page does.

    A member of a family reads the family's newest movement: the newest
    quest, level or gear event of any member, or the newest boss credit of
    any member (credits are kept on the run's leader). A guildmate outside
    the families reads its own events.
    """
    own = {r["name"]: int(r["at"]) for r in rows["moved"] or () if r.get("at")}
    for r in rows.get("credits") or ():
        if r.get("at"):
            own[r["name"]] = max(own.get(r["name"], 0), int(r["at"]))
    out = dict(own)
    for names in (rows.get("families") or {}).values():
        newest = max((own.get(n, 0) for n in names), default=0)
        for n in names:
            if newest:
                out[n] = newest
            else:
                out.pop(n, None)
    return out


def member(name: str, rows: dict, ids: dict) -> dict:
    """The six fields for one member, from fetch()'s rows and their indexes."""
    char = ids["chars"].get(name) or {}
    worn = ids["worn"].get(name, [])
    moved = ids["moved"].get(name)
    now_at = rows["now_at"]
    leveltime = char.get("leveltime")
    reading = rows["readings"].get(name) or {}
    guild_row = ids["guild"].get(name) or {}
    return {
        "name": name,
        "guild": guild_row.get("guild_name") or "",
        "roster": name in ids["roster"],
        "online": bool(reading.get("online")),
        "level": int(char.get("level") or guild_row.get("level") or 0),
        "since_moved_s": max(0, now_at - moved) if moved and now_at else None,
        "deaths_last_hour": ids["deaths"].get(name, 0),
        "slots_filled": len(worn),
        "slots": STAT_SLOTS,
        "wearable_in_bags": ids["bags"].get(name, 0),
        "item_level": _average(worn),
        "mail_uncollected": ids["mail"].get(name, 0),
        "hours_at_level": (
            None if leveltime is None else round(int(leveltime) / 3600, 1)
        ),
    }


def build(rows: dict) -> dict:
    """The /api/v2/audit payload from fetch()'s rows. Pure."""
    roster = set(rows["roster"])
    readings = rows["readings"]
    guild = {r["name"]: r for r in rows["guild"] or ()}
    names = sorted(
        n
        for n in roster | set(guild)
        if n in roster or (readings.get(n) or {}).get("online")
    )
    ids = {
        "roster": roster,
        "guild": guild,
        "chars": {r["name"]: r for r in rows["chars"] or ()},
        "worn": _worn(rows["worn"]),
        "bags": _counts(rows["bags"], "wearable"),
        "mail": _counts(rows["mail"], "letters"),
        "deaths": _counts(rows["deaths"], "deaths"),
        "moved": _moved(rows),
    }
    members = [member(n, rows, ids) for n in names]
    quiet = agenda.STALL_AFTER.total_seconds()
    return {
        "members": members,
        "stalled": [
            m["name"]
            for m in members
            if m["since_moved_s"] is not None and m["since_moved_s"] > quiet
        ],
        "empty_slots": [m["name"] for m in members if m["slots_filled"] < m["slots"]],
        "checked_at": rows["now_at"] or None,
        "basis": BASIS,
    }


def audit(_query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/audit: the six fields for every roster and online guild member."""
    return 200, build(fetch(ctx))


ROUTES = {"/api/v2/audit": audit}
