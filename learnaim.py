"""A learn errand that nobody is walking, and one that is already over.

infra#3686. `overseer_roster.learn_skill` non-zero makes mod-overseer's
`TravelAimBook::Claim` refuse EVERY travel aim for that character. The column
is cleared inside the worldserver in exactly one place - `ClearLearnAim`,
reached only from `TrainOnArrival` - so a character must ARRIVE at a trainer to
clear it, and arriving needs a travel aim. The gate is behind the fence it is
the gate for.

WHAT COST TEN DAYS. `overseer_trade` id 126 (learn skinning) settled on
2026-09-03 and the roster column still named skill 393 on 2026-09-13. The
worldserver refused that character's travel aim 359 times in six hours, the
family waited twenty minutes for it and left it 2,200 yards behind, and there
was no error anywhere - every component was behaving exactly as designed.

THIS MODULE DOES TWO THINGS, AND THE SECOND IS THE MORE IMPORTANT ONE.

  * IT TAKES AWAY AN ERRAND THAT IS OVER, on evidence that it was carried out:
    a settled `overseer_trade` row, or a skill the roster's declared end state
    does not ask for.

  * IT CARRIES OUT AN ERRAND NOBODY IS WALKING. A row with a non-zero
    `learn_skill` and an empty `travel_npc` is an instruction with no journey
    attached, and the answer is to write the journey - not to throw the
    instruction away. A clear discards something real; an aim lets
    `TrainOnArrival` reach its own verdict, whatever that verdict is.

WHY THERE IS NO "the character already holds it" RULE, which is the obvious
one and is wrong. `TrainOnArrival` used to read exactly that and was changed
because it is wrong (mod-overseer#74, mod_overseer.cpp ~10724): "Holding a
skill and holding it AT ITS CEILING are different facts, and only a trainer
selling the next tier tells them apart." It computes `alreadyHasSkill` and
deliberately does NOT clear on it - a character at Apprentice herbalism 75
standing next to nodes that need 120 is not finished, it is stuck. So holding
the skill is the one verdict `TrainOnArrival` stopped making, and a reconcile
that made it would stop every profession in the family at the tier it already
has. The live family is exactly that population: one character at herbalism
132 against a max of 225, and all five at First Aid 1/75.

The three verdicts `TrainOnArrival` DOES reach are: the roster does not want
this skill; the creature is not a trainer this character may use; and this
trainer has no spell to sell it. Only the first is knowable from outside the
world, and that is the only one restated here.

WHY THE COMPLETION EVIDENCE IS `overseer_trade` AND NOT `character_skills`.
A settled trade row is a record that THIS errand was carried out. The skill
map is a description of the world's current shape, which is a different claim
and a weaker one - and it may not even be current: `character_spell` was
measured on 2026-09-13 not to carry a runtime-granted spell a bot was casting
at that moment, because `Player::_SaveSpells` never persists one, and
`character_skills` is written by the same machinery.

PURE MODULE, same seam as trainjob.py, travel.py and professions.py: rows in,
a decision and some statements out. No MySQL, no Discord, no LLM. bridge.py
reads the rows, runs the statements and logs the sentence.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import trainjob
import travel

# Read from travel.ROLES rather than spelled, for the reason
# professions.TRAINER_ROLE and trainjob.TRAINER_ROLE both give: a fourth
# spelling of "profession trainer" is a fourth thing to get wrong, and a
# rename becomes an ImportError at startup instead of an errand that resolves
# to nothing six hours later.
TRAINER_ROLE = next(role for role in travel.ROLES if role == "profession trainer")

# THESE IDS ARE AN EXEMPTION, NOT A REFUSAL, and the distinction is the whole
# of mod-overseer#74 restated for secondaries. It is true that no trainer can
# START First Aid, Cooking or Fishing - every character already holds all
# three - and it is irrelevant, because `professions.secondary_rank_errand`
# does not ask one to. It fires when a character sits AT its rank ceiling
# (SECONDARY_RANK_CEILING, First Aid 75) to buy the NEXT RANK, which trainers
# do sell. Treating a secondary errand as stale would delete that errand on
# the protect cycle immediately after it was written, every time, forever.
#
# What they are exempted FROM is the `wanted` test below. `professions` on the
# roster is built by `professions.wanted_ids` out of `assigned()`, which is the
# PRIMARY trade assignment - it has never carried a secondary and was never
# meant to - so measuring a secondary against it is measuring against a
# permission that is not about it.
SECONDARY_IDS = tuple(sorted(trainjob.SECONDARY.values()))

# Why an errand is over. Constants rather than inline strings because they are
# matched in tests and read in a log line a person acts on, and a reason that
# drifts between the two is a reason nobody can grep for.
SETTLED = "the trade it named has already settled"
UNASSIGNED = "the roster does not ask for it"

@dataclass(frozen=True)
class Row:
    """One `overseer_roster` row, plus what `overseer_trade` says about it.

    `leads` is the roster's own `lead` column and not a re-derivation of it.
    bridge._mark_party_leader writes that column earlier in the same protect
    cycle from `_head_now()`, so reading it back is reading the answer the
    worldserver is about to act on - which is stronger than asking the same
    question twice and hoping the two agree.

    `traded` is every skill this character has a 'learn' row for at ANY status;
    `settled` is the subset that reached 'learned'. Two facts and not one,
    because they answer different questions - see `derived` and `finished`.
    """

    character: str
    learn_skill: int = 0
    travel_npc: str = ""
    leads: bool = False
    wanted: tuple = ()
    traded: tuple = ()
    settled: tuple = ()


@dataclass(frozen=True)
class Stale:
    """One errand that is over, and what makes it safe to say so."""

    character: str
    skill: int
    why: str


@dataclass(frozen=True)
class Plan:
    """What to do about the family's learn errands this cycle.

    `aim` is at most one character, for the reason trainjob.plan gives and the
    C++ states outright: `OverseerDecisions::AimedMover` answers
    `RefuseInFormation` for a follower, whose remedy is "aiming the leader is
    advice it can act on". Five aimed characters is the 937-yard scatter with
    a fresh reason attached, and four of the five would not move anyway.
    """

    clear: tuple = ()
    aim: str = ""
    skill: int = 0
    waiting: tuple = ()


def finished(row) -> str:
    """Why this errand is over, or '' while it is still live.

    TWO REASONS AND NOT THREE. Both are records of a decision rather than
    readings of the world's current shape - see the module docstring on
    mod-overseer#74 for the third one that used to be here and why holding a
    skill is not the same fact as having finished learning it.
    """
    skill = int(getattr(row, "learn_skill", 0) or 0)
    if not skill:
        return ""

    # THE ONE THAT ACTUALLY BIT. `_settle_trades` moved this row to 'learned'
    # because it observed the world agreeing, so the errand it names was
    # carried out - ten days before anybody noticed the roster column had not
    # followed it. Note this is about THIS skill: a settled row for a
    # DIFFERENT skill says nothing about the errand standing now.
    if skill in tuple(getattr(row, "settled", ()) or ()):
        return SETTLED

    # `TrainOnArrival`'s own first refusal - "the declared end state is the
    # only permission there is" - made before the journey rather than at the
    # far end of one the fence has made impossible.
    #
    # SECONDARIES ARE EXEMPT, see SECONDARY_IDS. An empty `professions` column
    # is exempt too, and for a reason that is not the same: it means
    # `_write_declared_professions` has not written this row - a realm missing
    # the column, a character outside bonds.FAMILY, a degraded cycle - and
    # reading absence as "the roster asks for nothing" would clear every
    # outstanding errand in the family the first time that write failed.
    wanted = tuple(getattr(row, "wanted", ()) or ())
    if skill not in SECONDARY_IDS and wanted and skill not in wanted:
        return UNASSIGNED

    return ""


def outstanding(row) -> int:
    """The skill this character must still visit a trainer for, or 0."""
    skill = int(getattr(row, "learn_skill", 0) or 0)
    return 0 if not skill or finished(row) else skill


def derived(row) -> bool:
    """Was this errand written by the worldserver rather than by a trade plan?

    `_write_trade_errand` only ever writes a `learn_skill` that
    `professions.plan` proposed, and `_record_trade_plan` writes an
    `overseer_trade` row for every such proposal and never deletes one. So a
    live errand with NO 'learn' row behind it can only have come from
    mod-overseer's own `AimLearnAt`.

    THAT IS ALSO A PROOF ABOUT THE IMAGE, and it is what lets the leadership
    borrow below go unbounded where `_errand_traveller` needs
    ERRAND_LEAD_HOURS. That bound exists because a worldserver built without
    the professions verbs never clears `learn_skill`, so an errand nothing can
    finish would reorganise the family forever. An errand `AimLearnAt` wrote
    is an errand written BY those verbs, so the drive that finishes it is
    provably deployed on the realm the row is on.
    """
    skill = int(getattr(row, "learn_skill", 0) or 0)
    return bool(skill) and skill not in tuple(getattr(row, "traded", ()) or ())

def traveller(rows: Sequence) -> str:
    """Who must lead the family because a DERIVED learn errand is outstanding.

    THE OTHER HALF OF THE AIM, and without it the aim is decoration. The C++
    refuses to move a follower in formation (`AimedMover::RefuseInFormation`)
    and says the remedy in its own words - aim the leader - so an errand on a
    character that is not leading is an errand that cannot be walked, however
    correctly its column is filled in.

    bridge._head_now asks this LAST, behind `_train_traveller` (an order a
    person just gave) and `_errand_traveller` (a trade the family decided), and
    ahead only of HOMEWARD_LEAD and seniority - which is to say it borrows the
    lead only when it would otherwise be resting. It can never preempt an order
    or a plan.

    DERIVED ERRANDS ONLY, on purpose. A trade-backed errand already has a
    borrower and that borrower is bounded by ERRAND_LEAD_HOURS; taking the
    lead for one here would route around a bound somebody wrote for a reason.
    `derived` says why this half needs no bound of its own.

    One character, sorted, so two consecutive cycles that see the same family
    reach the same answer rather than oscillating between two equally valid
    ones - an oscillating leader is a party split.
    """
    ready = sorted(r.character for r in rows or () if outstanding(r) and derived(r))
    return ready[0] if ready else ""


def plan(rows: Sequence) -> Plan:
    """The clears, and the one aim, for this family this cycle."""
    rows = list(rows or ())
    clear = tuple(sorted(
        (Stale(character=str(r.character), skill=int(r.learn_skill or 0),
               why=finished(r)) for r in rows if finished(r)),
        key=lambda s: s.character,
    ))

    # UNWALKED IS AN EMPTY COLUMN AND NOTHING ELSE. A character already aimed
    # somewhere - at a trainer by `_write_trade_errand`, at a vendor by the
    # economy, at a dungeon door by a run - is not waiting for this pass, and
    # writing over it is the second-writer collision this codebase has paid
    # for on this exact column.
    unwalked = sorted(
        (r for r in rows
         if outstanding(r) and not str(r.travel_npc or "").strip()),
        key=lambda r: r.character,
    )
    if not unwalked:
        return Plan(clear=clear)

    leading = [r for r in unwalked if r.leads]
    if not leading:
        # Nobody who can actually walk has an errand this cycle. Said rather
        # than forced: the leadership borrow above is what fixes this, and it
        # lands on the next cycle once `lead` has been rewritten. A pass that
        # aimed a follower anyway would write a column the C++ answers with
        # RefuseInFormation, which is the "written and unread" failure this
        # whole issue is about, self-inflicted.
        return Plan(clear=clear,
                    waiting=tuple(r.character for r in unwalked))

    chosen = leading[0]
    return Plan(
        clear=clear,
        aim=chosen.character,
        skill=int(chosen.learn_skill or 0),
        waiting=tuple(r.character for r in unwalked if r is not chosen),
    )


def statements(learn_plan) -> list:
    """The writes, as (sql, params) pairs for one cursor.

    Built here and executed by the caller, the same seam `travel.aim_statements`
    and `trainjob.statements` use: every value is bound where the decision is
    made, and a test proves the shape without a database.

    EVERY STATEMENT IS A COMPARE-AND-SWAP, and that is the whole of how a write
    from this process cannot step on one of the worldserver's. The clear only
    lands on the exact `learn_skill` it read, so an `AimLearnAt` that arrived in
    between keeps its errand. The aim only lands on an EMPTY `travel_npc`, so an
    economy pass or a dungeon `Claim` that took the column in between keeps it -
    the same guard `_write_trade_errand`'s ECONOMY_ERRANDS branch already
    applies, written the same way and for the same reason.

    ORDER MATTERS AND IS THE ORDER RETURNED. The clears run first, so a
    character whose errand is over has its fence lifted before anything else
    in the cycle asks the worldserver to move it.
    """
    out = [
        ("UPDATE overseer_roster SET learn_skill = 0 "
         "WHERE name = %s AND learn_skill = %s",
         (row.character, int(row.skill)))
        for row in getattr(learn_plan, "clear", ()) or ()
    ]
    if getattr(learn_plan, "aim", ""):
        out.append((
            "UPDATE overseer_roster SET travel_npc = %s "
            "WHERE name = %s AND learn_skill = %s AND travel_npc = ''",
            (TRAINER_ROLE, learn_plan.aim, int(learn_plan.skill)),
        ))
    return out


def report(learn_plan) -> str:
    """One or two sentences for the log, saying what was done and why.

    Silence is the normal state: a family with nothing over and nothing
    stranded produces the empty answer and the caller says nothing.
    """
    said = []
    for row in getattr(learn_plan, "clear", ()) or ():
        said.append(
            "cleared %s's finished learn errand (skill %d - %s); a non-zero "
            "learn_skill makes TravelAimBook::Claim refuse EVERY travel aim "
            "for that character (mod-overseer#435), and only arriving at a "
            "trainer clears it inside the worldserver - which needs a travel "
            "aim (infra#3686)" % (row.character, row.skill, row.why)
        )
    if getattr(learn_plan, "aim", ""):
        said.append(
            "aimed %s at %s for skill %d - the errand was standing with no "
            "journey attached, which is how a derived errand is born. "
            "Arriving is not learning: TrainOnArrival buys the trade through "
            "Trainer::TeachSpell, and only character_skills settles it"
            % (learn_plan.aim, travel.describe(TRAINER_ROLE), learn_plan.skill)
        )
    waiting = tuple(getattr(learn_plan, "waiting", ()) or ())
    if waiting:
        # Named even though nothing was written for them, because a character
        # in this state is fenced out of ALL travel and the only thing that
        # moves it is the lead coming round - see learnaim.traveller. A silent
        # wait is indistinguishable from no wait at all.
        said.append(
            "%s: an errand is standing with no journey and no lead, so it "
            "waits its turn" % ", ".join(waiting)
        )
    return ". ".join(said)