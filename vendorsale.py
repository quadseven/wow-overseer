"""What a guild member sells at a vendor, on every visit (#771).

WHY THIS EXISTS. Read on the dev realm on 2026-10-10 between 14:00 and 15:10
America/New_York, over the 132 members of the two family guilds off the
roster:

  * 118 of them had more than 80% of their bag slots full, and 69 had one free
    slot or none. mod-playerbots' StoreLootAction (LootAction.cpp) skips every
    item that does not stack once "bag space" passes 80% for a bot with no
    real master, and a stackable one unless a stack of it has room, so those
    members left their grey, white and green drops on the corpse. Coin is
    looted whatever the bags hold.
  * The bags held about 116 gold at a vendor: 1,116 slots of white trade goods
    (27g, mostly meat, eggs and stingers), 189 slots of gems (10g), 199 green
    and 51 blue weapons and armor.
  * Members sold 2.5 gold in a day between them, because the guild jobs sold
    only grey stacks and white gear ten levels outgrown. The auction house has
    no buyers, and nothing else takes a white material that no guild crafter
    eats.

WHAT A PLAYER DOES. At every vendor it visits, it sells what it looted and has
no use for, and keeps quest items, the gear that would be an upgrade, and what
its trade or its guild will use. So every vendor visit of a guild member (the
gear walk, the food and drink walk, the sale walk and the make-room walk) sells
the stacks `verdict` lets go, priciest first.

THE RULE (`verdict`), the first line that applies:

  * no sell price                            keep: no vendor buys it
  * protected (a class quest item, a trade   keep
    tool, a Soul Shard, what the member's
    own trade casts eat)
  * grey                                     sell
  * a bag, reagent, ammunition, quiver,      keep
    quest item or key
  * food, drink, potions and the rest of     keep: its own AI eats and drinks
    the consumables                          them
  * a pet or a mount (miscellaneous)         keep
  * other miscellaneous junk                 sell
  * rare or better weapon or armor           keep: guild loot, for the loot
                                             council and the bank
  * weapon or armor OUTGROWN_LEVELS under    sell
    the member's level
  * a ring, neck, trinket or other piece     keep: gear.py cannot weigh the
    with no slot bucket                      slot
  * weapon or armor while the worn gear is   keep
    unread
  * weapon or armor the member would wear    keep: an upgrade
    within LOOKAHEAD_LEVELS (gear.would_wear,
    the family's own test)
  * other weapon or armor                    sell: not an upgrade
  * a trade good, gem or recipe while the    keep
    bank forecast is unread
  * a trade good, gem or recipe the bank     keep
    forecast reserves (bankforecast.py)
  * a recipe the forecast did not judge      keep
  * other trade goods and gems               sell: the guild holds it past
                                             what it will use
  * anything else                            keep

NATURAL ONLY. The member sells its own loot to the world's vendor for the
world's price.

PURE MODULE: items and facts in, a verdict out. No MySQL, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

import bag_pressure

# item_template.class
CONSUMABLE = 0
CONTAINER = 1
WEAPON = 2
GEM = 3
ARMOR = 4
REAGENT = 5
PROJECTILE = 6
TRADE_GOODS = 7
RECIPE = 9
QUIVER = 11
QUEST = 12
KEY = 13
MISC = 15

# item_template.Quality
POOR = 0
RARE = 3

# The classes a member never sells, and why (the verdict's words).
KEPT_CLASSES = {
    CONTAINER: "a bag",
    REAGENT: "a reagent its spells use",
    PROJECTILE: "ammunition",
    QUIVER: "a quiver",
    QUEST: "a quest item",
    KEY: "a key",
}
# Miscellaneous subclasses: 0 is junk (sold), 2 a companion pet and 5 a mount
# (kept); the rest (reagents, holiday items, other) are kept.
MISC_JUNK = 0
MISC_KEPT = {2: "a companion pet", 5: "a mount"}
# The classes the bank forecast judges (bankforecast.judge).
FORECAST_CLASSES = frozenset({TRADE_GOODS, GEM, RECIPE})

# A weapon or armor piece this many item levels under its holder is outgrown,
# whatever its quality (guildjobs.OUTGROWN_LEVELS for white gear).
OUTGROWN_LEVELS = 10
# A piece the member would wear within this many levels is kept.
LOOKAHEAD_LEVELS = 3

SELL = True
KEEP = False


@dataclass(frozen=True)
class Judge:
    """What one member's verdicts are judged against.

    `worn` is the member's gear.CharacterState, None while its worn gear is
    unread (no weapon or armor short of outgrown is then sold). `reserved` is
    the set of entries the guild's bank forecast keeps, None while the forecast
    is unread (no trade good, gem or recipe is then sold). `protected` are the
    entries never sold at all.
    """

    level: int
    worn: object = None
    reserved: frozenset | None = None
    protected: frozenset = frozenset()


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _gear_verdict(item, judge: Judge) -> tuple:
    quality = _int(item.quality)
    if quality >= RARE:
        return KEEP, "guild loot, for the loot council and the bank"
    item_level = _int(getattr(item, "item_level", 0))
    if 0 < item_level <= _int(judge.level) - OUTGROWN_LEVELS:
        return SELL, "outgrown (item level %d at level %d)" % (item_level, judge.level)
    if not bag_pressure.has_slot_bucket(item):
        return KEEP, "a piece gear.py cannot weigh against the worn one"
    if judge.worn is None:
        return KEEP, "its worn gear is unread"
    wears, why = bag_pressure.holder_would_wear(
        item, judge.worn, _int(judge.level) + LOOKAHEAD_LEVELS
    )
    if wears:
        return KEEP, "an upgrade: %s" % why
    if why.startswith("not an upgrade"):
        return SELL, why
    return SELL, "not an upgrade: %s" % why


def _forecast_verdict(item, judge: Judge) -> tuple:
    if judge.reserved is None:
        return KEEP, "the bank forecast is unread"
    if _int(item.entry) in judge.reserved:
        return KEEP, "the guild's bank forecast keeps it"
    if _int(item.item_class) == RECIPE:
        return KEEP, "a recipe the bank forecast did not judge"
    return SELL, "the guild holds it past what it will use"


def verdict(item, judge: Judge) -> tuple:
    """(SELL or KEEP, why) for one carried stack. See THE RULE above."""
    if _int(item.sell_price) <= 0:
        return KEEP, "no vendor buys it"
    if _int(item.entry) in judge.protected:
        return KEEP, "protected"
    if _int(item.quality) == POOR:
        return SELL, "grey"
    item_class = _int(item.item_class)
    if item_class in KEPT_CLASSES:
        return KEEP, KEPT_CLASSES[item_class]
    if item_class == CONSUMABLE:
        return KEEP, "its own AI eats, drinks or uses it"
    if item_class == MISC:
        subclass = _int(item.subclass)
        if subclass == MISC_JUNK:
            return SELL, "junk"
        return KEEP, MISC_KEPT.get(subclass, "a miscellaneous item")
    if item_class in (WEAPON, ARMOR):
        return _gear_verdict(item, judge)
    if item_class in FORECAST_CLASSES:
        return _forecast_verdict(item, judge)
    return KEEP, "not a kind a member sells"


def sells(item, judge: Judge) -> bool:
    return verdict(item, judge)[0] is SELL


def worth(items) -> int:
    """Copper the stacks bring at the counter."""
    return sum(_int(i.sell_price) * max(1, _int(i.count, 1)) for i in items or ())
