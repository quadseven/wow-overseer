"""The classic ruleset: what a classic level-60 world allows, in one place.

WHAT THE OPERATOR ASKED FOR. "We're restricting our worlds to classic level 60
feeling. So profession level 300 max." The realm runs a Wrath client and Wrath
data, so every planner that picks a trainer, a recipe, a bag, an auction
purchase, a vendor item or a destination can reach Outland and Northrend
unless it is told not to. Measured on the dev world on 2026-09-23: a crafting
corps planned Master Tailoring and Netherweave Bags from Outland trainers, a
guild dues walk aimed a guild member at a mailbox on map 530, 410 random bots
stood on map 530, and 676 characters carried a 375 skill cap.

THE RULES.

- Level: at most 60.
- Professions: at most skill 300 (Artisan). No Master or Grand Master rank,
  and no recipe that needs more than 300.
- Maps: Eastern Kingdoms (0), Kalimdor (1) and the classic instances. Never
  Outland (530) or Northrend (571). The Blood Elf and Draenei starting lands
  are physically on map 530 and are outside too: the rule names the map.
- Items: item level at most 92 and required level at most 60, and not one of
  the items below whose only source is Outland or Northrend. Wrath data gives
  an item no expansion column, and several Outland and Northrend items (the
  Netherweave Bag is item level 63 with no required level) pass the two
  numbers, so those are named.

MIRRORED IN THE MODULE. mod-overseer keeps the same numbers in
`OverseerDecisions::Classic` (src/overseer_decisions.h), because it is the half
that walks a character and buys a rank. tests/test_classic.py reads that block
from the pinned module and fails when the two disagree; it engages once the
pin reaches the module commit that added the block. Change both together.

PURE MODULE: numbers and questions, no MySQL, no clock.
"""

from __future__ import annotations

MAX_LEVEL = 60
MAX_PROFESSION_SKILL = 300

OUTLAND_MAP = 530
NORTHREND_MAP = 571
EXPANSION_MAPS = frozenset({OUTLAND_MAP, NORTHREND_MAP})

CLASSIC_CONTINENTS = (0, 1)

# The classic instances: the dungeons and raids of dungeonpath.PATH, the
# Deeprun Tram, and the classic battlegrounds. Onyxia's Lair (249) and
# Naxxramas (533) are absent on purpose: on this realm both were rebuilt for
# level 80, and Naxxramas's door is in Northrend.
CLASSIC_DUNGEON_MAPS = frozenset(
    {
        33,  # Shadowfang Keep
        34,  # The Stockade
        36,  # The Deadmines
        43,  # Wailing Caverns
        47,  # Razorfen Kraul
        48,  # Blackfathom Deeps
        70,  # Uldaman
        90,  # Gnomeregan
        109,  # Sunken Temple
        129,  # Razorfen Downs
        189,  # Scarlet Monastery
        209,  # Zul'Farrak
        229,  # Blackrock Spire
        230,  # Blackrock Depths
        289,  # Scholomance
        329,  # Stratholme
        349,  # Maraudon
        389,  # Ragefire Chasm
        429,  # Dire Maul
    }
)
CLASSIC_RAID_MAPS = frozenset(
    {
        309,  # Zul'Gurub
        409,  # Molten Core
        469,  # Blackwing Lair
        509,  # Ruins of Ahn'Qiraj
        531,  # Temple of Ahn'Qiraj
    }
)
CLASSIC_OTHER_INSTANCE_MAPS = frozenset(
    {
        30,  # Alterac Valley
        369,  # Deeprun Tram
        489,  # Warsong Gulch
        529,  # Arathi Basin
    }
)
CLASSIC_INSTANCE_MAPS = (
    CLASSIC_DUNGEON_MAPS | CLASSIC_RAID_MAPS | CLASSIC_OTHER_INSTANCE_MAPS
)
CLASSIC_MAPS = frozenset(CLASSIC_CONTINENTS) | CLASSIC_INSTANCE_MAPS

# The instances that came with Outland and Northrend, or were rebuilt for
# level 80. Every map in entrances.json whose door is on 530 or 571, the
# Caverns of Time and Karazhan doors that stand on classic ground (269, 532,
# 534, 560, 595), Onyxia's Lair as rebuilt (249), Ebon Hold (609), and the
# later battlegrounds and arenas. A planner that meets an instance in neither
# list (a test map, a custom one) leaves it alone: this is the list it refuses.
EXPANSION_INSTANCE_MAPS = frozenset(
    {
        249,
        269,
        532,
        533,
        534,
        540,
        542,
        543,
        544,
        545,
        546,
        547,
        548,
        550,
        552,
        553,
        554,
        555,
        556,
        557,
        558,
        559,
        560,
        562,
        564,
        565,
        566,
        568,
        572,
        574,
        575,
        576,
        578,
        580,
        585,
        595,
        599,
        600,
        601,
        602,
        603,
        604,
        607,
        608,
        609,
        615,
        616,
        617,
        618,
        619,
        624,
        628,
        631,
        632,
        649,
        650,
        658,
        668,
        724,
    }
)

# The highest item level a classic item carries: the level-60 raid tier.
MAX_ITEM_LEVEL = 92
MAX_REQUIRED_LEVEL = MAX_LEVEL

# Items whose only source is Outland, Northrend, or a Blood Elf, Draenei or
# Death Knight start, and which the two numbers above let through. Read off
# this realm's item_template on 2026-09-23: every bag (class 1, subclass 0) and
# the tailoring cloth and bolts the planners know.
EXPANSION_ONLY_ITEMS = frozenset(
    {
        # Cloth and bolts.
        21877,  # Netherweave Cloth
        21840,  # Bolt of Netherweave
        21842,  # Bolt of Imbued Netherweave
        21845,  # Primal Mooncloth
        21881,  # Netherweb Spider Silk
        24271,  # Spellcloth
        24272,  # Shadowcloth
        33470,  # Frostweave Cloth
        41510,  # Bolt of Frostweave
        41511,  # Bolt of Imbued Frostweave
        42253,  # Iceweb Spider Silk
        # Bags.
        20474,  # Sunstrider Book Satchel
        21841,  # Netherweave Bag
        21843,  # Imbued Netherweave Bag
        21876,  # Primal Mooncloth Bag
        22571,  # Courier's Bag
        22976,  # Magister's Pouch
        23389,  # Empty Draenei Supply Pouch
        23852,  # Nolkai's Bag
        27680,  # Halaani Bag
        30744,  # Draenic Leather Pack
        33117,  # Jack-o'-Lantern
        34067,  # Tattered Hexcloth Sack
        34845,  # Pit Lord's Satchel
        35516,  # Sun Touched Satchel
        37606,  # Penny Pouch
        38082,  # "Gigantique" Bag
        38145,  # Deathweave Bag
        41599,  # Frostweave Bag
        41600,  # Glacial Bag
        43345,  # Dragon Hide Bag
        49295,  # Enlarged Onyxia Hide Backpack
        50316,  # Papa's Brand New Bag
        50317,  # Papa's New Bag
        51809,  # Portable Hole
    }
)


def is_expansion_map(map_id) -> bool:
    """Outland or Northrend. An unknown map (None) is not judged here."""
    return map_id is not None and int(map_id) in EXPANSION_MAPS


def is_classic_map(map_id) -> bool:
    """Eastern Kingdoms, Kalimdor or a classic instance."""
    return map_id is not None and int(map_id) in CLASSIC_MAPS


def outside_classic(map_id) -> bool:
    """Outland, Northrend, or an instance that came with them.

    The question a door list or a destination asks. An unknown map is not
    judged: it is neither named classic nor named outside.
    """
    return map_id is not None and (
        int(map_id) in EXPANSION_MAPS or int(map_id) in EXPANSION_INSTANCE_MAPS
    )


def level_ok(level) -> bool:
    return int(level or 0) <= MAX_LEVEL


def skill_ok(skill) -> bool:
    """A skill value, a recipe's required rank, or a rank's ceiling, at most 300."""
    return int(skill or 0) <= MAX_PROFESSION_SKILL


def item_ok(entry, item_level=0, required_level=0) -> bool:
    """May a planner pick this item: buy it, craft it, route it, or aim at it?

    `item_level` and `required_level` default to 0 for a caller that has only
    the entry; the named list still applies.
    """
    return (
        int(entry or 0) not in EXPANSION_ONLY_ITEMS
        and int(item_level or 0) <= MAX_ITEM_LEVEL
        and int(required_level or 0) <= MAX_REQUIRED_LEVEL
    )


def outside_note(who, map_id) -> str:
    """The sentence a planner writes when it leaves somebody out for the map."""
    return "%s stands in %s, outside the classic world" % (
        who,
        "Outland" if int(map_id) == OUTLAND_MAP else "Northrend",
    )
