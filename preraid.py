"""The pre-raid plan: what each family member should wear into Molten Core,
where it drops, and which dungeon gives the family the most of it.

WHY THIS EXISTS. A family at level 60 wears item level 39 to 45 against the
raiders' 67, and the campaign planner (campaignplan.py) chose its next dungeon
by how much of a round it had run, as if every level 60 dungeon gave the same
thing. A raid guild does not farm that way. It reads its loot tables, names
the pieces each member is missing, and runs the dungeon where the most of them
drop, picking up the attunement and the key on the way. This module is that
reading, from the world's own loot tables and each member's own gear.

WHAT IT READS. Everything that drops on the level 60 dungeon maps, and on
the lower ones whose rares still upgrade a fresh level 60 (LOWER_MAPS)
(creature_loot_template and gameobject_loot_template, one reference level
deep through reference_loot_template), the rewards of the quests those
dungeons hold (quest_template), each drop's stats (item_template, with equip
spells read off the committed spells.json), what each member wears, and the
attunement and key items and quests.

HOW A PIECE IS JUDGED. By a spec's stat weights (ROLES), not by item level
alone: a level 63 cloth robe of spell power is nothing to a protection
warrior. The weights are rough, labelled as such on the page, and in one
table so they can be argued with. An UPGRADE is a piece the member can wear
(armour type, weapon skill, class mask, level) whose score beats what is worn
in that slot. The item level difference is what the page and Jev are told,
because it is the number a reader already knows.

HOW LIKELY A DROP IS. Per run, from the loot rows: an ungrouped row's own
chance; a grouped row's chance, or its share of what the group's explicit
chances leave; a reference's items the same way inside the reference, times
the reference row's chance and roll count. A drop under MIN_CHANCE per run is
a world drop that happens to be possible there, and is left out.

WHERE. Each source is placed at a campaign run keyword (the door the planner
would send the family through) or at UPPER_SPIRE, which has no door. A map
with several wings (Blackrock Spire, Dire Maul, Stratholme) places a creature
or chest at the wing of the nearest named boss in WING_BOSSES.

PURE MODULE: no MySQL, no clock. Rows in, plans and sentences out. The
statements the bridge and the site run are written here.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import bag_pressure
import campaignplan
import council

# --- the places ----------------------------------------------------------------

# The level 60 dungeons, and only the classic ones.
SUNKEN_TEMPLE, SPIRE, DEPTHS, SCHOLOMANCE, STRATHOLME, DIRE_MAUL = (
    109,
    229,
    230,
    289,
    329,
    429,
)

# THE LOWER DUNGEONS A LEVEL 60 FAMILY STILL GEARS IN. A family that reaches
# 60 wears item level 39 to 45, and the rares of these five drop at 40 to 50.
# Measured on the dev realm on 2026-09-24: one Zul'Farrak visit by the level
# 60 Alliance family handed nine pieces to members they upgraded. Below
# these, a rare is under what a fresh 60 wears and the read would only add
# rows that never upgrade anyone.
SCARLET, RAZORFEN_DOWNS, ULDAMAN, ZULFARRAK, MARAUDON = 189, 129, 70, 209, 349
LOWER_MAPS = (SCARLET, RAZORFEN_DOWNS, ULDAMAN, ZULFARRAK, MARAUDON)

MAPS = (SUNKEN_TEMPLE, SPIRE, DEPTHS, SCHOLOMANCE, STRATHOLME, DIRE_MAUL) + LOWER_MAPS

# The Upper Spire shares map 229 with the Lower Spire and has no door of its
# own in mod-overseer (the Dragonspine Door inside opens for the Seal of
# Ascension), so it is a place the plan names and the planner cannot choose.
UPPER_SPIRE = "upper-blackrock-spire"

# Inner Maraudon, past Celebras, is reached through either the orange or the
# purple wing, so what drops there is credited to both runs (SHARED_PLACES).
MARAUDON_INNER = "maraudon-inner"
SHARED_PLACES = {MARAUDON_INNER: ("maraudon-orange", "maraudon-purple")}

# The place a single-wing map's drops belong to.
MAP_PLACE = {
    SUNKEN_TEMPLE: "sunken-temple",
    DEPTHS: "blackrock-depths",
    SCHOLOMANCE: "scholomance",
    RAZORFEN_DOWNS: "razorfen-downs",
    ULDAMAN: "uldaman",
    ZULFARRAK: "zulfarrak",
}

# THE WINGS, BY THEIR BOSSES (creature_template entries, read on the dev realm
# 2026-09-23). A creature or chest on one of these maps belongs to the wing of
# the nearest boss listed here that is spawned on the map.
WING_BOSSES = {
    SPIRE: {
        "lower-blackrock-spire": (9196, 9236, 9237, 10596, 9736, 10220, 9568),
        UPPER_SPIRE: (9816, 10429, 10430, 10363, 10339, 10264, 10509, 10899),
    },
    DIRE_MAUL: {
        "dire-maul-east-east": (11492, 13280, 14327, 11490, 14354, 11491),
        "dire-maul-west-north": (11489, 11488, 11487, 11496, 11486, 11467),
        "dire-maul-north": (14326, 14322, 14321, 14323, 14325, 14324, 11501),
    },
    STRATHOLME: {
        "stratholme-live": (10808, 10997, 10811, 11032, 10558, 10516, 10393, 11143),
        "stratholme-undead": (10435, 10437, 10436, 10438, 10440),
    },
    # Read on the dev realm 2026-09-24 off instance_encounters: each wing is
    # its own instance on map 189, far apart, so the nearest boss places a
    # drop in the wing it fell in.
    SCARLET: {
        "scarlet": (3983, 4543),
        "scarlet-library": (3974, 6487),
        "scarlet-armory": (3975,),
        "scarlet-cathedral": (4542, 3977, 3976),
    },
    MARAUDON: {
        "maraudon-orange": (13282, 12258),
        "maraudon-purple": (12236,),
        MARAUDON_INNER: (12225, 12203, 13601, 13596, 12201),
    },
}

# The quest zones (quest_template.QuestSortID) whose rewards count. A quest
# names its dungeon and not its wing, so its rewards are credited to the
# dungeon as a whole: a place of their own, with the runs that go there. A
# quest reward is reachable when any of those runs is.
QUEST_ZONES = {
    1417: ("sunken-temple-quests", "the Sunken Temple", ("sunken-temple",)),
    1583: (
        "blackrock-spire-quests",
        "Blackrock Spire",
        ("lower-blackrock-spire", UPPER_SPIRE),
    ),
    1584: ("blackrock-depths-quests", "Blackrock Depths", ("blackrock-depths",)),
    2057: ("scholomance-quests", "Scholomance", ("scholomance",)),
    2017: (
        "stratholme-quests",
        "Stratholme",
        ("stratholme-live", "stratholme-undead"),
    ),
    2557: (
        "dire-maul-quests",
        "Dire Maul",
        ("dire-maul-east-east", "dire-maul-west-north", "dire-maul-north"),
    ),
}
QUEST_PLACES = {key: (label, runs) for key, label, runs in QUEST_ZONES.values()}

# Every place a drop is credited to: a run's door, or the Upper Spire.
PLACES = tuple(
    sorted(
        set(MAP_PLACE.values()) | {p for wings in WING_BOSSES.values() for p in wings}
    )
)

# Why a place with no run cannot be chosen, in a reader's words.
CLOSED = {
    UPPER_SPIRE: (
        "it starts behind the Dragonspine Door, which opens for the Seal of "
        "Ascension, and the overseer has no door row for it"
    ),
}


def place_name(place: str) -> str:
    if place == UPPER_SPIRE:
        return "Upper Blackrock Spire"
    if place == MARAUDON_INNER:
        return "inner Maraudon"
    if place in QUEST_PLACES:
        return QUEST_PLACES[place][0]
    return council.keyword_place(place)


LEVEL_CAP = 60

# A drop rarer than this per run is a world drop that happens to be possible
# there, not a reason to go.
MIN_CHANCE = 1.0

DROP, CHEST, QUEST = "drop", "chest", "quest"

# --- the reads -----------------------------------------------------------------
#
# S608 on the statements below: the only interpolated parts are this module's
# own integer constants, passed through int(); every value from outside is
# bound. `{holes}` is a run of placeholders sized by the caller.

_MAPS_SQL = ", ".join(str(int(m)) for m in MAPS)
_ZONES_SQL = ", ".join(str(int(z)) for z in sorted(QUEST_ZONES))

_GEAR_FILTER = (
    "it.class IN (2, 4) AND it.Quality >= 3 AND it.RequiredLevel <= 60 "
    "AND it.InventoryType <> 0"
)

# Every creature spawned on the maps, with where it stands on average.
_CREATURES = (
    "SELECT c.id AS entry, c.map AS map_id, ct.name, ct.lootid, "  # noqa: S608
    "AVG(c.position_x) AS x, AVG(c.position_y) AS y, AVG(c.position_z) AS z "
    "FROM acore_world.creature c "
    "JOIN acore_world.creature_template ct ON ct.entry = c.id "
    "WHERE c.map IN (" + _MAPS_SQL + ") "
    "GROUP BY c.id, c.map, ct.name, ct.lootid"
)

# The same for loot chests (gameobject type 3, loot id in data1).
_CHESTS = (
    "SELECT g.id AS entry, g.map AS map_id, gt.name, gt.data1 AS lootid, "  # noqa: S608
    "AVG(g.position_x) AS x, AVG(g.position_y) AS y, AVG(g.position_z) AS z "
    "FROM acore_world.gameobject g "
    "JOIN acore_world.gameobject_template gt ON gt.entry = g.id AND gt.type = 3 "
    "WHERE g.map IN (" + _MAPS_SQL + ") AND gt.data1 <> 0 "
    "GROUP BY g.id, g.map, gt.name, gt.data1"
)


def _drops_sql(spawns: str, table: str, kind: str) -> str:
    """One loot table's gear rows for `spawns`, direct and one reference deep,
    each with its group's zero-chance count and explicit chance sum."""
    groups = (
        "(SELECT Entry, GroupId, SUM(Chance = 0) AS zero, SUM(Chance) AS explicit "
        "FROM acore_world.{t} WHERE Reference = 0 GROUP BY Entry, GroupId)"
    )
    return (
        "SELECT '"
        + kind
        + "' AS kind, s.entry AS source, s.map_id, s.name, s.x, s.y, s.z, "
        "l.Item AS item, l.Chance AS chance, l.GroupId AS grp, 1 AS rolls, "
        "100 AS outer_chance, g.zero AS group_zero, g.explicit AS group_explicit "
        "FROM (" + spawns + ") s "
        "JOIN acore_world." + table + " l ON l.Entry = s.lootid "
        "AND l.Reference = 0 AND l.QuestRequired = 0 "
        "JOIN " + groups.format(t=table) + " g "
        "ON g.Entry = l.Entry AND g.GroupId = l.GroupId "
        "JOIN acore_world.item_template it ON it.entry = l.Item "
        "WHERE " + _GEAR_FILTER + " "
        "UNION ALL "
        "SELECT '" + kind + "', s.entry, s.map_id, s.name, s.x, s.y, s.z, "
        "r.Item, r.Chance, r.GroupId, p.MaxCount, p.Chance, g.zero, g.explicit "
        "FROM (" + spawns + ") s "
        "JOIN acore_world." + table + " p ON p.Entry = s.lootid "
        "AND p.Reference <> 0 "
        "JOIN acore_world.reference_loot_template r ON r.Entry = p.Reference "
        "AND r.Reference = 0 AND r.QuestRequired = 0 "
        "JOIN " + groups.format(t="reference_loot_template") + " g "
        "ON g.Entry = r.Entry AND g.GroupId = r.GroupId "
        "JOIN acore_world.item_template it ON it.entry = r.Item "
        "WHERE " + _GEAR_FILTER
    )


DROPS_SQL = (
    _drops_sql(_CREATURES, "creature_loot_template", DROP)
    + " UNION ALL "
    + _drops_sql(_CHESTS, "gameobject_loot_template", CHEST)
)

# Where the wing bosses stand, so every other source can be placed by them.
_WING_ENTRIES = ", ".join(
    str(int(e)) for wings in WING_BOSSES.values() for es in wings.values() for e in es
)
ANCHORS_SQL = (
    "SELECT c.id AS entry, c.map AS map_id, AVG(c.position_x) AS x, "  # noqa: S608
    "AVG(c.position_y) AS y, AVG(c.position_z) AS z "
    "FROM acore_world.creature c WHERE c.id IN (" + _WING_ENTRIES + ") "
    "GROUP BY c.id, c.map"
)

REWARDS_SQL = (
    "SELECT q.ID AS quest, q.LogTitle AS title, q.QuestSortID AS zone, "  # noqa: S608
    "q.AllowableRaces AS races, a.AllowableClasses AS classes, "
    "q.RewardItem1, q.RewardItem2, q.RewardItem3, q.RewardItem4, "
    "q.RewardChoiceItemID1, q.RewardChoiceItemID2, q.RewardChoiceItemID3, "
    "q.RewardChoiceItemID4, q.RewardChoiceItemID5, q.RewardChoiceItemID6 "
    "FROM acore_world.quest_template q "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = q.ID "
    "WHERE q.QuestSortID IN (" + _ZONES_SQL + ") AND q.MinLevel <= 60 "
    "AND q.LogTitle NOT LIKE '<%%'"
)
REWARD_COLUMNS = tuple("RewardItem%d" % i for i in range(1, 5)) + tuple(
    "RewardChoiceItemID%d" % i for i in range(1, 7)
)

_ITEM_COLUMNS = (
    "it.entry, it.name, it.ItemLevel AS item_level, it.Quality AS quality, "
    "it.InventoryType AS inventory_type, it.class AS item_class, "
    "it.subclass, it.AllowableClass AS allowable_class, "
    "it.RequiredLevel AS required_level, it.armor, it.block, "
    + ", ".join("it.stat_type%d, it.stat_value%d" % (i, i) for i in range(1, 11))
    + ", it.dmg_min1, it.dmg_max1, it.delay, "
    + ", ".join("it.spellid_%d, it.spelltrigger_%d" % (i, i) for i in range(1, 6))
)

ITEMS_SQL = (
    "SELECT " + _ITEM_COLUMNS + " FROM acore_world.item_template it "  # noqa: S608
    "WHERE it.entry IN ({holes})"
)

# What each member wears, paper-doll slots 0 to 18, with the same columns.
WORN_SQL = (
    "SELECT c.name AS member, ci.slot, " + _ITEM_COLUMNS + " "  # noqa: S608
    "FROM characters c JOIN character_inventory ci ON ci.guid = c.guid "
    "AND ci.bag = 0 AND ci.slot < 19 "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN ({holes})"
)

# Each member's class, level and talent tree, which say which weights apply.
MEMBERS_SQL = (
    "SELECT c.name, c.class AS class_id, c.level, c.race, c.map AS map_id, "
    "r.lead, r.spec_tab "
    "FROM characters c JOIN overseer_roster r ON r.name = c.name "
    "WHERE c.name IN ({holes})"
)

# --- the attunement and the key ------------------------------------------------

ATTUNEMENT_QUESTS = (7487, 7848)  # raidready.ATTUNEMENT_QUESTS
CORE_FRAGMENT = 18412
LOTHOS = 14387

KEY_QUESTS = (4742, 4743)  # Vaelan's two "Seal of Ascension" quests
SEAL_OF_ASCENSION = 12344  # the key itself
# The four pieces 4742 asks for, and where each comes from (quest_template
# RequiredItemId1-4; creature_loot_template, all at QuestRequired 0).
KEY_PIECES = {
    12336: "the Gemstone of Spirestone (Highlord Omokk)",
    12335: "the Gemstone of Smolderthorn (War Master Voone)",
    12337: "the Gemstone of Bloodaxe (Overlord Wyrmthalak)",
    12219: "an Unadorned Seal of Ascension (the Lower Spire's orcs)",
}

_QUEST_IDS = ", ".join(str(int(q)) for q in ATTUNEMENT_QUESTS + KEY_QUESTS)
# The door keys (campaignplan.DOOR_KEYS) ride on the same read, so the Raid
# tab knows which Dire Maul and Scarlet doors the family can open.
_ITEM_IDS = ", ".join(
    str(int(i))
    for i in (
        CORE_FRAGMENT,
        SEAL_OF_ASCENSION,
        *sorted(KEY_PIECES),
        *campaignplan.KEY_ITEMS,
    )
)

PROGRESS_REWARDED_SQL = (
    "SELECT c.name, r.quest FROM character_queststatus_rewarded r "  # noqa: S608
    "JOIN characters c ON c.guid = r.guid "
    "WHERE c.name IN ({holes}) AND r.quest IN (" + _QUEST_IDS + ")"
)
PROGRESS_LOG_SQL = (
    "SELECT c.name, q.quest, q.status FROM character_queststatus q "  # noqa: S608
    "JOIN characters c ON c.guid = q.guid "
    "WHERE c.name IN ({holes}) AND q.quest IN (" + _QUEST_IDS + ")"
)
PROGRESS_ITEMS_SQL = (
    "SELECT c.name, ii.itemEntry AS entry, SUM(ii.count) AS count "  # noqa: S608
    "FROM character_inventory ci JOIN characters c ON c.guid = ci.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "WHERE c.name IN ({holes}) AND ii.itemEntry IN (" + _ITEM_IDS + ") "
    "GROUP BY c.name, ii.itemEntry"
)

# character_queststatus: 1 complete, 3 incomplete; both are in the log.
IN_LOG = frozenset({1, 3})


def holes(count: int) -> str:
    return ", ".join(["%s"] * max(int(count), 1))


# --- the items -----------------------------------------------------------------

# item_template stat types (3.3.5a), by the name the weights use.
STAT_NAMES = {
    3: "agi",
    4: "str",
    5: "int",
    6: "spi",
    7: "sta",
    12: "def",
    13: "dodge",
    14: "parry",
    15: "block",
    16: "hit",
    17: "hit",
    18: "hit",
    19: "crit",
    20: "crit",
    21: "crit",
    31: "hit",
    32: "crit",
    36: "haste",
    37: "expertise",
    38: "ap",
    39: "rap",
    41: "sp",
    42: "sp",
    43: "mp5",
    44: "arp",
    45: "sp",
    48: "block_value",
}

# Equip spells, read off their text in spells.json (tools/gen_items.py). The
# pinned world writes most classic bonuses as an equip spell rather than a
# stat row (Lionheart Helm's +2% crit and +2% hit are spells 7598 and 15465).
_SPELL_STATS = (
    (re.compile(r"Increases your spell critical strike rating by (\d+)"), "crit"),
    (re.compile(r"Increases your spell hit rating by (\d+)"), "hit"),
    (re.compile(r"Increases your critical strike rating by (\d+)"), "crit"),
    (re.compile(r"Increases your hit rating by (\d+)"), "hit"),
    (re.compile(r"Increases your haste rating by (\d+)"), "haste"),
    (re.compile(r"Increases your expertise rating by (\d+)"), "expertise"),
    (re.compile(r"Increases ranged attack power by (\d+)"), "rap"),
    (re.compile(r"Increases attack power by (\d+)"), "ap"),
    (re.compile(r"Increases spell power by (\d+)"), "sp"),
    (
        re.compile(
            r"Increases (arcane|fire|frost|holy|nature|shadow) spell power by (\d+)"
        ),
        None,
    ),
    (re.compile(r"Increases defense rating by (\d+)"), "def"),
    (re.compile(r"Increases your dodge rating by (\d+)"), "dodge"),
    (re.compile(r"Increases your parry rating by (\d+)"), "parry"),
    (re.compile(r"Increases your (?:shield )?block rating by (\d+)"), "block"),
    (re.compile(r"Increases the block value of your shield by (\d+)"), "block_value"),
    (re.compile(r"Restores (\d+) mana per 5 sec"), "mp5"),
    (re.compile(r"Increases armor penetration rating by (\d+)"), "arp"),
)

SPELL_ON_EQUIP = 1  # item_template.spelltrigger


@functools.lru_cache(maxsize=1)
def spell_text() -> dict:
    """spells.json, the committed equip spell text: id -> sentence."""
    path = Path(__file__).resolve().parent / "spells.json"
    try:
        with open(path) as f:
            return {int(k): str(v or "") for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def spell_stats(spell_id: int, texts: dict | None = None) -> dict:
    """The stats one equip spell gives, off its text. {} when unknown."""
    text = (spell_text() if texts is None else texts).get(int(spell_id), "")
    for pattern, stat in _SPELL_STATS:
        found = pattern.search(text)
        if not found:
            continue
        if stat is None:
            return {"sp_" + found.group(1): int(found.group(2))}
        return {stat: int(found.group(1))}
    return {}


@dataclass(frozen=True)
class Source:
    """One place a piece comes from, and how often per run (percent)."""

    place: str
    boss: str
    kind: str
    chance: float
    races: int = 0  # a quest reward's race mask, 0 for anybody
    classes: int = 0  # and its class mask

    def allows(self, race: int, class_id: int) -> bool:
        race_bit = 1 << (int(race) - 1) if int(race) > 0 else 0
        class_bit = 1 << (int(class_id) - 1) if int(class_id) > 0 else 0
        return (not self.races or bool(self.races & race_bit)) and (
            not self.classes or bool(self.classes & class_bit)
        )

    @property
    def said(self) -> str:
        if self.kind == QUEST:
            return "%s, quest reward (%s)" % (place_name(self.place), self.boss)
        return "%s, %s, %s" % (place_name(self.place), self.boss, _pct(self.chance))


def _pct(chance: float) -> str:
    return "%d%%" % round(chance) if chance >= 10 else "%.1f%%" % chance


@dataclass(frozen=True)
class Item:
    entry: int
    name: str
    item_level: int
    quality: int
    inventory_type: int
    item_class: int
    subclass: int
    allowable_class: int
    required_level: int
    stats: tuple  # ((stat name, value), ...)
    armor: int = 0
    dps: float = 0.0
    sources: tuple = ()


def item(row: dict, texts: dict | None = None) -> Item:
    """An Item from one row with _ITEM_COLUMNS."""
    stats: dict = {}
    for i in range(1, 11):
        kind = int(row.get("stat_type%d" % i) or 0)
        value = int(row.get("stat_value%d" % i) or 0)
        if kind in STAT_NAMES and value:
            name = STAT_NAMES[kind]
            stats[name] = stats.get(name, 0) + value
    for i in range(1, 6):
        spell = int(row.get("spellid_%d" % i) or 0)
        if spell and int(row.get("spelltrigger_%d" % i) or 0) == SPELL_ON_EQUIP:
            for name, value in spell_stats(spell, texts).items():
                stats[name] = stats.get(name, 0) + value
    if int(row.get("block") or 0):
        stats["block_value"] = stats.get("block_value", 0) + int(row["block"])
    delay = int(row.get("delay") or 0)
    low, high = float(row.get("dmg_min1") or 0), float(row.get("dmg_max1") or 0)
    dps = round((low + high) / 2 / (delay / 1000.0), 1) if delay and high else 0.0
    return Item(
        entry=int(row["entry"]),
        name=str(row.get("name") or ""),
        item_level=int(row.get("item_level") or 0),
        quality=int(row.get("quality") or 0),
        inventory_type=int(row.get("inventory_type") or 0),
        item_class=int(row.get("item_class") or 0),
        subclass=int(row.get("subclass") or 0),
        allowable_class=int(row.get("allowable_class") or -1),
        required_level=int(row.get("required_level") or 0),
        stats=tuple(sorted(stats.items())),
        armor=int(row.get("armor") or 0),
        dps=dps,
    )


# --- where things drop -----------------------------------------------------------


def chance(row: dict) -> float:
    """Percent per run that one loot row drops its item. See the docstring."""
    own = float(row.get("chance") or 0)
    if int(row.get("grp") or 0):
        zero = int(row.get("group_zero") or 0)
        explicit = float(row.get("group_explicit") or 0)
        if own <= 0:
            own = max(100.0 - explicit, 0.0) / zero if zero else 0.0
    outer = float(row.get("outer_chance") or 0) / 100.0
    rolls = max(int(row.get("rolls") or 1), 1)
    return min(own * outer * rolls, 100.0)


def _near(anchors: list, x: float, y: float, z: float) -> str:
    best = min(
        anchors,
        key=lambda a: (a[1] - x) ** 2 + (a[2] - y) ** 2 + (a[3] - z) ** 2,
        default=None,
    )
    return best[0] if best else ""


def placer(anchor_rows: list):
    """A function (map id, entry, x, y, z) -> place, from where the wing
    bosses stand. "" for a source on no known place."""
    anchors: dict = {}
    wing_of = {
        (m, e): p
        for m, wings in WING_BOSSES.items()
        for p, es in wings.items()
        for e in es
    }
    for row in anchor_rows or []:
        key = (int(row["map_id"]), int(row["entry"]))
        if key in wing_of:
            anchors.setdefault(key[0], []).append(
                (wing_of[key], float(row["x"]), float(row["y"]), float(row["z"]))
            )

    def place(map_id: int, entry: int, x: float, y: float, z: float) -> str:
        map_id = int(map_id)
        if map_id in MAP_PLACE:
            return MAP_PLACE[map_id]
        if (map_id, int(entry)) in wing_of:
            return wing_of[(map_id, int(entry))]
        return _near(anchors.get(map_id, []), float(x), float(y), float(z))

    return place


def sources(drop_rows: list, anchor_rows: list, reward_rows: list) -> dict:
    """item entry -> its Sources, strongest first. Drops under MIN_CHANCE are
    left out; the same boss dropping the same item by two rows adds up."""
    place = placer(anchor_rows)
    found: dict = {}
    for row in drop_rows or []:
        where = place(
            row["map_id"],
            row["source"],
            row.get("x") or 0,
            row.get("y") or 0,
            row.get("z") or 0,
        )
        if not where:
            continue
        key = (
            int(row["item"]),
            where,
            str(row.get("name") or ""),
            str(row["kind"]),
            0,
            0,
        )
        found[key] = found.get(key, 0.0) + chance(row)
    for row in reward_rows or []:
        zone = QUEST_ZONES.get(int(row.get("zone") or 0))
        if not zone:
            continue
        where = zone[0]
        for column in REWARD_COLUMNS:
            entry = int(row.get(column) or 0)
            if entry:
                key = (
                    entry,
                    where,
                    str(row.get("title") or ""),
                    QUEST,
                    int(row.get("races") or 0),
                    int(row.get("classes") or 0),
                )
                found[key] = 100.0
    out: dict = {}
    for (entry, where, boss, kind, races, classes), pct in found.items():
        if pct >= MIN_CHANCE:
            out.setdefault(entry, []).append(
                Source(where, boss, kind, round(min(pct, 100.0), 1), races, classes)
            )
    return {
        k: tuple(sorted(v, key=lambda s: (-s.chance, s.place, s.boss)))
        for k, v in out.items()
    }


def catalog(
    drop_rows: list, anchor_rows: list, reward_rows: list, item_rows: list, texts=None
) -> dict:
    """entry -> Item with its sources: every wearable piece that drops or is
    rewarded in the level 60 dungeons."""
    where = sources(drop_rows, anchor_rows, reward_rows)
    out = {}
    for row in item_rows or []:
        entry = int(row["entry"])
        if entry not in where:
            continue
        piece = item(row, texts)
        if piece.item_class not in (2, 4):
            continue
        out[entry] = replace(piece, sources=where[entry])
    return out


def catalog_entries(drop_rows: list, reward_rows: list) -> list:
    """Every item entry the item read must answer for, sorted."""
    entries = {int(r["item"]) for r in drop_rows or []}
    for row in reward_rows or []:
        entries |= {int(row.get(c) or 0) for c in REWARD_COLUMNS}
    entries.discard(0)
    return sorted(entries)


# --- the specs -------------------------------------------------------------------

TANK, STRENGTH, AGILITY, CASTER, HEALER, HUNTER = (
    "tank",
    "strength",
    "agility",
    "caster",
    "healer",
    "hunter",
)

# ROUGH WEIGHTS, per point, per role: what one point of each stat is worth
# against one point of the role's main stat. Ratings are the pinned world's
# numbers at level 60 (about 10 hit rating and 14 crit rating to the percent).
# `weapon` is the worth of one point of main hand damage per second, `off` of
# the off hand's. They rank pieces; they are not a simulation.
ROLES = {
    TANK: {
        "sta": 1.0,
        "def": 1.5,
        "dodge": 1.0,
        "parry": 0.9,
        "block": 0.5,
        "block_value": 0.3,
        "agi": 0.7,
        "str": 0.5,
        "hit": 0.5,
        "expertise": 0.5,
        "ap": 0.2,
        "crit": 0.2,
        "armor": 0.05,
        "weapon": 1.5,
        "off": 0.0,
    },
    STRENGTH: {
        "str": 1.0,
        "agi": 0.6,
        "ap": 0.45,
        "crit": 0.9,
        "hit": 1.2,
        "expertise": 0.8,
        "haste": 0.5,
        "arp": 0.3,
        "sta": 0.3,
        "int": 0.1,
        "armor": 0.005,
        "weapon": 3.5,
        "off": 1.5,
    },
    AGILITY: {
        "agi": 1.0,
        "str": 0.5,
        "ap": 0.5,
        "hit": 1.5,
        "crit": 1.0,
        "haste": 0.8,
        "expertise": 1.0,
        "arp": 0.4,
        "sta": 0.2,
        "armor": 0.005,
        "weapon": 3.0,
        "off": 1.5,
    },
    CASTER: {
        "sp": 1.0,
        "int": 0.4,
        "spi": 0.1,
        "crit": 0.5,
        "hit": 0.9,
        "haste": 0.6,
        "mp5": 0.3,
        "sta": 0.1,
    },
    HEALER: {
        "sp": 1.0,
        "int": 0.6,
        "spi": 0.6,
        "mp5": 1.2,
        "crit": 0.4,
        "haste": 0.5,
        "sta": 0.1,
    },
    HUNTER: {
        "agi": 1.0,
        "rap": 0.5,
        "ap": 0.4,
        "hit": 1.5,
        "crit": 1.0,
        "haste": 0.6,
        "int": 0.2,
        "sta": 0.2,
        "armor": 0.005,
        "ranged": 3.0,
    },
}

# The spell schools each caster spec actually casts, for "fire spell power"
# and its kind. Everything else a school bonus gives is worth nothing to it.
SCHOOLS = {
    (8, 0): ("arcane",),
    (8, 1): ("fire",),
    (8, 2): ("frost",),
    (9, 0): ("shadow",),
    (9, 1): ("shadow",),
    (9, 2): ("fire", "shadow"),
    (5, 2): ("shadow",),
    (7, 0): ("nature",),
    (11, 0): ("arcane", "nature"),
}

# How a role holds its weapons.
SHIELD, TWO_HAND, DUAL, STAFF_OR_HELD, RANGED = (
    "one-hand and shield",
    "two-hander",
    "two one-handers",
    "a staff, or a one-hander and a held item",
    "a ranged weapon",
)

# (class id, talent tree) -> (role, how it holds its weapons).
SPECS = {
    (1, 0): (STRENGTH, TWO_HAND),
    (1, 1): (STRENGTH, DUAL),
    (1, 2): (TANK, SHIELD),
    (2, 0): (HEALER, SHIELD),
    (2, 1): (TANK, SHIELD),
    (2, 2): (STRENGTH, TWO_HAND),
    (3, 0): (HUNTER, RANGED),
    (3, 1): (HUNTER, RANGED),
    (3, 2): (HUNTER, RANGED),
    (4, 0): (AGILITY, DUAL),
    (4, 1): (AGILITY, DUAL),
    (4, 2): (AGILITY, DUAL),
    (5, 0): (HEALER, STAFF_OR_HELD),
    (5, 1): (HEALER, STAFF_OR_HELD),
    (5, 2): (CASTER, STAFF_OR_HELD),
    (7, 0): (CASTER, SHIELD),
    (7, 1): (STRENGTH, TWO_HAND),
    (7, 2): (HEALER, SHIELD),
    (8, 0): (CASTER, STAFF_OR_HELD),
    (8, 1): (CASTER, STAFF_OR_HELD),
    (8, 2): (CASTER, STAFF_OR_HELD),
    (9, 0): (CASTER, STAFF_OR_HELD),
    (9, 1): (CASTER, STAFF_OR_HELD),
    (9, 2): (CASTER, STAFF_OR_HELD),
    (11, 0): (CASTER, STAFF_OR_HELD),
    (11, 1): (TANK, TWO_HAND),
    (11, 2): (HEALER, STAFF_OR_HELD),
}

# A class whose talent tree is unread gets its first-listed spec's role.
_DEFAULT_TREE = {1: 2, 2: 2, 3: 1, 4: 1, 5: 1, 7: 2, 8: 2, 9: 2, 11: 2}

_CLASS_NAMES = {
    1: "Warrior",
    2: "Paladin",
    3: "Hunter",
    4: "Rogue",
    5: "Priest",
    7: "Shaman",
    8: "Mage",
    9: "Warlock",
    11: "Druid",
}


@functools.lru_cache(maxsize=1)
def _tree_names() -> dict:
    path = Path(__file__).resolve().parent / "talents.json"
    try:
        with open(path) as f:
            trees = json.load(f)["trees"]
    except (OSError, ValueError, KeyError):
        return {}
    return {(int(t["class"]), int(t["order"])): str(t["name"]) for t in trees.values()}


@dataclass(frozen=True)
class Member:
    """One family member as the plan sees them: who, what they are, and what
    they wear by paper-doll slot (0 head ... 17 ranged)."""

    name: str
    class_id: int
    level: int
    tree: int = -1
    worn: dict = field(default_factory=dict)
    race: int = 0

    @property
    def spec(self) -> tuple:
        tree = (
            self.tree
            if (self.class_id, self.tree) in SPECS
            else _DEFAULT_TREE.get(self.class_id, 0)
        )
        return (self.class_id, tree)

    @property
    def role(self) -> str:
        return SPECS.get(self.spec, (STRENGTH, TWO_HAND))[0]

    @property
    def hands(self) -> str:
        return SPECS.get(self.spec, (STRENGTH, TWO_HAND))[1]

    @property
    def spec_name(self) -> str:
        tree = _tree_names().get(self.spec, "")
        return (
            "%s %s" % (tree, _CLASS_NAMES.get(self.class_id, ""))
        ).strip() or "unknown"

    @property
    def average(self) -> int:
        levels = [i.item_level for s, i in self.worn.items() if s not in (3, 18)]
        return round(sum(levels) / len(levels)) if levels else 0


def members(member_rows: list, worn_rows: list, texts=None) -> list:
    """Members from MEMBERS_SQL and WORN_SQL rows, in the order given."""
    worn: dict = {}
    for row in worn_rows or []:
        worn.setdefault(str(row["member"]), {})[int(row["slot"])] = item(row, texts)
    out = []
    for row in member_rows or []:
        tree = row.get("spec_tab")
        tree = int(tree) if tree is not None and int(tree) < 3 else -1
        out.append(
            Member(
                name=str(row["name"]),
                class_id=int(row.get("class_id") or 0),
                level=int(row.get("level") or 0),
                tree=tree,
                worn=worn.get(str(row["name"]), {}),
                race=int(row.get("race") or 0),
            )
        )
    return out


def score(piece: Item, member: Member, slot: int | None = None) -> float:
    """What `piece` is worth to `member`, in points of their main stat."""
    weights = ROLES[member.role]
    schools = SCHOOLS.get(member.spec, ())
    total = 0.0
    for name, value in piece.stats:
        if name.startswith("sp_"):
            total += value * weights.get("sp", 0) if name[3:] in schools else 0.0
        else:
            total += value * weights.get(name, 0)
    total += piece.armor * weights.get("armor", 0)
    if piece.dps:
        if (
            piece.inventory_type in (15, 25, 26)
            and piece.subclass != bag_pressure.WEAPON_WAND
        ):
            total += piece.dps * weights.get("ranged", 0)
        elif slot == 16 or piece.inventory_type == 22:
            total += piece.dps * weights.get("off", 0)
        elif piece.inventory_type in (13, 17, 21):
            total += piece.dps * weights.get("weapon", 0)
    return round(total, 1)


# --- who can wear what, where ------------------------------------------------------

SLOT_NAMES = {
    0: "head",
    1: "neck",
    2: "shoulders",
    4: "chest",
    5: "waist",
    6: "legs",
    7: "feet",
    8: "wrists",
    9: "hands",
    10: "ring",
    11: "ring",
    12: "trinket",
    13: "trinket",
    14: "back",
    15: "main hand",
    16: "off hand",
    17: "ranged",
}

_ARMOUR_SLOTS = {1: 0, 2: 1, 3: 2, 5: 4, 20: 4, 6: 5, 7: 6, 8: 7, 9: 8, 10: 9, 16: 14}
_PAIRS = {11: (10, 11), 12: (12, 13)}
_RELIC = 28


def _class_allows(piece: Item, member: Member) -> bool:
    bit = 1 << (member.class_id - 1)
    mask = piece.allowable_class
    return mask in (-1, 0) or bool(mask & bit)


def slots_for(piece: Item, member: Member) -> tuple:
    """The paper-doll slots `piece` could go in for `member`, () for none."""
    if piece.required_level > member.level or not _class_allows(piece, member):
        return ()
    if not bag_pressure.can_equip_piece(piece, member.class_id, member.level):
        return ()
    kind = piece.inventory_type
    if kind in _ARMOUR_SLOTS:
        heaviest = bag_pressure.heaviest_armor(member.class_id, member.level)
        body = piece.item_class == 4 and piece.subclass in (1, 2, 3, 4) and kind != 16
        return (_ARMOUR_SLOTS[kind],) if not body or piece.subclass == heaviest else ()
    if kind in _PAIRS:
        return _PAIRS[kind]
    return _hand_slots(piece, member)


def _hand_slots(piece: Item, member: Member) -> tuple:
    kind, hands = piece.inventory_type, member.hands
    if kind in (15, 25, 26):
        wand = piece.subclass == bag_pressure.WEAPON_WAND
        caster = member.role in (CASTER, HEALER) and member.class_id in (5, 8, 9)
        return (17,) if wand == caster else ()
    if kind == _RELIC:
        return (17,)
    if kind == 17:
        return (15,) if hands in (TWO_HAND, STAFF_OR_HELD, RANGED) else ()
    if kind == 14:
        return (16,) if hands == SHIELD else ()
    if kind == 23:
        return (16,) if hands == STAFF_OR_HELD else ()
    if kind in (13, 21):
        if hands == DUAL and kind == 13:
            return (15, 16)
        return (15,) if hands in (SHIELD, DUAL, STAFF_OR_HELD) else ()
    if kind == 22:
        return (16,) if hands == DUAL else ()
    return ()


# --- the plan --------------------------------------------------------------------


@dataclass(frozen=True)
class Upgrade:
    """One piece `member` would gain from, against what is worn."""

    member: str
    slot: int
    item: Item
    gain: float  # score points over what is worn
    levels: int  # item level over what is worn (may be negative)

    @property
    def slot_name(self) -> str:
        return SLOT_NAMES.get(self.slot, "slot %d" % self.slot)

    @property
    def said(self) -> str:
        return "%s: %s (item level %d, %+d)" % (
            self.slot_name,
            self.item.name,
            self.item.item_level,
            self.levels,
        )


def _worn_score(member: Member, slot: int) -> tuple:
    """(score, item level) against which a piece for `slot` is measured."""
    worn = member.worn
    if slot in (10, 11, 12, 13):
        pair = (10, 11) if slot in (10, 11) else (12, 13)
        held = [
            (score(worn[s], member, s), worn[s].item_level) if s in worn else (0.0, 0)
            for s in pair
        ]
        return min(held)
    here = worn.get(slot)
    if here is None:
        return 0.0, 0
    return score(here, member, slot), here.item_level


def upgrade(piece: Item, member: Member) -> Upgrade | None:
    """The best slot `piece` improves for `member`, or None."""
    best = None
    worn_entries = {i.entry for i in member.worn.values()}
    if piece.entry in worn_entries:
        return None
    for slot in slots_for(piece, member):
        mine = score(piece, member, slot)
        against, levels = _worn_score(member, slot)
        main = member.worn.get(15)
        if slot == 15 and piece.inventory_type == 17:
            off = member.worn.get(16)
            if off is not None:
                against += score(off, member, 16)
        elif slot == 16 and main is not None and main.inventory_type == 17:
            continue  # an off hand is no use until the two-hander goes
        elif (
            slot == 15
            and main is not None
            and main.inventory_type == 17
            and member.hands == TWO_HAND
        ):
            continue
        gain = round(mine - against, 1)
        if gain <= max(1.0, 0.03 * against):
            continue
        found = Upgrade(member.name, slot, piece, gain, piece.item_level - levels)
        if best is None or found.gain > best.gain:
            best = found
    return best


@dataclass(frozen=True)
class SlotPlan:
    slot: int
    worn: Item | None
    target: Upgrade | None  # the best piece anywhere
    next: Upgrade | None  # the best piece the family can go and get now


@dataclass(frozen=True)
class MemberPlan:
    member: Member
    slots: tuple
    upgrades: tuple  # every Upgrade, best gain first

    def next_up(self, reachable, limit: int = 5) -> tuple:
        """The biggest upgrades the family can go and get, best first: one a
        slot, two for the rings and the trinkets."""
        out: list = []
        taken: dict = {}
        for u in self.upgrades:
            group = next((g for g in SLOT_GROUPS if u.slot in g), (u.slot,))
            if not _reachable(u.item, reachable) or taken.get(group, 0) >= len(group):
                continue
            taken[group] = taken.get(group, 0) + 1
            out.append(u)
        return tuple(out[:limit])


def _reachable(piece: Item, reachable) -> bool:
    return any(reachable_place(s.place, reachable) for s in piece.sources)


def reachable_place(place: str, reachable) -> bool:
    """Whether `place` can be gone to, given the runs in `reachable`."""
    if place in QUEST_PLACES:
        return any(run in reachable for run in QUEST_PLACES[place][1])
    if place in SHARED_PLACES:
        return any(run in reachable for run in SHARED_PLACES[place])
    return place in reachable


def drops_at(source_place: str, place: str) -> bool:
    """Whether a drop placed at `source_place` falls on a run of `place`:
    the same place, or a place reached through it (SHARED_PLACES)."""
    return source_place == place or place in SHARED_PLACES.get(source_place, ())


# The paper-doll slots as the plan groups them: a pair of rings and a pair of
# trinkets are one choice of two pieces.
SLOT_GROUPS = (
    (0,),
    (1,),
    (2,),
    (14,),
    (4,),
    (8,),
    (9,),
    (5,),
    (6,),
    (7,),
    (10, 11),
    (12, 13),
    (15,),
    (16,),
    (17,),
)


def for_member(items: dict, member: Member) -> dict:
    """The catalog as `member` sees it: each piece with only the sources that
    allow them (a quest reward for the other faction or another class is no
    source at all), and pieces with none left out."""
    out = {}
    for entry, piece in items.items():
        allowed = tuple(
            s for s in piece.sources if s.allows(member.race, member.class_id)
        )
        if allowed:
            out[entry] = (
                piece if allowed == piece.sources else replace(piece, sources=allowed)
            )
    return out


def plan(member: Member, items: dict, reachable=()) -> MemberPlan:
    """`member`'s pre-raid plan over the catalog `items`.

    Per slot, the TARGET is the best piece anywhere in the level 60 dungeons
    and NEXT the best one from a place in `reachable`; for a pair of rings or
    trinkets, the best two distinct pieces.
    """
    mine = for_member(items, member)
    found = [u for u in (upgrade(i, member) for i in mine.values()) if u is not None]
    found.sort(key=lambda u: (-u.gain, u.item.entry))
    slots = []
    for group in SLOT_GROUPS:
        here = [u for u in found if u.slot in group]
        near = [u for u in here if _reachable(u.item, reachable)]
        for i, slot in enumerate(group):
            slots.append(
                SlotPlan(
                    slot,
                    member.worn.get(slot),
                    here[i] if len(here) > i else None,
                    near[i] if len(near) > i else None,
                )
            )
    return MemberPlan(member, tuple(slots), tuple(found))


# --- what a run gives ------------------------------------------------------------


@dataclass(frozen=True)
class Gain:
    """What one run of a place is worth to one member."""

    name: str
    upgrades: int  # distinct upgrade pieces that drop there
    drops: float  # expected upgrade pieces per run
    levels: float  # expected item levels gained per run
    best: str  # the likeliest big upgrade, said

    @property
    def line(self) -> str:
        if not self.upgrades:
            return "%s: nothing" % self.name
        return "%s: %d upgrade%s, %.2f a run, best %s" % (
            self.name,
            self.upgrades,
            "" if self.upgrades == 1 else "s",
            self.drops,
            self.best,
        )


def run_gains(plans: list) -> dict:
    """place -> (Gain per member), from each member's upgrades.

    A piece's chance at a place is the sum of its drop sources there, capped
    at one per run; a drop in inner Maraudon counts for both wings that lead
    there (SHARED_PLACES). A quest reward is not counted: it is had once, not
    every run. The item levels a run is worth are, per slot, the expected best
    upgrade that drops for it: two chests that each drop one run in five are
    not worth two chests, because only one is worn.
    """
    out: dict = {}
    for place in PLACES:
        gains = []
        for member_plan in plans:
            pieces = []
            for u in member_plan.upgrades:
                p = min(
                    sum(
                        s.chance
                        for s in u.item.sources
                        if drops_at(s.place, place) and s.kind != QUEST
                    )
                    / 100.0,
                    1.0,
                )
                if p > 0:
                    pieces.append((u, p))
            best = max(
                pieces,
                key=lambda up: (up[1] * max(up[0].levels, 1), up[0].gain),
                default=None,
            )
            gains.append(
                Gain(
                    name=member_plan.member.name,
                    upgrades=len(pieces),
                    drops=round(sum(p for _u, p in pieces), 2),
                    levels=_expected_levels(pieces),
                    best=""
                    if best is None
                    else "%s for %s (%+d item levels, %s)"
                    % (
                        best[0].item.name,
                        best[0].slot_name,
                        best[0].levels,
                        _pct(best[1] * 100),
                    ),
                )
            )
        out[place] = tuple(gains)
    return out


def _expected_levels(pieces: list) -> float:
    """The item levels one run is expected to add, slot by slot: in each
    slot group, the biggest upgrade that drops, given that the bigger ones
    did not."""
    total = 0.0
    for group in SLOT_GROUPS:
        here = sorted(
            ((max(u.levels, 0), p) for u, p in pieces if u.slot in group), reverse=True
        )
        missed = 1.0
        for levels, p in here:
            total += missed * p * levels
            missed *= 1.0 - p
    return round(total, 2)


# --- the attunement and the key ------------------------------------------------------

ATTUNEMENT, KEY = "attunement", "key"


@dataclass(frozen=True)
class Progress:
    """What a run of `place` does for the raid's attunement or key.

    rank   2 for the attunement, 1 for the key: which the planner puts first
    gains  whether a run advances it now (the objective can drop for us)
    """

    place: str
    kind: str
    needed: bool
    gains: bool
    line: str

    @property
    def rank(self) -> int:
        if not (self.needed and self.gains):
            return 0
        return 2 if self.kind == ATTUNEMENT else 1


def progress(names: list, rewarded_rows: list, log_rows: list, item_rows: list) -> dict:
    """place -> Progress for Blackrock Depths (the attunement) and the Lower
    Spire (the key), from the three PROGRESS reads."""
    rewarded: dict = {}
    for row in rewarded_rows or []:
        rewarded.setdefault(str(row["name"]), set()).add(int(row["quest"]))
    in_log: dict = {}
    for row in log_rows or []:
        if int(row.get("status") or 0) in IN_LOG:
            in_log.setdefault(str(row["name"]), set()).add(int(row["quest"]))
    held: dict = {}
    for row in item_rows or []:
        held.setdefault(str(row["name"]), {})[int(row["entry"])] = int(
            row.get("count") or 0
        )
    return {
        "blackrock-depths": _attunement(names, rewarded, in_log, held),
        "lower-blackrock-spire": _key(names, rewarded, held),
    }


def _attunement(names, rewarded, in_log, held) -> Progress:
    attune = set(ATTUNEMENT_QUESTS)
    unattuned = [n for n in names if not rewarded.get(n, set()) & attune]
    if not unattuned:
        return Progress(
            "blackrock-depths",
            ATTUNEMENT,
            False,
            False,
            "every member is attuned to the Core",
        )
    seeking = [
        n
        for n in unattuned
        if in_log.get(n, set()) & attune and not held.get(n, {}).get(CORE_FRAGMENT)
    ]
    if seeking:
        line = (
            "Attunement to the Core: %s hold%s the quest and need%s a Core Fragment, "
            "which drops beside the Molten Bridge here"
            % (
                _and(seeking),
                "s" if len(seeking) == 1 else "",
                "s" if len(seeking) == 1 else "",
            )
        )
        return Progress("blackrock-depths", ATTUNEMENT, True, True, line)
    carrying = [n for n in unattuned if held.get(n, {}).get(CORE_FRAGMENT)]
    if carrying:
        line = (
            "Attunement to the Core: %s carr%s a Core Fragment to hand to Lothos Riftwaker"
            % (
                _and(carrying),
                "ies" if len(carrying) == 1 else "y",
            )
        )
        return Progress("blackrock-depths", ATTUNEMENT, True, False, line)
    line = (
        "Attunement to the Core: %d of %d are not attuned and none holds the quest; "
        "each takes it from Lothos Riftwaker (creature %d) on Blackrock Mountain "
        "first, because the Core Fragment drops only for a holder"
        % (len(unattuned), len(names), LOTHOS)
    )
    return Progress("blackrock-depths", ATTUNEMENT, True, False, line)


def _key(names, rewarded, held) -> Progress:
    keyed = [
        n
        for n in names
        if held.get(n, {}).get(SEAL_OF_ASCENSION)
        or KEY_QUESTS[1] in rewarded.get(n, set())
    ]
    if keyed:
        return Progress(
            "lower-blackrock-spire",
            KEY,
            False,
            False,
            "the Upper Spire key: %s hold%s the Seal of Ascension"
            % (_and(keyed), "s" if len(keyed) == 1 else ""),
        )
    counts = {n: [e for e in KEY_PIECES if held.get(n, {}).get(e)] for n in names}
    lead = max(names, key=lambda n: (len(counts[n]), -names.index(n)), default="")
    have = counts.get(lead, [])
    if len(have) == len(KEY_PIECES):
        return Progress(
            "lower-blackrock-spire",
            KEY,
            True,
            False,
            "the Upper Spire key: %s holds all four pieces; Vaelan's quest "
            "and the forging come next" % lead,
        )
    missing = [KEY_PIECES[e] for e in KEY_PIECES if e not in have]
    line = "the Upper Spire key: %s; still to find: %s" % (
        "%s holds %d of the 4 pieces" % (lead, len(have))
        if have
        else "nobody holds a piece yet",
        _and(missing),
    )
    return Progress("lower-blackrock-spire", KEY, True, True, line)


def _and(names: list) -> str:
    names = list(names)
    if len(names) < 2:
        return "".join(names)
    return "%s and %s" % (", ".join(names[:-1]), names[-1])


# --- the Raid tab ----------------------------------------------------------------

COLUMNS = ("slot", "wearing", "next upgrade", "where it drops", "pre-raid target")

WEIGHTS_LINE = (
    "Upgrades are ranked by rough stat weights for each member's talent tree, "
    "not by item level alone, over every rare or better piece that drops "
    "at least %d%% of the time, or is a quest reward, in the level 60 "
    "dungeons (Blackrock Depths, both Blackrock Spires, Dire Maul, "
    "Scholomance, Stratholme and the Sunken Temple), read from the world's "
    "loot tables. Chances are per run." % MIN_CHANCE
)


def _where(piece: Item | None, limit: int = 2) -> str:
    if piece is None:
        return ""
    return "; ".join(s.said for s in piece.sources[:limit])


def _cells(slot: SlotPlan) -> list:
    return [
        SLOT_NAMES[slot.slot],
        "%s (%d)" % (slot.worn.name, slot.worn.item_level) if slot.worn else "nothing",
        slot.next.said.split(": ", 1)[1] if slot.next else "-",
        _where(slot.next.item) if slot.next else "",
        slot.target.said.split(": ", 1)[1] + ", " + _where(slot.target.item, 1)
        if slot.target
        else "what is worn",
    ]


def member_view(member_plan: MemberPlan, reachable) -> dict:
    """One member's block on the Raid tab: the line, the next few upgrades
    and where they drop, and the slot table."""
    member = member_plan.member
    nxt = member_plan.next_up(reachable)
    if nxt:
        line = "%s, %s, wears item level %d. Next upgrades: %s." % (
            member.name,
            member.spec_name,
            member.average,
            "; ".join("%s from %s" % (u.said, _where(u.item, 1)) for u in nxt[:3]),
        )
    elif member_plan.upgrades:
        u = member_plan.upgrades[0]
        line = (
            "%s, %s, wears item level %d. Every upgrade is where the family "
            "cannot go yet; the biggest is %s from %s."
            % (
                member.name,
                member.spec_name,
                member.average,
                u.said,
                _where(u.item, 1),
            )
        )
    else:
        line = "%s, %s: no dungeon piece beats what is worn." % (
            member.name,
            member.spec_name,
        )
    return {
        "name": member.name,
        "spec": member.spec_name,
        "line": line,
        "next": [
            {"said": u.said, "where": _where(u.item), "gain": u.gain} for u in nxt
        ],
        "rows": [{"cells": _cells(s)} for s in member_plan.slots],
    }


def build_view(plans: list, reachable, refused: dict, progress_by_place: dict) -> dict:
    """The Raid tab's pre-raid section for one family."""
    unreachable = sorted(p for p in PLACES if p not in set(reachable))
    why = [
        "%s: %s"
        % (
            place_name(p),
            refused.get(p)
            or CLOSED.get(p)
            or (
                "reached only through %s, and neither is open"
                % " or ".join(place_name(r) for r in SHARED_PLACES[p])
                if p in SHARED_PLACES
                else "no door the overseer can use"
            ),
        )
        for p in unreachable
    ]
    gains = run_gains(plans)
    runs = sorted(
        (p for p in PLACES if p in set(reachable)),
        key=lambda p: (-expected_levels(gains[p]), p),
    )
    return {
        "line": (
            "Next upgrades and where they drop, for each member against what "
            "they wear. The family can go to %s now."
            % (_and([place_name(p) for p in runs]) or "none of these dungeons")
        ),
        "columns": list(COLUMNS),
        "members": [member_view(p, reachable) for p in plans],
        "runs": [
            "%s: %.1f item levels a run, summed over every member's slots. %s."
            % (place_name(p), expected_levels(gains[p]), said_gains(gains[p]))
            for p in runs
        ],
        "progress": [p.line for p in progress_by_place.values()],
        "closed": why,
        "basis": WEIGHTS_LINE,
    }


def family_view(
    names: list,
    member_rows: list,
    worn_rows: list,
    items: dict,
    rewarded_rows: list,
    log_rows: list,
    held_rows: list,
) -> dict:
    """build_view for one family off the Raid tab's reads.

    Which dungeons the family can go to is campaignplan's answer, the same
    refusals its planner and an operator's queue order are held to, so the
    page and the planner cannot disagree about where the next upgrade is.
    """
    wanted = set(names)
    rows = [r for r in member_rows or [] if r.get("name") in wanted]
    levels = [int(r.get("level") or 0) for r in rows]
    why_not = ""
    if not levels:
        why_not = "Nobody's level could be read, so there is no pre-raid plan."
    elif min(levels) < LEVEL_CAP:
        why_not = (
            "The pre-raid plan starts when the whole family is level %d; the "
            "weakest is %d." % (LEVEL_CAP, min(levels))
        )
    elif not items:
        why_not = "The level 60 dungeons' loot tables could not be read on this realm."
    if why_not:
        return {
            "line": why_not,
            "columns": list(COLUMNS),
            "members": [],
            "runs": [],
            "progress": [],
            "closed": [],
            "basis": WEIGHTS_LINE,
        }
    family = members(rows, [r for r in worn_rows or [] if r.get("member") in wanted])
    # The upgrades first: a lower dungeon is open to a level 60 family only
    # while it still holds one (campaignplan.refusals), the planner's rule.
    upgrades = run_gains([plan(m, items) for m in family])
    held = [r for r in held_rows or [] if r.get("name") in wanted]
    facts = campaignplan.Facts(
        family=names[0] if names else "",
        level_rows=tuple(rows),
        done={},
        failed={},
        upgrades=upgrades,
        keys=campaignplan.keys_held(
            [r for r in held if int(r.get("entry") or 0) in campaignplan.KEY_ITEMS]
        ),
    )
    refused = campaignplan.refusals(facts)
    reachable = {r.keyword for r in campaignplan.RUNS if r.keyword not in refused}
    plans = [plan(m, items, reachable) for m in family]
    moved = progress(
        [m.name for m in family],
        [r for r in rewarded_rows or [] if r.get("name") in wanted],
        [r for r in log_rows or [] if r.get("name") in wanted],
        [r for r in held_rows or [] if r.get("name") in wanted],
    )
    return build_view(plans, open_places(reachable), refused, moved)


def open_places(reachable) -> set:
    """The places the family can go to, given the runs in `reachable`: those
    runs, and a place reached through one of them (inner Maraudon)."""
    return {p for p in PLACES if reachable_place(p, reachable)}


def said_gains(gains: tuple) -> str:
    """One run's worth to every member, in a line."""
    return "; ".join(g.line for g in gains)


def expected_levels(gains: tuple) -> float:
    return round(sum(g.levels for g in gains), 2)
