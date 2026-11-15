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

import guildcorps
import disposition

SLOT_PRICES = (1000, 10000, 100000, 250000, 250000, 250000, 250000)
BANK_BAG_SLOTS = len(SLOT_PRICES)
# A slot is bought only when it costs at most a quarter of the purse, so the
# training, repairs and reagents the purse is for are never what pays for it.
PURSE_SHARE = 4
SWAP_TARGET_SLOTS = 12

BUY_SLOT = "buy slot"

ITEM_CLASS_CONTAINER = 1
WORN_POSITIONS = range(19, 23)
BACKPACK_SLOTS = range(23, 39)
BANK_BASE_SLOTS = range(39, 67)
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
    crafter: bool = False  # holds tailoring: its ladder bags are the guild's
    placed_bags: tuple = ()  # Bag placed in bank bag positions
    bank_free: int | None = None  # free slots across base bank + bank bags
    bank_full_of_kept: bool = False  # full bank with nothing planned out

    @property
    def protected_entries(self) -> frozenset[int]:
        return frozenset(guildcorps.BAG_ITEMS) if self.crafter else frozenset()


@dataclass(frozen=True)
class SupplyNeed:
    """A bag that can fill an already bought bank position or swap a small one."""

    name: str
    max_slots: int
    excluded_entries: frozenset[int]
    min_slots: int = 0


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


def _placed_count(facts: Facts) -> int:
    return max(facts.placed, len(facts.placed_bags))


def _contents_fit(bag: Bag, bank_free: int | None) -> bool:
    """Whether `bag`'s items fit in the rest of the bank before swapping."""
    if bag.used <= 0:
        return True
    if bank_free is None:
        return False
    rest_free = bank_free - max(0, bag.slots - bag.used)
    return bag.used <= rest_free


def _small_bank_bags(facts: Facts) -> list:
    return sorted(
        (b for b in facts.placed_bags if 0 < b.slots < SWAP_TARGET_SLOTS),
        key=lambda b: (b.slots, b.used, b.guid),
    )


def _swappable_bank_bag(facts: Facts) -> Bag | None:
    """Smallest bank bag under 12 slots whose contents fit elsewhere in the bank."""
    for bag in _small_bank_bags(facts):
        if _contents_fit(bag, facts.bank_free):
            return bag
    return None


def _swap_pair(facts: Facts, floor=None):
    """(new 12+ bag, displaced small bank bag) when a safe swap exists, else None."""
    own = _smallest_worn(facts)
    eff_floor = own if floor is None else min(own, int(floor))
    if eff_floor < SWAP_TARGET_SLOTS:
        return None
    target = _swappable_bank_bag(facts)
    if target is None:
        return None
    spare = next(
        (b for b in placeable(facts, eff_floor) if b.slots >= SWAP_TARGET_SLOTS),
        None,
    )
    return (spare, target) if spare is not None else None


def _swap_step(facts: Facts, floor=None):
    pair = _swap_pair(facts, floor)
    if pair is None:
        return None
    spare, old = pair
    return Step(
        facts.name,
        "place-bag guid:%d" % spare.guid,
        "%s swaps a %d-slot bag for its %d-slot bank bag"
        % (facts.name, spare.slots, old.slots),
        spare.slots - old.slots,
    )


def _supply_need_for(facts: Facts, floor: int) -> SupplyNeed | None:
    if facts.bought > _placed_count(facts):
        if placeable(facts, floor):
            return None
        return SupplyNeed(facts.name, floor, facts.protected_entries)
    if (
        floor >= SWAP_TARGET_SLOTS
        and _swappable_bank_bag(facts) is not None
        and _swap_pair(facts, floor) is None
    ):
        return SupplyNeed(
            facts.name,
            floor,
            facts.protected_entries,
            min_slots=SWAP_TARGET_SLOTS,
        )
    return None


def supply_needs(family) -> list[SupplyNeed]:
    """Buy a placeable bag when an empty bank position or small bank bag has none coming.

    Worn positions and the family's existing spare bags come first. The
    size cap and corps exclusions are the same ones placement will enforce.
    """
    floor = family_floor(family)
    if floor <= 0:
        return []
    out = []
    for f in family:
        need = _supply_need_for(f, floor)
        if need is not None:
            out.append(need)
    return out


def _reserved_for_member(facts: Facts, floor: int) -> list:
    open_slots = max(0, facts.bought - _placed_count(facts))
    if open_slots > 0:
        return placeable(facts, floor)[:open_slots]
    pair = _swap_pair(facts, floor)
    return [pair[0]] if pair is not None else []


def reserved_guids(family) -> frozenset[int]:
    """Placeable carried bags promised to bought or swappable bank positions.

    Reserve only the number of positions that can take them, largest first.
    Once placed, the bag is no longer carried and the reservation disappears.
    """
    floor = family_floor(family)
    return frozenset(b.guid for f in family for b in _reserved_for_member(f, floor))


def with_kept_full(family, kept_full) -> list:
    """Return `family` marked with `bank_full_of_kept` for members in `kept_full`."""
    if not kept_full:
        return list(family or ())
    return [
        replace(f, bank_full_of_kept=True) if f.name in kept_full else f
        for f in (family or ())
    ]


def step(facts: Facts, floor=None):
    """(Step or None, note): this character's one bank bag step this visit."""
    bags = placeable(facts, floor)
    placed = _placed_count(facts)
    open_slots = facts.bought - placed
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
            % (facts.name, bag.slots, placed + 1),
            bag.slots,
        ), ""
    if facts.bought < BANK_BAG_SLOTS:
        price = SLOT_PRICES[facts.bought]
        need = price if facts.bank_full_of_kept else price * PURSE_SHARE
        if facts.money >= need:
            return Step(
                facts.name,
                BUY_SLOT,
                "%s buys bank bag slot %d for %d copper of its %d"
                % (facts.name, facts.bought + 1, price, facts.money),
            ), ""
    swap = _swap_step(facts, floor)
    if swap is not None:
        return swap, ""
    if facts.bought < BANK_BAG_SLOTS:
        price = SLOT_PRICES[facts.bought]
        need = price if facts.bank_full_of_kept else price * PURSE_SHARE
        return (
            None,
            "%s waits to buy bank bag slot %d: %d copper of the %d it wants in hand"
            % (facts.name, facts.bought + 1, facts.money, need),
        )
    blocked = _small_bank_bags(facts)
    if blocked:
        old = blocked[0]
        return (
            None,
            "%s cannot swap its %d-slot bank bag yet: %d item(s) need room in the rest of the bank"
            % (facts.name, old.slots, old.used),
        )
    return None, "%s has bought every bank bag slot" % facts.name


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
    from bag_pressure import item_binding

    name = str(person["name"])
    worn, spare, placed_bags = [], [], []
    for r in rows:
        where = _where(r, worn_guids)
        bag = Bag(
            _int(r.get("item_guid")),
            _int(r.get("entry")),
            _int(r.get("slots")),
            bound=item_binding(r) == disposition.BIND_ON_PICKUP,
            used=_int(r.get("used")),
        )
        if where == "worn":
            worn.append(bag.slots)
        elif where == "banked":
            placed_bags.append(bag)
        elif where == "carried" and bag.guid > 0:
            spare.append(bag)
    bank_free = None
    if person.get("bank_free") is not None:
        bank_free = max(0, _int(person.get("bank_free")))
    elif person.get("bank_base_used") is not None:
        base_free = max(0, len(BANK_BASE_SLOTS) - _int(person.get("bank_base_used")))
        bag_free = sum(max(0, b.slots - b.used) for b in placed_bags)
        bank_free = base_free + bag_free
    return Facts(
        name=name,
        money=_int(person.get("money")),
        bought=min(BANK_BAG_SLOTS, _int(person.get("bank_slots"))),
        placed=len(placed_bags),
        worn=tuple(sorted(worn)),
        spare=tuple(spare),
        crafter=name in crafters,
        placed_bags=tuple(sorted(placed_bags, key=lambda b: (b.slots, b.used, b.guid))),
        bank_free=bank_free,
        bank_full_of_kept=bool(person.get("bank_full_of_kept", False)),
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
