"""Bank bag slots: bought when affordable, filled, and upgraded safely (#625).

THE OPERATOR'S RULE (2026-10-05): members buy more bank space when they can
afford it, and bags fill it. Measured the same day: every family member had
bought 0 of 7 bank bag slots, Grog's 28 bank slots were full, and the bag hold
kept the family out of its campaign. `bank.py` never emitted `buy slot`, and
nothing could put a bag into a bought slot until mod-overseer's `place-bag`
verb (quadseven/mod-overseer#856): auto-bank fills the 28 item slots and never
a bag position.

ORDERED WORK AT A BANKER:

  1. A bought bank bag slot stands empty and a spare bag is carried: place it.
     A spare bag is one the holder does not wear and that is no upgrade over
     its own smallest worn bag or any family member's (the bag hand-over
     would wear that one instead).
     A guild crafter's ladder bag is never placed: it is made for the guild,
     and the corps posts it (guildcorps.master_step).
  2. A carried 12-slot sack may replace a smaller bank bag after that bag's
     contents are staged in the carried bags and fit in the rest of the bank.
     Their withdraw rows go first; the old bag and new sack move on later reads.
  3. Every bought slot holds a bag and the next slot costs at most a
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
BANK_BAG_UPGRADE_SLOTS = 12
BANK_BAG_UPGRADE_PRICE = 100_000
# A slot is bought only when it costs at most a quarter of the purse, so the
# training, repairs and reagents the purse is for are never what pays for it.
PURSE_SHARE = 4

BUY_SLOT = "buy slot"

ITEM_CLASS_CONTAINER = 1
WORN_POSITIONS = range(19, 23)
BACKPACK_SLOTS = range(23, 39)
BANK_BAG_POSITIONS = range(67, 74)
BANK_ITEM_POSITIONS = range(39, 67)


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
    contents: tuple = ()


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
    banked: tuple = ()  # bank bag positions, with the GUIDs inside each bag
    bank_free: int = 0
    bag_free: int = 0
    displaced: frozenset[int] = frozenset()

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


def with_recent_withdrawals(facts: list, recent) -> list:
    """Mark carried small bags withdrawn during the active replacement pass."""
    withdrawn: dict[str, set[int]] = {}
    for name, command in recent or ():
        if not str(command).startswith("withdraw guid:"):
            continue
        try:
            guid = int(str(command).split(":", 1)[1])
        except ValueError:
            continue
        withdrawn.setdefault(str(name), set()).add(guid)
    return [
        replace(
            facts_for_member,
            displaced=frozenset(
                bag.guid
                for bag in facts_for_member.spare
                if bag.guid in withdrawn.get(facts_for_member.name, set())
                and bag.slots < BANK_BAG_UPGRADE_SLOTS
                and not bag.contents
                and bag.entry not in facts_for_member.protected_entries
            ),
        )
        for facts_for_member in facts or ()
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
            if b.guid > 0
            and not b.contents
            and b.guid not in facts.displaced
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


def _upgrade_target(facts: Facts):
    candidates = [
        bag
        for bag in facts.banked
        if bag.guid > 0
        and 0 < bag.slots < BANK_BAG_UPGRADE_SLOTS
        and bag.entry not in facts.protected_entries
    ]
    return min(candidates, key=lambda bag: (bag.slots, bag.guid), default=None)


def _upgrade_sack(facts: Facts):
    candidates = [
        bag
        for bag in facts.spare
        if bag.guid > 0
        and bag.slots == BANK_BAG_UPGRADE_SLOTS
        and not bag.contents
        and bag.entry not in facts.protected_entries
    ]
    return min(candidates, key=lambda bag: bag.guid, default=None)


def _upgrade_fits(facts: Facts, target: Bag, has_sack: bool) -> bool:
    contents = len(target.contents)
    if any(guid <= 0 for guid in target.contents):
        return False
    free_inside_target = max(0, target.slots - contents)
    free_elsewhere = facts.bank_free - free_inside_target
    if contents and free_elsewhere < contents:
        return False
    carried_needed = contents + 1 + (0 if has_sack else 1)
    return facts.bag_free >= carried_needed


def upgrade_needs(family) -> list[SupplyNeed]:
    """Buy a 12-slot sack for a safe bank-bag replacement.

    An existing empty sack is already supply. Otherwise the member needs the
    list price, carried room for the sack, its old contents, and the displaced
    bag, plus enough room in the other bank slots to receive those contents.
    """
    needs = []
    for facts in family or ():
        if facts.bought > facts.placed or _upgrade_sack(facts):
            continue
        target = _upgrade_target(facts)
        if target is None or _spendable(facts) < BANK_BAG_UPGRADE_PRICE:
            continue
        if not _upgrade_fits(facts, target, has_sack=False):
            continue
        needs.append(
            SupplyNeed(
                facts.name,
                BANK_BAG_UPGRADE_SLOTS,
                facts.protected_entries,
                min_slots=BANK_BAG_UPGRADE_SLOTS,
            )
        )
    return needs


def _replacement_steps(facts: Facts) -> list[Step]:
    """Drain one eligible bank bag, then fill its bought position with a sack."""
    sack = _upgrade_sack(facts)
    if not sack:
        return []
    open_slots = facts.bought - facts.placed
    if open_slots > 0:
        displaced = any(bag.guid in facts.displaced for bag in facts.spare)
        if not displaced:
            return []
        return [
            Step(
                facts.name,
                "place-bag guid:%d" % sack.guid,
                "%s replaces a smaller bank bag with a 12-slot sack"
                % facts.name,
                sack.slots,
            )
        ]

    target = _upgrade_target(facts)
    if target is None or not _upgrade_fits(facts, target, has_sack=True):
        return []
    if target.contents:
        if any(guid <= 0 for guid in target.contents):
            return []
        return [
            Step(
                facts.name,
                "withdraw guid:%d" % guid,
                "%s stages a bank bag's contents before replacing it" % facts.name,
            )
            for guid in sorted(target.contents)
        ]
    return [
        Step(
            facts.name,
            "withdraw guid:%d" % target.guid,
            "%s removes the empty smaller bank bag for its 12-slot replacement"
            % facts.name,
        )
    ]


def reserved_guids(family) -> frozenset[int]:
    """Placeable carried bags promised to bought, still-empty bank positions.

    Reserve only the number of positions that can take them, largest first.
    Once placed, the bag is no longer carried and the reservation disappears.
    """
    floor = family_floor(family)
    reserved = {
        b.guid
        for f in family
        for b in placeable(f, floor)[: max(0, f.bought - f.placed)]
    }
    for facts in family or ():
        target, sack = _upgrade_target(facts), _upgrade_sack(facts)
        if target and sack:
            reserved.add(sack.guid)
        if facts.displaced and facts.bought > facts.placed and sack:
            reserved.add(sack.guid)
    return frozenset(reserved)


def step(facts: Facts, floor=None):
    """(Step or None, note): this character's one bank bag step this visit."""
    replacement = _replacement_steps(facts)
    if replacement:
        return replacement[0], ""
    return _ordinary_step(facts, floor)


def visit_steps(facts: Facts, floor=None) -> list:
    """This character's steps for one visit, in the order they are sent.

    `step` gives the one step the character's state calls for. When that is a
    purchase and a placeable bag is already carried, the new slot is filled
    on the same visit: buy, then place. Room grows before a deposit is judged.
    """
    replacement = _replacement_steps(facts)
    if replacement:
        return replacement
    first, _why = _ordinary_step(facts, floor)
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


def _ordinary_step(facts: Facts, floor=None):
    """The original slot-buy and empty-position placement decision."""
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
    """Every character's ordered steps this visit, for those with work.

    The bank pass walks the family to a banker while this is not empty, the
    way it does for bank.plan's item moves; a step is written only at the
    counter.
    """
    return [s for f in family or () for s in visit_steps(f, floor)]


def _container_guids(rows, positions) -> dict:
    """holder -> item guids occupying one of the named bag positions."""
    out: dict = {}
    for r in rows or ():
        if (
            _int(r.get("slots")) > 0
            and _int(r.get("bag")) == 0
            and _int(r.get("slot")) in positions
        ):
            out.setdefault(str(r.get("holder")), set()).add(_int(r.get("item_guid")))
    return out


def _where(row, worn_guids, banked_guids) -> str:
    """Return whether one inventory row is worn, banked, carried, or ignored."""
    bag, slot = _int(row.get("bag")), _int(row.get("slot"))
    if bag == 0 and slot in WORN_POSITIONS:
        return "worn"
    if bag == 0 and slot in BANK_BAG_POSITIONS:
        return "banked"
    if (bag == 0 and slot in BACKPACK_SLOTS) or bag in worn_guids:
        return "carried"
    if (bag == 0 and slot in BANK_ITEM_POSITIONS) or bag in banked_guids:
        return "banked"
    return ""


def _facts_for(person, rows, worn_guids, banked_guids, crafters) -> Facts:
    from bag_pressure import item_binding

    name = str(person["name"])
    worn, spare, banked = [], [], []
    contents_by_bag: dict[int, list[int]] = {}
    container_guids = {
        _int(row.get("item_guid"))
        for row in rows
        if _int(row.get("slots")) > 0 and _int(row.get("item_guid")) > 0
    }
    for r in rows:
        container = _int(r.get("bag"))
        if container in container_guids:
            contents_by_bag.setdefault(container, []).append(_int(r.get("item_guid")))
    bag_used = bank_used = 0
    for r in rows:
        where = _where(r, worn_guids, banked_guids)
        bag = Bag(
            _int(r.get("item_guid")),
            _int(r.get("entry")),
            _int(r.get("slots")),
            bound=item_binding(r) == disposition.BIND_ON_PICKUP,
            contents=tuple(sorted(contents_by_bag.get(_int(r.get("item_guid")), ()))),
        )
        if where == "worn" and bag.guid in worn_guids:
            worn.append(bag.slots)
        elif where == "banked" and bag.guid in banked_guids:
            banked.append(bag)
        elif where == "carried" and bag.guid > 0:
            bag_used += 1
            if bag.slots > 0:
                spare.append(bag)
        elif where == "banked":
            bank_used += 1
    worn_slots = sum(worn)
    bank_slots = sum(bag.slots for bag in banked)
    return Facts(
        name=name,
        money=_int(person.get("money")),
        bought=min(BANK_BAG_SLOTS, _int(person.get("bank_slots"))),
        placed=len(banked),
        worn=tuple(sorted(worn)),
        spare=tuple(spare),
        crafter=name in crafters,
        banked=tuple(sorted(banked, key=lambda bag: (bag.slots, bag.guid))),
        bank_free=max(0, 28 + bank_slots - bank_used),
        bag_free=max(0, len(BACKPACK_SLOTS) + worn_slots - bag_used),
    )


def facts_from_rows(people, bag_rows, crafters=frozenset()) -> list:
    """Facts per character, from the bridge's two reads.

    `people` carry name, money and bank_slots. `bag_rows` carry holder,
    item_guid, entry, slots, bag and slot for every inventory item, where
    `bag` is the containing bag's item guid (0 for the character's own slots).
    Reading all items counts bank contents, bank room and temporary carried
    room before a bank bag is replaced.
    """
    worn = _container_guids(bag_rows, WORN_POSITIONS)
    banked = _container_guids(bag_rows, BANK_BAG_POSITIONS)
    by_holder: dict = {}
    for r in bag_rows or ():
        by_holder.setdefault(str(r.get("holder")), []).append(r)
    return [
        _facts_for(
            p,
            by_holder.get(str(p["name"]), []),
            worn.get(str(p["name"]), set()),
            banked.get(str(p["name"]), set()),
            crafters,
        )
        for p in sorted(people or (), key=lambda p: str(p["name"]))
    ]
