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

# item_template.class for weapons. Kept local so this decision module does not
# import gear.py and create a dependency cycle.
ITEM_CLASS_WEAPON = 2

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

# Keep a margin inside the core's five-yard trainer gate: these are snapshot
# and spawn coordinates, not the live NPC's position or interaction geometry.
IN_REACH_YARDS = 4.0

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
    best: dict = {}
    for row in bag_rows or ():
        name = str(row.get("name") or "")
        need = _need(name, (facts or {}).get(name), row)
        if need is None:
            continue
        item_level = int(row.get("ItemLevel") or 0)
        if name not in best or item_level > best[name][0]:
            best[name] = (item_level, need)
    return [need for _level, need in (best[n] for n in sorted(best))]


def _class_id(fact) -> int:
    from gearup import CLASS_IDS

    return CLASS_IDS.get(str(fact.get("class") or "").lower(), 0)


def _learnable(fact, row) -> bool:
    """Its class can learn the type, it lacks the skill, and it can wear it."""
    cls_id = _class_id(fact)
    sub = row.get("subclass")
    sub = int(sub) if sub is not None else -1
    held = set((fact.get("skills") or {}).get("weapons") or ())
    if sub not in WEAPON_SKILLS or sub in held:
        return False
    if sub not in CLASS_WEAPONS.get(cls_id, set()):
        return False
    if int(row.get("RequiredLevel") or 0) > int(fact.get("level") or 0):
        return False
    allowed = int(row.get("AllowableClass") or 0)
    return allowed in (-1, 0) or bool(allowed & (1 << (cls_id - 1)))


def _need(name, fact, row):
    """The Need this carried weapon makes for its holder, or None."""
    if not fact or not _learnable(fact, row):
        return None
    slot = WEAPON_SLOT.get(int(row.get("InventoryType") or 0))
    if not slot:
        return None
    equipped = fact.get("equipped") or {}
    item_level = int(row.get("ItemLevel") or 0)
    worn = equipped.get(slot)
    if slot in equipped and worn is not None and item_level <= int(worn):
        return None
    skill, spell = WEAPON_SKILLS[int(row["subclass"])]
    why = (
        "its %s is empty" % slot
        if slot not in equipped
        else "item level %d over %s worn" % (item_level, worn)
    )
    return Need(
        name,
        skill,
        spell,
        int(row.get("entry") or 0),
        str(row.get("label") or ""),
        slot,
        why,
    )


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


def in_reach(master: dict, at: dict, yards: float = IN_REACH_YARDS) -> bool:
    """Is a snapshot reading within `yards` of the master's spawn."""
    if not master or not at:
        return False
    try:
        if int(at["map_id"]) != int(master["map_id"]):
            return False
        dx = float(at["pos_x"]) - float(master["x"])
        dy = float(at["pos_y"]) - float(master["y"])
    except (KeyError, TypeError, ValueError):
        return False
    return dx * dx + dy * dy <= float(yards) ** 2


def _learned_weapon_times(rows):
    """Most recent learning time for each character and weapon subclass."""
    subclass_by_skill = {
        skill: subclass for subclass, (skill, _spell) in WEAPON_SKILLS.items()
    }
    learned_at = {}
    for row in rows or ():
        try:
            key = (str(row["name"]), subclass_by_skill[int(row["skill"])])
            learned = row["learned_at"]
        except (KeyError, TypeError, ValueError):
            continue
        if learned is not None and (key not in learned_at or learned > learned_at[key]):
            learned_at[key] = learned
    return learned_at


def _carried_weapon_commands(rows):
    """Map each carried weapon equip command to its trained skill subclass."""
    commands = {}
    for row in rows or ():
        try:
            item_class = int(row.get("item_class", row.get("class")))
            name = str(row.get("holder") or row["name"])
            entry = int(row["entry"])
            subclass = int(row.get("item_subclass", row.get("subclass")))
        except (KeyError, TypeError, ValueError):
            continue
        if item_class == ITEM_CLASS_WEAPON and subclass in WEAPON_SKILLS:
            commands[(name, "e Hitem:%d:0" % entry)] = subclass
    return commands


def _was_blocked_by_unlearned_skill(attempt, commands, learned_at) -> bool:
    """Whether a resolved equip attempt predates learning its weapon skill."""
    try:
        key = (str(attempt["target_name"]), str(attempt["command"]))
        subclass = commands[key]
        learned = learned_at[(key[0], subclass)]
        created = attempt["created_at"]
        status = str(attempt["status"])
    except (KeyError, TypeError):
        return False
    return (
        status in {"delivered", "error"} and created is not None and created < learned
    )


def reopen_equip_attempts(history, learned, carried):
    """Retire resolved attempts made before a carried weapon's skill was learned.

    Pending and post-training attempts stay counted, so each eligible weapon
    gets one retry without resetting its give-up count on every pass.
    Returns `(remaining_history, reopened_attempts)`.
    """
    commands = _carried_weapon_commands(carried)
    learned_at = _learned_weapon_times(learned)
    remaining, reopened = [], []
    for attempt in history or ():
        if _was_blocked_by_unlearned_skill(attempt, commands, learned_at):
            reopened.append(attempt)
        else:
            remaining.append(attempt)
    return tuple(remaining), tuple(reopened)
