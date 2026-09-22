"""What a kind='skill' goal should actually make the family do (infra#3731).

Pure module, same seam as craft_rhythm.py and professions.py: facts about one
skill and one family in, a job mode and a sentence out. Nothing here talks to
MySQL, to Discord or to the worldserver, and nothing here writes anything.

WHY THIS EXISTS, AND WHY IT IS NOT IN goals.py. `goals.strategy_for` used to
answer every goal kind with `nc +grind`, skill goals included, and its own
docstring said so out loud - "no profession-specific strategy exists to issue
instead". That was true when it was written and it stopped being true three
issues ago. The cost of it staying is exactly what the owner complained about:
"why are they fighting in tanaris instead of working on their professions like
i told you to?". A goal of "get Grug's mining to 75" issued a combat strategy,
Grug walked off and fought Wastewander Assassins in Tanaris, and the goal row
reported itself healthy the whole time because a goal that never completes and
never errors looks exactly like a goal that is merely slow.

It is a SEPARATE MODULE and not a branch inside goals.py because goals.py is
the ROOT of this service's import graph - professions.py, trainjob.py and
craft.py all import it for SKILL_IDS, so it can import none of them back. The
shape of a profession is professions.py's fact and the bracket of a recipe is
craft.py's, so the decision that needs both has to live above them. goals.py
keeps deciding WHEN to act (the lease, the milestone, the completion); this
module decides WHAT acting means for the particular skill named.

THE THREE SHAPES, AND WHY ONE STRATEGY COULD NEVER HAVE SERVED THEM. They fail
in three unrelated places and only one of them works today:

  CRAFTED   consume reagents and cast a recipe. This is the one that works,
            and it is measured working: Og's Tailoring went 1 -> 50 and Ugga's
            Alchemy 1 -> 14 under job='craft', with mod-overseer logging every
            cast ("overseer: 'Ugga' crafted 'Minor Healing Potion' (2330)").
  GATHERED  be somewhere with nodes, and pick them up. Neither half exists.
  FISHING   its own thing entirely, and nothing in the module fishes.

WHAT THIS MODULE REFUSES, IT REFUSES LOUDLY. `Plan.blocked` is a sentence and
never a bare False, for the reason `craft_supply.SupplyTrip` and
`craft_rhythm.Stand` both give for theirs: this service's dominant failure is
a mechanism that reports health while doing nothing, and a refusal nobody can
read is indistinguishable from success. A skill goal whose shape has no drive
must SAY it has no drive, every time it is asked, naming the issue that would
have to close first.
"""

from __future__ import annotations

from dataclasses import dataclass

import craft
import craft_rhythm
import goals
import professions

# ---------------------------------------------------------------------------
# THE THREE SHAPES.
#
# Derived from professions.py's own sets rather than listed again here: a
# second spelling of "mining is a gathering trade" is a second thing to get
# wrong, and the only power a second copy has is to disagree with the first.
# `test_skillgoal.py` holds the three shapes to a TOTAL PARTITION of
# goals.SKILL_IDS, so a skill added to that table without a shape here is a
# failing test rather than a goal that silently falls through to nothing.
#
# FISHING IS ITS OWN SHAPE RATHER THAN A SECONDARY, and that is the whole
# reason this is not a two-way split. First Aid and Cooking are secondaries
# that CRAFT - they consume an item and cast a create-item spell, which is
# DriveCraft's exact shape, and craft.RECIPES carries brackets for them beside
# the primaries. Fishing consumes nothing, creates nothing, and needs a pole
# and a drive that do not exist. Filing it under "secondary" would put it
# behind the crafting path's reasoning, where its real blocker (infra#3733) is
# invisible.
CRAFTED = "crafted"
GATHERED = "gathered"
FISHING = "fishing"

_FISHING_SKILL = "fishing"

# The two modes this module may ask for, read out of craft_rhythm rather than
# spelled, for the reason that module gives for reading them out of
# jobs.IMPLEMENTED in the first place: a mode name spelled twice is a mode name
# that can drift, and a mode dropped from IMPLEMENTED should be a StopIteration
# at import - which the container's own startup surfaces at once - rather than
# an order refused six hours later with the family idle in between.
MODE_CRAFT = craft_rhythm.MODE_CRAFT
MODE_GATHER = craft_rhythm.MODE_GATHER
RHYTHM_MODES = (MODE_GATHER, MODE_CRAFT)


def shape_for(skill_name: str) -> str:
    """Which of the three shapes this skill has.

    Raises KeyError for a name no profession set claims. That is deliberate and
    it is the opposite of this codebase's usual "return nothing rather than
    invent a fallback" rule, because the two situations are different: a
    profession with no recipe bracket is a real, expected, temporary state,
    while a skill NAME that no set claims means goals.SKILL_IDS and
    professions.py have drifted apart - a code fault, not a world fact. Failing
    at the point of the drift is the only way that is ever noticed.
    """
    name = (skill_name or "").strip().lower()
    if name == _FISHING_SKILL:
        return FISHING
    if name in professions.GATHERING:
        return GATHERED
    if name in professions.CRAFTING or name in professions.SECONDARY:
        return CRAFTED
    raise KeyError(
        "no profession set in professions.py claims %r, so this module has no "
        "shape for it - goals.SKILL_IDS and professions.py have drifted" % skill_name
    )


@dataclass(frozen=True)
class Plan:
    """What the family should do about one skill goal, and what it may claim.

    `mode` is the job mode to write, and '' means "write nothing" - the same
    "'' means nobody" convention craft_rhythm.Rhythm.mode and
    professions.traveller both use. '' is the COMMON answer here, not the
    exceptional one: once the family is inside the gather/craft rhythm,
    craft_rhythm owns the alternation and this module must not write over it.

    `blocked` is why this goal cannot progress at all, and it is a sentence or
    it is empty. A non-empty `blocked` is a promise that `mode` is '': there is
    no order that would help, so issuing one would be theatre.

    `stalled` is the softer half - the mechanism is right and the number is
    still not moving. It is separate from `blocked` because the two want
    different responses from a reader: `blocked` means stop waiting, `stalled`
    means look at what the drive is starved of.

    `why` is never empty, under any branch. A verdict that cannot say why is
    the silent idle this whole family of modules exists to end.
    """

    skill_name: str
    beneficiary: str
    shape: str
    mode: str = ""
    blocked: str = ""
    stalled: str = ""
    why: str = ""


# ---------------------------------------------------------------------------
# THE REFUSALS, EACH NAMING THE ISSUE THAT WOULD HAVE TO CLOSE FIRST.
#
# Written as constants rather than built inline so that a test can assert the
# exact sentence a given state produces, and so that the next person to read
# "why is my mining goal not doing anything" gets the same words in Discord,
# in the thought log and in this file.

# All three holes this refusal used to name are now closed, and the text is
# kept only for the state where nobody handed `plan` a destination to judge.
#
# (1) `nc +loot` IS granted now - measured 2026-09-19 at 2,356 issuances and
#     2,315 applied, all five characters inside two hours, source
#     `overseer:life`. infra#3769 is closed. The old sentence said it "has
#     never been issued to anybody, once", which was true when written on
#     2026-09-14 and has been false since; it printed to Discord and the
#     thought log the whole time, which is the cost of a refusal nobody
#     re-measures.
# (2) and (3) are infra#3789, which is this change: `gatherband` projects
#     Lock.dbc's per-node requirement (the world DB's `lock_dbc` is empty, so
#     it comes from the worldserver's own client data) and `gatheraim` picks
#     the zone.
GATHERING_REFUSAL = (
    "Nothing surveyed a gathering destination for this pass, so there is no "
    "zone to judge. This is not the old three-hole refusal: granting "
    "gather/loot is closed (infra#3769, measured at 2,356 issuances), the "
    "per-node band is now projected from the worldserver's own Lock.dbc "
    "because acore_world.lock_dbc is empty (gatherband), and choosing a zone "
    "is gatheraim - so a destination CAN be computed. It simply was not passed "
    "in here, which means the caller did not run the survey rather than that "
    "the family has nowhere to go (infra#3789)."
)

SMELT_CAVEAT = (
    " There IS one partial exception and it does not rescue this goal. "
    "Smelting raises Mining, craft.RECIPES carries Smelt Copper (spell 2657, "
    "skill 1-69) for it, and bridge._forge_once really does walk a smelter to "
    "the nearest spawned Forge (infra#3748) - but a smelt consumes Copper Ore, "
    "which only mining produces, so it can EXTEND a supply the family already "
    "has and can never start one. It also needs no goal: craft_rhythm.errand "
    "already chooses the smelt over the craft on its own, whenever a miner "
    "holds ore and its crafting recipe cannot run, so blocking this goal costs "
    "the smelt nothing. What a goal must not do is CLAIM the smelt - "
    "craft_rhythm.errand prefers the crafting errand whenever it can run, so a "
    "Mining goal that entered the rhythm today would in fact drive "
    "Blacksmithing or Engineering and report that as progress on Mining."
)

FISHING_REFUSAL = (
    "Fishing cannot start and no job mode changes that: nobody owns a Fishing "
    "Pole (item 6256, 23 copper, verified against acore_world.item_template) "
    "and mod-overseer has no fishing drive of any kind, so a pole would be an "
    "inert purchase - infra#3733. It is not a crafting skill either: it "
    "consumes nothing and creates nothing, so craft.RECIPES can never carry a "
    "bracket for it."
)

PRIMARY_RANK_REFUSAL = (
    "This is a CAP, not a learn, and nothing in this system can lift one. "
    "trainjob.outstanding refuses any skill the character already holds "
    "(`if skill in tuple(member.holds): return 0`), so job='train' produces no "
    "errand for a rank-up; and mod-overseer's trainer resolve cannot find a "
    "trainer for a held trade either - quadseven/mod-overseer#196. Setting a "
    "skill target above the rank cap is therefore a goal that can only park "
    "where it is."
)


def _rank_cap_refusal(skill_name: str, observed: int, cap: int, target: int) -> str:
    head = (
        "%s is at %d/%d and the goal asks for %d, so the next point needs a "
        "rank the character does not have. " % (skill_name, observed, cap, target)
    )
    if skill_name in professions.SECONDARY:
        # The secondary case is worse than the primary one and is refused by
        # different C++ entirely; professions.py holds the full three-refusal
        # argument and the measurement behind it, so it is cited rather than
        # paraphrased here.
        return head + professions.SECONDARY_RANK_REFUSAL
    return head + PRIMARY_RANK_REFUSAL


def _no_bracket_refusal(skill_name: str, skill_id: int, observed: int) -> str:
    said = (
        "craft.RECIPES has no bracket covering %s (skill %d) at value %d, so "
        "there is no recipe to stand %s on - the goal would sit on job='%s' "
        "casting nothing. A profession with no entry returns nothing rather "
        "than a made-up spell id, which is craft.recipe_for's own permission "
        "rule, and inventing a fallback here would be the wrong half of it."
        % (skill_name, skill_id, observed, skill_name, MODE_CRAFT)
    )
    extra = professions.SECONDARY_BLOCKED.get(skill_name)
    if extra:
        # A secondary's gap is never "nobody has written the table yet" - all
        # three were measured against the deployed image and each is behind a
        # different wall. Saying which one is the difference between a reader
        # filing a recipe-table issue and a reader filing the right one.
        said += " And %s earns nothing today because %s." % (skill_name, extra)
    return said


def _unassigned_refusal(beneficiary: str, skill_name: str) -> str:
    held = professions.assigned(beneficiary)
    return (
        "%s is not assigned %s - professions.assigned(%r) is %s - so no craft "
        "errand for it will ever be written. craft.craft_errand walks that "
        "assignment and nothing else for a primary trade, which is the "
        "permission rule that keeps two miners from having their crafting "
        "trades stopped dead (see craft.smelt_errand). The fix is a roster "
        "change in professions.ROSTER, not a goal."
        % (beneficiary, skill_name, beneficiary, list(held) or "empty")
    )


def _stalled_sentence(
    skill_name: str, beneficiary: str, shape: str, observed: int, stalls: int
) -> str:
    """What a goal says when the drive is right and the number is not moving.

    NOT a refusal. The mechanism named in `why` is the correct one and it is
    running; something upstream of it is starved. The sentence points at the
    pass that can see what, rather than guessing here - this module has no
    inventory counts and must not pretend otherwise, which is craft.py's own
    infra#3695 rule ("forecasting is not a weaker version of asking").
    """
    said = (
        "%s's %s has not moved off %d in %d supervision cycles. The drive is "
        "the right one and it is standing; something it needs is missing."
        % (beneficiary, skill_name, observed, stalls)
    )
    if shape == CRAFTED:
        said += (
            " For a crafting skill there are exactly TWO causes and they are "
            "told apart by one grep, so do not guess between them. (a) THE "
            "RECIPE IS REFUSED: DriveCraft drops an errand for a spell the "
            "character does not hold and logs 'does not know the recipe. "
            "Dropping it', then clears overseer_roster.craft_spell - and the "
            "planner re-writes the same id on its next cycle, so the column "
            "oscillates and NOTHING is ever cast. That is a closed loop, not "
            "slowness, and it is infra#3689. (b) REAGENTS: DriveCraft skips a "
            "character short of mats with a bare `continue` and no log line at "
            "all, so 'employed and producing nothing' looks exactly like "
            "'busy' (infra#3696); craft_rhythm's own report names every starved "
            'character by reagent. Grep the worldserver for "does not know the '
            "recipe\" against this character's name: a hit is (a) and silence "
            "is (b). This module deliberately does not decide between them - "
            "only the worldserver's own recorded answer can, which is craft.py's "
            "infra#3695 rule, and forecasting is not a weaker version of asking."
        )
    return said


def plan(
    *,
    skill_name: str,
    skill_id: int,
    target: int,
    observed: int,
    cap: int,
    beneficiary: str,
    standing: str,
    stalls: int = 0,
    destination=None,
) -> Plan:
    """The one decision: what should the family do about this skill goal.

    Every argument is a fact somebody else read, and that is the seam. `cap` is
    `character_skills.max` and 0 for "not read"; `standing` is
    `craft_rhythm.standing_mode` over the enabled roster's `job` column, '' when
    the rows disagree; `stalls` is how many consecutive supervision cycles the
    observed value has not moved for, which goals.py counts on the goal row
    because the row is the only memory a restart preserves.

    `destination` is a `gatheraim.Choice` for a GATHERED skill and None
    otherwise, and None is not the same as a refusal - see the branch.
    Passing it in rather than computing it keeps this module pure: the
    survey it comes from is a database read and a clock, and neither
    belongs behind a function whose whole value is that a test can call it.

    THE ORDER OF THE BRANCHES IS LOAD-BEARING, and each one is here because a
    later branch would give a true-but-useless answer for the same state:

      1. The rank cap outranks everything. A character sitting ON its cap with
         a target above it also has no recipe bracket (every bracket stops at
         the cap), so the bracket branch would answer "no recipe" - true, and
         it would send a reader to craft.RECIPES to add one, which is not the
         problem and cannot fix it.
      2. Fishing outranks the crafting branch because it would otherwise be
         answered as "no bracket", and a bracket is not what fishing is missing.
      3. Gathering outranks everything but the cap because its refusal is about
         the world and not about this character at all.

    WHAT IT NEVER DOES IS RETURN A COMBAT STRATEGY. That is the defect this
    module exists to close, and there is no branch below that can reach one.
    """
    shape = shape_for(skill_name)

    if cap > 0 and observed >= cap and target > cap:
        return Plan(
            skill_name=skill_name,
            beneficiary=beneficiary,
            shape=shape,
            blocked=_rank_cap_refusal(skill_name, observed, cap, target),
            why="%s is capped at %d and the goal wants %d; no order helps."
            % (skill_name, cap, target),
        )

    if shape == FISHING:
        return Plan(
            skill_name=skill_name,
            beneficiary=beneficiary,
            shape=shape,
            blocked=FISHING_REFUSAL,
            why="fishing has no drive in this system at all.",
        )

    if shape == GATHERED:
        # infra#3789. A gathering goal is answerable now, and what decides it
        # is whether the caller surveyed somewhere to stand. `destination` is a
        # `gatheraim.Choice` or None, and the three states are kept apart on
        # purpose: None means nobody looked, `refused` means somebody looked
        # and the world said no, and `chosen` means go. Collapsing the first
        # two is how the old refusal came to claim something false for five
        # days.
        if destination is None:
            refusal = GATHERING_REFUSAL
            if craft.recipe_for(skill_id, observed) is not None:
                # Mining, below 69. The bracket is real and the forge walk that
                # honours it is real, so saying "no mechanism exists" flat
                # would be a refusal a reader can disprove in one grep - and a
                # refusal that can be disproved is one nobody trusts the next
                # time.
                refusal += SMELT_CAVEAT
            return Plan(
                skill_name=skill_name,
                beneficiary=beneficiary,
                shape=shape,
                blocked=refusal,
                why="no destination was surveyed for %s this pass." % skill_name,
            )

        if getattr(destination, "refused", ""):
            return Plan(
                skill_name=skill_name,
                beneficiary=beneficiary,
                shape=shape,
                blocked=destination.refused,
                why=getattr(destination, "why", "")
                or "the world offers nowhere to raise %s." % skill_name,
            )

        # A real field, on this map, inside the band, past the level guard.
        # MODE_GATHER is craft_rhythm's own constant and job='quest' IS that
        # mode - writing anything else here would read to mod_overseer.cpp as
        # "the quest drive stands down, full stop".
        got = destination.chosen
        return Plan(
            skill_name=skill_name,
            beneficiary=beneficiary,
            shape=shape,
            mode=MODE_GATHER,
            why="zone %d on map %d holds %d %s node(s) the weakest gatherer "
            "can open; aiming the family at a surveyed spawn there."
            % (got.zone_id, got.map_id, got.nodes, got.skill_name),
        )

    # --- CRAFTED from here down ------------------------------------------
    if skill_name not in professions.SECONDARY:
        if skill_name not in professions.assigned(beneficiary):
            return Plan(
                skill_name=skill_name,
                beneficiary=beneficiary,
                shape=shape,
                blocked=_unassigned_refusal(beneficiary, skill_name),
                why="%s holds no assignment for %s." % (beneficiary, skill_name),
            )

    recipe = craft.recipe_for(skill_id, observed)
    if recipe is None:
        return Plan(
            skill_name=skill_name,
            beneficiary=beneficiary,
            shape=shape,
            blocked=_no_bracket_refusal(skill_name, skill_id, observed),
            why="no craft.RECIPES bracket covers %s at %d." % (skill_name, observed),
        )

    stalled = ""
    if stalls >= goals.SKILL_BARREN_CYCLES:
        stalled = _stalled_sentence(skill_name, beneficiary, shape, observed, stalls)

    # THE HANDOVER, AND IT IS THE WHOLE REASON THIS RETURNS '' SO OFTEN.
    #
    # There must be exactly ONE writer for the gather/craft alternation, and it
    # is craft_rhythm - it is the pass that can see held reagent counts, and its
    # whole argument for when to flip is built on those counts drifting in one
    # direction only. A goal that re-asserted job='craft' on its own lease would
    # be a second opinion about the same column, arriving on a different clock
    # (60s here against 300s there), and the two would take turns undoing each
    # other while the family stood at a counter.
    #
    # So this module's authority stops at the DOOR. If the family is already
    # inside the rhythm it says nothing and craft_rhythm decides; if they are
    # outside it - on `dungeon`, on `train`, on a mode an operator typed - it
    # asks for the crafting half, which is the mode that actually casts, and
    # hands over from the next pass onward. That is a threshold consulted only
    # as an ENTRY to a mode this goal is not in, which is the same discipline
    # craft_rhythm's own SHORT_CASTS/STOCK_CASTS comment derives for its exits.
    if not standing:
        # '' from standing_mode is "the rows do not agree", which is a fan-out
        # still settling. Writing into a half-landed order is how a family ends
        # up split across two modes; asking again next cycle costs one minute.
        return Plan(
            skill_name=skill_name,
            beneficiary=beneficiary,
            shape=shape,
            stalled=stalled,
            why="the family's job column does not agree yet, so nothing is "
            "written this cycle - %s would cast spell %d (%s) once they do."
            % (beneficiary, recipe.spell_id, recipe.name),
        )

    if standing in RHYTHM_MODES:
        return Plan(
            skill_name=skill_name,
            beneficiary=beneficiary,
            shape=shape,
            stalled=stalled,
            why="the family is already inside the profession rhythm (job=%s), "
            "so craft_rhythm owns the alternation from here - %s's bracket "
            "for %s %d is spell %d (%s)."
            % (
                standing,
                beneficiary,
                skill_name,
                observed,
                recipe.spell_id,
                recipe.name,
            ),
        )

    return Plan(
        skill_name=skill_name,
        beneficiary=beneficiary,
        shape=shape,
        mode=MODE_CRAFT,
        stalled=stalled,
        why="the family is on job=%s, which is outside the profession rhythm, "
        "so nothing would ever cast %s's bracket for %s %d (spell %d, %s) "
        "- asking for job=%s is what lets craft_rhythm take over next pass."
        % (
            standing,
            beneficiary,
            skill_name,
            observed,
            recipe.spell_id,
            recipe.name,
            MODE_CRAFT,
        ),
    )


def report(skill_plan: Plan) -> str:
    """One line for the log, saying what was decided and what it means.

    Logged on EVERY pass, decided or not, for the reason craft_rhythm.report
    gives for its own: the state this module most often reports is "nothing
    written", and a pass that only speaks when it acts is indistinguishable
    from a pass that has died.
    """
    head = "skill goal %s for %s (%s)" % (
        skill_plan.skill_name,
        skill_plan.beneficiary,
        skill_plan.shape,
    )
    if skill_plan.blocked:
        return "%s: BLOCKED - %s" % (head, skill_plan.blocked)
    wrote = (
        ("asked for job=%s" % skill_plan.mode) if skill_plan.mode else "wrote nothing"
    )
    said = "%s: %s - %s" % (head, wrote, skill_plan.why)
    if skill_plan.stalled:
        said += " STALLED: %s" % skill_plan.stalled
    return said
