"""The Upper Spire run: ten seats from one guild, ordered and ended by itself.

WHAT THIS IS FOR. Upper Blackrock Spire is a raid on a dungeon-type map: Map.dbc
says dungeon, MapDifficulty.dbc allows 15, and no five-man party is the intended
shape. It runs through mod-overseer's raid run (RaidDoorFor's `ubrs` row), like
Molten Core, with one difference: nobody is standing by to order it.

ONE GUILD, NOT TWO FAMILIES. The two families are opposite factions and the realm
has AllowTwoSide.Interaction.Group = 0, so the core refuses a group holding both.
The ten are the head's family and the best of his guild.

THE FLOOR IS THE REALM'S. LFGDungeons.dbc row 44, Upper Blackrock Spire, has
minimum level 56. The core's own door (dungeon_access_template, map 229) asks 45,
and the bosses are 60 to 62, so 56 is the lowest level the game itself calls this
content. The Dragonspine Door has no lock and starts open on this core, so no
seat needs the Seal of Ascension.

ONLY EARNED LEVELS SIT. A Death Knight starts at 55. Everybody else in a guild got
to the floor by playing, which is the natural rule the realm runs under.

PURE MODULE, same seam as campaignqueue.py: rows in, decisions out, nothing that
talks to MySQL. bridge.py runs the statements named here.
"""

from __future__ import annotations

from dataclasses import dataclass

import campaignqueue
import raidroles
import raidrun

KEYWORD = raidrun.UPPER_SPIRE
FLOOR = raidrun.MIN_LEVEL[KEYWORD]
SOURCE = "overseer:spire"

SEATS = 10
GROUP_SIZE = 5
TANKS_NEEDED = 1
HEALERS_NEEDED = 2

DEATH_KNIGHT = 6

# ONE NIGHT'S LENGTH. A raid order has no rung that ends it; a person ends it, and
# no person is here. Four hours is a long night for a first clear and bounds a
# raid that keeps wiping.
CEILING_SECONDS = 4 * 3600
AFTER_CLEAR_SECONDS = 7 * 86400
AFTER_FAILURE_SECONDS = 86400

# The last entry this module wrote for a family, newest first, and whether the
# raid run recorded its clear (WriteRaidTimeline's `cleared` row) while it stood.
LAST_SQL = (
    "SELECT q.id, UNIX_TIMESTAMP(q.finished_at) AS finished_at, "
    "EXISTS(SELECT 1 FROM overseer_dungeon_run_event e WHERE e.family = q.family "
    "AND e.kind = 'cleared' AND e.created_at >= q.started_at "
    "AND e.created_at <= q.finished_at) AS cleared "
    "FROM overseer_dungeon_queue q WHERE q.family = %s AND q.keyword = %s "
    "AND q.source = %s AND q.status = 'done' ORDER BY q.id DESC LIMIT 1"
)
# Whether the entry now standing has a clear, and how long it has stood.
STANDING_SQL = (
    "SELECT TIMESTAMPDIFF(SECOND, q.started_at, NOW()) AS age, "
    "EXISTS(SELECT 1 FROM overseer_dungeon_run_event e WHERE e.family = q.family "
    "AND e.kind = 'cleared' AND e.created_at >= q.started_at) AS cleared "
    "FROM overseer_dungeon_queue q WHERE q.id = %s"
)
SHIFT_SQL = (
    "UPDATE overseer_dungeon_queue SET position = position + 1 "
    "WHERE id = %s AND status = 'queued'"
)


@dataclass(frozen=True)
class Lineup:
    """Two groups of seats, or why not. Never both."""

    groups: tuple
    short: str

    def as_dict(self) -> dict:
        """The shape raidrun.seat_rows reads."""
        return {"groups": list(self.groups)}


@dataclass(frozen=True)
class Slot:
    """Where the order goes: its position, and the queued ids moved down."""

    position: int
    shift: tuple


@dataclass(frozen=True)
class Last:
    finished_at: float
    cleared: bool


def _seat_of(member: dict) -> str:
    role = raidroles.role_of(member)
    if role == "tank":
        return raidroles.SEAT_TANK
    if role == "healer":
        return raidroles.SEAT_HEALER
    return raidroles.SEAT_DAMAGE


def _seated(member: dict, seat: str) -> dict:
    tree = member.get("spec") or ""
    return dict(
        member,
        role=seat,
        duty=raidroles.seat_duty(member.get("class_id"), tree) if tree else seat,
    )


def _names(members: list) -> str:
    return ", ".join(sorted(str(m.get("name")) for m in members))


def family_short(level_rows: list, family: list) -> str:
    """Why the family itself holds the run, or "". A row is read per name."""
    mine = [m for m in level_rows if m.get("name") in set(family)]
    missing = sorted(set(family) - {m.get("name") for m in mine})
    if missing:
        return "%s not found in the guild" % ", ".join(missing)
    under = [m for m in mine if int(m.get("level") or 0) < FLOOR]
    if under:
        return "the family needs level %d: %s" % (FLOOR, _names(under))
    return ""


def lineup(members: list, family: list) -> Lineup:
    """Ten seats from `members` (a guild), the family guaranteed, or why not."""
    short = family_short(members, family)
    if short:
        return Lineup((), short)
    rows = [raidroles.with_spec(m) for m in members]
    mine = [m for m in rows if m.get("name") in set(family)]
    pool = sorted(
        (
            m
            for m in rows
            if m.get("name") not in set(family)
            and int(m.get("level") or 0) >= FLOOR
            and int(m.get("class_id") or 0) != DEATH_KNIGHT
        ),
        key=lambda m: (-int(m.get("level") or 0), str(m.get("name"))),
    )
    placed = [_seated(m, _seat_of(m)) for m in mine]
    for seat, wanted in (
        (raidroles.SEAT_TANK, TANKS_NEEDED),
        (raidroles.SEAT_HEALER, HEALERS_NEEDED),
    ):
        owed = wanted - sum(1 for m in placed if m["role"] == seat)
        fits = [m for m in pool if _seat_of(m) == seat][: max(owed, 0)]
        placed += [_seated(m, seat) for m in fits]
        pool = [m for m in pool if m not in fits]
        if len(fits) < owed:
            return Lineup((), "%d more %s at level %d" % (owed - len(fits), seat, FLOOR))
    room = SEATS - len(placed)
    placed += [_seated(m, raidroles.SEAT_DAMAGE) for m in pool[:room]]
    if len(placed) < SEATS:
        return Lineup(
            (), "%d of %d seats at level %d" % (len(placed), SEATS, FLOOR)
        )
    groups = tuple(
        {"number": n + 1, "members": placed[n * GROUP_SIZE : (n + 1) * GROUP_SIZE]}
        for n in range(SEATS // GROUP_SIZE)
    )
    return Lineup(groups, "")


def order_slot(rows: list, last: Last | None, now: float) -> Slot | None:
    """Where to write the order this pass, or None when none is owed.

    NEVER OVER A RUNNING CAMPAIGN. An active entry keeps running and the order
    sits behind it. A queued entry has not begun, so the order goes in front of
    it and it waits its turn: nothing is cancelled either way.
    """
    if any(str(r.get("keyword")) == KEYWORD for r in rows):
        return None
    if last is not None:
        wait = AFTER_CLEAR_SECONDS if last.cleared else AFTER_FAILURE_SECONDS
        if now - last.finished_at < wait:
            return None
    active = [r for r in rows if r.get("status") == campaignqueue.ACTIVE]
    queued = [r for r in rows if r.get("status") != campaignqueue.ACTIVE]
    if active:
        position = max(int(r["position"]) for r in active) + 1
    elif queued:
        position = min(int(r["position"]) for r in queued)
    else:
        position = 0
    # Highest first, so a position is never held twice mid-way through the walk.
    shift = sorted(queued, key=lambda r: -int(r["position"]))
    return Slot(position, tuple(int(r["id"]) for r in shift))


def ending(rows: list, cleared: bool, age_seconds: float):
    """The campaignqueue.Move that ends this module's standing entry, or None.

    An operator's own order is left to the operator. The next pass starts the
    family's next entry, because the head row has moved on.
    """
    if not rows or str(rows[0].get("keyword")) != KEYWORD:
        return None
    head = rows[0]
    if head.get("status") != campaignqueue.ACTIVE or head.get("source") != SOURCE:
        return None
    if not cleared and age_seconds < CEILING_SECONDS:
        return None
    return campaignqueue.Move(
        finish=int(head["id"]),
        quest=True,
        why="the Upper Spire run is over: %s"
        % ("cleared" if cleared else "the night's ceiling passed"),
    )
