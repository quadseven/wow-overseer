"""Plan auction gear for empty equipment slots (#146, #147).

The planner is pure: it only spends a character's own purse on equipment
they can wear now, and keeps the same repair reserve and bounded spending
discipline as the other town purchases.
"""
from dataclasses import dataclass


SLOT_TYPES = {
    1: ("head",), 2: ("neck",), 3: ("shoulder",),
    5: ("chest",), 20: ("chest",), 6: ("waist",), 7: ("legs",),
    8: ("feet",), 9: ("wrist",), 10: ("hands",),
    11: ("finger1", "finger2"), 12: ("trinket1", "trinket2"),
    13: ("mainhand", "offhand"), 17: ("mainhand",), 21: ("mainhand",),
    14: ("offhand",), 22: ("offhand",), 23: ("offhand",),
    15: ("ranged",), 16: ("back",), 25: ("ranged",),
    26: ("ranged",), 28: ("ranged",),
}
CLASS_IDS = {"warrior": 1, "paladin": 2, "hunter": 3, "rogue": 4,
             "priest": 5, "death_knight": 6, "shaman": 7, "mage": 8,
             "warlock": 9, "druid": 11}
WEAPON_SUBCLASS = {"axe": 0, "two-handed axe": 1, "bow": 2, "gun": 3,
                   "mace": 4, "two-handed mace": 5, "polearm": 6,
                   "sword": 7, "two-handed sword": 8, "staff": 10,
                   "fist": 13, "dagger": 15, "thrown": 16,
                   "crossbow": 18, "wand": 19, "fishing pole": 20}
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
    if int(_get(item, "RequiredLevel", "required_level", default=0) or 0) > level:
        return False
    allowed = int(_get(item, "AllowableClass", "allowable_class", default=0) or 0)
    if allowed not in (-1, 0) and not allowed & (1 << (cls_id - 1)):
        return False
    kind = int(_get(item, "class", "item_class", default=-1) or 0)
    sub = int(_get(item, "subclass", default=-1) or 0)
    skills = _get(character, "skills", default={}) or {}
    if kind == 4:
        if int(_get(item, "InventoryType", "inventory_type", default=0) or 0) == 14:
            return cls_id in SHIELD_CLASSES
        if sub in (0, 1):
            return True
        if sub == 2:
            return cls_id in LEATHER_CLASSES
        if sub == 3:
            return cls_id in MAIL_FROM_START or (cls_id in MAIL_AT_40 and level >= 40)
        if sub == 4:
            return cls_id in PLATE_AT_40 and level >= 40
        return False
    if kind != 2:
        return False
    allowed_weapons = _get(skills, "weapons", default=skills.get("weapon_types", ()))
    return sub in allowed_weapons or WEAPON_SUBCLASS.get(str(sub).lower()) in allowed_weapons


def plan_buys(characters, listings, *, repair_floor=0):
    """Return best affordable buyouts for empty slots (or 10-level upgrades)."""
    output = []
    for name, character in sorted(characters.items()):
        level = int(_get(character, "level", default=0) or 0)
        purse = int(_get(character, "purse", "money", default=0) or 0)
        equipped = _get(character, "equipped", "slots", default={}) or {}
        tank = bool(_get(character, "shield_tank", "tank", default=False))
        reserve = repair_floor.get(name, 0) if isinstance(repair_floor, dict) else repair_floor
        available = max(0, min(purse * .6, purse - int(reserve)))
        chosen = set()
        used = set()
        for item in sorted(listings, key=lambda r: (-int(_get(r, "ItemLevel", "item_level", default=0) or 0), int(_get(r, "buyout", default=0) or 0), int(_get(r, "id", "listing_id", "auction_id", default=0) or 0))):
            if not _allowed(character, item) or int(_get(item, "buyout", default=0) or 0) <= 0:
                continue
            inv = int(_get(item, "InventoryType", "inventory_type", default=0) or 0)
            listing_id = int(_get(item, "id", "listing_id", "auction_id", default=0) or 0)
            if listing_id in used:
                continue
            slots = SLOT_TYPES.get(inv, ())
            if not slots:
                continue
            for slot in slots:
                # The second ring or trinket only once the first is worn or bought.
                if slot in chosen or (slot in ("finger2", "trinket2") and
                                      slot[:-1] + "1" not in chosen and
                                      slot[:-1] + "1" not in equipped):
                    continue
                if slot == "offhand" and tank and not (int(_get(item, "class", "item_class", default=0) or 0) == 4 and int(_get(item, "subclass", default=0) or 0) == 6 and inv == 14):
                    continue
                worn = equipped.get(slot)
                worn_level = (worn.get("item_level") if isinstance(worn, dict)
                              else worn)
                item_level = int(_get(item, "ItemLevel", "item_level", default=0) or 0)
                if slot in equipped and (
                    worn_level is None or int(worn_level) > level - 10
                    or item_level <= int(worn_level)
                ):
                    continue
                price = int(_get(item, "buyout", default=0) or 0)
                spent = sum(x.buyout for x in output if x.character == name)
                if price > purse * .2 or price > available - spent:
                    continue
                output.append(Buy(name, slot, int(_get(item, "id", "listing_id", "auction_id", default=0)), int(_get(item, "entry", default=0)), price, item_level))
                chosen.add(slot)
                used.add(listing_id)
                break
    return tuple(output)
