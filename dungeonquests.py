"""Dungeon quest pickup and turn-in for a queued campaign.

This module only decides. The bridge reads the world and character tables and
mod-overseer performs the two quest verbs at the selected creature.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

REACH_YARDS = 12.0
STATUS_NONE, STATUS_COMPLETE, STATUS_INCOMPLETE = 0, 1, 3
TAKE, TURN_IN = "take", "turnin"
WAIT, GO, DONE = "wait", "go", "done"

QUEST_SQL = (
    "SELECT q.ID AS quest, q.QuestSortID AS zone, q.MinLevel AS min_level, "
    "q.AllowableRaces AS races, a.PrevQuestID AS prev_quest, "
    "COALESCE((SELECT id FROM acore_world.creature_queststarter s "
    "WHERE s.quest = q.ID LIMIT 1), 0) AS starter, "
    "COALESCE((SELECT id FROM acore_world.creature_questender e "
    "WHERE e.quest = q.ID LIMIT 1), 0) AS ender "
    "FROM acore_world.quest_template q "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = q.ID "
    "WHERE q.QuestSortID IN ({zones}) AND q.LogTitle NOT LIKE '<%%' "
    "AND EXISTS (SELECT 1 FROM acore_world.creature_queststarter s "
    "WHERE s.quest = q.ID) AND EXISTS (SELECT 1 FROM acore_world.creature_questender e "
    "WHERE e.quest = q.ID)"
)
MEMBERS_SQL = "SELECT name, level, race FROM characters WHERE name IN ({holes})"
SNAPSHOT_SQL = (
    "SELECT name, map_id, pos_x, pos_y, pos_z FROM overseer_snapshot "
    "WHERE updated_at > NOW() - INTERVAL 60 SECOND AND name IN ({holes})"
)
REWARDED_SQL = (
    "SELECT c.name, r.quest FROM character_queststatus_rewarded r "
    "JOIN characters c ON c.guid = r.guid WHERE c.name IN ({holes})"
)
LOG_SQL = (
    "SELECT c.name, q.quest, q.status FROM character_queststatus q "
    "JOIN characters c ON c.guid = q.guid WHERE c.name IN ({holes})"
)
GIVERS_SQL = (
    "SELECT id, map AS map_id, position_x AS pos_x, position_y AS pos_y, "
    "position_z AS pos_z FROM acore_world.creature WHERE id IN ({entries}) "
    "ORDER BY guid"
)
RECENT_SQL = (
    "SELECT target_name, command FROM overseer_command WHERE kind = 'quest' "
    "AND source = %s AND created_at > NOW() - INTERVAL %s SECOND"
)
INSERT_SQL = (
    "INSERT INTO overseer_command (target_name, command, kind, source) "
    "VALUES (%s, %s, 'quest', %s)"
)


@dataclass(frozen=True)
class Quest:
    quest_id: int
    zone: int
    min_level: int
    races: int
    prev_quest_id: int
    starter: int
    ender: int


@dataclass(frozen=True)
class Member:
    name: str
    level: int = 0
    race: int = 0
    map_id: int | None = None
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass(frozen=True)
class Facts:
    dungeon: str
    leader: str = ""
    quests: tuple = ()
    members: tuple = ()
    rewarded: dict | frozenset = None
    statuses: dict = None
    spawn: tuple | None = None
    givers: dict = None
    recent: frozenset = frozenset()
    due: bool = False
    mid_run: bool = False

    def with_status(self, name: str, quest_id: int, status: int) -> "Facts":
        statuses = {n: dict(rows) for n, rows in (self.statuses or {}).items()}
        statuses.setdefault(name, {})[int(quest_id)] = int(status)
        return replace(self, statuses=statuses)


@dataclass(frozen=True)
class Step:
    verdict: str
    line: str
    hold_planner: bool = False
    aim: int | None = None
    giver: int | None = None
    release: bool = False
    rows: tuple = ()


def race_admitted(mask: int, race: int) -> bool:
    return not int(mask or 0) or bool(int(mask) & (1 << (int(race) - 1)))


def _done(rewarded, name: str) -> set:
    if isinstance(rewarded, (set, frozenset, list, tuple)):
        return {int(x) for x in rewarded}
    return {int(x) for x in (rewarded or {}).get(name, ())}


def eligible(quest: Quest, member: Member, rewarded) -> bool:
    previous = int(quest.prev_quest_id or 0)
    done = _done(rewarded, member.name)
    return (
        member.level >= int(quest.min_level or 0)
        and race_admitted(quest.races, member.race)
        and (not previous or abs(previous) in done)
        and int(quest.quest_id) not in done
    )


def open_quests(rows: list, rewarded, members) -> dict:
    """Return dungeon zone -> eligible quest count.

    A quest is open when at least one family member passes level, faction,
    prerequisite, and already-rewarded checks.
    """
    out = {}
    for row in rows or ():
        quest = Quest(
            int(row["quest"]),
            int(row["zone"]),
            int(row.get("min_level") or 0),
            int(row.get("races") or 0),
            int(row.get("prev_quest") or 0),
            int(row.get("starter") or 0),
            int(row.get("ender") or 0),
        )
        if any(eligible(quest, member, rewarded) for member in members):
            out[quest.zone] = out.get(quest.zone, 0) + 1
    return out


def command(verb: str, quest_id: int) -> str:
    return "%s quest:%d" % (verb, int(quest_id))


def _distance(member: Member, spawn) -> float | None:
    if spawn is None or member.map_id is None or int(member.map_id) != int(spawn[0]):
        return None
    return math.dist((member.x, member.y, member.z), tuple(spawn[1:4]))


def _giver(facts: Facts, entry: int):
    return (facts.givers or {}).get(int(entry), facts.spawn)


def _actions(facts: Facts):
    rewarded = facts.rewarded or {}
    statuses = facts.statuses or {}
    actions = []
    for quest in sorted(facts.quests, key=lambda q: q.quest_id):
        for member in facts.members:
            if int(quest.quest_id) in _done(rewarded, member.name):
                continue
            status = int(statuses.get(member.name, {}).get(quest.quest_id, STATUS_NONE))
            if status == STATUS_COMPLETE:
                said = command(TURN_IN, quest.quest_id)
                if (member.name, said) not in facts.recent:
                    actions.append((quest.ender, member, said))
            elif status == STATUS_NONE and eligible(quest, member, rewarded):
                said = command(TAKE, quest.quest_id)
                if (member.name, said) not in facts.recent:
                    actions.append((quest.starter, member, said))
    return actions


def step(facts: Facts) -> Step:
    actions = _actions(facts)
    if not actions:
        return Step(DONE, "no eligible dungeon quest needs action")
    if not facts.due:
        return Step(WAIT, "the dungeon campaign is not between attempts")
    if facts.mid_run:
        return Step(WAIT, "the family is inside the dungeon", hold_planner=True)
    giver = next((entry for entry, _member, _command in actions if entry), 0)
    if not giver:
        return Step(WAIT, "an eligible dungeon quest has no giver")
    spawn = _giver(facts, giver)
    ready = [
        (member.name, said)
        for entry, member, said in actions
        if int(entry) == int(giver)
        and _distance(member, spawn) is not None
        and _distance(member, spawn) <= REACH_YARDS
    ]
    leader = next((m for m in facts.members if m.name == facts.leader), None)
    leader = leader or (facts.members[0] if facts.members else None)
    at_giver = (
        leader is not None
        and _distance(leader, spawn) is not None
        and _distance(leader, spawn) <= REACH_YARDS
    )
    verb = "take" if any("take " in command for _, command in ready) else "turn in"
    line = (
        "at giver %d: %s" % (giver, "; ".join("%s %s" % x for x in ready))
        if ready
        else "walk the family to dungeon quest giver %d to %s" % (giver, verb)
    )
    return Step(
        GO,
        line,
        hold_planner=True,
        aim=None if at_giver else giver,
        giver=giver,
        release=at_giver,
        rows=tuple(ready),
    )


def facts_from_rows(
    dungeon,
    leader,
    members,
    quest_rows,
    rewarded_rows,
    log_rows,
    snapshot_rows,
    giver_rows,
    recent_rows,
    *,
    due=False,
    mid_run=False,
):
    chars = {str(row.get("name")): row for row in members or ()}
    seen = {str(row.get("name")): row for row in snapshot_rows or ()}
    names = tuple(str(row.get("name")) for row in members or ())
    rewarded = {name: set() for name in names}
    for row in rewarded_rows or ():
        rewarded.setdefault(str(row.get("name")), set()).add(int(row["quest"]))
    statuses = {name: {} for name in names}
    for row in log_rows or ():
        statuses.setdefault(str(row.get("name")), {})[int(row["quest"])] = int(
            row.get("status") or 0
        )
    quests = tuple(
        Quest(
            int(row["quest"]),
            int(row["zone"]),
            int(row.get("min_level") or 0),
            int(row.get("races") or 0),
            int(row.get("prev_quest") or 0),
            int(row.get("starter") or 0),
            int(row.get("ender") or 0),
        )
        for row in quest_rows or ()
    )
    parsed = []
    for name in names:
        c, s = chars.get(name, {}), seen.get(name, {})
        parsed.append(
            Member(
                name,
                int(c.get("level") or 0),
                int(c.get("race") or 0),
                None if not s else int(s.get("map_id")),
                float(s.get("pos_x") or 0),
                float(s.get("pos_y") or 0),
                float(s.get("pos_z") or 0),
            )
        )
    givers = {
        int(row["id"]): (
            int(row.get("map_id") or 0),
            float(row.get("pos_x") or 0),
            float(row.get("pos_y") or 0),
            float(row.get("pos_z") or 0),
        )
        for row in giver_rows or ()
    }
    recent = {
        (str(row.get("target_name")), str(row.get("command")))
        for row in recent_rows or ()
    }
    return Facts(
        dungeon=dungeon,
        leader=leader,
        quests=quests,
        members=tuple(parsed),
        rewarded=rewarded,
        statuses=statuses,
        givers=givers,
        recent=frozenset(recent),
        due=due,
        mid_run=mid_run,
    )
