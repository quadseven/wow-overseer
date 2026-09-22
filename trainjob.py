"""What `job = train` actually does, and what it refuses to pretend to do.

infra#2834 named twelve job modes and wired two. infra#3338 is what that cost:
a non-quest job stands the quest drive down and nothing replaces it, so
`job='train'` did not make anybody train, it made them stop. This module is the
positive half - the thing that turns the mode into a behaviour - and the honest
account of where that behaviour stops.

THE GAP IT FILLS, WHICH IS ONE LINE WIDE AND HAD NOBODY IN IT. mod-overseer
derives its own learn errands: `StepTowardAssignment` reads the declared end
state in `overseer_roster.professions`, decides the next trade, and writes
`overseer_roster.learn_skill` through `AimLearnAt` (mod_overseer.cpp). It then
cannot act on it. Nothing in the worldserver ever writes
`overseer_roster.travel_npc = 'profession trainer'` - `TravelAimBook::Claim`'s
only callers are dungeon staging and escort catch-up - so the errand it wrote
for itself sits there, correct and unwalked, until something outside the
process aims the character. `travel.aim_statements` is the function that would,
and infra#3270 is the observation that it has never had a caller. This module
is that caller, and `job = train` is the permission to be it.

WHAT ARRIVING DOES. mod-overseer's `TrainOnArrival` buys the trade through the
core's own `Trainer::TeachSpell`, so the money is taken and the free-slot rule
is enforced; nothing appears in `character_skills` a trainer was not paid for.
This module never teaches anybody anything and has no path that could.

WHAT IT REFUSES, AND WHY THAT IS THE POINT. Three shapes of errand look
trainable and are not, and each one would walk the family somewhere to learn
nothing - travel that reports success and delivers nothing, which is the
failure this epic is named after:

  1. A SECONDARY PROFESSION. First Aid, Cooking and Fishing are what the
     operator asked for by name, so the refusal has to be loud rather than a
     silent empty set. mod-overseer resolves a training errand through
     `SkillStartedBySpell`, which gates on the core's
     `IsPrimaryProfessionSkill` (mod_overseer.cpp) - so a secondary can never
     be the subject of one, the trainer index never lists one, and
     `TrainerSpellForSkill` returns 0 for one. The module's own comment says
     as much: "that is what keeps cooking, fishing and first aid out of this".
  2. A SKILL ALREADY HELD. Measured live 2026-09-05 against
     `character_skills`: all five hold every profession the roster assigns
     them, all at 1/75. A held skill is not a learn, it is a CAP, and the
     trainer resolve narrows on `TrainerStartedSkills` - the set of trades a
     spawn can START somebody in - so a capped character aimed at a trainer
     resolves to a trainer that cannot help. quadseven/mod-overseer#196 is the
     fix for that half and it is not merged; until it is, this module will not
     send anybody on that errand.
  3. A SKILL THE ROSTER NEVER ASKED FOR. `TrainOnArrival` refuses a learn that
     is not in `plan.wanted` and drops the errand. Refusing here too means the
     family does not make the journey to be turned away at the end of it.

PURE MODULE, same seam as travel.py, jobs.py and professions.py: rows in, a
decision and some statements out. No MySQL, no Discord, no LLM. `bridge.py`
reads the rows, runs the statements and speaks the sentences.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import goals
import travel

# The mode this module is the drive for. Spelled once, and jobs.MODES is what
# it has to agree with - tests/test_trainjob.py checks that it is a real mode
# and that jobs.IMPLEMENTED claims it, so this constant cannot drift into
# naming something the vocabulary does not have.
MODE = "train"


def should_activate(jobs: dict, has_assignments: bool) -> bool:
    """Return whether outstanding training should take over ordinary questing.

    Explicit dungeon or operator modes are never preempted.  A family-wide
    quest mode is the only passive mode this policy may promote.
    """
    if not has_assignments:
        return False
    values = {str(value or "").strip() for value in jobs.values()}
    return values == {"quest"}


# Read from travel.ROLES rather than spelled, for the reason
# professions.TRAINER_ROLE gives: a third spelling of "profession trainer" is
# a third thing to get wrong, and a rename becomes an ImportError at startup
# instead of an errand that resolves to nothing six hours later.
TRAINER_ROLE = next(role for role in travel.ROLES if role == "profession trainer")

# The three the operator asked for by name. Ids come from goals.SKILL_IDS,
# which is the one place in this codebase that holds them; restating the
# numbers here would be a second spelling whose only power is to disagree.
SECONDARY = {
    name: goals.SKILL_IDS[name] for name in ("first aid", "cooking", "fishing")
}

# Said back verbatim when somebody asks for the three by name, because "no
# errand was produced" is not an answer to "make them go train fishing".
SECONDARY_NOTE = (
    "First Aid, Cooking and Fishing cannot be trained by this mode, and no "
    "mode can: mod-overseer resolves every training errand through "
    "SkillStartedBySpell, which gates on IsPrimaryProfessionSkill, so a "
    "secondary is never a trainer's answer to one. All five already hold all "
    "three at 1/75 - what is behind is the VALUE, and a trainer does not sell "
    "that. It is raised by USING the skill: First Aid has 74 points of "
    "headroom and Cooking 50, both reachable with no trainer at all, and "
    "that is where the family's secondary progress has to come from. The "
    "ceiling at 75 is NOT the next thing to ask a trainer for either - "
    "infra#3701 measured the deployed image and no rank above it can be "
    "bought at all; see professions.SECONDARY_RANK_REFUSAL."
)


@dataclass(frozen=True)
class Member:
    """One `overseer_roster` row, plus what `character_skills` says they hold.

    `wanted` is the parsed `professions` column - the declared end state, which
    is the only permission there is. `holds` is the observation, and it is
    REQUIRED rather than optional for the same reason craftpleas.answer takes
    `held`: a decision that cannot see what a character already has is a
    decision that can only guess, and the guess sends somebody on a journey.
    """

    name: str
    job: str = ""
    wanted: tuple = ()
    learn_skill: int = 0
    holds: tuple = ()


@dataclass(frozen=True)
class TrainPlan:
    """What the drive should do about a family whose job is `train`.

    `traveller` is who walks, '' for nobody. `why_not` is why nobody does, and
    it is never empty when `traveller` is - a plan that declines to act and
    cannot say why is the silent idle this whole module exists to stop.
    """

    traveller: str = ""
    skill: int = 0
    why_not: str = ""
    waiting: tuple = ()


def parse_wanted(column):
    """The `professions` column as skill ids.

    Anything unparseable is dropped, so a malformed column NARROWS the
    permission rather than widening it - the same direction mod-overseer's own
    parser in LoadProfessionPlans fails in, and the only direction a parse
    error may fail in when the value being parsed is a permission.
    """
    ids = []
    for part in str(column or "").split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            ids.append(int(part))
    return tuple(sorted(set(ids)))


def outstanding(member) -> int:
    """The trade this character must visit a trainer for, or 0.

    Every clause is a refusal mod-overseer would otherwise make at the far end
    of the journey, made here instead so the journey is not taken. See the
    module docstring for the three shapes and where each one is enforced in
    the C++.
    """
    skill = int(member.learn_skill or 0)
    if not skill:
        return 0
    if skill in SECONDARY.values():
        return 0
    if skill not in tuple(member.wanted):
        return 0
    if skill in tuple(member.holds):
        return 0
    return skill


def family_mode(members: Sequence) -> str:
    """The one mode the whole family is on, or '' if they do not agree.

    A job is family-wide by construction (jobs.py's docstring says why), so
    disagreement is not a state to average over - it is a state to decline to
    act on, because acting on half a family is how one character walks off
    alone.
    """
    modes = {str(m.job or "") for m in members}
    return modes.pop() if len(modes) == 1 else ""


def nothing_to_train(members: Sequence) -> str:
    """Why an otherwise willing family has no trainer errand.

    Separated from `plan` because it is also the answer to "may I set this
    mode": a refusal at the moment the order is written is worth more than a
    log line an hour later, and both want the same sentence.
    """
    held = sorted({s for m in members for s in tuple(m.holds)})
    capped = sorted(
        m.name
        for m in members
        if int(m.learn_skill or 0) and int(m.learn_skill) in tuple(m.holds)
    )
    said = [
        "Nobody has an outstanding profession to learn, so train would stand "
        "the quest drive down and send nobody anywhere."
    ]
    if capped:
        said.append(
            "%s already hold the trade the roster asked them to learn - that "
            "is a CAP, not a learn, and the trainer resolve cannot find a "
            "trainer for it until quadseven/mod-overseer#196 lands." % ", ".join(capped)
        )
    if not held:
        said.append(
            "No profession skills were observed at all, which usually means "
            "the reading failed rather than that the family has none."
        )
    said.append(SECONDARY_NOTE)
    return " ".join(said)


def readiness(members: Sequence) -> str:
    """Why `train` cannot be set right now, or '' when it can be.

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
        return "Nobody is on the roster to train."
    if any(outstanding(m) for m in members):
        return ""
    return nothing_to_train(members)


def plan(members: Sequence) -> TrainPlan:
    """Who to send to a trainer, or why nobody is going.

    Deliberately ONE traveller and not a queue. The family has exactly one
    character carrying `new rpg` and it is the leader (professions.traveller
    explains the whole argument); two aims is the 937-yard scatter of
    infra#2812 with a fresh reason attached. The rest of the outstanding
    errands wait their turn, and `waiting` names them so the wait is visible.
    """
    members = list(members)
    if not members:
        return TrainPlan(why_not="Nobody is on the roster to train.")
    mode = family_mode(members)
    if mode != MODE:
        return TrainPlan(
            why_not="The family's job is %s, not %s."
            % (mode or "not agreed across the roster", MODE)
        )
    blocked = readiness(members)
    if blocked:
        return TrainPlan(why_not=blocked)
    ready = sorted((m.name, outstanding(m)) for m in members if outstanding(m))
    name, skill = ready[0]
    return TrainPlan(
        traveller=name, skill=skill, waiting=tuple(n for n, _ in ready[1:])
    )


def statements(train_plan) -> list:
    """The writes that aim the traveller and clear everyone else.

    Delegated whole to `travel.aim_statements` rather than rebuilt: the
    clearing half is not optional (its docstring says why), every value is
    bound there and a test already proves it, and a second construction of the
    same UPDATE is a second place for the binding to be got wrong.
    """
    if not train_plan.traveller:
        return []
    return travel.aim_statements([train_plan.traveller], TRAINER_ROLE)


def report(train_plan) -> str:
    """One sentence for the log and for Discord."""
    if not train_plan.traveller:
        return train_plan.why_not
    waiting = (
        " %s wait their turn." % ", ".join(train_plan.waiting)
        if train_plan.waiting
        else ""
    )
    return (
        "job train: %s is aimed at %s to learn skill %d, and the family "
        "follows.%s Arriving is not learning - mod-overseer buys the trade "
        "through Trainer::TeachSpell, and only character_skills settles it."
        % (
            train_plan.traveller,
            travel.describe(TRAINER_ROLE),
            train_plan.skill,
            waiting,
        )
    )
