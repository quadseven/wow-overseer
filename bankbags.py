"""Bank bag slots: bought when affordable, filled with a spare bag (#625).

THE OPERATOR'S RULE (2026-10-05): members buy more bank space when they can
afford it, and bags fill it. Measured the same day: every family member had
bought 0 of 7 bank bag slots, Grog's 28 bank slots were full, and the bag hold
kept the family out of its campaign. `bank.py` never emitted `buy slot`, and
nothing could put a bag into a bought slot until mod-overseer's `place-bag`
verb (quadseven/mod-overseer#856): auto-bank fills the 28 item slots and never
a bag position.

ONE STEP A VISIT, at a banker, in a player's order:

  1. A bought bank bag slot stands empty and a spare bag is carried: place it.
     A spare bag is one the holder does not wear and that is no upgrade over
     its own smallest worn bag or any family member's (the bag hand-over
     would wear that one instead).
     A guild crafter's ladder bag is never placed: it is made for the guild,
     and the corps posts it (guildcorps.master_step).
  2. Every bought slot holds a bag and the next slot costs at most a
     PURSE_SHARE of the purse: buy it.

THE PRICES ARE THE REALM'S OWN. Read from the worldserver's
BankBagSlotPrices.dbc on wow-dev 2026-10-05: 10 silver, 1 gold, 10 gold, then
25 gold for each of the last four. The core reads the same file and refuses a
slot the purse does not cover; these numbers only decide when it is worth
asking.

PURE MODULE: rows in, one command out. No MySQL and no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

import guildcorps

SLOT_PRICES = (1000, 10000, 100000, 250000, 250000, 250000, 250000)
BANK_BAG_SLOTS = len(SLOT_PRICES)
# A slot is bought only when it costs at most a quarter of the purse, so the
# training, repairs and reagents the purse is for are never what pays for it.
PURSE_SHARE = 4

BUY_SLOT = "buy slot"

ITEM_CLASS_CONTAINER = 1
WORN_POSITIONS = range(19, 23)
BACKPACK_SLOTS = range(23, 39)
BANK_BAG_POSITIONS = range(67, 74)


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Bag:
    guid: int
    entry: int
    slots: int


@dataclass(frozen=True)
class Facts:
    """One character's purse and bags, as the bridge read them."""

    name: str
    money: int = 0
    bought: int = 0
    placed: int = 0
    worn: tuple = ()  # slots of each worn bag
    spare: tuple = ()  # Bag, carried and not worn
    crafter: bool = False  # holds tailoring: its ladder bags are the guild's


@dataclass(frozen=True)
class Step:
    name: str
    command: str
    why: str


def _smallest_worn(facts: Facts) -> int:
    if len(facts.worn) < len(WORN_POSITIONS):
        return 0
    return min(facts.worn)


def family_floor(family) -> int:
    """The smallest bag anyone in the family wears, 0 for an empty position."""
    return min((_smallest_worn(f) for f in family or ()), default=0)


def placeable(facts: Facts, floor=None) -> list:
    """The spare bags this character may put in the bank, biggest first.

    `floor` is the family's smallest worn bag (`family_floor`); a bag bigger
    than it is worn by somebody before it is banked.
    """
    own = _smallest_worn(facts)
    floor = own if floor is None else min(own, int(floor))
    return sorted(
        (
            b
            for b in facts.spare
            if b.slots <= floor
            and not (facts.crafter and b.entry in guildcorps.BAG_ITEMS)
        ),
        key=lambda b: (-b.slots, b.guid),
    )


def step(facts: Facts, floor=None):
    """(Step or None, note): this character's one bank bag step this visit."""
    bags = placeable(facts, floor)
    open_slots = facts.bought - facts.placed
    if open_slots > 0:
        if not bags:
            return None, "%s has %d empty bank bag slot(s) and no spare bag" % (
                facts.name,
                open_slots,
            )
        bag = bags[0]
        return Step(
            facts.name,
            "place-bag guid:%d" % bag.guid,
            "%s puts a %d-slot bag in its bank bag slot %d"
            % (facts.name, bag.slots, facts.placed + 1),
        ), ""
    if facts.bought >= BANK_BAG_SLOTS:
        return None, "%s has bought every bank bag slot" % facts.name
    price = SLOT_PRICES[facts.bought]
    if facts.money < price * PURSE_SHARE:
        return (
            None,
            "%s waits to buy bank bag slot %d: %d copper of the %d it wants in hand"
            % (facts.name, facts.bought + 1, facts.money, price * PURSE_SHARE),
        )
    return Step(
        facts.name,
        BUY_SLOT,
        "%s buys bank bag slot %d for %d copper of its %d"
        % (facts.name, facts.bought + 1, price, facts.money),
    ), ""


def _worn_guids(bag_rows) -> dict:
    """holder -> the item guids of the bags it wears."""
    out: dict = {}
    for r in bag_rows or ():
        if _int(r.get("bag")) == 0 and _int(r.get("slot")) in WORN_POSITIONS:
            out.setdefault(str(r.get("holder")), set()).add(_int(r.get("item_guid")))
    return out


def _where(row, worn_guids) -> str:
    """ "worn", "banked", "carried" or "" for one container row."""
    bag, slot = _int(row.get("bag")), _int(row.get("slot"))
    if bag == 0 and slot in WORN_POSITIONS:
        return "worn"
    if bag == 0 and slot in BANK_BAG_POSITIONS:
        return "banked"
    if (bag == 0 and slot in BACKPACK_SLOTS) or bag in worn_guids:
        return "carried"
    return ""


def _facts_for(person, rows, worn_guids, crafters) -> Facts:
    name = str(person["name"])
    worn, spare, placed = [], [], 0
    for r in rows:
        where = _where(r, worn_guids)
        bag = Bag(_int(r.get("item_guid")), _int(r.get("entry")), _int(r.get("slots")))
        if where == "worn":
            worn.append(bag.slots)
        elif where == "banked":
            placed += 1
        elif where == "carried" and bag.guid > 0:
            spare.append(bag)
    return Facts(
        name=name,
        money=_int(person.get("money")),
        bought=min(BANK_BAG_SLOTS, _int(person.get("bank_slots"))),
        placed=placed,
        worn=tuple(sorted(worn)),
        spare=tuple(spare),
        crafter=name in crafters,
    )


def facts_from_rows(people, bag_rows, crafters=frozenset()) -> list:
    """Facts per character, from the bridge's two reads.

    `people` carry name, money and bank_slots. `bag_rows` carry holder,
    item_guid, entry, slots, bag and slot for every container the character
    owns, where `bag` is the containing bag's item guid (0 for the
    character's own slots). A bag inside a worn bag is carried; one inside a
    bank bag or in a bank slot is not.
    """
    worn = _worn_guids(bag_rows)
    by_holder: dict = {}
    for r in bag_rows or ():
        by_holder.setdefault(str(r.get("holder")), []).append(r)
    return [
        _facts_for(
            p,
            by_holder.get(str(p["name"]), []),
            worn.get(str(p["name"]), set()),
            crafters,
        )
        for p in sorted(people or (), key=lambda p: str(p["name"]))
    ]
