"""Dungeon quest pickup and turn-in for a queued campaign, and the guild's
Dark Iron Legacy chain to the Shadowforge Key (the end of this file).

This module only decides. The bridge reads the world and character tables and
mod-overseer performs the two quest verbs at the selected creature.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

REACH_YARDS = 12.0
# A giver further than this from the leader (or on another map, or with the
# leader unseen) is not worth holding a queued run for. Zug's family was held
# out of Ragefire Chasm for a turn-in at a giver 2600 yards off (wow-dev,
# 2026-09-29): the walk is an incidental errand, and the quest is taken when
# the family is next by the giver.
WALK_LIMIT_YARDS = 600.0
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


def _ready_actions(actions, giver, spawn):
    return tuple(
        (member.name, said)
        for entry, member, said in actions
        if int(entry) == int(giver)
        and _distance(member, spawn) is not None
        and _distance(member, spawn) <= REACH_YARDS
    )


def _leader_at_giver(facts: Facts, spawn) -> bool:
    leader = next((m for m in facts.members if m.name == facts.leader), None)
    leader = leader or (facts.members[0] if facts.members else None)
    return (
        leader is not None
        and _distance(leader, spawn) is not None
        and _distance(leader, spawn) <= REACH_YARDS
    )


def _too_far(facts: Facts, giver: int, spawn) -> Step | None:
    """A wait when the leader is too far from the giver to walk for a run's sake."""
    leader = next((m for m in facts.members if m.name == facts.leader), None)
    leader = leader or (facts.members[0] if facts.members else None)
    gap = None if leader is None else _distance(leader, spawn)
    if gap is not None and gap <= WALK_LIMIT_YARDS:
        return None
    where = (
        "on another map or out of sight" if gap is None else "%d yards off" % int(gap)
    )
    return Step(
        WAIT,
        "dungeon quest giver %d is %s: a queued run does not wait for that walk"
        % (giver, where),
        giver=giver,
        release=True,
    )


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
    ready = _ready_actions(actions, giver, spawn)
    at_giver = _leader_at_giver(facts, spawn)
    if not ready and not at_giver:
        far = _too_far(facts, giver, spawn)
        if far is not None:
            return far
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
    names = tuple(str(row.get("name")) for row in members or ())
    chars = {str(row.get("name")): row for row in members or ()}
    seen = {str(row.get("name")): row for row in snapshot_rows or ()}
    rewarded = _rewarded(names, rewarded_rows)
    statuses = _statuses(names, log_rows)
    quests = _quest_rows(quest_rows)
    parsed = _members(names, chars, seen)
    givers = _givers(giver_rows)
    recent = _recent(recent_rows)
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


def _rewarded(names, rows):
    out = {name: set() for name in names}
    for row in rows or ():
        out.setdefault(str(row.get("name")), set()).add(int(row["quest"]))
    return out


def _statuses(names, rows):
    out = {name: {} for name in names}
    for row in rows or ():
        out.setdefault(str(row.get("name")), {})[int(row["quest"])] = int(
            row.get("status") or 0
        )
    return out


def _quest_rows(rows):
    return tuple(
        Quest(
            int(row["quest"]),
            int(row["zone"]),
            int(row.get("min_level") or 0),
            int(row.get("races") or 0),
            int(row.get("prev_quest") or 0),
            int(row.get("starter") or 0),
            int(row.get("ender") or 0),
        )
        for row in rows or ()
    )


def _members(names, chars, seen):
    return tuple(
        Member(
            name,
            int(chars.get(name, {}).get("level") or 0),
            int(chars.get(name, {}).get("race") or 0),
            None if not seen.get(name) else int(seen[name].get("map_id")),
            float(seen.get(name, {}).get("pos_x") or 0),
            float(seen.get(name, {}).get("pos_y") or 0),
            float(seen.get(name, {}).get("pos_z") or 0),
        )
        for name in names
    )


def _givers(rows):
    return {
        int(row["id"]): (
            int(row.get("map_id") or 0),
            float(row.get("pos_x") or 0),
            float(row.get("pos_y") or 0),
            float(row.get("pos_z") or 0),
        )
        for row in rows or ()
    }


def _recent(rows):
    return frozenset(
        (str(row.get("target_name")), str(row.get("command"))) for row in rows or ()
    )


# DARK IRON LEGACY (#811). Blackrock Depths' keyed doors open only for a member
# carrying the Shadowforge Key (campaignplan.DOOR_KEYS), and its one source is
# this chain. Franclorn Forgewright gives 3801 and takes it back, and gives
# 3802; he is seen only by a ghost (creature_template.flags_extra 1026), so a
# member takes the chain on a corpse run past him, as players did. 3802 asks
# for Ironfel, Fineous Darkvire's drop inside the dungeon, laid at the Shrine
# of Thaurissan, a gameobject; its reward is the key. Nothing here grants
# anything: these are mod-overseer's own take and turnin rows, which it refuses
# for a quest the core would not give or reward.
FRANCLORN = 8888
SHRINE_OF_THAURISSAN = 164689
LEGACY_TALE, LEGACY = 3801, 3802
LEGACY_MIN_LEVEL = 48
LEGACY_RUN = "blackrock-depths"
LEGACY_SOURCE = "overseer:dark-iron-legacy"
# mod-overseer takes and hands in within SPAWN_WALK_ARRIVE_YARDS of the giver;
# a row written from further off is refused as out of reach.
LEGACY_REACH_YARDS = 20.0
LEGACY_RETRY_SECONDS = 600

LEGACY_MEMBERS_SQL = (
    "SELECT s.name, s.level, s.health, s.max_health, s.map_id, s.pos_x, s.pos_y, "
    "s.pos_z FROM overseer_snapshot s JOIN guild g ON g.guildid = s.guild_id "
    "WHERE s.updated_at > NOW() - INTERVAL 60 SECOND AND s.is_bot = 1 "
    "AND g.name IN ({holes})"
)
LEGACY_LOG_SQL = (
    "SELECT c.name, q.quest, q.status FROM character_queststatus q "
    "JOIN characters c ON c.guid = q.guid WHERE q.quest IN (%d, %d) "
    "AND c.name IN ({holes})" % (LEGACY_TALE, LEGACY)
)
LEGACY_REWARDED_SQL = (
    "SELECT c.name, r.quest FROM character_queststatus_rewarded r "
    "JOIN characters c ON c.guid = r.guid WHERE r.quest IN (%d, %d) "
    "AND c.name IN ({holes})" % (LEGACY_TALE, LEGACY)
)
LEGACY_SPAWNS_SQL = (
    "SELECT 'creature' AS kind, map AS map_id, position_x AS pos_x, "
    "position_y AS pos_y, position_z AS pos_z FROM acore_world.creature "
    "WHERE id = %d UNION ALL SELECT 'object' AS kind, map AS map_id, "
    "position_x AS pos_x, position_y AS pos_y, position_z AS pos_z "
    "FROM acore_world.gameobject WHERE id = %d" % (FRANCLORN, SHRINE_OF_THAURISSAN)
)
LEGACY_RUNS_SQL = (
    "SELECT keyword, members FROM overseer_guild_run "
    "WHERE state IN ('queued', 'inside')"
)


@dataclass(frozen=True)
class Seeker:
    """A guild member in the world, as the chain reads it."""

    member: Member
    ghost: bool
    log: dict
    rewarded: frozenset


@dataclass(frozen=True)
class LegacyFacts:
    seekers: tuple = ()
    franclorn: tuple | None = None
    shrine: tuple | None = None
    runners: frozenset = frozenset()
    recent: frozenset = frozenset()


def is_ghost(health, max_health) -> bool:
    """A released spirit: the core sets its health to 1 (apiv2/presence.py).
    A corpse not yet released has none and cannot talk to anybody."""
    return int(health or 0) == 1 and int(max_health or 0) > 1


def _in_reach(member: Member, spawn) -> bool:
    gap = _distance(member, spawn)
    return gap is not None and gap <= LEGACY_REACH_YARDS


def _franclorn_steps(seeker: Seeker) -> tuple:
    """The rest of the chain a ghost at Franclorn can do in one visit, in the
    order it must happen. 3801 has no objectives, so it is complete as soon
    as it is taken, and 3802 waits on 3801's reward (its PrevQuestID)."""
    done, log = seeker.rewarded, seeker.log
    if LEGACY in done or LEGACY in log:
        return ()
    steps = []
    if LEGACY_TALE not in done and LEGACY_TALE not in log:
        steps.append(command(TAKE, LEGACY_TALE))
    if LEGACY_TALE not in done:
        steps.append(command(TURN_IN, LEGACY_TALE))
    steps.append(command(TAKE, LEGACY))
    return tuple(steps)


def _shrine_steps(seeker: Seeker, facts: LegacyFacts) -> tuple:
    """3802 handed in at the Shrine by a member of a Blackrock Depths guild
    run who carries Ironfel (the quest's one requirement, so its status is
    complete) and stands at the Shrine."""
    if seeker.member.name not in facts.runners:
        return ()
    if seeker.log.get(LEGACY) != STATUS_COMPLETE:
        return ()
    if not _in_reach(seeker.member, facts.shrine):
        return ()
    return (command(TURN_IN, LEGACY),)


def _steps(seeker: Seeker, facts: LegacyFacts) -> tuple:
    if seeker.ghost:
        if seeker.member.level < LEGACY_MIN_LEVEL:
            return ()
        if not _in_reach(seeker.member, facts.franclorn):
            return ()
        return _franclorn_steps(seeker)
    return _shrine_steps(seeker, facts)


def legacy_rows(facts: LegacyFacts) -> tuple:
    """(name, command) rows for the Dark Iron Legacy chain, in write order.
    A row already written within the retry window is not written again."""
    rows = []
    for seeker in facts.seekers:
        for said in _steps(seeker, facts):
            if (seeker.member.name, said) not in facts.recent:
                rows.append((seeker.member.name, said))
    return tuple(rows)


def key_holders(facts: LegacyFacts, handed) -> tuple:
    """Members this bridge sent to the Shrine whose 3802 is now rewarded: the
    core gives the Shadowforge Key with that reward and records it after."""
    return tuple(
        seeker.member.name
        for seeker in facts.seekers
        if seeker.member.name in handed and LEGACY in seeker.rewarded
    )


def _run_names(rows) -> frozenset:
    """Members of the in-flight Blackrock Depths guild runs. members is
    overseer_guild_run's `name:seat:class:level` list (guildrun._member_list)."""
    return frozenset(
        part.split(":")[0]
        for row in rows or ()
        if str(row.get("keyword")) == LEGACY_RUN
        for part in str(row.get("members") or "").split(",")
        if part.split(":")[0]
    )


def _spawn(rows, kind: str):
    row = next((r for r in rows or () if str(r.get("kind")) == kind), None)
    if row is None:
        return None
    return (
        int(row.get("map_id") or 0),
        float(row.get("pos_x") or 0),
        float(row.get("pos_y") or 0),
        float(row.get("pos_z") or 0),
    )


def legacy_facts_from_rows(
    snapshot_rows, log_rows, rewarded_rows, spawn_rows, run_rows, recent_rows
) -> LegacyFacts:
    names = tuple(str(row.get("name")) for row in snapshot_rows or ())
    seen = {str(row.get("name")): row for row in snapshot_rows or ()}
    chars = {name: {"level": seen[name].get("level")} for name in names}
    members = _members(names, chars, seen)
    statuses = _statuses(names, log_rows)
    rewarded = _rewarded(names, rewarded_rows)
    seekers = tuple(
        Seeker(
            member,
            is_ghost(
                seen[member.name].get("health"), seen[member.name].get("max_health")
            ),
            statuses.get(member.name, {}),
            frozenset(rewarded.get(member.name, ())),
        )
        for member in members
    )
    return LegacyFacts(
        seekers=seekers,
        franclorn=_spawn(spawn_rows, "creature"),
        shrine=_spawn(spawn_rows, "object"),
        runners=_run_names(run_rows),
        recent=_recent(recent_rows),
    )
