"""Plan auction gear for empty equipment slots (#146, #147).

The planner is pure: it only spends a character's own purse on equipment
they can wear now, and keeps the same repair reserve and bounded spending
discipline as the other town purchases.
"""

from dataclasses import dataclass


SLOT_TYPES = {
    1: ("head",),
    2: ("neck",),
    3: ("shoulder",),
    5: ("chest",),
    20: ("chest",),
    6: ("waist",),
    7: ("legs",),
    8: ("feet",),
    9: ("wrist",),
    10: ("hands",),
    11: ("finger1", "finger2"),
    12: ("trinket1", "trinket2"),
    13: ("mainhand", "offhand"),
    17: ("mainhand",),
    21: ("mainhand",),
    14: ("offhand",),
    22: ("offhand",),
    23: ("offhand",),
    15: ("ranged",),
    16: ("back",),
    25: ("ranged",),
    26: ("ranged",),
    28: ("ranged",),
}

EARLY_LEVEL_MAX = 24
EARLY_LEVEL_EMPTY_SLOTS = 9


def campaign_hold(
    facts, in_run, held_seconds=0, empty_slots=6, min_purse=20000, ceiling=45 * 60
):
    """Whether an active campaign should yield to the town gear errand (#146, #147).

    A family already in a dungeon finishes that run first. Gear-short members
    with enough purse, or with bought equipment waiting in the mailbox
    (`mail_gear`), hold the next run, but the bag-withhold ceiling releases
    the campaign if town shopping cannot clear the condition.
    """
    if in_run or held_seconds >= ceiling:
        return False
    for character in (facts or {}).values():
        funded = character["purse"] >= min_purse or character.get("mail_gear", 0) > 0
        if needs_gear_hold(character, empty_slots=empty_slots) and funded:
            return True
    return False


def needs_gear_hold(character, empty_slots=6) -> bool:
    """Whether this member has a gear gap worth holding the next run for.

    An empty main hand is a critical equipment gap on its own. Otherwise the
    campaign keeps the existing empty-slot threshold. `equipped` is the named
    slot mapping returned by the bridge's gear-facts reader.
    """
    equipped = _get(character, "equipped", default={}) or {}
    worn = [slot for slot in equipped if slot not in ("shirt", "tabard")]
    level = int(_get(character, "level", default=0) or 0)
    threshold = (
        max(empty_slots, EARLY_LEVEL_EMPTY_SLOTS)
        if 0 < level <= EARLY_LEVEL_MAX
        else empty_slots
    )
    return "mainhand" not in worn or 17 - len(worn) >= threshold


CLASS_IDS = {
    "warrior": 1,
    "paladin": 2,
    "hunter": 3,
    "rogue": 4,
    "priest": 5,
    "death_knight": 6,
    "shaman": 7,
    "mage": 8,
    "warlock": 9,
    "druid": 11,
}
WEAPON_SUBCLASS = {
    "axe": 0,
    "two-handed axe": 1,
    "bow": 2,
    "gun": 3,
    "mace": 4,
    "two-handed mace": 5,
    "polearm": 6,
    "sword": 7,
    "two-handed sword": 8,
    "staff": 10,
    "fist": 13,
    "dagger": 15,
    "thrown": 16,
    "crossbow": 18,
    "wand": 19,
    "fishing pole": 20,
}
SHIELD_CLASSES = {1, 2, 7}

# THE COSMETIC SLOTS ARE NOT GEAR. A shirt (slot 3) and a tabard (slot 18) carry
# no stats, so they neither count as empty nor get bought.
GEAR_SLOT_COUNT = 17
COSMETIC_SLOTS = {3, 18}

# CLASSIC ARMOR RULES, by item_template.subclass for class 4 (armor):
# 0 miscellaneous (rings, necks, trinkets, held items), 1 cloth, 2 leather,
# 3 mail, 4 plate, 6 shield. Warriors and paladins wear mail from the start and
# plate at 40; hunters and shamans wear mail at 40.
LEATHER_CLASSES = {1, 2, 3, 4, 7, 11}
MAIL_FROM_START = {1, 2}
MAIL_AT_40 = {3, 7}
PLATE_AT_40 = {1, 2}


def empty_gear_slots(equipped_slots) -> int:
    """How many of the 17 stat-bearing slots are empty, from worn slot numbers."""
    worn = {int(s) for s in equipped_slots if int(s) not in COSMETIC_SLOTS}
    return GEAR_SLOT_COUNT - len(worn)


@dataclass(frozen=True)
class Buy:
    character: str
    slot: str
    listing_id: int
    entry: int
    buyout: int
    item_level: int
    item_class: int = 0
    item_subclass: int = 0


def _get(row, *keys, default=None):
    for key in keys:
        if key in row:
            return row[key]
    return default


# NOT GEAR, THOUGH item_template FILES THEM AS WEAPONS. A fishing pole
# (subclass 20) and the miscellaneous tools (subclass 14: a Blacksmith Hammer, a
# Mining Pick) are two-handers and main-hand pieces to the slot rules, and a
# character with the fishing skill passes the skill test for the pole. Measured
# on the dev realm on 2026-09-27: the level 35 mage bought a Strong Fishing Pole
# for his empty main hand twice, and the errand walked the family to the
# fishing supplier at the mailbox instead of the weaponsmith 128 yards off.
NOT_GEAR_WEAPONS = frozenset({14, 20})

# A piece this many levels below the buyer is not worth a slot or a coin: the
# holiday masks and starting-zone whites a level 35 character should walk past.
MAX_LEVELS_BEHIND = 25
AUCTION_STALE_GEAR_LEVEL_GAP = 10
AUCTION_MIN_UPGRADE_LEVELS = 3


def _allowed(character, item):
    level = int(_get(character, "level", default=0) or 0)
    cls = _get(character, "class", "class_id")
    cls_id = CLASS_IDS.get(str(cls).lower(), int(cls) if str(cls).isdigit() else 0)
    if not _level_and_class_ok(item, cls_id, level):
        return False
    item_level = int(_get(item, "ItemLevel", "item_level", default=0) or 0)
    if item_level < max(2, level - MAX_LEVELS_BEHIND):
        return False
    kind = int(_get(item, "class", "item_class", default=-1) or 0)
    sub = int(_get(item, "subclass", default=-1) or 0)
    inv = int(_get(item, "InventoryType", "inventory_type", default=0) or 0)
    if kind == 4:
        return _armor_ok(cls_id, sub, inv, level)
    if kind == 2:
        return _weapon_ok(character, sub)
    return False


def _level_and_class_ok(item, cls_id, level):
    if int(_get(item, "RequiredLevel", "required_level", default=0) or 0) > level:
        return False
    allowed = int(_get(item, "AllowableClass", "allowable_class", default=0) or 0)
    return allowed in (-1, 0) or bool(allowed & (1 << (cls_id - 1)))


def _armor_ok(cls_id, sub, inv, level):
    if inv == 14:
        return cls_id in SHIELD_CLASSES
    if sub in (0, 1):
        return True
    rules = {
        2: LEATHER_CLASSES,
        3: MAIL_FROM_START | (MAIL_AT_40 if level >= 40 else set()),
        4: PLATE_AT_40 if level >= 40 else set(),
    }
    return cls_id in rules.get(sub, set())


def _weapon_ok(character, sub):
    if sub in NOT_GEAR_WEAPONS:
        return False
    skills = _get(character, "skills", default={}) or {}
    allowed = _get(skills, "weapons", default=skills.get("weapon_types", ()))
    return sub in allowed or WEAPON_SUBCLASS.get(str(sub).lower()) in allowed


def plan_buys(characters, listings, *, repair_floor=0):
    """Return best affordable buyouts for empty slots or gear upgrades.

    ONE LISTING, ONE BUYER. An auction can be bought once, and every member
    reads the same listings in the same order, so two members who want the
    same slot plan the same auction. Measured on the dev realm on 2026-09-26:
    the paladin's buys went first and took the listings, and the warrior's
    eight planned purchases for the same slots all came back `auction not
    found`, which the retry window then held for thirty minutes. Each member
    is planned against what the members before it have not already taken.
    """
    output = []
    taken = set()
    ordered = sorted(listings, key=_listing_order)
    for name, character in sorted(characters.items()):
        buys = _plan_character(
            name,
            character,
            ordered,
            _budget_for(name, character, repair_floor),
            taken,
        )
        taken.update(b.listing_id for b in buys)
        output.extend(buys)
    return tuple(output)


def plan_vendor_buys(characters, offers, *, repair_floor=0, replace_stale=False):
    """Buy vendor equipment for EMPTY slots only, from each member's own reach.

    THE VENDOR IS THE PATH THAT IS ALWAYS OPEN. The auction house needs a walk
    to one counter in a capital and delivers by post; an armour merchant sells
    over the counter, into the bags, where the module's equip drive puts the
    piece on. Measured on the dev realm on 2026-09-27: the Alliance mage and
    priest wore five and six of seventeen slots at level 35, never stood at an
    auctioneer when the gear errand shopped, and each carried ten gold.

    `offers` is name -> the item rows the vendors within that member's reach
    stock, each with `entry` and `buyout` (the vendor price). A white from a
    vendor is rarely better than a worn green, so a worn slot is never
    replaced here: every worn slot reads as better than anything on offer. The
    same class, level, armour and budget rules as `plan_buys` apply.

    `replace_stale` is the exception, for guild members (guildjobs.gear_step):
    on wow-dev on 2026-10-03 they died at levels 10 to 21 in seven pieces
    averaging item level 3 to 5, a full set of slots nothing would replace. A
    worn piece AUCTION_STALE_GEAR_LEVEL_GAP or more levels behind its wearer
    may then be replaced by anything better.
    """
    output = []
    for name, character in sorted(characters.items()):
        rows = sorted(
            (
                dict(row, id=int(_get(row, "entry", default=0) or 0))
                for row in (offers.get(name) or ())
            ),
            key=_listing_order,
        )
        if not rows:
            continue
        equipped = _get(character, "equipped", "slots", default={}) or {}
        if shield_short(character):
            equipped = {s: v for s, v in equipped.items() if s != "offhand"}
            character = dict(character, equipped=equipped)
        # `replace_stale` keeps what is worn, so `_worn_is_better` lets a piece
        # AUCTION_STALE_GEAR_LEVEL_GAP or more levels behind the wearer go.
        worn_only = (
            character
            if replace_stale
            else dict(
                character,
                equipped={
                    slot: equipped[slot] if slot == "offhand" else None
                    for slot in equipped
                },
            )
        )
        output.extend(
            _plan_character(
                name, worn_only, rows, _budget_for(name, character, repair_floor)
            )
        )
    return tuple(output)


# A member with at least this many empty stat slots is worth a walk to an
# armour merchant. Fewer than that and the next quest reward or drop is as
# likely to fill them as a white off a counter.
VENDOR_TRIP_EMPTY_SLOTS = 3
# The walk cap, the bag trip's: a vendor in the same town or the next one.
VENDOR_TRIP_MAX_YARDS = 500.0
# Standing this close to the vendor is already there: the buy waits for reach.
VENDOR_TRIP_HERE_YARDS = 10.0
TWO_HAND_OFFHAND_MARGIN = 10


@dataclass(frozen=True)
class VendorTrip:
    """Where to walk the family so gear-short members can buy at a counter."""

    vendor: int = 0
    name: str = ""
    yards: float = 0.0
    buyers: tuple = ()
    here: bool = False
    why_not: str = ""


def vendor_trip(
    characters,
    rows,
    *,
    map_id,
    repair_floor=0,
    max_yards=VENDOR_TRIP_MAX_YARDS,
    skip=frozenset(),
    replace_stale=False,
):
    """The vendor on the leader's map worth the walk for the short members.

    THE WALK THE VENDOR HALF WAS MISSING. `plan_vendor_buys` buys only where a
    member already stands, and the family rarely stands at an armour merchant:
    measured on the dev realm on 2026-09-27, not one vendor buy in the first
    half hour. This picks a counter to walk to, from the world's own spawn and
    stock tables (`rows`, one per vendor and item, measured from the leader),
    and never a coordinate: the aim is the vendor's creature entry, resolved
    by the module to a spawn that will deal with the character.

    A WEAPON FIRST, THEN THE MOST PIECES, THEN THE NEAREST. The nearest vendor
    that sold anybody anything used to win, and in Ratchet that was the fishing
    supplier sixteen yards from the mailbox: the mage bought a fishing pole
    and the weaponsmith was never visited (dev realm, 2026-09-27). So a vendor
    that puts a weapon in an empty main hand beats one that does not, then the
    vendor that fills more slots, and only then the nearer one. `skip` is the
    vendors this errand already bought at, so the next call names the next.

    `characters` are the gear facts of the members on the leader's map. Only a
    member with VENDOR_TRIP_EMPTY_SLOTS or more empty slots, or no main hand,
    counts, and a vendor counts only if `plan_vendor_buys` would buy that
    member something there with its own gold, under the same budget rules.
    """
    short = {
        name: c
        for name, c in (characters or {}).items()
        if gear_short(c) or shield_short(c) or (replace_stale and stale_gear(c))
    }
    if not short:
        return VendorTrip(
            why_not="nobody on the leader's map has %d or more empty slots"
            % VENDOR_TRIP_EMPTY_SLOTS
        )
    ranked = []
    for vendor, (name, yards, stock) in _vendors(rows, map_id, max_yards, skip).items():
        buys = plan_vendor_buys(
            short,
            {n: stock for n in short},
            repair_floor=repair_floor,
            replace_stale=replace_stale,
        )
        if buys:
            weapons = sum(1 for b in buys if b.slot == "mainhand")
            key = (-weapons, -len(buys), yards, vendor)
            ranked.append((key, vendor, name, yards, buys))
    if not ranked:
        return VendorTrip(
            why_not="no vendor within %d yards sells a short member a piece it "
            "can wear and afford" % int(max_yards)
        )
    _key, vendor, name, yards, buys = min(ranked)
    return VendorTrip(
        vendor=vendor,
        name=name,
        yards=yards,
        buyers=tuple(sorted({b.character for b in buys})),
        here=yards <= VENDOR_TRIP_HERE_YARDS,
    )


def _vendors(rows, map_id, max_yards, skip) -> dict:
    """vendor -> [name, nearest yards, stock rows], on the map and in reach."""
    vendors: dict = {}
    for row in rows or ():
        try:
            vendor = int(row["vendor"])
            where = (str(row.get("vendor_name") or ""), int(row["map_id"]))
            yards = float(row["yards"])
        except (KeyError, TypeError, ValueError):
            continue
        if where[1] != int(map_id) or yards > max_yards or vendor in skip:
            continue
        seen = vendors.setdefault(vendor, [where[0], yards, []])
        seen[1] = min(seen[1], yards)
        seen[2].append(row)
    return vendors


def stock_of(rows, vendor) -> set:
    """The item entries one vendor stocks, from `vendor_trip`'s rows."""
    out = set()
    for row in rows or ():
        try:
            if int(row["vendor"]) == int(vendor):
                out.add(int(row["entry"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


_SLOT_NUMBERS = {
    "head": 0, "neck": 1, "shoulder": 2, "shirt": 3, "chest": 4, "waist": 5,
    "legs": 6, "feet": 7, "wrist": 8, "hands": 9, "finger1": 10,
    "finger2": 11, "trinket1": 12, "trinket2": 13, "back": 14,
    "mainhand": 15, "offhand": 16, "ranged": 17, "tabard": 18,
}  # fmt: skip


def _slot_numbers(character) -> list:
    equipped = _get(character, "equipped", "slots", default={}) or {}
    return [_SLOT_NUMBERS[s] for s in equipped if s in _SLOT_NUMBERS]


def vendor_command(buy) -> str:
    """The kind='buy' row DoBuy reads: one piece, capped at the list price."""
    return "entry:%d count:1 max:%d" % (int(buy.entry), int(buy.buyout))


def _listing_order(row):
    return (
        -int(_get(row, "ItemLevel", "item_level", default=0) or 0),
        int(_get(row, "buyout", default=0) or 0),
        int(_get(row, "id", "listing_id", "auction_id", default=0) or 0),
    )


def _budget_for(name, character, reserve):
    purse = int(_get(character, "purse", "money", default=0) or 0)
    amount = reserve.get(name, 0) if isinstance(reserve, dict) else reserve
    return purse, max(0, min(purse * 0.6, purse - int(amount)))


# A WARRIOR OR PALADIN WHO TANKS CARRIES A SHIELD (#550, after #549). The guild
# gear step asks its own question of such a member: is the off hand holding a
# shield? `shield_tank` in the member's facts says it tanks (the roster's tree,
# a raid seat or the raid plan's tree); `shield_carried` says a shield already
# sits in its bags, which the module's equip drive puts on, so none is bought.
SHIELD_TANK_CLASSES = {1, 2}


def _class_id(character) -> int:
    cls = _get(character, "class", "class_id")
    return CLASS_IDS.get(str(cls).lower(), int(cls) if str(cls).isdigit() else 0)


def _worn_shield(character) -> bool:
    equipped = _get(character, "equipped", "slots", default={}) or {}
    offhand = equipped.get("offhand")
    return (
        isinstance(offhand, dict)
        and int(offhand.get("item_class") or 0) == 4
        and int(offhand.get("item_subclass") or 0) == 6
    )


# WEAPON SUBCLASSES THAT TAKE BOTH HANDS: axe, mace, polearm, sword, staff
# and fishing pole (item_template class 2). A worn piece carries its class and
# subclass, not its InventoryType, so this is how a two-hander is read.
TWO_HAND_SUBCLASSES = {1, 5, 6, 8, 10, 20}


def holds_two_hander(character) -> bool:
    worn = (_get(character, "equipped", "slots", default={}) or {}).get("mainhand")
    return (
        isinstance(worn, dict)
        and int(worn.get("item_class") or 0) == 2
        and int(worn.get("item_subclass") or -1) in TWO_HAND_SUBCLASSES
    )


def _shield_tank(character) -> bool:
    return (
        bool(_get(character, "shield_tank", default=False))
        and _class_id(character) in SHIELD_TANK_CLASSES
    )


def tank_two_hander(character) -> bool:
    """A shield tank holding a two-hander: its main hand counts as empty, so a
    one-handed weapon is bought first and the shield can go on beside it.
    Measured on the dev realm 2026-10-05: Aradak, a level 17 Protection
    warrior, held its starting Practice Sword with a Dented Buckler in its bags
    that the equip drive could never put on."""
    return _shield_tank(character) and holds_two_hander(character)


def shield_short(character) -> bool:
    """A warrior or paladin in the tank seat with no shield worn, and none
    carried that it can put on (a two-hander in its main hand keeps a carried
    shield in the bag).

    Its off hand then counts as an empty slot, whatever it holds: a tank's
    off hand is a shield (gear._off_hand_refusal says the same of a held piece
    or a weapon).
    """
    return (
        _shield_tank(character)
        and not _worn_shield(character)
        and (
            not _get(character, "shield_carried", default=False)
            or holds_two_hander(character)
        )
    )


def _is_shield(item, inv):
    return (
        int(_get(item, "class", "item_class", default=0) or 0) == 4
        and int(_get(item, "subclass", default=0) or 0) == 6
        and inv == 14
    )


def _pair_slot_open(slot, equipped, chosen):
    """The second ring or trinket only once the first is worn or bought."""
    if slot not in ("finger2", "trinket2"):
        return True
    first = slot[:-1] + "1"
    return first in chosen or first in equipped


def _two_hander_beats_offhand(item, equipped, item_level):
    """Keep a worn offhand unless a two-hander is clearly better by 10 levels."""
    if int(_get(item, "InventoryType", "inventory_type", default=0) or 0) != 17:
        return True
    if "offhand" not in equipped:
        return True
    offhand = equipped["offhand"]
    if isinstance(offhand, dict):
        offhand = offhand.get("item_level")
    if offhand is None:
        return False
    return int(item_level) >= int(offhand) + TWO_HAND_OFFHAND_MARGIN


def _armor_rank(item):
    """Return the armor tier for cloth, leather, mail or plate."""
    if not isinstance(item, dict):
        return 0
    item_class = _get(item, "class", "item_class", default=0)
    subclass = _get(item, "subclass", "item_subclass", default=0)
    try:
        if int(item_class or 0) != 4:
            return 0
        return {1: 1, 2: 2, 3: 3, 4: 4}.get(int(subclass or 0), 0)
    except (TypeError, ValueError):
        return 0


def _worn_is_better(slot, equipped, item, level, tank=False, equipped_types=None):
    """Keep worn gear unless the auction item is meaningfully better."""
    if slot not in equipped:
        return False
    worn = equipped.get(slot)
    worn_level = worn.get("item_level") if isinstance(worn, dict) else worn
    if worn_level is None:
        return True
    worn_rank = _armor_rank(worn)
    if not worn_rank:
        worn_rank = _armor_rank((equipped_types or {}).get(slot))
    if tank and worn_rank > _armor_rank(item) > 0:
        return True
    item_level = int(_get(item, "ItemLevel", "item_level", default=0) or 0)
    worn_level = int(worn_level)
    if item_level <= worn_level:
        return True
    stale = worn_level <= level - AUCTION_STALE_GEAR_LEVEL_GAP
    return not stale and item_level < worn_level + AUCTION_MIN_UPGRADE_LEVELS


# A ONE-HANDED WEAPON GOES IN THE OFF HAND ONLY FOR A CLASS THAT DUAL WIELDS:
# rogues from the start, warriors and hunters from level 20 (class id -> level).
# Measured on the dev realm on 2026-09-28: the errand bought a level 13 priest a
# Mace for her off hand, which she can never equip there.
DUAL_WIELD_FROM = {4: 1, 1: 20, 3: 20}


def _dual_wields(character) -> bool:
    cls = _get(character, "class", "class_id")
    cls_id = CLASS_IDS.get(str(cls).lower(), int(cls) if str(cls).isdigit() else 0)
    level = int(_get(character, "level", default=0) or 0)
    return cls_id in DUAL_WIELD_FROM and level >= DUAL_WIELD_FROM[cls_id]


def _candidate_slots(
    item, equipped, chosen, tank, level, dual_wields=True, equipped_types=None
):
    inv = int(_get(item, "InventoryType", "inventory_type", default=0) or 0)
    item_level = int(_get(item, "ItemLevel", "item_level", default=0) or 0)
    tank_refuses = tank and not _is_shield(item, inv)
    if not _two_hander_beats_offhand(item, equipped, item_level):
        return
    for slot in SLOT_TYPES.get(inv, ()):
        if slot in chosen or not _pair_slot_open(slot, equipped, chosen):
            continue
        if slot == "offhand" and tank_refuses:
            continue
        if slot == "offhand" and inv == 13 and not dual_wields:
            continue
        if _worn_is_better(slot, equipped, item, level, tank, equipped_types):
            continue
        yield slot, item_level


def _fits_budget(price, purse, available, spent, weapon_first=False):
    """A piece costs at most a fifth of the purse; the first weapon for an
    empty main hand may take the whole spendable budget."""
    if price > available - spent:
        return False
    return weapon_first or price <= purse * 0.2


def _can_take(item, character, tank):
    """Class, level and skill rules, and never a two-hander for a shield tank."""
    inv = int(_get(item, "InventoryType", "inventory_type", default=0) or 0)
    if tank and inv == 17:
        return False
    return _allowed(character, item)


def _plan_character(name, character, listings, budget, taken=frozenset()):
    """The buys for one character, the main hand first.

    A WEAPON BEFORE ANYTHING ELSE. A level 35 mage and priest wore no main hand
    at all on the dev realm on 2026-09-28 while the planner filled cheaper
    slots first, and every piece was capped at a fifth of the purse, which put
    every weapon out of reach. So an empty main hand is planned first, against
    the best listing the character can afford with its whole spendable budget,
    and only then do the other empty slots share what is left, a fifth each.
    """
    plan = _Plan(name, character, budget, set(taken))
    if "mainhand" not in plan.equipped:
        for item in listings:
            if plan.consider(item, weapon_first=True):
                break
    for item in listings:
        plan.consider(item, weapon_first=False)
    return plan.buys


class _Plan:
    """One character's buys as they are chosen, and what is left to spend."""

    def __init__(self, name, character, budget, used):
        self.name = name
        self.character = character
        self.level = int(_get(character, "level", default=0) or 0)
        self.equipped = _get(character, "equipped", "slots", default={}) or {}
        self.equipped_types = _get(character, "equipped_types", default={}) or {}
        self.tank = bool(_get(character, "shield_tank", "tank", default=False))
        self.purse, self.available = budget
        self.chosen, self.used, self.buys = set(), used, []
        if tank_two_hander(character):
            # The two-hander goes when a one-hander comes, and a shield already
            # carried goes on then: none is bought for the off hand.
            self.equipped = {s: v for s, v in self.equipped.items() if s != "mainhand"}
            if _get(character, "shield_carried", default=False):
                self.chosen.add("offhand")

    def consider(self, item, weapon_first):
        """Buy `item` for the first open slot it suits and the budget allows."""
        price = int(_get(item, "buyout", default=0) or 0)
        listing_id = int(_get(item, "id", "listing_id", "auction_id", default=0) or 0)
        if price <= 0 or listing_id in self.used:
            return False
        if not _can_take(item, self.character, self.tank):
            return False
        spent = sum(b.buyout for b in self.buys)
        if not _fits_budget(price, self.purse, self.available, spent, weapon_first):
            return False
        for slot, item_level in _candidate_slots(
            item,
            self.equipped,
            self.chosen,
            self.tank,
            self.level,
            _dual_wields(self.character),
            self.equipped_types,
        ):
            if weapon_first and slot != "mainhand":
                continue
            entry = int(_get(item, "entry", default=0))
            self.buys.append(
                Buy(
                    self.name,
                    slot,
                    listing_id,
                    entry,
                    price,
                    item_level,
                    int(_get(item, "class", "item_class", default=0) or 0),
                    int(_get(item, "subclass", "item_subclass", default=0) or 0),
                )
            )
            self.chosen.add(slot)
            self.used.add(listing_id)
            return True
        return False


# THE FAMILY FUNDS ITS OWN (dev realm, 2026-09-28): the warrior carried 54 gold
# while the rogue had 2 and the second family 0 to 5 each, and every planner
# above spends only the buyer's own purse. A player hands a sibling gold before
# a shopping trip; here the richest member posts it at the errand's mailbox,
# where the mail step collects it a moment later (a letter with money and no
# item is delivered at once). A gear-short member is topped up to
# FUND_PER_LEVEL copper per level; the donor keeps its own top-up and at least
# FUND_DONOR_KEEP of its purse, and a gift under FUND_MIN_GIFT is not worth a
# letter.
FUND_PER_LEVEL = 3000
FUND_DONOR_KEEP = 0.5
FUND_MIN_GIFT = 5000


@dataclass(frozen=True)
class Gift:
    """One letter of gold from `donor` to `taker`."""

    donor: str
    taker: str
    copper: int
    why: str


# The gap guildrun's gear gate keeps a member out of dungeons at
# (guildrun.GEAR_GAP): a worn average this many levels under its own level.
STALE_GEAR_GAP = 6


def stale_gear(character) -> bool:
    """Every stat slot filled, perhaps, but with gear far below the wearer.

    The average item level of what is worn, the shirt and tabard aside (they
    carry no stats), under the wearer's level by more than STALE_GEAR_GAP.
    Nothing worn is not stale; it is `gear_short`.
    """
    equipped = _get(character, "equipped", "slots", default={}) or {}
    levels = []
    for slot, worn in equipped.items():
        if slot in ("shirt", "tabard"):
            continue
        level = worn.get("item_level") if isinstance(worn, dict) else worn
        if level is not None:
            levels.append(int(level))
    if not levels:
        return False
    level = int(_get(character, "level", default=0) or 0)
    return sum(levels) / len(levels) < level - STALE_GEAR_GAP


def gear_short(character) -> bool:
    """No main hand, or VENDOR_TRIP_EMPTY_SLOTS or more empty stat slots."""
    equipped = _get(character, "equipped", "slots", default={}) or {}
    return (
        "mainhand" not in equipped
        or empty_gear_slots(_slot_numbers(character)) >= VENDOR_TRIP_EMPTY_SLOTS
    )


def plan_funding(characters) -> tuple:
    """The richest member's gold letters to its gear-short siblings.

    `characters` are the gear facts (`level`, `purse`, `equipped`) of the
    members standing at the mailbox. Members with no main hand are funded
    first, then the higher level first. Pure: returns the gifts.
    """
    facts = {n: c for n, c in (characters or {}).items() if c}
    if len(facts) < 2:
        return ()

    def purse(c):
        return int(_get(c, "purse", "money", default=0) or 0)

    def target(c):
        level = int(_get(c, "level", default=0) or 0)
        return FUND_PER_LEVEL * level

    donor = max(sorted(facts), key=lambda n: purse(facts[n]))
    rich = facts[donor]
    keep = max(target(rich), int(purse(rich) * FUND_DONOR_KEEP))
    left = purse(rich) - keep
    takers = sorted(
        (n for n in facts if n != donor and gear_short(facts[n])),
        key=lambda n: (
            "mainhand" in (_get(facts[n], "equipped", default={}) or {}),
            -int(_get(facts[n], "level", default=0) or 0),
            n,
        ),
    )
    gifts = []
    for name in takers:
        need = target(facts[name]) - purse(facts[name])
        copper = min(need, left)
        if copper < FUND_MIN_GIFT:
            continue
        armed = "mainhand" in (_get(facts[name], "equipped", default={}) or {})
        gifts.append(
            Gift(
                donor,
                name,
                copper,
                "%s is short of gear" % name if armed else "%s has no weapon" % name,
            )
        )
        left -= copper
    return tuple(gifts)


def fund_command(gift) -> str:
    """The kind='mail' send row DoMail reads: gold only, from the donor."""
    return "send money:%d subject:For your gear" % int(gift.copper)


# WHAT A BUY ROW ANSWERED (dev realm, 2026-09-28 03:13Z). The errand wrote
# three buys at the weaponsmith for members the snapshot read in reach, and
# the world refused all three with `vendor not in range`: the followers were
# still walking up. The errand had already marked the slots bought, so the
# next vendor never offered the mage a staff. A slot counts as bought only
# once its row says so, and a vendor whose rows were refused for range is
# tried again, up to VENDOR_TRIES times.
BUY_DONE = frozenset({"delivered", "applied", "verifying", "unchanged"})
BUY_WAITING = frozenset({"", "pending", "claimed"})
OUT_OF_REACH = "vendor not in range"
VENDOR_TRIES = 2


@dataclass(frozen=True)
class BuyRow:
    """One written vendor buy: who, which slot, its command row."""

    character: str
    slot: str
    row_id: int


def settle_buys(rows, answers) -> tuple:
    """(bought, waiting, out_of_reach) from each row's answer.

    `answers` is row id -> the command row ({status, detail}) or None.
    `bought` is name -> slots the world confirmed, `waiting` the rows still
    unanswered, `out_of_reach` whether any row was refused for range. Pure.
    """
    bought, waiting, out_of_reach = {}, [], False
    for row in rows or ():
        answer = answers.get(row.row_id) or {}
        status = str(answer.get("status") or "")
        if status in BUY_WAITING:
            waiting.append(row)
        elif status in BUY_DONE:
            bought.setdefault(row.character, set()).add(row.slot)
        elif str(answer.get("detail") or "") == OUT_OF_REACH:
            out_of_reach = True
    return bought, waiting, out_of_reach
