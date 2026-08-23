"""Goal supervision for the wow-overseer bridge (infra#2601).

Pure decision module, same seam as core.py: goal-shaped text comes in and a
Goal comes out; a persisted goal row plus one observation comes in and typed
actions come out. Nothing here touches Discord, MySQL, or an LLM - bridge.py
persists the goals, observes the world, and applies the actions. That split
is what lets the supervisor be fully unit-tested against a fake store.

The reconcile contract that keeps a goal from spamming the world: strategy
commands are issued only when the stored state CHANGES (first sighting of
the character), never every cycle. Steady state is read-only. Progress is
recorded in the goal row itself, so a bridge restart resumes supervision
from the store with no in-memory carryover.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

# Profession -> SkillLine id (3.3.5a conventions). acore_world.skillline_dbc
# is EMPTY on this deployment (DBC data ships inside the client files), so
# these ids were verified live against acore_characters.character_skills
# instead: on 2026-08-21 every id below existed there across 100+ characters
# with profession-shaped value/max tiers (75/300 caps), which a wrong id
# (a class skill or a language) would not show.
SKILL_IDS = {
    "first aid": 129,
    "blacksmithing": 164,
    "leatherworking": 165,
    "alchemy": 171,
    "herbalism": 182,
    "cooking": 185,
    "mining": 186,
    "tailoring": 197,
    "engineering": 202,
    "enchanting": 333,
    "fishing": 356,
    "skinning": 393,
}

# 3.3.5a caps. Targets outside these bounds are not goals: the parser stays
# conservative and lets the voice treat the text as ordinary words instead
# of persisting something unreachable.
MAX_LEVEL = 80
MAX_SKILL = 450

# Level goals report every level; skill points come one at a time, so skill
# goals report on crossing each step boundary instead of every point.
SKILL_MILESTONE_STEP = 25

# Cycles without progress before the strategy is issued again. A character
# that logs out and back in loses its strategies - PlayerbotAI::ResetStrategies
# runs on login and rebuilds them from defaults, and the autonomous ones are
# gated behind IsRandomBot(), which is false for named characters. The roster
# loop relogs anyone who drops, so a long goal WILL meet this. Issued once and
# never again, a goal would go quietly inert with its row still reading
# 'active'.
REASSERT_AFTER_CYCLES = 5


@dataclass(frozen=True)
class Goal:
    """A parsed goal, before persistence (no id/character/channel yet)."""

    kind: str  # 'level' | 'skill'
    target: int
    skill_name: str | None = None


@dataclass(frozen=True)
class CancelGoal:
    """The character is being told to stand down from its goals."""


# --- reconcile actions: what the bridge should do this cycle ---------------


@dataclass(frozen=True)
class StrategyCommand:
    """An overseer_command row that puts the bot on task (e.g. co +grind)."""

    target_name: str
    command: str


@dataclass(frozen=True)
class MilestoneThought:
    """An overseer_thought row (source 'goal') marking progress."""

    character_name: str
    text: str


@dataclass(frozen=True)
class Report:
    """Progress or completion text for the Discord channel the goal came from."""

    text: str


@dataclass(frozen=True)
class RecordProgress:
    """Persist the observed value on the goal row; the store IS the memory.

    `stalls` counts consecutive cycles with no progress. It rides in the same
    field because the goal row is the only memory a restart preserves, and a
    counter held in the supervisor would reset every deploy - which is exactly
    when a strategy is most likely to have been lost.
    """

    goal_id: int
    value: int
    stalls: int = 0


@dataclass(frozen=True)
class MarkComplete:
    """Flip the goal to completed; it must never issue commands again."""

    goal_id: int


# Longest names first so 'leatherworking' cannot half-match anything shorter.
# Multi-word names ('first aid') tolerate any run of whitespace between words.
_PROF_ALT = "|".join(
    r"\s+".join(re.escape(word) for word in name.split())
    for name in sorted(SKILL_IDS, key=len, reverse=True)
)
_SKILL_RE = re.compile(
    rf"\b({_PROF_ALT})\b\s+(?:up\s+)?to\s+(\d{{1,3}})\b", re.IGNORECASE
)
_LEVEL_RE = re.compile(
    r"\b(?:reach|hit|make)\s+level\s+(\d{1,3})\b"
    r"|\b(?:get|level)(?:\s+up)?\s+to\s+(?:level\s+)?(\d{1,3})\b",
    re.IGNORECASE,
)
# Bounded gap so 'forget'/'cancel' only binds to a nearby 'goal', not one
# three sentences away in an unrelated order.
_CANCEL_RE = re.compile(
    r"\b(?:forget|cancel|abandon|drop|scrap)\b[^.!?]{0,40}\bgoals?\b",
    re.IGNORECASE,
)


def parse_goal(text: str) -> Goal | CancelGoal | None:
    """Recognize a goal-shaped order inside a natural-language directive.

    Skill shapes are checked before level shapes so 'level your cooking to
    150' reads as a cooking goal, not a level goal. None means 'not a goal':
    the caller falls through to the normal voice path.
    """
    if _CANCEL_RE.search(text):
        return CancelGoal()
    m = _SKILL_RE.search(text)
    if m:
        skill_name = " ".join(m.group(1).lower().split())
        target = int(m.group(2))
        if 1 <= target <= MAX_SKILL:
            return Goal("skill", target, skill_name)
        return None
    m = _LEVEL_RE.search(text)
    if m:
        target = int(m.group(1) or m.group(2))
        if 2 <= target <= MAX_LEVEL:
            return Goal("level", target)
    return None


def strategy_for(goal: Mapping) -> str:
    """The command that puts a character on task.

    NON-combat, and that is the whole point. This read 'co +grind' and could
    never work: mod-playerbots registers grind on the non-combat engine
    (AiFactory::AddDefaultNonCombatStrategies does
    `nonCombatEngine->addStrategy("grind")`), so sending it down the combat
    channel adds nothing to the engine that moves the character. The command
    still delivered, the goal still reported healthy, and the bot stood
    exactly where it spawned.

    Measured on the live server, same character, 90 seconds each:

        Ugga before        -8950,-132
        after 'co +grind'  -8950,-132   not one unit
        after 'nc +grind'  -8990,-103

    Skill goals ride the same strategy: gathering and combat skills rise while
    grinding, and no profession-specific strategy exists to issue instead -
    the supervisor's job is staying on task and reporting, not crafting
    rotations (out of scope on infra#2601).
    """
    return "nc +grind"


# The strategy that gives a character a LIFE rather than a task. `grind` means
# "kill what is in front of you", which is why it worked at level 1 in a
# starting zone and stopped working at level 7: nothing moves these characters
# to level-appropriate content, because RandomPlayerbotMgr's teleporting only
# ever applies to bots in its own pool and named characters are not in it.
#
# Measured live, same spot, 150 seconds, one on each strategy:
#
#     Grog  'new rpg'  -8800 -> -8924   travelled 124 yards
#     Ugga  'grind'    -8800 -> -8797   moved 3
#
# `new rpg` travels, takes quests and visits vendors, and the two coexist:
# Bork had both and was the only character in the family with a quest log.
LIFE_STRATEGY = "nc +new rpg"


def already_working(kind: str, target: int, active: list) -> bool:
    """Is this character already pursuing exactly this goal?

    A function rather than a check at the call site so the rule can be tested
    on its own. The council meets hourly and keeps reaching the same conclusion
    while the work is still in progress; replacing the goal each time wiped
    last_report, restarting the progress record AND the stall counter that
    re-issues a lost strategy. Four cancelled duplicates of one goal sat in the
    table before it was noticed, and the supervisor never once got far enough
    to re-assert.
    """
    return any(
        row.get("kind") == kind and int(row.get("target", -1)) == int(target)
        for row in active
    )


def _describe(kind: str, skill_name: str | None, target: int) -> str:
    if kind == "skill":
        return f"{skill_name} {target}"
    return f"level {target}"


def describe(goal: Goal) -> str:
    return _describe(goal.kind, goal.skill_name, goal.target)


def ack_text(name: str, goal: Goal) -> str:
    return (
        f"{name} accepts the charge: {describe(goal)}. "
        "I will keep watch and report progress here."
    )


def cancel_text(name: str, cancelled: int) -> str:
    if cancelled == 0:
        return f"{name} has no active goal to forget."
    plural = "s" if cancelled > 1 else ""
    return f"{name} stands down: {cancelled} goal{plural} cancelled."


def milestone_text(row: Mapping, observed: int) -> str:
    what = _describe(row["kind"], row.get("skill_name"), int(row["target"]))
    if row["kind"] == "skill":
        return f"{row['character_name']} advances: {row['skill_name']} {observed}, aiming for {what}."
    remaining = int(row["target"]) - observed
    return f"{row['character_name']} advances: level {observed}, {remaining} to go toward {what}."


def completion_text(row: Mapping, observed: int) -> str:
    what = _describe(row["kind"], row.get("skill_name"), int(row["target"]))
    return f"Goal complete: {row['character_name']} reached {what} (now at {observed})."


def _read_report(row: Mapping) -> tuple:
    """(last observed value, consecutive stalled cycles) from the goal row.

    Stored as "<value>" or "<value>/<stalls>". The bare form is what rows
    written before the stall counter existed look like, and it still reads
    correctly - a migration for one integer would be a schema change the
    module owns for no behavioral gain.
    """
    raw = row.get("last_report")
    if raw is None or not str(raw).strip():
        return None, 0
    text = str(raw).strip()
    value, _, stalls = text.partition("/")
    try:
        return int(value), int(stalls) if stalls else 0
    except ValueError:
        # A corrupt record must not wedge the goal; treat as first sighting.
        return None, 0


def _last_progress(row: Mapping) -> int | None:
    return _read_report(row)[0]


def _milestone_crossed(kind: str, last: int, observed: int) -> bool:
    if kind == "skill":
        return observed // SKILL_MILESTONE_STEP > last // SKILL_MILESTONE_STEP
    return observed > last


def reconcile(row: Mapping, observed: int | None) -> list:
    """One supervision cycle for one goal row: state in, actions out.

    `row` is the persisted overseer_goal row (the ONLY memory - restarts
    must change nothing), `observed` the character's current level or skill
    value, or None when it cannot be seen (offline snapshot, unlearned
    skill). The action order matters: MarkComplete comes after the Report
    so a failed Discord send retries the announcement next cycle rather
    than completing silently.
    """
    if row.get("status") != "active":
        return []
    if observed is None:
        # Nothing visible to reconcile against; keep quiet rather than
        # command a character we cannot see. The next cycle retries.
        return []
    name = row["character_name"]
    goal_id = int(row["id"])
    target = int(row["target"])
    if observed >= target:
        text = completion_text(row, observed)
        return [MilestoneThought(name, text), Report(text), MarkComplete(goal_id)]
    last, stalls = _read_report(row)
    if last is None:
        # First sighting: put the bot on task. Recording the observation is
        # what stops this re-issuing every cycle from here on.
        return [
            StrategyCommand(name, strategy_for(row)),
            RecordProgress(goal_id, observed),
        ]
    if observed == last:
        # No progress. Usually just a slow grind, but it is also exactly what a
        # lost strategy looks like, and the two are indistinguishable from
        # here - so re-assert on a cadence rather than trying to tell them
        # apart. The command is idempotent; issuing it to a bot already
        # grinding costs one whisper.
        if stalls + 1 >= REASSERT_AFTER_CYCLES:
            return [
                StrategyCommand(name, strategy_for(row)),
                RecordProgress(goal_id, observed),
            ]
        return [RecordProgress(goal_id, observed, stalls + 1)]
    actions: list = []
    if observed > last and _milestone_crossed(row["kind"], last, observed):
        text = milestone_text(row, observed)
        actions.append(MilestoneThought(name, text))
        actions.append(Report(text))
    actions.append(RecordProgress(goal_id, observed))
    return actions
