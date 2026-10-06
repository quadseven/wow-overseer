"""Every guild member's job, earned in play: farm, gather, post, sell, level (#194).

WHAT THE OPERATOR ASKED FOR (2026-09-24). "NATURALLY EARNED ONLY! All guild
members can feel free to contribute! I expect the 10 guild maintenance members
to farm and contribute the most since they will never raid! And the warlocks
doing nothing but summoning can farm occasionally too near their summon areas."
Both guilds are 71 places (raidlineup.py): the family, forty raiders, ten on
maintenance and twenty-one warlocks kept for summoning. Every guild bot is
restarted at level 1 with nothing, and the random-bot factory no longer hands a
guild member anything, so whatever a member gives the guild it has gathered,
looted or been paid for in play.

WHAT EACH ROLE DOES, and the order a member's work is chosen in each pass. One
step per member per pass; a step is a walk and the rows that follow it, the
guild corps' own `Step` shape, run by the corps' own runner in the bridge.

  maintenance  1. train: learn the two gathering trades the guild gave it (see
                  TRADE SPLIT) at a real trainer, and each next rank as its
                  skill reaches the ceiling, level and purse allowing; the
                  module's `walk-to-trainer skill:` buys the rank through the
                  core's own Trainer::TeachSpell, so the trainer is paid.
               2. tool: buy the Mining Pick or Skinning Knife its trade needs
                  (`walk-to-vendor item:` then `buy`), because the core will
                  not let it mine or skin without one.
               3. post: mail the materials it carries to whoever in the guild
                  uses them (see WHERE MATERIALS GO).
               4. sell: walk to any vendor that buys (`walk-to-vendor any`)
                  and sell its grey loot.
               5. farm: walk to a field of nodes its skill can open at a level
                  it can survive (gatheraim.choose, over the world's own node
                  spawns), with `walk-to-spawn gameobject:`; there the module
                  lets it go and its own gather and grind strategies work. A
                  skinner with no node trade is sent instead to the densest
                  pack of beasts it can kill and skin (`skinning_field`, over
                  the world's creature spawns), with `walk-to-spawn creature:`.
  summoner     post and sell like anybody. Below level 20 it levels, because
               Ritual of Summoning is learned at 20 and needs a Soul Shard.
               With the ritual it is given a door (see WHICH DOOR) and, while
               no summon is waiting on it, walks to that door's meeting stone
               with `walk-to-spawn` and farms there; the summon itself is
               quadseven/mod-overseer#702's.
  raider       post and sell, with a higher bar: its bags are for the raid.
               It levels on its own and raids when the guild does.

  every role   level: before its ordinary job, a member that has outgrown the
               zone it stands in (its level over the zone's quest band, a
               capital or a starting zone, or map 530) walks to the flight
               master of the lowest quest hub of its side whose band fits its
               level, with `walk-to-spawn creature:` (guildlevel.py). Never a
               roster family member, whom levelroute.py walks.

The gold each role posts is guildwork.py's, which gives maintenance the
largest share.

NATURALLY EARNED ONLY. A member acts here only once `eligible` says it has
restarted naturally (natural.py's gate, which the bridge asks). A
member that has not is listed with why and left alone: nothing it carries or
holds was earned. Nothing here ever grants, teaches, gives or teleports; every
row is a verb a player has, and every coordinate is a spawn row of the world's
own tables named by its id.

WHERE MATERIALS GO. Herbs, ore, stone, bars, leather, cloth, meat and elemental
materials a member carries go by post, one stack a letter, to the family member
of its guild who holds the craft that uses them (alchemy for herbs, and so on),
the highest skill first; with nobody holding it, to the guild master, whose
guild-bank pass files them into the Materials tab (bankpolicy.py). An item
reserved on its holder (`overseer_keep`, read through keep.py) is never posted
or sold.

TRADE SPLIT. Each maintenance member takes two of the three gathering trades,
as a guild officer would split them: whatever it already holds first, then the
trade the crew has fewest of, herbalism before mining before skinning on a tie
(herbs feed the raid's potions, bankpolicy's Raid Supplies). Ten members give
seven, seven and six.

WHICH DOOR. A warlock with the ritual serves the dungeon door whose band fits
its level (campaignplan.RUNS, asked through council.door_refusal_kind as a
party of one, so the faction, level floor and crossing rules are the family's
own) and farms near that door's meeting stone, the stone nearest the door's
entrance (entrances.json) in the world's spawn table. The warlocks are spread
over the doors that fit, fewest first.

THE CLOTH TRADES (the operator, 2026-09-29: "those are valuable crafting
resources for someone"). Every maintenance member also learns First Aid, a
secondary trade that costs no primary slot, and one member in three takes
Tailoring in place of one gathering trade (`choose_tailors`). A member that
holds either casts what the cloth in its own bags allows (`_craft_step`):
Linen Bandage, then Bolt of Linen Cloth, each the recipe craft.py keeps for
its skill value. Any other crafting trade craft.py covers is cast the same
way from what the member carries (2026-10-05). It keeps the materials its
next casts eat instead of posting them, and posts the rest as before. The
trainer rows are `walk-to-trainer skill:` and the casts are `cast` rows:
what a player does, paid for at a trainer.

THE GUILD FOCUS (`GUILD_FOCUS`, 2026-10-05). A guild named with focus craft
gives every free member the maintenance work above, natural or not for its
own casts and fields; focus dungeon keeps today's jobs. See THE GUILD FOCUS
below.

PURE MODULE: rows in, steps and sentences out. No MySQL, no clock.
"""

from __future__ import annotations

import functools
import json
import math
import os
import re
from dataclasses import dataclass, field

import campaignplan
import classic
import classquest
import council
import craft
import craft_rhythm
import craft_supply
import dungeonpath
import gearup
import guildcorps
import guildlevel
import guildroute
import keep
import pvpgear
import raidroles
import situation

HERBALISM = guildcorps.HERBALISM
MINING = guildcorps.MINING
SKINNING = guildcorps.SKINNING
GATHERING = (HERBALISM, MINING, SKINNING)
FIRST_AID = 129
TAILORING = guildcorps.TAILORING
SKILL_NAMES = {
    HERBALISM: "Herbalism",
    MINING: "Mining",
    SKINNING: "Skinning",
    FIRST_AID: "First Aid",
    TAILORING: "Tailoring",
    164: "Blacksmithing",
    165: "Leatherworking",
    171: "Alchemy",
    185: "Cooking",
    202: "Engineering",
}

# The primary trades, gathering and crafting, by skill line. Two may be held.
PRIMARY_SKILLS = frozenset({164, 165, 171, 182, 186, 197, 202, 333, 393, 755, 773})
MAX_PRIMARY = 2

# The roles, as raidlineup.build_lineup names them.
MAINTENANCE, SUMMONER, RAIDER, FAMILY = "maintenance", "summoner", "raider", "family"


@dataclass(frozen=True)
class Rank:
    """One trainer rank of a gathering trade.

    `spell` is the trainer's spell, `cap` the ceiling it gives, `level` and
    `needs` the character level and skill value the trainer asks, `cost` its
    price in copper before any reputation discount.
    """

    spell: int
    cap: int
    level: int
    needs: int
    cost: int


# THE RANKS, MEASURED RATHER THAN REMEMBERED: acore_world.trainer_spell on the
# dev world, 2026-09-24 (the least MoneyCost per SpellId across the trainers
# that teach it). Expert and Artisan past 300 are Outland ranks, left out under
# the classic ruleset. The module's trainer walk asks the core, not this table,
# which rank a trainer sells; this table only keeps the pass from asking before
# the level or the purse allows it.
RANKS = {
    HERBALISM: (
        Rank(2372, 75, 5, 0, 10),
        Rank(2373, 150, 10, 50, 500),
        Rank(3571, 225, 10, 125, 5000),
        Rank(11994, 300, 25, 200, 50000),
    ),
    MINING: (
        Rank(2581, 75, 5, 0, 10),
        Rank(2582, 150, 10, 50, 500),
        Rank(3568, 225, 10, 125, 5000),
        Rank(10249, 300, 25, 200, 50000),
    ),
    SKINNING: (
        Rank(8615, 75, 0, 0, 10),
        Rank(8619, 150, 0, 50, 500),
        Rank(8620, 225, 10, 125, 5000),
        Rank(10769, 300, 25, 200, 50000),
    ),
}

# THE CLOTH TRADES (the operator, 2026-09-29: "those are valuable crafting
# resources for someone"). Every guild's maintenance crew learns First Aid, a
# secondary trade that costs no primary slot, and a third of it also takes
# Tailoring in place of one gathering trade, so cloth the crew loots has a
# consumer that is not a family member. Measured on the dev world
# (acore_world.trainer_spell, 2026-09-29): Apprentice First Aid is the
# wrapper 3279 (one silver, no level); Journeyman and Expert are 3280 and
# 54254. Tailoring's ranks are the corps' own 3911, 3912 and 3913.
#
# ARTISAN, THE RANK AT 200 (2026-10-05). `acore_world.trainer_spell` sells
# Artisan First Aid as 10847 (ReqSkillRank 200, ReqLevel 35, 25000c, trainers
# 81, 82 and 83: every First Aid trainer) and Artisan Tailoring as 12181
# (ReqSkillRank 200, ReqLevel 35, 50000c, trainers 72, 73 and 74: every
# Tailoring trainer). The realm's Spell.dbc (md5 543b9fe6...) says each is a
# wrapper whose SPELL_EFFECT_LEARN_SPELL teaches the rank spell, 10846 and
# 12180, and whose SPELL_EFFECT_SKILL_STEP is step 4 of skill 129 and 197:
# the 300 ceiling. Without these rows the crew and the family stopped at 225.
RANKS[FIRST_AID] = (
    Rank(3279, 75, 0, 0, 100),
    Rank(3280, 150, 0, 50, 500),
    Rank(54254, 225, 0, 125, 1000),
    Rank(10847, 300, 35, 200, 25000),
)
RANKS[TAILORING] = (
    Rank(3911, 75, 5, 0, 10),
    Rank(3912, 150, 10, 50, 500),
    Rank(3913, 225, 20, 125, 5000),
    Rank(12181, 300, 35, 200, 50000),
)

# LEATHERWORKING AND ALCHEMY, THE SAME FOUR RANKS (2026-10-05). Read from
# `trainer_spell` on the dev world (least MoneyCost across the trainers that
# teach each: 4 for Leatherworking, 3 for Alchemy) and from Spell.dbc (md5
# 543b9fe6...): each is a wrapper whose SPELL_EFFECT_LEARN_SPELL teaches the
# rank spell (Leatherworking 2108, 3104, 3811, 10662; Alchemy 2259, 3101,
# 3464, 11611) and whose SPELL_EFFECT_SKILL_STEP is step 1 to 4 of skill 165
# or 171: ceilings 75, 150, 225, 300. Expert asks level 20 and Artisan 35,
# like Tailoring's. `next_rank` and `ranks_due` need nothing else: the
# family's rank errand reads this table (bridge._RANK_FACTS_SQL), and the
# crew's `_train_step` reads it for a held crafting trade.
LEATHERWORKING, ALCHEMY = 165, 171
RANKS[LEATHERWORKING] = (
    Rank(2155, 75, 5, 0, 10),
    Rank(2154, 150, 10, 50, 500),
    Rank(3812, 225, 20, 125, 5000),
    Rank(10663, 300, 35, 200, 50000),
)
RANKS[ALCHEMY] = (
    Rank(2275, 75, 5, 0, 10),
    Rank(2280, 150, 10, 50, 500),
    Rank(3465, 225, 20, 125, 5000),
    Rank(11612, 300, 35, 200, 50000),
)
# The crafting trades whose rank a member buys once it holds them, beside the
# gathering trades `split_trades` hands out. A trade is never started here.
RANKED_CRAFTS = (LEATHERWORKING, ALCHEMY)

# One maintenance member in this many is a tailor: a crew of ten gives three.
TAILOR_EVERY = 3

# A RECIPE A TRAINER ADDS TO THE BOOK BY ITSELF. Linen Bandage comes with
# Apprentice First Aid and Bolt of Linen Cloth with Apprentice Tailoring
# (SkillLineAbility AcquireMethod 1, ClassMask 0); the other first rungs are
# the rest of craft.py's list of nine auto-learned recipes: Rough Blasting
# Powder, Smelt Copper, Minor Healing Potion, Rough Sharpening Stone, Light
# Leather, Light Armor Kit and Handstitched Leather Cloak. Any other recipe is
# cast only once `character_spell` says the member knows it.
AUTO_LEARNED = frozenset({3275, 2963, 3918, 2657, 2330, 2660, 2881, 2152, 9058})
# EVERY CRAFTING TRADE craft.RECIPES COVERS (2026-10-05). First Aid first, a
# secondary trade every member may hold, then Tailoring, then the rest by
# skill line. A trade with no recipe castable in place (Mining's smelts need a
# forge; Cooking needs a fire) simply never yields a cast.
CRAFT_SKILLS = (FIRST_AID, TAILORING) + tuple(
    sorted(s for s in craft.RECIPES if s not in (FIRST_AID, TAILORING))
)
CRAFT_SPELLS = frozenset(
    r.spell_id for skill in CRAFT_SKILLS for r in craft.RECIPES.get(skill, ())
)
# Casts in one stand, so a stand stays short; the next pass casts more.
CRAFT_BATCH = 10

# A rank is bought once the skill is this close to its ceiling, as a player
# does: the last points of a rank come slowly and the next rank is the point.
RANK_UP_MARGIN = 5

# THE TOOLS. A bot does not mine without a pick or skin without a knife:
# mod-playerbots' LootObject::IsLootPossible lists the items that count, and
# these are its lists. The one bought is the vendor's: a Mining Pick or a
# Skinning Knife, item_template.BuyPrice 81 and 82 copper, 2026-09-24, sold by
# 218 and 113 vendor spawns on the dev world.
MINING_PICK, SKINNING_KNIFE = 2901, 7005
TOOLS = {
    MINING: (MINING_PICK, "Mining Pick", 81),
    SKINNING: (SKINNING_KNIFE, "Skinning Knife", 82),
}
TOOL_ENTRIES = {
    MINING: frozenset(
        {756, 778, 1819, 1893, 1959, 2901, 9465, 20723, 40772, 40892, 40893}
    ),
    SKINNING: frozenset({7005, 12709, 19901, 40772, 40893}),
}

# Warlocks. Ritual of Summoning is taught at level 20 and eats a Soul Shard.
RITUAL_OF_SUMMONING = 698
RITUAL_LEVEL = 20
SOUL_SHARD = 6265

# WHAT COUNTS AS A MATERIAL: item_template class 7 (Trade Goods) with these
# subclasses: 5 cloth, 6 leather, 7 metal and stone, 8 meat, 9 herb, 10
# elemental. Everything a gatherer, a skinner or a cloth-dropping mob gives.
TRADE_GOODS = 7
MATERIAL_SUBCLASSES = {
    5: "cloth",
    6: "leather",
    7: "metal and stone",
    8: "meat",
    9: "herb",
    10: "elemental",
}

# WHO USES WHICH MATERIAL: the crafts that consume it, first one held wins.
# Tailoring and first aid take cloth; leatherworking leather; blacksmithing,
# engineering and jewelcrafting metal and stone; cooking meat; alchemy herbs;
# the crafts that use elementals.
CONSUMERS = {
    5: (197, 129),
    6: (197, 165),
    7: (164, 202, 755),
    8: (185,),
    9: (171, 773),
    10: (171, 164, 165, 197, 202),
}

# Grey loot: quality 0 with a vendor price. Nobody in any guild needs it.
JUNK_QUALITY = 0

# OUTGROWN WHITE GEAR SELLS LIKE GREY. On wow-dev on 2026-10-04 the first
# guild mail collections were refused "no room in the bags" for 4 of 6
# members, whose bags held the starter weapons and armor they had replaced
# (Cudgel, Practice Sword, Simple Dagger, Scout's Boots) and no grey at all.
# A white weapon or armor piece carried in the bags, OUTGROWN_LEVELS or more
# item levels under its holder, is what a player sells. Never a profession
# tool (miscellaneous weapons: the mining pick and skinning knife; fishing
# poles) and never miscellaneous armor (shirts, rings, necks, trinkets).
# Armor subclasses 1 to 6: cloth, leather, mail, plate, buckler, shield.
WHITE_QUALITY = 1
OUTGROWN_LEVELS = 10
WEAPON, ARMOR = 2, 4
TOOL_WEAPON_SUBCLASSES = frozenset({14, 20})
WORN_ARMOR_SUBCLASSES = frozenset({1, 2, 3, 4, 5, 6})

# THE BAR FOR A POST, per role: a stack must hold at least this many before it
# is worth thirty copper of postage and a walk. Maintenance posts soonest, a
# raider only a real haul. MAX_LETTERS per stand keeps one stop short.
POST_MIN = {MAINTENANCE: 5, SUMMONER: 10, RAIDER: 20}
MAX_LETTERS = 6
POSTAGE_COPPER = 30

# THE BAR FOR A SALE: this many grey stacks, or this much grey worth.
SELL_MIN_STACKS = {MAINTENANCE: 4, SUMMONER: 6, RAIDER: 8}
SELL_MIN_COPPER = 5000
MAX_SALES = 12

# HOW OFTEN EACH KIND OF STEP MAY BE ASKED OF ONE MEMBER, in minutes, counted
# from the command log so a restart forgets nothing.
COOLDOWN_MINUTES = {
    "gear": 60,
    "collect": 60,
    "hearth": 60,
    "train": 60,
    "tool": 60,
    "post": 60,
    "sell": 120,
    "farm": 45,
    "door": 45,
    "craft": 15,
    # A walk, a take or a hand-in toward a class quest (classquest.py).
    classquest.ACTION: 10,
    # A walk out of an outgrown zone to a quest hub (guildlevel.py).
    guildlevel.ACTION: guildlevel.COOLDOWN_MINUTES,
    # PvP for upgrades (#589): a queue row waits this long for its battle.
    "pvp": pvpgear.QUEUE_MINUTES,
}

# A TRAINER WALK THAT KEEPS FAILING IS ASKED LESS OFTEN (#766). Measured on the
# dev world, 2026-09-27: a level 1 hunter was sent to a skinning trainer every
# hour for a day and every walk ended `died on the way to the trainer` or `the
# ground toward the trainer does not hold`, and a level 10 member's walk ended
# on the same ground 20 times. Each failed walk in a row (status `error` or
# `unchanged` in the log, newest first, until one that did not fail) doubles
# the wait, up to this cap; a walk that teaches something resets it.
TRAIN_FAILED = frozenset({"error", "unchanged"})
TRAIN_BACKOFF_CAP_MINUTES = 12 * 60

# NO TRADE BEFORE THIS LEVEL (#766). A player picks up a trade after leaving
# the starting area, and a level 1 walked to a capital's trainer dies on the
# way. Herbalism and mining already ask level 5 of their first rank; skinning
# asks none, and this is what keeps a level 1 skinner at home.
TRAIN_MIN_LEVEL = 5

# A member is at its field or its door within these many yards. The field is
# where it gathers, so it is left there while it stays inside; the door is a
# stone it farms around.
FIELD_REACH = 400.0
DOOR_REACH = 500.0

# A door's meeting stone is the one nearest its entrance within this many
# yards. Measured 2026-09-24: 25 yards at Ragefire Chasm, 846 at Dire Maul.
STONE_YARDS = 900.0

# New steps one guild starts in one pass.
STEPS_PER_GUILD = 4

# The command log's `source` for every row this pass writes.
SOURCE = "guildjobs"


def source_for(action, name) -> str:
    return "%s:%s:%s" % (SOURCE, action, name)


def action_of(source) -> str:
    """The action word of one of this pass's sources, "" for any other row."""
    parts = str(source or "").split(":")
    return parts[1] if len(parts) >= 3 and parts[0] == SOURCE else ""


# WHAT A WORLDSERVER OLDER THAN quadseven/mod-overseer#707 ANSWERS. It routes
# a spawn walk to the roster's job modes, and refuses `any` as a vendor walk.
UNKNOWN_JOB_MODE = "unknown job mode"
MALFORMED_VENDOR_WALK = "malformed walk-to-vendor command"


def unsupported_walk(kind, command, detail) -> str:
    """ "spawn" or "sale" when this answer says the worldserver does not carry
    that walk, "" otherwise."""
    command, detail = str(command or ""), str(detail or "")
    if (
        kind == "job"
        and command.startswith("walk-to-spawn")
        and UNKNOWN_JOB_MODE in detail
    ):
        return "spawn"
    if (
        kind == "buy"
        and command.startswith("walk-to-vendor any")
        and MALFORMED_VENDOR_WALK in detail
    ):
        return "sale"
    return ""


# ---------------------------------------------------------------------------
# THE FACTS.


@dataclass(frozen=True)
class Carried:
    """One stack a member carries (backpack and worn bags, never the bank)."""

    guid: int
    entry: int
    count: int = 1
    item_class: int = 0
    subclass: int = 0
    quality: int = 1
    sell_price: int = 0
    name: str = ""
    item_level: int = 0

    @property
    def material(self) -> str:
        if self.item_class != TRADE_GOODS:
            return ""
        return MATERIAL_SUBCLASSES.get(int(self.subclass), "")

    @property
    def junk(self) -> bool:
        return self.quality == JUNK_QUALITY and self.sell_price > 0

    def outgrown(self, level) -> bool:
        """A white weapon or armor piece this far under `level` (OUTGROWN_LEVELS)."""
        if self.quality != WHITE_QUALITY or self.sell_price <= 0:
            return False
        if self.item_class == WEAPON:
            fits = int(self.subclass) not in TOOL_WEAPON_SUBCLASSES
        elif self.item_class == ARMOR:
            fits = int(self.subclass) in WORN_ARMOR_SUBCLASSES
        else:
            return False
        return fits and 0 < int(self.item_level) <= int(level) - OUTGROWN_LEVELS

    def sellable(self, level) -> bool:
        """Grey, or outgrown white gear: what goes over the counter."""
        return self.junk or self.outgrown(level)


@dataclass(frozen=True)
class Member:
    """One guild member as the bridge read it."""

    name: str
    guild: str
    role: str
    level: int = 0
    class_id: int = 0
    race: int = 0
    online: bool = False
    in_combat: bool = False
    map_id: int | None = None
    x: float | None = None
    y: float | None = None
    # The snapshot's zone, None when no fresh snapshot was read.
    zone_id: int | None = None
    money: int = 0
    skills: dict = field(default_factory=dict)  # skill -> (value, max)
    known: frozenset = frozenset()
    carried: tuple = ()  # Carried
    eligible: bool = False
    # The class quests in the log (quest id -> status 1 or 3) and the quest
    # ids it was rewarded (classquest.py).
    quest_log: dict = field(default_factory=dict)
    quests_done: frozenset = frozenset()
    # Kills and items counted toward each logged quest (quest id -> total).
    quest_progress: dict = field(default_factory=dict)
    # The talent tree played ("Protection", "Holy"), "" when unread or a tie.
    tree: str = ""
    # False for a dead member or a ghost; a dead member is walked nowhere.
    alive: bool = True

    def skill(self, skill_id) -> tuple:
        value, cap = self.skills.get(int(skill_id), (0, 0))
        return int(value or 0), int(cap or 0)

    def holds(self, skill_id) -> bool:
        return self.skill(skill_id)[1] > 0

    def carries(self, entry) -> bool:
        return any(int(c.entry) == int(entry) for c in self.carried)

    def count(self, entry) -> int:
        return sum(int(c.count) for c in self.carried if int(c.entry) == int(entry))

    @property
    def primaries(self) -> tuple:
        return tuple(
            sorted(s for s in self.skills if s in PRIMARY_SKILLS and self.holds(s))
        )


@dataclass(frozen=True)
class Spot:
    """A place a member is sent to: a spawn row of the world, by id."""

    kind: str  # "gameobject" or "creature"
    spawn: int
    map_id: int
    x: float
    y: float
    name: str = ""
    why: str = ""

    @property
    def command(self) -> str:
        return "walk-to-spawn %s:%d" % (self.kind, int(self.spawn))


@dataclass(frozen=True)
class Door:
    """A dungeon door a warlock serves, and its meeting stone."""

    keyword: str
    place: str
    floor: int
    ceiling: int
    stone: Spot | None = None


@dataclass(frozen=True)
class Recent:
    """One of this pass's recent rows: who, which action, how long ago."""

    name: str
    action: str
    age_minutes: int
    status: str = ""
    skill_id: int | None = None
    # Whether the row is the step's walk (its source ends "-walk").
    walk: bool = False
    # Why the module refused the row, "" when it did not, and whether it said
    # the refusal would pass (the realm's far walk walls, a dead character).
    refusal: str = ""
    retryable: bool = False


@dataclass(frozen=True)
class JobsPlan:
    steps: tuple = ()
    lines: dict = field(default_factory=dict)  # name -> what it does now
    trades: dict = field(default_factory=dict)  # name -> (skill, skill)
    doors: dict = field(default_factory=dict)  # name -> Door
    notes: tuple = ()
    # guild -> {"focus", "members", "craft", "farm", "gathering"} (GUILD_FOCUS)
    focus: dict = field(default_factory=dict)
    # classquest.Help: class quests a guildmate could help with (classask.py).
    helps: tuple = ()


def _yards(ax, ay, bx, by) -> float:
    return math.hypot(float(ax) - float(bx), float(ay) - float(by))


def _near(member: Member, spot: Spot, reach: float) -> bool:
    if member.map_id is None or member.x is None or member.y is None:
        return False
    if int(member.map_id) != int(spot.map_id):
        return False
    return _yards(member.x, member.y, spot.x, spot.y) <= reach


def _cap_word(cap) -> str:
    return guildroute.errand_cap_word(cap)


def _cooling(member: Member, action: str, recent) -> bool:
    minutes = COOLDOWN_MINUTES.get(action, 60)
    if action == "train":
        minutes = train_cooldown(member.name, recent)
    elif action == "gear" and not last_gear_failed(member.name, recent):
        minutes = GEAR_SUCCESS_COOLDOWN_MINUTES
    return any(
        r.name == member.name and r.action == action and int(r.age_minutes) < minutes
        for r in recent or ()
    )


def train_cooldown(name: str, recent, skill_id: int | None = None) -> int:
    """Minutes to wait after failed trainer rows for this skill.

    Rows without a skill id predate skill-scoped cooldowns and remain
    character-wide so older facts and callers preserve their prior behavior.
    """
    rows = sorted(
        (
            r
            for r in recent or ()
            if r.name == name
            and r.action == "train"
            and (skill_id is None or r.skill_id is None or r.skill_id == skill_id)
        ),
        key=lambda r: int(r.age_minutes),
    )
    failed = 0
    for r in rows:
        if r.status not in TRAIN_FAILED:
            break
        failed += 1
    base = COOLDOWN_MINUTES["train"]
    return min(base * 2**failed, max(base, TRAIN_BACKOFF_CAP_MINUTES))


def _training_cooling(name: str, skill_id: int, recent) -> bool:
    rows = tuple(
        r
        for r in recent or ()
        if r.name == name
        and r.action == "train"
        and (r.skill_id is None or r.skill_id == skill_id)
    )
    minutes = train_cooldown(name, rows, skill_id)
    return any(int(r.age_minutes) < minutes for r in rows)


# ---------------------------------------------------------------------------
# A SKINNER'S FIELD.

# The core's own rule (Spell::CheckCast, SPELL_EFFECT_SKINNING): a creature of
# level L needs skinning (L - 10) * 10 below 100 skill and L * 5 from there.
# A skinner hunts beasts from SKIN_BELOW levels under itself to one over, and
# only as high as its skill can skin.
SKIN_BELOW = 6
SKIN_ABOVE = 1
# Spawns are grouped in cells this wide; the densest cell nearest the skinner
# wins, in thousand-yard steps, like gatheraim.near_fields.
SKIN_CELL = 250.0
# How far a skinner is sent for beasts, and how many make a field.
SKIN_YARDS = 3000.0
SKIN_MIN_SPAWNS = 4


def skinnable_level(value) -> int:
    """The highest creature level this skinning value can skin; 0 unlearned."""
    value = _int(value)
    if value <= 0:
        return 0
    return value // 10 + 10 if value < 100 else value // 5


def skin_band(level, value) -> tuple:
    """(lowest, highest) creature level a skinner of this level and skill
    hunts; highest below lowest means nothing fits."""
    level = _int(level)
    return max(1, level - SKIN_BELOW), min(level + SKIN_ABOVE, skinnable_level(value))


def _densest_field(mobs, origin, low, high, name, noun) -> Spot | None:
    """The spawn a farmer is sent to among `mobs`, or None.

    `mobs` are (Spot, level) for creature spawns on its map; `origin` its
    (x, y). The spawns in levels `low` to `high` are grouped into SKIN_CELL
    cells; of the cells with SKIN_MIN_SPAWNS or more within SKIN_YARDS, the
    nearest (in thousand-yard steps) and then the densest wins, and the spawn
    sent to is the real one nearest that cell's middle.
    """
    if high < low or origin is None:
        return None
    cells = {}
    for spot, mob_level in mobs or ():
        if not low <= _int(mob_level) <= high:
            continue
        if _yards(spot.x, spot.y, origin[0], origin[1]) > SKIN_YARDS:
            continue
        key = (int(spot.x // SKIN_CELL), int(spot.y // SKIN_CELL))
        cells.setdefault(key, []).append(spot)
    best = None
    for key, spots in cells.items():
        if len(spots) < SKIN_MIN_SPAWNS:
            continue
        cx = sum(s.x for s in spots) / len(spots)
        cy = sum(s.y for s in spots) / len(spots)
        central = min(spots, key=lambda s: ((s.x - cx) ** 2 + (s.y - cy) ** 2, s.spawn))
        rank = (int(_yards(cx, cy, origin[0], origin[1]) // 1000), -len(spots), key)
        if best is None or rank < best[0]:
            best = (rank, central, len(spots))
    if best is None:
        return None
    _rank, spot, count = best
    return Spot(
        kind="creature",
        spawn=spot.spawn,
        map_id=spot.map_id,
        x=spot.x,
        y=spot.y,
        name=spot.name or name,
        why="%d %s of levels %d to %d" % (count, noun, low, high),
    )


def skinning_field(beasts, origin, level, value) -> Spot | None:
    """The beast spawn a skinner is sent to, or None (see `_densest_field`)."""
    low, high = skin_band(level, value)
    return _densest_field(
        beasts, origin, low, high, "a pack of beasts", "skinnable beasts"
    )


# THE CLOTH FIELD (2026-10-06). The guild's master tailor is the bag maker, and
# Linen Cloth is its bottleneck: the crew's farm jobs were mining, herbalism and
# skinning, and the humanoid mobs that drop cloth were nobody's. A crew tailor
# (or a member with no field of its own) is sent to the densest pack of
# humanoids that carry cloth in their loot table and that it can fight, with the
# same `walk-to-spawn creature:` the skinner's beast field uses; the module's
# own grind strategy kills and loots there. What it loots reaches the master by
# the corps' supply letters and by `post`, as before. The cloth entries are the
# bolts' reagents (guildcorps.BOLTS, read off the realm's Spell.dbc), never a
# second list. The band is a skinner's: SKIN_BELOW levels under the member to
# one over.
CLOTH_ENTRIES = tuple(
    int(bolt.reagents[0][0])
    for bolt in guildcorps.BOLTS
    if all(classic.item_ok(int(e)) for e, _n in bolt.reagents)
)


def cloth_band(level) -> tuple:
    """(lowest, highest) creature level a cloth farmer of this level hunts."""
    level = _int(level)
    return max(1, level - SKIN_BELOW), level + SKIN_ABOVE


def farms_cloth(member, has_field) -> bool:
    """Whether this member's field is the cloth field: a crew tailor, whose
    trade eats cloth and whose master wants it, or anyone with no other field."""
    return member.holds(TAILORING) or not has_field


def cloth_field(mobs, origin, level) -> Spot | None:
    """The humanoid spawn a cloth farmer is sent to, or None.

    `mobs` are (Spot, level) for the world's creature spawns whose loot holds
    cloth (`CLOTH_ENTRIES`), already limited to the farmer's map.
    """
    low, high = cloth_band(level)
    return _densest_field(
        mobs, origin, low, high, "a pack of humanoids", "cloth-dropping humanoids"
    )


# ---------------------------------------------------------------------------
# THE TRADE SPLIT.


def choose_tailors(members) -> frozenset:
    """The maintenance members that take Tailoring, per guild.

    One in TAILOR_EVERY of a crew, so a crew under three has none. A member
    that already holds Tailoring comes first, then the ones with a primary
    slot to spare, the fewest primaries first and by name.
    """
    crews = {}
    for m in members or ():
        if m.role == MAINTENANCE:
            crews.setdefault(m.guild, []).append(m)
    out = set()
    for _guild, crew in sorted(crews.items()):
        room = [m for m in crew if m.holds(TAILORING) or len(m.primaries) < MAX_PRIMARY]
        room.sort(key=lambda m: (not m.holds(TAILORING), len(m.primaries), m.name))
        out.update(m.name for m in room[: len(crew) // TAILOR_EVERY])
    return frozenset(out)


def split_trades(members, tailors=frozenset()) -> dict:
    """name -> (skill, skill): the two gathering trades each maintenance
    member works, per guild. See TRADE SPLIT in the module docstring. A member
    in `tailors` keeps one primary slot for Tailoring, so it gets one."""
    out = {}
    crews = {}
    for m in members or ():
        if m.role == MAINTENANCE:
            crews.setdefault(m.guild, []).append(m)
    for _guild, crew in sorted(crews.items()):
        crew = sorted(crew, key=lambda m: m.name)
        # What the crew already holds is counted first, so a member who
        # learned a trade on its own keeps it and the split fills round it.
        counts = {s: sum(1 for m in crew if m.holds(s)) for s in GATHERING}
        for m in crew:
            out[m.name] = _fill_gathering(m, counts, m.name in tailors)
    return out


def _fill_gathering(m, counts, tailor) -> tuple:
    """The gathering trades one member works: what it holds, then the trade the
    crew has fewest of while a primary slot is left (a tailor keeps one back)."""
    wanted = [s for s in GATHERING if m.holds(s)]
    others = [s for s in m.primaries if s not in GATHERING]
    reserved = 1 if tailor and not m.holds(TAILORING) else 0
    room = max(0, MAX_PRIMARY - len(wanted) - len(others) - reserved)
    while room > 0:
        free = [s for s in GATHERING if s not in wanted]
        if not free:
            break
        pick = min(free, key=lambda s: (counts[s], GATHERING.index(s)))
        wanted.append(pick)
        counts[pick] += 1
        room -= 1
    return tuple(wanted)


def cloth_trades(trades, tailors) -> dict:
    """`split_trades` with the cloth trades added: Tailoring for a tailor and
    First Aid, which takes no primary slot, for every maintenance member."""
    return {
        name: tuple(gathering)
        + ((TAILORING,) if name in tailors else ())
        + (FIRST_AID,)
        for name, gathering in (trades or {}).items()
    }


def next_rank(skill: int, value: int, cap: int, level: int):
    """The rank this member should buy next, or None.

    An unlearned trade (cap 0) wants its first rank. A learned one wants the
    rank above its ceiling once its value is within RANK_UP_MARGIN of the
    ceiling and its level and value meet the rank's asks.
    """
    ranks = RANKS.get(int(skill), ())
    if not ranks:
        return None
    if cap <= 0:
        first = ranks[0]
        return first if level >= first.level else None
    if value < cap - RANK_UP_MARGIN:
        return None
    for rank in ranks:
        if rank.cap > cap:
            if level >= rank.level and value >= rank.needs:
                return rank
            return None
    return None


def ranks_due(level: int, money: int, skills, wanted=()) -> tuple:
    """The held trades whose next rank this character may buy now, cheapest first.

    The crew's own rule (`next_rank`, and the purse check `_train_step`
    makes), for a character a trainer walk is not written for: a roster
    family member, whose rank is bought on arrival at a trainer through
    `overseer_roster.learn_skill` (learnaim.py). `skills` is
    {skill id: (value, max)}. Only a HELD trade is asked about (max above 0),
    so this never starts a trade; a primary only when `wanted` (the roster's
    `professions` column, the permission TrainOnArrival reads) names it, and
    First Aid always, since it takes no primary slot.
    """
    due = []
    for skill, (value, ceiling) in sorted((skills or {}).items()):
        skill, value, ceiling = int(skill), int(value or 0), int(ceiling or 0)
        if ceiling <= 0:
            continue
        if skill != FIRST_AID and skill not in tuple(wanted or ()):
            continue
        rank = next_rank(skill, value, ceiling, int(level or 0))
        if rank is not None and int(money or 0) >= rank.cost:
            due.append((rank.cost, skill))
    return tuple(skill for _cost, skill in sorted(due))


# ---------------------------------------------------------------------------
# THE STEPS.


def _train_step(member, trades, cap, recent=()):
    """Buy the next rank of one of its trades, the cheapest first."""
    if member.level < TRAIN_MIN_LEVEL and trades.get(member.name):
        return None, "%s learns a trade from level %d" % (member.name, TRAIN_MIN_LEVEL)
    wants, cooling = [], []
    held = tuple(trades.get(member.name, ()))
    held += tuple(s for s in RANKED_CRAFTS if member.holds(s) and s not in held)
    for skill in held:
        value, ceiling = member.skill(skill)
        rank = next_rank(skill, value, ceiling, member.level)
        if rank is not None:
            if _training_cooling(member.name, skill, recent):
                cooling.append(skill)
            else:
                wants.append((rank.cost, skill, rank))
    if not wants:
        if cooling:
            return None, "%s waits to retry %s after a failed trainer walk" % (
                member.name,
                ", ".join(SKILL_NAMES[s] for s in cooling),
            )
        return None, ""
    cost, skill, rank = min(wants)
    if member.money < cost:
        return None, "%s saves for %s (%dc, it carries %dc)" % (
            member.name,
            SKILL_NAMES[skill],
            cost,
            member.money,
        )
    first = not member.holds(skill)
    step = guildcorps.Step(
        member.name,
        "train",
        skill,
        "%s walks to a trainer to %s %s (up to %d, %dc)"
        % (
            member.name,
            "learn" if first else "train",
            SKILL_NAMES[skill],
            rank.cap,
            cost,
        ),
        rows=(
            guildcorps.Row(
                "cast",
                "walk-to-trainer skill:%d%s" % (skill, _cap_word(cap)),
                "",
                source_for("train", member.name),
            ),
        ),
    )
    return step, ""


# The crafting trades whose rungs above the auto-learned first are trainer
# purchases a crew member walks to buy: First Aid's bandages, and (2026-10-05)
# the Leatherworking and Alchemy ladders, every rung of which the realm's
# trainers teach (craft.py's two ladder blocks). Tailoring is left to
# guildcorps, which buys its own recipes.
LEARNED_SKILLS = (FIRST_AID, LEATHERWORKING, ALCHEMY)


def recipe_to_learn(member, skill):
    """The rung of `skill` this member's value has reached and not bought, or None.

    Every rung above the first is a trainer purchase (craft.py's ladder
    comments), and `_open_recipe` casts only what `member.known` holds, so
    without this a crew member walked off its auto-learned rung and stopped.
    """
    if skill not in LEARNED_SKILLS:
        return None
    value, ceiling = member.skill(skill)
    if ceiling <= 0:
        return None
    recipe = craft.recipe_for(skill, value)
    if recipe is None or recipe.focus:
        return None
    if recipe.spell_id in AUTO_LEARNED or recipe.spell_id in member.known:
        return None
    return recipe


def bandage_to_learn(member):
    """The First Aid rung this member's skill has reached and not bought, or None."""
    return recipe_to_learn(member, FIRST_AID)


def _learn_step(member, cap, recent=()):
    """Walk to a trainer and buy the rung a held crafting trade has reached.

    The same `walk-to-trainer` row guildcorps sends a tailor with, carrying a
    `learn:` list: mod-overseer buys each listed spell through the core's own
    Trainer::TeachSpell, which takes the money and refuses a spell the skill
    is short of. Keyed on the skill so a failed walk cools down like a rank.
    """
    for skill in LEARNED_SKILLS:
        recipe = recipe_to_learn(member, skill)
        if recipe is None or _training_cooling(member.name, skill, recent):
            continue
        return guildcorps.Step(
            member.name,
            "train",
            skill,
            "%s walks to a trainer to learn %s for its %s"
            % (member.name, recipe.name, SKILL_NAMES[skill]),
            rows=(
                guildcorps.Row(
                    "cast",
                    "walk-to-trainer skill:%d learn:%d%s"
                    % (skill, recipe.spell_id, _cap_word(cap)),
                    "",
                    source_for("train", member.name),
                ),
            ),
        )
    return None


def _open_recipe(member, skill):
    """The recipe this member would cast toward `skill`, materials in hand or not.

    It is the one craft.py keeps for the member's skill value (its colour
    band), with a gathered reagent craft_rhythm names: a recipe that needs a
    forge, an anvil or a loom is left to the passes that walk there, and one
    made of crafted intermediates only is left alone. None at the ceiling,
    where a rank comes first.
    """
    value, ceiling = member.skill(skill)
    if ceiling <= 0 or value >= ceiling:
        return None
    recipe = craft.recipe_for(skill, value)
    if recipe is None or recipe.focus:
        return None
    if recipe.spell_id not in AUTO_LEARNED and recipe.spell_id not in member.known:
        return None
    return recipe if craft_rhythm.GATHERED.get(recipe.spell_id) else None


def bought_reagents(spell_id) -> tuple:
    """(entry, per cast) of the vendor reagents a recipe also eats.

    craft_rhythm.GATHERED is the gathered half of a recipe and craft_supply
    the bought half (a vial, a thread, a flux). A cast is asked only when the
    member carries both halves; buying the bought half is craft_supply's walk,
    not this one.
    """
    out = [
        (int(e), int(n))
        for e, _name, _price, n in craft_supply.REAGENTS.get(int(spell_id), ())
    ]
    single = craft_supply.REAGENT.get(int(spell_id))
    if single is not None and all(e != int(single[0]) for e, _n in out):
        out.append((int(single[0]), 1))
    return tuple(out)


def _weave_recipe(member, skill, spell):
    """(recipe, casts) of the earlier rung `spell` of `skill` when this member
    holds it and its materials, else (None, 0)."""
    recipe = next(
        (r for r in craft.RECIPES.get(skill, ()) if r.spell_id == spell), None
    )
    if recipe is None or recipe.focus:
        return None, 0
    if recipe.spell_id not in AUTO_LEARNED and recipe.spell_id not in member.known:
        return None, 0
    needs = [
        (int(r.entry), int(r.per_cast)) for r in craft_rhythm.GATHERED.get(spell, ())
    ] + list(bought_reagents(spell))
    if not needs:
        return None, 0
    casts = min(member.count(entry) // max(1, n) for entry, n in needs)
    return (recipe, min(casts, CRAFT_BATCH)) if casts > 0 else (None, 0)


def _craft_recipe(member, skill):
    """(recipe, casts) this member can cast now toward `skill`, or (None, 0)."""
    recipe = _open_recipe(member, skill)
    if recipe is None:
        return None, 0
    fed = craft_rhythm.BOLT_FED.get(recipe.spell_id)
    if fed is not None and member.count(fed[1].entry) < fed[1].per_cast:
        # The rung eats its own earlier output (a Cured Heavy Hide, a Minor
        # Healing Potion): cast that first, as craft_rhythm.errand does.
        return _weave_recipe(member, skill, fed[0])
    needs = [
        (int(r.entry), int(r.per_cast)) for r in craft_rhythm.GATHERED[recipe.spell_id]
    ] + list(bought_reagents(recipe.spell_id))
    casts = min(member.count(entry) // max(1, n) for entry, n in needs)
    return (recipe, min(casts, CRAFT_BATCH)) if casts > 0 else (None, 0)


def craft_entries(member) -> frozenset:
    """The gathered items this member's next casts eat, which it keeps."""
    out = set()
    for skill in CRAFT_SKILLS:
        recipe = _open_recipe(member, skill)
        if recipe is not None:
            out.update(int(r.entry) for r in craft_rhythm.GATHERED[recipe.spell_id])
            fed = craft_rhythm.BOLT_FED.get(recipe.spell_id)
            if fed is not None:
                # What the rung eats of its own earlier output, and what that
                # earlier cast eats, stay in the bags too.
                out.add(int(fed[1].entry))
                out.update(int(r.entry) for r in craft_rhythm.GATHERED.get(fed[0], ()))
    return frozenset(out)


def _craft_step(member):
    """Cast what its bags allow, to raise one of its crafting trades (#421).

    Every crafting trade craft.RECIPES covers, First Aid first: Linen Bandage
    takes a Linen Cloth, Bolt of Linen Cloth two, Light Leather three Ruined
    Leather Scraps, Rough Sharpening Stone a Rough Stone. Each grants skill to
    the cast and each is the member's own to make, where it stands. The rows
    are `cast` rows, the verb a player has, and the trade came from a trainer
    that was paid.
    """
    for skill in CRAFT_SKILLS:
        recipe, casts = _craft_recipe(member, skill)
        if recipe is None:
            continue
        return guildcorps.Step(
            member.name,
            "craft",
            recipe.spell_id,
            "%s crafts %d %s to raise its %s"
            % (member.name, casts, recipe.name, SKILL_NAMES.get(skill, skill)),
            rows=(
                guildcorps.Row(
                    "cast",
                    str(recipe.spell_id),
                    "",
                    source_for("craft", member.name),
                ),
            ),
            repeat=casts,
        )
    return None


def _tool_step(member, cap):
    """Buy the tool a held trade cannot work without."""
    for skill in (MINING, SKINNING):
        if not member.holds(skill):
            continue
        entry, name, price = TOOLS[skill]
        if any(member.carries(tool) for tool in TOOL_ENTRIES[skill]):
            continue
        if member.money < price:
            return None, "%s saves for a %s (%dc)" % (member.name, name, price)
        step = guildcorps.Step(
            member.name,
            "tool",
            entry,
            "%s walks to a vendor to buy a %s for its %s"
            % (member.name, name, SKILL_NAMES[skill]),
            rows=(
                guildcorps.Row(
                    "buy",
                    "entry:%d count:1 max:%d" % (entry, price * 2),
                    "",
                    source_for("tool", member.name),
                ),
            ),
            walk=guildcorps.Row(
                "buy",
                "walk-to-vendor item:%d%s" % (entry, _cap_word(cap)),
                "",
                source_for("tool-walk", member.name),
            ),
        )
        return step, ""
    return None, ""


# A GEAR-SHORT MEMBER BUYS WHITES OFF A COUNTER WITH ITS OWN GOLD. On wow-dev
# on 2026-10-03, 113 of 142 guild members wore gear more than six item levels
# under their own level, most of them in five to eight of seventeen slots, so
# guildrun's gear gate kept every guild group out of the dungeons that would
# have geared them. Nothing walked a guild member to a vendor: the family's
# gear errand (gearup) is the family's. This is that errand for one member: the
# vendor gearup.vendor_trip picks from the stock in reach, then every piece
# gearup.plan_vendor_buys would buy there, up to GEAR_BUYS_PER_STEP. A piece
# lands in the bags and the bot's own equip upgrade puts it on.
GEAR_BUYS_PER_STEP = 6

# GEAR HAS ITS OWN ALLOWANCE PER GUILD PER PASS, beside STEPS_PER_GUILD. Measured
# on wow-dev 2026-10-04: the job pass started 4 steps per guild every 15
# minutes, gear steps among the posts, sales and training, and in 8 hours 24
# members got 31 pieces while 119 stayed under guildrun's gear gate. No guild
# group can run until the gate opens, so gear does not queue behind the rest.
GEAR_STEPS_PER_GUILD = 6
# A gear step that bought something may follow on the next pass; only a failed
# one waits the full COOLDOWN_MINUTES["gear"].
GEAR_SUCCESS_COOLDOWN_MINUTES = 15

# How far a guild member may be sent for gear. Wider than the family's
# VENDOR_TRIP_MAX_YARDS because a guild walk that cannot go straight goes by
# the travel survey (quadseven/mod-overseer#830).
GUILD_GEAR_VENDOR_YARDS = 1500.0


# The lowest level a guild group may enter any door at (Ragefire Chasm and
# the Deadmines' floors, guildrun.LEVEL_MARGIN 0). A member below it fits no
# door yet, so gear that lifts it over guildrun's gate seats nobody today.
GUILD_DOOR_FLOOR = 15


def shield_aware(member, character):
    """`character` with `shield_carried` set when the member holds a shield in
    its bags: the module's equip drive wears that one, so none is bought."""
    if not character or not character.get("shield_tank"):
        return character
    carried = any(
        int(c.item_class) == ARMOR and int(c.subclass) == 6
        for c in (member.carried or ())
    )
    return dict(character, shield_carried=carried)


def gear_reads(members, facts, offsets, limit):
    """(names to read this pass, next offsets) for the guild gear step.

    `members` are the candidates (natural, online, out of combat, placed, off
    the gear cooldown) and `facts` their gearup facts by name. A member is
    needy when it is short of gear or wears stale gear; the needy are read
    door-fitting first (tiered_reads).
    """
    needy = [
        m
        for m in members
        if facts.get(m.name) and _gear_wanted(shield_aware(m, facts[m.name]))
    ]
    doorable = [m.name for m in needy if m.level >= GUILD_DOOR_FLOOR]
    others = [m.name for m in needy if m.level < GUILD_DOOR_FLOOR]
    return tiered_reads(doorable, others, offsets, limit)


def _gear_wanted(character) -> bool:
    return (
        gearup.gear_short(character)
        or gearup.stale_gear(character)
        or gearup.shield_short(character)
    )


def tiered_reads(doorable, others, offsets, limit):
    """(names to read, next offsets): members who fit a door first.

    On wow-dev on 2026-10-04 the gate passed 12 members at levels 10 to 14,
    who fit no door, and 4 at 15 to 19, while 67 members at 15 to 19 waited
    their turn behind them. `doorable` rotate among themselves for every read
    they can fill; the reads left over rotate through `others`. `offsets` is
    (doorable offset, others offset).
    """
    first, next_first = rotate_reads(doorable, offsets[0], limit)
    rest_limit = max(0, limit - len(first))
    rest, next_rest = rotate_reads(others, offsets[1], rest_limit)
    return first + rest, (next_first, next_rest if rest else offsets[1])


def rotate_reads(names, offset, limit):
    """(the names to read this pass, the offset for the next pass).

    The vendor stock reads are bounded per pass. Taken from the front of the
    list every time, the same members held every slot: a member with no
    vendor in reach is never given a step, so it never cools down, and on
    wow-dev on 2026-10-03 the same three filled the pass while over a hundred
    stale members were never looked at. A rolling window reaches all of them.
    """
    names = list(names)
    if not names or limit <= 0:
        return [], 0
    if len(names) <= limit:
        return names, 0
    start = offset % len(names)
    chosen = (names[start:] + names[:start])[:limit]
    return chosen, (start + limit) % len(names)


def friendly_vendor_rows(member, vendor_rows) -> list:
    """The rows of vendors whose faction will deal with this member.

    The module walks only to a vendor whose faction lets it serve the
    character, and refuses the row otherwise ("no vendor on this map sells
    that item to this character"). On wow-dev on 2026-10-03 an Alliance
    member's first guild gear walk named Varia Hardhide, whose faction is
    hostile to the Alliance. A row whose faction template is unread
    (`enemy_group` None; the dbc table is partial) is kept for the module to
    judge.
    """
    side = situation.side_mask([member.race])
    return [
        r
        for r in vendor_rows or ()
        if situation.hostile(r.get("enemy_group"), side) is not True
    ]


def junk_sales(member, kept) -> tuple:
    """The sell rows a gear step opens with: room first.

    The junk the member carries is sold at the same counter before the buys.
    On wow-dev on 2026-10-04 three of four guild members who reached their
    vendor were refused every piece with "bags cannot take the item". Never a
    stack reserved in overseer_keep, and at most MAX_SALES.
    """
    junk = sorted(
        (
            c
            for c in (member.carried or ())
            if c.sellable(member.level) and not _kept(member.name, c, kept)
        ),
        key=lambda c: (-int(c.sell_price) * int(c.count), int(c.guid)),
    )[:MAX_SALES]
    return tuple(
        guildcorps.Row(
            "sell", "guid:%d" % int(c.guid), "", source_for("gear", member.name)
        )
        for c in junk
    )


def gear_step(member, character, vendor_rows, cap, kept=None):
    """(step or None, why not) for one gear-short member.

    `character` is the member's gearup facts (class, level, purse, equipped,
    skills) and `vendor_rows` the vendor stock in reach of where it stands,
    the rows gearup.vendor_trip reads. The walk names the first piece's
    entry, and the module walks to the nearest friendly vendor that stocks it.
    """
    character = shield_aware(member, character)
    if not character or not _gear_wanted(character):
        return None, ""
    if member.map_id is None:
        return None, "%s is short of gear; where it stands is not read" % member.name
    vendor_rows = friendly_vendor_rows(member, vendor_rows)
    trip = gearup.vendor_trip(
        {member.name: character},
        vendor_rows,
        map_id=member.map_id,
        max_yards=GUILD_GEAR_VENDOR_YARDS,
        replace_stale=True,
    )
    if not trip.vendor:
        return None, "%s is short of gear: %s" % (member.name, trip.why_not)
    stock = gearup.stock_of(vendor_rows, trip.vendor)
    offers = [
        r
        for r in vendor_rows
        if int(r.get("vendor") or 0) == trip.vendor
        and int(r.get("entry") or 0) in stock
    ]
    buys = gearup.plan_vendor_buys(
        {member.name: character}, {member.name: offers}, replace_stale=True
    )
    buys = buys[:GEAR_BUYS_PER_STEP]
    if not buys:
        return (
            None,
            "%s is short of gear and %s sells it nothing it can wear and afford"
            % (member.name, trip.name),
        )
    said = "%s walks to %s to buy %d piece(s) for empty slots: %s" % (
        member.name,
        trip.name,
        len(buys),
        ", ".join(b.slot for b in buys),
    )
    sales = junk_sales(member, kept)
    step = guildcorps.Step(
        member.name,
        "gear",
        buys[0].entry,
        said,
        rows=sales
        + tuple(
            guildcorps.Row(
                "buy", gearup.vendor_command(b), "", source_for("gear", member.name)
            )
            for b in buys
        ),
        walk=guildcorps.Row(
            "buy",
            "walk-to-vendor item:%d%s" % (buys[0].entry, _cap_word(cap)),
            "",
            source_for("gear", member.name),
        ),
    )
    return step, ""


# A CRAFTER IS POSTED ONLY WHAT IT CAN WORK NOW (#373). Holding a trade is not
# enough: on wow-dev on 2026-09-27 all ten family members held Cooking at 1,
# so "the best cook" was a name tiebreak, and Bork was posted 1,190 items of
# meat across 64 letters he never opened. A holder qualifies when its skill is
# at least CRAFTER_FLOOR and a recipe it can cast at that skill consumes the
# item (craft.RECIPES, reagents from craft_rhythm.GATHERED). Anything else goes
# to the guild bank's Materials tab.
CRAFTER_FLOOR = 5

# The subject every post carries, which is also how an unopened one is found.
POST_SUBJECT = "Guild materials"

# A mailbox this full refuses the next letter: the core caps an inbox at 100
# ("recipient mailbox is full"). On wow-dev on 2026-10-04, 46 of 47 material
# posts in a day bounced off Grug, who held 113 letters already emptied but
# never deleted, because only an unopened post counted as waiting. A holder
# this full is treated as one with a post waiting: nothing more is sent to it.
MAILBOX_FULL_LETTERS = 95


def _bag_inputs(skill: int, value: int) -> frozenset:
    """The non-bolt, non-vendor reagents of the trainer bags a master tailor is
    within reach of: Small Silk Pack's Heavy Leather. A bag is a recipe of
    craft.BAG_RECIPES, not craft.RECIPES, so `consumes_at` reads it here."""
    if int(skill) != TAILORING:
        return frozenset()
    reach = int(value) + guildcorps.LADDER_AHEAD
    return frozenset(
        int(entry)
        for bag in guildcorps.BAGS
        if bag.source == "trainer"
        and guildcorps._classic(bag)
        and bag.learn_rank <= reach
        for entry, _need in bag.reagents
        if not guildcorps._vendor_reagent(entry)
        and int(entry) not in guildcorps.BOLT_OF
    )


def consumes_at(skill: int, value: int, entry: int) -> bool:
    """Whether a recipe of `skill` castable at `value` eats item `entry`.

    A master tailor is read one bracket ahead (guildcorps.LADDER_AHEAD): the
    cloth and the leather its next rung and bag eat reach it before the cast.
    """
    if int(value) < CRAFTER_FLOOR:
        return False
    ahead = guildcorps.LADDER_AHEAD if int(skill) == TAILORING else 0
    if int(entry) in _bag_inputs(skill, value):
        return True
    for recipe in craft.RECIPES.get(int(skill), ()):
        if recipe.min_skill > int(value) + ahead:
            continue
        if any(
            r.entry == int(entry)
            for r in craft_rhythm.GATHERED.get(recipe.spell_id, ())
        ):
            return True
    return False


def without_unclaimed(crafters: dict, unclaimed) -> dict:
    """`crafters` less every holder with an unopened post waiting (#373).

    A crafter who has not collected earlier posts is sent nothing new until
    it does, so its pile cannot grow without limit; the material goes to the
    bank instead.
    """
    waiting = {str(n) for n in unclaimed or ()}
    if not waiting:
        return crafters
    return {
        guild: {
            skill: [p for p in holders if str(p[0]) not in waiting]
            for skill, holders in (skills or {}).items()
        }
        for guild, skills in (crafters or {}).items()
    }


def recipient_for(item: Carried, crafters: dict, master: str) -> tuple:
    """(who, why) a material goes to: the guild's crafter of the trade that
    uses it, when that crafter can work it now, else the guild master for the
    Materials tab.

    `crafters` maps a skill line to [(name, value)] of the family members of
    this guild who hold it.
    """
    for skill in CONSUMERS.get(int(item.subclass), ()):
        holders = sorted(
            (
                p
                for p in crafters.get(skill, ())
                if consumes_at(skill, p[1], item.entry)
            ),
            key=lambda p: (-int(p[1]), p[0]),
        )
        if holders:
            return holders[0][0], "its crafter"
    return master, "the guild bank's Materials tab"


def bank_masters(masters: dict, banks, unclaimed) -> dict:
    """guild -> the master a Materials-tab post may go to, or "" (#395).

    A POST FOR THE BANK NEEDS A BANK, AND A MASTER WHO EMPTIES HIS MAILBOX.
    On wow-dev 2026-09-28 Bonkers owned no bank tab (its first costs 100g and
    Zug held 0g), yet every Bonkers pass posted meat, eggs and linen to Zug
    "for the Materials tab": letters with nowhere to go. Cave's master Grug
    held 70 letters. So a guild with no tab posts nothing to its master, and
    a master with an unopened materials post waiting is sent no more until he
    collects it. The stack stays in its holder's bags, where the vendor pass
    sees it. `banks` None (unread) keeps the old answer.
    """
    waiting = {str(n) for n in unclaimed or ()}
    out = {}
    for guild, master in (masters or {}).items():
        master = str(master or "")
        if banks is not None and guild not in banks:
            master = ""
        if master in waiting:
            master = ""
        out[guild] = master
    return out


def postable(member: Member, kept, crafting=False) -> list:
    """The material stacks this member would post, biggest first.

    `crafting` is a member of a guild whose focus is craft (GUILD_FOCUS),
    which keeps what its casts eat the way a maintenance member does.
    """
    bar = POST_MIN.get(member.role, POST_MIN[RAIDER])
    # Materials its own next casts eat stay in the bags: a member that can
    # still raise a crafting trade does not post away what it would cast.
    eaten = (
        craft_entries(member) if member.role == MAINTENANCE or crafting else frozenset()
    )
    out = [
        c
        for c in member.carried
        if c.material
        and int(c.count) >= bar
        and int(c.entry) not in eaten
        and not _kept(member.name, c, kept)
    ]
    out.sort(key=lambda c: (-int(c.count), int(c.entry), int(c.guid)))
    return out


def _kept(name, item, kept) -> bool:
    """Is this stack reserved on its holder? `kept` is keep.py's Reservations,
    asked the way every disposal row is asked: by the item's guid and entry."""
    if kept is None:
        return False
    return keep.reserved(
        kept, name, "guid:%d entry:%d" % (int(item.guid), int(item.entry))
    )


def _post_step(member, crafters, master, kept, cap, crafting=False):
    stacks = postable(member, kept, crafting)[:MAX_LETTERS]
    if not stacks:
        return None, ""
    if member.money < POSTAGE_COPPER:
        return None, "%s cannot pay the postage for its materials yet" % member.name
    stacks = stacks[: max(1, member.money // POSTAGE_COPPER)]
    rows, said = [], []
    for c in stacks:
        who, why = recipient_for(c, crafters.get(member.guild, {}), master)
        if not who or who == member.name:
            continue
        rows.append(
            guildcorps.Row(
                "mail",
                "send item:%d subject:%s" % (int(c.guid), POST_SUBJECT),
                who,
                source_for("post", member.name),
            )
        )
        said.append("%d %s to %s (%s)" % (int(c.count), c.name or c.entry, who, why))
    if not rows:
        return None, ""
    step = guildcorps.Step(
        member.name,
        "post",
        int(stacks[0].entry),
        "%s walks to a mailbox to post %s" % (member.name, ", ".join(said)),
        rows=tuple(rows),
        walk=guildcorps.Row(
            "mail",
            guildroute.mailbox_walk_command(cap),
            "",
            source_for("post-walk", member.name),
        ),
    )
    return step, ""


def _sell_step(member, kept, cap):
    junk = [
        c
        for c in member.carried
        if c.sellable(member.level) and not _kept(member.name, c, kept)
    ]
    worth = sum(int(c.sell_price) * int(c.count) for c in junk)
    bar = SELL_MIN_STACKS.get(member.role, SELL_MIN_STACKS[RAIDER])
    if not junk or (len(junk) < bar and worth < SELL_MIN_COPPER):
        return None
    junk.sort(key=lambda c: (-int(c.sell_price) * int(c.count), int(c.guid)))
    junk = junk[:MAX_SALES]
    return guildcorps.Step(
        member.name,
        "sell",
        len(junk),
        "%s walks to a vendor to sell %d grey or outgrown stack(s) worth %dc"
        % (member.name, len(junk), sum(int(c.sell_price) * int(c.count) for c in junk)),
        rows=tuple(
            guildcorps.Row(
                "sell", "guid:%d" % int(c.guid), "", source_for("sell", member.name)
            )
            for c in junk
        ),
        walk=guildcorps.Row(
            "buy",
            "walk-to-vendor any%s" % _cap_word(cap),
            "",
            source_for("sell-walk", member.name),
        ),
    )


def _spot_step(member, spot, action, cap, said):
    return guildcorps.Step(
        member.name,
        action,
        int(spot.spawn),
        said,
        rows=(
            guildcorps.Row(
                "job",
                spot.command + _cap_word(cap),
                "",
                source_for(action, member.name),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# WHICH DOOR A WARLOCK SERVES.


@functools.lru_cache(maxsize=1)
def entrances() -> dict:
    """entrances.json, the committed dungeon doors: map id -> {map, x, y}."""
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "entrances.json"), encoding="utf-8") as f:
        return json.load(f)


def stone_for(keyword: str, entrances: dict, stones) -> Spot | None:
    """The meeting stone nearest the door's entrance, within STONE_YARDS.

    `entrances` is entrances.json (dungeon map id -> the entrance on its
    continent); `stones` are the world's meeting stone spawns as Spots.
    """
    map_id = dungeonpath.PORTAL_MAPS.get(keyword)
    door = (entrances or {}).get(str(map_id)) if map_id is not None else None
    if not door:
        return None
    best = None
    for stone in stones or ():
        if int(stone.map_id) != int(door.get("map", -1)):
            continue
        yards = _yards(stone.x, stone.y, door["x"], door["y"])
        if yards <= STONE_YARDS and (best is None or yards < best[0]):
            best = (yards, stone)
    return best[1] if best else None


def doors_for(member: Member) -> list:
    """The door keywords whose band fits this warlock, as a party of one."""
    row = {
        "name": member.name,
        "level": member.level,
        "race": member.race,
        "map_id": member.map_id,
        "lead": True,
    }
    out = []
    for run in campaignplan.RUNS:
        if member.level > run.ceiling:
            continue
        kind, _why = council.door_refusal_kind(run.keyword, [row])
        if kind:
            continue
        out.append(run)
    return out


def assign_doors(members, entrances, stones) -> dict:
    """name -> Door for every warlock with the ritual, spread over the doors
    that fit: the stone with the fewest warlocks first (the Dire Maul wings
    and the Scarlet Monastery wings share one stone each), then the lower
    band, then the keyword."""
    load = {}
    out = {}
    casters = [
        m
        for m in members or ()
        if m.role == SUMMONER and RITUAL_OF_SUMMONING in m.known
    ]
    casters.sort(key=lambda m: (-int(m.level), m.name))
    for m in casters:
        fits = []
        for run in doors_for(m):
            stone = stone_for(run.keyword, entrances, stones)
            if stone is None:
                continue
            fits.append((load.get(stone.spawn, 0), run.floor, run.keyword, run, stone))
        if not fits:
            continue
        _n, _floor, keyword, run, stone = min(fits, key=lambda f: f[:3])
        load[stone.spawn] = load.get(stone.spawn, 0) + 1
        out[m.name] = Door(keyword, run.place, run.floor, run.ceiling, stone)
    return out


# ---------------------------------------------------------------------------
# THE GUILD FOCUS (the operator, 2026-10-05): two fronts. One guild is the
# crafting and farming front, the other the dungeon front, and what one front
# proves is later shared with the other. `GUILD_FOCUS` names them, e.g.
# "Cave:craft,Bonkers:dungeon". Unset, or a guild it does not name, keeps
# every member's ordinary job.
#
#   craft    every free member of the guild (not in a guild run, not on
#            another walk, never the family) takes the trade work a
#            maintenance member has between runs: train, tool, craft, post,
#            sell, farm. Raiders and summoners are given gathering trades of
#            their own (`focus_trades`); a summoner with a door keeps it. It
#            still answers guild asks and still levels: gear, PvP, mail and
#            the walk out of an outgrown zone come first, as for anybody.
#            FARMING AND CRAFTING ITS OWN TRADES IS NOT A CONTRIBUTION, so a
#            member short of its natural restart still casts what it carries
#            and walks to its field (the same reasoning as #638 for the level
#            step); training, tools, posts and sales still wait for it.
#   dungeon  unchanged: the guild social pass asks and runs, and the job
#            pass keeps every member's ordinary job. Said in the log.

FOCUS_ENV = "GUILD_FOCUS"
CRAFT_FOCUS, DUNGEON_FOCUS = "craft", "dungeon"
FOCI = (CRAFT_FOCUS, DUNGEON_FOCUS)


def parse_focus(text) -> dict:
    """guild -> focus word from "Guild:focus,Guild:focus".

    A pair without a colon, with an empty guild or with a focus word not in
    FOCI is dropped; a guild named twice keeps the last.
    """
    out = {}
    for part in str(text or "").split(","):
        guild, sep, word = part.partition(":")
        guild, word = guild.strip(), word.strip().lower()
        if sep and guild and word in FOCI:
            out[guild] = word
    return out


def focus_from_env(environ=None) -> dict:
    """GUILD_FOCUS, parsed; {} when unset."""
    environ = os.environ if environ is None else environ
    return parse_focus(environ.get(FOCUS_ENV, ""))


def focus_of(guild, focus) -> str:
    """The focus word for this guild, "" when GUILD_FOCUS does not name it.
    Guild names are matched without regard to case."""
    wanted = str(guild or "").lower()
    for name, word in (focus or {}).items():
        if str(name).lower() == wanted:
            return word
    return ""


def crafting(member: Member, focus) -> bool:
    """Whether this member works its trades for a craft-focus guild."""
    return member.role in (MAINTENANCE, SUMMONER, RAIDER) and (
        focus_of(member.guild, focus) == CRAFT_FOCUS
    )


def wants_field(member: Member, focus=None) -> bool:
    """Whether the bridge should find this member a field to farm.

    A natural maintenance member, as before; and under a craft focus every
    member of the guild that is online, natural or not, because farming its
    own trades contributes nothing.
    """
    if member.map_id is None or member.x is None or member.y is None:
        return False
    if member.role == MAINTENANCE and member.eligible:
        return True
    return crafting(member, focus) and member.online


def focus_trades(members, focus) -> dict:
    """name -> trades for the raiders and summoners of a craft-focus guild.

    Each guild's non-maintenance members are split among themselves the way
    the maintenance crew is (`split_trades`: what it holds first, then the
    trade fewest of them hold), with First Aid beside, which costs no primary
    slot. None takes Tailoring here; the crew's tailors are choose_tailors'.
    """
    crews = {}
    for m in members or ():
        if m.role in (SUMMONER, RAIDER) and crafting(m, focus):
            crews.setdefault(m.guild, []).append(m)
    out = {}
    for _guild, crew in sorted(crews.items()):
        crew = sorted(crew, key=lambda m: m.name)
        counts = {s: sum(1 for m in crew if m.holds(s)) for s in GATHERING}
        for m in crew:
            out[m.name] = _fill_gathering(m, counts, False) + (FIRST_AID,)
    return out


def _focus_tally(members, focus) -> dict:
    """guild -> the tally a pass fills, for every guild GUILD_FOCUS names."""
    out = {}
    for m in members or ():
        word = focus_of(m.guild, focus)
        if not word or m.role not in (MAINTENANCE, SUMMONER, RAIDER):
            continue
        tally = out.setdefault(
            m.guild,
            {"focus": word, "members": 0, "craft": 0, "farm": 0, "gathering": 0},
        )
        tally["members"] += 1
    return out


def _count_focus(tally, m, step, fields):
    """Count a craft-focus member's craft or farm step, or its stand in its
    field, into the guild's tally."""
    t = tally.get(m.guild)
    if t is None or t["focus"] != CRAFT_FOCUS:
        return
    if step is not None and step.action in ("craft", "farm"):
        t[step.action] += 1
    elif step is None and fields.get(m.name) and _near(m, fields[m.name], FIELD_REACH):
        t["gathering"] += 1


def focus_lines(plan_result) -> list:
    """One sentence per named guild: its focus and what its members took."""
    out = []
    for guild, t in sorted((plan_result.focus or {}).items()):
        if t["focus"] == CRAFT_FOCUS:
            out.append(
                "%s: focus craft: %d member(s); %d took a craft step, %d a "
                "farm step, %d gather in their field"
                % (guild, t["members"], t["craft"], t["farm"], t["gathering"])
            )
        else:
            out.append(
                "%s: focus dungeon: %d member(s) keep their jobs; the guild "
                "social pass's dungeon asks and runs are unchanged"
                % (guild, t["members"])
            )
    return out


def _own_trade_step(m, spot, recent, cap):
    """A craft-focus member short of its natural restart: it casts what it
    carries, else walks to its field. Nothing it does is counted as given."""
    if not _cooling(m, "craft", recent):
        step = _craft_step(m)
        if step:
            return step, step.said, ""
    step, doing = _gathering_step(m, spot, recent, cap)
    if step:
        return step, step.said, ""
    return None, doing + " (craft focus; not natural yet, so it gives nothing)", ""


def _crafting_job(
    m, trades, fields, doors, pending, crafters, master, kept, recent, cap
):
    """A natural member of a craft-focus guild: a maintenance member's work.
    A summoner that knows the ritual and has a door keeps its door."""
    if m.role == SUMMONER and RITUAL_OF_SUMMONING in m.known and m.name in doors:
        return _summoner_step(m, doors, pending, crafters, master, kept, recent, cap)
    return _maintenance_step(
        m, trades, fields, crafters, master, kept, recent, cap, crafting=True
    )


# ---------------------------------------------------------------------------
# THE PLAN.


def _maintenance_step(
    m, trades, fields, crafters, master, kept, recent, cap, crafting=False
):
    """(step or None, what it does now, a note or "")."""
    notes = []
    step, why = _train_step(m, trades, cap, recent)
    if step:
        return step, step.said, ""
    if why:
        notes.append(why)
    step = _learn_step(m, cap, recent)
    if step:
        return step, step.said, ""
    if not _cooling(m, "tool", recent):
        step, why = _tool_step(m, cap)
        if step:
            return step, step.said, ""
        if why:
            notes.append(why)
    if not _cooling(m, "craft", recent):
        step = _craft_step(m)
        if step:
            return step, step.said, ""
    shared = _shared_step(m, crafters, master, kept, recent, cap, crafting)
    if shared[0]:
        return shared
    if shared[2]:
        notes.append(shared[2])
    step, doing = _gathering_step(m, fields.get(m.name), recent, cap)
    if step:
        return step, step.said, ""
    return None, doing, "; ".join(notes)


def _gathering_step(m, spot, recent, cap):
    """(step or None, what a maintenance member gathers now)."""
    gathering = [SKILL_NAMES[s] for s in GATHERING if m.holds(s)]
    if spot is not None and not _near(m, spot, FIELD_REACH):
        if not _cooling(m, "farm", recent):
            said = "%s walks to %s to gather (%s)" % (
                m.name,
                spot.name or "a field",
                spot.why,
            )
            return _spot_step(m, spot, "farm", cap, said), said
    if spot is not None:
        doing = "gathers %s at %s" % (
            " and ".join(gathering) or "what it can",
            spot.name,
        )
    elif gathering:
        doing = "gathers %s where it levels" % " and ".join(gathering)
    else:
        doing = "levels, and learns its trades once it can pay a trainer"
    return None, doing


def _shared_step(m, crafters, master, kept, recent, cap, crafting=False):
    """Post, then sell: what every role does with what it carries."""
    if not _cooling(m, "post", recent):
        step, why = _post_step(m, crafters, master, kept, cap, crafting)
        if step:
            return step, step.said, ""
        if why:
            return None, "", why
    if not _cooling(m, "sell", recent):
        step = _sell_step(m, kept, cap)
        if step:
            return step, step.said, ""
    return None, "", ""


def _summoner_step(m, doors, pending, crafters, master, kept, recent, cap):
    shared = _shared_step(m, crafters, master, kept, recent, cap)
    if shared[0]:
        return shared
    if m.level < RITUAL_LEVEL:
        return None, "levels toward Ritual of Summoning at %d" % RITUAL_LEVEL, shared[2]
    if RITUAL_OF_SUMMONING not in m.known:
        return (
            None,
            "has the level for Ritual of Summoning and has not learned it at a warlock trainer",
            shared[2],
        )
    door = doors.get(m.name)
    if door is None:
        return None, "knows the ritual; no door fits its level yet", shared[2]
    shards = "" if m.carries(SOUL_SHARD) else "; carries no Soul Shard yet"
    if m.name in pending:
        return None, "answers a summon at %s" % door.place, ""
    if m.x is None or m.y is None:
        return None, "serves %s; where it stands is not read this pass" % door.place, ""
    if door.stone is not None and not _near(m, door.stone, DOOR_REACH):
        if not _cooling(m, "door", recent):
            said = (
                "%s walks to the meeting stone at %s to farm there between summons"
                % (
                    m.name,
                    door.place,
                )
            )
            return _spot_step(m, door.stone, "door", cap, said), said, ""
    return (
        None,
        "farms near the meeting stone at %s between summons%s" % (door.place, shards),
        "",
    )


def plan(
    members,
    *,
    masters=None,
    crafters=None,
    fields=None,
    doors=None,
    pending=(),
    kept=None,
    recent=(),
    busy=(),
    cap=guildroute.MAIL_RUN_YARDS,
    per_guild=STEPS_PER_GUILD,
    unclaimed=(),
    banks=None,
    gear=None,
    mail=None,
    pvp=None,
    leveling=None,
    focus=None,
    classes=None,
    hunts=None,
    now=0.0,
    far_slots=None,
) -> JobsPlan:
    """Every member's job this pass, and the steps to start.

    `masters` guild -> guild master; `crafters` guild -> {skill: [(family
    name, value)]}; `fields` name -> Spot a maintenance member gathers at;
    `doors` name -> Door (assign_doors); `pending` names a summon waits on;
    `kept` keep.Reservations; `recent` Recent rows; `busy`
    names another pass has on a walk; `unclaimed` names family members with a
    materials post still unopened in their mailbox (`without_unclaimed`);
    `banks` the guilds that own a guild bank tab, None when unread; `gear`
    name -> (gearup facts, vendor rows in reach) for gear-short members;
    `mail` name -> the mail commands (mailrun) waiting at its mailbox;
    `pvp` name -> (pvpgear.Aim, pvpgear.Move) for members playing PvP for an
    upgrade (#589); `leveling` the guildlevel.World a member who has outgrown
    its zone is walked to a quest hub from, None to take no level step;
    `focus` guild -> focus word (parse_focus), None or {} for every guild's
    ordinary job; `classes` the classquest.Book of every class quest, None to
    take no class quest step; `hunts` the classquest.Hunts clock (None keeps no
    clock, so no hunt ever stalls) and `now` its time in seconds; `far_slots`
    the far walks the realm can still take (None when not counted): class
    quest walks past it wait, and the members are planned tank-spec warriors
    and healers first, then by level (class_priority).
    """
    masters = bank_masters(masters or {}, banks, unclaimed)
    crafters = without_unclaimed(crafters or {}, unclaimed)
    fields = fields or {}
    doors = doors or {}
    busy = {str(n) for n in busy or ()}
    pending = {str(n) for n in pending or ()}
    tailors = choose_tailors(members)
    trades = cloth_trades(split_trades(members, tailors), tailors)
    trades.update(focus_trades(members, focus))
    tally = _focus_tally(members, focus)
    steps, lines, notes, helps = [], {}, [], []
    # One counter per allowance, each keyed by guild (_allowance).
    counters = {"jobs": {}, "gear": {}, "pvp": {}, "level": {}, "classquest": {}}
    far = classquest.FarSlots(far_slots) if far_slots is not None else None
    for m in _class_ordered(members, classes):
        if m.role not in (MAINTENANCE, SUMMONER, RAIDER):
            continue
        master = str(masters.get(m.guild) or "")
        step, doing, note = _member_step(
            m,
            (gear or {}).get(m.name),
            (mail or {}).get(m.name, ()),
            trades,
            fields,
            doors,
            pending,
            crafters,
            master,
            kept,
            recent,
            cap,
            (pvp or {}).get(m.name),
            leveling,
            crafting(m, focus),
            classes,
            hunts,
            now,
            far,
        )
        lines[m.name] = doing
        helps += class_helps(m, classes, hunts, now)
        if note:
            notes.append(note)
        if step is None:
            _count_focus(tally, m, None, fields)
            continue
        started, allowance = _allowance(step, counters, per_guild)
        why = _step_refusal(m, busy, started, allowance)
        if why:
            notes.append(why)
            if far is not None:
                far.release(m.name)
            continue
        started[m.guild] = started.get(m.guild, 0) + 1
        busy.add(m.name)
        steps.append(step)
        _count_focus(tally, m, step, fields)
    return JobsPlan(
        steps=tuple(steps),
        lines=lines,
        trades=trades,
        doors=doors,
        notes=tuple(notes),
        focus=tally,
        helps=tuple(helps),
    )


def _allowance(step, counters, per_guild):
    """(the counter, the cap) a step is started against: STEPS_PER_GUILD for
    every job, GEAR_STEPS_PER_GUILD for gear and hearth steps,
    PVP_STEPS_PER_GUILD for PvP queues and honor buys, and
    guildlevel.STEPS_PER_GUILD for walks out of an outgrown zone."""
    if step.action == classquest.ACTION:
        return counters["classquest"], CLASSQUEST_STEPS_PER_GUILD
    if step.action == pvpgear.ACTION:
        return counters["pvp"], PVP_STEPS_PER_GUILD
    if step.action == guildlevel.ACTION:
        return counters["level"], guildlevel.STEPS_PER_GUILD
    if step.action in ("gear", "hearth"):
        return counters["gear"], GEAR_STEPS_PER_GUILD
    return counters["jobs"], per_guild


def collect_step(m, commands, cap):
    """The member opens its post: a walk to a mailbox, then every take.

    GUILD MEMBERS NEVER OPENED THEIR MAIL. On wow-dev on 2026-10-04 the
    family's cloth and gear sat unopened in guild members' mailboxes for up to
    157 hours (Aalall 33 letters, Argam 25, Bezki and Cigtek 24 each), every
    one still carrying its items: bandage cloth for the First Aid crafters
    and pieces to wear, posted and never collected. `commands` are mailrun's,
    the same takes and empty-letter deletes the family's own pass writes.
    """
    if not commands:
        return None
    return guildcorps.Step(
        m.name,
        "collect",
        len(commands),
        "%s walks to a mailbox to open %d piece(s) of post" % (m.name, len(commands)),
        rows=tuple(
            guildcorps.Row("mail", command, "", source_for("collect", m.name))
            for command in commands
        ),
        walk=guildcorps.Row(
            "mail",
            guildroute.mailbox_walk_command(cap),
            "",
            source_for("collect-walk", m.name),
        ),
    )


def _collect_first(m, commands, recent, cap):
    if not commands or not m.eligible or not m.online or m.in_combat:
        return None
    if _cooling(m, "collect", recent):
        return None
    return collect_step(m, commands, cap)


def _member_step(
    m,
    offer,
    mail,
    trades,
    fields,
    doors,
    pending,
    crafters,
    master,
    kept,
    recent,
    cap,
    pvp=None,
    leveling=None,
    crafting=False,
    classes=None,
    hunts=None,
    now=0.0,
    far=None,
):
    """A class quest first, then gear, then PvP for an upgrade, then the post, then a walk out of an
    outgrown zone, then the member's ordinary job (a craft-focus guild's trade
    work when `crafting`), keeping the notes.

    THE CLASS QUEST COMES FIRST (the operator, 2026-10-06: the highest-priority
    job in the guild). It is the first rung here, ahead of gear, PvP, post, the
    level walk and every ordinary job, and it has its own allowance per guild
    (CLASSQUEST_STEPS_PER_GUILD), so no other kind of step can use up the
    passes it needs. A member held on a class quest is also kept out of the
    guild's dungeon asks (the bridge's mid_job set)."""
    step, doing, quest_note = class_step(m, classes, recent, cap, hunts, now, far)
    if step is not None or doing:
        return step, doing, quest_note
    step, doing, gear_note = _gear_first(m, offer, recent, cap, kept)
    if step is not None:
        return step, doing, gear_note
    step, doing, held = _pvp_first(m, pvp, recent, cap, kept)
    if step is not None or held:
        return step, doing, gear_note
    step = _collect_first(m, mail, recent, cap)
    if step is not None:
        return step, step.said, gear_note
    step, doing, level_note = level_step(m, leveling, recent, cap)
    if step is not None:
        return step, doing, gear_note
    step, doing, note = _plan_member(
        m,
        trades,
        fields,
        doors,
        pending,
        crafters,
        master,
        kept,
        recent,
        cap,
        crafting,
    )
    return (
        step,
        doing,
        "; ".join(n for n in (quest_note, gear_note, level_note, note) if n),
    )


def level_step(m, world, recent, cap):
    """(step or None, what it does, a note): a member that has outgrown
    where it stands walks to the flight master of a quest hub whose
    band fits its level (guildlevel.py).

    Never a roster family member (levelroute walks those), never at the level
    cap, never while offline or fighting, and at most once per
    COOLDOWN_MINUTES["level"]. The walk is `walk-to-spawn creature:` naming
    the flight master's spawn, at the pass's cap.
    """
    # EVERY MEMBER, NATURAL OR NOT (2026-10-05). The natural reset gates what
    # a member contributes, not where it walks: on the dev realm 1 of Cave's
    # 60 and none of Bonkers' 56 held a reset, so a step gated on it walked
    # nobody, and Cave's level 14-15 priests stayed in their starting zones.
    if world is None or not m.online or m.in_combat:
        return None, "", ""
    if m.name in world.roster or m.level >= guildlevel.LEVEL_CAP:
        return None, "", ""
    bands = world.bands.get(guildlevel.side_of(m.race), {})
    why = guildlevel.outgrown(m.level, m.race, m.map_id, m.zone_id, bands)
    if not why:
        return None, "", ""
    choice = guildlevel.choose(
        m.level, m.race, m.map_id, bands, world.masters, zone_id=m.zone_id
    )
    if choice.refused:
        return None, "", guildlevel.refused_note(m.name, m.level, why, choice)
    master = choice.master
    if guildlevel.there(m.map_id, m.x, m.y, master):
        return None, "", ""
    if _cooling(m, guildlevel.ACTION, recent):
        return None, "", ""
    said = guildlevel.said(m.name, m.level, why, choice)
    spot = Spot(
        kind="creature",
        spawn=master.spawn,
        map_id=master.map_id,
        x=master.x,
        y=master.y,
        name=master.name or choice.place,
        why=why,
    )
    return _spot_step(m, spot, guildlevel.ACTION, cap, said), said, ""


# THE CLASS QUEST (classquest.py).
CLASSQUEST_STEPS_PER_GUILD = 6


def _class_spot(move) -> Spot:
    s = move.spot
    chest = move.kind == classquest.USE and move.use.verb == classquest.USE_OBJECT
    return Spot(
        kind="gameobject" if chest else "creature",
        spawn=int(s.guid),
        map_id=int(s.map_id),
        x=float(s.x),
        y=float(s.y),
        name=s.name,
        why=move.why,
    )


def class_held(lines) -> set:
    """The names whose line says they are on a class quest, for the guild
    social pass, which does not ask them to a dungeon."""
    return {n for n, line in (lines or {}).items() if classquest.MARK in str(line)}


def _class_ready(m, book) -> bool:
    """Whether the member may be given a class quest move now: a book, online,
    out of combat and with a position read."""
    if book is None or not m.online or m.in_combat:
        return False
    return not (m.map_id is None or m.x is None or m.y is None)


def failed_class_walks(name, recent) -> bool:
    """Whether the member's last FAILED_WALKS class quest rows, newest first,
    all ended in error or unchanged (the spawn cannot be reached)."""
    # A refusal the module calls retryable (a far walk wall, a dead character)
    # says nothing about the spawn, so it is no failed hunt.
    rows = sorted(
        (
            r
            for r in recent or ()
            if r.name == name and r.action == classquest.ACTION and not r.retryable
        ),
        key=lambda r: r.age_minutes,
    )[: classquest.FAILED_WALKS]
    return len(rows) == classquest.FAILED_WALKS and all(
        r.status in TRAIN_FAILED for r in rows
    )


def class_walk_backoff(name, recent) -> int:
    """Minutes the member is left alone after the realm refused its newest
    class quest walk for a far walk wall (classquest.BACKOFF_MINUTES), 0 when
    the newest class row was anything else, or the wall has had its time."""
    rows = sorted(
        (r for r in recent or () if r.name == name and r.action == classquest.ACTION),
        key=lambda r: int(r.age_minutes),
    )
    if not rows:
        return 0
    newest = rows[0]
    wait = classquest.BACKOFF_MINUTES.get(newest.refusal, 0)
    return max(0, wait - int(newest.age_minutes))


def class_priority(m) -> int:
    """0 for a member whose class quest reward the party most needs and the
    realm's few far walk slots should go to first: a tank-spec warrior (the
    reward of the level-10 quest is Defensive Stance, Taunt and Sunder Armor,
    and a warrior without them cannot hold a dungeon) and a healer of any
    class (the heal ranks); 1 for everyone else."""
    cls = int(m.class_id)
    if cls == classquest.WARRIOR and raidroles.fits_seat(
        cls, m.tree, raidroles.SEAT_TANK
    ):
        return 0
    return 0 if raidroles.fits_seat(cls, m.tree, raidroles.SEAT_HEALER) else 1


def _class_ordered(members, classes):
    """The members in the order their steps are planned. With a class quest
    book, the scarce far walk slots go first to class_priority 0, then by level,
    highest first (the member nearest its next reward spell and the dungeons
    that want it); the old order (role, guild, name) breaks every tie."""
    ordered = _ordered_members(members)
    if classes is None:
        return ordered
    return sorted(ordered, key=lambda m: (class_priority(m), -int(m.level or 0)))


def _far_class_walk(m, spot, cap) -> bool:
    """Whether a walk from the member to the spot is a far walk, one the
    module counts against the realm: past the near cap, or on another map."""
    if float(cap) <= guildroute.TRAINER_WALK_YARDS:
        return False
    if m.map_id is None or m.x is None or m.y is None:
        return True
    if int(m.map_id) != int(spot.map_id):
        return True
    return _yards(m.x, m.y, spot.x, spot.y) > guildroute.TRAINER_WALK_YARDS


def class_helps(m, book, hunts=None, now=0.0) -> list:
    """The class quests this member cannot do alone and no other class move
    stands ahead of, as classquest.Help rows for classask: a group quest, or a
    hunt given up after it stalled. Nothing for a member with a class move."""
    if not _class_ready(m, book):
        return []
    avoid, off = hunts.state(m.name, now) if hunts else ({}, frozenset())
    move, _blocked = classquest.next_move(book, m, avoid, off)
    if move is not None:
        return []
    return [
        classquest.Help(m.name, m.guild, int(m.level), int(m.map_id), h)
        for h in classquest.helps(book, m, avoid, off)
    ]


def _class_move(m, book, recent, hunts, now):
    """(move or None, blocked sentences): classquest.next_move, with a hunt
    that has stalled sent to another pack, or given up (HUNT_STALL_MINUTES)."""
    avoid, off = hunts.state(m.name, now) if hunts else ({}, frozenset())
    move, blocked = classquest.next_move(book, m, avoid, off)
    if not hunts or move is None or move.kind not in (classquest.HUNT, classquest.USE):
        return move, blocked
    verdict = hunts.observe(
        m.name,
        move.quest,
        int(m.quest_progress.get(move.quest, 0)),
        move.spot,
        now,
        failed_class_walks(m.name, recent),
    )
    if verdict:
        avoid, off = hunts.state(m.name, now)
        move, blocked = classquest.next_move(book, m, avoid, off)
    return move, blocked


def class_step(m, book, recent, cap, hunts=None, now=0.0, far=None):
    """(step or None, what it does, a note): the member's next move toward a
    class quest it may do now, from classquest.next_move.

    Never at a roster family member (levelroute walks those), never while
    offline or fighting, and at most once per COOLDOWN_MINUTES. A hunt holds
    the member where it hunts (`doing` is set with no step): the member's own
    grind and loot strategies work the field, and nothing else is asked of it
    until the quest is complete and handed in. A hunt with no progress for
    classquest.HUNT_STALL_MINUTES is walked to another pack, and after
    MAX_REROLLS of those is given up for GIVE_UP_MINUTES and asked for in guild
    chat (classask.py), so a hunt never holds a member for ever. A quest that
    cannot be done solo is named in the note, so a member never waits in
    silence. A quest that has the member use an item on a creature or click a
    gameobject (classquest.USE) is a walk to the target and one `kind='quest'`
    row there, which the bridge follows by its answer (classuse.py); the same
    clock moves it to another target and gives it up.
    """
    if not _class_ready(m, book):
        return None, "", ""
    move, blocked = _class_move(m, book, recent, hunts, now)
    note = "; ".join(blocked)
    if move is None:
        return None, "", note
    spot = _class_spot(move)
    # A pack tried without progress is left, so a member is "at" the next one
    # only within a pack's width, not the whole field's.
    tried = hunts.state(m.name, now)[0].get(move.quest) if hunts else ()
    reach = classquest.PACK_YARDS if tried else classquest.HUNT_REACH
    if move.kind == classquest.HUNT and _near(m, spot, reach):
        return None, move.said, note
    held = _class_held(m, move, spot, cap, recent, hunts, now, far)
    if held is not None:
        return None, move.said, _join(note, held)
    if move.kind == classquest.HUNT:
        return _spot_step(m, spot, classquest.ACTION, cap, move.said), move.said, note
    if move.kind == classquest.USE:
        return _use_step(m, move, spot, cap), move.said, note
    verb = "turnin" if move.kind == classquest.TURN_IN else "take"
    step = guildcorps.Step(
        m.name,
        classquest.ACTION,
        int(move.quest),
        move.said,
        rows=(
            guildcorps.Row(
                "quest",
                "%s quest:%d" % (verb, int(move.quest)),
                "",
                source_for(classquest.ACTION, m.name),
            ),
        ),
        walk=guildcorps.Row(
            "job",
            spot.command + _cap_word(cap),
            "",
            source_for(classquest.ACTION + "-walk", m.name),
        ),
        goal=spot.name,
    )
    return step, move.said, note


def _class_held(m, move, spot, cap, recent, hunts, now, far):
    """The note for a member a class quest walk is held back from, or None when
    the walk may start. Held back: a dead member (the module refuses "character
    is dead"), a member the realm refused for a far walk wall (its backoff), the
    class cooldown, and a far walk with no slot left. None of these is the
    hunt's fault, so the first, second and last restart its stall clock."""
    wait = class_walk_backoff(m.name, recent)
    if not m.alive or wait:
        if hunts:
            hunts.pause(m.name, move.quest, now)
        return _held_note(m, wait)
    if _cooling(m, classquest.ACTION, recent):
        return ""
    walks = move.kind != classquest.USE or not _near(m, spot, classquest.USE_NEAR)
    if far is None or not walks or not _far_class_walk(m, spot, cap):
        return None
    if far.take(m.name):
        return None
    if hunts:
        hunts.pause(m.name, move.quest, now)
    return "%s waits for a far walk slot on the realm" % m.name


def _join(*parts) -> str:
    return "; ".join(p for p in parts if p)


def _held_note(m, wait) -> str:
    if not m.alive:
        return "%s is dead and is walked nowhere" % m.name
    return "%s waits %d more minute(s) after the realm refused its far walk" % (
        m.name,
        wait,
    )


def _use_step(m, move, spot, cap):
    """The walk to the target and the quest row that uses the item or object
    there (classquest.USE_ITEM, USE_OBJECT). A member already beside the target
    writes the row with no walk."""
    row = guildcorps.Row(
        "quest",
        classquest.use_command(move.use, move.spot),
        "",
        source_for(classquest.ACTION, m.name),
    )
    walk = None
    if not _near(m, spot, classquest.USE_NEAR):
        walk = guildcorps.Row(
            "job",
            spot.command + _cap_word(cap),
            "",
            source_for(classquest.ACTION + "-walk", m.name),
        )
    return guildcorps.Step(
        m.name,
        classquest.ACTION,
        int(move.quest),
        move.said,
        rows=(row,),
        walk=walk,
        goal=spot.name,
    )


# PVP FOR UPGRADES (#589). A member whose next upgrade is PvP gear
# (pvpgear.plan_aims) queues its battleground, waits in the queue, plays, and
# walks to the vendor once its honor covers the price. Queue rows are cheap and
# a battleground wants a team, so PvP has its own allowance per guild per pass.
PVP_STEPS_PER_GUILD = 10


# A WALK TO A PVP VENDOR THAT FAILED IS NOT ASKED AGAIN AT ONCE. On wow-dev on
# 2026-10-05 Ahgeathou, a level 21 Alliance member in Mulgore with the honor
# for Protector's Sword, was sent to Illiyana Moonblaze 3,965 yards off across
# ground the other side guards: the walk died at 07:24, the next stopped
# getting nearer, and the one after was "refused by the budget: 2 per bot per
# 3600s (#633)", because the PvP cooldown asks again every QUEUE_MINUTES. Each
# failed walk in a row (newest first, until one that did not fail) doubles the
# wait from the module's far-walk budget window, up to the trainer walks' cap.
PVP_WALK_BACKOFF_MINUTES = 60


def pvp_walk_cooldown(name, recent) -> int:
    """Minutes to wait after this member's failed walks to a PvP vendor, 0
    when its newest such walk did not fail."""
    rows = sorted(
        (r for r in recent or () if r.name == name and r.action == pvpgear.ACTION
         and r.walk),
        key=lambda r: int(r.age_minutes),
    )  # fmt: skip
    failed = 0
    for r in rows:
        if r.status not in TRAIN_FAILED:
            break
        failed += 1
    if not failed:
        return 0
    return min(PVP_WALK_BACKOFF_MINUTES * 2 ** (failed - 1), TRAIN_BACKOFF_CAP_MINUTES)


def _pvp_walk_cooling(name, recent) -> bool:
    minutes = pvp_walk_cooldown(name, recent)
    return any(
        r.name == name and r.action == pvpgear.ACTION and r.walk
        and int(r.age_minutes) < minutes
        for r in recent or ()
    )  # fmt: skip


def pvp_step(m, aim, move, cap, kept=None):
    """The step for a PvP move: the queue row, or the walk to the vendor that
    stocks the item and the honor buy, after selling junk for room."""
    if move.kind == pvpgear.QUEUE:
        return guildcorps.Step(
            m.name,
            pvpgear.ACTION,
            aim.entry,
            move.said,
            rows=(
                guildcorps.Row(
                    "guild", pvpgear.queue_command(aim), "", source_for("pvp", m.name)
                ),
            ),
        )
    if move.kind == pvpgear.BUY:
        return guildcorps.Step(
            m.name,
            pvpgear.ACTION,
            aim.entry,
            move.said,
            rows=junk_sales(m, kept)
            + (
                guildcorps.Row(
                    "buy", pvpgear.buy_command(aim), "", source_for("pvp", m.name)
                ),
            ),
            walk=guildcorps.Row(
                "buy",
                "walk-to-vendor item:%d%s" % (aim.entry, _cap_word(cap)),
                "",
                source_for("pvp-walk", m.name),
            ),
            goal=aim.vendor,
        )
    return None


def _pvp_first(m, pvp, recent, cap, kept=None):
    """(step, doing, held): a member playing PvP for an upgrade.

    Inside a battleground or waiting in its queue the member is HELD: it does
    nothing else this pass. A queue or a buy whose last row failed inside the
    PvP cooldown waits it out doing its ordinary job, and so does a buy whose
    walks to the vendor failed, for pvp_walk_cooldown. A bought item still in
    the bags is the equip drive's, and the member goes about its job.
    """
    if not pvp or not m.eligible or not m.online:
        return None, "", False
    aim, move = pvp
    if move.kind in (pvpgear.INSIDE, pvpgear.WAITING):
        return None, aim.line + ": " + move.said, True
    if move.kind not in (pvpgear.QUEUE, pvpgear.BUY) or m.in_combat:
        return None, "", False
    if _cooling(m, pvpgear.ACTION, recent):
        return None, "", False
    if move.kind == pvpgear.BUY and _pvp_walk_cooling(m.name, recent):
        return None, "", False
    step = pvp_step(m, aim, move, cap, kept)
    return step, (aim.line + ": " + move.said) if step else "", False


def last_gear_failed(name, recent) -> bool:
    """Whether this member's newest gear row (walk or buy) failed."""
    rows = [r for r in recent or () if r.name == name and r.action == "gear"]
    if not rows:
        return False
    newest = min(rows, key=lambda r: int(r.age_minutes))
    return newest.status in TRAIN_FAILED


def hearth_step(m):
    """The member uses its hearthstone, a player's own way home.

    A GEAR WALK THAT CANNOT START IS A MEMBER STANDING SOMEWHERE NO STEP
    LEAVES. On wow-dev on 2026-10-03, after the walk legs learned to follow
    the navmesh, every guild vendor walk was still refused at its first leg:
    the members stood on a mountain top above Northshire (z 274 where the
    valley is 80), on the Darnassus terraces, on a Durotar ledge for hours,
    or on the Exodar's island where no far walk goes. Their inn is in a town
    with vendors and walkable streets, so the next gear walk starts there.
    """
    return guildcorps.Step(
        m.name,
        "hearth",
        0,
        "%s hearths home: its last walk to a vendor could not start" % m.name,
        rows=(guildcorps.Row("hearth", "use", "", source_for("hearth", m.name)),),
    )


def _gear_first(m, offer, recent, cap, kept=None):
    """A natural member short of gear walks to a vendor before any other job."""
    if not m.eligible or not m.online or m.in_combat:
        return None, "", ""
    if _cooling(m, "gear", recent):
        if last_gear_failed(m.name, recent) and not _cooling(m, "hearth", recent):
            step = hearth_step(m)
            return step, step.said, ""
        return None, "", ""
    if not offer:
        return None, "", ""
    character, vendor_rows = offer
    step, why = gear_step(m, character, vendor_rows, cap, kept)
    if step is None:
        return None, "", why
    return step, step.said, ""


def _plan_member(
    m,
    trades,
    fields,
    doors,
    pending,
    crafters,
    master,
    kept,
    recent,
    cap,
    crafting=False,
):
    if not m.eligible:
        if crafting:
            return _own_trade_step(m, fields.get(m.name), recent, cap)
        return None, "waits for its natural restart; nothing it holds is counted", ""
    if crafting:
        return _crafting_job(
            m, trades, fields, doors, pending, crafters, master, kept, recent, cap
        )
    return _member_job(
        m, trades, fields, doors, pending, crafters, master, kept, recent, cap
    )


def _ordered_members(members):
    order = {MAINTENANCE: 0, SUMMONER: 1, RAIDER: 2}
    return sorted(members or (), key=lambda m: (order.get(m.role, 3), m.guild, m.name))


def _member_job(m, trades, fields, doors, pending, crafters, master, kept, recent, cap):
    if m.role == MAINTENANCE:
        return _maintenance_step(m, trades, fields, crafters, master, kept, recent, cap)
    if m.role == SUMMONER:
        return _summoner_step(m, doors, pending, crafters, master, kept, recent, cap)
    step, doing, note = _shared_step(m, crafters, master, kept, recent, cap)
    return step, doing or "levels toward the raid and raids when the guild does", note


def _step_refusal(m, busy, started, per_guild):
    if not m.online:
        return "%s is offline" % m.name
    if m.in_combat:
        return "%s is in combat" % m.name
    if m.name in busy:
        return "%s is already on another guild walk" % m.name
    if started.get(m.guild, 0) >= int(per_guild):
        return "%s waits: %d guild job steps per guild per pass" % (
            m.name,
            int(per_guild),
        )
    return ""


# ---------------------------------------------------------------------------
# WHAT THE PAGE SAYS.

JOB_WORDS = {
    MAINTENANCE: "farms and gathers for the guild",
    SUMMONER: "summons at a door, and farms there between summons",
    RAIDER: "raids",
}


def _body(row) -> dict:
    result = row.get("result")
    try:
        body = json.loads(result) if isinstance(result, str) else (result or {})
    except (TypeError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def _sent_count(row) -> int:
    """Items a letter the world says it sent carried; 0 for anything else.

    DoMail's result names the attachment, `item.count` among it.
    """
    if str(row.get("status") or "") != "delivered":
        return 0
    body = _body(row)
    if body.get("outcome") != "sent":
        return 0
    item = body.get("item")
    try:
        return max(1, int((item or {}).get("count") or 1))
    except (TypeError, ValueError, AttributeError):
        return 1


def _sold_copper(row) -> int:
    """Copper a sale the world applied brought in; 0 for anything else.

    DoSell's result carries `gained`, the purse after less the purse before.
    """
    if str(row.get("status") or "") not in ("delivered", "applied"):
        return 0
    body = _body(row)
    try:
        gained = int(body.get("gained") or 0)
    except (TypeError, ValueError):
        gained = 0
    if gained > 0:
        return gained
    try:
        return max(0, int(body.get("money_after")) - int(body.get("money_before")))
    except (TypeError, ValueError):
        return 0


def contributions(rows) -> dict:
    """name -> {"letters", "items", "sold"} from this pass's post and sell rows.

    `rows` carry target_name, source, status and result. Only a letter the
    world says it sent counts, and only a sale it applied.
    """
    out = {}
    for row in rows or ():
        name = str(row.get("target_name") or "")
        action = action_of(row.get("source"))
        if not name or action not in ("post", "sell"):
            continue
        entry = out.setdefault(name, {"letters": 0, "items": 0, "sold": 0})
        if action == "post":
            count = _sent_count(row)
            if count:
                entry["letters"] += 1
                entry["items"] += count
        else:
            entry["sold"] += _sold_copper(row)
    return out


def page_doing(role, level, skills, known, eligible) -> str:
    """What a member does now, from what the page can read without a pass:
    its level, its gathering skills, whether it knows the ritual, and the
    natural gate. The bridge's pass says the same things in its log with the
    place named."""
    if not eligible:
        return "waits for its natural restart; nothing it holds is counted"
    level = _int(level)
    skills = skills or {}
    if role == MAINTENANCE:
        held = [
            "%s %d/%d" % (SKILL_NAMES[s], _int(skills[s][0]), _int(skills[s][1]))
            for s in GATHERING
            if s in skills and _int(skills[s][1]) > 0
        ]
        if held:
            return "gathers (%s)" % ", ".join(held)
        return "levels, and learns its gathering trades once it can pay a trainer"
    if role == SUMMONER:
        if level < RITUAL_LEVEL:
            return "levels toward Ritual of Summoning at %d (level %d)" % (
                RITUAL_LEVEL,
                level,
            )
        if RITUAL_OF_SUMMONING not in (known or ()):
            return "has the level for Ritual of Summoning and has not learned it at a warlock trainer"
        return "summons at its door, and farms near the meeting stone between summons"
    if role == RAIDER:
        return "levels toward the raid (level %d)" % level
    return ""


def job_line(role, doing, posted, dues) -> str:
    """One sentence for a member: its job, what it does now, what it gave."""
    head = JOB_WORDS.get(role, "")
    gave = []
    entry = dues or {}
    if int(entry.get("copper") or 0):
        gave.append("%s in dues" % _gold(entry["copper"]))
    posted = posted or {}
    if int(posted.get("letters") or 0):
        gave.append(
            "%d item(s) in %d letter(s)"
            % (int(posted["items"]), int(posted["letters"]))
        )
    if int(posted.get("sold") or 0):
        gave.append("sold %s of grey loot" % _gold(posted["sold"]))
    text = head
    if doing:
        text += (": " if text else "") + doing
    return text + "; gave " + (", ".join(gave) if gave else "nothing yet")


def _gold(copper) -> str:
    copper = int(copper or 0)
    if copper >= 10000:
        return "%dg" % (copper // 10000)
    if copper >= 100:
        return "%ds" % (copper // 100)
    return "%dc" % copper


ROLE_ORDER = (MAINTENANCE, SUMMONER, RAIDER)


def attach_jobs(lineup, doing, posted, dues, family=()) -> dict:
    """Every placed member outside the family gets `job` and `work`; the guild
    gets `given`, what each role gave in all.

    `doing` name -> what it does now (plan().lines, or `page_doing`);
    `posted` contributions(); `dues` guildwork.contributions(); `family` the
    roster names, whose own passes are not this job.
    """
    doing, posted, dues = doing or {}, posted or {}, dues or {}
    family = set(family or ())
    totals = {role: {"copper": 0, "items": 0, "sold": 0} for role in ROLE_ORDER}
    for member, role in _placed_jobs(lineup, family):
        _attach_job(member, role, doing, posted, dues, totals)
    lineup["given"] = {"by_role": totals, "said": _given_summary(totals)}
    return lineup


def _placed_jobs(lineup, family):
    for group in lineup.get("groups") or ():
        for member in group.get("members") or ():
            if member.get("name") not in family:
                yield member, RAIDER
    for member in lineup.get("maintenance") or ():
        yield member, MAINTENANCE
    for member in lineup.get("summoners") or ():
        yield member, SUMMONER


def _attach_job(member, role, doing, posted, dues, totals):
    name = member.get("name")
    member["job"] = role
    member["work"] = job_line(
        role, doing.get(name, ""), posted.get(name), dues.get(name)
    )
    total = totals[role]
    total["copper"] += int((dues.get(name) or {}).get("copper") or 0)
    total["items"] += int((posted.get(name) or {}).get("items") or 0)
    total["sold"] += int((posted.get(name) or {}).get("sold") or 0)


def _given_summary(totals):
    return "given: " + "; ".join(
        "%s %s in dues, %d item(s) posted, %s of grey loot sold"
        % (
            role,
            _gold(totals[role]["copper"]),
            totals[role]["items"],
            _gold(totals[role]["sold"]),
        )
        for role in ROLE_ORDER
    )


# ---------------------------------------------------------------------------
# ROWS INTO FACTS.


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def carried_from_rows(rows) -> dict:
    """guid of the owner -> tuple of Carried."""
    out = {}
    for row in rows or ():
        owner = _int(row.get("owner"))
        if not owner:
            continue
        out.setdefault(owner, []).append(
            Carried(
                guid=_int(row.get("item_guid")),
                entry=_int(row.get("entry")),
                count=_int(row.get("count"), 1),
                item_class=_int(row.get("class")),
                subclass=_int(row.get("subclass")),
                quality=_int(row.get("quality"), 1),
                sell_price=_int(row.get("sell_price")),
                name=str(row.get("item_name") or ""),
                item_level=_int(row.get("item_level")),
            )
        )
    return {k: tuple(v) for k, v in out.items()}


def recent_from_rows(rows) -> tuple:
    out = []
    for row in rows or ():
        action = action_of(row.get("source"))
        if not action:
            continue
        out.append(
            Recent(
                name=str(row.get("target_name") or ""),
                action=action.replace("-walk", ""),
                age_minutes=_int(row.get("age"), 10**6),
                status=str(row.get("status") or ""),
                skill_id=(
                    _trainer_skill_id(row.get("command")) if action == "train" else None
                ),
                walk=action.endswith("-walk"),
                **_refusal_of(row),
            )
        )
    return tuple(out)


def _refusal_of(row) -> dict:
    """The module's refusal in a row's `result` ({"outcome":"refused","reason":
    "...","retryable":true,...}), read from the text so a result cut short in
    the read still gives its reason, which comes first."""
    result = str(row.get("result") or "")
    if '"outcome":"refused"' not in result:
        return {}
    found = re.search(r'"reason":"((?:[^"\\]|\\.)*)"', result)
    return {
        "refusal": found.group(1) if found else "",
        "retryable": '"retryable":true' in result,
    }


def _trainer_skill_id(command) -> int | None:
    """Read the skill line from a trainer walk, or None for legacy/malformed rows."""
    for token in str(command or "").split():
        if token.startswith("skill:"):
            value = token[len("skill:") :]
            return int(value) if value.isdecimal() else None
    return None


def spots_from_rows(rows, kind="gameobject") -> tuple:
    out = []
    for r in rows or ():
        try:
            out.append(
                Spot(
                    kind=kind,
                    spawn=int(r["guid"]),
                    map_id=int(r["map_id"]),
                    x=float(r["x"]),
                    y=float(r["y"]),
                    name=str(r.get("name") or ""),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(out)
