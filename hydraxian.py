"""Optional, per-member pickup and turn-in for the Hydraxian quest chain.

This step never walks the family or holds a raid campaign. It emits ordinary
quest commands only for a member already within interaction range of the
quest's live starter or ender. Kills, item drops, reputation and rewards stay
with the game.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

QUEST_IDS = (6804, 6805, 6821, 6822, 6823, 6824, 7486)
REACH_YARDS = 12.0
ROW_RETRY_SECONDS = 600

STATUS_NONE, STATUS_COMPLETE = 0, 1
TAKE, TURN_IN = "take", "turnin"

QUEST_SQL = (
    "SELECT q.ID AS quest, q.MinLevel AS min_level, "
    "q.AllowableRaces AS races, COALESCE(a.PrevQuestID, 0) AS prev_quest, "
    "COALESCE((SELECT id FROM acore_world.creature_queststarter s "
    "WHERE s.quest = q.ID LIMIT 1), 0) AS starter, "
    "COALESCE((SELECT id FROM acore_world.creature_questender e "
    "WHERE e.quest = q.ID LIMIT 1), 0) AS ender "
    "FROM acore_world.quest_template q "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = q.ID "
    "WHERE q.ID IN ({quests})"
)
MEMBERS_SQL = "SELECT name, level, race FROM characters WHERE name IN ({holes})"
SNAPSHOT_SQL = (
    "SELECT name, map_id, pos_x, pos_y, pos_z FROM overseer_snapshot "
    "WHERE updated_at > NOW() - INTERVAL 60 SECOND AND name IN ({holes})"
)
REWARDED_SQL = (
    "SELECT c.name, r.quest FROM character_queststatus_rewarded r "
    "JOIN characters c ON c.guid = r.guid WHERE c.name IN ({holes}) "
    "AND r.quest IN ({quests})"
)
LOG_SQL = (
    "SELECT c.name, q.quest, q.status FROM character_queststatus q "
    "JOIN characters c ON c.guid = q.guid WHERE c.name IN ({holes}) "
    "AND q.quest IN ({quests})"
)
GIVERS_SQL = (
    "SELECT id, map AS map_id, position_x AS x, position_y AS y, "
    "position_z AS z FROM acore_world.creature WHERE id IN ({entries}) "
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
SOURCE = "overseer:hydraxian"


@dataclass(frozen=True)
class Quest:
    quest_id: int
    min_level: int
    races: int
    prev_quest_id: int
    starter: int
    ender: int


@dataclass(frozen=True)
class Member:
    name: str
    level: int
    race: int
    map_id: int | None = None
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass(frozen=True)
class Facts:
    members: tuple = ()
    quests: tuple = ()
    rewarded: dict = field(default_factory=dict)
    statuses: dict = field(default_factory=dict)
    givers: dict = field(default_factory=dict)
    recent: frozenset = field(default_factory=frozenset)


@dataclass(frozen=True)
class Step:
    rows: tuple = ()
    hold_planner: bool = False
    aim: int | None = None


def quest_ids() -> str:
    return ", ".join(str(int(q)) for q in QUEST_IDS)


def command(verb: str, quest_id: int) -> str:
    return "%s quest:%d" % (verb, int(quest_id))


def race_admitted(mask: int, race: int) -> bool:
    mask = int(mask or 0)
    race = int(race or 0)
    return not mask or (race > 0 and bool(mask & (1 << (race - 1))))


def _done(rewarded, name: str) -> set:
    if isinstance(rewarded, (set, frozenset, list, tuple)):
        return {int(q) for q in rewarded}
    return {int(q) for q in (rewarded or {}).get(name, ())}


def eligible(quest: Quest, member: Member, rewarded, statuses) -> bool:
    prev = int(quest.prev_quest_id or 0)
    done = _done(rewarded, member.name)
    held = (statuses or {}).get(member.name, {})
    previous_done = not prev or (
        prev in done
        if prev > 0
        else (abs(prev) in done or int(held.get(abs(prev), STATUS_NONE)) != STATUS_NONE)
    )
    return (
        member.level >= int(quest.min_level or 0)
        and race_admitted(quest.races, member.race)
        and previous_done
        and int(quest.quest_id) not in done
    )


def _distance(member: Member, spawn) -> float | None:
    if spawn is None or member.map_id is None or int(member.map_id) != int(spawn[0]):
        return None
    return math.dist((member.x, member.y, member.z), tuple(spawn[1:4]))


def _near(member: Member, entry: int, givers) -> bool:
    distance = _distance(member, (givers or {}).get(int(entry)))
    return distance is not None and distance <= REACH_YARDS


def facts_from_rows(
    member_rows,
    snapshot_rows,
    quest_rows,
    rewarded_rows,
    log_rows,
    giver_rows,
    recent_rows,
) -> Facts:
    """Build the pure step's facts from the bridge's bounded reads."""
    snapshots = {str(row["name"]): row for row in snapshot_rows or ()}
    members = []
    for row in member_rows or ():
        name = str(row["name"])
        snap = snapshots.get(name, {})
        members.append(
            Member(
                name=name,
                level=int(row.get("level") or 0),
                race=int(row.get("race") or 0),
                map_id=(None if snap.get("map_id") is None else int(snap["map_id"])),
                x=float(snap.get("pos_x") or 0.0),
                y=float(snap.get("pos_y") or 0.0),
                z=float(snap.get("pos_z") or 0.0),
            )
        )
    quests = tuple(
        Quest(
            quest_id=int(row["quest"]),
            min_level=int(row.get("min_level") or 0),
            races=int(row.get("races") or 0),
            prev_quest_id=int(row.get("prev_quest") or 0),
            starter=int(row.get("starter") or 0),
            ender=int(row.get("ender") or 0),
        )
        for row in quest_rows or ()
    )
    rewarded = {}
    for row in rewarded_rows or ():
        rewarded.setdefault(str(row["name"]), set()).add(int(row["quest"]))
    statuses = {}
    for row in log_rows or ():
        statuses.setdefault(str(row["name"]), {})[int(row["quest"])] = int(
            row.get("status") or STATUS_NONE
        )
    givers = {
        int(row["id"]): (
            int(row["map_id"]),
            float(row["x"]),
            float(row["y"]),
            float(row["z"]),
        )
        for row in giver_rows or ()
    }
    recent = frozenset(
        (str(row["target_name"]), str(row["command"])) for row in recent_rows or ()
    )
    return Facts(
        members=tuple(members),
        quests=quests,
        rewarded=rewarded,
        statuses=statuses,
        givers=givers,
        recent=recent,
    )


def step(facts: Facts) -> Step:
    """Emit only eligible take/turn-in verbs at a live, nearby quest giver."""
    rewarded = facts.rewarded or {}
    statuses = facts.statuses or {}
    actions = []
    for quest in sorted(facts.quests, key=lambda row: row.quest_id):
        for member in sorted(facts.members, key=lambda row: row.name):
            if quest.quest_id in _done(rewarded, member.name):
                continue
            status = int(statuses.get(member.name, {}).get(quest.quest_id, STATUS_NONE))
            if (
                status == STATUS_COMPLETE
                and quest.ender
                and _near(member, quest.ender, facts.givers)
            ):
                said = command(TURN_IN, quest.quest_id)
            elif (
                status == STATUS_NONE
                and quest.starter
                and eligible(quest, member, rewarded, statuses)
                and _near(member, quest.starter, facts.givers)
            ):
                said = command(TAKE, quest.quest_id)
            else:
                continue
            if (member.name, said) not in facts.recent:
                actions.append((member.name, said))
    if not actions:
        return Step()
    return Step(rows=tuple(actions))
