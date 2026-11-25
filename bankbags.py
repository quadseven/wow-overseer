"""Bank bag slots: bought when affordable, filled and upgraded (#625, #2608).

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
  2. A bank bag under twelve slots is replaced after its contents fit in free
     regular bank slots.
  3. Every bought slot holds a bag and the next slot costs at most a
     PURSE_SHARE of the purse: buy it.

If a bought position has no placeable bag, supply_needs asks the ordinary
vendor-bag pass for one. The vendor charges the normal price, and the bank
pass places it on arrival. A bank bag is not equipped into a worn position.

For an upgrade, the vendor pass buys an exact twelve-slot sack while leaving
one carried slot for the displaced bag. Before the bank pass removes the old
bag, its contents move one stack at a time into measured free regular bank
slots. Unreadable contents, nested nonempty bags, or insufficient room defer
the swap. The old empty bag stays carried for the existing sale and handover
passes.

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
    contents: tuple[int, ...] = ()
    general: bool = True
    contents_movable: bool = True


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
    bank_full_of_kept: bool = False
    purse_order: purse.Order | None = None
    bank_bags: tuple[Bag, ...] = ()
    bank_free: int = 0
    bank_base_free: int = 0
    bag_free: int = 0
    displaced_guids: frozenset[int] = frozenset()
    bank_moves_blocked: bool = False

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


def with_bank_state(facts: list, members, blocked=()) -> list:
    """Attach bank contents and free slots from the bank planner's read."""
    by_name = {m.name: m for m in members or ()}
    blocked_names = set(blocked or ())
    out = []
    for fact in facts or ():
        member = by_name.get(fact.name)
        if member is None:
            out.append(fact)
            continue
        contents: dict[int, list[int]] = {}
        for item in member.banked:
            if item.container_guid:
                contents.setdefault(item.container_guid, []).append(item.guid)
        items = {item.guid: item for item in member.banked}
        nested = set(contents)
        bags = []
        for bag in fact.bank_bags:
            guids = tuple(sorted(contents.get(bag.guid, bag.contents)))
            bags.append(
                replace(
                    bag,
                    used=bag.used if bag.used else len(guids),
                    contents=guids,
                    contents_movable=bag.contents_movable
                    and all(
                        not (
                            items.get(guid)
                            and items[guid].container_slots
                            and guid in nested
                        )
                        for guid in guids
                    ),
                )
            )
        out.append(
            replace(
                fact,
                bank_bags=tuple(bags),
                bank_free=member.bank_free,
                bank_base_free=member.bank_base_free,
                bag_free=member.bag_free,
                bank_moves_blocked=fact.name in blocked_names,
            )
        )
    return out


def with_displaced(facts: list, seen) -> list:
    """Keep recently withdrawn bank bags out of empty-slot placement."""
    displaced = {}
    for name, command in seen or ():
        if not str(command).startswith("withdraw guid:"):
            continue
        try:
            guid = int(str(command).split(":", 1)[1])
        except (TypeError, ValueError):
            continue
        displaced.setdefault(str(name), set()).add(guid)
    return [
        replace(f, displaced_guids=frozenset(displaced.get(f.name, ())))
        for f in facts or ()
    ]


def _spendable(facts: Facts) -> int:
    if facts.purse_order is None:
        return facts.money
    return facts.purse_order.spendable(purse.GEAR)


@dataclass(frozen=True)
class SupplyNeed:
    """A bag needed for a bought position or a safe small-bag upgrade."""

    name: str
    max_slots: int
    excluded_entries: frozenset[int]
    min_slots: int = 0
    min_free_slots: int = 1


@dataclass(frozen=True)
class Step:
    name: str
    command: str
    why: str
    # Bank slots a placed bag adds; 0 for a purchase.
    slots: int = 0
    guid: int = 0
    transfer: bool = False


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
            if b.guid not in facts.displaced_guids
            if b.slots <= (own if b.bound else floor)
            and b.entry not in facts.protected_entries
        ),
        key=lambda b: (-b.slots, b.guid),
    )


def supply_needs(family) -> list[SupplyNeed]:
    """Buy a placeable bag or a twelve-slot replacement when one is needed.

    Worn positions and the family's existing spare bags come first. A bank
    upgrade is asked only when its contents have measured room in the regular
    bank and no carried twelve-slot sack can already replace it.
    """
    floor = family_floor(family)
    needs = []
    for f in family or ():
        target = _upgrade_target(f)
        replacement = _replacement_bag(f)
        if target and replacement is None and _contents_fit_in_base_bank(target, f):
            needs.append(
                SupplyNeed(
                    f.name, 12, f.protected_entries, min_slots=12, min_free_slots=2
                )
            )
            continue
        if floor > 0 and f.bought > f.placed and not placeable(f, floor):
            if (target and replacement) or _place_displaced(f):
                continue
            needs.append(SupplyNeed(f.name, floor, f.protected_entries))
    return needs


def reserved_guids(family) -> frozenset[int]:
    """Placeable carried bags promised to bought, still-empty bank positions.

    Reserve only the number of positions that can take them, largest first.
    Once placed, the bag is no longer carried and the reservation disappears.
    """
    floor = family_floor(family)
    reserved = {
        b.guid
        for f in family or ()
        for b in placeable(f, floor)[: max(0, f.bought - f.placed)]
    }
    reserved.update(
        replacement.guid
        for f in family or ()
        if _upgrade_target(f)
        for replacement in [_replacement_bag(f)]
        if replacement is not None
    )
    reserved.update(
        replacement.guid
        for f in family or ()
        if f.displaced_guids
        for replacement in [_replacement_bag(f)]
        if replacement is not None
    )
    return frozenset(reserved)


def _upgrade_target(facts: Facts) -> Bag | None:
    """The smallest bank bag under twelve slots, for the next safe swap."""
    return min(
        (b for b in facts.bank_bags if 0 < b.slots < 12),
        key=lambda b: (b.slots, b.guid),
        default=None,
    )


def _replacement_bag(facts: Facts) -> Bag | None:
    """A carried general twelve-slot sack that is not reserved for another use."""
    return min(
        (
            b
            for b in facts.spare
            if b.slots == 12
            and b.general
            and b.guid not in facts.displaced_guids
            and b.entry not in facts.protected_entries
        ),
        key=lambda b: b.guid,
        default=None,
    )


def _contents_fit_in_base_bank(bag: Bag, facts: Facts) -> bool:
    """Whether every item in `bag` has a measured regular bank slot to move to."""
    return (
        bag.contents_movable
        and len(bag.contents) == bag.used
        and facts.bank_base_free >= bag.used
    )


def _upgrade_steps(facts: Facts) -> list[Step]:
    target = _upgrade_target(facts)
    replacement = _replacement_bag(facts)
    if target is None or replacement is None or facts.bag_free < 1:
        return []
    if target.used:
        if facts.bank_moves_blocked or not _contents_fit_in_base_bank(target, facts):
            return []
        steps = []
        for guid in target.contents:
            why = "%s moves a bank bag's contents into free bank slots" % facts.name
            steps.extend(
                (
                    Step(
                        facts.name,
                        "withdraw guid:%d" % guid,
                        why,
                        guid=guid,
                        transfer=True,
                    ),
                    Step(
                        facts.name,
                        "deposit guid:%d" % guid,
                        why,
                        guid=guid,
                        transfer=True,
                    ),
                )
            )
        return steps
    return [
        Step(
            facts.name,
            "withdraw guid:%d" % target.guid,
            "%s withdraws an empty %d-slot bank bag for an upgrade"
            % (facts.name, target.slots),
            guid=target.guid,
        ),
        Step(
            facts.name,
            "place-bag guid:%d" % replacement.guid,
            "%s replaces a %d-slot bank bag with a 12-slot sack"
            % (facts.name, target.slots),
            slots=12 - target.slots,
            guid=replacement.guid,
        ),
    ]


def _place_displaced(facts: Facts) -> Step | None:
    """Finish a swap after its old bag left and its new sack remains carried."""
    carried_guids = {bag.guid for bag in facts.spare}
    if not facts.displaced_guids.intersection(carried_guids):
        return None
    if facts.bought <= facts.placed:
        return None
    replacement = _replacement_bag(facts)
    if replacement is None:
        return None
    return Step(
        facts.name,
        "place-bag guid:%d" % replacement.guid,
        "%s places a 12-slot sack in the bank position just opened" % facts.name,
        slots=12,
        guid=replacement.guid,
    )


def step(facts: Facts, floor=None):
    """(Step or None, note): this character's one bank bag step this visit."""
    upgrade = _upgrade_steps(facts)
    if upgrade:
        return upgrade[0], ""
    displaced = _place_displaced(facts)
    if displaced is not None:
        return displaced, ""
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

    `step` gives the one step the character's state calls for. A bought slot
    and carried bag can be handled together; a swap moves the contents first,
    then withdraws the old bag before placing the new sack.
    """
    upgrade = _upgrade_steps(facts)
    if upgrade:
        return upgrade
    displaced = _place_displaced(facts)
    if displaced is not None:
        return [displaced]
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
    """name -> net bank slots a bag placement or replacement adds this visit."""
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
    worn, spare, bank_bags, placed = [], [], [], 0
    for r in rows:
        where = _where(r, worn_guids)
        bag = Bag(
            _int(r.get("item_guid")),
            _int(r.get("entry")),
            _int(r.get("slots")),
            bound=item_binding(r) == disposition.BIND_ON_PICKUP,
            used=_int(r.get("used")),
            general=_int(r.get("subclass")) == 0,
        )
        if where == "worn":
            worn.append(bag.slots)
        elif where == "banked":
            placed += 1
            bank_bags.append(bag)
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
        bank_bags=tuple(bank_bags),
    )


def facts_from_rows(people, bag_rows, crafters=frozenset()) -> list:
    """Facts per character, from the bridge's two reads.

    `people` carry name, money and bank_slots. `bag_rows` carry holder,
    item_guid, entry, slots, used, subclass, bag and slot for every container
    the character owns, where `bag` is the containing bag's item guid (0 for
    the character's own slots). A bag inside a worn bag is carried; one inside
    a bank bag or in a bank slot is not.
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
