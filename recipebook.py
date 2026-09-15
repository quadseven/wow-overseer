"""Which recipe a character can learn off an item, and which one to buy.

WHAT THIS IS FOR. A crafting recipe reaches a character by one of two unrelated
routes, and until now neither was drivable:

  A TRAINER TEACHES IT.  Blocked, and NOT what this module is about.
                         mod-overseer's TrainerSpellForSkill returns only a
                         skill's RANK spells (Apprentice, Journeyman, ...) and
                         never the recipes a trainer also sells, so nothing on
                         that route can be bought at all (infra#3792).

  AN ITEM TEACHES IT.    A Pattern, Formula, Manual, Recipe, Plans, Schematic
                         or Design - every one of them item_template.class 9 -
                         is USED, and using it teaches the recipe and destroys
                         the item. Those items drop, and vendors and the
                         auction house sell them.

This module is the second route. It decides two things and grants nothing:

  1. WHICH RECIPE ALREADY IN THE BAGS IS WORTH USING. This is the half that
     costs nothing: the family was measured holding 43 unlearned class-9 items
     on 2026-09-14 (18, 13, 5, 5 and 2), every one of them looted and never
     opened - and, on the same day, not one of them usable. See the skill wall
     below: that is what makes this a measurement worth keeping rather than a
     backlog to work through.
  2. WHICH RECIPE ON THE AUCTION HOUSE IS WORTH BUYING, given what the
     character's trades are and how far along they are.

THE MECHANISM IT CALLS, so the refusals below are not invented. mod-overseer's
`use` verb (mod-overseer#467) drives Player::CastItemUseSpell on a carried
class-9 item. It rides on kind='cast' rather than a kind of its own - a cast row
begins with a spell id, which is digits, and a learn row begins with the word
`use` - so no ENUM migration stands between this pass and a world.

WHY THE `ALREADY KNOWN` QUESTION IS NOT ASKED HERE, and this is the single most
important rule in this file. `character_spell` CANNOT answer it.
Player::_SaveSpells writes only spells whose state is not UNCHANGED, so a recipe
granted to a playerbot at runtime never reaches that table at all - craft.py's
infra#3695 header has the measurement, with two spells watched being cast while
zero rows existed for them. A pass that filtered on `character_spell` here would
be wrong in the expensive direction: it would conclude "not known" about a
recipe the character has, send the row, and the core would destroy the item
teaching it a second time, because nothing in the core asks that question either
(Spell::TakeCastItem destroys the item whether or not anything was learned).

SO THE WORLDSERVER IS ASKED, AND ITS ANSWER IS CONSUMED. The `use` verb refuses
`the character already knows that recipe` BEFORE it sends anything, against
Player::HasSpell, and that refusal lands in overseer_command.detail with
retry=never. This module reads those refusals back and never re-asks - which is
the same "consume the worldserver's OWN recorded answer rather than forecasting
it" discipline craft.py states at length and for the same reason.

THE OTHER REFUSAL THAT MATTERS IS THE SKILL WALL, and it is the reason the
shopping half exists at all rather than buying whatever is listed.
Player::CanUseItem refuses an item whose RequiredSkillRank is above the
character's own value in RequiredSkill. Measured on 2026-09-14: of the 72
class-9 items listed on the family's own auction house, exactly two were within
reach of anybody in it, because the lowest Plans on offer wants Blacksmithing 60
against a smith at 1, and the lowest Pattern wants Leatherworking 150 against a
leatherworker at 1. Buying by profession alone would have spent gold on a wall.

NOTHING HERE READS A DATABASE. Rows in, decisions out, the same seam auction.py
and craft_supply.py keep.
"""
from __future__ import annotations

from dataclasses import dataclass

import auction

# ---------------------------------------------------------------------------
# THE COMMAND GRAMMAR. Rendered rather than spelled at the call site, the same
# reasoning auction.buy_command and guildbank.format_item_deposit both give:
# the parser on the other side is strict (the literal word `use`, then exactly
# one `guid:` or `entry:` whose value is decimal digits and not zero, and no
# other word at all), and a second spelling is a second thing to get wrong.
# tests/test_recipebook.py reads ParseLearnRequest's own source text and asserts
# this rendering is what it accepts.

# IT RIDES ON kind='cast', WHICH IS NOT A TYPO. A new `kind` value is an ENUM
# migration in mod-overseer's data/sql, which reaches a world only when
# db-import runs - a different clock from the module image, and one more thing
# to be behind (see bridge._insert_share's own note on that skew). The two
# grammars cannot collide: OverseerDecisions::IsLearnRow routes on the exact
# word `use`, and a cast row begins with digits.
LEARN_KIND = "cast"

# The `source` column value, which is also what the dedupe window keys on. Its
# own word rather than 'auction' or 'towntrip', so a row this pass wrote can be
# told from one the reagent shopper wrote at the same counter.
LEARN_SOURCE = "recipebook"

# item_template.class for a Pattern, Formula, Manual, Recipe, Plans, Schematic
# or Design. Named here rather than written as a bare 9 in a WHERE clause, the
# same way bridge.NPC_FLAG_AUCTIONEER is named: it is a fact about the game.
RECIPE_ITEM_CLASS = 9

# The most this pass will spend in one cycle, across everybody. The same shape
# of number auction.SPEND_CAP_COPPER is and deliberately smaller: a reagent is
# consumed and rebought forever, while a recipe is bought once and kept, so a
# pass that runs away here is buying things nobody asked for rather than
# over-stocking something they did.
SPEND_CAP_COPPER = 20_000

# The most this pass will pay for one recipe. A class-9 item that is listed far
# above what the rest of the market wants is somebody's mistake or somebody's
# scheme, and either way it is not worth a purse this family has to grind back.
PER_RECIPE_CAP_COPPER = 10_000

# Free bag slots a character must still have AFTER a purchase. A recipe bought
# into the last slot blocks the next loot, and the bag passes then spend a cycle
# undoing it.
SLOTS_KEPT_FREE = 1


def use_command(*, item_guid: int | None = None, entry: int | None = None) -> str:
    """The `use guid:<n>` or `use entry:<n>` text ParseLearnRequest accepts.

    EXACTLY ONE OF THE TWO, and refused rather than resolved when both or
    neither is given: `ParseLearnRequest` takes exactly two words and refuses a
    third, so a row carrying both could only ever be refused as malformed, and
    a row carrying neither names no item at all.

    GUID IS THE FORM THIS PASS USES for something already in the bags, because
    it names exactly one row an operator can read back out of
    character_inventory. `entry` exists for the case where the item does not
    exist yet - a recipe that is about to be bought - and for an operator
    driving this by hand.

    Refuses a non-positive number rather than rendering one, the same way
    auction.buy_command refuses a zero auction id: `ParseLearnRequest` rejects
    zero by name, so writing one would be a row whose only possible answer is a
    refusal.
    """
    if (item_guid is None) == (entry is None):
        raise ValueError("use_command takes exactly one of item_guid or entry")
    if item_guid is not None:
        if not isinstance(item_guid, int) or isinstance(item_guid, bool) or item_guid <= 0:
            raise ValueError("item guid must be a positive integer")
        return f"use guid:{item_guid}"
    if not isinstance(entry, int) or isinstance(entry, bool) or entry <= 0:
        raise ValueError("item entry must be a positive integer")
    return f"use entry:{entry}"


@dataclass(frozen=True)
class Held:
    """One class-9 item sitting in one character's bags.

    `recipe_spell` is item_template.spellid_2, which is what the item teaches.
    It is carried for the log and for the report and is deliberately NOT used to
    decide anything: this module cannot tell whether a character knows a spell
    (see the header), so knowing the id buys it nothing a decision could rest
    on.
    """

    holder: str
    item_guid: int
    entry: int
    label: str
    required_skill: int
    required_rank: int
    recipe_spell: int = 0


@dataclass(frozen=True)
class Listing:
    """One live auction of a class-9 item, as this side reads it.

    NEITHER `entry` NOR THE SKILL GATE COMES FROM `auctionhouse`, for the reason
    bridge._AUCTION_LISTINGS_SQL spells out about its own read: that table holds
    ten columns and none of them is an item. The entry is
    `item_instance.itemEntry` reached through `auctionhouse.itemguid`, and the
    two skill numbers are `item_template`'s own.
    """

    auction_id: int
    entry: int
    label: str
    buyout: int
    house: int
    required_skill: int
    required_rank: int
    recipe_spell: int = 0


@dataclass(frozen=True)
class Learn:
    """One kind='cast' row, ready to insert."""

    holder: str
    command: str
    entry: int
    label: str
    why: str


@dataclass(frozen=True)
class Purchase:
    """One kind='auction' row, ready to insert, and what it will cost."""

    shopper: str
    command: str
    auction_id: int
    entry: int
    label: str
    spend: int
    why: str


@dataclass(frozen=True)
class Skipped:
    """A recipe this pass looked at and did not act on, and the sentence why.

    Carried rather than dropped because "nothing happened" is the state this
    whole area was in for months, and a pass that reports no decisions is
    indistinguishable from a pass that is not running.
    """

    character: str
    entry: int
    label: str
    why: str


def within_reach(required_skill: int, required_rank: int, skills: dict) -> bool:
    """Would Player::CanUseItem let this character use this item?

    The core's own test, asked the core's own way: a RequiredSkill of 0 gates
    nothing, a skill the character does not hold at all is
    EQUIP_ERR_NO_REQUIRED_PROFICIENCY, and a value below RequiredSkillRank is
    EQUIP_ERR_CANT_EQUIP_SKILL (PlayerStorage.cpp:2402-2412).

    `skills` is {skill_id: value}. A value of 0 is NOT the same as an absent
    key here only in prose - the core treats both as "does not hold it" - so
    they are deliberately collapsed rather than distinguished, which is what
    stops a 0/75 row reading as a holder.

    ASKED FROM `character_skills`, WHICH IS LATE BUT CONVERGES. That tolerance
    is fine here for the same reason craft.craft_errand's is: a value a few
    points stale picks a slightly easier recipe, and the worldserver makes the
    real decision anyway - if this is wrong the `use` verb refuses with `the
    character skill is too low to use that item` and nothing is spent. Do not
    generalise it to `character_spell`, which does not converge at all.
    """
    if int(required_skill) <= 0:
        return True
    value = int(skills.get(int(required_skill), 0) or 0)
    return value > 0 and value >= int(required_rank)


def plan_learns(held, skills: dict, settled=None, seen=None):
    """Every recipe already in the bags worth using, and why the rest are not.

    `skills`   {character: {skill_id: value}}
    `settled`  (character, entry) pairs the WORLDSERVER has already answered
               with a refusal that will not change - it already knows the
               recipe, or it cannot use the item. Read back out of
               overseer_command, never forecast. See the header.
    `seen`     (character, command) pairs already queued inside the retry
               window, so a row still walking its own three second cast is not
               queued again every cycle.

    THE ORDER IS DELIBERATE AND IS NOT ALPHABETICAL BY ITEM. Within one
    character the HIGHEST reachable RequiredSkillRank goes first, because that
    is the recipe nearest the top of what the trade can currently do and
    therefore the one most likely to still be worth casting; ties break on the
    item guid so a cycle that changes nothing queues the same row.
    """
    settled = settled or set()
    seen = seen or set()
    out: list = []
    skipped: list = []

    for item in sorted(held, key=lambda h: (h.holder, -int(h.required_rank), int(h.item_guid))):
        mine = skills.get(item.holder, {})
        if (item.holder, int(item.entry)) in settled:
            skipped.append(Skipped(
                item.holder, int(item.entry), item.label,
                "the worldserver has already refused this one and said why"))
            continue
        if not within_reach(item.required_skill, item.required_rank, mine):
            have = int(mine.get(int(item.required_skill), 0) or 0)
            skipped.append(Skipped(
                item.holder, int(item.entry), item.label,
                "needs skill %d at %d and %s has %d"
                % (int(item.required_skill), int(item.required_rank),
                   item.holder, have)))
            continue
        command = use_command(item_guid=int(item.item_guid))
        if (item.holder, command) in seen:
            skipped.append(Skipped(
                item.holder, int(item.entry), item.label,
                "already queued inside the retry window"))
            continue
        out.append(Learn(
            holder=item.holder,
            command=command,
            entry=int(item.entry),
            label=item.label,
            why="carried, and skill %d is at %d against the %d it needs"
                % (int(item.required_skill),
                   int(mine.get(int(item.required_skill), 0) or 0),
                   int(item.required_rank)),
        ))
    return out, skipped


def usable(listings, house: int, skills: dict, settled=None,
           cap: int = PER_RECIPE_CAP_COPPER) -> list:
    """The listings one character could actually buy AND then use, cheapest last.

    `buyout > 0` is re-applied here as well as in the query that fetched them,
    the same duplication auction.usable keeps and for the same reason: a
    bid-only listing is a hard exclusion (a bid buys nothing, and DoAuction
    refuses one by name) and a hard rule belongs where a test with no database
    can reach it.

    Sorted so the BEST one is last: highest reachable RequiredSkillRank, then
    cheapest. Callers take from the end. Buying the highest rank within reach
    rather than the cheapest thing on offer is the difference between levelling
    a trade and filling a bag with recipes that are already grey.
    """
    settled = settled or set()
    out = [
        listing for listing in listings
        if int(listing.house) == int(house)
        and int(listing.buyout) > 0
        and int(listing.buyout) <= int(cap)
        and within_reach(listing.required_skill, listing.required_rank, skills)
        and int(listing.entry) not in settled
    ]
    return sorted(out, key=lambda x: (int(x.required_rank), -int(x.buyout),
                                      -int(x.auction_id)))


def plan_purchases(shoppers, listings, skills: dict, houses: dict, purses: dict,
                   slots: dict, settled=None, seen=None, carried=None,
                   cap: int = SPEND_CAP_COPPER):
    """Every recipe worth buying this pass, and a sentence for each refusal.

    `shoppers` the characters standing at an auctioneer RIGHT NOW. Nobody else
               is considered: this pass writes no travel errand and claims no
               town slot, because the auction pass already walks the family to
               a counter on its own clock and a second writer of `travel_npc`
               is the collision this repo has paid for more than once
               (infra#3712). Recipes therefore get bought while somebody is
               there for another reason, which costs a cycle and no new
               machinery.
    `houses`   {character: auctionhouse.houseid they can reach}, from
               auction.reachable_house - a character buys from its own side's
               house or the neutral one, never the other side's.
    `settled`  entries the worldserver has already refused for that character.
               Keyed (character, entry) like plan_learns'.
    `carried`  (character, entry) pairs that character is ALREADY HOLDING.

    WHY `carried` IS NOT OPTIONAL IN PRACTICE, even though the signature allows
    it to be omitted. A recipe teaches its spell once and is destroyed doing it,
    so a second copy is worth exactly nothing - and the overlap is not
    hypothetical, it is the normal case: the reason a character is holding an
    unlearned Pattern is that the trade is not high enough yet, and the moment
    it IS high enough this pass would find the same recipe on the house and buy
    one. `plan_learns` would then use the free one and the bought one would sit
    in the bag for ever. The two halves have to know about each other exactly
    here and nowhere else.

    ONE RECIPE PER CHARACTER PER PASS. Not a throughput limit: a recipe is
    bought once and kept, so there is no reason to race, and buying one at a
    time means a refusal is read back before more gold follows it.

    A BOUGHT RECIPE DOES NOT ARRIVE IN THE BAGS, and the buy half therefore
    never feeds the learn half in the same pass. DoAuction says so in its own
    success message - `the item arrives by mail
    (AuctionHouseMgr::SendAuctionWonMail); the mailbox is not read here` - so
    the chain is buy, then the mail pass collects it, then `plan_learns` sees it
    in `character_inventory` on some later cycle and uses it. Nothing here
    should try to shorten that: a pass that assumed the item was carried would
    write a `use guid:` row for an item_instance that is still attached to a
    mail row.
    """
    settled = settled or set()
    seen = seen or set()
    carried = carried or set()
    out: list = []
    skipped: list = []
    spent = 0
    taken: set = set()

    for name in sorted(shoppers):
        house = int(houses.get(name, 0) or 0)
        if house <= 0:
            skipped.append(Skipped(name, 0, "",
                                   "no auction house is reachable from this counter"))
            continue
        mine = skills.get(name, {})
        # ONE EXCLUSION LIST, TWO REASONS, and they are folded together because
        # `usable` only needs to know that this entry is not worth buying for
        # this character - not which of the two answers said so.
        settled_here = ({entry for who, entry in settled if who == name}
                        | {entry for who, entry in carried if who == name})
        market = [
            listing for listing in usable(listings, house, mine, settled_here)
            if int(listing.auction_id) not in taken
        ]
        if not market:
            skipped.append(Skipped(name, 0, "",
                                   "nothing on house %d is both usable and affordable"
                                   % house))
            continue

        best = market[-1]
        price = int(best.buyout)
        purse = int(purses.get(name, 0) or 0)
        free = int(slots.get(name, 0) or 0)

        if spent + price > int(cap):
            skipped.append(Skipped(name, int(best.entry), best.label,
                                   "the pass has already spent %d of its %d"
                                   % (spent, int(cap))))
            continue
        if price > purse:
            skipped.append(Skipped(name, int(best.entry), best.label,
                                   "costs %d and %s carries %d"
                                   % (price, name, purse)))
            continue
        if free <= SLOTS_KEPT_FREE:
            skipped.append(Skipped(name, int(best.entry), best.label,
                                   "%s has %d free bag slots and this pass keeps %d"
                                   % (name, free, SLOTS_KEPT_FREE)))
            continue

        command = auction.buy_command(int(best.auction_id))
        if (name, command) in seen:
            skipped.append(Skipped(name, int(best.entry), best.label,
                                   "already queued inside the retry window"))
            continue

        taken.add(int(best.auction_id))
        spent += price
        out.append(Purchase(
            shopper=name,
            command=command,
            auction_id=int(best.auction_id),
            entry=int(best.entry),
            label=best.label,
            spend=price,
            why="skill %d is at %d and this needs %d, for %d copper"
                % (int(best.required_skill),
                   int(mine.get(int(best.required_skill), 0) or 0),
                   int(best.required_rank), price),
        ))
    return out, skipped


# ---------------------------------------------------------------------------
# READING THE WORLDSERVER'S OWN ANSWER BACK.
#
# These are the `detail` literals mod-overseer's `use` verb writes for the two
# refusals that must never be re-asked. Matched on the literal rather than on
# the retry word, for the reason craft.py gives about forecasting: the retry
# word is a classification this module would be re-deriving, while the sentence
# is the thing the worldserver actually wrote.
#
# IF THESE DRIFT, THIS PASS RE-ASKS A SETTLED ROW FOREVER, which is why
# tests/test_recipebook.py reads them out of the deployed module's own source
# rather than trusting this copy.
ALREADY_KNOWN = "the character already knows that recipe"
SKILL_TOO_LOW = "the character skill is too low to use that item"

# A row whose detail is one of these is an answer, not a failure to retry.
SETTLED_DETAILS = (ALREADY_KNOWN, SKILL_TOO_LOW)


def settled_from_rows(rows) -> set:
    """(character, entry) pairs the worldserver has already answered for good.

    `rows` are overseer_command rows this pass wrote, carrying `target_name`,
    `detail` and the entry the row was about. An `already knows` is permanent.
    A `skill too low` is not permanent in principle - the character can train
    the trade up - but it is permanent for as long as the skill sits where it
    is, and re-asking it on a ten minute timer would write a refusal per cycle
    per item for ever. It clears the moment the item is looked at again with a
    higher skill, because this set is rebuilt from the rows every pass and the
    reachability test is re-applied on top of it.
    """
    out = set()
    for row in rows or ():
        detail = str(row.get("detail") or "").strip()
        if detail not in SETTLED_DETAILS:
            continue
        name = str(row.get("target_name") or "")
        entry = int(row.get("entry") or 0)
        if name and entry:
            out.add((name, entry))
    return out


def report(learns, purchases, skipped) -> str:
    """One log sentence for a whole pass, including the pass that did nothing."""
    if not learns and not purchases:
        if not skipped:
            return "recipebook: nobody is carrying a recipe item this pass"
        return ("recipebook: nothing to learn or buy; %d looked at, first: %s"
                % (len(skipped), skipped[0].why))
    parts = []
    if learns:
        parts.append("%d to learn (%s)"
                     % (len(learns), ", ".join(
                         "%s uses %s" % (x.holder, x.label) for x in learns[:3])))
    if purchases:
        parts.append("%d to buy for %d copper (%s)"
                     % (len(purchases), sum(p.spend for p in purchases),
                        ", ".join("%s buys %s" % (p.shopper, p.label)
                                  for p in purchases[:3])))
    return "recipebook: " + "; ".join(parts)
