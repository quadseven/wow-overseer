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
  * the weakest member has not outgrown it (`Run.ceiling`).
  * it has not been run to its target count (`target`).

HOW MANY RUNS (`target`). Not a fixed fifty:

  * a levelling family runs a dungeon until the weakest member would outgrow
    it, estimated at RUNS_PER_LEVEL runs a level;
  * a family at the level cap farms each dungeon AT_CAP_RUNS runs a round, and
    starts another round once every dungeon it can reach has had one;
  * a dungeon that holds quests the family has not finished gets a quest pass
    of QUEST_PASS_RUNS more runs on top.

WHICH ONE (`heuristic`). A ready run before one the family would be carried
through; then the run they will outgrow soonest, because a group levelling
through a band uses a dungeon before it loses it; then the one with the least
of its target done; then path order. Jev is asked the same question over the
same options (jev_choices.dungeon_ask) and its answer is carried out when it
is confident enough; otherwise this answer is.

PURE MODULE: no MySQL, no Discord, no clock. Rows in, choices and sentences
out. The statements the bridge and the site read with are written here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

import council
import dungeonpath

# The source a planned queue entry carries, so the queue's own rows say which
# entries the operator ordered and which this module chose.
SOURCE = "overseer:planner"

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
    "SELECT ID AS quest, QuestSortID AS zone, MinLevel AS min_level, "  # noqa: S608
    "AllowableRaces AS races FROM acore_world.quest_template "
    "WHERE QuestSortID IN (" + ", ".join(str(int(z)) for z in ZONES) + ") "
    "AND LogTitle NOT LIKE '<%%'"
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


def holes(count: int) -> str:
    return ", ".join(["%s"] * max(int(count), 1))


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
    return (
        (not races or bool(races & bit))
        and level >= int(row.get("min_level") or 0)
        and int(row["quest"]) not in done_by.get(name, set())
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
    """

    family: str
    level_rows: tuple
    done: dict
    failed: dict
    quests: dict | None = None
    gear: dict | None = None
    loot: dict | None = None

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


def refusals(facts: Facts) -> dict:
    """Run keyword -> why it is not offered, for every run that is not."""
    _who, level = facts.weakest
    out = {}
    for run in RUNS:
        why = council.door_refusal(run.keyword, list(facts.level_rows))
        if not why and level > run.ceiling:
            why = "outgrown: it tops out at %d" % run.ceiling
        if why:
            out[run.keyword] = why
    return out


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
        want = target(run, level, quests, rounds)
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
            )
        )
    return out


def _order(option: Option) -> int:
    return next(i for i, r in enumerate(RUNS) if r.keyword == option.keyword)


def heuristic(opts: list) -> Option | None:
    """The run a group of players would pick. See the module docstring."""
    if not opts:
        return None
    return min(
        opts,
        key=lambda o: (
            not o.ready,
            o.ceiling,
            o.done / max(o.target, 1),
            _order(o),
        ),
    )


def heuristic_why(pick: Option) -> str:
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
    """
    run = BY_KEYWORD.get(wing_of(str(head.get("keyword") or "")))
    if str(head.get("source") or "") != SOURCE or run is None:
        return Due()
    weakest = [int(r.get("level") or 0) for r in level_rows if r.get("level")]
    if weakest and min(weakest) > run.ceiling:
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
    return "queued %s (%s; %s done of %d) because %s; chosen by %s" % (
        entry_line(option),
        option.why,
        option.done,
        option.target,
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


def page_view(queue_view: dict, facts: Facts | None, done: int | None) -> dict:
    """The Dungeons tab's two lines for one family: now, and next planned.

    `queue_view` is campaignqueue.view's; `done` the leader's run count.
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
    return {"now": now, "next": nxt, "line": " ".join(p for p in (now, nxt) if p)}


def portal_coverage() -> set:
    """Every portal keyword the planner sends a family through or counts."""
    return set(BY_KEYWORD) | set(ALTERNATES)
