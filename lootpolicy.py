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
     TRULY TRASH is disenchanted too: an unbound uncommon-to-epic piece that
     upgrades nobody, whose expected auction value is under `TRASH_CEILING`
     copper, and that a guild enchanter's Enchanting skill can break down
     (`decide`'s `auction_value` and `enchanters` judges). A worthwhile piece
     keeps BANK_OR_AUCTION, and so does a piece no enchanter can break down:
     it is never vendored.
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
# "Truly trash" ceiling: an unbound piece whose expected auction value is under
# this many copper (one gold) is disenchanted for enchanting materials rather
# than shelved. It is twice itemplan.AUCTION_MIN_GAIN, the least a listing must
# clear over the vendor for the item plan to list at all, so a piece the plan
# would not bother to list is not worth shelving either.
TRASH_CEILING = 10_000


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
    flags = _int(row.get("instance_flags"))
    bonding = _int(row.get("bonding"))
    if flags is None or bonding is None:
        return True  # unread binding: treated as bound, the cautious answer
    return bool(flags & _SOULBOUND) or bonding in _BOUND_ON_PICKUP


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


def decide(
    row: dict, guild_classes, upgrade=None, auction_value=None, enchanters=None
) -> Verdict:
    """The policy's verdict for one carried item.

    `row` carries `quality`, `item_class`, `subclass`, `inventory_type`,
    `required_level`, `allowable_class`, `bonding`, `instance_flags`,
    `holder_class`, `quest_needed` and `disenchant_id`. `guild_classes` is every class among
    the guilds' members. `upgrade(row)` names the members whose own equip
    judge would put the piece on over what they wear now, or None when it
    could not be read; it is asked only for a piece some class could wear.
    `auction_value(row)` is the item's expected auction copper, None when it
    could not be read; `enchanters()` is {name: Enchanting skill} for the guild
    enchanters, None or empty when there are none. Both are asked only for an
    unbound, disenchantable piece, and without them it is shelved, never broken
    down: a missing judge never turns a piece into trash.
    """
    if "quest_needed" in row:
        # A quest in the holder's log names the item (the item is the quest's
        # source, drop or required item): it stays, whatever its class or
        # quality, because the quest cannot be finished without it. Unread is
        # held too.
        needed = row.get("quest_needed")
        if needed is None:
            return Verdict(HOLD, "its quest log could not be read")
        if needed:
            return Verdict(HOLD, "a quest in the holder's log names it")
    quality = _int(row.get("quality"))
    if quality is None:
        return Verdict(HOLD, "its quality could not be read")
    if _int(row.get("instance_flags")) is None or _int(row.get("bonding")) is None:
        # Fail closed before ANY verdict, a vendor one included: an item whose
        # binding was never read is kept (item plan rule R1).
        return Verdict(HOLD, "its binding could not be read")
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
    if equipment and not bag_pressure._epic_wearer_classes(row, guild_classes):
        # No class to judge it against: the guild's classes were not read (or
        # a soulbound piece has no known holder class). Unknown is not "nobody".
        return Verdict(HOLD, "the guild's classes could not be read")
    if equipment and _wearable(row, guild_classes):
        return _wearable_verdict(row, quality, upgrade, auction_value, enchanters)
    if quality == COMMON and equipment:
        return Verdict(VENDOR, "a common piece no guild class can wear")
    if _int(row.get("item_class")) in _GUILD_USED_CLASSES:
        return _shelve(row, "the guild's trades use it", usable=True)
    return _shelve(row, "no guild member can use it", False, auction_value, enchanters)


def _wearable_verdict(
    row: dict, quality: int, upgrade, auction_value=None, enchanters=None
) -> Verdict:
    """A piece some guild class could wear: an upgrade for somebody, or kept."""
    wanted = upgrade(row) if upgrade is not None else None
    if wanted is None:
        return Verdict(HOLD, "the guild's upgrade judge could not answer")
    if wanted and is_bound(row):
        # A bound copy cannot be handed on (gear routing skips it): it can
        # only upgrade the member who holds it, who equips it themselves.
        holder = row.get("holder")
        wanted = tuple(name for name in wanted if holder and name == holder)
    if wanted:
        return Verdict(UPGRADE, "an upgrade for %s" % ", ".join(wanted), tuple(wanted))
    if quality == COMMON:
        return Verdict(VENDOR, "a common piece nobody would wear over their own")
    return _shelve(
        row, "a guild member could use it later", True, auction_value, enchanters
    )


def _breakable_by(row: dict, enchanters):
    """The guild enchanter (highest skill, then name) whose Enchanting reaches
    the core's RequiredDisenchantSkill for this piece, or None."""
    need = _int(row.get("disenchant_skill"))
    if need is None or need < 0 or not enchanters:
        return None
    able = sorted(
        (name for name, skill in enchanters.items() if (_int(skill) or 0) >= need),
        key=lambda name: (-(_int(enchanters[name]) or 0), name),
    )
    return able[0] if able else None


def _truly_trash(row: dict, auction_value, enchanters):
    """The enchanter who should break this unbound piece down, or None when it
    is worth shelving or nobody can break it down. Unread means shelved."""
    if not (_is_equipment(row) and _can_disenchant(row)) or auction_value is None:
        return None
    value = auction_value(row)
    if value is None or value >= TRASH_CEILING:
        return None
    # The judge answers a read failure itself (an empty answer); a bug in it
    # is not caught here.
    skills = enchanters() if enchanters is not None else None
    return _breakable_by(row, skills)


def _shelve(
    row: dict, why: str, usable: bool = False, auction_value=None, enchanters=None
) -> Verdict:
    """Bank or auction an item that can leave the bags. A bound piece nobody
    can use is disenchanted; a bound piece somebody could use stays with its
    holder; what is bound and cannot be broken down is held. An unbound piece
    that is truly trash (worth little, upgrades nobody, an enchanter can break
    it down) is disenchanted too."""
    if not is_bound(row):
        breaker = _truly_trash(row, auction_value, enchanters)
        if breaker:
            return Verdict(
                DISENCHANT,
                why
                + "; worth under %d copper, so %s disenchants it"
                % (TRASH_CEILING, breaker),
            )
        return Verdict(BANK_OR_AUCTION, why + "; the guild bank or the auction house")
    if usable:
        return Verdict(HOLD, why + "; it is bound and stays with its holder")
    if _can_disenchant(row):
        return Verdict(DISENCHANT, why + "; it is bound, so it is disenchanted")
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
