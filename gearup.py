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


def _get(row, *keys, default=None):
    for key in keys:
        if key in row:
            return row[key]
    return default


def _allowed(character, item):
    level = int(_get(character, "level", default=0) or 0)
    cls = _get(character, "class", "class_id")
    cls_id = CLASS_IDS.get(str(cls).lower(), int(cls) if str(cls).isdigit() else 0)
    if not _level_and_class_ok(item, cls_id, level):
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
    skills = _get(character, "skills", default={}) or {}
    allowed = _get(skills, "weapons", default=skills.get("weapon_types", ()))
    return sub in allowed or WEAPON_SUBCLASS.get(str(sub).lower()) in allowed


def plan_buys(characters, listings, *, repair_floor=0):
    """Return best affordable buyouts for empty slots (or 10-level upgrades)."""
    output = []
    ordered = sorted(listings, key=_listing_order)
    for name, character in sorted(characters.items()):
        output.extend(
            _plan_character(
                name, character, ordered, _budget_for(name, character, repair_floor)
            )
        )
    return tuple(output)


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


def _worn_is_better(slot, equipped, item_level, level):
    """A worn piece stays unless it is 10 or more levels behind and this is better."""
    if slot not in equipped:
        return False
    worn = equipped.get(slot)
    worn_level = worn.get("item_level") if isinstance(worn, dict) else worn
    if worn_level is None:
        return True
    return int(worn_level) > level - 10 or item_level <= int(worn_level)


def _candidate_slots(item, equipped, chosen, tank, level):
    inv = int(_get(item, "InventoryType", "inventory_type", default=0) or 0)
    item_level = int(_get(item, "ItemLevel", "item_level", default=0) or 0)
    tank_refuses = tank and not _is_shield(item, inv)
    for slot in SLOT_TYPES.get(inv, ()):
        if slot in chosen or not _pair_slot_open(slot, equipped, chosen):
            continue
        if slot == "offhand" and tank_refuses:
            continue
        if _worn_is_better(slot, equipped, item_level, level):
            continue
        yield slot, item_level


def _fits_budget(price, purse, available, spent):
    return price <= purse * 0.2 and price <= available - spent


def _plan_character(name, character, listings, budget):
    level = int(_get(character, "level", default=0) or 0)
    equipped = _get(character, "equipped", "slots", default={}) or {}
    tank = bool(_get(character, "shield_tank", "tank", default=False))
    purse, available = budget
    chosen, used, buys = set(), set(), []
    for item in listings:
        price = int(_get(item, "buyout", default=0) or 0)
        listing_id = int(_get(item, "id", "listing_id", "auction_id", default=0) or 0)
        if not _allowed(character, item) or price <= 0 or listing_id in used:
            continue
        for slot, item_level in _candidate_slots(item, equipped, chosen, tank, level):
            spent = sum(b.buyout for b in buys)
            if not _fits_budget(price, purse, available, spent):
                continue
            buys.append(
                Buy(
                    name,
                    slot,
                    listing_id,
                    int(_get(item, "entry", default=0)),
                    price,
                    item_level,
                )
            )
            chosen.add(slot)
            used.add(listing_id)
            break
    return buys
