"""A guild member with Apprentice Riding and no mount buys one (#779).

WHY THIS EXISTS. Read on the dev realm on 2026-10-10: 94 of the 97 members of
the two family guilds at level 20 or above had no Riding skill (762), and
nothing walked a member to a mount vendor. The riding walk
(guildjobs.riding_step, #810) buys the skill; this module is the other half.
Riding without a mount is a skill with nothing to ride.

THE CHOICE. A member at Apprentice Riding's level that holds Riding, knows no
mount, and whose purse covers the mount after what it keeps for its class
spells (purse.Order.held_before(purse.RIDING), the same reserve the riding walk
spends above) walks to its own race's mount vendor and buys the cheapest mount
that vendor sells which its Riding skill can use. It then uses the item:
on 3.3.5 a mount item teaches its mount spell through the generic learning
spell 483 or 55884 (quadseven/mod-overseer's `use entry:` learn row), and the
item is gone after. A member already carrying an unused mount item uses it and
buys nothing.

WHAT THE WORLD SAYS, AND WHAT IS WRITTEN DOWN HERE. The prices, the items and
the skill rank each item needs are read from the world at run time (npc_vendor
and item_template; bridge._MOUNT_STOCK_SQL), never written here. What is
written here is which creature is each race's mount vendor (MOUNT_VENDORS),
checked against AzerothCore's own creature_template and npc_vendor data:
every one sells its race's riding mounts and nothing else.

WHO IS LEFT OUT, AND WHY. A paladin or a warlock (CLASS_MOUNT_CLASSES) learns
its mount from its own class trainer at 20, a class spell the purchase order
already saves for; it does not walk to a race's vendor.

NATURAL ONLY. Nothing here grants anything: the member pays the vendor with
its own gold, and only gold above its class spell reserve.

PURE MODULE: facts in, a Decision out. No MySQL, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

import purse

ACTION = "mount"

# item_template.class and .subclass of a mount item (ITEM_CLASS_MISC,
# ITEM_SUBCLASS_MOUNT).
MOUNT_CLASS = 15
MOUNT_SUBCLASS = 5

# Race id -> the creature entry of that race's mount vendor. Checked against
# AzerothCore's creature_template and npc_vendor (2026-10-19).
MOUNT_VENDORS = {
    1: 384,  # Human: Katie Hunter, Elwynn Forest
    2: 3362,  # Orc: Ogunaro Wolfrunner, Orgrimmar
    3: 1261,  # Dwarf: Veron Amberstill, Dun Morogh
    4: 4730,  # Night Elf: Lelanai, Darnassus
    5: 4731,  # Undead: Zachariah Post, Tirisfal Glades
    6: 3685,  # Tauren: Harb Clawhoof, Mulgore
    7: 7955,  # Gnome: Milli Featherwhistle, Dun Morogh
    8: 7952,  # Troll: Zjolnir, Durotar
    10: 16264,  # Blood Elf: Winaestra, Eversong Woods
    11: 17584,  # Draenei: Torallius the Pack Handler, Azuremyst Isle
}

# Paladin and warlock: their mount is a class spell (Summon Warhorse, Summon
# Felsteed) from their own trainer.
CLASS_MOUNT_CLASSES = frozenset({2, 9})

USE = "use"
BUY = "buy"


@dataclass(frozen=True)
class Offer:
    """One mount a vendor sells, as the world reads it."""

    vendor: int
    entry: int
    price: int
    # item_template.RequiredSkillRank: the Riding value the item needs.
    rank: int
    map_id: int
    name: str = ""


@dataclass(frozen=True)
class Facts:
    """What the bridge read for one member: whether it knows a mount spell
    already, and the stock of the mount vendors (Offer rows)."""

    knows_mount: bool = False
    offers: tuple = ()


@dataclass(frozen=True)
class Decision:
    """`kind` is USE (the member carries the item), BUY (it walks to the
    vendor, buys and uses it) or "" (nothing now, `why` says why when it is
    worth saying)."""

    kind: str = ""
    offer: Offer | None = None
    why: str = ""


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def offer_from_row(row) -> Offer:
    """An Offer from one bridge._MOUNT_STOCK_SQL row."""
    return Offer(
        _int(row.get("vendor")),
        _int(row.get("entry")),
        max(0, _int(row.get("price"))),
        _int(row.get("rank")),
        _int(row.get("map_id"), -1),
        str(row.get("name") or ""),
    )


def wants_mount(level, class_id, riding_max) -> bool:
    """Is this member one whose mount comes from a race's vendor and that can
    ride one now: Apprentice Riding's level, Riding learned (its ceiling at
    Apprentice's or above), and not a paladin or a warlock."""
    return (
        _int(level) >= purse.APPRENTICE.level
        and _int(riding_max) >= purse.APPRENTICE.ceiling
        and _int(class_id) not in CLASS_MOUNT_CLASSES
    )


def cheapest(race, riding_value, offers) -> Offer | None:
    """The cheapest mount the race's vendor sells that `riding_value` can use;
    the lower entry on a tie. None when the race has no vendor or the vendor
    sells nothing it can ride."""
    vendor = MOUNT_VENDORS.get(_int(race))
    if vendor is None:
        return None
    usable = [
        o
        for o in offers
        if o.vendor == vendor and 0 < o.rank <= _int(riding_value) and o.entry > 0
    ]
    if not usable:
        return None
    return min(usable, key=lambda o: (o.price, o.entry))


def _carried_mount(carried, offers, riding_value) -> Offer | None:
    """The mount item the member carries and can use, None when none. An item
    the stock does not list still counts (a gift or a drop); its rank is
    unknown, so the module's learn row is left to judge it."""
    by_entry = {o.entry: o for o in offers}
    for entry, item_class, subclass in carried:
        if _int(item_class) != MOUNT_CLASS or _int(subclass) != MOUNT_SUBCLASS:
            continue
        held = by_entry.get(_int(entry)) or Offer(0, _int(entry), 0, 0, -1)
        if held.rank <= _int(riding_value):
            return held
    return None


def _no_offer(name, race, riding_value) -> Decision:
    """Why the race's vendor has nothing for the member."""
    if _int(race) not in MOUNT_VENDORS:
        return Decision(why="no mount vendor is known for %s's race" % name)
    return Decision(
        why="%s's mount vendor sells nothing its Riding %d can ride"
        % (name, _int(riding_value))
    )


def _on_map(offer, offers, map_id) -> bool:
    """Whether a spawn of the offer's vendor stands on the member's map."""
    if map_id is None:
        return False
    return any(
        o.entry == offer.entry and o.vendor == offer.vendor and o.map_id == _int(map_id)
        for o in offers
    )


def decide(
    name,
    level,
    class_id,
    race,
    riding,
    money,
    reserve,
    map_id,
    carried,
    facts,
) -> Decision:
    """The member's mount decision.

    `riding` is its Riding skill as (value, max); `reserve` the copper kept
    ahead of riding in its purchase order (its class spells); `carried` the
    (entry, item class, subclass) of what it carries; `facts` a Facts.
    """
    value, ceiling = (tuple(riding) + (0, 0))[:2]
    if facts is None or facts.knows_mount:
        return Decision()
    if not wants_mount(level, class_id, ceiling):
        return Decision()
    offers = tuple(facts.offers)
    held = _carried_mount(carried, offers, value)
    if held is not None:
        return Decision(USE, held)
    offer = cheapest(race, value, offers)
    if offer is None:
        return _no_offer(name, race, value)
    if _int(money) < offer.price + max(0, _int(reserve)):
        return Decision(
            offer=offer,
            why="%s saves for a mount (%s, after %s kept for its class spells; "
            "it holds %s)"
            % (
                name,
                purse.money(offer.price),
                purse.money(reserve),
                purse.money(money),
            ),
        )
    if not _on_map(offer, offers, map_id):
        return Decision(
            offer=offer,
            why="%s can buy a mount for %s and its race's mount vendor stands on "
            "another map" % (name, purse.money(offer.price)),
        )
    return Decision(BUY, offer)
