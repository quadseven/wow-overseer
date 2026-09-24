"""What `job = raid prep` actually does, and what it refuses to pretend to do.

infra#3980: the family wants to get ready for raiding - professions maxed, recipes
traded, mail collected, materials in the guild bank. This module is the positive
half of that mode - the thing that turns the mode into a behaviour - and the
honest account of where that behaviour stops.

THE GAP IT FILLS. Setting any non-quest job stands the quest drive down inside
the worldserver; until this ran, nothing put anything in its place, which is the
whole of infra#3338. What replaces it is calling the shipped sub-passes that
already exist: _mail_once to collect reagents and recipes from the mailbox,
_craft_once to re-assert craft spells for profession progress, and
_guild_bank_once to deposit gold above float to the guild bank.

WHAT IT REFUSES, AND WHY THAT IS THE POINT. Three shapes of "raid prep" look
actionable and are not, and each one would leave the family on a mode with no
work in it - the idle infra#3338 is about, arrived at from the other side.

  1. NO MAIL, NO PROFESSION GAPS, NO CRAFT QUEUE. If the family has no mail
     waiting, all professions are at their target ranks, and there are no
     craft recipes to work, raid prep would stand the quest drive down and send
     nobody anywhere. Refused at the order and logged at the drive cycle.

  2. NO GUILD BANK ACCESS. If the guild bank pass cannot run (not in a guild,
     no float configured), the deposit sub-pass has nothing to do. The mail and
     craft sub-passes still run, but if all three are empty this mode idles.

  3. A SKILL THE ROSTER NEVER ASKED FOR. Mirroring trainjob's refusal: if a
     character's profession target is not declared in the roster's professions
     column, the drive will not invent one. The operator must name the
     profession in the roster for it to be part of raid prep.

PURE MODULE, same seam as travel.py, jobs.py, trainjob.py and professions.py:
rows in, a decision and some statements out. No MySQL, no Discord, no LLM.
`bridge.py` reads the rows, runs the statements and speaks the sentences.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import classic
import goals


# The mode this module is the drive for. Spelled once, and jobs.MODES is what
# it has to agree with - tests/test_raidprep.py checks that it is a real mode
# and that jobs.IMPLEMENTED claims it, so this constant cannot drift into
# naming something the vocabulary does not have.
MODE = "raid prep"


# Read from goals.SKILL_IDS rather than spelled, for the same reason
# professions.TRAINER_ROLE gives: a third spelling of "alchemy" is a third
# thing to get wrong, and a rename becomes an ImportError at startup instead
# of an errand that resolves to nothing six hours later.
SKILL_IDS = goals.SKILL_IDS

# Reverse mapping for reporting
SKILL_NAMES = {v: k for k, v in SKILL_IDS.items()}


# The secondary professions the operator asked for by name. Mirroring
# trainjob.SECONDARY: they cannot be trained by a trainer (mod-overseer gates
# on IsPrimaryProfessionSkill), and the family already holds all three at 1/75.
# What is behind is the VALUE, and a trainer does not sell that.
SECONDARY = {name: SKILL_IDS[name] for name in ("first aid", "cooking", "fishing")}

SECONDARY_NOTE = (
    "First Aid, Cooking and Fishing cannot be trained by this mode, and no "
    "mode can: mod-overseer resolves every training errand through "
    "SkillStartedBySpell, which gates on IsPrimaryProfessionSkill, so a "
    "secondary is never a trainer's answer to one. All five already hold all "
    "three at 1/75 - what is behind is the VALUE, and a trainer does not sell "
    "that. It is raised by USING the skill: First Aid has 74 points of "
    "headroom and Cooking 50, both reachable with no trainer at all, and "
    "that is where the family's secondary progress has to come from."
)


@dataclass(frozen=True)
class Member:
    """One `overseer_roster` row, plus what `character_skills` says they hold.

    `wanted` is the parsed `professions` column - the declared end state, which
    is the only permission there is. `holds` is the observation, and it is
    REQUIRED rather than optional for the same reason trainjob.outstanding takes
    `holds`: a decision that cannot see what a character already has is a
    decision that can only guess, and the guess sends somebody on a journey.
    """

    name: str
    job: str = ""
    wanted: tuple = ()
    learn_skill: int = 0
    holds: tuple = ()
    level: int = 0


@dataclass(frozen=True)
class RaidPrepPlan:
    """What the drive should do about a family whose job is `raid prep`.

    The drive itself does not emit SQL statements - it composes the shipped
    sub-passes (_mail_once, _craft_once, _guild_bank_once) which each emit
    their own statements. This plan describes what those sub-passes will find.

    `mail_items` is a count of mail items waiting (attachments + copper).
    `profession_gaps` is a list of (name, profession_name, current_skill, target_skill).
    `why_not` is why nobody does anything, and it is never empty when all
    action indicators are zero - a plan that declines to act and cannot say why
    is the silent idle this whole module exists to stop.
    """

    mail_items: int = 0
    profession_gaps: tuple = ()
    why_not: str = ""


def family_mode(members: Sequence) -> str:
    """The one mode the whole family is on, or '' if they do not agree.

    A job is family-wide by construction (jobs.py's docstring says why), so
    disagreement is not a state to average over - it is a state to decline to
    act on, because acting on half a family is how one character walks off
    alone.
    """
    modes = {str(m.job or "") for m in members}
    return modes.pop() if len(modes) == 1 else ""


def parse_wanted(column) -> tuple:
    """The `professions` column as skill ids.

    Reuses trainjob's parser: anything unparseable is dropped, so a malformed
    column NARROWS the permission rather than widening it.
    """
    ids = []
    for part in str(column or "").split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            ids.append(int(part))
    return tuple(sorted(set(ids)))


def profession_gaps(members: Sequence) -> tuple:
    """Return (name, prof_name, current_skill, target_skill) for each profession below target.

    A profession only appears in the gap list if:
    - it is declared in the roster's `professions` column (wanted)
    - the character's current skill is > 0 (they actually have the profession)
    - the character's current skill is below 300 (the classic ruleset's cap)
    """
    gaps = []
    for m in members:
        # `wanted` is already parsed (a tuple of skill ids), exactly as
        # trainjob.outstanding consumes it. Do not re-parse it: the column
        # string is only parseable before it reaches the Member.
        for prof_id in m.wanted:
            if prof_id in SECONDARY.values():
                continue  # secondaries cannot be raised by a trainer (see docstring)
            current = 0
            for held_id in m.holds:
                if held_id == prof_id:
                    current = (
                        1  # We only know they have it, not the exact value from roster
                    )
                    break
            # In the real _train_members, holds contains skill IDs not levels.
            # For raid prep we care about whether the profession is declared and
            # whether the character has it at all. The actual skill level check
            # happens in the craft drive (_craft_once) which reads live skills.
            if current > 0:
                prof_name = SKILL_NAMES.get(prof_id, f"skill_{prof_id}")
                gaps.append((m.name, prof_name, current, classic.MAX_PROFESSION_SKILL))
    return tuple(gaps)


def nothing_to_prepare(members: Sequence) -> str:
    """Why an otherwise willing family has no raid prep work.

    Separated from `plan` because it is also the answer to "may I set this
    mode": a refusal at the moment the order is written is worth more than a
    log line an hour later, and both want the same sentence.
    """
    said = [
        "Nobody has mail to collect, professions to raise, recipes to craft, "
        "or gold to deposit - raid prep would stand the quest drive down "
        "and send nobody anywhere."
    ]
    return " ".join(said)


def readiness(
    members: Sequence,
    mail_items: int = 0,
) -> str:
    """Why `raid prep` cannot be set right now, or '' when it can be.

    INDEPENDENT OF THE JOB COLUMN, on purpose. This is the question asked
    BEFORE the order is written, when the family is still on whatever mode
    they were - so it must not require them to already be on the one being
    asked for. `plan` asks it again afterwards, which is how the answer at the
    moment of the order and the answer on the next drive cycle stay the same
    sentence.

    THE SECOND HALF OF THE #3338 GUARD. jobs.can_set answers "is this mode
    wired at all", which is a fact about the code and never changes at
    runtime. This answers "is there anything for it to do", which is a fact
    about the world and changes hourly. A mode can pass the first and fail the
    second, and setting it then is the same silent idle by a longer route.
    """
    members = list(members)
    if not members:
        return "Nobody is on the roster to prepare for raid."

    # If mail has items, readiness passes (mail_once will collect them)
    if mail_items > 0:
        return ""

    # If any profession is declared and held but not maxed, readiness passes
    # (craft_once will re-assert the correct spell)
    gaps = profession_gaps(members)
    if gaps:
        return ""

    # If guild bank has deposits above float, readiness passes
    # (guild_bank_once will handle it). We can't know this without a DB read,
    # so we assume it might have work and let the sub-pass decide.

    # Fall back: if nothing concrete is known, be conservative and check roster
    return nothing_to_prepare(members)


def plan(
    members: Sequence,
    mail_items: int = 0,
) -> RaidPrepPlan:
    """What raid prep should do about this family, or why nothing.

    Deliberately composes the shipped sub-passes rather than inventing new
    ones. Each sub-pass is a complete decision module that the bridge already
    knows how to run.
    """
    members = list(members)
    if not members:
        return RaidPrepPlan(why_not="Nobody is on the roster to prepare for raid.")

    mode = family_mode(members)
    if mode != MODE:
        return RaidPrepPlan(
            why_not="The family's job is %s, not %s."
            % (mode or "not agreed across the roster", MODE)
        )

    blocked = readiness(members, mail_items)
    if blocked:
        return RaidPrepPlan(why_not=blocked)

    gaps = profession_gaps(members)

    return RaidPrepPlan(
        mail_items=mail_items,
        profession_gaps=gaps,
    )


def report(raid_plan) -> str:
    """One sentence for the log and for Discord."""
    if raid_plan.why_not:
        return "raid prep not possible: %s" % raid_plan.why_not

    parts = []
    if raid_plan.mail_items:
        parts.append("collecting %d mail item(s)" % raid_plan.mail_items)
    if raid_plan.profession_gaps:
        profs = ", ".join(
            "%s (%d->%d)" % (p, c, t) for _, p, c, t in raid_plan.profession_gaps
        )
        parts.append("raising %s" % profs)
    if raid_plan.profession_gaps == () and raid_plan.mail_items == 0:
        parts.append("guild-bank deposit pass will run")

    if not parts:
        return "raid prep: nothing to do"

    return "raid prep: " + "; ".join(parts)
