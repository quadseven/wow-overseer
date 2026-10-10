"""Food and drink a guild member buys with its own gold, so it rests between
fights (2026-10-10).

WHY THIS EXISTS. Read on the dev realm on 2026-10-10 at 01:00 America/New_York:
Femur, a level 14 Bonkers priest in Silverpine Forest, had been level 14 for 117
hours and died 57 times in 24 hours, most of them to bears of levels 11 to 13.
His bags held no food and no drink. mod-playerbots rests a bot by its EatAction
and DrinkAction, and without the `food` cheat (the realm's BotCheats is empty,
and the alt maintenance that hands out food is off) both use only food and
drink the bot carries. A bot with none never sits down: it rises from its corpse
at half health and mana and pulls the next bear. 119 of the two guilds' 142
members carried no food or drink at all.

WHAT A PLAYER DOES. Buys a stack of the best food and water its level may use
at the inn or the food vendor, with its own gold, and eats and drinks between
pulls. This is that errand for one guild member: when it carries fewer than
LOW_UNITS of food, or of drink for a class that drinks, it walks to a friendly
vendor in reach, sells its junk there, and buys a handful of each, spending at
most half of its purse and the junk's price. Nothing is granted: the gold is
the member's own and the vendor is the world's.

WHICH VENDOR AND WHICH TIER (`plan`). The vendor that sells the most of what
the member wants, then the nearest. At that vendor, for each kind, the highest
tier whose required level the member has and of which its budget buys at least
MIN_UNITS, up to a STACK. A kind's budget is the half share split evenly over
the kinds wanted. A buy row counts purchases of the item's BuyCount, as the
module's `buy` grammar does, and its ceiling is the whole price.

PURE MODULE: facts in, buys out. No MySQL, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

# The step's action word, in the command log's source (guildjobs.source_for).
ACTION = "supply"

# The game's own classification: item_template.spellcategory_1 is 11 for what
# is eaten and 59 for what is drunk (towntrip.CONSUMABLE_CATEGORY_*), the two
# numbers mod-playerbots' EatAction and DrinkAction look for.
FOOD_CATEGORY = 11
DRINK_CATEGORY = 59
KIND_WORDS = {FOOD_CATEGORY: "food", DRINK_CATEGORY: "drink"}

# The classes whose resource is mana: priest, mage, paladin, druid, shaman,
# hunter, warlock (towntrip.MANA_CLASSES, by class id). Only they drink.
MANA_CLASS_IDS = frozenset({2, 3, 5, 7, 8, 9, 11})

# A member carrying fewer units than this of a kind wants that kind.
LOW_UNITS = 5
# Never a trip for fewer than this many units of a kind, and never more than a
# stack (one bag slot).
MIN_UNITS = 5
STACK = 20
# At most this share of the purse and the junk's price goes on food and drink.
PURSE_SHARE = (1, 2)

# New supply steps one guild starts in one pass.
STEPS_PER_GUILD = 6


@dataclass(frozen=True)
class Buy:
    """One purchase: `count` lots of `entry` at `vendor`, `units` items in all,
    for at most `ceiling` copper."""

    vendor: int
    vendor_name: str
    entry: int
    name: str
    category: int
    count: int
    units: int
    ceiling: int

    @property
    def command(self) -> str:
        """The kind='buy' row the module's DoBuy reads."""
        return "entry:%d count:%d max:%d" % (self.entry, self.count, self.ceiling)


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def wanted(member) -> tuple:
    """The categories this member is short of, drink first for a class that
    drinks; () while its bags are unread."""
    food = getattr(member, "food", None)
    drink = getattr(member, "drink", None)
    out = []
    if _int(member.class_id) in MANA_CLASS_IDS and drink is not None:
        if int(drink) < LOW_UNITS:
            out.append(DRINK_CATEGORY)
    if food is not None and int(food) < LOW_UNITS:
        out.append(FOOD_CATEGORY)
    return tuple(out)


def budget(member, junk) -> int:
    """Copper the member spends on food and drink: PURSE_SHARE of its purse and
    of what its junk sells for at the same counter."""
    numerator, denominator = PURSE_SHARE
    total = max(0, _int(member.money)) + max(0, _int(junk))
    return total * numerator // denominator


def _pick(level, rows, category, copper):
    """The Buy of one kind from one vendor's `rows` for `copper`, or None."""
    fits = [
        r
        for r in rows
        if _int(r.get("category")) == category
        and _int(r.get("required_level")) <= int(level)
        and _int(r.get("price")) > 0
        and _int(r.get("buy_count"), 1) > 0
    ]
    fits.sort(key=lambda r: (-_int(r.get("required_level")), _int(r.get("price"))))
    for r in fits:
        price, lot = _int(r.get("price")), _int(r.get("buy_count"), 1)
        lots = min(copper // price, -(-STACK // lot))
        while lots > 0 and lots * lot > STACK:
            lots -= 1
        if lots * lot < MIN_UNITS:
            continue
        return Buy(
            vendor=_int(r.get("vendor")),
            vendor_name=str(r.get("vendor_name") or ""),
            entry=_int(r.get("entry")),
            name=str(r.get("item_name") or ""),
            category=category,
            count=lots,
            units=lots * lot,
            ceiling=lots * price,
        )
    return None


def plan(member, rows, junk=0) -> tuple:
    """(buys, why not) for one member: the Buys at one vendor in reach, or ()
    and the reason when nothing is bought. `rows` are the friendly vendors'
    food and drink in reach (bridge._SUPPLY_VENDOR_SQL); `junk` the copper its
    junk sells for at the counter."""
    kinds = wanted(member)
    if not kinds:
        return (), ""
    words = " and ".join(KIND_WORDS[k] for k in kinds)
    if not rows:
        return (), "no vendor in reach sells %s %s" % (member.name, words)
    each = budget(member, junk) // len(kinds)
    vendors = {}
    for r in rows:
        vendors.setdefault(_int(r.get("vendor")), []).append(r)
    best = None
    for vendor, stock in vendors.items():
        buys = tuple(
            b for b in (_pick(member.level, stock, k, each) for k in kinds) if b
        )
        if not buys:
            continue
        yards = min(float(r.get("yards") or 0.0) for r in stock)
        key = (-len(buys), yards, vendor)
        if best is None or key < best[0]:
            best = (key, buys)
    if best is None:
        return (
            (),
            "%s cannot afford %d of the %s a vendor in reach sells (%d copper)"
            % (
                member.name,
                MIN_UNITS,
                words,
                budget(member, junk),
            ),
        )
    return best[1], ""


def said(member, buys) -> str:
    """The sentence the pass logs for a supply walk."""
    kinds = " and ".join(KIND_WORDS[b.category] for b in buys)
    if len(buys) == 2:
        kinds = "food and drink"
    return (
        "%s walks to %s to buy %s with its own gold, so it rests between fights: %s"
        % (
            member.name,
            buys[0].vendor_name or "a vendor",
            kinds,
            ", ".join("%d %s" % (b.units, b.name or "item %d" % b.entry) for b in buys),
        )
    )
