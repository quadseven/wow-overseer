"""The questers' play (#924): every quest in reach, and a quest that stops is broken.

WHY THIS EXISTS. The questers (#922, raidteams.QUESTERS) are there to prove
that every quest works. A guild member follows the levelling route
(levelroute.py, guildlevel.py) and the class chains (classquest.py), so most
quests are never tried, and a quest that cannot be finished blocks a member
until somebody notices. A quester does the other thing: it takes every quest
open to it where it stands, works them, hands them in, and moves on only when
nothing in reach is left. A quest that cannot be finished is written down as
broken with the reason, dropped, and left behind.

IN REACH (`open_to`, `in_reach`). A quest of the catalogue (`catalogue`) is in
reach of a quester when:

  * its zone is the quester's zone (a starting area counts as the zone it lies
    in, `START_AREAS`: Northshire Valley is Elwynn Forest);
  * its race and class masks hold the quester's, its minimum level is met and
    its own level is at most levelroute.ABOVE over the quester's;
  * the quest before it is rewarded (or held, for a negative PrevQuestID), and
    no quest of its exclusive group is rewarded or held;
  * the quester has not finished it, does not hold it, and has not found it
    broken.

What the catalogue leaves out is what a five cannot reach: dungeon, raid and
PvP quests (`OUT_OF_REACH_INFO`), quests over the classic level cap, and
quests outside the classic world and the Blood Elf and Draenei starting lands.

WHAT A QUESTER DOES NEXT (`next_move`), one move a pass, in this order:

  1. drop a quest it holds that is broken (`classquest.ABANDON`);
  2. hand in a complete quest, the nearest turn-in NPC first;
  3. take a quest in reach while the log has a free slot (questlog.LOG_SLOTS),
     the nearest quest giver first;
  4. work a quest it holds: walk to the nearest objective spawn at most
     classquest.OVERLEVEL_MAX levels over it and hunt its creature there with
     the module's `hunt-spawn` row, as a class hunt does (`step_for`);
  5. with nothing left in reach, go to the next zone (`next_zone`): the zone
     whose band (levelroute.bands, the catalogue's own levels) is lowest of the
     zones holding a quest in reach for it, the most quests first on a tie.
     The move is the take of that zone's nearest quest; a zone on the other
     continent is a `cross-to-map` row (classquest.CROSSING_VERB) first.

The party works together through questshare (the bridge shares among the five
as it does for the family), and every take, hand-in and drop is the module's
own verb (`take quest:`, `turnin quest:`, `abandon quest:`). Nothing is ever
granted: a quest is never completed, skipped or rewarded by a command.

BROKEN (`Broken`, `failures`). A quest is broken when:

  * FAILED: the log holds it as failed (an escort died, a timer ran out);
  * STALLED: its objectives (status and counters) have not moved for
    STALL_SECONDS of play while the quester was working it (`Clock`). Play is
    time online and alive between two looks, at most PLAY_GAP_SECONDS each, so
    a bridge restart or a night offline is not play. A quest is being worked
    while it is in the quester's log and of the zone it stands in, or is the
    quest its last move was for;
  * GIVER_MISSING: a creature is named as its giver, none is spawned, and
    no gameobject or item starts it either;
  * ENDER_MISSING: nothing is named to hand it in to, or the creature named is
    not spawned, or the world refused every spawn of it as gone;
  * SOURCE_MISSING: the world refused every spawn of its objective as gone.
    A quest whose objective no spawned creature is or drops is not judged on
    that alone (a script may summon it, a chest or a vendor may hold the
    item): it stalls, and its stall says so (STALLED_UNSOURCED);
  * REFUSED_TAKE / REFUSED_TURN_IN: the world refused the take or the hand-in
    FAILS_BEFORE_BROKEN times in a day, with its own words appended.

A broken quest the quester holds is dropped (the move in 1 above); one it
never held (a giver that is not there) is only recorded. The bridge writes
each into the quest ledger (questledger.py, #923) with its reason.

PURE MODULE: rows in, moves and verdicts out. No MySQL; the clock is passed in.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace

import classhunt
import classic
import classquest
import guildcorps
import guildjobs
import guildroute
import levelroute
import questlog

# The step's action word, in the command log's source (guildjobs.source_for).
ACTION = "quester"
WALK_ACTION = ACTION + "-walk"
# A quester's crossing row has its own source action (quest takes, hand-ins
# and hunts are ACTION), so it shares the one crossing clock and the walls of
# the class quest's and the level step's crossings (guildjobs.CROSS_ACTIONS).
#
# ONE CROSSING ROW EVERY PASS (2026-10-18). Written under ACTION, a quester's
# `cross-to-map` row was outside that clock, and the quester pass asks every
# two minutes: of 4,252 crossing rows the dev realm took in a day, 3,717 were
# seven questers', refused 1,286 times as having no transport (two death
# knights in Acherus, map 609, and a Blood Elf on map 530 asking for Kalimdor),
# 491 times as held by another job (the revived sickness hold after a death)
# and 413 times at the realm's crossing cap. The module said each of these
# once; the rest is the same question asked again.
CROSS_ACTION = guildjobs.QUESTER_CROSS_ACTION

# Two hours of play with no objective moving is a broken quest (#924).
STALL_SECONDS = 2 * 60 * 60
# The longest gap between two looks counted as play. Twice the bridge's pass
# at its default, so one slow pass is still play and a restart or an outage of
# the bridge is not.
PLAY_GAP_SECONDS = 10 * 60

# The quest log's hard cap (MAX_QUEST_LOG_SIZE): a full log refuses every take.
LOG_SLOTS = questlog.LOG_SLOTS

# QuestInfoID of the quests a party of five does not reach: PvP (41), raid
# (62), dungeon (81), heroic (85), 10 and 25 player raid (88, 89).
OUT_OF_REACH_INFO = frozenset({41, 62, 81, 85, 88, 89})

# A starting area's quests carry the area as their QuestSortID; the character
# stands in the zone around it (its `zone` column is the zone). Both are read as
# the zone. AreaTable: the nine starting areas of #922 and their zones.
START_AREAS = {
    9: 12,  # Northshire Valley, Elwynn Forest
    132: 1,  # Coldridge Valley, Dun Morogh
    188: 141,  # Shadowglen, Teldrassil
    3526: 3524,  # Ammen Vale, Azuremyst Isle
    363: 14,  # Valley of Trials, Durotar
    154: 85,  # Deathknell, Tirisfal Glades
    220: 215,  # Camp Narache, Mulgore
    3431: 3430,  # Sunstrider Isle, Eversong Woods
}

STATUS_COMPLETE = classquest.STATUS_COMPLETE
STATUS_INCOMPLETE = classquest.STATUS_INCOMPLETE
# A failed quest (an escort that died, a timer that ran out) holds its log slot
# until it is dropped (questlog.FAILED).
STATUS_FAILED = questlog.FAILED

# The reasons a quest is broken, as the ledger records them. FAILED is the
# ledger's own words for it (questledger.FAILED_REASON, #923).
FAILED = "the quest failed in the log"
STALLED = "its objectives did not move for 2 hours of play"
GIVER_MISSING = "the quest giver is not in the world"
ENDER_MISSING = "the turn-in NPC is not in the world"
SOURCE_MISSING = "an objective's creature or item is never found in the world"
STALLED_UNSOURCED = STALLED + ", and no spawned creature is or drops what it asks for"
REFUSED_TAKE = "the quest giver would not give it"
REFUSED_TURN_IN = "the turn-in NPC would not take it"

# The world's own words for a spawn that is not there (classquest.SPAWN_REFUSALS).
GONE = "no such spawn in the world"
# The world's own words when an abandon is refused for a quest that is
# complete: hand it in instead of dropping it (#1085).
COMPLETE_HAND_IN = "it is complete; hand it in"
# A take or a hand-in the world refused this many times in a day is broken.
FAILS_BEFORE_BROKEN = 3
# The quest ledger's reason column.
REASON_WIDTH = 255

_FAILED = ("error", "failed", "refused", "expired")
_WENT = ("applied", "delivered")
_CHAIN_ROW = re.compile(r"^(take|turnin|abandon) quest:(\d+)")

_NPCS = "".join(
    "q.RequiredNpcOrGo%d AS npc%d, q.RequiredNpcOrGoCount%d AS npc_count%d, "
    % (i, i, i, i)
    for i in range(1, 5)
)
_ITEMS = "".join(
    "q.RequiredItemId%d AS item%d, q.RequiredItemCount%d AS item_count%d, "
    % (i, i, i, i)
    for i in range(1, 7)
)
_PROVIDED = "q.StartItem AS provided0, " + "".join(
    "q.ItemDrop%d AS source%d, " % (i, i) for i in range(1, 5)
)

# Every quest with a zone, of the classic level range, that a five may reach.
# The world's quests, the same columns classquest.QUESTS_SQL reads and the
# quest's own level, zone and type. Built from this module's integer constants
# only, no outside value (S608 does not apply; ruff reports it on the first
# string, so the noqa sits there).
QUESTS_SQL = (
    "SELECT q.ID AS id, q.LogTitle AS title, q.QuestSortID AS sort, "  # noqa: S608
    "q.QuestSortID AS zone, q.QuestLevel AS level, q.QuestInfoID AS info, "
    "q.MinLevel AS min_level, q.AllowableRaces AS races, "
    "COALESCE(a.AllowableClasses, 0) AS classes, "
    "COALESCE(a.PrevQuestID, 0) AS prev_signed, "
    "COALESCE(a.PrevQuestID, 0) AS prev, "
    "COALESCE(a.ExclusiveGroup, 0) AS exclusive, q.RewardSpell AS reward, "
    "q.RewardDisplaySpell AS display, q.SuggestedGroupNum AS grp, "
    + _NPCS
    + _ITEMS
    + _PROVIDED
    + "0 AS pad FROM acore_world.quest_template q "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = q.ID "
    "WHERE q.QuestSortID > 0 AND q.MinLevel <= "
    + str(classic.MAX_LEVEL)
    + " AND q.QuestLevel <= "
    + str(classic.MAX_LEVEL)
    + " AND q.QuestInfoID NOT IN ("
    + ", ".join(str(i) for i in sorted(OUT_OF_REACH_INFO))
    + ") AND q.LogTitle NOT LIKE '<%%' AND q.LogTitle NOT LIKE 'NOT A QUEST%%'"
)

# What starts each quest besides a spawned creature (classquest.STARTERS_SQL),
# and every creature named as a giver whether it is spawned or not, so a giver
# that is named and not in the world is told from a quest nothing gives. Two
# constant strings joined; `{quests}` is filled with integer ids only
# (bridge._quester_catalogue), so S608 does not apply.
STARTERS_SQL = (
    classquest.STARTERS_SQL + " UNION ALL "  # noqa: S608
    "SELECT s.quest, 'creature', s.id FROM acore_world.creature_queststarter s "
    "WHERE s.quest IN ({quests})"
)

# Everything named to hand each quest in to: a creature or a gameobject.
ENDERS_SQL = (
    "SELECT e.quest AS quest, 'creature' AS kind, e.id AS entry "
    "FROM acore_world.creature_questender e WHERE e.quest IN ({quests}) "
    "UNION ALL "
    "SELECT e.quest, 'gameobject', e.id FROM acore_world.gameobject_questender e "
    "WHERE e.quest IN ({quests})"
)

# The questers: where each stands (the snapshot, fresh within two minutes),
# its quest log with each quest's counters summed, and what it was rewarded.
MEMBERS_SQL = (
    "SELECT c.guid, c.name, c.class AS class_id, c.race, c.level, c.online, "
    "c.map AS map_id, c.zone AS saved_zone, s.pos_x, s.pos_y, s.zone_id, s.health, "
    "EXISTS (SELECT 1 FROM corpse k WHERE k.guid = c.guid) AS has_corpse "
    "FROM characters c "
    "LEFT JOIN overseer_snapshot s ON s.name = c.name "
    "AND s.updated_at > NOW() - INTERVAL 120 SECOND "
    "WHERE c.name IN ({names})"
)
LOG_SQL = (
    "SELECT guid, quest, status, "
    "(mobcount1 + mobcount2 + mobcount3 + mobcount4 + itemcount1 + itemcount2 + "
    "itemcount3 + itemcount4 + itemcount5 + itemcount6) AS progress "
    "FROM character_queststatus WHERE guid IN ({guids}) AND status IN (1, 3, 5)"
)
REWARDED_SQL = (
    "SELECT guid, quest FROM character_queststatus_rewarded WHERE guid IN ({guids})"
)
# The quest ledger (questledger.py, #923): what is recorded of each quester's
# quests, and a broken quest written into it. A quest already in the ledger
# keeps the time it was first taken.
LEDGER_SQL = (
    "SELECT l.quest, c.name, l.state FROM overseer_quest_ledger l "
    "JOIN characters c ON c.guid = l.guid WHERE c.name IN ({names})"
)
BROKEN_SQL = (
    "INSERT INTO overseer_quest_ledger "
    "(quest, guid, character_name, state, first_taken, finished, reason) "
    "SELECT %s, c.guid, c.name, 'broken', IF(%s, NOW(), NULL), NOW(), %s "
    "FROM characters c WHERE c.name = %s "
    "ON DUPLICATE KEY UPDATE state = 'broken', finished = NOW(), reason = VALUES(reason)"
)


def members_from_rows(rows, log_rows, rewarded_rows) -> list:
    """Member rows from MEMBERS_SQL's, LOG_SQL's and REWARDED_SQL's rows. The
    position and zone come from a fresh snapshot only, so a walk is never judged
    from an old one; with none the quester is offline or unplaced."""
    log_by, progress_by, done_by = _logs_by_guid(log_rows, rewarded_rows)
    out = []
    for r in rows or ():
        guid = _int(r.get("guid"))
        out.append(
            _member_from_row(
                r,
                log_by.get(guid, {}),
                frozenset(done_by.get(guid, ())),
                progress_by.get(guid, {}),
            )
        )
    return out


def _logs_by_guid(log_rows, rewarded_rows) -> tuple:
    """(guid -> {quest: status}, guid -> {quest: progress}, guid -> {quests
    rewarded}) from LOG_SQL's and REWARDED_SQL's rows."""
    log_by, progress_by, done_by = {}, {}, {}
    for r in log_rows or ():
        guid, qid = _int(r.get("guid")), _int(r.get("quest"))
        log_by.setdefault(guid, {})[qid] = _int(r.get("status"))
        progress_by.setdefault(guid, {})[qid] = _int(r.get("progress"))
    for r in rewarded_rows or ():
        done_by.setdefault(_int(r.get("guid")), set()).add(_int(r.get("quest")))
    return log_by, progress_by, done_by


def _alive(row) -> bool:
    """Alive with no health read, above 1, or at 1 with no corpse (a ghost has one)."""
    health = row.get("health")
    if health is None:
        return True
    return _int(health) > 1 or (_int(health) == 1 and not row.get("has_corpse"))


def _member_from_row(r, quest_log, quests_done, quest_progress):
    fresh = r.get("pos_x") is not None and r.get("pos_y") is not None
    map_id = r.get("map_id")
    return Member(
        name=str(r.get("name") or ""),
        level=_int(r.get("level")),
        race=_int(r.get("race")),
        class_id=_int(r.get("class_id")),
        map_id=_int(map_id) if map_id is not None else None,
        x=float(r["pos_x"]) if fresh else None,
        y=float(r["pos_y"]) if fresh else None,
        zone_id=_int(r.get("zone_id") if fresh else r.get("saved_zone")),
        online=bool(_int(r.get("online"))) and fresh,
        alive=_alive(r),
        quest_log=quest_log,
        quests_done=quests_done,
        quest_progress=quest_progress,
    )


def zone_of(zone_id) -> int:
    """The zone a quest's sort or a character's zone column stands for."""
    z = int(zone_id or 0)
    return START_AREAS.get(z, z)


def side_of(race) -> str:
    return (
        levelroute.HORDE if int(race) in levelroute.HORDE_RACES else levelroute.ALLIANCE
    )


@dataclass(frozen=True)
class Facts:
    """What the catalogue knows of a quest beyond classquest.Quest."""

    zone: int
    level: int
    classes: int = 0
    # quest_template_addon.PrevQuestID as stored: positive, rewarded first;
    # negative, held first.
    prev: int = 0
    # A creature is named as its giver (spawned or not).
    giver_named: bool = False
    # What is named to hand it in to: creatures, gameobjects.
    ender_npcs: bool = False
    ender_objects: bool = False


@dataclass(frozen=True)
class Catalogue:
    """Every quest a quester may take, as a classquest.Book, with each quest's
    zone and level, and each side's zone bands."""

    book: classquest.Book
    facts: dict = field(default_factory=dict)
    # side -> zone -> (floor, ceiling, count), levelroute.bands of these quests
    bands: dict = field(default_factory=dict)

    def quest(self, quest_id):
        return self.book.quests.get(int(quest_id))


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def catalogue(quest_rows, giver_rows, spawn_rows, loot_rows, start_rows, ender_rows):
    """The Catalogue from the world's rows: QUESTS_SQL's, classquest's
    GIVERS_SQL, SPAWNS_SQL and LOOT_SQL rows for these quests, STARTERS_SQL's
    and ENDERS_SQL's.

    Only the classic world: a quest is kept when its zone holds a quest whose
    giver is spawned on a classic continent, or is one of the starting lands.
    """
    rows = list(quest_rows or ())
    book = classquest.build(
        rows, giver_rows, spawn_rows, loot_rows, start_rows=start_rows, every=True
    )
    named, npc_enders, object_enders = _named(start_rows, ender_rows)
    zones = {_int(r.get("id")): zone_of(r.get("zone")) for r in rows}
    classic_zones = _classic_zones(book, zones)
    facts = {}
    kept = {}
    band_rows = []
    for r in rows:
        qid = _int(r.get("id"))
        quest = book.quests.get(qid)
        if quest is None or zones.get(qid, 0) not in classic_zones:
            continue
        facts[qid] = Facts(
            zone=zones[qid],
            level=max(_int(r.get("level")), quest.min_level, 1),
            classes=_int(r.get("classes")),
            prev=_int(r.get("prev_signed")),
            giver_named=qid in named,
            ender_npcs=qid in npc_enders,
            ender_objects=qid in object_enders,
        )
        kept[qid] = quest
        band_rows.append(
            {
                "zone": zones[qid],
                "level": facts[qid].level,
                "races": quest.races,
                "classes": facts[qid].classes,
            }
        )
    bands = {side: levelroute.bands(band_rows, side) for side in levelroute.RACE_MASK}
    return Catalogue(classquest.Book(kept), facts, bands)


def _named(start_rows, ender_rows) -> tuple:
    """(quests a creature is named to give, quests a creature is named to take,
    quests a gameobject is named to take) from STARTERS_SQL's and ENDERS_SQL's
    rows."""
    named = {
        _int(r.get("quest"))
        for r in start_rows or ()
        if str(r.get("kind") or "") == "creature"
    }
    npc_enders, object_enders = set(), set()
    for r in ender_rows or ():
        kind = str(r.get("kind") or "")
        (npc_enders if kind == "creature" else object_enders).add(_int(r.get("quest")))
    return named, npc_enders, object_enders


def _classic_zones(book, zones) -> set:
    """The starting lands, and every zone holding a quest whose giver is
    spawned on a classic continent."""
    out = set(classic.STARTING_LAND_ZONES)
    for qid, quest in book.quests.items():
        if any(int(s.map_id) in classic.CLASSIC_CONTINENTS for s in quest.starters):
            out.add(zones.get(qid, 0))
    return out


@dataclass(frozen=True)
class Member:
    """One quester as the pass reads it."""

    name: str
    level: int
    race: int
    class_id: int
    map_id: int | None = None
    x: float | None = None
    y: float | None = None
    zone_id: int = 0
    online: bool = False
    alive: bool = True
    # quest id -> status (1 complete, 3 incomplete), the quests in its log
    quest_log: dict = field(default_factory=dict)
    quests_done: frozenset = frozenset()
    # quest id -> the sum of its objective counters
    quest_progress: dict = field(default_factory=dict)

    @property
    def zone(self) -> int:
        return zone_of(self.zone_id)

    @property
    def placed(self) -> bool:
        return self.map_id is not None and self.x is not None and self.y is not None


@dataclass(frozen=True)
class Broken:
    """A quest found broken: `held` when the quester holds it and drops it."""

    name: str
    quest: int
    title: str
    reason: str
    held: bool = False

    @property
    def ledger_reason(self) -> str:
        return self.reason[:REASON_WIDTH]


@dataclass(frozen=True)
class Attempt:
    """One of a quester's recent rows: what it asked and how it ended."""

    name: str
    command: str
    status: str
    reason: str = ""
    spawn: int = 0
    age_minutes: int = 0

    @property
    def failed(self) -> bool:
        return self.status in _FAILED


def attempts(rows) -> tuple:
    """Attempt rows from the command log's rows of this pass's source (id,
    target_name, command, source, status, result, age), with the module's
    reason and the spawn a walk named read as guildjobs reads them."""
    out = []
    for row in rows or ():
        if guildjobs.action_of(row.get("source")) not in (ACTION, WALK_ACTION):
            continue
        read = guildjobs.recent_from_rows([row])
        recent = read[0] if read else None
        out.append(
            Attempt(
                name=str(row.get("target_name") or ""),
                command=str(row.get("command") or ""),
                status=str(row.get("status") or ""),
                reason=(recent.reason or recent.refusal) if recent else "",
                spawn=recent.spawn if recent else 0,
                age_minutes=_int(row.get("age"), 10**6),
            )
        )
    return tuple(out)


def gone_spawns(name, tried) -> frozenset:
    """The spawn ids the world told this quester are not in the world."""
    return frozenset(
        a.spawn for a in tried or () if a.name == name and a.spawn and a.reason == GONE
    )


def left_spawns(name, tried) -> frozenset:
    """The spawn ids this quester leaves for now: the gone ones, and those a
    walk was refused for a lasting reason (classquest.SPAWN_REFUSALS: a drop on
    the way, the other side's ground) inside classquest.SPAWN_REFUSED_MINUTES,
    or for a short one (stopped getting nearer, died on the way) inside
    classquest.SPAWN_SHORT_MINUTES. Only the gone ones say the quest is broken:
    the rest say the way there is, for now."""
    out = set(gone_spawns(name, tried))
    for a in tried or ():
        if a.name != name or not a.spawn or a.reason not in classquest.SPAWN_REFUSALS:
            continue
        short = a.reason in classquest.SPAWN_SHORT_REFUSALS
        hold = (
            classquest.SPAWN_SHORT_MINUTES
            if short
            else classquest.SPAWN_REFUSED_MINUTES
        )
        if a.age_minutes < hold:
            out.add(a.spawn)
    return frozenset(out)


def refusals(name, tried) -> dict:
    """(verb, quest id) -> (times refused, the last words) for this quester's
    takes and hand-ins the world refused."""
    out: dict = {}
    for a in sorted(tried or (), key=lambda a: -a.age_minutes):
        if a.name != name or not a.failed:
            continue
        found = _CHAIN_ROW.match(a.command)
        if not found:
            continue
        key = (found.group(1), int(found.group(2)))
        count, _words = out.get(key, (0, ""))
        out[key] = (count + 1, a.reason)
    return out


def _module_complete(name, tried) -> frozenset:
    """The quest ids the module told this quester are complete, by refusing
    their abandon with its complete words: they are due a turn-in, never a
    drop (#1085)."""
    return frozenset(
        qid
        for (verb, qid), (_count, words) in refusals(name, tried).items()
        if verb == "abandon" and COMPLETE_HAND_IN in (words or "")
    )


class Clock:
    """Play time with no objective moving, per quester and quest.

    `observe` is told each pass what the quest's objectives read (its status and
    counters) and whether the quester was working it; it answers the seconds of
    play since they last moved. Its state is plain data (`dump`, `load`), so the
    bridge keeps it across restarts."""

    def __init__(self):
        # (name, quest) -> [value, seconds played without a move, last look]
        self._by: dict = {}

    def observe(self, name, quest, value, now, playing) -> float:
        key = (str(name), int(quest))
        value = list(value)
        held = self._by.get(key)
        if held is None or held[0] != value:
            self._by[key] = [value, 0.0, float(now)]
            return 0.0
        gap = float(now) - float(held[2])
        if playing and 0 < gap:
            held[1] += min(gap, PLAY_GAP_SECONDS)
        held[2] = float(now)
        return held[1]

    def played(self, name, quest) -> float:
        held = self._by.get((str(name), int(quest)))
        return held[1] if held else 0.0

    def forget(self, name, keep) -> None:
        """Drop every quest of `name` not in `keep` (no longer in its log)."""
        keep = {int(q) for q in keep}
        for key in [k for k in self._by if k[0] == name and k[1] not in keep]:
            del self._by[key]

    def dump(self) -> dict:
        return {"%s:%d" % k: v for k, v in self._by.items()}

    def load(self, data) -> None:
        for key, held in (data or {}).items():
            name, _, quest = str(key).rpartition(":")
            try:
                value, played, last = held
                self._by[(name, int(quest))] = [list(value), float(played), float(last)]
            except (TypeError, ValueError):
                continue


def _yards(member, spawn) -> float:
    return math.hypot(float(member.x) - spawn.x, float(member.y) - spawn.y)


def _here(member, spawns, gone=frozenset()) -> list:
    if not member.placed:
        return []
    return [
        s for s in spawns if int(s.map_id) == int(member.map_id) and s.guid not in gone
    ]


def _nearest(member, spawns, gone=frozenset()):
    here = _here(member, spawns, gone)
    return min(here, key=lambda s: (_yards(member, s), s.guid)) if here else None


def _class_ok(facts: Facts, class_id) -> bool:
    return not facts.classes or bool(facts.classes & (1 << (int(class_id) - 1)))


def _exclusive_closed(cat: Catalogue, member, quest) -> bool:
    if not quest.exclusive:
        return False
    return any(
        other.exclusive == quest.exclusive
        and other.id != quest.id
        and (other.id in member.quests_done or other.id in member.quest_log)
        for other in cat.book.quests.values()
    )


def open_to(cat: Catalogue, member, quest_id, broken=frozenset()) -> bool:
    """Whether the quester may take this quest now: race, class, level, the
    quest before it, its exclusive group, and not done, held or broken."""
    qid = int(quest_id)
    quest, facts = cat.quest(qid), cat.facts.get(qid)
    if quest is None or facts is None:
        return False
    if qid in member.quests_done or qid in member.quest_log or qid in broken:
        return False
    if not quest.admits(member.race) or not _class_ok(facts, member.class_id):
        return False
    if int(member.level) < quest.min_level:
        return False
    if facts.level > int(member.level) + levelroute.ABOVE:
        return False
    if facts.prev > 0 and facts.prev not in member.quests_done:
        return False
    if facts.prev < 0 and -facts.prev not in member.quest_log:
        return False
    return not _exclusive_closed(cat, member, quest)


def in_reach(cat: Catalogue, member, zone, broken=frozenset()) -> list:
    """The quest ids of `zone` the quester may take now, in id order."""
    return [
        qid
        for qid, facts in sorted(cat.facts.items())
        if facts.zone == int(zone) and open_to(cat, member, qid, broken)
    ]


def _working(cat: Catalogue, member, last_quest=0) -> set:
    """The quests the quester is working now: those in its log of the zone it
    stands in, and the quest its last move was for."""
    out = {
        qid
        for qid in member.quest_log
        if (cat.facts.get(qid) is not None and cat.facts[qid].zone == member.zone)
    }
    if last_quest and int(last_quest) in member.quest_log:
        out.add(int(last_quest))
    return out


def _fields_gone(quest, gone) -> bool:
    """Every spawn of the objective was refused as not in the world."""
    return bool(quest.fields) and all(s.guid in gone for s in quest.fields)


def _ender_missing(quest, facts: Facts, gone) -> bool:
    """Nothing to hand the quest in to: no gameobject is named, and no named
    creature is spawned (or every spawn of it was refused as gone)."""
    if facts.ender_objects:
        return False
    return not [s for s in quest.enders if s.guid not in gone]


def failures(cat: Catalogue, member, clock, now, tried=(), last_quest=0) -> list:
    """Broken rows for the quests the quester holds that cannot be finished:
    a stall of STALL_SECONDS of play, a turn-in NPC or an objective the world
    does not hold, or a take or a hand-in the world keeps refusing. The clock
    is told every quest in the log, so it must be asked once a pass."""
    gone = gone_spawns(member.name, tried)
    refused = refusals(member.name, tried)
    working = _working(cat, member, last_quest)
    playing = bool(member.online and member.alive)
    out = []
    for qid in sorted(member.quest_log):
        status = int(member.quest_log[qid])
        value = (status, int(member.quest_progress.get(qid, 0)))
        played = clock.observe(member.name, qid, value, now, playing and qid in working)
        quest, facts = cat.quest(qid), cat.facts.get(qid)
        if quest is None or facts is None:
            continue
        reason = _broken_reason(quest, facts, status, played, gone, refused)
        if reason:
            out.append(Broken(member.name, qid, quest.title, reason, held=True))
    clock.forget(member.name, member.quest_log)
    return out


def _broken_reason(quest, facts: Facts, status, played, gone, refused) -> str:
    """Why a quest the quester holds is broken, "" when it is not (yet). A
    complete quest's objectives cannot move, so stillness never stalls it:
    it is due a turn-in, not a drop (#1085)."""
    if status == STATUS_FAILED:
        return FAILED
    if _ender_missing(quest, facts, gone):
        return ENDER_MISSING
    if status == STATUS_INCOMPLETE and _fields_gone(quest, gone):
        return SOURCE_MISSING
    count, words = refused.get(("turnin", quest.id), (0, ""))
    if count >= FAILS_BEFORE_BROKEN:
        return _refused_words(REFUSED_TURN_IN, words)
    if played < STALL_SECONDS or status == STATUS_COMPLETE:
        return ""
    unsourced = (quest.kills or quest.items) and not quest.fields
    return STALLED_UNSOURCED if unsourced else STALLED


def _refused_words(reason, words) -> str:
    return "%s: %s" % (reason, words) if words else reason


def _giver_failure(cat: Catalogue, member, qid, gone, refused):
    """The reason a quest in reach cannot be taken, "" when it can or when what
    stands in the way is no fault of the quest (a giver on another map, or a
    quest a gameobject or an item starts, which no verb takes)."""
    quest, facts = cat.quest(qid), cat.facts[qid]
    count, words = refused.get(("take", qid), (0, ""))
    if count >= FAILS_BEFORE_BROKEN:
        return _refused_words(REFUSED_TAKE, words)
    if any(kind != "creature" for kind, _entry in quest.other_starts):
        return ""
    if facts.giver_named and not [s for s in quest.starters if s.guid not in gone]:
        return GIVER_MISSING
    return ""


@dataclass(frozen=True)
class Plan:
    """One quester's pass: its move (None for none), the quests it found broken,
    and a line saying what it does or why it waits."""

    name: str
    move: classquest.Move | None = None
    broken: tuple = ()
    line: str = ""


def _move(kind, member, quest, spot, said, to_map=-1) -> classquest.Move:
    return classquest.Move(
        kind,
        quest.id,
        quest.klass,
        spot,
        said,
        "",
        "quester",
        title=quest.title,
        to_map=to_map,
    )


def next_zone(cat: Catalogue, member, broken=frozenset()):
    """(zone, its open quest ids) of the zone the quester goes to next, or
    (0, []) when no zone holds a quest in reach for it: the lowest band of
    its side among those zones, the most quests first on a tie."""
    bands = cat.bands.get(side_of(member.race), {})
    best = None
    for zone in sorted({f.zone for f in cat.facts.values()} - {member.zone}):
        opens = in_reach(cat, member, zone, broken)
        if not opens:
            continue
        band = bands.get(zone, (0, 0, 0))
        key = (int(band[0]), -len(opens), zone)
        if best is None or key < best[0]:
            best = (key, zone, opens)
    return (best[1], best[2]) if best else (0, [])


def _travel(cat: Catalogue, member, broken, gone):
    """The move that takes the quester to the next zone: the take of that
    zone's nearest quest on its map, or a crossing to the continent the zone's
    quests are on; (None, why) when there is no zone to go to."""
    zone, opens = next_zone(cat, member, broken)
    if not zone:
        return None, "%s has no quest in reach in any zone" % member.name
    name = levelroute.zone_name(zone)
    options = []
    for qid in opens:
        quest = cat.quest(qid)
        spot = _nearest(member, quest.starters, gone)
        if spot is not None:
            options.append((_yards(member, spot), qid, quest, spot))
    if options:
        _d, _q, quest, spot = min(options, key=lambda o: (o[0], o[1]))
        said = (
            "%s has nothing left in reach here and goes on to %s: walks to %s and takes %s"
            % (member.name, name, spot.name or "its giver", quest.title)
        )
        return _move(classquest.TAKE, member, quest, spot, said), ""
    maps = sorted(
        {
            int(s.map_id)
            for qid in opens
            for s in cat.quest(qid).starters
            if int(s.map_id) in classquest.CONTINENTS
        }
    )
    if maps and member.placed and int(member.map_id) not in maps:
        quest = cat.quest(opens[0])
        said = "%s crosses to %s for %s" % (
            member.name,
            classquest.CONTINENTS[maps[0]],
            name,
        )
        return _move(classquest.CROSS, member, quest, None, said, to_map=maps[0]), ""
    return None, "%s would go on to %s and has no way there from where it stands" % (
        member.name,
        name,
    )


def next_move(cat: Catalogue, member, broken=frozenset(), found=(), tried=()):
    """(move or None, why there is none, quests found broken that it never
    held): the quester's next move toward every quest in reach.

    `broken` is the quest ids already found broken for this quester, `found`
    this pass's Broken rows for the quests it holds (`failures`)."""
    left = left_spawns(member.name, tried)
    # Quests the module told this quester are complete: due a turn-in, never
    # a drop, even when their log row still says otherwise (#1085).
    complete = _module_complete(member.name, tried)
    # 1. A broken quest it holds is dropped.
    move = _drop(cat, member, broken, found, complete)
    if move is not None:
        return move, "", []
    skip = set(broken) | {b.quest for b in found}
    # 2. A complete quest, the nearest turn-in NPC first.
    move = _hand_in(cat, member, skip, left, complete)
    if move is not None:
        return move, "", []
    # 3. A quest in reach in its zone, the nearest giver first, while the log
    # has room.
    takes, never_held = _takes(cat, member, skip, left, tried)
    if takes and len(member.quest_log) < LOG_SLOTS:
        _d, _q, quest, spot = min(takes, key=_by_yards)
        said = "%s walks to %s and takes %s" % (
            member.name,
            spot.name or "its giver",
            quest.title,
        )
        return _move(classquest.TAKE, member, quest, spot, said), "", never_held
    # 4. A quest it holds: the nearest objective spawn within its level.
    move = _hunt(cat, member, skip, left)
    if move is not None:
        return move, "", never_held
    if takes:
        return (
            None,
            "%s's quest log is full (%d of %d)"
            % (member.name, len(member.quest_log), LOG_SLOTS),
            never_held,
        )
    # 5. Nothing left in reach here: the next zone.
    move, why = _travel(cat, member, skip, left)
    return move, why, never_held


def _by_yards(option):
    """The sort key of a (yards, quest id, quest, spot) option: nearest first,
    then the lowest quest id."""
    return option[0], option[1]


def _drop(cat: Catalogue, member, broken, found, complete=frozenset()):
    """The drop of the first broken quest the quester holds, or None. A quest
    the module called complete is never dropped (#1085)."""
    held_broken = [b for b in found if b.held and b.quest not in complete] + [
        Broken(member.name, q, cat.quest(q).title if cat.quest(q) else "", "", True)
        for q in sorted(member.quest_log)
        if q in broken and q not in complete
    ]
    if not held_broken:
        return None
    b = held_broken[0]
    quest = cat.quest(b.quest) or classquest.Quest(
        b.quest, b.title, 0, 0, 0, 0, 0, 0, 0
    )
    said = "%s drops %s: %s" % (
        member.name,
        b.title or b.quest,
        b.reason or "it is broken",
    )
    return _move(classquest.ABANDON, member, quest, None, said)


def _held(cat: Catalogue, member, status, skip):
    """(quest id, quest) of each quest in the log at `status`, not in `skip`."""
    for qid, held in member.quest_log.items():
        quest = cat.quest(qid)
        if quest is not None and int(held) == status and qid not in skip:
            yield qid, quest


def _hand_in(cat: Catalogue, member, skip, left, complete=frozenset()):
    """The hand-in of the complete quest whose turn-in NPC is nearest, or
    None. A quest the module called complete is handed in even when its log
    row still says otherwise (#1085)."""
    due = {qid for qid, _quest in _held(cat, member, STATUS_COMPLETE, skip)}
    due |= {qid for qid in complete if qid in member.quest_log}
    ready = []
    for qid in due:
        quest = cat.quest(qid)
        spot = _nearest(member, quest.enders, left) if quest is not None else None
        if spot is not None:
            ready.append((_yards(member, spot), qid, quest, spot))
    if not ready:
        return None
    _d, _q, quest, spot = min(ready, key=_by_yards)
    said = "%s walks to %s and hands in %s" % (
        member.name,
        spot.name or "its ender",
        quest.title,
    )
    return _move(classquest.TURN_IN, member, quest, spot, said)


def _takes(cat: Catalogue, member, skip, left, tried) -> tuple:
    """(the (yards, quest id, quest, giver) of each quest in reach in the
    quester's zone with a giver it can walk to, Broken rows for those whose
    giver fails). A quest found broken here is added to `skip`."""
    gone = gone_spawns(member.name, tried)
    refused = refusals(member.name, tried)
    never_held = []
    takes = []
    for qid in in_reach(cat, member, member.zone, skip):
        why = _giver_failure(cat, member, qid, gone, refused)
        if why:
            never_held.append(Broken(member.name, qid, cat.quest(qid).title, why))
            skip.add(qid)
            continue
        spot = _nearest(member, cat.quest(qid).starters, left)
        if spot is not None:
            takes.append((_yards(member, spot), qid, cat.quest(qid), spot))
    return takes, never_held


def _hunt(cat: Catalogue, member, skip, left):
    """The hunt at the nearest objective spawn within the quester's level of
    an incomplete quest it holds, or None."""
    hunts = []
    for qid, quest in _held(cat, member, STATUS_INCOMPLETE, skip):
        spot = _nearest(
            member, classquest.within_level(member, classquest.solo_fields(quest)), left
        )
        if spot is not None:
            hunts.append((_yards(member, spot), qid, quest, spot))
    if not hunts:
        return None
    _d, _q, quest, spot = min(hunts, key=_by_yards)
    said = "%s works %s at %s" % (
        member.name,
        quest.title,
        spot.name or "its objective",
    )
    return _move(classquest.HUNT, member, quest, spot, said)


# The module's verb for each move that is one quest row.
_QUEST_VERBS = {
    classquest.TAKE: "take",
    classquest.TURN_IN: "turnin",
    classquest.ABANDON: "abandon",
}


def step_for(member, move, cap, quest=None, hunt=True, item_form=True):
    """The guildcorps.Step that makes the move, or None when there is nothing
    to write: a walk-only hunt the quester already stands at.

    A hunt is the walk to the objective's spawn and then the module's
    `hunt-spawn` row for its creature (classhunt.command), the way a class
    hunt is: a bot left to its own grind strategy at the field never looted a
    quest drop (classhunt.py), and a quest that stalls for that reason would be
    recorded broken for no fault of its own. A quester already beside the spawn
    (classhunt.HUNT_NEAR) writes the hunt row alone. With `hunt` False (a
    worldserver without the verb, bridge._class_hunt_row) the hunt is the walk
    alone, as it was, and nothing within classquest.HUNT_REACH."""
    source = guildjobs.source_for(ACTION, member.name)
    walk = _walk_row(member, move, cap)
    if move.kind == classquest.HUNT:
        row = (
            classhunt.command(quest, move.spot.entry, None, item_form)
            if (hunt and quest is not None)
            else ""
        )
        yards = _yards(member, move.spot)
        if not row and yards <= classquest.HUNT_REACH:
            return None
        rows = (guildcorps.Row("job", row, "", source),) if row else ()
        if row and yards <= classhunt.HUNT_NEAR:
            walk = None
    elif move.kind == classquest.CROSS:
        rows = _move_rows(move, guildjobs.source_for(CROSS_ACTION, member.name))
    else:
        rows = _move_rows(move, source)
    goal = move.spot.name if move.spot is not None else member.name
    return guildcorps.Step(
        member.name,
        ACTION,
        int(move.quest),
        move.said,
        rows=rows,
        walk=walk,
        goal=goal,
        spot=move.spot if move.kind == classquest.HUNT else None,
    )


def _walk_row(member, move, cap):
    """The walk to the move's spawn, None for a move with no spot."""
    if move.spot is None:
        return None
    spot = guildjobs.Spot(
        "creature",
        int(move.spot.guid),
        int(move.spot.map_id),
        float(move.spot.x),
        float(move.spot.y),
    )
    return guildcorps.Row(
        "job",
        spot.command + guildroute.errand_cap_word(cap),
        "",
        guildjobs.source_for(WALK_ACTION, member.name),
    )


def _move_rows(move, source) -> tuple:
    """The rows of a take, a hand-in, a drop or a crossing; () for any other."""
    verb = _QUEST_VERBS.get(move.kind)
    if verb:
        return (
            guildcorps.Row("quest", "%s quest:%d" % (verb, move.quest), "", source),
        )
    if move.kind == classquest.CROSS:
        return (
            guildcorps.Row("job", classquest.cross_command(move.to_map), "", source),
        )
    return ()


def settled(member, tried):
    """The quester with what its rows did inside classquest.TAKE_SETTLE_MINUTES
    put into its log: the saved log trails the live game by up to a save
    (guildjobs.with_recent_takes), so a quest just taken is in the log, one
    just handed in is done and one just dropped is gone."""
    log_now = dict(member.quest_log)
    done = set(member.quests_done)
    for a in sorted(tried or (), key=lambda a: -a.age_minutes):
        if a.name != member.name or a.status not in _WENT:
            continue
        if a.age_minutes >= classquest.TAKE_SETTLE_MINUTES:
            continue
        found = re.match(r"^(take|turnin|abandon) quest:(\d+)", a.command)
        if not found:
            continue
        verb, qid = found.group(1), int(found.group(2))
        if verb == "take" and qid not in done:
            log_now.setdefault(qid, STATUS_INCOMPLETE)
        elif verb == "turnin":
            log_now.pop(qid, None)
            done.add(qid)
        else:
            log_now.pop(qid, None)
    if log_now == member.quest_log and done == set(member.quests_done):
        return member
    return replace(member, quest_log=log_now, quests_done=frozenset(done))


def plan(
    cat: Catalogue,
    member,
    clock,
    now,
    broken=frozenset(),
    tried=(),
    last_quest=0,
    crossings=(),
) -> Plan:
    """One quester's Plan for this pass. Offline, dead or unplaced, it is
    given no move, but the clock still reads its log (and counts no play).

    `crossings` is the realm's recent crossing rows (guildjobs.Recent of
    guildjobs.CROSS_ACTIONS): a crossing is held while the member's last one is
    young (guildjobs.crossing_cooling) or the module refused that map for good
    (guildjobs.class_walls), as the class quest's and the level step's are."""
    member = settled(member, tried)
    found = failures(cat, member, clock, now, tried, last_quest)
    if not member.online:
        return Plan(
            member.name, None, tuple(found), "%s is not in the world" % member.name
        )
    if not member.alive:
        return Plan(member.name, None, tuple(found), "%s is dead" % member.name)
    if not member.placed:
        return Plan(
            member.name, None, tuple(found), "%s has no fresh position" % member.name
        )
    move, why, never_held = next_move(cat, member, broken, found, tried)
    if move is not None and move.kind == classquest.CROSS:
        held = crossing_held(member.name, move, crossings)
        if held:
            move, why = None, held
    return Plan(
        member.name, move, tuple(found) + tuple(never_held), move.said if move else why
    )


def crossing_held(name, move, crossings) -> str:
    """Why the quester's crossing `move` is not asked this pass, "" when it is:
    the module refused that map for good inside classquest.CROSS_WALL_MINUTES
    (guildjobs.class_walls), or the member's last crossing row is still young
    (guildjobs.crossing_cooling)."""
    continent = classquest.CONTINENTS.get(int(move.to_map), "map %d" % move.to_map)
    wall = guildjobs.class_walls(name, crossings).get(int(move.to_map))
    if wall:
        return "%s would cross to %s, and the world refused it: %s" % (
            name,
            continent,
            wall,
        )
    if guildjobs.crossing_cooling(name, crossings):
        return "%s waits on its last crossing before it crosses to %s" % (
            name,
            continent,
        )
    return ""
