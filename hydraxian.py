"""Optional Hydraxian quest progress, earned at live quest givers.

When the family's campaign is due, a member who can take or hand in a quest
walks the family to its real NPC. The game owns every objective, item drop,
reputation check and reward.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import attunestep

QUEST_IDS = (6804, 6805, 6821, 6822, 6823, 6824, 7486)
REACH_YARDS = attunestep.REACH_YARDS
ROW_RETRY_SECONDS = 600
HOLD_LIMIT_SECONDS = attunestep.HOLD_LIMIT_SECONDS

STATUS_NONE = attunestep.STATUS_NONE
STATUS_COMPLETE = attunestep.STATUS_COMPLETE
STATUS_INCOMPLETE = attunestep.STATUS_INCOMPLETE
TAKE, TURN_IN = attunestep.TAKE, attunestep.TURN_IN

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
MEMBERS_SQL = attunestep.MEMBERS_SQL
SNAPSHOT_SQL = attunestep.SNAPSHOT_SQL
REWARDED_SQL = attunestep.REWARDED_SQL
LOG_SQL = attunestep.LOG_SQL
GIVERS_SQL = (
    "SELECT id, map AS map_id, position_x AS x, position_y AS y, "
    "position_z AS z FROM acore_world.creature WHERE id IN ({entries}) "
    "ORDER BY guid"
)
RECENT_SQL = attunestep.RECENT_SQL
INSERT_SQL = attunestep.INSERT_SQL
SOURCE = "overseer:hydraxian"


@dataclass(frozen=True)
class Quest:
    """Realm metadata needed to check and visit one Hydraxian quest."""

    quest_id: int
    min_level: int
    races: int
    prev_quest_id: int
    starter: int
    ender: int


# Both quest passes use the same member shape and the same command, race and
# range rules. Their domain facts stay separate.
Member = attunestep.Member
command = attunestep.command
race_admitted = attunestep.race_admitted


@dataclass(frozen=True)
class Facts:
    """Per-member quest state and live giver positions for one family."""

    members: tuple = ()
    quests: tuple = ()
    rewarded: dict = field(default_factory=dict)
    statuses: dict = field(default_factory=dict)
    givers: dict = field(default_factory=dict)
    recent: frozenset = field(default_factory=frozenset)


@dataclass(frozen=True)
class Step:
    """Natural quest commands and any live-giver travel request."""

    rows: tuple = ()
    hold_planner: bool = False
    aim: int | None = None
    release: int | None = None


def quest_ids() -> str:
    """Return the Hydraxian quest IDs for the bounded world-data query."""
    return ", ".join(str(int(q)) for q in QUEST_IDS)


def _done(rewarded, name: str) -> set:
    if isinstance(rewarded, (set, frozenset, list, tuple)):
        return {int(q) for q in rewarded}
    return {int(q) for q in (rewarded or {}).get(name, ())}


def eligible(quest: Quest, member: Member, rewarded, statuses) -> bool:
    """Whether this member meets the level, race, and predecessor rules."""
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


def _near(member: Member, entry: int, givers) -> bool:
    return any(
        attunestep.in_reach(member, spawn)
        for spawn in (givers or {}).get(int(entry), ())
    )


def giver_entries(quest_rows) -> tuple:
    """The creature entries the bounded quest read names as givers."""
    return tuple(
        sorted(
            {
                int(row.get(key) or 0)
                for row in quest_rows or ()
                for key in ("starter", "ender")
                if int(row.get(key) or 0)
            }
        )
    )


def _members_from_rows(member_rows, snapshot_rows) -> tuple:
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
    return tuple(members)


def _quests_from_rows(quest_rows) -> tuple:
    return tuple(
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


def _states_from_rows(rows, *, with_status: bool = False) -> dict:
    out = {}
    for row in rows or ():
        name = str(row["name"])
        quest_id = int(row["quest"])
        if with_status:
            out.setdefault(name, {})[quest_id] = int(row.get("status") or STATUS_NONE)
        else:
            out.setdefault(name, set()).add(quest_id)
    return out


def _givers_from_rows(rows) -> dict:
    out = {}
    for row in rows or ():
        entry = int(row["id"])
        out.setdefault(entry, []).append(
            (
                int(row["map_id"]),
                float(row["x"]),
                float(row["y"]),
                float(row["z"]),
            )
        )
    return {entry: tuple(spawns) for entry, spawns in out.items()}


def _recent_from_rows(rows) -> frozenset:
    return frozenset(
        (str(row["target_name"]), str(row["command"])) for row in rows or ()
    )


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
    return Facts(
        members=_members_from_rows(member_rows, snapshot_rows),
        quests=_quests_from_rows(quest_rows),
        rewarded=_states_from_rows(rewarded_rows),
        statuses=_states_from_rows(log_rows, with_status=True),
        givers=_givers_from_rows(giver_rows),
        recent=_recent_from_rows(recent_rows),
    )


def _candidate_action(quest: Quest, member: Member, facts: Facts) -> tuple | None:
    """Return this member's eligible natural verb at a live quest giver."""
    rewarded = facts.rewarded or {}
    statuses = facts.statuses or {}
    if quest.quest_id in _done(rewarded, member.name):
        return None
    status = int(statuses.get(member.name, {}).get(quest.quest_id, STATUS_NONE))
    if status == STATUS_COMPLETE and quest.ender and quest.ender in facts.givers:
        return (quest.quest_id, quest.ender, member, TURN_IN)
    if (
        status == STATUS_NONE
        and quest.starter
        and quest.starter in facts.givers
        and eligible(quest, member, rewarded, statuses)
    ):
        return (quest.quest_id, quest.starter, member, TAKE)
    return None


def _wanted_actions(facts: Facts) -> list:
    """Collect each per-member take or turn-in allowed by the live facts."""
    wanted = []
    for quest in sorted(facts.quests, key=lambda row: row.quest_id):
        for member in sorted(facts.members, key=lambda row: row.name):
            action = _candidate_action(quest, member, facts)
            if action is not None:
                wanted.append(action)
    return wanted


def _step_for_giver(facts: Facts, wanted: list, allow_walk: bool) -> Step:
    """Choose the first wanted giver, its local rows, and any walk or release."""
    if not wanted:
        return Step()
    _quest_id, entry, _member, _verb = wanted[0]
    at_target = [row for row in wanted if row[1] == entry]
    rows = tuple(
        (member.name, command(verb, quest_id))
        for quest_id, giver, member, verb in at_target
        if _near(member, giver, facts.givers)
        and (member.name, command(verb, quest_id)) not in facts.recent
    )
    missing = any(
        not _near(member, giver, facts.givers) for _, giver, member, _ in at_target
    )
    if missing and allow_walk:
        return Step(rows=rows, hold_planner=True, aim=entry)
    return Step(rows=rows, release=entry if not missing else None)


def step(facts: Facts, *, allow_walk: bool = False) -> Step:
    """Emit eligible quest verbs, or aim the family at their live giver."""
    return _step_for_giver(facts, _wanted_actions(facts), allow_walk)


ENV_SWITCH = "HYDRAXIAN_STEP"


def enabled(environ=None) -> bool:
    """Run unless HYDRAXIAN_STEP is explicitly switched off."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")
