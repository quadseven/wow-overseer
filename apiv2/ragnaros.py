"""GET /api/v2/ragnaros?guild=<cave|bonkers>: the road to a Ragnaros attempt.

One total per guild, the eight goal checkpoints A to H as rows of seats
passing, every blocker with how many of the 40 seats it holds back, and the
Molten Core attempt count. It composes reads that exist: the goal read
(cached, apiv2/goal.py), the raidteams read, the guild's Molten Core runs
and dungeon runs, the summoner and maintenance coverage and the per-seat
class quest read.
roadtoragnaros.py holds the rules and the arithmetic.
"""

from __future__ import annotations

import classquest
import guildrun
import raidrun
import raidteams
import readcache
import realmread
import roadtoragnaros

from . import _scope
from . import classchain
from . import goal as goal_read
from . import raidteams as teams_read

CACHE_SECONDS = 60.0
_MAX_RUNS = 500

ENGINEERING = 202
RITUAL = 698

COVERAGE_CHAR_SQL = "SELECT name, level FROM characters WHERE name IN ({holes})"
COVERAGE_SKILLS_SQL = (
    "SELECT c.name, cs.value AS engineering FROM characters c "
    "JOIN character_skills cs ON cs.guid = c.guid AND cs.skill = 202 "
    "WHERE c.name IN ({holes})"
)
COVERAGE_RITUAL_SQL = (
    "SELECT c.name FROM characters c "
    "JOIN character_spell cs ON cs.guid = c.guid AND cs.spell = 698 "
    "WHERE c.name IN ({holes})"
)
SEAT_CHAR_SQL = (
    "SELECT guid, name, class AS class_id, race FROM characters WHERE name IN ({holes})"
)
SEAT_SPELLS_SQL = (
    "SELECT guid, spell FROM character_spell "
    "WHERE guid IN ({guids}) AND spell IN ({spells})"
)

_CACHE = readcache.ReadCache(CACHE_SECONDS)


def _holes(n: int) -> str:
    return ", ".join(["%s"] * n)


def _read(rd, sql: str, params: tuple):
    """The rows, or None when this realm cannot answer the read."""
    try:
        return rd.must(sql, params)
    except realmread.Gap:
        return None


def _coverage_names(guild: str) -> list:
    """(name, role) for every summoner and repair hand the guild approves."""
    out = [(n, "summoner") for n, _old in raidteams.SUMMONERS.get(guild, ())]
    out += [(n, "maintenance") for n, _old in raidteams.MAINTENANCE.get(guild, ())]
    return out


def _coverage(rd, guild: str) -> list | None:
    """Levels, engineering skill and Ritual of Summoning by approved name.

    None when any of the three reads cannot be answered: a missing table
    must not read as nobody being in place.
    """
    names = [n for n, _role in _coverage_names(guild)]
    if not names:
        return None
    holes = _holes(len(names))
    chars = _read(rd, COVERAGE_CHAR_SQL.format(holes=holes), tuple(names))  # noqa: S608
    skills = _read(rd, COVERAGE_SKILLS_SQL.format(holes=holes), tuple(names))  # noqa: S608
    ritual = _read(rd, COVERAGE_RITUAL_SQL.format(holes=holes), tuple(names))  # noqa: S608
    if chars is None or skills is None or ritual is None:
        return None
    level = {r["name"]: r.get("level") for r in chars}
    skill = {r["name"]: r.get("engineering") for r in skills}
    known = {r["name"] for r in ritual}
    return [
        {
            "name": name,
            "role": role,
            "level": level.get(name),
            "summon": name in known,
            "engineering": skill.get(name, 0),
        }
        for name, role in _coverage_names(guild)
    ]


def _quest_done(book, klass: int, rewarded: set, known: set) -> bool:
    """Every reward group of the class whose reward the member has.

    A reward a trainer sells for coin is the trainer's, not a quest's
    (classquest's own rule), so those groups are left out.
    """
    for key, quests in book.groups.items():
        if key[0] != klass or book.trained.intersection(key[1]):
            continue
        spells, got = key[1], rewarded
        if not any(s in known for s in spells) and not any(q in got for q in quests):
            return False
    return True


def _class_quest_map(rd, names: list) -> dict | None:
    """Seat name -> every mandatory class quest rewarded, or None overall.

    None when the quest read itself cannot be answered, so every seat reads
    unread for B rather than short. A seat with no character row is absent
    from the map and reads unread for B too.
    """
    if not names:
        return {}
    try:
        world = classchain._world(rd)
    except (realmread.Gap, KeyError):
        return None
    book = classchain.book_of(world["quests"], world["started"], world["trained"])
    chars = _read(rd, SEAT_CHAR_SQL.format(holes=_holes(len(names))), tuple(names))  # noqa: S608
    if chars is None:
        return None
    ids = [int(r["id"]) for r in world["quests"]]
    if not ids:
        return None
    guids = [int(c["guid"]) for c in chars if c.get("guid")]
    if not guids:
        return None
    rewarded_rows = _read(
        rd,
        classquest.REWARDED_SQL.format(
            guids=_holes(len(guids)), quests=_holes(len(ids))
        ),
        (*guids, *ids),
    )
    spells = book.spell_ids()
    known_rows = _read(
        rd,
        SEAT_SPELLS_SQL.format(guids=_holes(len(guids)), spells=_holes(len(spells))),
        (*guids, *spells),
    )
    if rewarded_rows is None or known_rows is None:
        return None
    rewarded: dict = {}
    for r in rewarded_rows:
        rewarded.setdefault(int(r["guid"]), set()).add(int(r["quest"]))
    known: dict = {}
    for r in known_rows:
        known.setdefault(int(r["guid"]), set()).add(int(r["spell"]))
    out = {}
    for row in chars:
        guid = int(row["guid"])
        klass = int(row.get("class_id") or 0)
        out[row["name"]] = _quest_done(
            book, klass, rewarded.get(guid, set()), known.get(guid, set())
        )
    return out


def _attach_quests(rd, teams: dict | None):
    """Paint the class quest read onto each seated member of `teams`."""
    if not teams:
        return
    names = list((teams.get("members") or {}).keys())
    found = _class_quest_map(rd, names)
    for name, member in (teams.get("members") or {}).items():
        member["class_quests"] = None if found is None else found.get(name)


def _dungeons(rd, guild: str) -> list | None:
    """The guild's dungeon runs, or None when the run table cannot be read."""
    try:
        return guildrun.recent(rd, guild, _MAX_RUNS)
    except realmread.Gap:
        return None


def build(ctx, guild: str) -> dict:
    teams = None
    if guild in raidteams.GROUPS:
        teams = teams_read.build(guild, teams_read.fetch(ctx.read, guild))
        _attach_quests(ctx.read, teams)
    _, goal = goal_read.goal({"guild": [guild]}, ctx)
    try:
        runs = guildrun.keyword_runs(ctx.read, guild, raidrun.MOLTEN_CORE, _MAX_RUNS)
    except realmread.Gap:
        runs = None
    return roadtoragnaros.build(
        guild,
        teams,
        goal,
        runs,
        dungeons=_dungeons(ctx.read, guild),
        coverage=_coverage(ctx.read, guild),
    )


def ragnaros(query: dict, ctx) -> tuple[int, dict]:
    asked = (query.get("guild") or [""])[0].strip()
    if not asked:
        return 400, {"error": "say guild="}
    guild = _scope.guild(ctx, asked)
    if guild is None:
        return 404, _scope.no_such_guild(ctx)
    return 200, _CACHE.get("ragnaros:%s" % guild, lambda: build(ctx, guild))


ROUTES = {"/api/v2/ragnaros": ragnaros}
