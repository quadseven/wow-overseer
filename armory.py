"""Pure builder for the Armory tab: character rows -> a profile, per member.

WHY THIS EXISTS. What the five are WEARING and how they are SPECCED are the
two things that decide whether a dungeon run works, and until this tab both
were invisible on every surface the overseer has. Answering either one meant
writing SQL by hand, which is why a real defect - the watched character being
the only one nobody buffs (mod-overseer#80) - hid for as long as it did. A
thing nobody can see is a thing nobody checks.

WHAT A PROFILE IS. The first cut of this tab was a grid: five columns of
nineteen item NAMES. Correct, and it looked nothing like an armory, which is
what the operator asked for. An armory page - the one the family's players
already know how to read - is a header (name, level, race, class, item
level), a paper doll (the item ICONS down both sides of the character, each
bordered in its quality colour), a tooltip per item with the lines the game
itself shows, a stat block, and the three talent trees drawn as the trainer
draws them. That is what build_armory now produces, per member, and the
page's job is to lay it out and nothing more.

Same seam rule as map_core, panel and family (infra#2597): the HTTP adapter
fetches rows and does nothing else. Every judgement here is a decision -
which slots count as gear at all, what an empty slot means, what "of the
Tiger" adds to a belt, how a pile of spell ids becomes "0/0/16 Protection" -
so all of it lives in this module where the stdlib suite can reach it
without a database.

TWO FROZEN BOOKS. `character_talent` stores one row per learned talent and
the only thing in that row is the spell id of the rank currently held; an
item row names a displayid and a handful of spell ids. Turning either back
into something a person reads needs the client's own tables (Talent.dbc,
ItemDisplayInfo.dbc, Spell.dbc and friends), and those are exactly what the
server database does NOT have: acore_world ships `talent_dbc` and
`talenttab_dbc` as EMPTY tables because the core reads the real DBCs off
disk. The three routes were: mount the DBC directory into this pod (a new
runtime dependency, on a deployment that is not the worldserver), populate
the empty world tables (an admin change to a database that gets rebuilt from
upstream), or freeze the DBCs into committed reference files. The third is
what zones.json and shapes.json already do with frozen 3.3.5a client data,
so it is what this does too: tools/gen_talents.py writes talents.json and
tools/gen_items.py writes icons.json, spells.json and items.json, TalentBook
and ItemBook read them, and the PER-CHARACTER data still comes from the live
database on every poll.

Tickets: infra#3096 (the tab), infra#3139 (the profile).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import bonds
import bag_pressure
import family
import raidlineup
from core import _ALLIANCE_RACES, _HORDE_RACES
from panel import (  # noqa: F401 - CLASS_COLOURS is re-exported for its old callers
    CLASS_COLOURS,
    _CLASS_NAMES,
    _EQUIPMENT_SLOT_NAMES,
    _RACE_NAMES,
)

# The paper doll, in slot order, re-exported under a public name. panel owns
# the list; both the SQL bound (`ci.slot < len(EQUIPPED_SLOTS)`) and the rows
# this module builds read it from here, so the query and the grid cannot come
# to disagree about how many slots a character has.
EQUIPPED_SLOTS = _EQUIPMENT_SLOT_NAMES

# Item quality, and the word the game itself uses for each. The page owns the
# colours; naming them here keeps "what quality 4 is called" in one place
# rather than in a switch statement inside a render function.
QUALITY_NAMES = {
    0: "poor",
    1: "common",
    2: "uncommon",
    3: "rare",
    4: "epic",
    5: "legendary",
    6: "artifact",
    7: "heirloom",
}
UNKNOWN_QUALITY = "unknown"

# Shirt and tabard carry no stats in 3.3.5 - they are clothes, not equipment.
# They are still DRAWN, because "what is he wearing" includes them, but they
# are excluded from the empty count and the average item level. Without this
# every character on the server reads as permanently two slots short, and a
# number that is always wrong by two is a number nobody reads.
COSMETIC_SLOTS = frozenset({"shirt", "tabard"})

# AN EMPTY SLOT IS TWO DIFFERENT FINDINGS WEARING ONE WORD. A missing helmet
# is something somebody can fix this evening. An empty tabard slot is true of
# nearly every character on the realm and always will be. Drawn identically
# they READ identically, and the alarm that fires on everyone is the one that
# drowns the alarm that does not - which is the specific complaint: the
# watched warrior's bare ring fingers must not sit in a row of cells that
# look exactly as alarming and never mean anything.
#
# So the word an empty slot says is decided here, per slot, rather than by a
# ternary in the page. A cosmetic slot says its own NAME, because "shirt" is
# a complete and unalarming answer to what is in it; a real gap says "empty",
# because there is no name that would be the answer.
EMPTY_MISSING, EMPTY_COSMETIC = "missing", "cosmetic"
EMPTY_WORD = "empty"


def empty_reading(slot_name: str) -> dict:
    """What an empty slot says, and which of the two kinds of empty it is."""
    if slot_name in COSMETIC_SLOTS:
        return {
            "kind": EMPTY_COSMETIC,
            "label": slot_name,
            "note": f"nothing worn, and nothing missing: a {slot_name} carries "
            "no stats in this expansion and is empty on almost every "
            "character. It is drawn because what somebody is wearing "
            "includes what they are not.",
        }
    return {
        "kind": EMPTY_MISSING,
        "label": EMPTY_WORD,
        "note": "nothing worn in a slot that takes gear. This is a real gap: "
        "it costs the character every stat the slot would carry, and "
        "it is the thing this tab exists to make visible.",
    }


# A talent point arrives every level from 10 on. Rate.Talent is 1 on this
# realm, which is the assumption this budget makes.
FIRST_TALENT_LEVEL = 10

# Death Knights are the one class whose budget is not a function of level:
# theirs also counts quest rewards, tracked in memory by the core and not
# exposed as a column here. So for a DK the budget is reported as unknown
# rather than guessed - an "unspent points" number that is quietly wrong is
# worse than one that admits it does not know.
DEATH_KNIGHT = 6

# The trainer's grid is eleven tiers by four columns for every class.
TALENT_ROWS = 11
TALENT_COLS = 4

# The paper doll, as the character sheet draws it: a column down each side
# of the character. Sent to the page rather than typed into it, for the
# same reason the slot list is - one list decides what the slots are, and
# a test holds these two columns to exactly that list.
DOLL_LEFT = [
    "head",
    "neck",
    "shoulders",
    "back",
    "chest",
    "shirt",
    "tabard",
    "wrists",
    "main hand",
    "off hand",
]
DOLL_RIGHT = [
    "hands",
    "waist",
    "legs",
    "feet",
    "finger 1",
    "finger 2",
    "trinket 1",
    "trinket 2",
    "ranged",
]

# The mark a doll cell wears when there is no picture in it. A cell is 46px
# and the icon comes from a host off the tailnet, so "no icon" is an ordinary
# outcome rather than a rare one - and "shoulders" wrapped over three lines
# inside 46 pixels is not a fallback, it is a smudge. Two letters fit.
#
# WHICH two letters is a naming decision and so it lives here: a ring slot is
# stored as "finger 1" and read by a player as R1, a trinket as T1, and no
# rule that took the first two letters of the stored name would produce
# either. The page is handed the mark and never invents one, which is the
# same rule that keeps it from naming a slot at all.
SLOT_MARKS = {
    "head": "HD",
    "neck": "NK",
    "shoulders": "SH",
    "shirt": "SR",
    "chest": "CH",
    "waist": "WS",
    "legs": "LG",
    "feet": "FT",
    "wrists": "WR",
    "hands": "HN",
    "finger 1": "R1",
    "finger 2": "R2",
    "trinket 1": "T1",
    "trinket 2": "T2",
    "back": "BK",
    "main hand": "MH",
    "off hand": "OH",
    "ranged": "RG",
    "tabard": "TB",
}


def slot_mark(slot_name: str) -> str:
    """A slot's two-letter mark; its own first two letters if it has none.

    The fallback exists so the day panel's slot list grows a twentieth entry
    the doll draws a slightly wrong mark rather than an empty cell.
    """
    return SLOT_MARKS.get(slot_name) or slot_name[:2].upper()


# --- the client's own vocabulary, by id -----------------------------------
# All 3.3.5a enums, from the core's SharedDefines.h / ItemTemplate.h. Named
# here because a tooltip that says "slot 13" instead of "One-Hand" is not a
# tooltip.

BINDING = {
    1: "Binds when picked up",
    2: "Binds when equipped",
    3: "Binds when used",
    4: "Quest Item",
    5: "Quest Item",
}

INVENTORY_TYPES = {
    1: "Head",
    2: "Neck",
    3: "Shoulder",
    4: "Shirt",
    5: "Chest",
    6: "Waist",
    7: "Legs",
    8: "Feet",
    9: "Wrist",
    10: "Hands",
    11: "Finger",
    12: "Trinket",
    13: "One-Hand",
    14: "Off Hand",
    15: "Ranged",
    16: "Back",
    17: "Two-Hand",
    18: "Bag",
    19: "Tabard",
    20: "Chest",
    21: "Main Hand",
    22: "Off Hand",
    23: "Held In Off-hand",
    24: "Ammo",
    25: "Thrown",
    26: "Ranged",
    27: "Quiver",
    28: "Relic",
}

ITEM_CLASS_WEAPON, ITEM_CLASS_ARMOR = 2, 4

ARMOR_SUBCLASSES = {
    1: "Cloth",
    2: "Leather",
    3: "Mail",
    4: "Plate",
    6: "Shield",
    7: "Libram",
    8: "Idol",
    9: "Totem",
    10: "Sigil",
}

WEAPON_SUBCLASSES = {
    0: "Axe",
    1: "Axe",
    2: "Bow",
    3: "Gun",
    4: "Mace",
    5: "Mace",
    6: "Polearm",
    7: "Sword",
    8: "Sword",
    10: "Staff",
    13: "Fist Weapon",
    14: "Miscellaneous",
    15: "Dagger",
    16: "Thrown",
    18: "Crossbow",
    19: "Wand",
    20: "Fishing Pole",
}

# ITEM_MOD_*. The five base stats and the two pools are the WHITE lines of a
# tooltip; every other modifier is a green "Equip:" sentence, which is how
# the client draws them.
BASE_STATS = {
    0: "Mana",
    1: "Health",
    3: "Agility",
    4: "Strength",
    5: "Intellect",
    6: "Spirit",
    7: "Stamina",
}
EQUIP_STATS = {
    12: "Increases defense rating by {}.",
    13: "Increases your dodge rating by {}.",
    14: "Increases your parry rating by {}.",
    15: "Increases your shield block rating by {}.",
    16: "Improves melee hit rating by {}.",
    17: "Improves ranged hit rating by {}.",
    18: "Improves spell hit rating by {}.",
    19: "Improves melee critical strike rating by {}.",
    20: "Improves ranged critical strike rating by {}.",
    21: "Improves spell critical strike rating by {}.",
    28: "Improves melee haste rating by {}.",
    29: "Improves ranged haste rating by {}.",
    30: "Improves spell haste rating by {}.",
    31: "Improves hit rating by {}.",
    32: "Improves critical strike rating by {}.",
    35: "Improves your resilience rating by {}.",
    36: "Improves haste rating by {}.",
    37: "Increases your expertise rating by {}.",
    38: "Increases attack power by {}.",
    39: "Increases ranged attack power by {}.",
    40: "Increases attack power by {} in Cat, Bear, Dire Bear, and Moonkin forms only.",
    41: "Increases healing done by spells by {}.",
    42: "Increases damage done by spells by {}.",
    43: "Restores {} mana per 5 sec.",
    44: "Increases your armor penetration rating by {}.",
    45: "Increases spell power by {}.",
    46: "Restores {} health per 5 sec.",
    47: "Increases your spell penetration by {}.",
    48: "Increases the block value of your shield by {}.",
}

RESISTANCES = [
    ("holy_res", "Holy"),
    ("fire_res", "Fire"),
    ("nature_res", "Nature"),
    ("frost_res", "Frost"),
    ("shadow_res", "Shadow"),
    ("arcane_res", "Arcane"),
]

# spelltrigger_N -> the word the tooltip leads the sentence with.
SPELL_TRIGGERS = {0: "Use", 1: "Equip", 2: "Chance on hit", 5: "Equip"}

# SpellItemEnchantment effect types.
ENCHANT_PROC, ENCHANT_DAMAGE, ENCHANT_SPELL, ENCHANT_RESIST, ENCHANT_STAT = (
    1,
    2,
    3,
    4,
    5,
)
RESIST_SCHOOLS = {
    1: "Holy",
    2: "Fire",
    3: "Nature",
    4: "Frost",
    5: "Shadow",
    6: "Arcane",
}
# Public compatibility name used by the tooltip contract. Keep the source of
# truth beside the resistance vocabulary so a new school cannot drift between
# the two payloads.
_DAMAGE_SCHOOLS = RESIST_SCHOOLS

# item_instance.enchantments: twelve slots of (id, duration, charges). The
# permanent enchant, the temporary one, three gems, the socket bonus, the
# prismatic socket, and five slots for what a random suffix or property
# applied. The last five are how "of the Tiger" reaches an item.
ENCHANT_SLOTS = 12
PERMANENT_ENCHANT_SLOT, TEMPORARY_ENCHANT_SLOT = 0, 1
GEM_SLOTS = range(2, 5)
BONUS_ENCHANT_SLOT, PRISMATIC_ENCHANT_SLOT = 5, 6
PROPERTY_ENCHANT_SLOTS = range(7, 12)

# RandPropPoints groups: which of its five columns an inventory type reads,
# exactly as Item::GetItemSuffixFactor picks them. A "Belt of the Monkey"
# gets less agility than a "Chestpiece of the Monkey" of the same level, and
# this is the whole of why.
SUFFIX_GROUP = {
    1: 0,
    5: 0,
    7: 0,
    17: 0,
    20: 0,
    3: 1,
    6: 1,
    8: 1,
    10: 1,
    12: 1,
    2: 2,
    9: 2,
    11: 2,
    14: 2,
    16: 2,
    23: 2,
    13: 3,
    21: 3,
    22: 3,
    15: 4,
    25: 4,
    26: 4,
}
SUFFIX_QUALITY_COLUMN = {4: 0, 5: 0, 6: 0, 3: 1, 7: 1, 2: 2}

# The portrait in the middle of the paper doll. There is no character model
# renderer here and no honest way to fake one, so the centre shows the
# client's own race-and-gender portrait icon with the class icon beside it -
# the same two icons the character sheet and the guild roster use. Both are
# named the way the icon host files them; the page draws a silhouette if
# the host is unreachable, never a blank.
RACE_ICON_NAMES = {
    1: "human",
    2: "orc",
    3: "dwarf",
    4: "nightelf",
    5: "undead",
    6: "tauren",
    7: "gnome",
    8: "troll",
    10: "bloodelf",
    11: "draenei",
}
CLASS_ICON_NAMES = {
    1: "warrior",
    2: "paladin",
    3: "hunter",
    4: "rogue",
    5: "priest",
    6: "deathknight",
    7: "shaman",
    8: "mage",
    9: "warlock",
    11: "druid",
}

# The class's own colour (panel.CLASS_COLOURS, the client's RAID_CLASS_COLORS
# table) is what the name in the header is drawn in, as every armory does.

# --- the 3D model (infra#88) ---------------------------------------------
# The page draws each member as Wowhead's model viewer draws a character:
# a race-and-gender model with the customisation the character was made
# with, and the DISPLAY id of every visible item attached at the viewer's
# own slot number. Those slot numbers are the client's INVENTORY TYPES
# (head 1, shoulder 3, shirt 4, chest 5, robe 20, back 16, tabard 19),
# not the paper doll's positions, with two quirks the viewer has and the
# doll does not: whatever is in the hands goes at 21 (main) and 22 (off)
# no matter what kind of weapon it is, and a chest piece that is a robe
# goes at 20 rather than 5 because the model wears it differently. The
# neck, rings and trinkets are never drawn and so are never sent.
INVENTORY_TYPE_CHEST, INVENTORY_TYPE_ROBE = 5, 20
VIEWER_MAIN_HAND, VIEWER_OFF_HAND = 21, 22
# Ranged weapons are attached by their own inventory type: a bow is held
# differently from a gun or a wand, and a relic is not drawn at all.
VIEWER_RANGED_TYPES = frozenset({15, 25, 26})
VIEWER_SLOTS = {
    "head": 1,
    "shoulders": 3,
    "shirt": 4,
    "chest": INVENTORY_TYPE_CHEST,
    "waist": 6,
    "legs": 7,
    "feet": 8,
    "wrists": 9,
    "hands": 10,
    "back": 16,
    "tabard": 19,
    "main hand": VIEWER_MAIN_HAND,
    "off hand": VIEWER_OFF_HAND,
}
# WHERE THE MODEL HOST KEEPS THE ART FOR A DRAWN ITEM (infra#3510). Before it
# can draw a piece the viewer fetches one metadata file for it, and the path
# it builds is its own rule, read out of the pinned build the page loads: the
# display id under a directory named by the viewer slot for the twelve slots
# worn on the body, and a flat item directory for anything held in a hand,
# which carries no slot in its path at all.
#
# It is written here, beside the slot table it is the other half of, rather
# than in the page, for the reason the whole of this module exists: the page
# does not get to decide what a request means. It is also the only way the
# page can ask "is the art for this piece actually there" without a second,
# disagreeing copy of the viewer's rule in JavaScript.
VIEWER_BODY_SLOTS = frozenset({1, 3, 4, 5, 6, 7, 8, 9, 10, 16, 19, 20})


def viewer_asset(slot: int, display_id: int) -> str:
    """A drawn item -> the model host's path for the metadata behind it.

    A tail, not an address: WHICH host these hang off is the page's to know,
    and the page reaches them through this server's own cache rather than
    the model host directly (modelviewer.py says why).
    """
    if slot in VIEWER_BODY_SLOTS:
        return f"meta/armor/{slot}/{display_id}.json"
    return f"meta/item/{display_id}.json"


# WHY A PIECE THAT CANNOT BE DRAWN HAS TO SAY SO (infra#3510). The model host
# does not have art for every display id the world database holds, and when it
# has none the viewer swallows the miss: it drops that one piece and draws
# the rest. A character whose legs and boots were dropped is a character in
# its underwear and bare feet - which is EXACTLY what a character who owns
# neither looks like, so the failure hides inside a picture that is already
# meaningful. It went unreported for as long as it did because there was
# nothing anywhere, on the page or in the log, that said a piece had been
# asked for and not drawn.
#
# So each drawn item carries the sentence to print if its art turns out to be
# missing, written here where a test can read it, and the page prints the
# ones that actually failed. The paper doll beside the model still shows the
# item: the claim is about the PICTURE, never about the gear.
MODEL_GAP_HINT = "Worn, but not drawn - the model host has no art for these:"


def _model_gap_note(slot_name: str, item_name: str | None, display_id: int) -> str:
    """What one undrawn piece says about itself.

    The display id is on the line on purpose. It is the number somebody has
    to carry to the model host to find out whether the art is missing or the
    world database is naming art that never existed, and it is not written
    anywhere else on this tab.
    """
    named = item_name or "an item the world database does not name"
    return f"{slot_name} - {named} (display {display_id})"


# characters.* -> the viewer's own names for the same five numbers. Both
# sides are indexes into the race's list of choices, so they pass straight
# through.
APPEARANCE_COLUMNS = {
    "skin": "skin",
    "face": "face",
    "hairStyle": "hairStyle",
    "hairColor": "hairColor",
    "facialStyle": "facialStyle",
}

# --- the derived stats, when the world has not saved them --------------
# character_stats is the core's OWN reading of every derived number (dodge,
# crit, attack power...) and is the source used whenever a row exists. It
# is written on save only when PlayerSave.Stats.MinLevel allows it, so a
# character may have none yet; for that case the handful of stats that CAN
# be honestly derived from base stats and gear are computed with the core's
# own formulas (Player::UpdateAttackPowerAndDamage and friends, 3.3.5a),
# and everything that cannot is reported as unavailable rather than guessed.
# Attack power: (level multiplier, strength multiplier, agility multiplier,
# constant) per class.
MELEE_AP = {
    1: (3, 2, 0, -20),
    2: (3, 2, 0, -20),
    6: (3, 2, 0, -20),
    3: (2, 1, 1, -20),
    4: (2, 1, 1, -20),
    7: (2, 1, 1, -20),
    11: (0, 2, 0, -20),
    8: (0, 1, 0, -10),
    5: (0, 1, 0, -10),
    9: (0, 1, 0, -10),
}
RANGED_AP = {
    3: (2, 0, 1, -10),
    4: (1, 0, 1, -10),
    1: (1, 0, 1, -10),
    11: (0, 0, 0, 0),
    2: (0, 0, 0, 0),
    6: (0, 0, 0, 0),
    7: (0, 0, 0, 0),
    8: (0, 0, 1, -10),
    5: (0, 0, 1, -10),
    9: (0, 0, 1, -10),
}
# Power pool per class: the label, and the character_stats column that
# holds its maximum. Rage and runic power are stored x10.
POWER = {
    1: ("Rage", "maxpower2", 10),
    4: ("Energy", "maxpower4", 1),
    6: ("Runic Power", "maxpower7", 10),
}
DEFAULT_POWER = ("Mana", "maxpower1", 1)
# The first twenty points of stamina are worth one health each and every
# point after that ten; intellect is the same shape at fifteen mana.
STAT_BONUS_FLOOR = 20

# WHERE A STAT CAME FROM IS PART OF THE STAT. "Attack Power 214" read off the
# world's own save and "Attack Power 214" worked out here from base stats and
# gear are different claims - the second is missing every buff and every
# talent - and a block that prints them in the same ink invites somebody to
# compare two characters whose numbers do not mean the same thing.
#
# Three words, one per row, and a plain-language gloss for each so the word
# does not need to be learned. The page colours by the word; it does not
# decide it.
STAT_SAVED, STAT_DERIVED, STAT_UNAVAILABLE = "saved", "derived", "unavailable"
STAT_SOURCE_GLOSS = {
    STAT_SAVED: "read from the world's own save of this character",
    STAT_DERIVED: "worked out from base stats and gear; buffs and talents "
    "are not counted",
    STAT_UNAVAILABLE: "the world has not saved this and it cannot be worked "
    "out honestly from what is here",
}
# The same three, said once for the block as a whole.
STAT_BLOCK_GLOSS = {
    STAT_SAVED: "the world's own reading, as it was last saved.",
    STAT_DERIVED: "the world has not saved this character's stats yet: base "
    "plus gear where that is honest, unavailable where it is not.",
    STAT_UNAVAILABLE: "no base stats for this race, class and level, so "
    "nothing in this block can be worked out.",
}


def stat_reading(value) -> str:
    """What a stat PRINTS.

    A stat the world has not saved prints the word, never a zero: 0 attack
    power and 0 dodge are numbers somebody acts on, and printing them for
    "we do not know" is the one failure this whole block is arranged around.
    Whole floats print whole, because "4.0% dodge" is a percentage nobody
    writes that way.
    """
    if value is None:
        return STAT_UNAVAILABLE
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@dataclass(frozen=True)
class TalentBook:
    """The frozen client talent tables: spell id -> which talent, which rank.

    Loaded the same way Geometry loads zones.json - once, at import, from a
    file committed beside the code. `trees` is keyed by tab id (as a string,
    because it came from JSON); `by_spell` is the reverse index built here so
    the committed file does not have to carry it twice.
    """

    trees: dict[str, dict]
    talents: list[dict]
    by_spell: dict[int, tuple[dict, int]]

    @classmethod
    def load(cls, static_dir: str) -> "TalentBook":
        with open(os.path.join(static_dir, "talents.json")) as f:
            book = json.load(f)
        by_spell: dict[int, tuple[dict, int]] = {}
        for talent in book["talents"]:
            for index, spell in enumerate(talent["ranks"]):
                by_spell[spell] = (talent, index + 1)
        return cls(trees=book["trees"], talents=book["talents"], by_spell=by_spell)

    def trees_for(self, class_id: int) -> list[tuple[str, dict]]:
        """That class's three trees, in the order the game draws them."""
        trees = [(tid, t) for tid, t in self.trees.items() if t["class"] == class_id]
        return sorted(trees, key=lambda pair: pair[1]["order"])

    def grid_for(self, tree_id: str) -> list[dict]:
        """Every talent in one tree, tier then column: the trainer's grid."""
        talents = [t for t in self.talents if str(t["tree"]) == tree_id]
        return sorted(talents, key=lambda t: (t["row"], t["col"]))


@dataclass(frozen=True)
class ItemBook:
    """The frozen client item tables: what the world database cannot say.

    Icons by displayid, spell text by spell id, sets, enchantments and the
    random-suffix tables - three files, one book. Built by
    tools/gen_items.py; see there for what each section is and why it is
    needed, and why three files.
    """

    icons: dict[int, str]
    spells: dict[int, str]
    sets: dict[int, dict]
    enchants: dict[int, list]
    suffixes: dict[int, list]
    properties: dict[int, list]
    points: dict[int, list]
    # item entry -> the MODEL HOST's display id, where it is not the world's
    # own (tools/gen_viewer_displays.py says why the two numberings differ).
    # Defaulted so a book built by hand in a test still constructs.
    viewer_displays: dict[int, int] = field(default_factory=dict)

    @classmethod
    def load(cls, static_dir: str) -> "ItemBook":
        with open(os.path.join(static_dir, "items.json")) as f:
            book = json.load(f)
        with open(os.path.join(static_dir, "icons.json")) as f:
            icons = json.load(f)
        with open(os.path.join(static_dir, "spells.json")) as f:
            spells = json.load(f)
        names = icons["names"]
        return cls(
            icons={int(d): names[i] for d, i in icons["display"].items()},
            spells={int(k): v for k, v in spells.items()},
            sets={int(k): v for k, v in book["sets"].items()},
            enchants={int(k): v for k, v in book["enchants"].items()},
            suffixes={int(k): v for k, v in book["suffixes"].items()},
            properties={int(k): v for k, v in book["properties"].items()},
            points={int(k): v for k, v in book["points"].items()},
            viewer_displays=load_viewer_displays(static_dir),
        )


def load_viewer_displays(static_dir: str) -> dict[int, int]:
    """viewerdisplays.json -> {item entry: model host display id}."""
    with open(os.path.join(static_dir, "viewerdisplays.json")) as f:
        return {int(k): v for k, v in json.load(f)["display"].items()}


def viewer_display(row: dict, displays: dict[int, int] | None) -> int | None:
    """The display id the MODEL HOST keeps this item's art under.

    THE WORLD'S NUMBER IS THE WRONG ONE FOR ABOUT HALF THE ITEMS. The world
    database carries the 3.3.5a client's display ids; the model host keys its
    art by the modern Wrath Classic client's, and that client renumbered
    roughly half of the equippable items. Sending the world's number for one
    of those is a 404 the viewer swallows, and the character is drawn without
    the piece - which is how the family came to be drawn nearly naked while
    wearing a full set. The frozen table holds only the entries that differ,
    so an entry that is absent keeps the world's number.
    """
    world = row.get("displayid") or None
    if not world:
        return None
    return (displays or {}).get(row.get("entry"), world)


def viewer_slot(slot_name: str, inventory_type: int | None) -> int | None:
    """A paper-doll slot and the item's inventory type -> the viewer's slot.

    None for a slot the viewer never draws (neck, rings, trinkets) and for
    a ranged slot holding something that is not a drawn weapon (a relic,
    a quiver). The robe quirk: a chest piece of inventory type 20 is
    attached at 20, every other chest piece at 5.
    """
    if slot_name == "chest":
        return (
            INVENTORY_TYPE_ROBE
            if inventory_type == INVENTORY_TYPE_ROBE
            else INVENTORY_TYPE_CHEST
        )
    if slot_name == "ranged":
        return inventory_type if inventory_type in VIEWER_RANGED_TYPES else None
    return VIEWER_SLOTS.get(slot_name)


def viewer_model(
    char_row: dict, equipment_rows: list[dict], displays: dict[int, int] | None = None
) -> dict | None:
    """The character as the model viewer wants it, or None if it cannot be drawn.

    `gender` is sent as the database stores it (0 male, 1 female): the
    viewer's model id is race * 2 - 1 + gender and model 1 is the human
    male, so the two agree and nothing is flipped. The five appearance
    numbers are omitted when the row does not carry them (an older row,
    or a fixture) rather than defaulted, so the viewer picks its own
    first choice instead of drawing a face the character does not have.
    `items` are [viewer slot, display id] pairs for every drawn slot that
    holds an item the world database knows a display for. The display id is
    the MODEL HOST's (viewer_display, via `displays`), not the world's own.

    `assets` is the SAME list read the other way round: one entry per pair,
    carrying the model host's own path for that piece's metadata and the
    sentence to print if the host turns out not to have it. The viewer will
    fetch exactly these paths and say nothing when one is missing, so this
    is what lets the page report a piece it could not draw instead of
    leaving a bare-legged character to be read as a character with no legs.
    """
    race, gender = char_row.get("race"), char_row.get("gender")
    if race not in RACE_ICON_NAMES or gender not in (0, 1):
        return None
    model: dict = {"race": race, "gender": gender}
    for column, key in APPEARANCE_COLUMNS.items():
        value = char_row.get(column)
        if value is not None:
            model[key] = int(value)
    items: list[list[int]] = []
    assets: list[dict] = []
    for row in sorted(equipment_rows, key=lambda r: r["slot"]):
        if row["slot"] >= len(EQUIPPED_SLOTS) or not row.get("displayid"):
            continue
        slot_name = EQUIPPED_SLOTS[row["slot"]]
        slot = viewer_slot(slot_name, row.get("inventory_type"))
        if slot is not None:
            display = viewer_display(row, displays)
            items.append([slot, display])
            assets.append(
                {
                    "slot": slot_name,
                    "path": viewer_asset(slot, display),
                    "note": _model_gap_note(slot_name, row.get("item_name"), display),
                }
            )
    model["items"] = items
    model["assets"] = assets
    return model


def talent_points_at(level: int, class_id: int) -> int | None:
    """How many points a character of this level and class should have spent."""
    if class_id == DEATH_KNIGHT:
        return None
    return max(0, level - FIRST_TALENT_LEVEL + 1)


def _quality_name(quality: int | None) -> str:
    if quality is None:
        return UNKNOWN_QUALITY
    return QUALITY_NAMES.get(quality, UNKNOWN_QUALITY)


def parse_enchantments(text: str | None) -> list[int]:
    """item_instance.enchantments -> the enchant id in each of the 12 slots.

    The column is a space-separated run of (id, duration, charges) triples.
    Anything malformed reads as no enchantments, which is what a row the
    core has not written yet also reads as.
    """
    if not text:
        return [0] * ENCHANT_SLOTS
    try:
        values = [int(v) for v in text.split()]
    except ValueError:
        return [0] * ENCHANT_SLOTS
    ids = values[::3][:ENCHANT_SLOTS]
    return ids + [0] * (ENCHANT_SLOTS - len(ids))


def suffix_factor(row: dict, book: ItemBook) -> int:
    """The item-level scaling a random SUFFIX's stats are a percentage of."""
    group = SUFFIX_GROUP.get(row["inventory_type"] or 0)
    column = SUFFIX_QUALITY_COLUMN.get(row["quality"] or 0)
    points = book.points.get(row["item_level"] or 0)
    if group is None or column is None or points is None:
        return 0
    return points[column][group]


def money(copper: int | None) -> dict | None:
    if not copper:
        return None
    return {
        "gold": copper // 10000,
        "silver": copper // 100 % 100,
        "copper": copper % 100,
    }


def _class_list(mask: int | None) -> list[str] | None:
    """AllowableClass -> the classes named, or None when anyone can wear it."""
    if mask is None or mask <= 0:
        return None
    named = [name for cid, name in _CLASS_NAMES.items() if mask & (1 << (cid - 1))]
    if len(named) == len(_CLASS_NAMES):
        return None
    return named


def _scaled(amount: int, pct: int | None, row: dict, book: ItemBook) -> int:
    """A suffix enchant's amount: the allocation, scaled by the item's level.

    A stat with amount 0 is a random suffix's, and the core scales it from
    RandPropPoints when the item is equipped; this is that arithmetic.
    """
    if amount or pct is None:
        return amount
    return pct * suffix_factor(row, book) // 10000


def _stat_line(arg: int, amount: int) -> str:
    label = BASE_STATS.get(arg)
    if label:
        return f"+{amount} {label}"
    if arg in EQUIP_STATS:
        return "Equip: " + EQUIP_STATS[arg].format(amount)
    return f"+{amount} stat #{arg}"


def _enchant_lines(
    enchant_id: int, row: dict, book: ItemBook, pct: int | None
) -> tuple[list[str], dict[int, int]]:
    """One enchantment -> its tooltip lines and the stats it adds.

    Returns (lines, {stat type: amount}).
    """
    entry = book.enchants.get(enchant_id)
    if entry is None:
        return [f"Enchantment #{enchant_id}"], {}
    name, effects = entry
    fallback = name or f"Enchantment #{enchant_id}"
    lines: list[str] = []
    stats: dict[int, int] = {}
    for kind, amount, arg in effects:
        if kind == ENCHANT_STAT:
            amount = _scaled(amount, pct, row, book)
            stats[arg] = stats.get(arg, 0) + amount
            lines.append(_stat_line(arg, amount))
        elif kind == ENCHANT_RESIST:
            amount = _scaled(amount, pct, row, book)
            lines.append(f"+{amount} {RESIST_SCHOOLS.get(arg, 'All')} Resistance")
        elif kind in (ENCHANT_PROC, ENCHANT_SPELL):
            text = book.spells.get(arg)
            lead = "Chance on hit" if kind == ENCHANT_PROC else "Equip"
            lines.append(f"{lead}: {text}" if text else fallback)
        elif kind == ENCHANT_DAMAGE:
            lines.append(f"+{amount} Weapon Damage")
        else:
            lines.append(fallback)
    return lines or [fallback], stats


def _random_property(row: dict, book: ItemBook) -> tuple[str, dict[int, int]]:
    """item_instance.randomPropertyId -> (suffix name, allocation per enchant).

    Positive ids are ItemRandomProperties (fixed amounts, no allocation);
    negative ones are ItemRandomSuffix, whose enchants carry a percentage
    of the item's RandPropPoints instead of an amount.
    """
    random_id = row.get("random_property_id") or 0
    if random_id > 0:
        prop = book.properties.get(random_id)
        return (prop[0] if prop else ""), {}
    if random_id < 0:
        suffix = book.suffixes.get(-random_id)
        if suffix:
            return suffix[0], {e: pct for e, pct in suffix[1]}
    return "", {}


def _template_stats(row: dict) -> tuple[dict[int, int], list[str], list[str]]:
    """The template's ten stat slots -> (sums, white lines, green lines)."""
    stats: dict[int, int] = {}
    white: list[str] = []
    green: list[str] = []
    for n in range(1, 11):
        kind, value = row.get(f"stat_type{n}"), row.get(f"stat_value{n}")
        if not value:
            continue
        stats[kind] = stats.get(kind, 0) + value
        if kind in BASE_STATS:
            white.append(f"{value:+d} {BASE_STATS[kind]}")
        elif kind in EQUIP_STATS:
            green.append("Equip: " + EQUIP_STATS[kind].format(value))
    return stats, white, green


def _instance_enchants(
    row: dict,
    book: ItemBook,
    pct_by_enchant: dict[int, int],
    stats: dict[int, int],
    white: list[str],
    green: list[str],
) -> list[str]:
    """The twelve enchantment slots, sorted into the tooltip's three places.

    A random property's stats sit among the white lines, as the game draws
    them, not as a separate "enchanted" block. An enchant or a poison
    applied to the item is drawn by NAME ("+6 Weapon Damage", "Instant
    Poison"), which is what the client does - the spell behind a poison
    describes the poison to the rogue, not the weapon to a reader.
    """
    named: list[str] = []
    for slot, enchant_id in enumerate(parse_enchantments(row.get("enchantments"))):
        if not enchant_id:
            continue
        from_property = slot in PROPERTY_ENCHANT_SLOTS
        pct = pct_by_enchant.get(enchant_id) if from_property else None
        lines, added = _enchant_lines(enchant_id, row, book, pct)
        for kind, amount in added.items():
            stats[kind] = stats.get(kind, 0) + amount
        if from_property:
            white.extend(line for line in lines if not line.startswith("Equip:"))
            green.extend(line for line in lines if line.startswith("Equip:"))
            continue
        entry = book.enchants.get(enchant_id)
        named.extend([entry[0]] if entry and entry[0] else lines)
    return named


def _spell_effects(row: dict, book: ItemBook) -> list[str]:
    """spellid_1..5 -> the green "Equip:" / "Use:" / "Chance on hit:" lines."""
    lines: list[str] = []
    for n in range(1, 6):
        spell, trigger = row.get(f"spellid_{n}"), row.get(f"spelltrigger_{n}")
        lead = SPELL_TRIGGERS.get(trigger)
        # No lead: learn-on-use, soulstone and the like, not a tooltip line.
        if spell and lead is not None:
            text = book.spells.get(spell)
            lines.append(f"{lead}: {text}" if text else f"{lead}: spell #{spell}")
    return lines


def _elemental_damage(row: dict) -> list[dict] | None:
    """The `+N - M <School> Damage` line(s), separate from base weapon damage.

    infra#3513: item_template on this world carries exactly one extra
    damage slot - dmg_min2/dmg_max2/dmg_type2 (verified live: `DESCRIBE
    item_template` has no dmg_min3.. at all, unlike some other cores) - and
    dmg_type2 is a SpellSchool id (1 Holy .. 6 Arcane), the same vocabulary
    RESIST_SCHOOLS already names for resistances. Torturing Poker (entry
    7682) confirmed the mapping live: dmg_type2=2, dmg_min2=5, dmg_max2=7 -
    exactly the "+5 - 7 Fire Damage" line missing from the tooltip. A
    dmg_type2 of 0 is physical, which base `_damage` already carries as
    dmg_min1/dmg_max1 - listing it again here would double the same number
    under a second label, so 0 is excluded.
    """
    school = RESIST_SCHOOLS.get(row.get("dmg_type2") or 0)
    if not school or not row.get("dmg_min2"):
        return None
    return [{"school": school, "min": row["dmg_min2"], "max": row["dmg_max2"]}]


def _secondary_damage(row: dict) -> list[dict] | None:
    """Compatibility spelling for the public secondary-damage contract."""
    return _elemental_damage(row)


def _damage(row: dict) -> dict | None:
    if not row.get("dmg_min1"):
        return None
    speed = (row.get("delay") or 0) / 1000
    dps = (row["dmg_min1"] + row["dmg_max1"]) / 2 / speed if speed else None
    return {
        "min": row["dmg_min1"],
        "max": row["dmg_max1"],
        "speed": speed,
        "dps": round(dps, 1) if dps is not None else None,
        "elemental": _elemental_damage(row),
    }


def _item_kind(row: dict) -> str | None:
    """'Mail', 'Sword': the right-hand word of the slot line."""
    item_class, subclass = row.get("class"), row.get("subclass")
    if item_class == ITEM_CLASS_ARMOR:
        return ARMOR_SUBCLASSES.get(subclass)
    if item_class == ITEM_CLASS_WEAPON:
        return WEAPON_SUBCLASSES.get(subclass)
    return None


def _item_set(
    row: dict, book: ItemBook, worn_entries: set[int], set_names: dict[int, str]
) -> dict | None:
    entry = book.sets.get(row.get("itemset") or 0)
    if entry is None:
        return None
    pieces = [
        {"entry": e, "name": set_names.get(e, f"Item #{e}"), "worn": e in worn_entries}
        for e in entry["items"]
    ]
    worn = sum(1 for p in pieces if p["worn"])
    return {
        "name": entry["name"],
        "worn": worn,
        "total": len(pieces),
        "pieces": pieces,
        "bonuses": [
            {
                "threshold": t,
                "active": worn >= t,
                "text": book.spells.get(s, f"spell #{s}"),
            }
            for t, s in entry["bonuses"]
        ],
    }


def _tooltip(
    row: dict, book: ItemBook, worn_entries: set[int], set_names: dict[int, str]
) -> tuple[dict, dict[int, int], int]:
    """The lines the game draws for one item, in the order it draws them.

    Returns (tooltip, {stat type: amount}, armor) so the stat block can be
    derived from the same reading a person sees - one source, two views.
    """
    suffix_name, pct_by_enchant = _random_property(row, book)
    name = row["item_name"] if row["item_name"] is not None else f"Item #{row['entry']}"
    if suffix_name:
        name = f"{name} {suffix_name}"
    stats, white, green = _template_stats(row)
    enchant_lines = _instance_enchants(row, book, pct_by_enchant, stats, white, green)
    green.extend(_spell_effects(row, book))
    max_durability = row.get("max_durability") or 0
    armor = row.get("armor") or 0
    tooltip = {
        "name": name,
        "quality": row["quality"],
        "item_level": row["item_level"],
        "binding": BINDING.get(row.get("bonding") or 0),
        "slot": INVENTORY_TYPES.get(row.get("inventory_type") or 0),
        "kind": _item_kind(row),
        "damage": _damage(row),
        "secondary_damage": _secondary_damage(row),
        "armor": armor or None,
        "block": row.get("block") or None,
        "stats": white,
        "resistances": [
            f"+{row[col]} {school} Resistance"
            for col, school in RESISTANCES
            if row.get(col)
        ],
        "enchant": enchant_lines,
        "durability": f"{row.get('durability') or 0} / {max_durability}"
        if max_durability
        else None,
        "classes": _class_list(row.get("allowable_class")),
        "requires_level": row["required_level"] or None,
        "effects": green,
        "set": _item_set(row, book, worn_entries, set_names),
        "flavor": row.get("description") or None,
        "sell_price": money(row.get("sell_price")),
    }
    return tooltip, stats, armor


def template_tooltip(row: dict, book: ItemBook) -> dict | None:
    """The lines the game draws for an item that is in nobody's hands.

    `_tooltip` above reads an item INSTANCE: this belt, with this enchant, at
    this durability, carrying the suffix that makes it a Belt of the Tiger.
    Every OTHER view on this page names an item no character is holding - a
    drop on the loot board, a first equip in the Chronicle, a quest reward -
    and there is no instance row behind any of those. So the three
    instance-only readings are answered here rather than left to arrive as
    zeros, which is what each of them would otherwise do:

    - no enchantments and no random property. The template is what DROPS;
      what it becomes once somebody puts it on is a fact about their copy.
    - durability at FULL, because `_tooltip` prints "durability / max" off a
      column a template row does not have. Left alone that reads "0 / 55",
      which is the tooltip for a broken sword.
    - no item set. `_item_set` names the other pieces out of a lookup the
      caller supplies and none of these callers has one, so a set header over
      five lines of "Item #40303" would say less than no set header at all.

    None for a row from a NARROW read. Four queries behind this page used to
    select a name, a quality and a level and nothing else; a caller that has
    not been widened gets no tooltip rather than a tooltip full of nulls, and
    the page draws the name without the affordance that would open one.
    """
    if not row or "item_name" not in row:
        return None
    unheld = dict(row)
    unheld["enchantments"] = None
    unheld["random_property_id"] = 0
    unheld["durability"] = row.get("max_durability")
    tooltip, _stats, _armor = _tooltip(unheld, book, frozenset(), {})
    tooltip["set"] = None
    return tooltip


def _slot_payload(
    slot_name: str,
    row: dict | None,
    book: ItemBook,
    worn_entries: set[int],
    set_names: dict[int, str],
) -> dict:
    """One paper-doll slot, whether or not anything is in it."""
    cosmetic = slot_name in COSMETIC_SLOTS
    mark = slot_mark(slot_name)
    if row is None:
        reading = empty_reading(slot_name)
        return {
            "slot": slot_name,
            "mark": mark,
            "cosmetic": cosmetic,
            "empty": True,
            "empty_kind": reading["kind"],
            "empty_label": reading["label"],
            "empty_note": reading["note"],
        }
    # A LEFT JOIN miss on acore_world.item_template is a custom or removed
    # item: it is genuinely equipped, so it must not read as an empty slot.
    # Say which item instead of drawing a blank, the same way panel does.
    tooltip, stats, armor = _tooltip(row, book, worn_entries, set_names)
    max_durability = row["max_durability"] or 0
    return {
        "slot": slot_name,
        "mark": mark,
        "cosmetic": cosmetic,
        "empty": False,
        # A worn slot has no empty reading, and says so with a null rather
        # than by leaving the keys off: the page reads the same fields for
        # every cell it draws.
        "empty_kind": None,
        "empty_label": None,
        "empty_note": None,
        "entry": row["entry"],
        "name": tooltip["name"],
        "quality": row["quality"],
        "quality_name": _quality_name(row["quality"]),
        "item_level": row["item_level"],
        # The corner of the cell, already a string: an item the world database
        # does not know has no level, and "" is the honest mark for that. A
        # page left to do this itself writes `|| 0` and paints a level-0 item.
        "item_level_mark": "" if row["item_level"] is None else str(row["item_level"]),
        "required_level": row["required_level"],
        # The icon is the DISPLAY's, and a display the book does not know
        # (a custom item) gets none: the page draws the slot name instead.
        "icon": book.icons.get(row.get("displayid") or 0),
        # The DISPLAY id, for the 3D model: what the item looks like, as
        # distinct from what it is. A custom item with no template has none.
        "display_id": row.get("displayid") or None,
        # Rings, cloaks, necks and trinkets have no durability at all, so a
        # stored 0 only means "broken" when the item HAS durability to lose.
        "broken": bool(max_durability) and not row["durability"],
        "tooltip": tooltip,
        "_stats": stats,
        "_armor": armor,
    }


# How loud each header chip is. Three words, because there are three kinds of
# thing to say: a fact, something to look at, something to fix.
TONE_PLAIN, TONE_CAUTION, TONE_WARN = "plain", "caution", "warn"


def _build_gear(slots: list[dict]) -> dict:
    """The read across one character's slots: what is worn, what is missing."""
    counts = [s for s in slots if not s["cosmetic"]]
    worn = [s for s in counts if not s["empty"]]
    levels = [s["item_level"] for s in worn if s["item_level"] is not None]
    empty_slots = [s["slot"] for s in counts if s["empty"]]
    broken = [s["slot"] for s in worn if s["broken"]]
    # Averaged over what is WORN, not over every slot. Counting an empty
    # slot as item level 0 would fold two different complaints - "his gear
    # is old" and "he has no helmet" - into one number that answers
    # neither. The empty slots are listed right beside it instead.
    average = round(sum(levels) / len(levels)) if levels else None
    # The header's chips, in the order the design reads them: what the gear
    # is worth, how much of it there is, and then only the two things that
    # are wrong, if either is. Which chips exist and how loud each one is is
    # the judgement; the page draws what it is handed.
    chips = [
        {
            "key": "average item level",
            "value": stat_reading(average),
            "tone": TONE_PLAIN,
        },
        {
            "key": "slots worn",
            "value": f"{len(worn)} of {len(counts)}",
            "tone": TONE_PLAIN,
        },
    ]
    # EMPTY IS A COUNT AND BROKEN IS A LIST, and the asymmetry is deliberate.
    # Both are visible on the doll directly below - an empty slot is dashed
    # amber and says the word, a broken one wears a vermilion ring - so the
    # chip does not have to repeat what the doll already draws. What differs
    # is what you do next: an empty slot is scanned ("how far off is he"),
    # while a broken item is carried to a repair vendor by name, and eleven
    # slot names in a header chip is a wall of text that buries the one line
    # under it that is an instruction.
    if empty_slots:
        chips.append(
            {"key": "empty", "value": str(len(empty_slots)), "tone": TONE_CAUTION}
        )
    if broken:
        chips.append({"key": "broken", "value": ", ".join(broken), "tone": TONE_WARN})
    return {
        "worn": len(worn),
        "slots": len(counts),
        "empty_slots": empty_slots,
        "average_item_level": average,
        "broken": broken,
        "chips": chips,
    }


# --- the weakest slot (#174) ----------------------------------------------
# Which worn slot is furthest below the character's level, by gear.py's own
# rule (gear.weakest_slot, through bag_pressure), so the Armory and the guild hand-over pass that
# prefers filling it cannot disagree. The paper doll's slot names map onto
# gear's buckets here; rings, necks and trinkets have no bucket and are not
# judged, the same refusal gear.py makes.
_GEAR_BUCKET_BY_SLOT = {
    "head": "head",
    "shoulders": "shoulder",
    "chest": "chest",
    "waist": "waist",
    "legs": "legs",
    "feet": "feet",
    "wrists": "wrist",
    "hands": "hands",
    "back": "back",
    "main hand": "main_hand",
    "off hand": "off_hand",
    "ranged": "ranged",
}

# How far behind, in gear.weakest_slot's weighted item levels, a slot has to
# be before the family's worst one earns a chip. A level 60 in item level 50
# boots is not news; an item level 30 weapon at 60 (a shortfall of 60) is.
WEAKEST_FLAG = 20
WEAKEST_KEY = "weakest slot"


def weakest_payload(name: str, class_id, level, slots: list[dict]):
    """gear.weakest_slot over one member's paper doll, or None."""
    equipped = {}
    for s in slots:
        bucket = _GEAR_BUCKET_BY_SLOT.get(s["slot"])
        if bucket and not s["empty"] and s.get("item_level") is not None:
            equipped[bucket] = int(s["item_level"])
    try:
        weakest = bag_pressure.weakest_slot_of(name, class_id, level, equipped)
    except (TypeError, ValueError):
        return None
    if weakest is None:
        return None
    return {
        "slot": weakest.label,
        "item_level": weakest.item_level,
        "level": weakest.level,
        "shortfall": weakest.shortfall,
        "said": weakest.said,
    }


def flag_weakest(members: list[dict]) -> list[str]:
    """Put a chip on every member whose weakest slot is badly behind.

    Only past WEAKEST_FLAG, so the header stays quiet on a character with
    nothing far behind. Every member and not only the worst one: measured on
    the dev family 2026-09-22, four of the five carried a weapon between item
    level 24 and 30 at level 60, and naming one of them would hide the other
    three. Returns the names it flagged, worst first.
    """
    behind = [
        m
        for m in members
        if m.get("weakest") and m["weakest"]["shortfall"] >= WEAKEST_FLAG
    ]
    behind.sort(key=lambda m: (-m["weakest"]["shortfall"], m["name"]))
    for m in behind:
        m["gear"]["chips"].append(
            {"key": WEAKEST_KEY, "value": m["weakest"]["said"], "tone": TONE_CAUTION}
        )
    return [m["name"] for m in behind]


def _stat(key: str, label: str, value, note: str | None = None) -> dict:
    return {
        "key": key,
        "label": label,
        "value": value,
        "reading": stat_reading(value),
        "note": note,
    }


def _sourced(rows: list[dict], source: str) -> list[dict]:
    """Label every row with where its own number came from.

    The block has one source and the rows do NOT: a derived block still
    contains dodge and parry, which cannot be derived at all and are not
    "derived, and 0". A row with no value is unavailable whatever the block
    around it managed.
    """
    for row in rows:
        row["source"] = STAT_UNAVAILABLE if row["value"] is None else source
        row["gloss"] = STAT_SOURCE_GLOSS[row["source"]]
    return rows


def _pct(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def _build_stats(
    char_row: dict, saved: dict | None, base: dict | None, slots: list[dict]
) -> dict:
    """The stat block: the core's saved reading, or the honest subset.

    character_stats is preferred outright - it is the world's own answer,
    including everything a talent or a buff adds. Without it, five base
    stats plus gear is a real number (the game's own formula, minus buffs
    and talents), attack power follows from those, and dodge, parry, block
    and crit chance are NOT computable here without the rating tables, so
    they say so.
    """
    class_id, level = char_row["class"], char_row["level"]
    power_label, power_column, power_scale = POWER.get(class_id, DEFAULT_POWER)
    if saved is not None:
        rows = [
            _stat("health", "Health", saved["maxhealth"]),
            _stat("power", power_label, saved[power_column] // power_scale),
            _stat("stamina", "Stamina", saved["stamina"]),
            _stat("strength", "Strength", saved["strength"]),
            _stat("agility", "Agility", saved["agility"]),
            _stat("intellect", "Intellect", saved["intellect"]),
            _stat("spirit", "Spirit", saved["spirit"]),
            _stat("armor", "Armor", saved["armor"]),
            _stat("block", "Block", _pct(saved["blockPct"])),
            _stat("dodge", "Dodge", _pct(saved["dodgePct"])),
            _stat("parry", "Parry", _pct(saved["parryPct"])),
            _stat("attack_power", "Attack Power", saved["attackPower"]),
            _stat("melee_crit", "Melee Critical Strike", _pct(saved["critPct"])),
            _stat(
                "ranged_attack_power", "Ranged Attack Power", saved["rangedAttackPower"]
            ),
            _stat(
                "ranged_crit", "Ranged Critical Strike", _pct(saved["rangedCritPct"])
            ),
            _stat("spell_power", "Spell Power", saved["spellPower"]),
            _stat("spell_crit", "Spell Critical Strike", _pct(saved["spellCritPct"])),
        ]
        return {
            "source": STAT_SAVED,
            "gloss": STAT_BLOCK_GLOSS[STAT_SAVED],
            "rows": _sourced(rows, STAT_SAVED),
        }

    gear: dict[int, int] = {}
    armor = 0
    for s in slots:
        if s["empty"]:
            continue
        for kind, amount in s["_stats"].items():
            gear[kind] = gear.get(kind, 0) + amount
        armor += s["_armor"]
    derived = "base + gear; buffs and talents not counted"
    unavailable = "not saved by the world yet"
    if base is None:
        # No base-stat row for this race, class and level: nothing here can
        # be derived, and the block says so on every line rather than
        # showing a gear-only number that reads as the whole.
        keys = [
            ("health", "Health"),
            ("power", power_label),
            ("stamina", "Stamina"),
            ("strength", "Strength"),
            ("agility", "Agility"),
            ("intellect", "Intellect"),
            ("spirit", "Spirit"),
            ("armor", "Armor"),
            ("block", "Block"),
            ("dodge", "Dodge"),
            ("parry", "Parry"),
            ("attack_power", "Attack Power"),
            ("melee_crit", "Melee Critical Strike"),
            ("ranged_attack_power", "Ranged Attack Power"),
            ("ranged_crit", "Ranged Critical Strike"),
            ("spell_power", "Spell Power"),
            ("spell_crit", "Spell Critical Strike"),
        ]
        rows = [_stat(k, label, None, unavailable) for k, label in keys]
        return {
            "source": STAT_UNAVAILABLE,
            "gloss": STAT_BLOCK_GLOSS[STAT_UNAVAILABLE],
            "rows": _sourced(rows, STAT_UNAVAILABLE),
        }

    stamina = base["stamina"] + gear.get(7, 0)
    strength = base["strength"] + gear.get(4, 0)
    agility = base["agility"] + gear.get(3, 0)
    intellect = base["intellect"] + gear.get(5, 0)
    spirit = base["spirit"] + gear.get(6, 0)
    floor = min(stamina, STAT_BONUS_FLOOR)
    health = base["health"] + floor + (stamina - floor) * 10 + gear.get(1, 0)
    if power_label == "Mana":
        floor = min(intellect, STAT_BONUS_FLOOR)
        power = base["mana"] + floor + (intellect - floor) * 15 + gear.get(0, 0)
    else:
        power = 100
    lv, st, ag, c = MELEE_AP.get(class_id, (0, 1, 0, -10))
    attack_power = lv * level + st * strength + ag * agility + c + gear.get(38, 0)
    lv, st, ag, c = RANGED_AP.get(class_id, (0, 0, 1, -10))
    ranged_power = lv * level + st * strength + ag * agility + c + gear.get(39, 0)
    spell_power = gear.get(45, 0) + gear.get(42, 0)
    rows = [
        _stat("health", "Health", health, derived),
        _stat("power", power_label, power, derived),
        _stat("stamina", "Stamina", stamina, derived),
        _stat("strength", "Strength", strength, derived),
        _stat("agility", "Agility", agility, derived),
        _stat("intellect", "Intellect", intellect, derived),
        _stat("spirit", "Spirit", spirit, derived),
        _stat("armor", "Armor", armor + agility * 2, "gear + 2 per agility"),
        _stat("block", "Block", None, unavailable),
        _stat("dodge", "Dodge", None, unavailable),
        _stat("parry", "Parry", None, unavailable),
        _stat("attack_power", "Attack Power", attack_power, derived),
        _stat("melee_crit", "Melee Critical Strike", None, unavailable),
        _stat("ranged_attack_power", "Ranged Attack Power", ranged_power, derived),
        _stat("ranged_crit", "Ranged Critical Strike", None, unavailable),
        _stat("spell_power", "Spell Power", spell_power, "gear only"),
        _stat("spell_crit", "Spell Critical Strike", None, unavailable),
    ]
    return {
        "source": STAT_DERIVED,
        "gloss": STAT_BLOCK_GLOSS[STAT_DERIVED],
        "rows": _sourced(rows, STAT_DERIVED),
    }


def _build_spec(
    class_id: int, level: int, talent_rows: list[dict], book: TalentBook
) -> dict:
    """A pile of learned spell ids -> the build a person can read.

    Two views of each tree: `talents`, only what is learned (the list the
    first cut of the tab drew), and `grid`, every talent the tree has at its
    true row and column with the rank held - which is what the trainer's
    own window draws and what the page now draws.
    """
    trees = {
        tid: {
            "name": t["name"],
            "icon": t["icon"],
            "points": 0,
            "talents": [],
            "ranks": {},
        }
        for tid, t in book.trees_for(class_id)
    }
    order = [tid for tid, _ in book.trees_for(class_id)]
    unplaced, spent = [], 0
    for row in sorted(talent_rows, key=lambda r: r["spell"]):
        found = book.by_spell.get(row["spell"])
        if found is None:
            # A talent the frozen tables do not know: a custom talent, or a
            # client newer than the committed file. It is still a real point
            # the character has spent, so it is counted and named - dropping
            # it would silently understate the build.
            unplaced.append(
                {"name": f"Spell #{row['spell']}", "rank": None, "max_rank": None}
            )
            spent += 1
            continue
        talent, rank = found
        tid = str(talent["tree"])
        spent += rank
        if tid not in trees:
            # Learned from another class's tree - impossible in play, so it
            # means the character or the tables are wrong. Surfaced, not hidden.
            unplaced.append(
                {"name": talent["name"], "rank": rank, "max_rank": len(talent["ranks"])}
            )
            continue
        trees[tid]["points"] += rank
        trees[tid]["ranks"][talent["id"]] = rank
        trees[tid]["talents"].append(
            {
                "name": talent["name"],
                "rank": rank,
                "max_rank": len(talent["ranks"]),
                "row": talent["row"],
                "col": talent["col"],
            }
        )
    for tid, tree in trees.items():
        # Tier then column: the order the talents sit in on the trainer's
        # own grid, so reading the list top to bottom reads down the tree.
        tree["talents"].sort(key=lambda t: (t["row"], t["col"]))
        ranks = tree.pop("ranks")
        tree["grid"] = [
            {
                "id": t["id"],
                "name": t["name"],
                "icon": t["icon"],
                "row": t["row"],
                "col": t["col"],
                "rank": ranks.get(t["id"], 0),
                "max_rank": len(t["ranks"]),
                "requires": t["requires"],
            }
            for t in book.grid_for(tid)
        ]
        tree["rows"] = TALENT_ROWS
        tree["cols"] = TALENT_COLS
    ordered = [trees[tid] for tid in order]
    available = talent_points_at(level, class_id)
    deepest = max(ordered, key=lambda t: t["points"], default=None)
    distribution = "/".join(str(t["points"]) for t in ordered)
    primary = deepest["name"] if deepest and deepest["points"] else None
    unspent = None if available is None else max(0, available - spent)
    return {
        "trees": ordered,
        # The shorthand every WoW player already reads, in tree order.
        "distribution": distribution,
        "primary": primary,
        "spent": spent,
        "available": available,
        "unspent": unspent,
        "unplaced": unplaced,
        # THE COLLAPSED READING, which is what the tab shows by default.
        # Three grids of forty-four cells each, five times over, is six
        # hundred and sixty icons for a question that is answered by six
        # characters, and the operator said so: the build IS "0/0/15
        # Protection", and the trees are the thing you open when the answer
        # is surprising. So the summary is a first-class field rather than
        # something the page assembles out of four others.
        "headline": f"{distribution} {primary}"
        if primary
        else f"{distribution} nothing spent",
        "budget": f"{spent} points spent"
        if available is None
        else f"{spent} of {available} points spent",
        # Said separately from the budget because it is the only part of it
        # anybody acts on, and it is drawn in the caution colour.
        "unspent_note": None if not unspent else f"{unspent} unspent",
        # The bar, as segments rather than as two numbers and a rule in the
        # page about whether the second one exists. A death knight's budget
        # is unknown, so there is no unspent segment to draw; a character
        # who has spent nothing and is owed nothing has no bar at all.
        "bar": [
            seg
            for seg in (
                {"kind": "spent", "points": spent} if spent else None,
                {"kind": "unspent", "points": unspent} if unspent else None,
            )
            if seg is not None
        ],
    }


# What a profile says when there is no character behind it. A sentence, not
# a blank: a profile stripped to a name is how a missing character stops
# being noticed, which is the failure this whole tab exists to prevent.
ABSENT_NOTE = "no saved character - deleted, or never made."


UNKNOWN_CLASS = "unknown class"


def _absent_member(name: str, bond) -> dict:
    """No `characters` row at all - the character was deleted or never made.

    Unlike the Family tab there is no freshness window here: gear and talents
    are what is SAVED, so a logged-out character still has both and still
    gets a full column; only a missing row lands here.
    """
    return {
        "name": name,
        "role": bond.role if bond else UNKNOWN_ROLE,
        "class": bond.char_class.title() if bond else UNKNOWN_CLASS,
        "class_id": None,
        "present": False,
        "identity": ABSENT_NOTE,
    }


def _member(
    name: str,
    char_row: dict | None,
    equipment_rows: list[dict],
    talent_rows: list[dict],
    stats_row: dict | None,
    base_row: dict | None,
    set_names: dict[int, str],
    book: TalentBook,
    items: ItemBook,
) -> dict:
    # The persona table knows ONE family. A Horde member, or a guildmate, has
    # no bond, and that is not an error: it has no family role, only the
    # party role party_roles gives it from its class.
    bond = bonds.FAMILY.get(name)
    if char_row is None:
        return _absent_member(name, bond)
    class_id, race = char_row["class"], char_row["race"]
    by_slot = {r["slot"]: r for r in equipment_rows}
    worn_entries = {r["entry"] for r in equipment_rows}
    slots = [
        _slot_payload(slot_name, by_slot.get(index), items, worn_entries, set_names)
        for index, slot_name in enumerate(EQUIPPED_SLOTS)
    ]
    stats = _build_stats(char_row, stats_row, base_row, slots)
    for s in slots:
        # The per-item stat sums were for the block above; they are not a
        # thing the page draws and not part of the contract.
        s.pop("_stats", None)
        s.pop("_armor", None)
    # Dual spec: character_talent holds BOTH builds, told apart by specMask,
    # and the active one is the only one the character is actually playing.
    # Summing the two would report a level-25 warrior with 32 points spent.
    active = 1 << char_row["activeTalentGroup"]
    in_play = [r for r in talent_rows if r["specMask"] & active]
    gender = "female" if char_row.get("gender") else "male"
    race_name = _RACE_NAMES.get(race, f"race {race}")
    class_name = _CLASS_NAMES.get(class_id, f"class {class_id}")
    guild = char_row.get("guild") or None
    kills = char_row.get("totalKills") or 0
    # The one line every armory writes under the name, assembled here so the
    # page has a sentence to print rather than four fields and a rule about
    # which of them are worth a separator. A character in no guild has no
    # guild segment, and five PvE characters do not each carry a "0
    # honourable kills" that is furniture on all of them.
    identity = [f"Level {char_row['level']} {race_name} {class_name}"]
    if guild:
        identity.append(guild)
    if kills:
        identity.append(f"{kills} honourable kill" + ("" if kills == 1 else "s"))
    role = bond.role if bond else UNKNOWN_ROLE
    return {
        "name": char_row["name"],
        # The family role ("father") where there is one; party_roles
        # overwrites this with the party role for anyone without a bond.
        "role": role,
        "present": True,
        "class_id": class_id,
        "identity": " - ".join(identity),
        # The word, not the boolean, because the page must not be the place
        # that decides what the opposite of online is called.
        "presence": "online" if char_row["online"] else "offline",
        "level": char_row["level"],
        "class": class_name,
        "class_colour": CLASS_COLOURS.get(class_id, "#ffffff"),
        "race": race_name,
        "gender": gender,
        "faction": "alliance"
        if race in _ALLIANCE_RACES
        else "horde"
        if race in _HORDE_RACES
        else "neutral",
        "online": bool(char_row["online"]),
        # Guild and honourable kills are shown only when there is something
        # to show. A character in no guild has no guild line, not "<none>".
        "guild": guild,
        "honorable_kills": kills,
        "portrait": {
            "race_icon": (
                f"achievement_character_{RACE_ICON_NAMES[race]}_{gender}"
                if race in RACE_ICON_NAMES
                else None
            ),
            "class_icon": (
                f"classicon_{CLASS_ICON_NAMES[class_id]}"
                if class_id in CLASS_ICON_NAMES
                else None
            ),
        },
        "slots": slots,
        # What the 3D viewer draws, or None when the race is one the
        # viewer has no model for; the page keeps the portrait then.
        "model": viewer_model(char_row, equipment_rows, items.viewer_displays),
        "gear": _build_gear(slots),
        "stats": stats,
        "spec": _build_spec(class_id, char_row["level"], in_play, book),
        "weakest": weakest_payload(
            char_row["name"], class_id, char_row["level"], slots
        ),
    }


# --- both families, side by side (#88) --------------------------------------
# The Armory used to draw one family. There are two - an Alliance five and a
# Horde five - and the operator asked to read them as a COMPARISON: Alliance
# on the left, Horde on the right, one row per party role, so the tank is
# beside the tank and the healer beside the healer.
#
# THE ROLE IS THE CLASS'S, BY THE SAME PACKING THE RAID LINEUP USES. A five
# has one tank and one healer. raidlineup already decides who can fill each
# (TANKS, HEALERS) and spends the classes that can ONLY do one thing first,
# so a warrior tanks before a paladin is asked to and a priest heals before
# a druid is. Reading it off the talent tree instead would put a level-11
# character with two points in Fury into the damage row, and the spec a
# character is levelling in is not the seat it holds in the party.
TANK, HEALER, DAMAGE = "tank", "healer", "damage"
UNKNOWN_ROLE = "unknown"
ROLE_ORDER = (TANK, HEALER, DAMAGE)
# How the damage row is matched when the classes differ: melee against
# melee, casters against casters. Druids and shamans are either, and their
# deepest tree says which.
MELEE_CLASSES = frozenset(
    {raidlineup.WARRIOR, raidlineup.PALADIN, raidlineup.ROGUE, raidlineup.DEATH_KNIGHT}
)
MELEE_TREES = frozenset({"Feral Combat", "Enhancement"})
# What an empty half of a row says. A blank cell reads as a card that
# failed to load; this says the other family simply has nobody for it.
NO_COUNTERPART = "no one in this role on this side"
FACTION_HEADINGS = {"alliance": "Alliance", "horde": "Horde"}


def party_roles(members: list[dict]) -> dict[str, str]:
    """name -> tank, healer or damage, for one family of five.

    Present members only; in roster order within a class band, so the lead
    is chosen first when two could do it. A member with no saved character
    has no class to read and gets no role. The packing itself is
    raidlineup.party_roles, which gear.py's role guard reads as well (#174),
    so the Armory and the hand-off passes cannot disagree about who tanks.
    """
    return raidlineup.party_roles([m for m in members if m.get("present")])


def _style(m: dict) -> str:
    if m.get("class_id") in MELEE_CLASSES:
        return "melee"
    primary = (m.get("spec") or {}).get("primary")
    if m.get("class_id") in (raidlineup.DRUID, raidlineup.SHAMAN):
        return "melee" if primary in MELEE_TREES else "ranged"
    return "ranged"


def _zip_rows(role: str, left: list[str], right: list[str]) -> list[dict]:
    """Two name lists side by side, the shorter padded with None."""
    return [
        {
            "role": role,
            "left": left[i] if i < len(left) else None,
            "right": right[i] if i < len(right) else None,
        }
        for i in range(max(len(left), len(right)))
    ]


# How the damage row is matched, tightest first: the same class, then the
# same style, then anyone left.
_DAMAGE_RULES = (
    lambda a, b: a.get("class_id") == b.get("class_id"),
    lambda a, b: _style(a) == _style(b),
    lambda a, b: True,
)


def _match_damage(left: list[dict], right: list[dict]) -> list[dict]:
    """The damage rows: matched pairs in left roster order, then the rest."""
    partner: dict[int, dict] = {}
    spare = list(right)
    for rule in _DAMAGE_RULES:
        for i, a in enumerate(left):
            if i in partner:
                continue
            b = next((b for b in spare if rule(a, b)), None)
            if b is not None:
                partner[i] = b
                spare.remove(b)
    rows = [
        {"role": DAMAGE, "left": a["name"], "right": partner[i]["name"]}
        for i, a in enumerate(left)
        if i in partner
    ]
    rows += [
        {"role": DAMAGE, "left": a["name"], "right": None}
        for i, a in enumerate(left)
        if i not in partner
    ]
    rows += [{"role": DAMAGE, "left": None, "right": b["name"]} for b in spare]
    return rows


def pair_by_role(left: list[dict], right: list[dict]) -> list[dict]:
    """Rows of {role, left, right}: tank, healer, then damage, then absent.

    The damage row is matched as closely as the classes allow: the same class
    first (a mage against a mage), then the same style (melee against melee),
    then whoever is left, in roster order. Either side may be None.
    """

    def by_role(side, role):
        return [m for m in side if m.get("party_role") == role]

    def names(side, role):
        return [m["name"] for m in by_role(side, role)]

    rows = _zip_rows(TANK, names(left, TANK), names(right, TANK))
    rows += _zip_rows(HEALER, names(left, HEALER), names(right, HEALER))
    rows += _match_damage(by_role(left, DAMAGE), by_role(right, DAMAGE))
    # A member with no role (no saved character) still gets a row: a
    # comparison that quietly drops somebody is the failure this tab is for.
    rows += _zip_rows(
        UNKNOWN_ROLE,
        [m["name"] for m in left if not m.get("party_role")],
        [m["name"] for m in right if not m.get("party_role")],
    )
    return rows


def _faction_of(members: list[dict]) -> str:
    counts: dict[str, int] = {}
    for m in members:
        if m.get("faction") in FACTION_HEADINGS:
            counts[m["faction"]] = counts.get(m["faction"], 0) + 1
    return max(counts, key=counts.get) if counts else "neutral"


def family_sides(groups: list[tuple[str, list[dict]]]) -> list[dict]:
    """The families as page columns: Alliance first (left), then Horde.

    A family is on the side its members' races put it on. Two families of
    one faction, or a realm with only one, still draw: the order is then
    the roster's.
    """
    sides = []
    for key, members in groups:
        faction = _faction_of(members)
        lead = key or (members[0]["name"] if members else "")
        guilds = [m.get("guild") for m in members if m.get("guild")]
        guild = max(set(guilds), key=guilds.count) if guilds else None
        heading = FACTION_HEADINGS.get(faction, "Family")
        heading += f" - {lead}'s family" if lead else ""
        if guild:
            heading += f", guild {guild}"
        sides.append(
            {
                "family": key,
                "faction": faction,
                "heading": heading,
                "guild": guild,
                "members": members,
            }
        )
        sides[-1]["names"] = [m["name"] for m in members]
    rank = {"alliance": 0, "horde": 1}
    sides.sort(key=lambda s: rank.get(s["faction"], 2))
    return sides


def guild_sections(
    members: list[dict], sizes: dict[str, int], sides: list[dict]
) -> list[dict]:
    """One collapsed section per guild a family member is in.

    The count is the whole guild; `others` is how many are NOT already drawn
    above as family, which is what opening the section will show. The
    members themselves are not here: a guild of seventy is fetched only
    when its section is opened (/api/armory/guild).
    """
    faction_of = {s["guild"]: s["faction"] for s in sides if s.get("guild")}
    shown: dict[str, int] = {}
    for m in members:
        if m.get("guild"):
            shown[m["guild"]] = shown.get(m["guild"], 0) + 1
    out = []
    for name in sorted(
        shown, key=lambda g: ({"alliance": 0, "horde": 1}.get(faction_of.get(g), 2), g)
    ):
        size = sizes.get(name, shown[name])
        others = max(0, size - shown[name])
        out.append(
            {
                "name": name,
                "faction": faction_of.get(name, "neutral"),
                "size": size,
                "others": others,
                "summary": f"{name} - {size} member"
                + ("" if size == 1 else "s")
                + f", {others} not shown above",
            }
        )
    return out


# What an opened guild says when every member is already drawn above.
GUILD_EMPTY_NOTE = "everyone in this guild is already drawn above."


# The collapsed guild list: one line per member, the one sentence, and the
# gear read that matters at a glance. Full profiles are fetched one at a
# time (/api/armory/member) so the default page never carries seventy.
def guild_roster(rows: list[dict], exclude=()) -> list[dict]:
    """Guild member rows -> the compact list a guild section draws.

    `rows` carry name, level, class, race, online, and the equipped count
    and average item level of what is worn. Highest level first, then name,
    so the list does not reshuffle between opens.
    """
    exclude = set(exclude)
    out = []
    for r in sorted(rows, key=lambda r: (-(r.get("level") or 0), r["name"])):
        if r["name"] in exclude:
            continue
        class_id, race = r.get("class"), r.get("race")
        line = (
            f"Level {r.get('level')} {_RACE_NAMES.get(race, f'race {race}')} "
            f"{_CLASS_NAMES.get(class_id, f'class {class_id}')}"
        )
        if r.get("worn"):
            line += (
                f" - {r['worn']} worn, item level {int(r.get('avg_item_level') or 0)}"
            )
        out.append(
            {
                "name": r["name"],
                "line": line,
                "class_colour": CLASS_COLOURS.get(class_id, "#ffffff"),
                "presence": "online" if r.get("online") else "offline",
            }
        )
    return out


# What the page says over the whole tab, and how loudly. LOUD ONLY FOR THE
# TWO THINGS SOMEBODY CAN ACT ON TODAY: a broken item is a repair and an
# unspent talent point is a click, while empty slots are ordinary at these
# levels and would leave the headline permanently coloured - which is the
# same as leaving it permanently unread. That is a verdict, so it is here.
def _headline(members: list[dict], expected: int) -> dict:
    present = [m for m in members if m["present"]]
    empty = sum(len(m["gear"]["empty_slots"]) for m in present)
    broken = sum(len(m["gear"]["broken"]) for m in present)
    idle = [m for m in present if m["spec"]["unspent"]]
    bits = [f"{len(present)} of {expected} shown"]
    if empty:
        bits.append(f"{empty} empty slot" + ("" if empty == 1 else "s"))
    if broken:
        bits.append(f"{broken} broken")
    if idle:
        bits.append(
            "unspent: " + ", ".join(f"{m['name']} {m['spec']['unspent']}" for m in idle)
        )
    return {"text": "  -  ".join(bits), "alarm": bool(broken or idle)}


# The item card sits in the flow under the doll rather than floating beside
# a cell, so it is a place on the page that exists before anything is chosen
# and has to say something then. "Nothing selected" would be a description of
# the software; this is an instruction about the page.
DETAIL_HINT = "choose a slot above to read what is in it."

# THE TREES START CLOSED. Explicitly stated rather than left to whatever the
# page happens to do, because it is a product decision and the operator's
# own: the collapsed line answers the question, and eleven tiers of icons
# per tree, three trees per character, five characters, is a scroll nobody
# asked for. The words on the control live here for the same reason every
# other word on this tab does.
TREES_EXPANDED = False
TREES_SHOW, TREES_HIDE = "show trees", "hide trees"


def _by_name(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(row["name"], []).append(row)
    return out


def _assign_roles(members: list[dict], families) -> list[tuple[str, list[dict]]]:
    """Give every member its party role, family by family; return the groups.

    A member with no family role (no bond) takes the party role as its role
    line too, so a Horde card says "tank" where an Alliance one says "father".
    """
    by_name = {m["name"]: m for m in members}
    groups = [(key, [by_name[n] for n in names]) for key, names in families]
    for _key, group in groups:
        for name, role in party_roles(group).items():
            by_name[name]["party_role"] = role
            if by_name[name]["role"] == UNKNOWN_ROLE:
                by_name[name]["role"] = role
    return groups


def build_armory(
    char_rows: list[dict],
    equipment_rows: list[dict],
    talent_rows: list[dict],
    book: TalentBook,
    items: ItemBook,
    stats_rows: list[dict] | None = None,
    base_rows: list[dict] | None = None,
    set_rows: list[dict] | None = None,
    families: list[tuple[str, list[str]]] | None = None,
    guild_sizes: dict[str, int] | None = None,
) -> dict:
    """Every member's profile, in roster order.

    The row lists arrive keyed by character name, unfiltered; splitting them
    per member is this module's job so the adapter stays a handful of
    queries and no logic. A member with no rows still gets a profile - a
    family view that quietly drops somebody is the exact failure this tab
    exists to stop.

    `families` is every family the roster knows, as (key, names) with the
    lead first; None is the one family bonds holds, which is what a caller
    with no roster table gets. `guild_sizes` counts every guild a family
    member is in, for the collapsed guild sections under the pairs.

    `stats_rows` are character_stats (may be absent for any member),
    `base_rows` the class-and-race base stats keyed by (race, class, level),
    and `set_rows` the names of every item in a set anybody is wearing.
    """
    chars = {r["name"]: r for r in char_rows}
    equipment = _by_name(equipment_rows)
    talents = _by_name(talent_rows)
    stats = {r["name"]: r for r in (stats_rows or [])}
    base = {(r["race"], r["class"], r["level"]): r for r in (base_rows or [])}
    set_names = {r["entry"]: r["item_name"] for r in (set_rows or [])}
    if families is None:
        families = [("", family.roster())]
    members = []
    for name in [n for _key, names in families for n in names]:
        char_row = chars.get(name)
        base_row = None
        if char_row is not None:
            base_row = base.get(
                (char_row["race"], char_row["class"], char_row["level"])
            )
        members.append(
            _member(
                name,
                char_row,
                equipment.get(name, []),
                talents.get(name, []),
                stats.get(name),
                base_row,
                set_names,
                book,
                items,
            )
        )
    flag_weakest(members)
    sides = family_sides(_assign_roles(members, families))
    pairs = pair_by_role(
        sides[0]["members"] if sides else [],
        sides[1]["members"] if len(sides) > 1 else [],
    )
    # The profiles travel once, in `members`; a side names its own.
    for side in sides:
        side.pop("members")
    return {
        "members": members,
        "sides": sides,
        "pairs": pairs,
        "no_counterpart": NO_COUNTERPART,
        "guilds": guild_sections(members, guild_sizes or {}, sides),
        # The slot order, sent rather than retyped in the page: the paper
        # doll's left column, right column and weapon row are all drawn from
        # this one list, so both ends must agree on what the slots are.
        "slots": [
            {"slot": name, "cosmetic": name in COSMETIC_SLOTS, "mark": slot_mark(name)}
            for name in EQUIPPED_SLOTS
        ],
        "doll": {"left": DOLL_LEFT, "right": DOLL_RIGHT},
        "expected": len(members),
        "headline": _headline(members, len(members)),
        "detail_hint": DETAIL_HINT,
        # The heading over the pieces the model host had no art for, sent
        # rather than typed into the page for the same reason every other
        # sentence here is.
        "model_gap_hint": MODEL_GAP_HINT,
        "talent_trees": {
            "expanded": TREES_EXPANDED,
            "show": TREES_SHOW,
            "hide": TREES_HIDE,
        },
    }
