"""GET /api/v2/evidence?name=X&map_id=N&since=D&limit=N - fixed, named read-only questions an agent proves a ticket with.

    {name, params: {...}, rows: [{...}], count, capped}

An agent checking a shipped ticket needs one fixed fact from the realm, such
as the runs on one dungeon since a date or the guild materials letters nobody
has opened. Without this route that fact meant SQL typed into a shell against
the database. Here each question is an entry in QUERIES: fixed SQL that only
reads, the parameters it takes and how each is checked, and a row cap.

THE REQUEST IS CHECKED WHOLE BEFORE ANY SQL RUNS. An unknown `name` is 404
with the list of names. A missing parameter, a value that fails its check, a
parameter the query does not take, or a parameter given twice is 400. Nothing
from the request reaches a statement except as a bound value that has already
passed its check, so no request can change what SQL runs.

`capped` is true when the query had more rows than it returns: the answer is
then the newest `limit` rows, not all of them.

A REALM WITHOUT THE TABLE IS 409, NOT AN EMPTY ANSWER. Evidence that reads
"no rows" must mean the realm has none; a module table the realm predates is
said out loud instead. A query with a thinner statement (`dungeon_runs` on a
realm without the `outcome` column) answers through it first.

WHAT A DEATH ROW KNOWS, AND WHEN (#1733). `deaths_by_member` and
`death_loop_summary` read overseer_death, the module's own row per death. It
records the member's level, map, zone and killer AT the death. It records no
soul shards, pet, bag room or food, and nothing else in the realm does at
death time either, so those come from the member's current state as the realm
last saved it (character_inventory, character_pet), and every such field is
named `_now`: `shards_now`, `pet_now`, `free_slots_now`, `food_now`,
`drink_now`. The killer's level is not recorded either; `killer_min_level`
and `killer_max_level` are its creature template's range, NULL for a killer
with no creature entry. A death whose member no longer has a character row
is not counted.

Read-only, like every route under /api/v2.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Callable

import realmread

MAX_ROWS = 200
DEFAULT_ROWS = 50

# The subject guildjobs.POST_SUBJECT gives every guild materials letter. A
# literal here so the map server does not import the bridge's job module; a
# test fails if the two ever differ.
GUILD_MATERIALS_SUBJECT = "Guild materials"
# mail.checked is a bit mask; bit 0 is MAIL_CHECK_MASK_READ in the core
# (holdings.MAIL_READ reads the same bit).
MAIL_READ = 1

# item_template.entry of a Soul Shard (guildjobs.SOUL_SHARD).
SOUL_SHARD = 6265
# item_template.spellcategory_1 for what is eaten and what is drunk
# (restsupply.FOOD_CATEGORY and DRINK_CATEGORY).
FOOD_CATEGORY = 11
DRINK_CATEGORY = 59
# character_pet.slot of the pet the realm saved as the member's current one
# (PET_SAVE_AS_CURRENT in the core).
CURRENT_PET_SLOT = 0
# characters.class ids, for the `class` parameter.
CLASS_IDS = {
    "warrior": 1,
    "paladin": 2,
    "hunter": 3,
    "rogue": 4,
    "priest": 5,
    "deathknight": 6,
    "shaman": 7,
    "mage": 8,
    "warlock": 9,
    "druid": 11,
}

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")
_INT = re.compile(r"\d{1,10}")


class Refused(ValueError):
    """A request this route will not run: answered 400 with the reason."""


def _int_in(low: int, high: int) -> Callable[[str], int]:
    def check(raw: str) -> int:
        if not _INT.fullmatch(raw):
            raise Refused("must be a whole number")
        value = int(raw)
        if not low <= value <= high:
            raise Refused(f"must be from {low} to {high}")
        return value

    return check


def _since(raw: str) -> str:
    """An ISO date or date and time, as MySQL's 'YYYY-MM-DD HH:MM:SS'."""
    if not _DATE.fullmatch(raw):
        raise Refused("must be YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS]")
    try:
        when = datetime.datetime.fromisoformat(raw)
    except ValueError:
        raise Refused("is not a real date") from None
    return when.strftime("%Y-%m-%d %H:%M:%S")


_NAME = re.compile(r"[^\W\d_]{2,12}")


def _member(raw: str) -> str:
    """A character name: letters only, 2 to 12 of them; empty is any."""
    if raw and not _NAME.fullmatch(raw):
        raise Refused("must be a character name of 2 to 12 letters")
    return raw


def _class(raw: str) -> int:
    """A class id (1 to 11) or its English name; empty (0) is any class."""
    if not raw:
        return 0
    word = raw.lower().replace(" ", "").replace("_", "")
    if word in CLASS_IDS:
        return CLASS_IDS[word]
    if _INT.fullmatch(raw) and int(raw) in CLASS_IDS.values():
        return int(raw)
    raise Refused("must be a class id or name, e.g. 9 or warlock")


@dataclass(frozen=True)
class Param:
    check: Callable[[str], object]
    default: str | None = None  # None: the request must give it


@dataclass(frozen=True)
class Query:
    """One named question: its SQL, its parameters in the order the SQL binds
    them, and an optional thinner SQL for a realm missing a newer column."""

    sql: str
    params: tuple
    takes: dict
    what: str
    fallback: str = ""
    about: str = ""


DUNGEON_RUNS_SQL = (
    "SELECT id, leader_name, map_id, state, outcome, ended_reason, "
    "started_at, ended_at FROM overseer_dungeon_run "
    "WHERE map_id = %s AND started_at >= %s "
    "ORDER BY started_at DESC, id DESC LIMIT %s"
)
# A realm whose module predates the run accounting has no `outcome` column.
DUNGEON_RUNS_THIN_SQL = (
    "SELECT id, leader_name, map_id, state, ended_reason, "
    "started_at, ended_at FROM overseer_dungeon_run "
    "WHERE map_id = %s AND started_at >= %s "
    "ORDER BY started_at DESC, id DESC LIMIT %s"
)
GUILD_MATERIALS_SQL = (
    "SELECT c.name AS recipient, COUNT(*) AS letters, "
    "SUM(m.deliver_time <= UNIX_TIMESTAMP()) AS delivered "
    "FROM mail m JOIN characters c ON c.guid = m.receiver "
    "WHERE m.subject = %s AND (m.checked & %s) = 0 "
    "GROUP BY c.name ORDER BY letters DESC, recipient LIMIT %s"
)

# The class name a characters.class id stands for (ELT is 1-based; 10 is
# unused in this expansion).
_CLASS_NAME = (
    "ELT(c.class, 'Warrior', 'Paladin', 'Hunter', 'Rogue', 'Priest', "
    "'Death Knight', 'Shaman', 'Mage', 'Warlock', '', 'Druid')"
)
# An item the member carries: in the backpack (bag 0, slots 23 to 38) or in a
# bag it wears (bag 0, slots 19 to 22), as bridge._JOB_SUPPLIES_SQL reads it.
_CARRIED = (
    "((ci.bag = 0 AND ci.slot BETWEEN 23 AND 38) "
    "OR ci.bag IN (SELECT wb.item FROM character_inventory wb "
    "WHERE wb.guid = ci.guid AND wb.bag = 0 AND wb.slot BETWEEN 19 AND 22))"
)
DEATHS_BY_MEMBER_SQL = (
    "SELECT d.id, d.created_at AS died_at, d.character_name AS name, "  # noqa: S608 - only module constants are joined; request values are bound %s
    "c.class AS class_id, " + _CLASS_NAME + " AS class_name, d.level, d.map, "
    "d.zone, d.killer_type, d.killer_name AS killer, d.killer_entry, "
    "ct.minlevel AS killer_min_level, ct.maxlevel AS killer_max_level, "
    "(SELECT COALESCE(SUM(ii.count), 0) FROM character_inventory ci "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "WHERE ci.guid = d.character_guid AND ii.itemEntry = %s AND " + _CARRIED + ") "
    "AS shards_now, "
    "(SELECT MAX(p.name) FROM character_pet p "
    "WHERE p.owner = d.character_guid AND p.slot = %s) AS pet_now, "
    "(SELECT MAX(p.entry) FROM character_pet p "
    "WHERE p.owner = d.character_guid AND p.slot = %s) AS pet_entry_now, "
    # The backpack's 16 slots and each worn general bag's size, less the
    # items in them (gear.general_bag_room): a quiver or soul bag is no room.
    "16 - (SELECT COUNT(*) FROM character_inventory bp "
    "WHERE bp.guid = d.character_guid AND bp.bag = 0 "
    "AND bp.slot BETWEEN 23 AND 38) + COALESCE((SELECT SUM(bt.ContainerSlots "
    "- (SELECT COUNT(*) FROM character_inventory inb "
    "WHERE inb.guid = b.guid AND inb.bag = b.item)) "
    "FROM character_inventory b JOIN item_instance bi ON bi.guid = b.item "
    "JOIN acore_world.item_template bt ON bt.entry = bi.itemEntry "
    "WHERE b.guid = d.character_guid AND b.bag = 0 AND b.slot BETWEEN 19 AND 22 "
    "AND bt.class = 1 AND bt.subclass = 0), 0) AS free_slots_now, "
    "(SELECT COALESCE(SUM(ii.count), 0) FROM character_inventory ci "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE ci.guid = d.character_guid AND it.class = 0 AND it.subclass = 5 "
    "AND it.spellcategory_1 = %s AND " + _CARRIED + ") AS food_now, "
    "(SELECT COALESCE(SUM(ii.count), 0) FROM character_inventory ci "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE ci.guid = d.character_guid AND it.class = 0 AND it.subclass = 5 "
    "AND it.spellcategory_1 = %s AND " + _CARRIED + ") AS drink_now "
    "FROM overseer_death d JOIN characters c ON c.guid = d.character_guid "
    "LEFT JOIN acore_world.creature_template ct "
    "ON ct.entry = d.killer_entry AND d.killer_entry > 0 "
    "WHERE d.created_at >= %s AND (%s = '' OR d.character_name = %s) "
    "AND (%s = 0 OR c.class = %s) "
    "ORDER BY d.created_at DESC, d.id DESC LIMIT %s"
)
# Per class over the window: deaths, members, deaths per member, and the
# deaths whose member now has no current pet and carries no Soul Shard.
DEATH_LOOP_SUMMARY_SQL = (
    "SELECT c.class AS class_id, " + _CLASS_NAME + " AS class_name, "  # noqa: S608 - only module constants are joined; request values are bound %s
    "COUNT(*) AS deaths, COUNT(DISTINCT d.character_guid) AS members, "
    "ROUND(COUNT(*) / COUNT(DISTINCT d.character_guid), 2) AS deaths_per_member, "
    "SUM(p.owner IS NULL AND COALESCE(s.shards, 0) = 0) "
    "AS deaths_no_pet_no_shard_now, "
    "ROUND(SUM(p.owner IS NULL AND COALESCE(s.shards, 0) = 0) / COUNT(*), 3) "
    "AS share_no_pet_no_shard_now "
    "FROM (SELECT character_guid FROM overseer_death WHERE created_at >= %s) d "
    "JOIN characters c ON c.guid = d.character_guid "
    "LEFT JOIN (SELECT DISTINCT owner FROM character_pet WHERE slot = %s) p "
    "ON p.owner = d.character_guid "
    "LEFT JOIN (SELECT ci.guid, SUM(ii.count) AS shards "
    "FROM character_inventory ci JOIN item_instance ii ON ii.guid = ci.item "
    "WHERE ii.itemEntry = %s AND " + _CARRIED + " GROUP BY ci.guid) s "
    "ON s.guid = d.character_guid "
    "GROUP BY c.class ORDER BY deaths DESC, class_id LIMIT %s"
)

QUERIES = {
    "dungeon_runs": Query(
        sql=DUNGEON_RUNS_SQL,
        fallback=DUNGEON_RUNS_THIN_SQL,
        params=("map_id", "since", "limit"),
        takes={
            "map_id": Param(_int_in(0, 65535)),
            "since": Param(_since),
            "limit": Param(_int_in(1, MAX_ROWS), str(DEFAULT_ROWS)),
        },
        what="overseer_dungeon_run",
        about="runs on one map started at or after `since`, newest first",
    ),
    "guild_materials_unopened": Query(
        sql=GUILD_MATERIALS_SQL,
        params=("subject", "read_bit", "limit"),
        takes={},
        what="mail",
        about="per recipient, unread guild materials letters and how many are delivered",
    ),
    "deaths_by_member": Query(
        sql=DEATHS_BY_MEMBER_SQL,
        params=(
            "soul_shard",
            "pet_slot",
            "pet_slot",
            "food",
            "drink",
            "since",
            "member",
            "member",
            "class",
            "class",
            "limit",
        ),
        takes={
            "since": Param(_since),
            "member": Param(_member, ""),
            "class": Param(_class, ""),
            "limit": Param(_int_in(1, MAX_ROWS), str(DEFAULT_ROWS)),
        },
        what="overseer_death",
        about=(
            "deaths at or after `since`, newest first, optionally for one `member` "
            "or `class`. level, zone and killer are as recorded at the death; "
            "*_now fields are the member's state as the realm last saved it, "
            "not at the death; killer_*_level is the creature template's range"
        ),
    ),
    "death_loop_summary": Query(
        sql=DEATH_LOOP_SUMMARY_SQL,
        params=("since", "pet_slot", "soul_shard", "limit"),
        takes={"since": Param(_since)},
        what="overseer_death",
        about=(
            "per class, deaths at or after `since`, members, deaths per member, "
            "and the share of deaths whose member now has no current pet and "
            "carries no Soul Shard (state as last saved, not at the death)"
        ),
    ),
}

# Values a query binds that no request supplies.
_FIXED = {
    "subject": GUILD_MATERIALS_SUBJECT,
    "read_bit": MAIL_READ,
    "soul_shard": SOUL_SHARD,
    "pet_slot": CURRENT_PET_SLOT,
    "food": FOOD_CATEGORY,
    "drink": DRINK_CATEGORY,
}


def _single(query: dict, key: str) -> str:
    values = query.get(key) or []
    if len(values) != 1:
        raise Refused(f"`{key}` must be given exactly once")
    return values[0]


def checked(entry: Query, query: dict) -> dict:
    """The request's parameters, each checked, or Refused."""
    extra = sorted(set(query) - set(entry.takes) - {"name"})
    if extra:
        raise Refused("unexpected parameter: " + ", ".join(extra))
    out = {}
    for key, param in entry.takes.items():
        if key not in query:
            if param.default is None:
                raise Refused(f"`{key}` is required")
            raw = param.default
        else:
            raw = _single(query, key)
        try:
            out[key] = param.check(raw)
        except Refused as why:
            raise Refused(f"`{key}` {why}") from None
    return out


def _plain(value):
    if isinstance(value, datetime.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def evidence(query: dict, ctx) -> tuple[int, dict]:
    """One named read-only question, checked whole before any SQL runs."""
    try:
        name = _single(query, "name")
    except Refused as why:
        return 400, {"error": str(why), "names": sorted(QUERIES)}
    entry = QUERIES.get(name)
    if entry is None:
        return 404, {"error": "no such query", "names": sorted(QUERIES)}
    try:
        params = checked(entry, query)
    except Refused as why:
        return 400, {"error": str(why), "takes": sorted(entry.takes)}
    limit = params.get("limit", MAX_ROWS)
    bound = {**_FIXED, **params, "limit": limit + 1}
    values = tuple(bound[key] for key in entry.params)
    rows = None
    for sql in (entry.sql, entry.fallback):
        if not sql:
            continue
        try:
            rows = ctx.read.must(sql, values)
            break
        except realmread.Gap:
            continue
    if rows is None:
        return 409, {"error": f"this realm has no {entry.what} to read", "name": name}
    kept = [{k: _plain(v) for k, v in dict(row).items()} for row in rows[:limit]]
    return 200, {
        "name": name,
        "about": entry.about,
        "params": {k: _plain(v) for k, v in params.items()},
        "rows": kept,
        "count": len(kept),
        "capped": len(rows) > limit,
    }


ROUTES = {"/api/v2/evidence": evidence}
