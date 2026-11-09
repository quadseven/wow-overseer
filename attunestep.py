"""The Molten Core attunement, carried out: to Lothos Riftwaker and back.

WHAT WAS THERE. The Raid tab (#269) reads each member's state on Attunement to
the Core - not taken, in the quest log, fragment held, attuned - and prints the
path: go to Lothos Riftwaker, take the quest, run Blackrock Depths for the Core
Fragment, hand it in. The planner (preraid.py, campaignplan.py) already ranks
Blackrock Depths first while a member holds the quest without a fragment. What
nobody did was the two walks to Lothos: taking the quest, and handing it in.
On the dev realm on 2026-09-24, 0 of Cave's 71 were attuned, and the family
was on Kalimdor.

WHAT THIS DECIDES, per family, on the campaign queue's own cycle:

  * Every member attuned: nothing to do.
  * Nobody able to take it (below quest_template.MinLevel, or a race no row
    admits): wait, naming each member and why. A member who cannot yet never
    holds back one who can; the others go, and the line says who is not yet.
  * Nobody needs Lothos (every member not yet attuned holds the quest without
    a fragment): nothing to do here; Blackrock Depths is the planner's.
  * Not every member on the Eastern Kingdoms, where Lothos stands: wait.
    Getting the family across is the campaign's crossing, not this module's.
  * The family's queue still has runs to make (campaignplan.due says nothing
    is due), or the family is on another job or mid-run: wait. An operator's
    order and a planned run always come first.
  * Otherwise the step is the family's: the planner is held so it does not
    queue the next dungeon over the walk; the leader is aimed at Lothos
    (creature 14387, the bare entry mod-overseer resolves to the nearest
    spawn) through the town slot; and each member standing within REACH_YARDS
    of his spawn gets one kind='quest' row, `take quest:<id>` or
    `turnin quest:<id>` (quadseven/mod-overseer#678). A row is not written
    again for ROW_RETRY_SECONDS, whatever it answered.

WHICH QUEST ROW. The core carries two, 7848 and 7487, one per faction. The row
whose quest_template.AllowableRaces admits the member's race is that member's;
nothing here names a faction.

WHERE HE STANDS comes from acore_world.creature, and where the members stand
from overseer_snapshot, readings no older than SNAPSHOT_MAX_AGE_SECONDS. An
unreadable member is never "in reach" and never "on the Eastern Kingdoms".

HOW LONG THE PLANNER WAITS. HOLD_LIMIT_SECONDS at most per stretch, counted by
the bridge. A walk that cannot arrive, or a quest the core keeps refusing, must
not park the family for ever; past the limit the planner is released and the
step says so, and the next stretch starts once the planner's own runs end.

PURE MODULE: rows in, a Step out. The statements it needs are named here.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace

import raidrun
import raidready

LOTHOS = raidrun.LOTHOS
QUESTS = raidready.ATTUNEMENT_QUESTS
EASTERN_KINGDOMS = 0

# mod-overseer's TRAVEL_ARRIVED_YARDS: the radius the travel errand arrives at
# and the one DoQuest looks for the giver in.
REACH_YARDS = 12.0
SNAPSHOT_MAX_AGE_SECONDS = 60
ROW_RETRY_SECONDS = 600
HOLD_LIMIT_SECONDS = 7200

SOURCE = "overseer:attunement"
CLAIMANT = "attunement"
AIM = str(LOTHOS)

# The core's QuestStatus values a log row carries.
STATUS_NONE, STATUS_COMPLETE, STATUS_INCOMPLETE = 0, 1, 3

TAKE, TURN_IN = "take", "turnin"

# The step's verdicts.
DONE = "done"
WAIT = "wait"
BLACKROCK = "blackrock depths"
GO = "go"

# --- the statements -----------------------------------------------------------

SPAWN_SQL = (
    "SELECT map, position_x, position_y, position_z FROM acore_world.creature "
    "WHERE id = %s ORDER BY guid LIMIT 1"
)
QUEST_SQL = (
    "SELECT ID, MinLevel, AllowableRaces FROM acore_world.quest_template "
    "WHERE ID IN ({quests})"
)
MEMBERS_SQL = "SELECT name, level, race FROM characters WHERE name IN ({holes})"
# SNAPSHOT_MAX_AGE_SECONDS, written out (tests/test_attunestep.py holds the
# two equal), so the statement is one constant string.
SNAPSHOT_SQL = (
    "SELECT name, map_id, pos_x, pos_y, pos_z FROM overseer_snapshot "
    "WHERE updated_at > NOW() - INTERVAL 60 SECOND AND name IN ({holes})"
)
REWARDED_SQL = (
    "SELECT c.name, q.quest FROM characters c "
    "JOIN character_queststatus_rewarded q ON q.guid = c.guid "
    "WHERE c.name IN ({holes}) AND q.quest IN ({quests})"
)
LOG_SQL = (
    "SELECT c.name, q.quest, q.status FROM characters c "
    "JOIN character_queststatus q ON q.guid = c.guid "
    "WHERE c.name IN ({holes}) AND q.quest IN ({quests})"
)
RECENT_SQL = (
    "SELECT target_name, command FROM overseer_command "
    "WHERE kind = 'quest' AND source = %s "
    "AND created_at > NOW() - INTERVAL %s SECOND"
)
INSERT_SQL = (
    "INSERT INTO overseer_command (target_name, command, kind, source) "
    "VALUES (%s, %s, 'quest', %s)"
)


def quest_list() -> str:
    return ", ".join(str(int(q)) for q in QUESTS)


def command(verb: str, quest_id: int) -> str:
    return "%s quest:%d" % (verb, int(quest_id))


# --- the facts ----------------------------------------------------------------


@dataclass(frozen=True)
class Member:
    name: str
    level: int = 0
    race: int = 0
    # None when the snapshot has no fresh row for this member.
    map_id: int | None = None
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rewarded: bool = False
    status: int = STATUS_NONE


@dataclass(frozen=True)
class QuestRow:
    quest_id: int
    min_level: int
    races: int  # AllowableRaces; 0 admits every race


@dataclass(frozen=True)
class Facts:
    family: str
    leader: str
    members: tuple
    quests: tuple = ()  # QuestRow per attunement row the world has
    spawn: tuple | None = None  # (map, x, y, z) of Lothos
    job: str = ""
    mid_run: bool = False
    due: bool = False  # campaignplan.due has a reason: the queue ran out
    recent: frozenset = field(default_factory=frozenset)  # (name, command)


def race_admitted(races_mask: int, race: int) -> bool:
    if not races_mask:
        return True
    return bool(int(races_mask) & (1 << (int(race) - 1))) if race else False


def quest_for(members, quests) -> QuestRow | None:
    """The attunement row every member's race may take, or None."""
    for row in sorted(quests or (), key=lambda q: q.quest_id):
        if members and all(race_admitted(row.races, m.race) for m in members):
            return row
    return None


def need(member: Member) -> str:
    """take, turnin, or "" (attuned, or holding it without the fragment)."""
    if member.rewarded:
        return ""
    if member.status == STATUS_NONE:
        return TAKE
    if member.status == STATUS_COMPLETE:
        return TURN_IN
    return ""


def yards(member: Member, spawn) -> float | None:
    """Distance from a member to the spawn, or None when it cannot be said."""
    if spawn is None or member.map_id is None or int(member.map_id) != int(spawn[0]):
        return None
    return math.dist((member.x, member.y, member.z), spawn[1:4])


def in_reach(member: Member, spawn) -> bool:
    d = yards(member, spawn)
    return d is not None and d <= REACH_YARDS


# --- the step -----------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    verdict: str
    line: str
    hold_planner: bool = False
    aim: bool = False  # aim the leader at Lothos through the town slot
    release: bool = False  # the leader stands at Lothos: hand the aim back
    rows: tuple = ()  # (name, command) to write


def _names(members) -> str:
    names = [m.name for m in members]
    if len(names) <= 3:
        return ", ".join(names)
    return "%s and %d more" % (", ".join(names[:3]), len(names) - 3)


def _s(items) -> str:
    """The verb ending for a list of names: "s" for one, "" for more."""
    return "s" if len(items) == 1 else ""


def quest_for_member(member: Member, quests) -> QuestRow | None:
    """The lowest-numbered attunement row this member's own race may take."""
    for row in sorted(quests or (), key=lambda q: q.quest_id):
        if race_admitted(row.races, member.race):
            return row
    return None


def _blocked_reason(member: Member, row: QuestRow | None) -> str:
    """Why this member cannot take or hand in the quest yet, or empty."""
    if row is None:
        return "no row admits the race"
    if need(member) == TAKE and member.level < row.min_level:
        return "below level %d" % row.min_level
    return ""


def _partition(members: tuple, quests):
    """(ready, blocked): (member, row) pairs who can go to Lothos now, and
    (member, reason) pairs who need him but cannot yet. Members who are
    attuned or hold the quest need nothing and are in neither."""
    ready, blocked = [], []
    for m in members:
        if not need(m):
            continue
        row = quest_for_member(m, quests)
        why = _blocked_reason(m, row)
        if why:
            blocked.append((m, why))
        else:
            ready.append((m, row))
    return ready, blocked


def _blocked_note(blocked) -> str:
    """The members who cannot go, grouped by reason."""
    reasons: dict = {}
    for m, why in blocked:
        reasons.setdefault(why, []).append(m)
    return "; ".join("%s %s" % (_names(ms), why) for why, ms in reasons.items())


def _not_now(facts: Facts, members: tuple, needing: list, idle_jobs) -> Step | None:
    """Why the family cannot walk to Lothos this pass, or None."""
    away = [m for m in members if m.map_id is None or int(m.map_id) != EASTERN_KINGDOMS]
    if away:
        unread = [m for m in away if m.map_id is None]
        return Step(
            WAIT,
            "%s need%s Lothos Riftwaker on the Eastern Kingdoms, and %s %s not "
            "there%s; getting across is the campaign's crossing"
            % (
                _names(needing),
                _s(needing),
                _names(away),
                "is" if len(away) == 1 else "are",
                " (%s unread)" % _names(unread) if unread else "",
            ),
        )
    if not facts.due:
        return Step(
            WAIT,
            "%s need%s Lothos Riftwaker, after the family's queued runs"
            % (_names(needing), _s(needing)),
        )
    job = str(facts.job or "").strip().lower()
    if facts.mid_run or job not in idle_jobs:
        return Step(
            WAIT,
            "%s need%s Lothos Riftwaker, once the family is off job %s"
            % (
                _names(needing),
                _s(needing),
                "mid-run" if facts.mid_run else job or "?",
            ),
            hold_planner=True,
        )
    return None


def _go(facts: Facts, members: tuple, ready: list) -> Step:
    """The walk, and the rows for the members standing at Lothos."""
    needing = [m for m, _ in ready]
    wanted = [(m, command(need(m), row.quest_id)) for m, row in ready]
    rows = tuple(
        (m.name, said)
        for m, said in wanted
        if in_reach(m, facts.spawn) and (m.name, said) not in facts.recent
    )
    leader = next((m for m in members if m.name == facts.leader), None)
    at_lothos = leader is not None and in_reach(leader, facts.spawn)
    far = yards(leader, facts.spawn) if leader else None
    if rows:
        line = "at Lothos Riftwaker: %s" % "; ".join("%s %s" % r for r in rows)
    elif at_lothos:
        line = "the family stands at Lothos Riftwaker; %s's rows are written" % (
            _names(needing)
        )
    else:
        line = "%s walks the family to Lothos Riftwaker%s for %s" % (
            facts.leader,
            " (%d yards)" % far if far is not None else "",
            _names(needing),
        )
    return Step(
        GO,
        line,
        hold_planner=True,
        aim=not at_lothos,
        release=at_lothos,
        rows=rows,
    )


def _with_note(result: Step, blocked) -> Step:
    """The step, naming the members who cannot go yet and why."""
    if not blocked:
        return result
    note = _blocked_note(blocked)
    return replace(result, line="%s; not yet: %s" % (result.line, note))


def step(facts: Facts, idle_jobs=("", "quest")) -> Step:
    """What the family does about the attunement this pass (see the module
    docstring for the order the checks are made in)."""
    members = tuple(facts.members)
    if not members:
        return Step(WAIT, "no member of the family could be read")
    if all(m.rewarded for m in members):
        return Step(DONE, "every member is attuned to the Core")
    ready, blocked = _partition(members, facts.quests)
    if not ready and blocked:
        return Step(WAIT, "nobody can take it yet: %s" % _blocked_note(blocked))
    if not ready:
        holding = [m for m in members if not m.rewarded]
        return Step(
            BLACKROCK,
            "%s hold%s Attunement to the Core without a Core Fragment: "
            "Blackrock Depths is next, and the planner ranks it first"
            % (_names(holding), _s(holding)),
        )
    if facts.spawn is None:
        return Step(WAIT, "Lothos Riftwaker has no spawn in the world database")
    needing = [m for m, _ in ready]
    return _with_note(
        _not_now(facts, members, needing, idle_jobs) or _go(facts, members, ready),
        blocked,
    )


# --- reading the rows ---------------------------------------------------------


def _statuses(log_rows) -> dict:
    """name -> the furthest QuestStatus a log row carries for it."""
    status: dict = {}
    for row in log_rows or ():
        name = str(row.get("name"))
        status[name] = max(status.get(name, 0), int(row.get("status") or 0))
    return status


def _member(name, char_row, seen, rewarded, status) -> Member:
    c = char_row or {}
    s = seen or {}
    return Member(
        name=name,
        level=int(c.get("level") or 0),
        race=int(c.get("race") or 0),
        map_id=None if s.get("map_id") is None else int(s["map_id"]),
        x=float(s.get("pos_x") or 0.0),
        y=float(s.get("pos_y") or 0.0),
        z=float(s.get("pos_z") or 0.0),
        rewarded=rewarded,
        status=status,
    )


def _spawn(spawn_rows) -> tuple | None:
    if not spawn_rows:
        return None
    r = spawn_rows[0]
    return (
        int(r.get("map") or 0),
        float(r.get("position_x") or 0.0),
        float(r.get("position_y") or 0.0),
        float(r.get("position_z") or 0.0),
    )


def facts_from_rows(
    family: str,
    leader: str,
    names: list,
    member_rows: list,
    snapshot_rows: list,
    rewarded_rows: list,
    log_rows: list,
    quest_rows: list,
    spawn_rows: list,
    recent_rows: list,
    *,
    job: str = "",
    mid_run: bool = False,
    due: bool = False,
) -> Facts:
    """Facts out of the rows the bridge read with the statements above."""
    chars = {str(r.get("name")): r for r in member_rows or ()}
    seen = {str(r.get("name")): r for r in snapshot_rows or ()}
    rewarded = {str(r.get("name")) for r in rewarded_rows or ()}
    status = _statuses(log_rows)
    members = tuple(
        _member(n, chars.get(n), seen.get(n), n in rewarded, status.get(n, STATUS_NONE))
        for n in names
    )
    quests = tuple(
        QuestRow(
            int(r.get("ID") or 0),
            int(r.get("MinLevel") or 0),
            int(r.get("AllowableRaces") or 0),
        )
        for r in quest_rows or ()
    )
    recent = frozenset(
        (str(r.get("target_name")), str(r.get("command"))) for r in recent_rows or ()
    )
    return Facts(
        family=family,
        leader=leader,
        members=members,
        quests=quests,
        spawn=_spawn(spawn_rows),
        job=job,
        mid_run=mid_run,
        due=due,
        recent=recent,
    )


# --- the switch ---------------------------------------------------------------

ENV_SWITCH = "ATTUNEMENT_STEP"


def enabled(environ=None) -> bool:
    """On unless the operator sets ATTUNEMENT_STEP to off."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")
