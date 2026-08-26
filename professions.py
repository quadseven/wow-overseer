"""Who in the family takes which trade - and nothing that grants one.

Pure module, same seam as council.py, bonds.py and goals.py: state in, a
decision and some sentences out. bridge.py reads the rows, speaks the lines and
records the outcome. Nothing here talks to MySQL, to Discord or to an LLM.

WHY THIS EXISTS (infra#2757). All five characters gather herbs and nothing any
of them owns consumes one. Measured live 2026-08-23 against `character_skills`:

    herbalism (182)   Grug 34/75  Ugga 17  Bork 15  Og 8  Grog 4
    alchemy (171), cooking (185), first aid (129), fishing (356)   ALL 1/75
    no mining, no skinning, no TAILORING, no leatherworking, no blacksmithing

Between them they carry ~84 Linen Cloth, three Bolts of Linen, and recipes and
patterns for professions nobody has. Every bag is 100% full, which is #2813,
which is also why the family cannot loot a quest item, which is #2830 and
#2829. The gathering loop has no consumer bolted to the far end.

WHY UPSTREAM NEVER DID IT. `PlayerbotFactory::InitTradeSkills` is the function
that picks a bot's two professions, and its first two lines are

    if (!sRandomPlayerbotMgr.IsRandomBot(bot))
        return;
                                    -- PlayerbotFactory.cpp:2755-2758

mod-overseer's TrainRoster calls `factory.InitSkills()` (mod_overseer.cpp:2206)
expecting it to do the whole job, and `InitSkills` does call `InitTradeSkills`
(PlayerbotFactory.cpp:3172) - which has therefore returned at its first line
every single time it has run for these five. Their accounts are named, so they
can never enter the `<prefix>0..N` random-bot list; they are kept out of
`currentBots` so they are never re-rolled; and SelfBotLevel is 3. Three
independent reasons, any one of them enough. Same wall as #2756 (talents),
#2813 (bags) and #2782 (trainer spells) - this is the fourth thing it has
silently withheld.

THE RULE THAT SHAPES EVERYTHING BELOW. Evan rejected #2823 for conjuring bags
out of nowhere, and #2782 is open against spells that appear without a trainer
ever being visited. A profession that simply shows up in `character_skills` is
the same violation wearing a different noun. So this module DECIDES and never
GRANTS. It produces errands - "Ugga must find a tailoring trainer" - and an
assignment only ever becomes settled when the world is observed to already
agree (see `settled`). What the errand still needs that this repo cannot do yet
is written down in BLOCKERS rather than routed around - and so is what it no
longer needs, because the aiming wall this module was first written against has
since come down (infra#2840).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import goals

# The skill ids are NOT restated here. goals.SKILL_IDS was verified live
# against `character_skills` across 100+ characters and is already this
# service's answer to "what number is tailoring"; a second copy is a second
# thing to get wrong, and the two would drift the first time one was edited.
GATHERING = frozenset({"herbalism", "mining", "skinning"})
CRAFTING = frozenset({"alchemy", "blacksmithing", "enchanting", "engineering",
                      "inscription", "jewelcrafting", "leatherworking",
                      "tailoring"})
PRIMARY = GATHERING | CRAFTING

# Free. They cost no primary slot, and every one of the five already holds all
# three at 1/75. So they are never an errand here - nobody has to go anywhere
# or give anything up to have them. They are a LEVELLING matter, and the note
# says so: first aid in particular is a second consumer for the 84 Linen Cloth
# the family is carrying, which costs nobody a profession.
SECONDARY = frozenset({"first aid", "cooking", "fishing"})

# Two, and the world enforces it. Upstream reads it as
# `std::min<uint32>(2, CONFIG_MAX_PRIMARY_TRADE_SKILL)`
# (PlayerbotFactory.cpp:2760-2761), so two is the ceiling however the realm is
# configured. This is the fact that makes the roster below expensive: all five
# already hold herbalism AND alchemy, so four of them have to give up BOTH
# before they can take the pair they are assigned.
MAX_PRIMARY = 2

# A skill at this value has been learned and never used once.
#
# THIS IS NO LONGER A PERMISSION GATE, AND THE CHANGE IS DELIBERATE. It used to
# be: nothing above the floor could be given up at all. That rule was correct
# while the plan was "make one tailor out of a spare slot", and it is wrong now
# - the family's own assignment (ROSTER) has Grug, Bork, Og and Grog each give
# up a herbalism they HAVE worked, Grug's at 34/75. A guard that blocks the
# decision the family made is not protecting anything, it is just refusing.
#
# So the floor became a REPORTING threshold instead: anything above it is a
# real loss, it is priced into Assignment.cost, and it is said out loud in the
# plan's notes and in the errand's own reason. What replaced the floor as the
# actual protection is `expendable` - see the three conditions there, which are
# about the family's intended END STATE and are strictly stronger than a value
# check, because they cannot be satisfied by accident.
FLOOR = 1

# What a class ends up wearing. Low-level characters wear whatever drops, but
# the ARMOUR is what makes a crafting trade worth being: a tailor who wears
# cloth wears what she makes, and a tailor who wears plate has taken a
# profession that can only ever make things for other people. Used to CHECK the
# roster below rather than to build it (see `suits_wearer`), because a table
# handed down by a person should still be answerable to a rule.
ARMOUR = {
    "warrior": "plate", "paladin": "plate", "death knight": "plate",
    "hunter": "mail", "shaman": "mail",
    "rogue": "leather", "druid": "leather",
    "priest": "cloth", "mage": "cloth", "warlock": "cloth",
}

# The crafting trades that make wearable armour, and what they make it out of.
# Anything not here (alchemy, enchanting, engineering, inscription,
# jewelcrafting) makes things nobody wears, so its owner's armour is irrelevant
# and `suits_wearer` says so rather than inventing an opinion.
CRAFT_ARMOUR = {
    "tailoring": "cloth",
    "leatherworking": "leather",
    "blacksmithing": "plate",
}


@dataclass(frozen=True)
class Member:
    """One character as the trade plan sees it.

    `skills` is PRIVATE - a character's professions are not something you can
    read off a portrait, which is the same rule council.py enforces. It is
    profession skills only; the caller filters, because `character_skills`
    holds languages, Defense and every weapon skill too, and counting those was
    the bug that made the council's own trade proposal unreachable.
    """

    name: str
    class_name: str
    skills: Mapping[str, int] = field(default_factory=dict)
    # Higher is older, from bonds.FAMILY. Used only to break ties, and only so
    # that the same family always produces the same plan - an answer that
    # depends on dict order is an answer that changes every restart.
    seniority: int = 0


@dataclass(frozen=True)
class Assignment:
    """One errand at one trainer.

    `verb` is 'learn' or 'unlearn'. They are separate assignments on purpose:
    a character with both primary slots full has to make room BEFORE it can
    take a trade, at a different trainer, and folding the two into one row
    would hide the half that costs somebody something.

    `cost` is the skill value being destroyed by an unlearn, 0 for a learn. It
    exists so that a loss can never be silent: Grug's herbalism is 34/75 and
    the family should be told it is going, not discover it afterwards.
    """

    character: str
    verb: str
    skill: str
    skill_id: int
    reason: str
    said: str
    cost: int = 0


@dataclass(frozen=True)
class TradePlan:
    assignments: tuple = ()
    # Things that are true and need no errand: who is already correct, what the
    # secondaries are, and every point of worked skill the plan is going to
    # destroy. Notes cost no trainer visit, which is exactly why they are not
    # assignments.
    notes: tuple = ()


@dataclass(frozen=True)
class _Trade:
    """One character's assigned pair, and why it is theirs."""

    primaries: tuple
    why: str


# WHO TAKES WHAT. Evan's assignment, with the reasoning kept next to it.
#
# WHY A TABLE IS THE RIGHT SHAPE HERE, having been the wrong one before. An
# earlier draft of this module DERIVED a single tailor from armour and
# seniority, because the family's need was a single need. This is a different
# decision: it is a whole economy, and its correctness is a property of the
# SET, not of any member - three gathering trades covering five characters,
# every gatherer feeding a craft somebody in this family owns, and one
# character deliberately dependent on the others. No per-member rule produces
# that, and one reverse-engineered to produce it would be a table wearing a
# function's clothes. So the table is the honest form - and every row carries
# its reason, which is what the "do not hardcode without explaining" rule is
# actually asking for.
#
# Keyed by NAME rather than by class, because these are five named people and
# not five slots; `suits_wearer` is what keeps the pairing answerable to the
# class anyway.
ROSTER = {
    "Grug": _Trade(
        primaries=("mining", "blacksmithing"),
        why=(
            "the father, a plate-wearing warrior who tanks: blacksmithing makes "
            "the plate he takes hits in, and mining feeds it. His ore also "
            "feeds Grog's jewelcrafting, so this is the gathering trade two of "
            "the family's crafts run on"
        ),
    ),
    "Bork": _Trade(
        primaries=("skinning", "leatherworking"),
        why=(
            "the rogue, who wears leather and is already killing the things it "
            "comes off. Skinning is the one gathering trade that costs him no "
            "detour at all - it is done on corpses he made anyway"
        ),
    ),
    "Og": _Trade(
        primaries=("tailoring", "enchanting"),
        why=(
            "the mage, who wears cloth. Tailoring is the family's BAG problem "
            "(#2823, #2829, #2813) and it runs on LOOTED cloth, not on a "
            "gathering profession - 84 Linen Cloth is already in their bags - "
            "so he loses nothing by spending his second slot on enchanting "
            "instead of a gatherer. Enchanting also has its own supply: it eats "
            "the unusable gear they are already hoarding"
        ),
    ),
    "Ugga": _Trade(
        primaries=("herbalism", "alchemy"),
        why=(
            "the priest and the healer, and the one character already holding "
            "exactly the right pair. Potions and elixirs are what a healer "
            "hands out, and she becomes the family's SOLE herbalist by design - "
            "which is what turns five people gathering into one supply chain"
        ),
    ),
    "Grog": _Trade(
        primaries=("inscription", "jewelcrafting"),
        why=(
            "the elder son, and the only one with no gathering trade - "
            "deliberately. The other four already cover all three gathering "
            "professions, and the crafts still unclaimed are engineering, "
            "inscription and jewelcrafting. Inscription runs on Ugga's herbs "
            "and jewelcrafting on Grug's ore, so he needs no slot of his own to "
            "feed them: he is the one character whose trade depends entirely on "
            "the family supplying him, which makes the material hand-off "
            "(#2830) structural rather than optional. Glyphs benefit all five, "
            "permanently"
        ),
    ),
}

# Engineering is the one primary nobody is assigned, ON PURPOSE. Evan wants the
# guild (#2831) to cover the last profession, so leaving it open is a decision
# and not an oversight - and this constant is here so that a future reader
# counting the crafts does not "fix" it.
UNASSIGNED = ("engineering",)

# The order the family opens its trades in, one at a time.
#
# WHY ONE AT A TIME: every learn is a journey to a trainer AND a transaction at
# the end of it. The journey exists now (infra#2840); the transaction does not
# (BLOCKERS). Eight queued would be eight things half-done instead of one.
#
# WHY THIS ORDER:
#   tailoring       first, because it is the measured blocker. Every bag is
#                   full, a full bag freezes a character on a herb node
#                   (#2813), and the linen is already in their bags - so this
#                   is the one trade that pays out the day it is learned.
#   mining          before blacksmithing, and skinning before leatherworking:
#                   a craft with no supply is a skill that sits at 1/75, which
#                   is the exact failure this whole issue is about.
#   enchanting      after Og's tailoring, so the bag maker is working before he
#                   spends his second slot.
#   inscription,    LAST, because Grog's pair depends entirely on other people
#   jewelcrafting   having their gathering trades first. Opening them early
#                   would be opening two more empty skills.
OPEN_ORDER = (
    "tailoring",
    "mining", "blacksmithing",
    "skinning", "leatherworking",
    "enchanting",
    "inscription", "jewelcrafting",
)

# What the errand still needs - and, first, what it no longer needs, because
# the wall this module was originally written against has since come down.
#
# THE AIM EXISTS NOW, AND THIS MODULE USED TO SAY IT DID NOT. When professions.py
# was written the blocker was that a bot could not be pointed at a CHOSEN NPC:
# ChangeToWanderNpc took no argument (NewRpgInfo.h:104) while ChangeToDoQuest
# took a target (:106), so a bot sent wandering picked its own trainer at random.
# That asymmetry is GONE. infra#2840 added patch 0005 (an aimable
# ChangeToWanderNpc that walks the long leg by position), the
# overseer_roster.travel_npc column, DriveTravel() in mod-overseer, and the
# travel vocabulary shared with Python. travel.ROLES carries
# "profession trainer" -> UNIT_NPC_FLAG_TRAINER_PROFESSION, which is precisely
# the aim this plan wanted. It was proven end to end on the dev world - a bot
# walked 1,914 yards cross-zone into Ironforge and handed in a quest - and the
# family runs that binary on the live realm.
#
# infra#2818's half is answered too: goals.life_strategies(aimed=True) gives an
# aimed follower `new rpg` back, so the character that is sent is one that
# actually runs the strategy that reads the aim.
#
# SO THE LEARNING STEP IS A DELIBERATE FOLLOW-UP, NOT A BLOCKED ONE. It is out
# of scope in this change because this change is the DECISION and that one is
# the TRANSACTION - not because it cannot be built. What remains is one verb.
BLOCKERS = (
    "WHAT infra#2840 DELIVERED IS TRAVEL, NOT TRANSACTION. A character aimed "
    "at a profession trainer walks there and stands in front of it. It does "
    "not train. That is the whole remaining distance between this plan and a "
    "family that holds its trades, and it is one verb wide.",
    "NOTHING LEARNS FROM A TRAINER TODAY. mod-overseer's TrainRoster calls "
    "factory.InitSkills / InitClassSpells / InitAvailableSpells directly "
    "(mod_overseer.cpp:2206-2209) with no NPC involved at all - "
    "InitAvailableSpells walks the trainer TABLES, not a trainer. That is "
    "infra#2782 confirmed, and it is why this module must not add a second "
    "path of the same shape for professions.",
    "mod-playerbots' TrainerAction - the only code that learns anything AT a "
    "trainer - requires a trainer creature that is already SELECTED and in "
    "interaction range: GetCreatureTarget() returns nullptr otherwise and "
    "Execute bails immediately (TrainerAction.cpp:22-24). Being in range is "
    "now solved; SELECTING the trainer is not. With a master set it reads the "
    "MASTER's selection rather than the bot's (TrainerAction.cpp:75-82), and "
    "infra#2822 gave the family a master.",
    "AND THE ARRIVAL STILL DOES NOTHING. NewRpgWanderNpcAction interacts only "
    "for a QUEST when it reaches an NPC (NewRpgAction.cpp:398-400) - there is "
    "no train, no buy, no repair branch. The aim is built; the verb for what "
    "to do on arrival is what infra#2782 is now free to build on top of it.",
)


def skill_id(name: str) -> int:
    """The `character_skills.skill` number, from the one table that has them."""
    return goals.SKILL_IDS[name]


def armour_for(class_name: str) -> str:
    """What this class eventually wears, or '' for a class nobody named."""
    return ARMOUR.get((class_name or "").strip().lower(), "")


def assigned(name: str) -> tuple:
    """The primaries this character is meant to end up with. () if unlisted."""
    trade = ROSTER.get(name)
    return trade.primaries if trade else ()


def suits_wearer(name: str, class_name: str) -> bool:
    """Does every armour-making craft in this character's pair suit their class?

    The table in ROSTER was handed down by a person, and this is what keeps it
    answerable to a rule anyway: a leatherworking plate-wearer or a tailoring
    warrior would pass unnoticed forever otherwise. Trades that make nothing
    anybody wears are not judged - `CRAFT_ARMOUR` has no opinion about
    alchemy - so this is True for them, which is the honest answer rather than
    a vacuous one.
    """
    worn = armour_for(class_name)
    return all(CRAFT_ARMOUR[skill] == worn
               for skill in assigned(name) if skill in CRAFT_ARMOUR)


def primaries(member: Member) -> tuple:
    """The primary professions this character holds, in a fixed order."""
    return tuple(sorted(name for name in member.skills if name in PRIMARY))


def free_primary_slots(member: Member) -> int:
    return max(0, MAX_PRIMARY - len(primaries(member)))


def _holders(family: Sequence, skill: str) -> tuple:
    return tuple(sorted(m.name for m in family if skill in m.skills))


def _keepers(family: Sequence, skill: str) -> tuple:
    """Who is ASSIGNED this skill and is in this family. The end state."""
    return tuple(sorted(m.name for m in family if skill in assigned(m.name)))


def expendable(member: Member, family: Sequence) -> tuple:
    """Primaries this character may give up, cheapest first.

    THIS IS THE GUARD, and it was rewritten when the plan went from one tailor
    to a whole economy. The old form was "at the floor, and somebody else holds
    it". That is a fact about NOW, and it turned out to be both too strict and
    too weak.

    TOO STRICT: it blocked the family's own decision. Grug, Bork, Og and Grog
    are each assigned a pair that does not include herbalism, and three of them
    have WORKED herbalism (34, 15, 8). A value check would refuse the last
    three trades outright and there would be no way to say "yes, we meant it".

    TOO WEAK, which is the more interesting half: "somebody else holds it" is
    satisfied right up until the second-to-last holder drops it, so an
    unlucky ORDER could walk the family down to a single holder who is himself
    scheduled to drop it next. The old rule could not see that, because it
    could not see the plan.

    So the three conditions are now about the intended END STATE, and they are
    order-independent:

      (a) the skill is NOT in this character's own assignment - you may never
          give up something you are meant to have;
      (b) somebody in this family IS assigned it - so the family still has it
          when the plan is finished. Herbalism and alchemy both survive because
          Ugga is assigned both and is never a dropper;
      (c) somebody OTHER than this character holds it right now - so the
          transition never passes through zero holders either.

    (b) is what (a) and (c) alone could not give: it is a statement about where
    the family is going, and it cannot be satisfied by accident, because the
    only thing that can satisfy it is a row in ROSTER that a person wrote.

    Cheapest first, and crafting before gathering at equal cost: a gathering
    skill is a SOURCE, and sources are what feed the trades being opened.
    """
    mine = assigned(member.name)
    out = []
    for name in primaries(member):
        if name in mine:
            continue
        if not _keepers(family, name):
            continue
        if len(_holders(family, name)) < 2:
            continue
        out.append(name)
    return tuple(sorted(out, key=lambda s: (member.skills[s], s in GATHERING, s)))


def alchemist(family: Sequence) -> str:
    """Who the family's alchemist is: whoever is assigned alchemy.

    Read off the roster rather than computed from skill values. Alchemy is the
    profession that consumes herbs (#2813), and the plan pairs it with the
    family's only herbalist on purpose, so "who gathers most right now" is the
    wrong question - it is a fact about today that the plan is about to change.
    """
    for member in sorted(family, key=lambda m: m.name):
        if "alchemy" in assigned(member.name):
            return member.name
    return ""


def _next_trade(family: Sequence) -> tuple:
    """(member, skill) for the ONE trade the family opens next, or (None, '').

    OPEN_ORDER decides, not the family order, so the sequence is the same
    whatever order the rows came back in.
    """
    by_name = {m.name: m for m in family}
    for skill in OPEN_ORDER:
        for name in sorted(ROSTER):
            if skill not in assigned(name):
                continue
            member = by_name.get(name)
            if member is None or skill in member.skills:
                continue
            return member, skill
    return None, ""


def plan(family: Sequence) -> TradePlan:
    """The family's trade decision: state in, errands and notes out.

    Deterministic - the same family always produces the same plan, so a test
    can pin it and the bridge cannot be surprised by a scene it has already
    played out.
    """
    family = list(family)
    if not family:
        return TradePlan()

    notes = _notes(family)
    taker, skill = _next_trade(family)
    if taker is None:
        return TradePlan(notes=notes)

    rows: list = []
    spare = free_primary_slots(taker)
    if not spare:
        room = expendable(taker, family)
        if not room:
            # Said, not silently skipped. This is the state a broken guard
            # would produce, and it is the one thing about this module that
            # should be loud rather than quiet.
            notes = notes + (
                f"{taker.name} cannot take {skill}: both primary slots are "
                f"full and neither can be given up. Held: "
                f"{', '.join(primaries(taker))}; assigned: "
                f"{', '.join(assigned(taker.name))}.",
            )
            return TradePlan(notes=notes)
        drop = room[0]
        rows.append(_drop(taker, drop, family))

    rows.append(_take(taker, skill))
    return TradePlan(assignments=tuple(rows), notes=notes)


def _drop(taker: Member, skill: str, family: Sequence) -> Assignment:
    cost = int(taker.skills.get(skill, 0))
    keeper = ", ".join(_keepers(family, skill))
    priced = (f"It is at {cost}/75, which is real work and is going"
              if cost > FLOOR else
              f"It is at {cost}/75 - learned and never once used")
    return Assignment(
        character=taker.name, verb="unlearn", skill=skill,
        skill_id=skill_id(skill), cost=cost,
        reason=(
            f"{taker.name} holds {MAX_PRIMARY} primary professions and is "
            f"assigned {' + '.join(assigned(taker.name))}, so {skill} has to "
            f"go to make room. {priced}. The family keeps {skill} because "
            f"{keeper} is assigned it."
        ),
        said=(f"{taker.name} give up {skill}. {keeper} keep that for family "
              f"now."),
    )


def _take(taker: Member, skill: str) -> Assignment:
    trade = ROSTER[taker.name]
    return Assignment(
        character=taker.name, verb="learn", skill=skill,
        skill_id=skill_id(skill), cost=0,
        reason=(
            f"{taker.name} is assigned {' + '.join(trade.primaries)}, because "
            f"{trade.why}."
        ),
        said=f"{taker.name} go find {skill} teacher. Family need {skill}.",
    )


def _notes(family: Sequence) -> tuple:
    """Everything true about the plan that costs nobody a trainer visit."""
    notes: list = []

    who = alchemist(family)
    if who:
        notes.append(
            f"{who} is the family's alchemist and its only herbalist. Every "
            "herb the family gathers is meant to end up with one person who "
            "can use it, which is the consumer #2813 says the gathering loop "
            "has never had."
        )

    settled_already = sorted(
        m.name for m in family
        if assigned(m.name) and not set(assigned(m.name)) - set(m.skills)
    )
    if settled_already:
        notes.append(
            f"Already correct and needing no errand at all: "
            f"{', '.join(settled_already)}."
        )

    # WHAT THIS PLAN DESTROYS, ADDED UP, IN ADVANCE. Nobody should find out
    # afterwards that Grug's 34/75 herbalism went. It is the single largest
    # cost in the whole assignment and it is stated before a single errand
    # runs.
    losses = []
    for member in sorted(family, key=lambda m: m.name):
        for skill in primaries(member):
            if skill in assigned(member.name):
                continue
            value = int(member.skills.get(skill, 0))
            if value > FLOOR:
                losses.append((value, member.name, skill))
    if losses:
        losses.sort(reverse=True)
        worst = ", ".join(f"{name}'s {skill} at {value}/75"
                          for value, name, skill in losses)
        notes.append(
            "THIS PLAN DESTROYS WORKED SKILL, and here is all of it before any "
            f"of it happens: {worst}. Every point of it is deliberate - each "
            "of those characters is assigned a pair that does not include the "
            "skill - and the family keeps the trade itself, because somebody "
            "else is assigned it."
        )

    unheld = sorted(
        s for s in SECONDARY
        if any(s not in m.skills for m in family)
    )
    if not unheld:
        notes.append(
            "All five already hold cooking, fishing and first aid, and none of "
            "the three costs a primary slot. So they are a LEVELLING matter "
            "and never an errand - and first aid in particular is a second "
            "consumer for the linen, that nobody gives anything up for."
        )

    if UNASSIGNED:
        notes.append(
            f"Deliberately unassigned: {', '.join(UNASSIGNED)}. The guild "
            "(#2831) is meant to cover the last profession, so this is a "
            "decision and not a gap to be filled in."
        )
    return tuple(notes)


def errand(assignment: Assignment) -> str:
    """What the character must physically go and do, in one sentence.

    A JOURNEY, always - this is the sentence that stops the change being a
    database write with a story attached. Unlearning happens at a trainer of
    the profession being dropped, which is a second trip and not a free action.
    """
    article = "an" if assignment.skill[0] in "aeiou" else "a"
    return (f"{assignment.character} must find {article} {assignment.skill} "
            f"trainer and {assignment.verb} {assignment.skill}.")


def lines(trade_plan: TradePlan) -> list:
    """The family saying it, in the "Name: words" shape the council speaks in.

    Said in party chat by the character it is about (#2829: a need has to
    become a request to a person). A plan nobody hears is the overseer talking
    to itself, which is the half of every one of these features that Evan
    actually sees.
    """
    return [f"{a.character}: {a.said}" for a in trade_plan.assignments]


def settled(assignment: Assignment, skills: Mapping[str, int]) -> bool:
    """Has the WORLD already done what this assignment asked for?

    The only thing that may move an assignment forward, and it takes the
    observed skills as an argument rather than going and getting them. That is
    deliberate and it is the whole no-magic guarantee in one signature: this
    module has no path to the observation, so it cannot fake one. The bridge
    reads `character_skills`, hands the answer here, and writes 'learned' only
    when the answer is yes - by whatever route it happened, including Evan
    walking Ugga to a trainer himself.
    """
    if assignment.verb == "unlearn":
        return assignment.skill not in skills
    return assignment.skill in skills
