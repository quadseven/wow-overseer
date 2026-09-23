"""Pure bag-pressure and vendor-sale decisions for the family economy loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import disposition
import gear
import jobs
import raidlineup
import travel

# The trade-range judgement, re-exported for `handover` (#189) so there is one
# opinion about "standing together" and gear keeps its single importer.
TRADE_YARDS = gear.TRADE_YARDS
GIVE = gear.GIVE
MAIL = gear.MAIL
spots_from_rows = gear.spots_from_rows
within_trade_range = gear._within_trade_range

# The two item classes that are worn: weapons and armour. A bag is class 1 and
# is deliberately not here, because an empty bag is still slots.
EQUIPMENT_CLASSES = frozenset({2, 4})

# `item_template.bonding` as the core writes it. 3 is bind-on-use, which is
# still tradable while it sits in the bag, and 4 is a quest binding that the
# quest_item gate refuses long before binding is consulted. A value outside
# this map is a fact we do not have, and a row we cannot read the binding of
# is dropped rather than guessed at.
_BONDING = {
    0: disposition.BIND_NONE,
    1: disposition.BIND_ON_PICKUP,
    2: disposition.BIND_ON_EQUIP,
    3: disposition.BIND_NONE,
}

# item_instance.flags bit 1: ITEM_FIELD_FLAG_SOULBOUND.
_INSTANCE_SOULBOUND = 0x1


# WHETHER A QUEST ITEM IS STILL A QUEST ITEM (#144), as one SQL expression
# both readers splice in: bridge._VENDOR_ITEMS_SQL, which decides the sale,
# and map_server's Bags read, which says on the page what will happen. One
# spelling, so the page and the vendor cannot disagree about a stack.
#
# It used to be `it.class = 12` alone, which made every turn-in leftover a
# quest item for ever: measured on the dev family 2026-09-22, 85 of 259
# carried stacks were quest-class and 43 of them were asked for by no quest
# in the holder's log. A class-12 stack is a quest item when it starts a
# quest, or when a quest in the holder's log (a character_queststatus row
# whose status is not 0, QUEST_STATUS_NONE: complete-but-not-turned-in and
# failed-but-retryable still need the item; rewarded quests live in
# character_queststatus_rewarded and never appear here)
# names it as required, as a drop it collects, or as the item it hands out
# at the start. Anything else is ordinary goods, and `sellable` still asks
# for quality 1 or less and a vendor price, so a leftover with no price is
# never offered. Expects the aliases `it` (item_template), `ii`
# (item_instance) and `ci` (character_inventory).
QUEST_NEEDED_SQL = (
    "(it.class = 12 AND (it.startquest > 0 OR EXISTS ("
    "SELECT 1 FROM character_queststatus qs "
    "JOIN acore_world.quest_template qt ON qt.ID = qs.quest "
    "WHERE qs.guid = ci.guid AND qs.status <> 0 AND ii.itemEntry IN ("
    "qt.RequiredItemId1, qt.RequiredItemId2, qt.RequiredItemId3, "
    "qt.RequiredItemId4, qt.RequiredItemId5, qt.RequiredItemId6, "
    "qt.ItemDrop1, qt.ItemDrop2, qt.ItemDrop3, qt.ItemDrop4, qt.StartItem))))"
)


def owner_keeps(name: str, keep_names) -> bool:
    """Has the owner marked this item by name as never-dispose (infra#3449)?

    A LIST OF NAMES, NOT OF GUIDS, and deliberately. The owner types this,
    and a guid is a number that changes every time an item is re-looted while
    "Dervish Buckler" is the thing he means. Matched case-insensitively on the
    whole name for the same reason - "dervish buckler" is the same mark.

    The list is passed in rather than read from the environment here, because
    this module is pure and the seam is worth more than the convenience: a
    test can hand it a mark, and bridge.py can hand it the deployment's.
    """
    if not keep_names:
        return False
    return str(name).strip().casefold() in {
        str(k).strip().casefold() for k in keep_names if str(k).strip()
    }


@dataclass(frozen=True)
class ItemForSale:
    quality: int
    quest_item: bool = False
    reagent: bool = False
    profession_needed: bool = False
    sell_price: int = 0


@dataclass(frozen=True)
class SellCandidate:
    """A carried stack the world executor may offer to a vendor."""

    holder: str
    item_guid: int
    count: int
    item: ItemForSale


def vendor_candidates(rows: Iterable[dict], keep_names=()) -> tuple[SellCandidate, ...]:
    """Select only explicitly classified, safe carried vendor goods.

    The adapter supplies flags from world data. Missing flags are dangerous
    and therefore become False only for positive facts such as ``quest_item``;
    unknown identity, price, or count keeps the row out of the action queue.

    `keep_names` is the owner's own never-dispose mark and is checked on this
    path as well as the gear path, because a mark the owner has to remember to
    put on the right one of two lists is not a protection.
    """
    out = []
    for row in rows:
        if owner_keeps(row.get("name", ""), keep_names):
            continue
        try:
            item = ItemForSale(
                quality=int(row["quality"]),
                quest_item=bool(row.get("quest_item", True)),
                reagent=bool(row.get("reagent", True)),
                profession_needed=bool(row.get("profession_needed", True)),
                sell_price=int(row["sell_price"]),
            )
            candidate = SellCandidate(
                holder=str(row["holder"]),
                item_guid=int(row["item_guid"]),
                count=int(row.get("count", 0)),
                item=item,
            )
        except (KeyError, TypeError, ValueError):
            continue
        if candidate.item_guid > 0 and candidate.count > 0 and sellable(item):
            out.append(candidate)
    return tuple(out)


def vendor_batch(
    candidates: Iterable[SellCandidate],
) -> tuple[str, tuple[SellCandidate, ...]]:
    """Choose one holder's safe stacks for a single vendor errand.

    The world executor sells items carried by the character named on each
    command. Sending every holder to one leader's vendor position makes all
    but the leader fail the core's interaction-range check, so one pass must
    be scoped to one travelling holder.
    """
    grouped: dict[str, list[SellCandidate]] = {}
    for candidate in candidates:
        if not isinstance(candidate, SellCandidate) or not candidate.holder:
            continue
        grouped.setdefault(candidate.holder, []).append(candidate)
    if not grouped:
        return "", ()
    holder = sorted(grouped)[0]
    return holder, tuple(grouped[holder])


def vendor_holders_to_queue(
    candidates: Iterable[SellCandidate],
    *,
    leader: str,
    leader_at_counter: bool,
    holder_at_counter,
) -> tuple:
    """Which candidate holders may receive sell rows this pass.

    The leader's arrival owns the family's vendor trip. Once the leader is at
    the counter, queueing the already-judged rows for followers is safe: the
    world executor will retry a follower until that character catches up. If
    the leader is not there yet, retain the old per-holder range gate.
    """
    holders = sorted(
        {
            candidate.holder
            for candidate in candidates
            if getattr(candidate, "holder", "")
        }
    )
    if leader_at_counter:
        return tuple(holders)
    return tuple(name for name in holders if name == leader or holder_at_counter(name))


def town_run_needed(
    used: int, slots: int, minimum_free: int = 2, pressure_percent: int = 90
) -> bool:
    """Return whether bag pressure warrants a vendor run."""
    if slots <= 0 or used < 0 or used > slots:
        return False
    free = slots - used
    return free <= minimum_free or used * 100 >= slots * pressure_percent


# The world-side town trip uses the same boundary. If this is lower, the module
# can walk the family to a vendor and hold it there while the bridge refuses to
# write the sale rows that are the trip's transaction.
TOWN_RUN_FREE_SLOTS = 3


def family_town_run_needed(
    free_slots: dict[str, int],
    minimum_free: int = TOWN_RUN_FREE_SLOTS,
    sellable: dict[str, int] | None = None,
) -> bool:
    """Return whether any measured family member needs a vendor visit.

    The bridge's capacity query returns free slots rather than used and total
    counts. A conservative pressure floor is enough for the trigger: a
    member at or below it can no longer reliably receive loot or materials.
    Unknown and negative readings fail closed, so a broken read cannot send
    the family on a blind trip.

    `sellable` IS THE "COULD A VENDOR EVEN HELP?" HALF (infra#4190), and
    without it this predicate asks only half the question. Measured live
    2026-09-19: Og sat at 0 free slots of 62 while carrying 20 recipes, 16
    quest items, 7 green armour pieces and 6 gems - every one of them
    deliberately protected - plus a single spare bag. Selling everything a
    vendor would accept lifts him to 1, still under a trigger of 3, so the
    pressure he raised could never be answered and never cleared. The vendor
    pass took the travel column on that pressure every cycle, wrote no sale,
    and starved gathering for hours; infra#4191 had to bound the urgent path
    precisely because this predicate kept re-arming it.

    So a member only counts when a vendor trip could actually lift them past
    the trigger: `free + sellable > minimum_free`. A member nobody can
    relieve is a real problem - it is just not a VENDOR problem, and the
    relief has to come from the guild bank or a hand-off instead.

    Omitting a name from `sellable` reads as "nothing to sell", which keeps
    the existing fail-closed bias: an unknown read must not send the family
    on a blind trip. Passing `None` disables the half entirely and preserves
    the original behaviour for callers that only want "is anyone low".
    """
    if not free_slots or minimum_free < 0:
        return False
    low = [
        (name, free)
        for name, free in free_slots.items()
        if isinstance(free, int) and free >= 0 and free <= minimum_free
    ]
    if not low:
        return False
    if sellable is None:
        return True
    for name, free in low:
        offered = sellable.get(name, 0)
        if not isinstance(offered, int) or offered < 0:
            continue
        if free + offered > minimum_free:
            return True
    return False


# WHAT THE ECONOMY PASS DOES THIS CYCLE (#225). Three answers, not a bool,
# because the middle one is new. "trip" takes the travel column and writes
# sales; "counter" writes sales only for holders already at a vendor and takes
# no aim; "none" writes nothing.
VENDOR_PASS_TRIP = "trip"
VENDOR_PASS_COUNTER = "counter"
VENDOR_PASS_NONE = "none"


def vendor_pass_mode(trip_worth: bool, withheld: bool, in_run: bool) -> str:
    """Whether the economy pass travels, sells where it stands, or stops.

    `trip_worth` is `family_town_run_needed` with the sellable half. It asks
    whether SELLING alone can lift somebody past the trigger. For a campaign
    withheld for bag space the answer can be no when a bag would still clear
    it. Measured on wow-dev 2026-09-23: the leader at 2 free slots with 1
    sellable item, a trip worth 3 against a trigger of 3, so the pass returned
    here every cycle. The Jev sell interlude called this same pass and wrote
    no sale in 45 minutes.

    SO A WITHHELD CAMPAIGN SELLS AT THE COUNTER, WITHOUT TRAVELLING. The bag
    trip owns the aim (`townslot.Slot.reserve`) and walks the family to a
    vendor that stocks a bag. Every vendor buys, so the sales are written
    there. A trip this pass cannot justify is still not taken, which keeps
    infra#4190's reason for the gate intact.
    """
    if trip_worth:
        return VENDOR_PASS_TRIP
    if withheld and not in_run:
        return VENDOR_PASS_COUNTER
    return VENDOR_PASS_NONE


# WHAT A VENDOR ERRAND SHOULD DO NEXT. Three words rather than two booleans at
# the call site, because the interesting answer is the middle one and a pair of
# flags is exactly how it stayed invisible: "not aiming" and "giving the column
# back" are opposite intentions that both read as "no write this pass".
VENDOR_ERRAND_AIM = "aim"
VENDOR_ERRAND_HOLD = "hold"
VENDOR_ERRAND_RELEASE = "release"


def vendor_errand_step(
    at_counter: bool, sales_outstanding: int, pressure: bool = False
) -> str:
    """What to do with the leader's `travel_npc` this pass (infra#3708).

    THE ERRAND HAD NO TERMINAL PATH, AND THAT IS THE WHOLE BUG. `travel_npc` was
    written by the economy and cleared by nobody, so `TravelHoldsTheWheel` stood
    the quest drive down for ever: measured 2026-09-13, all five inside one shop
    in Gadgetzan for over half an hour, with the guild bank pass refused the
    column every cycle (infra#3703). mod-overseer will not clear it and refuses
    on purpose - see `bridge._release_trade_errand` for that half.

    RELEASED ON COMPLETION, NEVER ON SUSPICION, which is the distinction a first
    draft of this got wrong. The errand was neither stale nor an orphan write:
    the leader had arrived, 4.4 yards from the merchant against the core's 5.0
    yard interact gate, and the sales were landing, seventeen `delivered` in
    half an hour. Releasing one for LOOKING finished breaks the half that works.
    The only thing allowed to end it is the queue emptying, because that is the
    one fact saying the trip has nothing left to do.

    NOT KNOWING IS A REASON TO HOLD. A negative count is what the bridge reports
    when it could not read the queue at all. Holding a cycle too long costs a
    cycle; releasing a live errand costs the rows already queued against the
    counter the character then walks away from.

    AND `hold` IS A REAL ANSWER, NOT A DO-NOTHING. Re-asserting the keyword on a
    leader already at the counter makes the aim book erase its own state and
    read a standing errand as a new one, which releases and re-takes the 300
    second counter hold. Measured every fifteen seconds for hours: the ceiling
    was never once reached, so nothing ever collected it.
    """
    if not at_counter:
        return VENDOR_ERRAND_AIM
    # A counter reading without a queued sale is not completion while the
    # family is still under the pressure that caused this trip.  The bridge
    # can observe the leader at a vendor before follower sellers have arrived;
    # releasing here would send the party back to questing with the bags full.
    if pressure:
        return VENDOR_ERRAND_HOLD
    # THE SAME QUESTION `stranded_errand_step` ANSWERS, ASKED IN ONE PLACE. A
    # leader standing at the counter and a follower nobody is walking differ in
    # everything EXCEPT what ends the errand, and "a quiet queue is the only
    # thing that may end one" is the rule this pair of functions exists to
    # protect. Two copies of it would be two chances for a later edit to make
    # one of them release on something softer.
    return stranded_errand_step(sales_outstanding)


def stranded_errand_step(sales_outstanding: int) -> str:
    """What to do with a `vendor` aim nobody is walking to a vendor (infra#3746).

    THE ERRAND THAT IS RELEASED BY NOBODY. `vendor_errand_step` above settles
    the errand the LEADER carries, and `bridge._settle_vendor_errand` hands it
    back by naming `_head_now()`. A `vendor` aim that ends up on a FOLLOWER is
    therefore released by nothing at all: the release names a character that is
    not the one carrying the column, so the UPDATE matches no row. Measured on
    wow-dev 2026-09-13 20:20, with infra#3717 deployed, `overseer_roster` held
    `Bork | lead=0 | travel_npc=vendor` while Grug led - and at 20:45 it still
    did, with Bork's own sell queue holding 0 `pending` and 0 `claimed` rows
    against 358 `delivered`.

    IT IS NOT INERT, WHICH IS WHY IT NEEDS A TERMINAL PATH AND NOT A SHRUG.
    `bridge._aimed_names` counts a non-empty `travel_npc` as aimed,
    `_give_them_a_life` hands every aimed character `nc +new rpg`, and
    mod-overseer's `CanBeSentToNpc(botAI)` is exactly
    `botAI->HasStrategy("new rpg", ...)`. So `TravelHoldsTheWheel` -
    `!travelTarget.empty() && (CanBeSentToNpc(botAI) || MaySteerItself(name))` -
    makes itself true off the stale column and stands that follower's quest
    drive down for ever, exactly as the leader's was. mod-overseer will not
    clear it either: `vendor` is one of the four aims `IsMaintenanceErrand`
    covers, so `TravelAimBook::Release` reaches "errand done, releasing" and
    then skips the column write (the infra#3655 fence). The bridge is the only
    side that can, and it was naming the wrong character.

    NO `at_counter` ARGUMENT, AND THE ABSENCE IS THE POINT. Arrival is the
    leader's completion half because the leader is the one the aim WALKS -
    releasing a leader still on the road would cancel the journey the errand
    exists to make. A follower's aim walks nobody: mod-overseer's
    `AimedMover::RefuseInFormation` answers "'Ugga' was sent to 'vendor' but
    does not carry `new rpg` - nothing walks it anywhere. Followers travel by
    following the leader; aim the leader instead", and `bridge._head_now` never
    borrows the lead for an economy errand, so a follower carrying one is not
    on its way anywhere and will not be. There is no journey to cancel, so
    asking where it is standing would be asking a question whose answer cannot
    change what should happen.

    WHICH LEAVES EXACTLY ONE HONEST SIGNAL, AND IT IS THE SAME ONE infra#3717
    ARGUED FOR: that character's own `kind='sell'` queue going quiet. NOT a
    timeout, NOT "the column looks stale", NOT "the family is not in town" -
    every one of those releases an errand for LOOKING finished, which is the
    half of this the coordinator corrected on infra#3708 and which would break
    the working half all over again. `bridge._outstanding_sales` returns -1 for
    "could not read", and a hold on any non-zero covers that with no special
    case: not knowing is a reason to hold.

    PER CHARACTER AND NOT PER FAMILY, which the leader's half does not need.
    The leader's errand is settled against the whole family's queue because the
    leader has to be standing at the counter while ANY holder's rows execute -
    the family walks as one. A stranded aim is the opposite shape by
    construction: it is on one row, it moves one character nowhere, and holding
    it open because a SIBLING still has rows outstanding would leave it latched
    on exactly the realm state that produced this defect.
    """
    if sales_outstanding != 0:
        return VENDOR_ERRAND_HOLD
    return VENDOR_ERRAND_RELEASE


def sellable(item: ItemForSale) -> bool:
    """Sell only safe vendor goods: never rare, quest, reagent, or needed."""
    return (
        item.quality <= 1
        and not item.quest_item
        and not item.reagent
        and not item.profession_needed
        and item.sell_price > 0
    )


def protection_counts(rows: Iterable[dict]) -> dict[str, int]:
    """Summarise why carried rows are protected from the vendor pass.

    This is an observation only.  It does not change the sale decision and it
    deliberately counts overlapping reasons: a rare quest reagent belongs in
    all three buckets because each fact is independently important to an
    operator diagnosing full bags.  Rows missing any sale fact are counted as
    ``unknown``; the sale selector already fails closed for those rows, and
    the summary must make that hidden pressure visible rather than calling it
    junk.

    The bridge supplies rows from the world and logs this result.  Keeping the
    aggregation here makes the explanation testable without a database and
    prevents the HTTP or SQL adapters from growing another inventory opinion.
    """
    counts = {
        "rows": 0,
        "quest": 0,
        "reagent": 0,
        "profession": 0,
        "rare_or_better": 0,
        "unknown": 0,
    }
    required = ("quality", "sell_price", "quest_item", "reagent", "profession_needed")
    for row in rows:
        counts["rows"] += 1
        if any(key not in row for key in required):
            counts["unknown"] += 1
        if bool(row.get("quest_item", False)):
            counts["quest"] += 1
        if bool(row.get("reagent", False)):
            counts["reagent"] += 1
        if bool(row.get("profession_needed", False)):
            counts["profession"] += 1
        try:
            if int(row.get("quality", -1)) >= 3:
                counts["rare_or_better"] += 1
        except (TypeError, ValueError):
            counts["unknown"] += 1
    return counts


def bag_purchase_allowed(
    money: int, price: int, empty_position: bool, reserve: int = 10000
) -> bool:
    """Buy a bag only when a real slot exists and the reserve remains."""
    return empty_position and price > 0 and money >= price + reserve


# ---------------------------------------------------------------------------
# BUYING A BAG (#150)
#
# `bag_purchase_allowed` had no caller. Measured on wow-dev 2026-09-22 the
# second family (levels 12 to 16) carried only the 16-slot backpack each,
# four empty bag positions apiece, 8 to 20 silver in their purses, and Zug's
# client was showing the "Full Bags" tutorial. The cheapest general bag in
# this realm's vendor tables is the 6-slot Small Brown Pouch at 5 silver.
#
# BOUGHT, NEVER GRANTED. Every purchase is a kind='buy' row that mod-overseer's
# DoBuy executes as the character at a vendor in reach, paying the vendor's
# price. Nothing here writes a GM command or creates an item.

# What stays in the purse after a bag is bought: 100 copper (1 silver) per
# character level. A level 13 keeps 1300 copper (13 silver) back for repairs,
# food and training; a level 60 keeps 6000 copper (60 silver). A judgement,
# not a measurement: it is the floor below which a bag stops being worth more
# than the next repair bill.
BAG_RESERVE_PER_LEVEL = 100


def bag_reserve(level: int) -> int:
    """The copper a character keeps after buying a bag."""
    return BAG_RESERVE_PER_LEVEL * max(1, int(level))


@dataclass(frozen=True)
class BagOffer:
    """One general-purpose bag a vendor in reach stocks, at its list price."""

    entry: int
    name: str
    slots: int
    price: int


@dataclass(frozen=True)
class BagBuyer:
    """One character's side of a purchase, as the caller measured it.

    `stocks` is what the vendors in reach of THIS character sell, because
    DoBuy answers on the buyer's own range. `open_positions` is empty bag
    positions less the spare bags already coming to fill them.
    """

    name: str
    level: int
    money: int
    open_positions: int
    free_slots: int
    stocks: frozenset = frozenset()


@dataclass(frozen=True)
class BagPurchase:
    """One bag to buy: a kind='buy' row, then an equip into the position."""

    buyer: str
    entry: int
    name: str
    slots: int
    price: int
    why: str

    @property
    def command(self) -> str:
        """What mod-overseer's ParseBuyRequest reads. `max` caps the spend at
        the list price, which a reputation discount can only lower."""
        return "entry:%d count:1 max:%d" % (int(self.entry), int(self.price))

    @property
    def equip_command(self) -> str:
        """The playerbot equip verb that moves it into the empty position."""
        return "e Hitem:%d:0" % int(self.entry)


def open_bag_positions(members) -> dict:
    """name -> empty bag positions the family's own spare bags will not fill.

    `members` are bag_upgrade.Member values. A spare bag anybody in the family
    carries empty is going to be handed to (or put on by) somebody with an
    empty position, so buying one while a spare exists spends coin on a bag the
    family already owns. The spares are counted against the family's open
    positions in name order, the order bag_upgrade.plan_family_bags fills them.
    """
    spares = sum(1 for m in members for bag in m.carried if bag.used == 0)
    out = {}
    for member in sorted(members, key=lambda m: m.name):
        empty = max(0, int(member.positions) - len(member.worn))
        filled = min(empty, spares)
        spares -= filled
        out[member.name] = empty - filled
    return out


def reserve_yields(buyer: BagBuyer, campaign_waiting: bool) -> bool:
    """Does this buyer's reserve give way to the bag (#88)?

    Yes only when both hold: an operator-ordered dungeon campaign is waiting
    for this family, and this buyer is one of the members whose free slots
    hold it back (`TOWN_RUN_FREE_SLOTS`, the line `bridge._drive_dungeon`
    withholds on). The bag is then the one purchase standing between the
    family and the run the operator asked for.

    WHY THE RESERVE YIELDS RATHER THAN A SIBLING BUYING THE BAG. Measured on
    wow-dev 2026-09-22: Zug held 2149 copper against a 2000 copper reserve at
    level 20, and the pouch in reach cost 500, so the purchase was held back
    every cycle while his three free slots withheld Ragefire Chasm from the
    whole family. A sibling purchase would need a buy that skips the equip,
    a hand-over the next cycle within trade range, and a way to stop the
    family's other empty positions taking the pouch first. The yield is one
    condition on facts this module already has, it spends the buyer's own
    coin, and it cannot fire outside the case that blocks a campaign. The
    first dungeon run refills a purse of 16 silver many times over.
    """
    return bool(campaign_waiting) and 0 <= buyer.free_slots <= TOWN_RUN_FREE_SLOTS


def bag_purchases(buyers, offers, campaign_waiting: bool = False) -> tuple:
    """The cheapest bag each buyer can afford, and a note for each who cannot.

    One bag per buyer per pass: the next pass sees the bag it bought. The
    cheapest offer the buyer's own vendors stock is the only one considered
    (ties go to the bigger bag, then the lower entry), and it is bought only
    when `bag_purchase_allowed` says the reserve survives it and there is a
    free slot for it to land in. Returns (purchases, notes).

    `campaign_waiting` says an operator-ordered dungeon campaign is queued
    for this family; `reserve_yields` decides which buyers it frees from the
    reserve.
    """
    by_entry = {}
    for offer in offers:
        if offer.price > 0 and offer.slots > 0:
            by_entry[int(offer.entry)] = offer
    purchases, notes = [], []
    for buyer in sorted(buyers, key=lambda b: b.name):
        if buyer.open_positions <= 0:
            continue
        stocked = sorted(
            (by_entry[e] for e in buyer.stocks if e in by_entry),
            key=lambda o: (o.price, -o.slots, o.entry),
        )
        if not stocked:
            notes.append(
                "%s has an empty bag position and no vendor in reach "
                "stocks a bag" % buyer.name
            )
            continue
        offer = stocked[0]
        reserve = bag_reserve(buyer.level)
        yielded = reserve_yields(buyer, campaign_waiting)
        if yielded:
            reserve = 0
        if not bag_purchase_allowed(buyer.money, offer.price, True, reserve=reserve):
            notes.append(
                "%s cannot spare %d copper for %s (%d in the purse, "
                "%d kept back at level %d)"
                % (
                    buyer.name,
                    offer.price,
                    offer.name,
                    buyer.money,
                    reserve,
                    buyer.level,
                )
            )
            continue
        if buyer.free_slots < 1:
            notes.append(
                "%s has no free slot for %s to land in; a sell pass "
                "has to run first" % (buyer.name, offer.name)
            )
            continue
        purchases.append(
            BagPurchase(
                buyer=buyer.name,
                entry=offer.entry,
                name=offer.name,
                slots=offer.slots,
                price=offer.price,
                why=(
                    "%d empty bag position(s), %d copper in the purse, %d kept "
                    "back" % (buyer.open_positions, buyer.money, reserve)
                )
                + (
                    "; the reserve yields because %d free slot(s) hold back "
                    "the family's dungeon campaign" % buyer.free_slots
                    if yielded
                    else ""
                ),
            )
        )
    return tuple(purchases), tuple(notes)


# ---------------------------------------------------------------------------
# WALKING TO A VENDOR THAT STOCKS A BAG (#206)
#
# `bag_purchases` buys only where the family already stands. Measured on the
# dev realm 2026-09-22: the second family stood in Ratchet at vendor 8307,
# which sells no bags, and logged "no vendor in reach stocks a bag" every
# cycle while Jazzik (creature 3498), forty yards away, sold the Small Brown
# Pouch and the Brown Leather Satchel. Nothing sent them there, and the
# dungeon coordinator will not open a run while a member has three or fewer
# free slots, so the family's first dungeon waited on a pouch.
#
# The trip is one aim on the leader, written as the vendor's bare creature
# entry through the town slot. mod-overseer resolves that to the nearest
# spawn this character may deal with, holds the leader at the counter on
# arrival (CounterRoleForNpcFlags), and the purchase pass buys there on its
# next cycle, exactly as it would at any other counter.

# How far the family may be walked for a bag: a walk across a town or to the
# next settlement over, never a cross-zone trip. Measured on map 1: Jazzik is
# 48 yards from the Ratchet counter the family stood at, and the Crossroads
# bag vendors (3487, 3481) are 309 and 389 yards from where the second family
# stood an hour later. The next ones out (K'waii, Jark) are over 1,200 yards
# from either spot, which is a journey, not an errand.
BAG_VENDOR_MAX_YARDS = 500.0

# Within this many yards of the chosen vendor's spawn the leader is already
# there, and re-aiming would only make mod-overseer arrive, release and be
# asked again. A follower still outside the counter's reach closes the gap by
# following. Wider than the 8-yard counter box because a spawn row is where a
# vendor was placed, not where it stands after wandering.
BAG_VENDOR_HERE_YARDS = 10.0

# How far a home may be from where the leader stands and still be "this
# town". Mirrors mod-overseer's CAMPAIGN_HOME_TOWN_YARDS (#348): comfortably
# wider than a town and far narrower than the gap to the next one.
CAMPAIGN_HOME_TOWN_YARDS = 250.0


@dataclass(frozen=True)
class BagVendor:
    """One creature entry that stocks a general bag, and its nearest spawn.

    Read from acore_world.npc_vendor joined to the creature spawns and
    item_template (class 1, subclass 0), never hand-authored. `yards` is the
    2D distance from the leader, the measure ResolveTravelTarget ranks by.
    """

    entry: int
    name: str
    map_id: int
    yards: float
    faction: int = 0
    offers: tuple = ()


def bag_vendors_from_rows(rows) -> tuple:
    """BagVendor per creature entry, from one row per (vendor, bag)."""
    grouped: dict = {}
    for row in rows or ():
        try:
            entry = int(row["entry"])
            offer = BagOffer(
                entry=int(row["item"]),
                name=str(row.get("item_name") or ""),
                slots=int(row["slots"]),
                price=int(row["price"]),
            )
            spot = (
                str(row.get("name") or ""),
                int(row["map_id"]),
                float(row["yards"]),
                int(row.get("faction") or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if entry <= 0 or offer.price <= 0 or offer.slots <= 0:
            continue
        seen = grouped.setdefault(entry, [spot, []])
        seen[1].append(offer)
    return tuple(
        BagVendor(
            entry=entry,
            name=spot[0],
            map_id=spot[1],
            yards=spot[2],
            faction=spot[3],
            offers=tuple(sorted(offers, key=lambda o: (o.price, -o.slots, o.entry))),
        )
        for entry, (spot, offers) in grouped.items()
    )


@dataclass(frozen=True)
class Standing:
    """Where one family member is, whether it is fighting, and its home.

    `map_id` is None when the snapshot has no fresh row. `home_map` is None
    when character_homebind has no row, which reads as "not bound here".
    """

    name: str
    map_id: int | None = None
    x: float = 0.0
    y: float = 0.0
    in_combat: bool = False
    job: str = ""
    home_map: int | None = None
    home_x: float = 0.0
    home_y: float = 0.0


def _number(value, cast, default=None):
    try:
        return default if value is None else cast(value)
    except (TypeError, ValueError):
        return default


def standing_from_rows(rows) -> dict:
    """name -> Standing, from bridge._fetch_bag_trip_facts rows."""
    out = {}
    for row in rows or ():
        name = str(row.get("name") or "")
        if not name:
            continue
        out[name] = Standing(
            name=name,
            map_id=_number(row.get("map_id"), int),
            x=_number(row.get("pos_x"), float, 0.0),
            y=_number(row.get("pos_y"), float, 0.0),
            in_combat=bool(_number(row.get("in_combat"), int, 0)),
            job=str(row.get("job") or ""),
            home_map=_number(row.get("home_map"), int),
            home_x=_number(row.get("home_x"), float, 0.0),
            home_y=_number(row.get("home_y"), float, 0.0),
        )
    return out


def _yards(ax, ay, bx, by) -> float:
    return ((float(ax) - float(bx)) ** 2 + (float(ay) - float(by)) ** 2) ** 0.5


def bind_pending(standing: dict, leader: str) -> tuple:
    """Names whose campaign bind may not have landed yet (#206, mod-overseer#583).

    A dungeon campaign walks each member to the campaign's inn and holds it
    there to bind, and a vendor aim taken meanwhile cancels that hold
    (mod-overseer#583). The bridge cannot read the campaign's inn, so it asks
    the question it can answer: a member on a dungeon job whose home is not in
    the town the leader stands in may still be waiting for that bind. Once
    character_homebind shows this town, the bind has landed and a town errand
    no longer competes with it. Unknown reads count as pending.
    """
    here = standing.get(leader)
    out = []
    for name in sorted(standing):
        member = standing[name]
        if not jobs.is_dungeon_job(member.job):
            continue
        if (
            here is None
            or here.map_id is None
            or member.home_map is None
            or int(member.home_map) != int(here.map_id)
            or _yards(member.home_x, member.home_y, here.x, here.y)
            > CAMPAIGN_HOME_TOWN_YARDS
        ):
            out.append(name)
    return tuple(out)


@dataclass(frozen=True)
class BagTrip:
    """The one walk to a bag vendor, or why none is taken.

    `target` is the `travel_npc` value (a bare creature entry) and is '' when
    no aim should be written; `why_not` is never empty then.
    """

    target: str = ""
    vendor: BagVendor | None = None
    buyers: tuple = ()
    why_not: str = ""


def _trip_blocked(leader: str, standing: dict, in_run: bool) -> str:
    """Why no trip may be taken at all right now, or '' when one may."""
    if not leader:
        return "nobody leads the family, and a follower aimed at a vendor does not walk"
    if in_run:
        return "a dungeon run is in progress; the bag trip waits until it ends"
    fighting = sorted(name for name, s in standing.items() if s.in_combat)
    if fighting:
        return "%s in combat; the bag trip waits" % ", ".join(fighting)
    pending = bind_pending(standing, leader)
    if pending:
        return (
            "%s on a dungeon job and not yet bound in this town; the bag trip "
            "waits for the campaign bind to land (mod-overseer#583)"
            % ", ".join(pending)
        )
    here = standing.get(leader)
    if here is None or here.map_id is None:
        return "nothing can say where %s is standing" % leader
    return ""


def _trip_walkers(buyers, standing: dict, map_id: int) -> list:
    """Buyers with a position to fill and a slot to land a bag in, who stand
    on the leader's map and so can follow it to a counter."""
    out = []
    for buyer in sorted(buyers or (), key=lambda b: b.name):
        spot = standing.get(buyer.name)
        if (
            buyer.open_positions > 0
            and buyer.free_slots >= 1
            and spot is not None
            and spot.map_id is not None
            and int(spot.map_id) == map_id
        ):
            out.append(buyer)
    return out


def _trip_vendors(vendors, map_id: int, max_yards: float) -> list:
    """Stocking vendors on the leader's map within the cap, nearest first."""
    return sorted(
        (
            v
            for v in (vendors or ())
            if int(v.map_id) == map_id and float(v.yards) <= max_yards and v.offers
        ),
        key=lambda v: (float(v.yards), int(v.entry)),
    )


def _served_at(vendor: BagVendor, walkers) -> tuple:
    """Who can buy this vendor's cheapest bag and keep the level reserve."""
    price = vendor.offers[0].price
    return tuple(
        b.name
        for b in walkers
        if bag_purchase_allowed(b.money, price, True, reserve=bag_reserve(b.level))
    )


def bag_vendor_trip(
    buyers,
    vendors,
    *,
    leader: str,
    standing: dict,
    in_run: bool = False,
    max_yards: float = BAG_VENDOR_MAX_YARDS,
) -> BagTrip:
    """Where to walk the family so a member who wants a bag can buy one.

    `buyers` are the BagBuyers whose own reach stocks no bag. `vendors` are
    BagVendors measured from the leader. The nearest vendor within
    `max_yards` on the leader's map at which at least one buyer can afford
    that vendor's cheapest bag (with the level reserve kept back and a free
    slot for it to land in) is chosen; ties go to the lower entry.

    NEVER OVER SOMETHING MORE IMPORTANT. No trip while a dungeon run is in
    progress, while anybody in the family is fighting, or while a campaign
    bind may still be pending (`bind_pending`). No trip either once nobody
    who can afford a bag lacks one, which is what stops it repeating.
    """
    blocked = _trip_blocked(leader, standing, in_run)
    if blocked:
        return BagTrip(why_not=blocked)
    map_id = int(standing[leader].map_id)
    walkers = _trip_walkers(buyers, standing, map_id)
    if not walkers:
        return BagTrip(
            why_not="nobody on %s's map wants a bag and has a free slot for one"
            % leader
        )
    usable = _trip_vendors(vendors, map_id, max_yards)
    if not usable:
        return BagTrip(
            why_not="no vendor within %d yards of %s on map %d stocks a bag"
            % (int(max_yards), leader, map_id)
        )
    for vendor in usable:
        served = _served_at(vendor, walkers)
        if not served:
            continue
        if float(vendor.yards) <= BAG_VENDOR_HERE_YARDS:
            return BagTrip(
                vendor=vendor,
                buyers=served,
                why_not="%s already stands at %s (creature %d); the purchase "
                "waits for the buyers to reach the counter"
                % (leader, vendor.name, vendor.entry),
            )
        target = travel.resolve(str(int(vendor.entry)))
        if not target or len(target) > travel.COLUMN_WIDTH:
            return BagTrip(
                why_not="creature %r cannot be named in travel_npc" % (vendor.entry,)
            )
        return BagTrip(target=target, vendor=vendor, buyers=served)
    return BagTrip(
        why_not="nobody who wants a bag can spare the price of the cheapest "
        "one within %d yards and keep the level reserve" % int(max_yards)
    )


def bag_trip_report(trip: BagTrip, leader: str) -> str:
    """One log sentence naming the vendor, its faction and who it serves."""
    if not trip.target:
        return trip.why_not
    vendor = trip.vendor
    return "%s is aimed at creature %s (%s, faction %d, %d yards) so %s can buy %s" % (
        leader,
        trip.target,
        vendor.name,
        vendor.faction,
        int(vendor.yards),
        ", ".join(trip.buyers),
        vendor.offers[0].name,
    )


def item_binding(row) -> str:
    """How this particular copy is bound, which is not what the template says.

    SOULBOUND IS A FACT ABOUT THE INSTANCE. A bind-on-equip green somebody
    wore once is bound forever and its template still reads `bonding = 2`.
    Measured 2026-09-05: of the 111 bind-on-equip greens the family carries,
    38 are already soulbound in `item_instance.flags`. Reading the template
    alone calls those 38 tradable and holds them for an auction house that can
    never list them, which is exactly the bag that never empties.
    """
    flags = int(row.get("instance_flags", 0) or 0)
    if flags & _INSTANCE_SOULBOUND:
        return disposition.BIND_ON_PICKUP
    return _BONDING.get(int(row.get("bonding", -1) or 0), "")


def gear_candidates(
    rows: Iterable[dict], family, available=None, fits=None, keep_names=()
) -> tuple[SellCandidate, ...]:
    """Carried equipment whose only honest route is a vendor (infra#3330).

    `disposition.decide` makes every judgement; this is the adapter that turns
    world rows into the items it wants and drops the rows it cannot describe.
    Only a VENDOR verdict becomes a candidate, because a sale is the only
    thing the caller can write today; a KEEP, or an AUCTION or BANK verdict
    withheld for want of an executor, produces nothing and the item stays put.

    THE SIBLING-UPGRADE QUESTION IS STILL NOT ANSWERED HERE, and still must
    not be - but it is now ANSWERABLE, and `fits` is where the answer arrives
    (infra#3449). It maps item guid to one of disposition's FIT_* values, as
    `gear.claims` computed them from the same class- and role-aware opinion
    that decides hand-offs. One opinion, consulted twice, rather than a second
    one grown next to it.

    `fits=None` means nobody asked, every row is FIT_UNASKED, and this
    function behaves exactly as it did before the gate existed. That default
    is the fail-closed one: on a world image where the gear facts cannot be
    read, the pass keeps everything instead of falling back to a level proxy
    that sells the soulbound upgrades their holders should be wearing.

    `keep_names` is the owner's never-dispose mark, checked before anything
    else and before any row is even parsed.
    """
    if available is None:
        available = disposition.EXECUTABLE_TODAY
    fits = fits or {}
    out = []
    for row in rows:
        if owner_keeps(row.get("name", ""), keep_names):
            continue
        try:
            binding = item_binding(row)
            if not binding:
                continue
            item_class = int(row["item_class"])
            item = disposition.Item(
                name=str(row["name"]),
                quality=int(row["quality"]),
                known=True,
                binding=binding,
                quest_item=item_class == 12,
                equipment=item_class in EQUIPMENT_CLASSES,
                required_level=int(row["required_level"]),
                sell_price=int(row["sell_price"]),
                # Handed straight through so disposition's trade-tool gate
                # can read them (infra#3709); missing on an older world image
                # means 0, which is "not a tool" and leaves this path exactly
                # as it was.
                item_class=item_class,
                bag_family=int(row.get("bag_family", 0) or 0),
            )
            holder = str(row["holder"])
            guid = int(row["item_guid"])
            count = int(row.get("count", 0))
            level = int(row["level"])
        except (KeyError, TypeError, ValueError):
            continue
        if guid <= 0 or count <= 0 or not holder:
            continue
        verdict = disposition.decide(
            item,
            family,
            character_level=level,
            available=available,
            # An item the gate never reached is UNASKED, not "nobody wants
            # it": the two answers differ by exactly one irreversible sale.
            family_fit=fits.get(guid, disposition.FIT_UNASKED),
        )
        if verdict.route != disposition.VENDOR:
            continue
        out.append(
            SellCandidate(
                holder=holder,
                item_guid=guid,
                count=count,
                # Carried only so the insert path has one shape to write. The
                # decision above is disposition's, not `sellable`'s, which refuses
                # every uncommon on purpose and would refuse these too.
                item=ItemForSale(quality=item.quality, sell_price=item.sell_price),
            )
        )
    return tuple(out)


def bag_candidates(
    rows: Iterable[dict], equipped_slots: dict, keep_names=()
) -> tuple[SellCandidate, ...]:
    """Redundant carried bags whose only honest route is a vendor (infra#4163).

    A carried Container (item_class 1) is a candidate only when it is
    unbound AND would be no better than every bag its holder already has
    equipped - selling it can never cost capacity, only reclaim the slot it
    occupies. `equipped_slots` maps holder name to the ContainerSlots of
    every bag that holder currently has equipped; a holder missing from it
    is unknown and every row of theirs is kept, the same fail-closed default
    as the rest of this module.

    THE UPGRADE QUESTION IS NOT ANSWERED HERE. A bag that beats the smallest
    bag its holder has equipped is not a vendor candidate even if nobody has
    equipped it yet - it should be equipped instead, and that decision is
    deliberately left to a separate path. Refusing it here rather than
    guessing "nobody wants it" is the same fail-closed shape `gear_candidates`
    already uses for the equipment it is unsure about.

    Only BIND_NONE bags are offered. A bind-on-equip bag that happens not to
    be an upgrade is still withheld - it is one accidental `/equip` away from
    being useful, and that judgement is out of scope for this pass.
    """
    out = []
    for row in rows:
        if owner_keeps(row.get("name", ""), keep_names):
            continue
        try:
            if int(row["item_class"]) != 1:
                continue
            if item_binding(row) != disposition.BIND_NONE:
                continue
            holder = str(row["holder"])
            guid = int(row["item_guid"])
            count = int(row.get("count", 0))
            container_slots = int(row["container_slots"])
            sell_price = int(row["sell_price"])
            quality = int(row["quality"])
        except (KeyError, TypeError, ValueError):
            continue
        if guid <= 0 or count <= 0 or not holder or sell_price <= 0:
            continue
        sizes = equipped_slots.get(holder)
        if not sizes:
            continue
        if container_slots > min(sizes):
            continue
        out.append(
            SellCandidate(
                holder=holder,
                item_guid=guid,
                count=count,
                item=ItemForSale(quality=quality, sell_price=sell_price),
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# THE FAMILY-FIT GATE, TRANSLATED (infra#3449)
#
# gear.py answers in names because that is what a hand-off needs: WHO should
# get it. disposition asks a coarser question - is disposal off the table -
# and answers in FIT_* values. This is the whole of the translation between
# them, and it lives here because bag_pressure is already the adapter between
# world rows and disposition, and because gear.py is deliberately
# dependency-free and must not learn about disposition to do it.


def family_characters(equipped_rows, names) -> list:
    """The family's CharacterStates, each carrying its party role (#174).

    The role is `raidlineup.party_roles` over the family itself, the packing
    the Armory already shows: one tank, one healer, the rest damage. It is
    what lets `gear.would_wear` hand a two-hander to a damage-role paladin
    who happens to carry a shield, and still refuse one to the tank. Every
    family judgement in this module builds its characters here, so the
    hand-off, the claim that guards the sell path and the holder's own equip
    all read the same role and cannot disagree about the same piece.

    `names` is ONE family: the bridge passes its own roster, never two.
    """
    base = gear.characters_from_rows(equipped_rows, names)
    roles = raidlineup.party_roles(
        [{"name": c.name, "class_id": c.class_id} for c in base]
    )
    return gear.characters_from_rows(equipped_rows, names, roles=roles)


def family_fits(gear_rows, equipped_rows, names) -> dict:
    """item guid -> disposition.FIT_*, from the one gear opinion.

    A guid missing from the result is FIT_UNASKED at the point of use, which
    keeps the item. That is the right answer for every way this can come back
    short - no equipped rows on an older world image, a row gear.py could not
    describe, a holder nobody named - and it is why this returns only what it
    positively decided rather than a value for every row it was handed.
    """
    characters = family_characters(equipped_rows, names)
    holdings = gear.holdings_from_rows(gear_rows)
    holder_of = {int(h.guid): h.holder for h in holdings}
    fits = {}
    for guid, who in gear.claims(holdings, characters).items():
        if who == gear.UNJUDGEABLE:
            fits[guid] = disposition.FIT_UNJUDGEABLE
        elif who == gear.NOBODY:
            fits[guid] = disposition.FIT_NOBODY
        elif who == holder_of.get(guid):
            fits[guid] = disposition.FIT_HOLDER
        else:
            fits[guid] = disposition.FIT_SIBLING
    return fits


# gear.claims' two answers that are not a name, re-exported so a reader of
# claimants never imports gear itself (this module is its one adapter).
CLAIM_NOBODY = gear.NOBODY
CLAIM_UNJUDGEABLE = gear.UNJUDGEABLE


def family_claimants(gear_rows, equipped_rows, names) -> dict:
    """item guid -> WHO gear.claims says should have it, for the Bags tab.

    family_fits' question with the name kept: the page says "gear for Ugga"
    where the sell path only needs "a sibling". Same rows, same opinion; the
    answer is a name, CLAIM_NOBODY or CLAIM_UNJUDGEABLE.
    """
    characters = family_characters(equipped_rows, names)
    return gear.claims(gear.holdings_from_rows(gear_rows), characters)


def family_gifts(
    gear_rows, equipped_rows, names, keep_names=(), position_rows=None, free_slots=None
):
    """The carried pieces a sibling should be handed, and who should have them.

    THE OTHER HALF OF THE SAME PASS, AND THE BIGGER ONE (infra#3464). The
    family-fit gate has answered FIT_SIBLING about a carried piece since
    infra#3450, and `gear_candidates` above deliberately drops every verdict
    that is not VENDOR because a sale was the only thing the caller could
    write. On the measurement that shipped with that gate, 35 of 101 carried
    weapons and armour were upgrades a sibling should be wearing against 25
    that were nobody's - so the larger answer was the one being computed and
    thrown away every cycle, and the bag kept it.

    `gear.plan` has been the writer for exactly this since mod-overseer#14 and
    has never had a production call site: bridge.py did not import gear at
    all, and the kind='give' rows on the realm come from materials.py and
    bag_upgrade.py. This is that call site, and it is an adapter and nothing
    else - who should get what is `gear.plan`'s to say, for the same reason
    `family_fits` refuses to re-decide what `gear.claims` already decided.

    IT CANNOT DISAGREE WITH `family_fits`, and that is structural rather than
    hoped for: both ask `gear.would_wear` of the holder and
    `gear.is_upgrade_for` of every sibling. `claimant` returns the first
    sibling by name and `plan` returns the one who gains most, which is a
    difference about WHO and never about WHETHER. tests/test_gear_handoff.py
    pins that.

    `keep_names` is the owner's never-dispose mark, applied before a row is
    parsed, exactly as it is on both halves of the vendor pass. A hand-off is
    not a disposal, but a mark on a name means leave that item alone, and an
    owner should not have to know which of three passes would have moved it.

    RETURNS A PLAN AND NOT A TUPLE OF GRANTS, because "nothing moved" and
    "nothing should move" were indistinguishable here and that cost a
    fortnight. `gear.deliverable` withholds a grant the world will refuse and
    says which wall it hit, one note per withheld grant, and the caller logs
    them. `position_rows` and `free_slots` default to "nobody asked" and the
    result is what it was before either gate existed; see `gear.deliverable`.

    THE NOTES ARE THE DELIVERY REFUSALS ONLY. `gear.plan` also notes every
    piece nobody in the family can use, which on a measured cycle is most of
    the bag and is the VENDOR half's business - it is already reported there,
    and repeating it here would bury the six lines that are actionable.
    """
    kept = [
        row for row in gear_rows if not owner_keeps(row.get("name", ""), keep_names)
    ]
    characters = family_characters(equipped_rows, names)
    holdings = gear.holdings_from_rows(kept)
    return gear.deliverable(
        gear.plan(holdings, characters).grants,
        position_rows=position_rows,
        free_slots=free_slots,
    )


def holder_equips(gear_rows, equipped_rows, names, keep_names=()) -> tuple:
    """The carried pieces their own holder should put on now (#146).

    An adapter and nothing else, the same contract `family_gifts` keeps:
    `gear.equips` decides, from `gear.claimant` naming the holder. The
    owner's never-dispose mark is honoured here too, because a marked item is
    one to leave alone and wearing it is not leaving it alone.
    """
    kept = [
        row for row in gear_rows if not owner_keeps(row.get("name", ""), keep_names)
    ]
    characters = family_characters(equipped_rows, names)
    return gear.equips(gear.holdings_from_rows(kept), characters)


def jev_equips(wanted, gear_rows, equipped_rows, names, plan, keep_names=()) -> tuple:
    """`holder_equips` with Jev's act plan applied (#95); `wanted` itself when
    there is no plan or it changes no equip.

    `plan.no_equip` is item guids to leave in the bags; `plan.equip` maps an
    item guid to why Jev puts it on its own holder. A chosen piece still has
    to pass gear.py's own can-wear rules and the owner's never-dispose mark,
    and it becomes the same `e Hitem:` row through `gear.chosen_equip`.
    """
    if plan is None or not (plan.equip or plan.no_equip):
        return tuple(wanted)
    withheld, chosen = plan.no_equip, plan.equip
    characters = {c.name: c for c in family_characters(equipped_rows, names)}
    picks = []
    for holding in gear.holdings_from_rows(gear_rows):
        reason = (chosen or {}).get(int(holding.guid))
        character = characters.get(holding.holder)
        if reason is None or character is None:
            continue
        if owner_keeps(holding.name, keep_names) or not can_wear(holding, character):
            continue
        pick = gear.chosen_equip(holding, character, reason)
        if pick is not None:
            picks.append(pick)
    return gear.merge_equips(wanted, withheld, picks)


# Re-exported so the bridge never imports gear itself (this module is its one
# adapter); see gear.equips_to_queue and gear.equip_entry.
equips_to_queue = gear.equips_to_queue
equip_entry = gear.equip_entry


def guild_gear_gifts(
    gear_holdings,
    characters,
    family_names,
    members,
    position_rows=None,
    free_slots=None,
    at_mailbox=None,
):
    """Return useful BoE gear in family-first, guild-second order.

    `gear.plan` owns the class, slot and upgrade judgement. This adapter keeps
    that opinion at the existing `bag_pressure` gear boundary: the family
    gets first claim, then only observed-online non-family guild members see
    pieces left unclaimed. A guild name without observed presence is never
    evidence that a `give` can land.
    """
    family = {str(name) for name in (family_names or ())}
    by_name = {str(member.name): member for member in (members or ())}
    family_chars = [
        character for character in (characters or ()) if character.name in family
    ]
    guild_chars = [
        character
        for character in (characters or ())
        if character.name not in family
        and by_name.get(character.name) is not None
        and bool(by_name[character.name].online)
    ]
    first = tuple(gear.plan(gear_holdings, family_chars).grants)
    claimed = {int(grant.guid) for grant in first}
    remaining = [
        holding for holding in gear_holdings if int(holding.guid) not in claimed
    ]
    guild_grants = tuple(gear.plan(remaining, guild_chars).grants)
    # Family grants are claims used to reserve an item, not guild gifts. The
    # guild pass must never duplicate the family handoff writer.
    # A guildmate is rarely beside the family, so a holder standing at a
    # mailbox posts it instead (#189); otherwise the piece waits.
    return gear.deliverable(
        guild_grants,
        position_rows=position_rows,
        free_slots=free_slots,
        at_mailbox=at_mailbox,
    )


def guild_gear_gifts_from_rows(
    gear_rows,
    equipped_rows,
    family_names,
    members,
    position_rows=None,
    free_slots=None,
    at_mailbox=None,
):
    """Parse bridge rows and apply the guild BoE policy.

    Row parsing stays beside the existing family gear adapter. The bridge
    supplies facts only; this function owns the conversion and the
    family-first reservation before a guild recipient is considered.
    """
    names = [str(member.name) for member in (members or ())]
    # The family carries its party role, the same one every family pass in
    # this module reads; a guildmate has none and keeps the off-hand guard.
    roles = {
        c.name: c.role
        for c in family_characters(equipped_rows, [str(n) for n in family_names or ()])
    }
    characters = gear.characters_from_rows(equipped_rows, names, roles=roles)
    holdings = gear.holdings_from_rows(gear_rows)
    return guild_gear_gifts(
        holdings,
        characters,
        family_names,
        members,
        position_rows=position_rows,
        free_slots=free_slots,
        at_mailbox=at_mailbox,
    )


# ---------------------------------------------------------------------------
# THE GUILD'S LOOT, ROUTED (#174)
#
# The adapter half of gear.route_plan: guildmates' carried rows become
# Holdings, online guild members become Candidates (the family carrying its
# party role), and gear decides. Re-exported below so the bridge, and a second
# scorer beside the ranking, never import gear themselves.

# item_template.bonding values that are bound before anybody equips anything:
# bind on pickup (1) and quest (4). Bind on equip (2) and bind on use (3)
# still trade from a bag, unless the INSTANCE is soulbound, which
# gear.holdings_from_rows reads.
_BOUND_TEMPLATES = frozenset({1, 4})


def guild_route_holdings(rows) -> list:
    """Holdings for guildmates' carried gear; nothing bound gets through."""
    kept = []
    for row in rows or ():
        try:
            if int(row.get("bonding", 0) or 0) in _BOUND_TEMPLATES:
                continue
        except (TypeError, ValueError):
            continue
        kept.append(row)
    return [h for h in gear.holdings_from_rows(kept) if not h.soulbound]


def guild_route_candidates(equipped_rows, members, family_names) -> list:
    """Candidates for every ONLINE guild member, the family carrying roles.

    `members` are guildshare.Member rows. A member who is not online is not
    a candidate: neither a trade nor a mailbox collection happens for
    somebody who is not there.
    """
    family = [str(n) for n in family_names or ()]
    online = [str(m.name) for m in members or () if m.online]
    roles = {c.name: c.role for c in family_characters(equipped_rows, family)}
    characters = gear.characters_from_rows(equipped_rows, online, roles=roles)
    kin = set(family)
    return [gear.Candidate(character=c, family=c.name in kin) for c in characters]


def guild_routes_from_rows(gear_rows, equipped_rows, family_names, members):
    """gear.route_plan over the rows: who in the guild gains most, per item."""
    return gear.route_plan(
        guild_route_holdings(gear_rows),
        guild_route_candidates(equipped_rows, members, family_names),
    )


def weakest_slot_of(name, class_id, level, equipped: dict):
    """gear.weakest_slot for a character described by bucket -> item level."""
    return gear.weakest_slot(
        gear.CharacterState(
            name=str(name), class_id=int(class_id), level=int(level), equipped=equipped
        )
    )


# Re-exported so no caller outside this adapter imports gear (see above).
guild_route_deliverable = gear.route_deliverable
rank_receivers = gear.rank_receivers


def recipe_gifts(
    gear_rows, holders_by_skill, keep_names=(), position_rows=None, free_slots=None
):
    """The carried recipes that belong in another member's bag (infra#3731).

    THE THIRD HAND-OFF, AND THE ONE NOTHING WAS EVEN ASKING ABOUT. `gear.plan`
    moves a piece somebody would WEAR and `family_fits` guards what may be
    SOLD; both judge by slot and item level, so both are structurally blind to
    a Pattern. Measured on the live realm 2026-09-13, that blindness is not
    theoretical: 13 of the 15 recipes the family carries are in the bag of
    somebody who can never learn them, and no pass in this process had ever
    looked at one. See the banner above `disposition.LEARNER_UNASKED` for the
    full table and for why the skill RANK is deliberately not consulted.

    AN ADAPTER AND NOTHING ELSE, the same contract `family_gifts` above keeps.
    `disposition.learners` decides who may claim a recipe and
    `disposition.decide` decides whether that claim beats every other route;
    this only turns world rows into that question and the answer into the
    `gear.Grant` shape the insert path already takes. Re-deciding either here
    is how two answers grow apart.

    IT GOES THROUGH `gear.deliverable` FOR THE SAME REASONS THE GEAR HALF
    DOES, and not because a recipe is gear: 343 of 755 trade rows died on
    `characters are too far apart` and Og was measured at 62 of 62 slots used
    with eight pieces waiting for him. A recipe crossing the family hits both
    of those walls identically, so it gets the same verb choice and the same
    room budget rather than a second copy of that hard-won logic.

    `keep_names` is applied before a row is parsed, exactly as it is on every
    other half of this pass. An owner should not have to know which of four
    passes would have moved the thing they marked.
    """
    kept = [
        row for row in gear_rows if not owner_keeps(row.get("name", ""), keep_names)
    ]
    learner_options = disposition.learner_options(kept, holders_by_skill)
    # Nothing is reachable by any route but GIVE for a recipe, and the
    # module is told exactly that rather than being handed ALL_ROUTES and
    # trusted to avoid the ones that do not ship.
    family = disposition.Family()
    grants = []
    remaining = dict(free_slots or {})
    for row in kept:
        try:
            guid = int(row["item_guid"])
            holder = str(row["holder"]).strip()
            item_class = int(row["item_class"])
            item = disposition.Item(
                name=str(row["name"]),
                quality=int(row["quality"]),
                known=True,
                # A recipe's template bonding is read the same way the gear
                # half reads it, through the INSTANCE flag, because a recipe
                # that has been used is soulbound while its template is not.
                binding=item_binding(row) or disposition.BIND_ON_PICKUP,
                quest_item=item_class == 12,
                item_class=item_class,
                bag_family=int(row.get("bag_family", 0) or 0),
                required_skill=int(row.get("required_skill", 0) or 0),
                sell_price=int(row["sell_price"]),
            )
            entry = int(row.get("entry", 0) or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if guid <= 0 or not holder:
            continue
        options = learner_options.get(guid, ())
        if options and free_slots is not None:
            learner = next(
                (
                    candidate
                    for candidate in options
                    if candidate in remaining and int(remaining[candidate]) > 0
                ),
                options[0],
            )
        else:
            learner = options[0] if options else disposition.LEARNER_UNASKED
        if learner == holder:
            continue
        verdict = disposition.decide(
            item,
            family,
            available=disposition.EXECUTABLE_TODAY,
            learner=learner,
        )
        if verdict.route != disposition.GIVE:
            continue
        # SOULBOUND IS REFUSED HERE AND AGAIN BY THE WORLD. DoGuild and
        # DoTrade both refuse a bound item on their own side, and so does
        # this, because a row that can only ever be refused is a row that
        # should not have been written - the same discipline the gear half
        # keeps by leaning on `gear.is_upgrade_for`.
        if item.binding == disposition.BIND_ON_PICKUP:
            continue
        grants.append(
            gear.Grant(
                holder=holder,
                taker=learner,
                entry=entry,
                name=item.name,
                guid=guid,
                reason=verdict.why,
                said=f"{holder} trade {learner} {item.name}.",
            )
        )
        if free_slots is not None and learner in remaining:
            remaining[learner] = max(0, int(remaining[learner]) - 1)
    return gear.deliverable(
        grants,
        position_rows=position_rows,
        free_slots=free_slots,
    )


# ---------------------------------------------------------------------------
# WHAT JEV'S SHADOW PASS READS OFF GEAR (#95)
#
# jev_items asks Jev the questions the gear passes answer, and records both
# answers. It needs the same Holdings and CharacterStates, and gear.py's own
# reasons, so it reads them HERE: this module stays the one place a world row
# becomes a Holding, and jev_items never grows a second opinion on gear.
# Its CharacterStates come from `family_characters` above, the one builder
# family_fits reads too, party roles included (#174).

WEAPON_CLASS = gear.ITEM_CLASS_WEAPON


def carried_holdings(gear_rows) -> list:
    """gear.Holding per carried piece, as family_fits reads them."""
    return gear.holdings_from_rows(gear_rows)


def can_wear(holding, character) -> bool:
    """Class mask, armour training and required level: gear.py's rules for
    whether a character can put a piece on at all, better or not."""
    return bool(
        gear.usable_by_class(holding, character.class_id)
        and gear.wearable_armor(holding, character)
        and int(character.level) >= int(holding.required_level)
    )


def wear_reason(holding, character) -> tuple:
    """gear.py's (yes, why) for this character: `would_wear` for the holder,
    who needs no hand-off, and `is_upgrade_for` for anybody else."""
    if character.name == holding.holder:
        return gear.would_wear(holding, character)
    return gear.is_upgrade_for(holding, character)
