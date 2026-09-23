"""Which crafting material should move from whose bags to whose (infra#2830).

Pure module, same seam as questshare.py and professions.py: facts in, a plan
out. bridge.py reads `character_inventory` joined against
`acore_world.item_template` (the same join shape `_QUEST_SQL`'s item lookups
already use), builds one Holding per item stack, calls `plan()`, and turns
each Grant into one `overseer_command` row with `kind='give'`. mod-overseer's
`DoGive` performs the actual transfer.

WHY THIS EXISTS. Measured live 2026-08-24 against `character_inventory`, with
every bag at 100% full (#2813):

    holder  has                                            relevant to
    Bork    Linen Cloth x19, Silverleaf x19, Bolt x2        tailoring
    Ugga    Linen Cloth x13, Silverleaf x18, Bolt x1        tailoring
    Og      Linen Cloth x15, Silverleaf x13, Peacebloom x7  tailoring/alchemy
    Grog    Linen Cloth x18                                 tailoring
    Grug    Linen Cloth x19, Silver Ore x2, Malachite x4    tailoring/smithing

84 Linen Cloth, spread across five characters, and - per professions.ROSTER,
infra#2757 - exactly one of them (Og) is actually assigned tailoring. Nobody
had a way to move a stack from one character's bags into another's as part of
a plan; #2793 gave the family quest SHARING, and this is the equivalent for
STUFF.

WHY kind='give' AND NOT NEW C++. infra#2597 already built a real item
transfer between two living characters - `guid:<item_instance.guid>` or
`entry:<id>` in, one `CharacterDatabase` transaction, both inventories
updated - to solve the Severing Axe problem (a loot roll hands a two-hander to
a priest). #2830 is the same mechanism aimed at a different noun: reagents
instead of gear. `DoGive` does not know or care why an item is moving, so this
module supplies only the WHO and the WHAT; `tests/test_give.py` already proves
the HOW - the atomic move, the five distinguishable refusals, the widened
ENUM - and none of that needs re-proving here.

WHAT THIS DECIDES AND WHAT IT DOES NOT. This module answers "whose bags should
this stack end up in", never "should this stack exist" - the item is already
real and already sitting in somebody's inventory. REAGENTS below is read-only
domain knowledge (which profession consumes which material), the same shape
as professions.ARMOUR and professions.CRAFT_ARMOUR: a short, named table
rather than a derivation, because the correctness here is Evan's own
observation of what is actually in these bags, not a rule that could
reverse-engineer it. Deliberately small: a material not listed is left alone
rather than guessed at, exactly as craftpleas.PRODUCTS (#2829) leaves an
unlisted product unanswered rather than inventing an opinion.

WHAT IS STILL UNVERIFIED. Every fact in REAGENTS and every line of bridge.py's
SQL that reads `character_inventory` was written with `wow-dev` mid-RAM-swap
and unreachable - so none of it has been watched moving a real item. This
module's tests are unit tests against synthetic Holdings; they prove the
DECISION is right for the inputs given, not that the SQL that will produce
those inputs is. Say so plainly rather than implying otherwise, per this
service's own hard-won rule about `delivered` meaning nothing was verified.

WHAT INFRA#3197 CHANGED, AND WHY THE WORDS MOVED OUT OF THE DECISION. What
Evan watched on stream was this, twice per character, minutes apart:

    [Party] [Grog]: Grog give Og 20 Linen Cloth. Og need it for tailoring.
    [Party] [Grog]: Grog give Og 19 Linen Cloth. Og need it for tailoring.

Three things wrong with it, and only the third is about this module's
decision. The stack COUNT drifted because Grog is carrying two stacks and
this module correctly plans one give per `item_instance.guid` - two moves,
which the world needs, but one thing to SAY, which is what `handovers` now
collapses them into. The claim "Og need it for tailoring" was false: Og does
not have tailoring and `character_skills` has never said he does, so the
spoken line is now built from the live skills and drops the claim when there
is no claim to make. And the whole exchange repeated for hours because every
one of those gives came back `status='error'`, `detail="receiver bags are
full"` - see `stuck`, and mod-overseer#169 for the underlying refusal, which
is not fixed here. A plan that cannot land must say so once and stop, which
is a different thing from a plan nobody has answered yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import chat
import handover
import professions

# Which profession consumes which material, restricted to what infra#2830
# actually measured in the family's bags. Keyed on the item's NAME because
# that is what `character_inventory` joined to `acore_world.item_template`
# gives back - not a hardcoded item entry id, which this repo has nowhere
# else needed and which cannot be checked against a live server right now
# (see the module docstring).
REAGENTS = {
    "Linen Cloth": "tailoring",
    "Bolt of Linen Cloth": "tailoring",
    "Silverleaf": "alchemy",
    "Peacebloom": "alchemy",
    "Silver Ore": "blacksmithing",
    "Malachite": "jewelcrafting",
}


@dataclass(frozen=True)
class Holding:
    """One item stack, in one character's bags, right now.

    ONE ROW PER `item_instance.guid`. A stack split across two bag slots
    because it never fully merged is two Holdings, not one merged count -
    `DoGive` moves a single guid, and cannot address "19 Linen Cloth,
    wherever it happens to sit."
    """

    holder: str
    material: str
    count: int
    guid: int


@dataclass(frozen=True)
class Grant:
    """One stack, moving from one family member's bags into another's.

    NO `said` FIELD, DELIBERATELY. A Grant is one guid moving, and a guid is
    not a sentence: Grog carrying two stacks of Linen Cloth is two Grants and
    ONE thing to say. What gets spoken is a Handover, built by `handovers`
    from however many Grants share an intent.
    """

    holder: str
    taker: str
    material: str
    count: int
    guid: int
    skill: str
    reason: str

    @property
    def command(self) -> str:
        """What mod-overseer's DoGive parses out of `overseer_command.command`."""
        return "guid:%d" % int(self.guid)


@dataclass(frozen=True)
class Handover:
    """One thing said, however many stacks it takes to do it.

    `count` is every stack in this intent added together, so the line reads
    "Grug give Og 39 Linen Cloth" instead of 20 and then 19 - which is what
    the family is actually doing, and the reason a viewer read the pair as a
    loop re-announcing itself rather than as two bags being handed over.
    """

    holder: str
    taker: str
    material: str
    skill: str
    count: int
    guids: tuple
    said: str

    @property
    def key(self) -> tuple:
        """The say-it-once key: who hands what to whom, never the wording."""
        return chat.say_key(
            speaker=self.holder, subject=self.material, listener=self.taker
        )


@dataclass(frozen=True)
class Blocked:
    """A handover the world keeps refusing, said once and then dropped.

    Distinct from a Grant that has simply not happened yet, and the
    distinction is the whole point (mod-overseer#169): four give commands sat
    at `status='error'`, `detail="receiver bags are full"` and were re-issued
    every cycle for six hours, each one re-announced in party chat. A family
    that says "Og bags full" once and stops is telling the truth; one that
    asks again every ten minutes is a loop.
    """

    holder: str
    taker: str
    material: str
    skill: str
    refusal: str
    said: str

    @property
    def key(self) -> tuple:
        return chat.say_key(
            speaker=self.holder, subject="stuck:" + self.material, listener=self.taker
        )


@dataclass(frozen=True)
class Attempt:
    """One `overseer_command` give row that has already been tried."""

    holder: str
    taker: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class Plan:
    grants: tuple = ()
    # Materials REAGENTS names but that professions.ROSTER assigns to nobody -
    # costs no give command, said rather than silently skipped, same reason
    # professions._notes exists.
    notes: tuple = ()
    # Handovers this pass will NOT propose because the world has refused them
    # enough times to be believed. See Blocked.
    blocked: tuple = ()


def crafter_for(material: str) -> str:
    """Who should end up holding this material, or '' if this module has no
    opinion (not in REAGENTS, or REAGENTS names a skill nobody is assigned)."""
    skill = REAGENTS.get(material, "")
    if not skill:
        return ""
    return professions.crafter_for(skill)


# How many refusals it takes before the family believes the world. Three,
# because one is a bad moment (the taker was mid-loot) and two is bad luck;
# the live rows sat at SEVEN identical refusals over six hours, which is
# nobody's bad luck. Read from the environment nowhere: this is a decision
# about when to stop asking, and it belongs in the module a test can hold.
GIVE_UP_AFTER = 3


# What a refusal reads as when the world gave one and said nothing about it.
# Named because it is a SENTENCE the family repeats out loud, and a sentence
# that appears in two places is a sentence that gets edited in one of them.
NO_REASON_GIVEN = "the world refused it, and said nothing about why"


def refusal_counts(attempts) -> dict:
    """(holder, taker) -> (how many refusals running, what the world said).

    Only `status='error'` counts. A pending give is one nobody has answered
    yet and must not be mistaken for a refusal - that is exactly the
    distinction mod-overseer#169 asks for - and a delivered one is not a
    failure at all, so a pair that has ever succeeded starts again from zero.

    EVERY refused pair, however few times, which is the difference between
    this and `stuck`. The family only ever acts on the ones past the
    threshold, but a view showing "1 of 3" is showing a person the thing that
    is about to happen rather than announcing it after the fact.
    """
    counts: dict = {}
    refusals: dict = {}
    for attempt in attempts:
        pair = (
            (attempt.holder or "").strip(),
            (attempt.taker or "").strip(),
        )
        status = (attempt.status or "").strip().lower()
        if status == "delivered":
            counts[pair] = 0
            continue
        if status != "error":
            continue
        # The module's distance wall (#189) is about where two characters
        # stood for one second, not about the pair: it neither counts toward
        # giving up nor clears a count, and the pass waits for them to meet.
        if handover.is_range_refusal(attempt.detail):
            continue
        counts[pair] = counts.get(pair, 0) + 1
        detail = (attempt.detail or "").strip()
        if detail:
            refusals[pair] = detail
    return {
        pair: (seen, refusals.get(pair, NO_REASON_GIVEN))
        for pair, seen in counts.items()
    }


def stuck(attempts, *, threshold: int = GIVE_UP_AFTER) -> dict:
    """(holder, taker) -> the refusal the world keeps giving back.

    `refusal_counts` with the threshold applied: the pairs the family has
    stopped asking about. Kept as its own name because that is what the
    bridge asks for, and because "refused once" and "refused enough times to
    be believed" are two different facts that must not share a spelling.
    """
    return {
        pair: reason
        for pair, (seen, reason) in refusal_counts(attempts).items()
        if seen >= threshold
    }


def retryable_stuck(stuck_pairs: Mapping, free_slots: Mapping) -> dict:
    """Release a stopped handover when its receiver has room again.

    A full receiver is a temporary world state, not a permanent decision
    about who should own a profession reagent. The bridge supplies current
    free-slot facts; this pure seam decides which old refusals can re-enter
    the normal plan. Unknown capacity stays blocked, so a failed read never
    turns into a noisy retry storm.
    """
    return {
        pair: reason
        for pair, reason in stuck_pairs.items()
        if int(free_slots.get(pair[1], 0) or 0) <= 0
    }


def _said_for(
    holder: str, taker: str, material: str, count: int, skill: str, held: Mapping
) -> str:
    """The handover, said in a way that is true whoever is carrying it.

    THE SKILL IS ONLY NAMED WHEN THE SKILL EXISTS. "Og need it for tailoring"
    read as a fact about Og and was not one; it was a fact about ROSTER. So
    the trade in hand explains the handover, a trade the family has only
    decided on is said as the plan it is, and a trade nobody is getting is
    not mentioned - the stack still moves, because the ROSTER decision is
    what makes it the right bag, and the sentence simply stops short of a
    claim it cannot support.
    """
    head = f"{holder} give {taker} {count} {material}."
    how = chat.skill_state(
        taker, skill, held=held, planned={taker: professions.assigned(taker)}
    )
    if how == chat.HELD:
        return f"{head} {taker} need it for {skill}."
    if how == chat.LEARNING:
        return f"{head} {taker} learning {skill}."
    return head


def family_crafters(skills_by_name: Mapping) -> dict:
    """skill -> the member who holds it, highest value first, then by name.

    For a family `professions.ROSTER` does not name (#215): the trade a
    reagent feeds belongs to whoever has learned it, since that is the only
    character who can cast with it.
    """
    out: dict = {}
    best: dict = {}
    for name in sorted(skills_by_name):
        for skill, value in (skills_by_name.get(name) or {}).items():
            if skill not in professions.CRAFTING or not value:
                continue
            if int(value) > best.get(skill, 0):
                best[skill] = int(value)
                out[skill] = name
    return out


def plan(
    holdings, *, stuck_pairs: Mapping | None = None, crafters: Mapping | None = None
) -> Plan:
    """Every stack that should move, in one pass.

    Deterministic: the same holdings in produce the same grants in the same
    order, sorted by (holder, material, guid) - so a re-run against unchanged
    bags proposes an identical plan and bridge.py's dedupe (the `give` sibling
    of `_recent_share_keys`) sees the same key twice rather than a shuffled
    one that never matches.

    NO LIVE SKILLS ARE NEEDED HERE, and that is a statement about the
    decision: whose bags a reagent belongs in is ROSTER's answer and does not
    depend on anybody having learned anything yet. Only the WORDS need to
    know what a character can actually do, which is why `handovers` takes the
    skills and this does not.

    `stuck_pairs` is `stuck()`'s answer: those pairs produce a Blocked instead
    of a Grant, so a doomed give is proposed no further.

    `crafters` maps a skill to the member who works it, for a family ROSTER
    does not name (#215); `family_crafters` builds it from what they hold.
    None keeps ROSTER's answer for this bridge's own family.
    """
    refused = stuck_pairs or {}
    grants = []
    notes = []
    blocked = []
    seen_blocks = set()
    for holding in sorted(holdings, key=lambda h: (h.holder, h.material, h.guid)):
        skill = REAGENTS.get(holding.material, "")
        if not skill:
            continue
        if crafters is None:
            taker = professions.crafter_for(skill)
        else:
            taker = str(crafters.get(skill) or "")
        if not taker:
            note = (
                f"{holding.material} feeds {skill}, and nobody is assigned "
                f"{skill} - see professions.UNASSIGNED."
            )
            if note not in notes:
                notes.append(note)
            continue
        if taker == holding.holder:
            # Already in the right hands. Not a note - this is the common,
            # boring, correct case and saying it every pass would drown the
            # notes that are actually asking for something.
            continue
        refusal = refused.get((holding.holder, taker))
        if refusal:
            mark = (holding.holder, taker, holding.material)
            if mark not in seen_blocks:
                seen_blocks.add(mark)
                blocked.append(
                    Blocked(
                        holder=holding.holder,
                        taker=taker,
                        material=holding.material,
                        skill=skill,
                        refusal=refusal,
                        said=(
                            f"{holding.holder} no give {taker} {holding.material} - "
                            f"{refusal}. {holding.holder} wait."
                        ),
                    )
                )
            continue
        grants.append(
            Grant(
                holder=holding.holder,
                taker=taker,
                material=holding.material,
                count=holding.count,
                guid=holding.guid,
                skill=skill,
                reason=(
                    f"{holding.holder} holds {holding.count} {holding.material}, "
                    f"which feeds {skill}, and {taker} is the family's assigned "
                    f"{skill}. {holding.holder} is not assigned {skill}, so the "
                    f"stack does {holding.holder} no good where it sits."
                ),
            )
        )
    return Plan(
        grants=tuple(grants),
        notes=tuple(notes),
        blocked=tuple(blocked),
    )


def handovers(grants, *, held: Mapping | None = None) -> tuple:
    """One thing to say per (holder, taker, material), however many stacks.

    THIS IS WHERE THE DOUBLE LINE DIED. Two stacks of Linen Cloth in Grug's
    bags are two guids and two give commands, because DoGive moves one guid;
    they were also two announcements, one saying 20 and one saying 19, which
    is what made the family read as a loop re-evaluating rather than a person
    handing something over. Merging them here rather than in `plan` keeps the
    world's half exact - both stacks still move - while the family says the
    one true sentence about it.

    Order follows the grants, so the same plan speaks in the same order.
    """
    order: list = []
    merged: dict = {}
    for grant in grants:
        key = (grant.holder, grant.taker, grant.material)
        if key not in merged:
            order.append(key)
            merged[key] = [grant.skill, 0, []]
        merged[key][1] += int(grant.count)
        merged[key][2].append(int(grant.guid))

    live = held or {}
    spoken = []
    for holder, taker, material in order:
        skill, count, guids = merged[(holder, taker, material)]
        spoken.append(
            Handover(
                holder=holder,
                taker=taker,
                material=material,
                skill=skill,
                count=count,
                guids=tuple(guids),
                said=_said_for(holder, taker, material, count, skill, live),
            )
        )
    return tuple(spoken)


def lines(material_plan: Plan, *, held: Mapping | None = None) -> list:
    """The family saying it, "Name: words" - the shape professions.lines and
    kin's muster report already speak in, so a handoff is a line in party
    chat and never a silent database write (#2830: "The request should be
    legible in party chat, not silent").

    One line per handover, and one per handover the world has refused: a
    family that has given up on a transfer says so rather than going quiet,
    which is the difference between reading the room and hiding a failure.
    """
    spoken = [
        f"{h.holder}: {h.said}" for h in handovers(material_plan.grants, held=held)
    ]
    spoken += [f"{b.holder}: {b.said}" for b in material_plan.blocked]
    return spoken


# --- WHAT WANTS TO MOVE, AS SOMETHING TO LOOK AT (infra#2597) --------------
#
# The functions above are what the bridge calls: they decide what moves and
# what gets said in party chat. This is the same answer shaped for a person
# LOOKING at the family rather than listening to it, and it exists here rather
# than in the page for the reason infra#2597 states in one line: a status
# word, a threshold and a sentence are judgement, and judgement belongs in a
# module the stdlib suite can import with no database and no browser.
#
# It is deliberately a READ. Nothing here inserts a command, and nothing here
# decides anything `plan` has not already decided - a view that could change
# what the family does by being looked at is a view nobody can trust.

# The status word a row carries. `GAVE UP AFTER n` is built from the threshold
# rather than typed, so it cannot go on claiming three the day somebody
# changes GIVE_UP_AFTER.
MOVING = "WANTS TO MOVE"


def gave_up_word(threshold: int = GIVE_UP_AFTER) -> str:
    return "GAVE UP AFTER %d" % threshold


@dataclass(frozen=True)
class Move:
    """One row of "what wants to move": a handover, or one given up on."""

    holder: str
    taker: str
    material: str
    skill: str
    # Every stack in this intent added together - the same merge `handovers`
    # does, and for the same reason: two stacks of linen are two guids the
    # world moves separately and ONE thing a person reads.
    count: int
    # What the family says about it, from `_said_for` for a live handover and
    # from `Blocked.said` for one that has been given up on. The exact
    # sentence, not a paraphrase: a view that reworded it would be showing
    # something nobody ever said.
    said: str
    word: str
    blocked: bool
    # How many times running the world has refused this pair, and its own
    # words for why. Zero and "" for a handover nobody has refused yet.
    refusals: int
    refusal: str

    @property
    def key(self) -> str:
        """A stable id for one row, so a view reuses it rather than rebuilding
        it. Not `Handover.key`, which is the say-it-once key and is a tuple."""
        return "%s>%s>%s" % (self.holder, self.taker, self.material)

    @property
    def title(self) -> str:
        """Who is handing what to whom, over the sentence they say about it.

        A blocked row can have a count of zero - the stack it was about is no
        longer in those bags - and "0 Linen Cloth" would read as a bug rather
        than as the honest "we do not know how much any more". So the count is
        dropped when there is none rather than printed as nothing.
        """
        if not self.count:
            return "%s to %s: %s" % (self.holder, self.taker, self.material)
        return "%s to %s: %d %s" % (self.holder, self.taker, self.count, self.material)

    @property
    def refusal_line(self) -> str:
        """What the world said, and how many times running it said it.

        Empty for a handover nobody has refused: a row that printed "refused 0
        times" about a give that is simply waiting would turn every plan into
        a failure report.
        """
        if not self.blocked and not self.refusals:
            return ""
        return "refused %d time%s: %s" % (
            self.refusals,
            "" if self.refusals == 1 else "s",
            self.refusal or NO_REASON_GIVEN,
        )


def giving_up_rule(threshold: int = GIVE_UP_AFTER) -> str:
    """The rule, said once under the rows instead of on every one.

    This sentence is the whole point of the section. Four gives sat at
    `status='error'`, `detail="receiver bags are full"` and were re-issued and
    re-announced every cycle for six hours (mod-overseer#169); a family that
    says it once and stops is telling the truth, and a reader has to be told
    that the silence afterwards is the rule working rather than the page
    losing the row.
    """
    return (
        "After %d identical refusals the family stops asking, so this is said "
        "once and then dropped rather than re-announced every cycle. A give "
        "nobody has answered yet is not a refusal and keeps its place in the "
        "plan." % threshold
    )


def _headline(rows: tuple, threshold: int) -> str:
    """The one line over the rows. Says nothing rather than inventing a
    finding when there is nothing to move."""
    if not rows:
        return (
            "nothing wants to move - every reagent this family carries is "
            "already in the bags of whoever is assigned it"
        )
    waiting = sum(1 for r in rows if not r.blocked)
    stopped = sum(1 for r in rows if r.blocked)
    bits = []
    if waiting:
        bits.append("%d handover%s waiting" % (waiting, "" if waiting == 1 else "s"))
    if stopped:
        bits.append("%d given up on after %d refusals each" % (stopped, threshold))
    return "  -  ".join(bits)


def board(
    holdings,
    *,
    attempts=(),
    held: Mapping | None = None,
    threshold: int = GIVE_UP_AFTER,
) -> dict:
    """Everything the "what wants to move" section draws, in one call.

    `holdings` are the same Holdings the bridge plans on and `attempts` the
    same give rows it judges refusals from, so this view and the family cannot
    disagree about what is happening - they are one decision read twice, which
    is the same discipline `family.build_family` follows by carrying the watch
    wall on the payload the cards are drawn from.

    A blocked row carries the COUNT as well, looked up from the holdings: "Og
    bags full" is worth reading, and "39 Linen Cloth is stuck in Grug's bags
    because Og bags full" is worth acting on.
    """
    counts = refusal_counts(attempts)
    refused = {
        pair: reason for pair, (seen, reason) in counts.items() if seen >= threshold
    }
    material_plan = plan(holdings, stuck_pairs=refused)

    carried: dict = {}
    for holding in holdings:
        carried[(holding.holder, holding.material)] = carried.get(
            (holding.holder, holding.material), 0
        ) + int(holding.count)

    rows = [
        Move(
            holder=hand.holder,
            taker=hand.taker,
            material=hand.material,
            skill=hand.skill,
            count=hand.count,
            said=hand.said,
            word=MOVING,
            blocked=False,
            refusals=counts.get((hand.holder, hand.taker), (0, ""))[0],
            refusal="",
        )
        for hand in handovers(material_plan.grants, held=held)
    ]
    rows += [
        Move(
            holder=stop.holder,
            taker=stop.taker,
            material=stop.material,
            skill=stop.skill,
            count=carried.get((stop.holder, stop.material), 0),
            said=stop.said,
            word=gave_up_word(threshold),
            blocked=True,
            refusals=counts.get((stop.holder, stop.taker), (threshold, ""))[0],
            refusal=stop.refusal,
        )
        for stop in material_plan.blocked
    ]
    rows = tuple(rows)
    return {
        "rows": rows,
        "notes": material_plan.notes,
        "give_up_after": threshold,
        "rule": giving_up_rule(threshold),
        "headline": _headline(rows, threshold),
    }
