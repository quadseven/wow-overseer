"""The next dungeon for a family whose campaign queue has run out.

WHY THIS EXISTS. The campaign queue (campaignqueue.py, #209) runs whatever the
operator ordered and then returns the family to questing. Nothing chose the
next dungeon by itself, so a family that finished "Ragefire Chasm 50" sat on
the quest job until somebody wrote another order. This module is that choice,
made the way a group of players makes it: a dungeon the weakest member can
survive, that the group has not already run to its fill, on the continent the
group is standing on, and not one the overseer withholds.

WHEN IT PLANS (`due`). Only when the family has nothing else to do: the queue
is empty, or its last entry has reached its count, or the planner's own entry
has been outgrown. An operator's order is never replaced, reordered or cut
short; a planned entry is appended after it.

WHAT IT MAY CHOOSE (`options`). Every door mod-overseer has a portal for is a
`Run` here, or an alternate door into a `Run`'s wing (`ALTERNATES`), and a test
holds that to jobs.PORTAL_KEYWORDS. A run is offered when:

  * council.door_refusal has nothing to say against it: a portal the module
    runs, not withheld, not in the other faction's capital, not more than
    council.NEAR_ENOUGH levels above the weakest member, and on the family's
    continent or across a crossing that can be made. The same rules an
    operator's queue order is held to (#204, #205, #207).
  * the weakest member has not outgrown it (`Run.ceiling`). At the level cap
    a lower dungeon is outgrown only once its loot holds no upgrade for any
    member (preraid.py reads Zul'Farrak, Maraudon, Uldaman, Razorfen Downs
    and the Scarlet wings as well as the level 60 dungeons).
  * its door does not need a key nobody in the family holds (DOOR_KEYS): the
    Scarlet Armory and Cathedral wait for the Scarlet Key from the Library,
    Dire Maul West and North for the Crescent Key from the East wing.
  * it has not been run to its target count (`target`).

HOW MANY RUNS (`target`). Not a fixed fifty:

  * a levelling family runs a dungeon until the weakest member would outgrow
    it, estimated at RUNS_PER_LEVEL runs a level;
  * a family at the level cap farms each dungeon AT_CAP_RUNS runs a round, and
    starts another round once every dungeon it can reach has had one;
  * a dungeon that holds quests the family has not finished gets a quest pass
    of QUEST_PASS_RUNS more runs on top.

WHICH ONE (`heuristic`). A ready run before one the family would be carried
through, and a run the family has not died its way out of (`Option.troubled`:
never completed, with TROUBLE_WIPES wipes or TROUBLE_DEATHS deaths on its map
in DEATH_HOURS) before one it has. Then, for a levelling family, the run they
will outgrow soonest, because a group levelling through a band uses a dungeon
before it loses it; then the one with the least of its target done; then path
order.

AT THE LEVEL CAP THE GEAR DECIDES, the way a raid guild gears for Molten
Core (#280). preraid.py reads every level 60 dungeon's loot tables against
what each member wears, and each Option carries what one run is worth:
`expected`, the item levels the family should gain per run (each upgrade's
drop chance times its item level gain, summed over the members), and
`progress`, the raid progression a run gives (the Molten Core attunement in
Blackrock Depths, the Upper Spire key in the Lower Spire). A capped family
runs, in order: a run that advances the attunement now; one that advances
the key; the most expected item levels, halved for a run across a continent
crossing; the least of its target done; path order. Each dungeon is still
run AT_CAP_RUNS times a round before the next round starts, so the family
works through the dungeons as it outgrows their loot rather than living in
one.

Jev is asked the same question over the same options, told the same facts
(jev_choices.dungeon_ask) and the history behind them: the bosses' levels,
the family's deaths and wipes there, what the loot council has handed out
from there. Its answer is carried out when it is confident enough, and the
queue entry then carries SOURCE_JEV; otherwise the heuristic's is, with
SOURCE.

AT MOST ONE PLANNED ENTRY, AND NEVER BEFORE THE OPERATOR'S (`due`). The
planner writes only when the family's queue is empty, or holds one entry
that has reached its count; an operator entry still waiting to start, or a
planned entry still running, stops it.

PURE MODULE: no MySQL, no Discord, no clock. Rows in, choices and sentences
out. The statements the bridge and the site read with are written here.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace

import council
import dungeonpath

# The source a planned queue entry carries, so the queue's own rows say which
# entries the operator ordered and which this module chose: SOURCE_JEV when
# Jev's answer was carried out (alone, or agreeing with the heuristic),
# SOURCE when the heuristic's was because Jev was off, unsure or unanswered.
SOURCE = "overseer:planner"
SOURCE_JEV = "overseer:jev"
PLANNED_SOURCES = (SOURCE, SOURCE_JEV)


def source_for(by_jev: bool) -> str:
    """The queue source for a planned entry, by who chose it."""
    return SOURCE_JEV if by_jev else SOURCE


# THE HISTORY THAT COUNTS AGAINST A DUNGEON. A run never completed, with this
# many wipes on the ledger or this many of the family's deaths on its map in
# the last DEATH_HOURS, goes behind every run that is not. Two wipes is not
# bad luck; ten deaths is two whole parties.
TROUBLE_WIPES = 2
TROUBLE_DEATHS = 10
DEATH_HOURS = 168

# How far the bosses may stand from the weakest member's level before the fit
# is said as above or below them. Words for Jev and the page; the gate is
# council's floor and the Run's ceiling.
FIT_ABOVE = 3
FIT_BELOW = 6

# DOORS THAT NEED A KEY, and where the key drops. mod-overseer stages a party
# at each of these and does not check for the key (its portal table says so),
# so a run aimed at one before anybody holds the key stands at a door that
# will not move. Keyed by Run keyword: (item entry, the key, the run it drops
# in).
DOOR_KEYS = {
    "scarlet-armory": (7146, "the Scarlet Key", "scarlet-library"),
    "scarlet-cathedral": (7146, "the Scarlet Key", "scarlet-library"),
    "dire-maul-west-north": (18249, "the Crescent Key", "dire-maul-east-east"),
    "dire-maul-north": (18249, "the Crescent Key", "dire-maul-east-east"),
}
KEY_ITEMS = tuple(sorted({key for key, _name, _where in DOOR_KEYS.values()}))

# Why a run is not offered, beyond council's door refusals.
REFUSED_OUTGROWN = "outgrown"
REFUSED_LOCKED = "locked"

LEVEL_CAP = 60

# Runs of a level-appropriate dungeon it takes the weakest member to gain a
# level. An estimate for sizing an entry, not a promise: the planner looks
# again when the entry ends, and ends its own entry early once it is outgrown.
RUNS_PER_LEVEL = 4

# The extra runs a dungeon with unfinished quests gets, so the family can pick
# them up, carry them in and hand them back. Most dungeon quests are one kill
# or one drop, and a drop can take a second or third clear.
QUEST_PASS_RUNS = 3

# A level-capped family's pass at one dungeon before it moves to the next, per
# round. Long enough to see a dungeon's loot table drop, short enough that
# every dungeon it can reach comes round again the same week.
AT_CAP_RUNS = 10

# The most runs one planned entry asks for, whatever the estimate says.
MAX_RUNS = 30

# How many planned entries `sequence` looks ahead.
LOOKAHEAD = 8

# How long a family with nothing to plan waits before its facts are read
# again. Nothing it could be offered changes faster than a level or a run.
IDLE_SECONDS = 600

# The switch. On unless the operator turns it off.
ENV_SWITCH = "CAMPAIGN_PLANNER"


def enabled(environ=None) -> bool:
    """Whether the planner may queue anything, from CAMPAIGN_PLANNER."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")


@dataclass(frozen=True)
class Run:
    """One wing a family can be sent to, by the door the planner uses.

    zone     quest_template.QuestSortID for the dungeon's own quests
    ceiling  the level at which the weakest member has outgrown it
    """

    keyword: str
    zone: int
    ceiling: int

    @property
    def map_id(self) -> int:
        return int(dungeonpath.PORTAL_MAPS[self.keyword])

    @property
    def floor(self) -> int:
        """The level council.door_refusal holds this door to, so the planner
        and an operator's order agree about when a family may go."""
        return council.door_floor(self.keyword)

    @property
    def place(self) -> str:
        return council.keyword_place(self.keyword)


# EVERY WING THE OVERSEER HAS A DOOR INTO, lowest band first. The floors are
# council's (Scarlet wings, council.PLACES, then dungeonpath.PATH); the
# ceilings are dungeonpath.PATH's band tops, narrowed per wing where one map
# holds wings for different levels (Scarlet Monastery, Dire Maul).
RUNS: tuple = (
    Run("ragefire", 2437, 21),
    Run("wailing", 718, 24),
    Run("deadmines", 1581, 26),
    Run("shadowfang", 209, 30),
    Run("blackfathom", 719, 32),
    Run("stockades", 717, 32),
    Run("scarlet", 796, 34),
    Run("gnomeregan", 133, 38),
    Run("scarlet-library", 796, 38),
    Run("razorfen-kraul", 1717, 40),
    Run("scarlet-armory", 796, 41),
    Run("scarlet-cathedral", 796, 45),
    Run("razorfen-downs", 722, 47),
    Run("uldaman", 1517, 51),
    Run("zulfarrak", 978, 54),
    Run("maraudon-orange", 2100, 55),
    Run("maraudon-purple", 2100, 55),
    Run("sunken-temple", 1417, LEVEL_CAP),
    Run("blackrock-depths", 1584, LEVEL_CAP),
    Run("lower-blackrock-spire", 1583, LEVEL_CAP),
    Run("dire-maul-east-east", 2557, LEVEL_CAP),
    Run("dire-maul-west-north", 2557, LEVEL_CAP),
    Run("dire-maul-north", 2557, LEVEL_CAP),
    Run("scholomance", 2057, LEVEL_CAP),
    Run("stratholme-live", 2017, LEVEL_CAP),
    Run("stratholme-undead", 2017, LEVEL_CAP),
)

# Second doors into a wing a Run already covers. A run through one counts as
# a run of the wing; the planner sends the family through the Run's door.
ALTERNATES = {
    "gnomeregan-depot": "gnomeregan",
    "uldaman-back": "uldaman",
    "dire-maul-east-west": "dire-maul-east-east",
    "dire-maul-east-south": "dire-maul-east-east",
    "dire-maul-west-south": "dire-maul-west-north",
}

BY_KEYWORD = {run.keyword: run for run in RUNS}
ZONES = tuple(sorted({run.zone for run in RUNS}))
MAPS = tuple(sorted({run.map_id for run in RUNS}))


def wing_of(keyword: str) -> str:
    """The Run keyword a door counts toward, or "" for none."""
    keyword = str(keyword or "").strip().lower()
    keyword = ALTERNATES.get(keyword, keyword)
    return keyword if keyword in BY_KEYWORD else ""


def _front_run(map_id: int) -> str:
    """The first Run on a map, which a ledger row with no door counts toward."""
    return next((r.keyword for r in RUNS if r.map_id == int(map_id)), "")


# --- the reads ---------------------------------------------------------------
#
# Every statement names its tables and binds its values; `{holes}` is a run
# of placeholders sized by the family, never a value.

SUCCESS = "complete"

RUNS_SQL = (
    "SELECT leader_name, map_id, portal_keyword, outcome "
    "FROM overseer_dungeon_run WHERE state = 'ended' AND leader_name IN ({holes})"
)
# A realm whose ledger predates `portal_keyword` still counts by map.
RUNS_SQL_OLD = (
    "SELECT leader_name, map_id, outcome "
    "FROM overseer_dungeon_run WHERE state = 'ended' AND leader_name IN ({holes})"
)

# S608 on the three statements below: the only interpolated parts are this
# module's own integer constants (ZONES, GEAR_SLOTS, MAPS), passed through
# int() or range(); no value from outside reaches them.
QUESTS_SQL = (
    "SELECT q.ID AS quest, q.QuestSortID AS zone, q.MinLevel AS min_level, "  # noqa: S608
    "q.AllowableRaces AS races, a.PrevQuestID AS prev_quest "
    "FROM acore_world.quest_template q "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = q.ID "
    "WHERE q.QuestSortID IN (" + ", ".join(str(int(z)) for z in ZONES) + ") "
    "AND q.LogTitle NOT LIKE '<%%' "
    "AND EXISTS (SELECT 1 FROM acore_world.creature_queststarter s "
    "WHERE s.quest = q.ID) AND EXISTS (SELECT 1 FROM acore_world.creature_questender e "
    "WHERE e.quest = q.ID)"
)

REWARDED_SQL = (
    "SELECT c.name, r.quest FROM character_queststatus_rewarded r "
    "JOIN characters c ON c.guid = r.guid WHERE c.name IN ({holes})"
)

# The equipment slots a member can fill (bag 0, slots 0-17) less the shirt.
GEAR_SLOTS = tuple(s for s in range(18) if s != 3)

GEAR_SQL = (
    "SELECT c.name, AVG(it.ItemLevel) AS item_level, COUNT(*) AS worn "  # noqa: S608
    "FROM character_inventory ci JOIN characters c ON c.guid = ci.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE ci.bag = 0 AND ci.slot IN ("
    + ", ".join(str(s) for s in GEAR_SLOTS)
    + ") AND c.name IN ({holes}) GROUP BY c.name"
)

# What a dungeon's bosses drop, as one number: the mean item level of their
# uncommon-or-better weapons and armour. Static per world, read once.
LOOT_SQL = (
    "SELECT cr.map AS map_id, AVG(it.ItemLevel) AS item_level "  # noqa: S608
    "FROM acore_world.creature_loot_template clt "
    "JOIN acore_world.creature_template ct ON ct.lootid = clt.Entry "
    "JOIN acore_world.item_template it ON it.entry = clt.Item "
    "JOIN (SELECT DISTINCT id, map FROM acore_world.creature WHERE map IN ("
    + ", ".join(str(int(m)) for m in MAPS)
    + ")) cr ON cr.id = ct.entry "
    "WHERE clt.Reference = 0 AND it.Quality >= 2 AND it.class IN (2, 4) "
    "AND ct.entry IN (SELECT creditEntry FROM acore_world.instance_encounters "
    "WHERE creditType = 0) GROUP BY cr.map"
)


# The family's deaths per dungeon map in the last DEATH_HOURS (bound).
DEATHS_SQL = (
    "SELECT map AS map_id, COUNT(*) AS n FROM overseer_death "  # noqa: S608
    "WHERE character_name IN ({holes}) AND map IN ("
    + ", ".join(str(int(m)) for m in MAPS)
    + ") AND created_at > NOW() - INTERVAL %s HOUR GROUP BY map"
)

# The pieces the loot council handed to a member, per map, for one family.
WON_SQL = (
    "SELECT map AS map_id, COUNT(*) AS n FROM overseer_loot_council "
    "WHERE family = %s AND status = 'given' AND recipient <> '' GROUP BY map"
)

# The level range of each dungeon's bosses, off the world's own encounter
# credits. Static per world, read once.
BOSSES_SQL = (
    "SELECT cr.map AS map_id, MIN(ct.minlevel) AS low, "  # noqa: S608
    "MAX(ct.maxlevel) AS high FROM acore_world.instance_encounters ie "
    "JOIN acore_world.creature_template ct ON ct.entry = ie.creditEntry "
    "JOIN (SELECT DISTINCT id, map FROM acore_world.creature WHERE map IN ("
    + ", ".join(str(int(m)) for m in MAPS)
    + ")) cr ON cr.id = ct.entry WHERE ie.creditType = 0 GROUP BY cr.map"
)

# The door keys any member carries, anywhere in their bags or key ring.
KEYS_SQL = (
    "SELECT DISTINCT ii.itemEntry AS entry FROM character_inventory ci "  # noqa: S608
    "JOIN characters c ON c.guid = ci.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "WHERE c.name IN ({holes}) AND ii.itemEntry IN ("
    + ", ".join(str(int(k)) for k in KEY_ITEMS)
    + ")"
)


def holes(count: int) -> str:
    return ", ".join(["%s"] * max(int(count), 1))


def per_map(rows: list) -> dict:
    """map id -> n, off DEATHS_SQL or WON_SQL rows."""
    return {int(r["map_id"]): int(r.get("n") or 0) for r in rows or []}


def bosses(rows: list) -> dict:
    """map id -> (lowest, highest) boss level, off BOSSES_SQL rows."""
    return {
        int(r["map_id"]): (int(r["low"] or 0), int(r["high"] or 0))
        for r in rows or []
        if r.get("low") is not None and r.get("high") is not None
    }


def keys_held(rows: list) -> frozenset:
    """The door key entries somebody in the family carries, off KEYS_SQL."""
    return frozenset(int(r["entry"]) for r in rows or [])


def ledger(rows: list, names: list) -> tuple:
    """(completed runs, failed attempts) per Run keyword, off the run ledger.

    Only runs the family's own members led count. A completed run is outcome
    'complete'; every other ended row is a failed attempt. A row with no door
    (a ledger that predates `portal_keyword`) counts toward its map's first
    Run.
    """
    members = set(names)
    done: dict = {}
    failed: dict = {}
    for row in rows or []:
        if str(row.get("leader_name") or "") not in members:
            continue
        keyword = wing_of(str(row.get("portal_keyword") or "")) or _front_run(
            int(row.get("map_id") or 0)
        )
        if not keyword:
            continue
        bucket = done if str(row.get("outcome") or "") == SUCCESS else failed
        bucket[keyword] = bucket.get(keyword, 0) + 1
    return done, failed


WIPE = "wipe"
STAGING_FAILED = "staging_failed"


def outcomes(rows: list, names: list) -> dict:
    """Run keyword -> {outcome: ended runs}, off the same ledger rows and by
    the same rules as `ledger`."""
    members = set(names)
    out: dict = {}
    for row in rows or []:
        if str(row.get("leader_name") or "") not in members:
            continue
        keyword = wing_of(str(row.get("portal_keyword") or "")) or _front_run(
            int(row.get("map_id") or 0)
        )
        if not keyword:
            continue
        said = str(row.get("outcome") or "") or "unrecorded"
        tally = out.setdefault(keyword, {})
        tally[said] = tally.get(said, 0) + 1
    return out


def _race_bit(race) -> int:
    try:
        race = int(race or 0)
    except (TypeError, ValueError):
        return 0
    return 1 << (race - 1) if race > 0 else 0


def _can_do(row: dict, member: tuple, done_by: dict) -> bool:
    """Whether one member (name, level, race bit) can still do one quest."""
    name, level, bit = member
    races = int(row.get("races") or 0)
    previous = int(row.get("prev_quest") or 0)
    done = done_by.get(name, set())
    return (
        (not races or bool(races & bit))
        and level >= int(row.get("min_level") or 0)
        and (not previous or abs(previous) in done)
        and int(row["quest"]) not in done
    )


def open_quests(quest_rows: list, rewarded_rows: list, level_rows: list) -> dict:
    """zone -> how many of its quests somebody in the family can still do.

    A quest counts when at least one member is of a race it allows, is at or
    above its minimum level, and has not been rewarded for it.
    """
    done_by: dict = {}
    for row in rewarded_rows or []:
        done_by.setdefault(str(row.get("name") or ""), set()).add(int(row["quest"]))
    members = [
        (str(r.get("name") or ""), int(r.get("level") or 0), _race_bit(r.get("race")))
        for r in level_rows
    ]
    out: dict = {}
    for row in quest_rows or []:
        if any(_can_do(row, member, done_by) for member in members):
            zone = int(row["zone"])
            out[zone] = out.get(zone, 0) + 1
    return out


def gear(rows: list) -> dict:
    """name -> (mean item level of what is worn, empty gear slots)."""
    out = {}
    for row in rows or []:
        worn = int(row.get("worn") or 0)
        out[str(row["name"])] = (
            round(float(row.get("item_level") or 0), 1),
            max(len(GEAR_SLOTS) - worn, 0),
        )
    return out


def loot(rows: list) -> dict:
    """map id -> the mean item level of its bosses' gear drops."""
    return {int(r["map_id"]): int(round(float(r["item_level"] or 0))) for r in rows}


# --- the facts ---------------------------------------------------------------


@dataclass(frozen=True)
class Facts:
    """Everything one plan is made from, for one family.

    level_rows  each member's name, level, race, map id and whether they lead
    done        Run keyword -> completed runs
    failed      Run keyword -> ended attempts that did not complete
    quests      zone -> open quest count, or None when unread
    gear        name -> (mean worn item level, empty gear slots), or None
    loot        map id -> boss gear item level, or None
    upgrades    preraid place -> (preraid.Gain per member), or None
    progress    preraid place -> preraid.Progress, or None
    outcomes    Run keyword -> {outcome: ended runs}, or None when unread
    deaths      map id -> the family's deaths there in DEATH_HOURS, or None
    won         map id -> pieces the loot council gave a member, or None
    bosses      map id -> (lowest, highest) boss level, or None
    keys        door key entries somebody carries (DOOR_KEYS), or None
    """

    family: str
    level_rows: tuple
    done: dict
    failed: dict
    quests: dict | None = None
    gear: dict | None = None
    loot: dict | None = None
    upgrades: dict | None = None
    progress: dict | None = None
    outcomes: dict | None = None
    deaths: dict | None = None
    won: dict | None = None
    bosses: dict | None = None
    keys: frozenset | None = None

    @property
    def weakest(self) -> tuple:
        """(name, level) of the lowest member, or ("", 0) when unread."""
        known = [
            (int(r.get("level") or 0), str(r.get("name") or ""))
            for r in self.level_rows
            if str(r.get("name") or "") and int(r.get("level") or 0) > 0
        ]
        if not known:
            return "", 0
        level, name = min(known)
        return name, level


@dataclass(frozen=True)
class Option:
    """One run the family could be queued for now."""

    keyword: str
    place: str
    floor: int
    ceiling: int
    ready: bool
    done: int
    failed: int
    target: int
    runs: int
    quests: int | None
    loot_level: int | None
    below: tuple  # members whose worn gear is under the loot level
    capped: bool = False  # sized as a level-cap round, not by levels
    gains: tuple = ()  # preraid.Gain per member for one run, () when unread
    expected: float | None = None  # item levels the family gains per run
    progress: str = ""  # the attunement or key progress a run gives, said
    progress_rank: int = 0  # 2 the attunement, 1 the key, 0 neither now
    continent: str = ""  # the continent the door stands on
    crossing: bool = False  # the door is across a continent crossing
    level: int = 0  # the weakest member's level
    bosses: tuple | None = None  # (lowest, highest) boss level, None unread
    deaths: int | None = None  # the family's deaths on its map, DEATH_HOURS
    wipes: int = 0  # ledger runs that ended in a wipe
    staged: int = 0  # ledger runs that never got in (staging_failed)
    won: int | None = None  # pieces the loot council gave a member there

    @property
    def troubled(self) -> bool:
        """Never completed, and the family keeps dying there."""
        return self.done == 0 and (
            self.wipes >= TROUBLE_WIPES or (self.deaths or 0) >= TROUBLE_DEATHS
        )

    @property
    def fit(self) -> str:
        """The bosses' levels against the weakest member's, said; "" unread."""
        if not self.bosses or not self.level:
            return ""
        low, high = self.bosses
        span = "%d" % low if low == high else "%d to %d" % (low, high)
        if high - self.level > FIT_ABOVE:
            where = "above"
        elif self.level - high > FIT_BELOW:
            where = "below"
        else:
            where = "about right for"
        return "its bosses are level %s, %s a weakest of %d" % (
            span,
            where,
            self.level,
        )

    @property
    def history(self) -> str:
        """The family's record there, said."""
        parts = ["%d completed" % self.done]
        if self.wipes:
            parts.append("%d wiped" % self.wipes)
        other = self.failed - self.wipes - self.staged
        if other > 0:
            parts.append("%d ended early" % other)
        if self.staged:
            parts.append("%d never got in" % self.staged)
        if self.deaths is not None:
            parts.append(
                "%d death%s there in the last %d days"
                % (self.deaths, "" if self.deaths == 1 else "s", DEATH_HOURS // 24)
            )
        if self.won:
            parts.append(
                "%d piece%s the loot council gave a member"
                % (self.won, "" if self.won == 1 else "s")
            )
        return ", ".join(parts)

    @property
    def value(self) -> float:
        """`expected`, halved for a run across a continent crossing."""
        worth = float(self.expected or 0.0)
        return round(worth / 2 if self.crossing else worth, 2)

    @property
    def why(self) -> str:
        """The run count, said: how it was sized."""
        if self.capped:
            how = "a round at the level cap"
        else:
            how = "until the weakest member outgrows it at %d" % self.ceiling
        if self.quests:
            how += ", with a quest pass for its %d open quest%s" % (
                self.quests,
                "" if self.quests == 1 else "s",
            )
        return how


def _rounds(facts: Facts, runs: list) -> int:
    """How many full at-cap rounds every reachable cap dungeon has had."""
    counts = [int(facts.done.get(r.keyword, 0)) // AT_CAP_RUNS for r in runs]
    return min(counts) if counts else 0


def target(run: Run, level: int, quests: int | None, rounds: int = 0) -> int:
    """How many completed runs of `run` make it done for a family at `level`.

    A levelling family: RUNS_PER_LEVEL for every level until it is outgrown.
    A capped family: AT_CAP_RUNS for every round, this one included. Either
    way a quest pass on top while the dungeon holds open quests.
    """
    if level >= LEVEL_CAP:
        base = AT_CAP_RUNS * (rounds + 1)
    else:
        base = max(run.ceiling - level + 1, 0) * RUNS_PER_LEVEL
    if quests:
        base += QUEST_PASS_RUNS
    return base


def _expected(facts: Facts, keyword: str) -> float | None:
    """The item levels one run of `keyword` is worth, None when unread or
    when preraid does not read that dungeon's loot at all."""
    if facts.upgrades is None or keyword not in facts.upgrades:
        return None
    return round(sum(float(g.levels) for g in facts.upgrades.get(keyword, ())), 2)


def _outgrown_run(facts: Facts, run: Run, level: int) -> str:
    """Why the family has outgrown `run`, or "" while it has not.

    Levelling, a run is outgrown past its ceiling. At the level cap it is
    outgrown only once its loot holds no upgrade for anybody, because a raid
    guild gears in the lower dungeons too.
    """
    if level <= run.ceiling:
        return ""
    worth = _expected(facts, run.keyword) if level >= LEVEL_CAP else None
    if worth:
        return ""
    if worth is None:
        return "outgrown: it tops out at %d" % run.ceiling
    return "outgrown: it tops out at %d and holds no upgrade for anyone" % (run.ceiling)


def _locked(facts: Facts, run: Run) -> str:
    """Why the family cannot get through `run`'s door without a key, or ""."""
    need = DOOR_KEYS.get(run.keyword)
    if need is None:
        return ""
    entry, name, where = need
    if facts.keys is not None and entry in facts.keys:
        return ""
    return "locked: it needs %s, which drops in %s, and %s" % (
        name,
        council.keyword_place(where),
        "nobody carries one"
        if facts.keys is not None
        else "nothing says anybody carries one",
    )


def refusal_kinds(facts: Facts) -> dict:
    """Run keyword -> (kind, why) it is not offered, for every run that is
    not. The kinds are council's REFUSED_* and this module's."""
    _who, level = facts.weakest
    out = {}
    for run in RUNS:
        kind, why = council.door_refusal_kind(run.keyword, list(facts.level_rows))
        if not why:
            why = _outgrown_run(facts, run, level)
            kind = REFUSED_OUTGROWN if why else ""
        if not why:
            why = _locked(facts, run)
            kind = REFUSED_LOCKED if why else ""
        if why:
            out[run.keyword] = (kind, why)
    return out


def refusals(facts: Facts) -> dict:
    """Run keyword -> why it is not offered, for every run that is not."""
    return {keyword: why for keyword, (_k, why) in refusal_kinds(facts).items()}


def _gear_facts(facts: Facts, run: Run) -> dict:
    """The preraid fields of one run's Option, from the facts."""
    out: dict = {}
    if facts.upgrades is not None:
        gains = tuple(facts.upgrades.get(run.keyword, ()))
        out["gains"] = gains
        out["expected"] = round(sum(float(g.levels) for g in gains), 2)
    moved = (facts.progress or {}).get(run.keyword)
    if moved is not None and moved.needed:
        out["progress"] = moved.line
        out["progress_rank"] = int(moved.rank)
    door = council.continent_of(run.map_id)
    home = council._home_continent(list(facts.level_rows))
    out["continent"] = council.CONTINENT_NAMES.get(door, "")
    out["crossing"] = door is not None and home is not None and door != home
    return out


def shares_map(run: Run) -> bool:
    """Whether another Run's wing stands on the same map (Scarlet Monastery,
    Maraudon, Dire Maul, Stratholme)."""
    return sum(1 for r in RUNS if r.map_id == run.map_id) > 1


def _history_facts(facts: Facts, run: Run) -> dict:
    """The record fields of one run's Option, from the facts.

    Deaths, the loot council's awards and the bosses' levels are read per
    map, so a wing that shares its map is told None for them: ten deaths in
    the Graveyard are not the Cathedral's, nor are the Cathedral's bosses the
    Graveyard's. The ledger's wipes are per door already.
    """
    tally = (facts.outcomes or {}).get(run.keyword, {})

    def own(found: dict | None):
        if found is None or shares_map(run):
            return None
        return found.get(run.map_id)

    deaths = own(facts.deaths)
    won = own(facts.won)
    return {
        "level": facts.weakest[1],
        "bosses": own(facts.bosses),
        "deaths": None if facts.deaths is None or shares_map(run) else int(deaths or 0),
        "wipes": int(tally.get(WIPE, 0)),
        "staged": int(tally.get(STAGING_FAILED, 0)),
        "won": None if facts.won is None or shares_map(run) else int(won or 0),
    }


def options(facts: Facts) -> list:
    """Every run the family could be queued for now, in path order."""
    _who, level = facts.weakest
    if not level:
        return []
    refused = refusals(facts)
    open_runs = [r for r in RUNS if r.keyword not in refused]
    rounds = _rounds(facts, [r for r in open_runs if r.ceiling >= LEVEL_CAP])
    out = []
    for run in open_runs:
        quests = None if facts.quests is None else int(facts.quests.get(run.zone, 0))
        # A LOWER DUNGEON AT THE CAP COUNTS ITS OWN ROUNDS. The ledger has
        # no window, so the runs a family made while levelling through it
        # would otherwise fill the first at-cap round before it began. Its
        # loot (`_outgrown_run`) is what retires it.
        own = (
            int(facts.done.get(run.keyword, 0)) // AT_CAP_RUNS
            if level >= LEVEL_CAP and run.ceiling < LEVEL_CAP
            else 0
        )
        want = target(run, level, quests, max(rounds, own))
        done = int(facts.done.get(run.keyword, 0))
        if done >= want:
            continue
        loot_level = None if facts.loot is None else facts.loot.get(run.map_id)
        below = ()
        if facts.gear is not None and loot_level:
            below = tuple(
                sorted(n for n, (ilvl, _e) in facts.gear.items() if ilvl < loot_level)
            )
        out.append(
            Option(
                keyword=run.keyword,
                place=run.place,
                floor=run.floor,
                ceiling=run.ceiling,
                ready=level >= run.floor,
                done=done,
                failed=int(facts.failed.get(run.keyword, 0)),
                target=want,
                runs=max(1, min(want - done, MAX_RUNS)),
                quests=quests,
                loot_level=loot_level,
                below=below,
                capped=level >= LEVEL_CAP,
                **_gear_facts(facts, run),
                **_history_facts(facts, run),
            )
        )
    return out


def _order(option: Option) -> int:
    return next(i for i, r in enumerate(RUNS) if r.keyword == option.keyword)


def rank(option: Option) -> tuple:
    """The heuristic's sort key: smallest first. See the module docstring."""
    if option.capped:
        return (
            not option.ready,
            option.troubled,
            -option.progress_rank,
            -option.value,
            option.done / max(option.target, 1),
            _order(option),
        )
    return (
        not option.ready,
        option.troubled,
        option.ceiling,
        option.done / max(option.target, 1),
        _order(option),
    )


def heuristic(opts: list) -> Option | None:
    """The run a group of players would pick. See the module docstring."""
    if not opts:
        return None
    return min(opts, key=rank)


def heuristic_why(pick: Option) -> str:
    said = _heuristic_why(pick)
    if pick.troubled:
        said += "; every run left has cost the family (%s)" % pick.history
    return said


def _heuristic_why(pick: Option) -> str:
    if pick.capped and pick.progress_rank:
        return "%s advances the raid's progression: %s (%s)" % (
            pick.place,
            pick.progress,
            pick.why,
        )
    if pick.capped and pick.expected is not None:
        return (
            "%s gives the family the most expected upgrades of the dungeons "
            "it can reach, %.1f item levels a run over every member's slots%s (%s)"
            % (
                pick.place,
                pick.expected,
                ", across a continent crossing" if pick.crossing else "",
                pick.why,
            )
        )
    return "%s the weakest member %s, and the soonest outgrown of those (%s)" % (
        pick.place,
        "is ready for" if pick.ready else "would be carried through",
        pick.why,
    )


# --- when to plan ------------------------------------------------------------


@dataclass(frozen=True)
class Due:
    """Why the planner should queue a run now ("" for not), and the entry to
    mark done first (0 for none)."""

    reason: str = ""
    finish: int = 0


def due(rows: list, leader: dict | None, level_rows: list) -> Due:
    """Whether this family needs a planned run, from its pending queue rows.

    rows    the family's queued and active entries, in order, each with its
            `source` (campaignqueue.SELECT_PENDING_SQL)
    leader  the leader's roster row; its dungeon_runs_done counts the head

    Conservative on purpose: nothing is planned while any entry waits behind
    the head, or while the head (the operator's or a planned one) is short of
    its count. So an operator's order always runs first and to its end, and
    at most one planned entry is ever pending.
    """
    if not rows:
        return Due("the queue is empty")
    if len(rows) > 1:
        return Due()
    head = rows[0]
    if str(head.get("status")) != "active" or leader is None:
        return Due()
    done = leader.get("dungeon_runs_done")
    if done is not None and int(done) >= int(head.get("runs_wanted") or 0):
        return Due(
            "%s is done at %d of %d"
            % (
                council.keyword_place(str(head["keyword"])),
                int(done),
                int(head["runs_wanted"]),
            )
        )
    return _outgrown(head, level_rows)


def _outgrown(head: dict, level_rows: list) -> Due:
    """An active planner entry the weakest member has outgrown ends early.

    Only the planner's own entries: an operator's order runs to its count.
    Only while the family levels: at the level cap a lower dungeon was chosen
    for its loot, not its levels, and its round is short (AT_CAP_RUNS).
    """
    run = BY_KEYWORD.get(wing_of(str(head.get("keyword") or "")))
    if str(head.get("source") or "") not in PLANNED_SOURCES or run is None:
        return Due()
    weakest = [int(r.get("level") or 0) for r in level_rows if r.get("level")]
    if weakest and run.ceiling < min(weakest) < LEVEL_CAP:
        return Due(
            "the family has outgrown %s (the weakest is %d, it tops out at %d)"
            % (run.place, min(weakest), run.ceiling),
            finish=int(head["id"]),
        )
    return Due()


# --- saying it ---------------------------------------------------------------


def entry_line(option: Option) -> str:
    return "%s, %d run%s" % (option.place, option.runs, "" if option.runs == 1 else "s")


def planned_line(option: Option, reason: str, chooser: str) -> str:
    """The log line for a written plan."""
    worth = ""
    if option.expected is not None:
        worth = "; %.1f expected item levels a run over every slot" % (option.expected)
    if option.progress:
        worth += "; %s" % option.progress
    if option.fit:
        worth += "; %s" % option.fit
    return "queued %s (%s; %s done of %d%s; record: %s) because %s; chosen by %s" % (
        entry_line(option),
        option.why,
        option.done,
        option.target,
        worth,
        option.history,
        reason,
        chooser,
    )


def nothing_line(facts: Facts) -> str:
    """Why nothing could be planned, grouped by reason."""
    who, level = facts.weakest
    if not level:
        return "nobody's level can be read, so nothing is planned"
    grouped: dict = {}
    for keyword, why in sorted(refusals(facts).items()):
        grouped.setdefault(why.split(" - ")[0].split(":")[0], []).append(keyword)
    said = "; ".join("%s (%s)" % (why, ", ".join(k)) for why, k in grouped.items())
    return (
        "nothing to plan for a family whose weakest is %s at %d: every run is "
        "refused or done%s" % (who, level, (" - " + said) if said else "")
    )


# --- looking ahead -----------------------------------------------------------


def _after(facts: Facts, keyword: str, runs: int) -> Facts:
    """The facts once `runs` more runs of `keyword` are done: the count grows,
    its quests are handed in, and every member gains RUNS_PER_LEVEL's worth
    of levels, capped."""
    done = dict(facts.done)
    wing = wing_of(keyword)
    if wing:
        done[wing] = done.get(wing, 0) + int(runs)
    quests = facts.quests
    if quests is not None and wing:
        quests = dict(quests)
        quests[BY_KEYWORD[wing].zone] = 0
    gained = int(runs) // RUNS_PER_LEVEL
    rows = tuple(
        dict(r, level=min(int(r.get("level") or 0) + gained, LEVEL_CAP))
        for r in facts.level_rows
    )
    return replace(facts, done=done, quests=quests, level_rows=rows)


def sequence(facts: Facts, queued: list | None = None, count: int = LOOKAHEAD) -> list:
    """The planned entries after `queued` [(keyword, runs still to go)], as
    the heuristic would choose them: [(Option, weakest level at the time)].

    A forecast for the page and the report, not a commitment: Jev may choose
    differently when the time comes, and the family may level faster or
    slower than RUNS_PER_LEVEL says.
    """
    for keyword, runs in queued or []:
        facts = _after(facts, keyword, runs)
    out = []
    for _ in range(max(int(count), 0)):
        pick = heuristic(options(facts))
        if pick is None:
            break
        out.append((pick, facts.weakest[1]))
        facts = _after(facts, pick.keyword, pick.runs)
    return out


# The latest dungeon choice recorded for one family: what Jev said, what the
# heuristic said and why, which was carried out, and how long ago.
CHOICE_SQL = (
    "SELECT heuristic, heuristic_why, jev, confidence, probabilities, acted, "
    "status, item_name, TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_seconds "
    "FROM overseer_jev_judgment WHERE kind = %s AND subject = %s "
    "ORDER BY id DESC LIMIT 1"
)
CHOICE_KIND = "dungeon_choice"  # jev_choices.KIND_DUNGEON, which imports this


def _runner_up(row: dict, chosen: str) -> str:
    """ "; next Razorfen Kraul at 0.12" off the recorded probabilities."""
    try:
        probs = json.loads(str(row.get("probabilities") or "") or "{}")
    except ValueError:
        return ""
    others = sorted(
        ((float(p), k) for k, p in probs.items() if k != chosen), reverse=True
    )
    if not others:
        return ""
    p, keyword = others[0]
    return "; next %s at %.2f" % (council.keyword_place(keyword), p)


def choice_line(row: dict | None) -> str:
    """Jev's last dungeon choice for a family and its reasons, said; "" for
    none on record."""
    if not row:
        return ""
    heuristic = str(row.get("heuristic") or "")
    answer = str(row.get("jev") or "")
    acted = str(row.get("acted") or "")
    why = str(row.get("heuristic_why") or "")
    when = council.ago(row.get("age_seconds"))
    asked = str(row.get("item_name") or "")
    head = "Jev's last dungeon choice%s%s: " % (
        (", " + when) if when else "",
        (", asked because " + asked) if asked else "",
    )
    if not answer:
        return head + (
            "Jev gave no answer (%s), so the heuristic's %s was queued, because %s."
            % (row.get("status") or "no status", council.keyword_place(heuristic), why)
        )
    sure = "%.2f" % float(row.get("confidence") or 0.0)
    runner = _runner_up(row, answer)
    if acted == "both":
        return head + (
            "Jev chose %s (sure at %s%s), as the heuristic did, because %s. "
            "That was queued." % (council.keyword_place(answer), sure, runner, why)
        )
    if acted == "jev":
        return head + (
            "Jev chose %s (sure at %s%s) over the heuristic's %s, which it "
            "picked because %s. Jev's choice was queued."
            % (
                council.keyword_place(answer),
                sure,
                runner,
                council.keyword_place(heuristic),
                why,
            )
        )
    return head + (
        "Jev leaned to %s at %s%s, short of its floor, so the heuristic's %s was "
        "queued, because %s."
        % (
            council.keyword_place(answer),
            sure,
            runner,
            council.keyword_place(heuristic),
            why,
        )
    )


def page_view(
    queue_view: dict, facts: Facts | None, done: int | None, choice: dict | None = None
) -> dict:
    """The Dungeons tab's lines for one family: now, next planned, and the
    last dungeon choice Jev was asked for, with its reasons.

    `queue_view` is campaignqueue.view's; `done` the leader's run count;
    `choice` the CHOICE_SQL row, or None.
    """
    entries = list((queue_view or {}).get("entries") or [])
    if entries:
        head = entries[0]
        count = (
            "%d of %d" % (min(int(done), head["runs"]), head["runs"])
            if head["status"] == "active" and done is not None
            else "%d runs, starting" % head["runs"]
        )
        now = "Now: %s, %s." % (head["place"], count)
    else:
        now = "Now: no dungeon; the family quests."
    if len(entries) > 1:
        nxt = "Next: %s, %d runs, as queued." % (
            entries[1]["place"],
            entries[1]["runs"],
        )
    elif facts is None:
        nxt = ""
    else:
        queued = []
        if entries:
            head = entries[0]
            left = head["runs"] - (min(int(done or 0), head["runs"]))
            queued = [(head["keyword"], left)]
        ahead = sequence(facts, queued, count=1)
        if ahead:
            option, _level = ahead[0]
            nxt = "Next planned: %s (%s)." % (entry_line(option), option.why)
        else:
            nxt = "Next planned: nothing in range on this continent, so the family quests."
    return {
        "now": now,
        "next": nxt,
        "line": " ".join(p for p in (now, nxt) if p),
        "jev": choice_line(choice),
    }


def portal_coverage() -> set:
    """Every portal keyword the planner sends a family through or counts."""
    return set(BY_KEYWORD) | set(ALTERNATES)
