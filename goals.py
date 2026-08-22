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
    """Persist the observed value on the goal row; the store IS the memory."""

    goal_id: int
    value: int


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
    # 'co +grind' is the one always-on leveling strategy in mod-playerbots'
    # chat grammar (and already in the voice vocabulary). Skill goals ride
    # the same strategy: gathering and combat skills rise while grinding,
    # and no profession-specific strategy exists to issue instead - the
    # supervisor's job is staying on task and reporting, not crafting
    # rotations (out of scope on infra#2601).
    return "co +grind"


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


def _last_progress(row: Mapping) -> int | None:
    raw = row.get("last_report")
    if raw is None or not str(raw).strip():
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        # A corrupt record must not wedge the goal; treat as first sighting.
        return None


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
    last = _last_progress(row)
    if last is None:
        # First sighting: put the bot on task exactly once. Recording the
        # observation is what prevents a re-issue every cycle after this.
        return [
            StrategyCommand(name, strategy_for(row)),
            RecordProgress(goal_id, observed),
        ]
    if observed == last:
        return []
    actions: list = []
    if observed > last and _milestone_crossed(row["kind"], last, observed):
        text = milestone_text(row, observed)
        actions.append(MilestoneThought(name, text))
        actions.append(Report(text))
    actions.append(RecordProgress(goal_id, observed))
    return actions
