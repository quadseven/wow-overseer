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

# WHAT THE BOT'S OWN EQUIP NEVER DOES (#830). Measured on the dev realm over
# two days: `e` put on 0 of 11 melee weapons asked of hunters, though each held
# the skill line and the piece was a clear upgrade; their bots keep the weapon
# they were made with. Every path that would write that `e` row, or walk a
# hunter to a weapon master for it, asks this one rule. A hunter's ranged
# weapon (InventoryType 15, 25, 26) is never refused here.
HUNTER = 3
MELEE_INVENTORY_TYPES = frozenset({13, 17, 21, 22})


def bot_wont_wear(class_id, item_class, inventory_type) -> bool:
    """True when the member's bot will not put this piece on, whatever the
    numbers say: today, a hunter and any melee weapon."""
    try:
        cls, item, inv = int(class_id), int(item_class), int(inventory_type)
    except (TypeError, ValueError):
        return False
    return cls == HUNTER and item == ITEM_CLASS_WEAPON and inv in MELEE_INVENTORY_TYPES


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

    @property
    def fills_empty(self) -> bool:
        """The weapon would go in a slot that holds nothing now."""
        return self.why == "its %s is empty" % self.slot


# A GUILD MEMBER'S TRIP (#793). The family walks with its leader (above); a
# guild member outside the family walks alone, as its own guild job: to the
# weapon master's spawn, then `train-weapon`, then the guild equip pass puts the
# weapon on once the skill reads learned. On the dev realm on 2026-10-18 each
# guild's equip pass logged 10 to 11 carried weapon upgrades that "wait on a
# weapon skill a weapon master teaches", pass after pass, because only the
# family's pass ever walked anyone to one.


@dataclass(frozen=True)
class Offer:
    """One guild member's weapon-master trip: the need, and the master's spawn
    (0 when no master of its side on its map teaches the skill)."""

    need: Need
    spawn: int = 0
    map_id: int = 0
    x: float = 0.0
    y: float = 0.0
    master: str = ""
    cost: int = 0


def offer(need, master) -> Offer:
    """The Offer for `need` at `master` (a choose_master row that carries the
    spawn guid and the trainer's MoneyCost); a master-less Offer when `master`
    is empty or names no spawn."""
    try:
        spawn = int((master or {}).get("spawn") or 0)
        if not spawn:
            return Offer(need)
        return Offer(
            need,
            spawn,
            int(master["map_id"]),
            float(master["x"]),
            float(master["y"]),
            str(master.get("name") or ""),
            int(master.get("cost") or 0),
        )
    except (KeyError, TypeError, ValueError):
        return Offer(need)


def may_need(class_id, level, carried) -> bool:
    """Could one of `carried` (guildjobs.Carried) make a Need, before the
    skills are read: a main hand or ranged weapon its class can learn, at its
    level. Keeps the skill and bag reads to members who carry one."""
    try:
        cls, lvl = int(class_id), int(level)
    except (TypeError, ValueError):
        return False
    learnable = CLASS_WEAPONS.get(cls, set())
    for item in carried or ():
        try:
            if int(item.item_class) != ITEM_CLASS_WEAPON:
                continue
            if int(item.subclass) not in learnable:
                continue
            if int(item.inventory_type) not in WEAPON_SLOT:
                continue
            if int(item.required_level) > lvl:
                continue
        except (AttributeError, TypeError, ValueError):
            continue
        if not bot_wont_wear(cls, ITEM_CLASS_WEAPON, item.inventory_type):
            return True
    return False


def needs(facts: dict, bag_rows) -> list:
    """The best untrained weapon upgrade per member, sorted by name.

    `facts` is bridge._fetch_gearup_facts (class name, level, `equipped` slot
    -> item level or a worn-item mapping with `item_level`, and
    `skills.weapons` subclasses held). `bag_rows` are carried
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
    # The skill would buy nothing: the bot never wears the weapon (#830).
    if bot_wont_wear(cls_id, ITEM_CLASS_WEAPON, row.get("InventoryType") or 0):
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
    worn_level = worn.get("item_level") if isinstance(worn, dict) else worn
    if slot in equipped and worn_level is not None and item_level <= int(worn_level):
        return None
    skill, spell = WEAPON_SKILLS[int(row["subclass"])]
    why = (
        "its %s is empty" % slot
        if slot not in equipped
        else "item level %d over %s worn" % (item_level, worn_level)
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

    `masters` rows: entry, name, faction, map_id, x, y, yards, spell, and
    (bridge._WEAPON_MASTERS_SQL) the spawn guid and the spell's cost. Rows come
    nearest first, so an entry keeps its nearest spawn.
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
