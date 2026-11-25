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

If a bought position has no placeable bag, supply_needs asks the ordinary
vendor-bag pass for one. The vendor charges the normal price, and the bank
pass places it on arrival. A bank bag is not equipped into a worn position.

THE PRICES ARE THE REALM'S OWN. Read from the worldserver's
BankBagSlotPrices.dbc on wow-dev 2026-10-05: 10 silver, 1 gold, 10 gold, then
25 gold for each of the last four. The core reads the same file and refuses a
slot the purse does not cover; these numbers only decide when it is worth
asking.

PURE MODULE: rows in, one command out. No MySQL and no clock.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import disposition
import guildcorps
import purse

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
    bound: bool = False
    used: int = 0


@dataclass(frozen=True)
class Facts:
    """One character's purse and bags, as the bridge read them."""

    name: str
    money: int = 0
    bought: int = 0
    placed: int = 0
    worn: tuple = ()  # slots of each worn bag
    spare: tuple = ()  # Bag, carried and not worn
    banked: tuple = ()  # Bag, in bank bag positions
    crafter: bool = False  # holds tailoring: its ladder bags are the guild's
    bank_full_of_kept: bool = False
    purse_order: purse.Order | None = None

    @property
    def protected_entries(self) -> frozenset[int]:
        return frozenset(guildcorps.BAG_ITEMS) if self.crafter else frozenset()


def with_kept_full(facts: list, names) -> list:
    """Mark every member in `names` whose personal bank holds only kept stacks."""
    if not names:
        return list(facts)
    return [replace(f, bank_full_of_kept=f.name in names) for f in facts]


def with_purse_orders(facts: list, orders: dict) -> list:
    """Attach each member's `purse.Order` so slot buys honor spells, riding, and food."""
    if not orders:
        return list(facts)
    return [
        replace(f, purse_order=orders[f.name]) if f.name in orders else f for f in facts
    ]


def _spendable(facts: Facts) -> int:
    if facts.purse_order is None:
        return facts.money
    return facts.purse_order.spendable(purse.GEAR)


@dataclass(frozen=True)
class SupplyNeed:
    """A bag that can fill an already bought bank position."""

    name: str
    max_slots: int
    excluded_entries: frozenset[int]


@dataclass(frozen=True)
class Step:
    name: str
    command: str
    why: str
    # Bank slots a placed bag adds; 0 for a purchase.
    slots: int = 0


def _smallest_worn(facts: Facts) -> int:
    if len(facts.worn) < len(WORN_POSITIONS):
        return 0
    return min(facts.worn)


def family_floor(family) -> int:
    """The smallest bag anyone in the family wears, 0 for an empty position."""
    return min((_smallest_worn(f) for f in family or ()), default=0)


def placeable(facts: Facts, floor=None) -> list:
    """The spare bags this character may put in the bank, biggest first.

    `floor` is the family's smallest worn bag (`family_floor`); a tradable
    bag bigger than it is worn by somebody before it is banked. A soulbound
    bag cannot reach a sibling, so only its holder's worn bags take priority.
    """
    own = _smallest_worn(facts)
    floor = own if floor is None else min(own, int(floor))
    return sorted(
        (
            b
            for b in facts.spare
            if b.slots <= (own if b.bound else floor)
            and b.entry not in facts.protected_entries
        ),
        key=lambda b: (-b.slots, b.guid),
    )


def supply_needs(family) -> list[SupplyNeed]:
    """Buy a placeable bag when an empty bank position has none coming.

    Worn positions and the family's existing spare bags come first. The
    size cap and corps exclusions are the same ones placement will enforce.
    """
    floor = family_floor(family)
    if floor <= 0:
        return []
    return [
        SupplyNeed(f.name, floor, f.protected_entries)
        for f in family
        if f.bought > f.placed and not placeable(f, floor)
    ]


def reserved_guids(family) -> frozenset[int]:
    """Placeable carried bags promised to bought, still-empty bank positions.

    Reserve only the number of positions that can take them, largest first.
    Once placed, the bag is no longer carried and the reservation disappears.
    """
    floor = family_floor(family)
    return frozenset(
        b.guid
        for f in family
        for b in placeable(f, floor)[: max(0, f.bought - f.placed)]
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
            bag.slots,
        ), ""
    if facts.bought >= BANK_BAG_SLOTS:
        return None, "%s has bought every bank bag slot" % facts.name
    price = SLOT_PRICES[facts.bought]
    available = _spendable(facts)
    required = price if facts.bank_full_of_kept else price * PURSE_SHARE
    if available < required:
        return (
            None,
            "%s waits to buy bank bag slot %d: %d copper of the %d it wants in hand"
            % (facts.name, facts.bought + 1, available, required),
        )
    return Step(
        facts.name,
        BUY_SLOT,
        "%s buys bank bag slot %d for %d copper of its %d"
        % (facts.name, facts.bought + 1, price, available),
    ), ""


def visit_steps(facts: Facts, floor=None) -> list:
    """This character's steps for one visit, in the order they are sent.

    `step` gives the one step the character's state calls for. When that is a
    purchase and a placeable bag is already carried, the new slot is filled
    on the same visit: buy, then place. Room grows before a deposit is judged.
    """
    first, _why = step(facts, floor)
    if first is None:
        return []
    steps = [first]
    if first.command == BUY_SLOT:
        bags = placeable(facts, floor)
        if bags:
            bag = bags[0]
            steps.append(
                Step(
                    facts.name,
                    "place-bag guid:%d" % bag.guid,
                    "%s puts a %d-slot bag in its bank bag slot %d"
                    % (facts.name, bag.slots, facts.bought + 1),
                    bag.slots,
                )
            )
    return steps


def room_gain(family) -> dict:
    """name -> bank slots a bag placed this visit adds, for who has one."""
    floor = family_floor(family)
    return {
        s.name: s.slots
        for f in family or ()
        for s in visit_steps(f, floor)
        if s.slots > 0
    }


def pending_steps(family, floor=None) -> list:
    """Every character's step this visit, for the characters that have one.

    The bank pass walks the family to a banker while this is not empty, the
    way it does for bank.plan's item moves; a step is written only at the
    counter.
    """
    return [s for s in (step(f, floor)[0] for f in family or ()) if s is not None]


def _worn_guids(bag_rows) -> dict:
    """holder -> the item guids of the bags it wears."""
    out: dict = {}
    for r in bag_rows or ():
        if _int(r.get("bag")) == 0 and _int(r.get("slot")) in WORN_POSITIONS:
            out.setdefault(str(r.get("holder")), set()).add(_int(r.get("item_guid")))
    return out


def _bank_bag_guids(bag_rows) -> dict:
    """holder -> the item guids of the bags in its bank bag positions."""
    out: dict = {}
    for r in bag_rows or ():
        if _int(r.get("bag")) == 0 and _int(r.get("slot")) in BANK_BAG_POSITIONS:
            out.setdefault(str(r.get("holder")), set()).add(_int(r.get("item_guid")))
    return out


def _where(row, worn_guids, bank_bag_guids) -> str:
    """ "worn", "banked", "carried", "in_bank_bag" or "" for one container row."""
    bag, slot = _int(row.get("bag")), _int(row.get("slot"))
    if bag == 0 and slot in WORN_POSITIONS:
        return "worn"
    if bag == 0 and slot in BANK_BAG_POSITIONS:
        return "banked"
    if (bag == 0 and slot in BACKPACK_SLOTS) or bag in worn_guids:
        return "carried"
    if bag in bank_bag_guids:
        return "in_bank_bag"
    return ""


def _facts_for(person, rows, worn_guids, bank_bag_guids, crafters) -> Facts:
    from bag_pressure import item_binding

    name = str(person["name"])
    worn, spare, placed = [], [], 0
    banked_bags = {}
    banked_items = {}  # bank_bag_guid -> count of items
    for r in rows:
        where = _where(r, worn_guids, bank_bag_guids)
        bag = Bag(
            _int(r.get("item_guid")),
            _int(r.get("entry")),
            _int(r.get("slots")),
            bound=item_binding(r) == disposition.BIND_ON_PICKUP,
        )
        if where == "worn":
            worn.append(bag.slots)
        elif where == "banked":
            placed += 1
            banked_bags[bag.guid] = bag
        elif where == "in_bank_bag":
            container = _int(r.get("bag"))
            banked_items[container] = banked_items.get(container, 0) + 1
        elif where == "carried" and bag.guid > 0:
            spare.append(bag)
    banked = tuple(
        Bag(
            guid=guid,
            entry=bag.entry,
            slots=bag.slots,
            bound=bag.bound,
            used=banked_items.get(guid, 0),
        )
        for guid, bag in sorted(banked_bags.items())
    )
    return Facts(
        name=name,
        money=_int(person.get("money")),
        bought=min(BANK_BAG_SLOTS, _int(person.get("bank_slots"))),
        placed=placed,
        worn=tuple(sorted(worn)),
        spare=tuple(spare),
        banked=banked,
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
    bank_bags = _bank_bag_guids(bag_rows)
    by_holder: dict = {}
    for r in bag_rows or ():
        by_holder.setdefault(str(r.get("holder")), []).append(r)
    return [
        _facts_for(
            p,
            by_holder.get(str(p["name"]), []),
            worn.get(str(p["name"]), set()),
            bank_bags.get(str(p["name"]), set()),
            crafters,
        )
        for p in sorted(people or (), key=lambda p: str(p["name"]))
    ]


# ---------------------------------------------------------------------------
# BANK BAG UPGRADES (#2608)
#
# Swap bank bags under 12 slots for 12-slot sacks (Huge Brown Sack, entry 4499,
# 100000 copper = 10g). The swap is only planned when the bag's contents fit
# in the rest of the bank (bank_free + bag.slots - bag.used >= bag.used).

HUGE_BROWN_SACK_ENTRY = 4499
HUGE_BROWN_SACK_PRICE = 100000
HUGE_BROWN_SACK_SLOTS = 12


@dataclass(frozen=True)
class UpgradeNeed:
    """One bank bag that should be upgraded to a 12-slot sack."""

    guid: int
    entry: int
    slots: int
    used: int


def _bank_free(facts: Facts) -> int:
    """Free slots in the bank, including bank bag capacity.

    This is a simplified calculation. The bridge's bank.py computes this
    exactly from the full inventory. Here we approximate: 28 base slots +
    sum of banked bag slots - items in bank (approximated as sum of used
    in banked bags, since items in base slots are not tracked here).
    """
    base = 28
    bag_capacity = sum(b.slots for b in facts.banked)
    items_in_bank = sum(b.used for b in facts.banked)
    return max(0, base + bag_capacity - items_in_bank)


def _upgrade_is_safe(bag: Bag, bank_free: int) -> bool:
    """Can we swap this bag for a 12-slot sack without stranding items?

    The bag's used slots must fit in the rest of the bank after removing
    this bag's capacity. Rest of bank free = bank_free + (bag.slots - bag.used).
    """
    rest_free = bank_free + (bag.slots - bag.used)
    return bag.used <= rest_free


def upgrade_needs(family, floor: int = HUGE_BROWN_SACK_SLOTS) -> list[UpgradeNeed]:
    """Bank bags under `floor` slots that can be safely upgraded.

    Returns a list of UpgradeNeed, largest gain first (smallest bag first).
    """
    needs = []
    for f in family or ():
        if f.money < HUGE_BROWN_SACK_PRICE:
            continue
        bank_free = _bank_free(f)
        for bag in f.banked:
            if bag.slots >= floor:
                continue
            if not _upgrade_is_safe(bag, bank_free):
                continue
            needs.append(UpgradeNeed(bag.guid, bag.entry, bag.slots, bag.used))
    # Smallest bag first = largest gain first
    needs.sort(key=lambda n: n.slots)
    return needs


def upgrade_steps(facts: Facts, floor: int = HUGE_BROWN_SACK_SLOTS) -> list:
    """Steps to upgrade the first eligible bank bag this visit.

    Returns [buy_command, place_command] for the smallest bank bag under
    `floor` slots, or empty list if none qualifies.
    """
    needs = upgrade_needs([facts], floor)
    if not needs:
        return []
    need = needs[0]
    buy_step = Step(
        facts.name,
        f"entry:{HUGE_BROWN_SACK_ENTRY} count:1 max:{HUGE_BROWN_SACK_PRICE}",
        f"{facts.name} buys a {HUGE_BROWN_SACK_SLOTS}-slot sack for {HUGE_BROWN_SACK_PRICE} copper",
    )
    place_step = Step(
        facts.name,
        f"place-bag guid:{need.guid}",
        f"{facts.name} places the {HUGE_BROWN_SACK_SLOTS}-slot sack in bank bag slot {facts.placed}",
        HUGE_BROWN_SACK_SLOTS - need.slots,
    )
    return [buy_step, place_step]
