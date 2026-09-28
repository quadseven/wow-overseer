"""A member carrying a weapon it has no skill for learns it at a weapon master.

WHY (wow-overseer#399). Measured on the dev realm on 2026-09-28: the level 35
mage carried a Silithid Ripper, a one-handed sword of item level 36, with no
Swords skill, and wore no main hand at all; the level 38 warrior carried a
Ravenwood Bow with no Bows skill and an empty ranged slot. The gear planners
treat a weapon as usable only when its skill is already held, which is right
for equipping, and nothing asked the next question a player asks: would a few
silver at a weapon master let me wield what I already carry?

THE PLAYER'S WAY. The family walks to a weapon master of its own side on the
leader's map (the leader's ordinary travel aim), each member that needs a
skill buys it with its own gold (mod-overseer's `train-weapon skill:<id>`,
which goes through the trainer and takes the money), and then puts the weapon
on (`e Hitem:<entry>:0`). Nothing is granted.

PURE MODULE: rows in, decisions out. bridge.py reads and writes.
"""

from __future__ import annotations

from dataclasses import dataclass

# item_template.subclass for a weapon -> (SkillLine id, the trainer spell that
# teaches it). Wands are left out: no trainer sells them, the class has them.
WEAPON_SKILLS = {
    0: (44, 196),  # one-handed axes
    1: (172, 197),  # two-handed axes
    2: (45, 264),  # bows
    3: (46, 266),  # guns
    4: (54, 198),  # one-handed maces
    5: (160, 199),  # two-handed maces
    6: (229, 200),  # polearms
    7: (43, 201),  # one-handed swords
    8: (55, 202),  # two-handed swords
    10: (136, 227),  # staves
    13: (473, 15590),  # fist weapons
    15: (173, 1180),  # daggers
    16: (176, 2567),  # thrown
    18: (226, 5011),  # crossbows
}

# Which weapon types each class can ever learn, by class id and subclass, as
# the classic trainers teach them. A member is never walked to learn what its
# class cannot hold.
CLASS_WEAPONS = {
    1: {0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 15, 16, 18},  # warrior
    2: {0, 1, 4, 5, 6, 7, 8},  # paladin
    3: {0, 1, 2, 3, 6, 7, 8, 10, 13, 15, 16, 18},  # hunter
    4: {2, 3, 4, 7, 13, 15, 16, 18},  # rogue
    5: {4, 10, 15},  # priest
    7: {0, 1, 4, 5, 10, 13, 15},  # shaman
    8: {7, 10, 15},  # mage
    9: {7, 10, 15},  # warlock
    11: {4, 5, 6, 10, 13, 15},  # druid
}

# InventoryType -> the slot the weapon goes in. Off-hand weapons are left to
# the dual-wield rule in gearup; this is about the main hand and the ranged slot.
WEAPON_SLOT = {13: "mainhand", 17: "mainhand", 21: "mainhand", 15: "ranged",
               25: "ranged", 26: "ranged"}  # fmt: skip

# Weapon masters by faction template: which side each one serves. Read off
# acore_world on 2026-09-28 (creature_template.subname = 'Weapon Master').
MASTER_TEAM = {
    12: "alliance", 55: "alliance", 80: "alliance",
    29: "horde", 68: "horde", 104: "horde", 876: "horde",
}  # fmt: skip

# How close to the weapon master's spawn a member must be read before its
# train row is written; the module's interact gate is the real test.
IN_REACH_YARDS = 8.0

TRAIN_SOURCE = "gear:weapon-skill"


@dataclass(frozen=True)
class Need:
    """One member, one weapon it carries, and the skill that would let it."""

    name: str
    skill: int
    spell: int
    entry: int
    item: str
    slot: str
    why: str

    @property
    def train_command(self) -> str:
        return "train-weapon skill:%d" % self.skill

    @property
    def equip_command(self) -> str:
        return "e Hitem:%d:0" % self.entry


def needs(facts: dict, bag_rows) -> list:
    """The best untrained weapon upgrade per member, sorted by name.

    `facts` is bridge._fetch_gearup_facts (class name, level, `equipped` slot
    -> item level, `skills.weapons` subclasses held). `bag_rows` are carried
    weapons: name, entry, label, subclass, InventoryType, ItemLevel,
    RequiredLevel, AllowableClass. An upgrade fills an empty slot or beats the
    worn piece's item level.
    """
    from gearup import CLASS_IDS

    best: dict = {}
    for row in bag_rows or ():
        name = str(row.get("name") or "")
        fact = (facts or {}).get(name)
        if not fact:
            continue
        cls_id = CLASS_IDS.get(str(fact.get("class") or "").lower(), 0)
        sub = int(row.get("subclass") if row.get("subclass") is not None else -1)
        slot = WEAPON_SLOT.get(int(row.get("InventoryType") or 0))
        held = set((fact.get("skills") or {}).get("weapons") or ())
        if sub not in WEAPON_SKILLS or sub in held or not slot:
            continue
        if sub not in CLASS_WEAPONS.get(cls_id, set()):
            continue
        if int(row.get("RequiredLevel") or 0) > int(fact.get("level") or 0):
            continue
        allowed = int(row.get("AllowableClass") or 0)
        if allowed not in (-1, 0) and not allowed & (1 << (cls_id - 1)):
            continue
        item_level = int(row.get("ItemLevel") or 0)
        worn = (fact.get("equipped") or {}).get(slot)
        if (
            slot in (fact.get("equipped") or {})
            and worn is not None
            and item_level <= int(worn)
        ):
            continue
        skill, spell = WEAPON_SKILLS[sub]
        why = (
            "its %s is empty" % slot
            if slot not in (fact.get("equipped") or {})
            else "item level %d over %s worn" % (item_level, worn)
        )
        need = Need(
            name,
            skill,
            spell,
            int(row.get("entry") or 0),
            str(row.get("label") or ""),
            slot,
            why,
        )
        if name not in best or item_level > best[name][0]:
            best[name] = (item_level, need)
    return [best[n][1] for n in sorted(best)]


def choose_master(masters, wanted, team: str, map_id: int) -> dict:
    """The weapon master on `map_id`, of `team`'s side, that teaches the most
    of `wanted` (trainer spell ids), nearest first. {} when none.

    `masters` rows: entry, name, faction, map_id, x, y, yards, spell.
    """
    by: dict = {}
    for row in masters or ():
        try:
            if int(row["map_id"]) != int(map_id):
                continue
            if MASTER_TEAM.get(int(row["faction"])) != str(team or "").lower():
                continue
            if int(row["spell"]) not in wanted:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        entry = int(row["entry"])
        seen = by.setdefault(entry, dict(row, spells=set()))
        seen["spells"].add(int(row["spell"]))
    if not by:
        return {}
    return min(
        by.values(),
        key=lambda r: (-len(r["spells"]), float(r["yards"]), int(r["entry"])),
    )


def in_reach(master: dict, at: dict) -> bool:
    """Is a snapshot reading within IN_REACH_YARDS of the master's spawn."""
    if not master or not at:
        return False
    try:
        if int(at["map_id"]) != int(master["map_id"]):
            return False
        dx = float(at["pos_x"]) - float(master["x"])
        dy = float(at["pos_y"]) - float(master["y"])
    except (KeyError, TypeError, ValueError):
        return False
    return dx * dx + dy * dy <= IN_REACH_YARDS**2
