"""One loot policy for the two family guilds: a guild handles loot like a guild.

WHY. Every path that sells an item to a vendor wrote its own rule, and each
rule was narrower than the guild's. The gate `bridge._epic_blocks` kept the
epics a member could wear and the bind-on-equip rares that were an upgrade,
and let everything else go to the vendor: a green or a blue nobody asked
about, an epic no class can wear, a soulbound piece the holder did not need.
Over a week the two guilds sold about 2,500 uncommon and 1,500 rare items
this way, and the same gate had let eight epics go before it existed.

THE POLICY, in priority order (the first rule that claims an item decides):

  1. An upgrade for anyone in the guild: equip it, or pass it to the
     guildmate it upgrades.                                        UPGRADE
  2. Somebody could use it, or nobody could: the guild bank or the auction
     house, a listing the bot posts itself.                    BANK_OR_AUCTION
     A piece nobody can use that is soulbound cannot go to either, so it is
     disenchanted.                                                DISENCHANT
  3. Vendor only gray (quality 0) and junk.                           VENDOR

`decide` is the whole policy: pure, rows in, a `Verdict` out. No MySQL, no
clock. `bridge._loot_policy_blocks` reads the facts and asks it once per item,
before every writer of a `sell`, `destroy` or `disenchant` row writes one.

USABLE means some member's class, level and proficiency could equip it (the
rule the epic gate already used: `bag_pressure._could_be_worn` at the level
cap, with the armour and weapon training `gear` knows), or it is a recipe,
reagent, consumable, trade good, gem or container, which the guild's trades
and bags use.

FAIL CLOSED. A fact that is unread, or a judge that could not answer, gives
HOLD: the item stays in the bags. Nothing here ever sells on a guess.

WHAT THIS DOES NOT DO. It decides; it does not move anything. The item plan
(`itemplan`), the guild jobs and the gear routing carry the routes out, each
as they already do. It grants nothing and lists nothing on the auction house
by itself: a listing is only ever one the bot posts from its own bags.
"""

from __future__ import annotations

from dataclasses import dataclass

import bag_pressure

VENDOR = "VENDOR"
UPGRADE = "UPGRADE"
BANK_OR_AUCTION = "BANK_OR_AUCTION"
DISENCHANT = "DISENCHANT"
HOLD = "HOLD"
ROUTES = (VENDOR, UPGRADE, BANK_OR_AUCTION, DISENCHANT, HOLD)

# item_template.Quality.
POOR = 0
COMMON = 1
# item_template.class values the guild's trades and bags use: consumable,
# container, gem, reagent, trade goods, recipe, quiver.
_GUILD_USED_CLASSES = frozenset({0, 1, 3, 5, 7, 9, 11})
_EQUIPMENT = bag_pressure.EQUIPMENT_CLASSES
_JUNK_CLASS = 15  # miscellaneous
_JUNK_SUBCLASS = 0  # "Junk"
_RECIPE_CLASS = 9
# item_template.bonding: 1 is bind on pickup, 4 is quest-bound.
_BOUND_ON_PICKUP = frozenset({1, 4})
_SOULBOUND = 0x1  # item_instance.flags bit 1


@dataclass(frozen=True)
class Verdict:
    """Where an item goes, and why, in words the log can print."""

    route: str
    why: str
    wanted_by: tuple = ()


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_junk(row: dict) -> bool:
    """A gray item, or an item the game itself files as junk."""
    quality = _int(row.get("quality"))
    if quality == POOR:
        return True
    return (
        quality == COMMON
        and _int(row.get("item_class")) == _JUNK_CLASS
        and _int(row.get("subclass")) == _JUNK_SUBCLASS
    )


def is_bound(row: dict) -> bool:
    """Soulbound already, or bound the moment it was picked up."""
    flags = _int(row.get("instance_flags")) or 0
    if flags & _SOULBOUND:
        return True
    return _int(row.get("bonding")) in _BOUND_ON_PICKUP


def _is_equipment(row: dict) -> bool:
    return (
        _int(row.get("item_class")) in _EQUIPMENT
        and (_int(row.get("inventory_type")) or 0) != 0
    )


def _wearable(row: dict, guild_classes) -> bool:
    """Could some member's class equip it at the cap, with its training?"""
    classes = bag_pressure._epic_wearer_classes(row, guild_classes)
    if not classes:
        return False
    level = _int(row.get("required_level"))
    if level is None or level > bag_pressure.GUILD_LEVEL_CAP:
        return False
    return bag_pressure._could_be_worn(
        row,
        _int(row.get("quality")),
        _int(row.get("item_class")),
        _int(row.get("inventory_type")),
        classes,
    )


def _can_disenchant(row: dict) -> bool:
    """Would the core let any enchanter break it down (class, quality, table)?"""
    return (
        _int(row.get("item_class")) in bag_pressure.DISENCHANT_CLASSES
        and _int(row.get("quality")) in bag_pressure.DISENCHANT_QUALITIES
        and (_int(row.get("disenchant_id")) or 0) > 0
    )


def decide(row: dict, guild_classes, upgrade=None) -> Verdict:
    """The policy's verdict for one carried item.

    `row` carries `quality`, `item_class`, `subclass`, `inventory_type`,
    `required_level`, `allowable_class`, `bonding`, `instance_flags`,
    `holder_class` and `disenchant_id`. `guild_classes` is every class among
    the guilds' members. `upgrade(row)` names the members whose own equip
    judge would put the piece on over what they wear now, or None when it
    could not be read; it is asked only for a piece some class could wear.
    """
    quality = _int(row.get("quality"))
    if quality is None:
        return Verdict(HOLD, "its quality could not be read")
    if is_junk(row):
        return Verdict(VENDOR, "gray or junk")
    equipment = _is_equipment(row)
    if (
        quality == COMMON
        and not equipment
        and _int(row.get("item_class")) != _RECIPE_CLASS
    ):
        return Verdict(VENDOR, "a common item no guild rule claims")
    if equipment and (
        _int(row.get("required_level")) is None
        or _int(row.get("inventory_type")) is None
    ):
        return Verdict(HOLD, "its gear facts could not be read")
    if equipment and _wearable(row, guild_classes):
        return _wearable_verdict(row, quality, upgrade)
    if quality == COMMON and equipment:
        return Verdict(VENDOR, "a common piece no guild class can wear")
    if _int(row.get("item_class")) in _GUILD_USED_CLASSES:
        return _shelve(row, "the guild's trades use it")
    return _shelve(row, "no guild member can use it")


def _wearable_verdict(row: dict, quality: int, upgrade) -> Verdict:
    """A piece some guild class could wear: an upgrade for somebody, or kept."""
    wanted = upgrade(row) if upgrade is not None else None
    if wanted is None:
        return Verdict(HOLD, "the guild's upgrade judge could not answer")
    if wanted:
        return Verdict(UPGRADE, "an upgrade for %s" % ", ".join(wanted), tuple(wanted))
    if quality == COMMON:
        return Verdict(VENDOR, "a common piece nobody would wear over their own")
    return _shelve(row, "a guild member could use it later")


def _shelve(row: dict, why: str) -> Verdict:
    """Bank or auction an item that can leave the bags, disenchant one that
    cannot; hold what is bound and cannot be broken down."""
    if not is_bound(row):
        return Verdict(BANK_OR_AUCTION, why + "; the guild bank or the auction house")
    if _can_disenchant(row):
        return Verdict(DISENCHANT, why + "; it is bound, so it is disenchanted")
    if _int(row.get("item_class")) in _GUILD_USED_CLASSES or _is_equipment(row):
        # Bound to its holder and wanted by the guild's trades or a later
        # level: the holder carries it, and no sale path may take it.
        return Verdict(HOLD, why + "; it is bound and stays with its holder")
    return Verdict(HOLD, why + "; it is bound and cannot be disenchanted")


def allowed(verdict: Verdict, kind: str) -> bool:
    """May a row of this kind be written for an item with this verdict?

    A `sell` or `destroy` is allowed only for VENDOR. A `disenchant` is
    allowed only for DISENCHANT, so an upgrade or something the guild bank
    could take is never broken down.
    """
    if kind == "disenchant":
        return verdict.route == DISENCHANT
    return verdict.route == VENDOR


def kept_line(row: dict, holder: str, verdict: Verdict, kind: str = "sell") -> str:
    """The one log line a refused row writes, naming the route it takes."""
    where = {
        UPGRADE: "gear routing hands it to the guildmate it upgrades",
        BANK_OR_AUCTION: "the item plan banks it or the bot posts it",
        DISENCHANT: "a disenchant carries it out",
        HOLD: "it stays in the bags",
    }.get(verdict.route, "it stays in the bags")
    return "kept %s for %s, no %s: %s (%s); %s" % (
        row.get("name") or "item %s" % row.get("item_guid"),
        holder,
        "vendor sale" if kind != "disenchant" else "disenchant",
        verdict.why,
        verdict.route,
        where,
    )
