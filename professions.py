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

from dataclasses import dataclass, field, replace
from typing import Mapping, Sequence

import goals
# The travel vocabulary, imported rather than re-spelled. `to_errand` needs
# the exact keyword mod-overseer resolves, and tests/test_travel_npc.py
# already compares travel.ROLES against the C++ table in both directions -
# so importing it means this module cannot drift from the module that reads
# what it writes.
import travel

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
# both walls this module was written against have now come down.
#
# THE AIM CAME DOWN IN infra#2840. When professions.py was written a bot could
# not be pointed at a CHOSEN NPC: ChangeToWanderNpc took no argument
# (NewRpgInfo.h:104) while ChangeToDoQuest took a target (:106), so a bot sent
# wandering picked its own trainer. Patch 0005 made it aimable, the
# overseer_roster.travel_npc column and DriveTravel() shipped with it, and
# travel.ROLES carries "profession trainer". Proven end to end on dev: a bot
# walked 1,914 yards cross-zone into Ironforge and handed in a quest.
#
# THE TRANSACTION CAME DOWN IN infra#2757, WHICH IS THIS. mod-overseer's
# TrainOnArrival buys the named trade from the trainer the character was sent
# to, through the core's own Trainer::TeachSpell so the money is taken and the
# free-slot rule enforced; UnlearnProfession runs the one line the client's
# CMSG_UNLEARN_SKILL handler runs; and the four roster columns this module now
# fills (see `to_errand`) are the road between the plan and the worldserver.
# The three blockers this constant used to list are answered, and the answers
# are cited in mod_overseer.cpp rather than restated here.
#
# WHAT IS LISTED BELOW IS WHAT IS STILL TRUE. It is deliberately not empty: an
# empty BLOCKERS would say "nothing can go wrong", and the failure this whole
# epic is about is a feature that reports success while doing nothing.
BLOCKERS = (
    "NONE OF IT EXISTS UNTIL THE IMAGE IS BUILT. The verbs are C++ in "
    "mod-overseer, which compiles only on a push to main and reaches the world "
    "only through a worldserver pin bump - about forty-five minutes. The four "
    "roster columns travel separately, in the DB-IMPORT image, applied by the "
    "db-upgrade initContainer (infra#2846). Until BOTH have shipped, this "
    "module's plan is still written and unread, and every column it fills is "
    "silently dropped by a SELECT that fails with error 1054.",
    "SAME MAP ONLY, AND THAT IS A REFUSAL RATHER THAN A GAP. "
    "ResolveTravelTarget will not pick a spawn on another map, because "
    "MoveFarTo paths through PathGenerator and there is no navmesh across an "
    "ocean. The family are all in Westfall on map 0 and every profession "
    "trainer they need is on it, so this costs them nothing today - but a "
    "trade whose only trainer is in Kalimdor needs a boat, and the errand will "
    "refuse rather than walk into the sea.",
    "ONE TRADE AT A TIME, ON PURPOSE (see OPEN_ORDER). Eight queued would be "
    "eight things half-done. The family holds none of its assigned trades yet, "
    "so at one per settled errand this is a sequence of journeys and not a "
    "single switch being thrown.",
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


# --------------------------------------------------------------- the errand --
#
# TURNING A DECISION INTO SOMETHING THE WORLDSERVER CAN SEE.
#
# Everything above this line decides. Nothing above it acts, and that is the
# rule the module was built around. What was missing was not a decision, it was
# a ROAD: `overseer_trade` is a Python table and mod-overseer reads
# `overseer_roster`, so the plan sat there, correct and unread, for two days.
#
# The functions below say what the roster row should CONTAIN for a given plan.
# They still act on nothing - they return values, the bridge writes them, and
# the worldserver is what actually visits a trainer. `settled` remains the only
# thing that can move an assignment forward, and it still takes the observation
# as an argument.


@dataclass(frozen=True)
class Errand:
    """The `overseer_roster` columns one character's outstanding plan becomes.

    ONE CHARACTER, because `plan()` opens one trade at a time and both of its
    assignments - the unlearn that makes room and the learn that fills it - are
    for the same person. A shape that could carry two people would be a shape
    that invited two errands at once, which OPEN_ORDER exists to prevent.

    `unlearn_max` IS THE PRICE, and it is the reason this is a dataclass rather
    than a dict. It is the observed value of the skill being destroyed at the
    moment the plan was made, and mod-overseer refuses the unlearn if the live
    value is above it. So the request carries what the requester believes it
    costs, and a stale belief produces a refusal instead of a surprise.
    """

    character: str
    learn_skill: int = 0
    unlearn_skill: int = 0
    unlearn_max: int = 0
    # The travel role, and it is READ FROM travel.ROLES rather than spelled
    # here. A third spelling of "profession trainer" is a third thing to get
    # wrong, and the one place this string has to be right is the one place a
    # test already compares it against the C++ (tests/test_travel_npc.py).
    travel_npc: str = ""


# Only a LEARN needs a journey. Unlearning is a spellbook action - the client
# sends CMSG_UNLEARN_SKILL and no NPC is involved - so an unlearn-only errand
# moves nobody, and pretending it did would send the family across a zone to
# watch somebody forget something.
# Looked up rather than merely spelled, so a rename in travel.ROLES is an
# ImportError-shaped failure at startup instead of an errand that resolves to
# nothing six hours later.
TRAINER_ROLE = next(role for role in travel.ROLES if role == "profession trainer")


def wanted_ids(name: str) -> str:
    """This character's assigned primaries as the roster column holds them.

    Skill ids and not words, and the reasoning is in the migration: both ends
    already hold these numbers - goals.SKILL_IDS here, SkillLineStore and
    `character_skills`.skill there - so a word would be a THIRD spelling of a
    fact that already exists twice, and the only thing a third spelling can add
    is a way to disagree. The prose explaining each choice stays in ROSTER,
    where it can be read; it has no place in a VARCHAR.

    Sorted, so the column does not churn between two identical answers.
    """
    return ",".join(str(i) for i in sorted(skill_id(s) for s in assigned(name)))


def to_errand(trade_plan: TradePlan, skills: Mapping[str, Mapping[str, int]]):
    """What the roster should say, for the one character this plan is about.

    Returns None when there is nothing to ask for - an empty plan, or one whose
    assignments are all notes. `skills` is the same observation `settled` takes
    and for the same reason: the price of an unlearn is a fact about the world,
    and this module must not be able to invent one.

    BOTH VERBS ARE WRITTEN AT ONCE, and the ordering is left to the world. It
    would be tidier to send the unlearn, wait, then send the learn - and it
    would also be a state machine in this process, with a memory, that has to
    survive a restart. It does not need to be: mod-overseer's learn refuses
    while both primary slots are full and says so, its unlearn runs on its own
    poll, and the character simply stands at the trainer for the thirty seconds
    in between. The world already sequences this correctly, so the plan does
    not have to.
    """
    if not trade_plan.assignments:
        return None

    character = trade_plan.assignments[0].character
    errand = Errand(character=character)
    for assignment in trade_plan.assignments:
        if assignment.character != character:
            # `plan()` guarantees this cannot happen; said out loud rather than
            # silently dropped, because a second character appearing here means
            # the one-trade-at-a-time rule has broken and the roster would be
            # given half an errand.
            raise ValueError(
                "a plan covering %s and %s cannot become one errand"
                % (character, assignment.character)
            )
        if assignment.verb == "unlearn":
            errand = replace(
                errand,
                unlearn_skill=assignment.skill_id,
                # The observed value, NOT assignment.cost. They agree today,
                # and the one that has to be right is the one read from the
                # world - a cost carried through a dataclass is a belief, and
                # this is the number a refusal will be measured against.
                unlearn_max=int(skills.get(character, {}).get(assignment.skill, 0)),
            )
        else:
            errand = replace(
                errand,
                learn_skill=assignment.skill_id,
                travel_npc=TRAINER_ROLE,
            )
    return errand


def traveller(errand) -> str:
    """Who must become the family's one traveller for this errand, or ''.

    THIS IS THE ANSWER TO THE BLOCKER THAT LOOKED UNANSWERABLE, and it is worth
    stating plainly because the obvious fix is the wrong one. `travel_npc` is
    the only way to send a character to an NPC, and mod-overseer refuses to
    send anyone who does not carry `new rpg`. The family carry `new rpg` on the
    LEADER ALONE, deliberately: it acts at relevance 3.0-11.0 against follow's
    1.0, so a follower given both wanders off every tick, which is the 937-yard
    scatter of infra#2812. So the errand column is unusable for exactly the
    characters that need it.

    The obvious fix is to give the follower `new rpg` for the duration. That is
    the scatter, re-run, with a reason attached.

    The fix here changes WHO TRAVELS instead of HOW MANY TRAVEL. A character
    with an errand becomes the leader, and the other four follow it - through
    machinery that already exists and is not touched: the `lead` column,
    KeepRosterGrouped promoting it, KeepRosterFollowing re-pointing the rest.
    The invariant survives exactly as it was: one character carries `new rpg`,
    and it is the group leader. The family stays together and goes to the
    trainer, which is what "the party must stay together" actually asks for.

    An unlearn-only errand returns '' - nobody has to go anywhere, so nobody
    should be made to lead.
    """
    if not errand or not errand.travel_npc:
        return ""
    return errand.character
