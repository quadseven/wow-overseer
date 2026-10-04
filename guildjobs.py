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
its skill value. It keeps the cloth its next casts eat instead of posting it,
and posts the rest as before. The trainer rows are `walk-to-trainer skill:`
and the casts are `cast` rows: what a player does, paid for at a trainer.

PURE MODULE: rows in, steps and sentences out. No MySQL, no clock.
"""

from __future__ import annotations

import functools
import json
import math
import os
from dataclasses import dataclass, field

import campaignplan
import council
import craft
import craft_rhythm
import dungeonpath
import gearup
import guildcorps
import guildroute
import keep
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
RANKS[FIRST_AID] = (
    Rank(3279, 75, 0, 0, 100),
    Rank(3280, 150, 0, 50, 500),
    Rank(54254, 225, 0, 125, 1000),
)
RANKS[TAILORING] = (
    Rank(3911, 75, 5, 0, 10),
    Rank(3912, 150, 10, 50, 500),
    Rank(3913, 225, 20, 125, 5000),
)

# One maintenance member in this many is a tailor: a crew of ten gives three.
TAILOR_EVERY = 3

# A RECIPE A TRAINER ADDS TO THE BOOK BY ITSELF. Linen Bandage comes with
# Apprentice First Aid and Bolt of Linen Cloth with Apprentice Tailoring
# (SkillLineAbility AcquireMethod 1, ClassMask 0; craft.py's notes). Any other
# recipe is cast only once `character_spell` says the member knows it.
AUTO_LEARNED = frozenset({3275, 2963})
CRAFT_SKILLS = (FIRST_AID, TAILORING)
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
    6: (165,),
    7: (164, 202, 755),
    8: (185,),
    9: (171, 773),
    10: (171, 164, 165, 197, 202),
}

# Grey loot: quality 0 with a vendor price. Nobody in any guild needs it.
JUNK_QUALITY = 0

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
    "hearth": 60,
    "train": 60,
    "tool": 60,
    "post": 60,
    "sell": 120,
    "farm": 45,
    "door": 45,
    "craft": 15,
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

    @property
    def material(self) -> str:
        if self.item_class != TRADE_GOODS:
            return ""
        return MATERIAL_SUBCLASSES.get(int(self.subclass), "")

    @property
    def junk(self) -> bool:
        return self.quality == JUNK_QUALITY and self.sell_price > 0


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
    money: int = 0
    skills: dict = field(default_factory=dict)  # skill -> (value, max)
    known: frozenset = frozenset()
    carried: tuple = ()  # Carried
    eligible: bool = False

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


@dataclass(frozen=True)
class JobsPlan:
    steps: tuple = ()
    lines: dict = field(default_factory=dict)  # name -> what it does now
    trades: dict = field(default_factory=dict)  # name -> (skill, skill)
    doors: dict = field(default_factory=dict)  # name -> Door
    notes: tuple = ()


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


def skinning_field(beasts, origin, level, value) -> Spot | None:
    """The beast spawn a skinner is sent to, or None.

    `beasts` are (Spot, level) for skinnable creature spawns on its map;
    `origin` its (x, y). The spawns in its band are grouped into SKIN_CELL
    cells; of the cells with SKIN_MIN_SPAWNS or more within SKIN_YARDS, the
    nearest (in thousand-yard steps) and then the densest wins, and the spawn
    sent to is the real one nearest that cell's middle.
    """
    low, high = skin_band(level, value)
    if high < low or origin is None:
        return None
    cells = {}
    for spot, beast_level in beasts or ():
        if not low <= _int(beast_level) <= high:
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
        name=spot.name or "a pack of beasts",
        why="%d skinnable beasts of levels %d to %d" % (count, low, high),
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


# ---------------------------------------------------------------------------
# THE STEPS.


def _train_step(member, trades, cap, recent=()):
    """Buy the next rank of one of its trades, the cheapest first."""
    if member.level < TRAIN_MIN_LEVEL and trades.get(member.name):
        return None, "%s learns a trade from level %d" % (member.name, TRAIN_MIN_LEVEL)
    wants, cooling = [], []
    for skill in trades.get(member.name, ()):
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


def _open_recipe(member, skill):
    """The recipe this member would cast toward `skill`, cloth or not in hand.

    It is the one craft.py keeps for the member's skill value (its colour
    band), made of cloth alone: a recipe with a vendor reagent or a forge or
    loom is left to the passes that walk there. None at the ceiling, where a
    rank comes first.
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


def _craft_recipe(member, skill):
    """(recipe, casts) this member can cast now toward `skill`, or (None, 0)."""
    recipe = _open_recipe(member, skill)
    if recipe is None:
        return None, 0
    reagents = craft_rhythm.GATHERED[recipe.spell_id]
    casts = min(member.count(r.entry) // max(1, int(r.per_cast)) for r in reagents)
    return (recipe, min(casts, CRAFT_BATCH)) if casts > 0 else (None, 0)


def craft_entries(member) -> frozenset:
    """The items this member's next cloth casts eat, which it keeps."""
    out = set()
    for skill in CRAFT_SKILLS:
        recipe = _open_recipe(member, skill)
        if recipe is not None:
            out.update(int(r.entry) for r in craft_rhythm.GATHERED[recipe.spell_id])
    return frozenset(out)


def _craft_step(member):
    """Cast what its cloth allows, to raise First Aid and Tailoring (#421).

    Linen Bandage takes a Linen Cloth and Bolt of Linen Cloth two; both grant
    skill to the cast and both are the member's own to make, where it stands.
    The rows are `cast` rows, the verb a player has, and the trade came from a
    trainer that was paid.
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
            % (member.name, casts, recipe.name, SKILL_NAMES[skill]),
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
        (c for c in member.carried if c.junk and not _kept(member.name, c, kept)),
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
    if not character or not (
        gearup.gear_short(character) or gearup.stale_gear(character)
    ):
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


def consumes_at(skill: int, value: int, entry: int) -> bool:
    """Whether a recipe of `skill` castable at `value` eats item `entry`."""
    if int(value) < CRAFTER_FLOOR:
        return False
    for recipe in craft.RECIPES.get(int(skill), ()):
        if recipe.min_skill > int(value):
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


def postable(member: Member, kept) -> list:
    """The material stacks this member would post, biggest first."""
    bar = POST_MIN.get(member.role, POST_MIN[RAIDER])
    # Cloth its own next casts eat stays in the bags: a member that can still
    # raise First Aid or Tailoring does not post away what it would cast.
    eaten = craft_entries(member) if member.role == MAINTENANCE else frozenset()
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


def _post_step(member, crafters, master, kept, cap):
    stacks = postable(member, kept)[:MAX_LETTERS]
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
    junk = [c for c in member.carried if c.junk and not _kept(member.name, c, kept)]
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
        "%s walks to a vendor to sell %d grey stack(s) worth %dc"
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
# THE PLAN.


def _maintenance_step(m, trades, fields, crafters, master, kept, recent, cap):
    """(step or None, what it does now, a note or "")."""
    notes = []
    step, why = _train_step(m, trades, cap, recent)
    if step:
        return step, step.said, ""
    if why:
        notes.append(why)
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
    shared = _shared_step(m, crafters, master, kept, recent, cap)
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


def _shared_step(m, crafters, master, kept, recent, cap):
    """Post, then sell: what every role does with what it carries."""
    if not _cooling(m, "post", recent):
        step, why = _post_step(m, crafters, master, kept, cap)
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
) -> JobsPlan:
    """Every member's job this pass, and the steps to start.

    `masters` guild -> guild master; `crafters` guild -> {skill: [(family
    name, value)]}; `fields` name -> Spot a maintenance member gathers at;
    `doors` name -> Door (assign_doors); `pending` names a summon waits on;
    `kept` keep.Reservations; `recent` Recent rows; `busy`
    names another pass has on a walk; `unclaimed` names family members with a
    materials post still unopened in their mailbox (`without_unclaimed`);
    `banks` the guilds that own a guild bank tab, None when unread; `gear`
    name -> (gearup facts, vendor rows in reach) for gear-short members.
    """
    masters = bank_masters(masters or {}, banks, unclaimed)
    crafters = without_unclaimed(crafters or {}, unclaimed)
    fields = fields or {}
    doors = doors or {}
    busy = {str(n) for n in busy or ()}
    pending = {str(n) for n in pending or ()}
    tailors = choose_tailors(members)
    trades = cloth_trades(split_trades(members, tailors), tailors)
    steps, lines, notes = [], {}, []
    # One counter per allowance, each keyed by guild: STEPS_PER_GUILD for
    # every job, GEAR_STEPS_PER_GUILD for gear and hearth steps.
    started_jobs, started_gear = {}, {}
    for m in _ordered_members(members):
        if m.role not in (MAINTENANCE, SUMMONER, RAIDER):
            continue
        master = str(masters.get(m.guild) or "")
        step, doing, note = _member_step(
            m,
            (gear or {}).get(m.name),
            trades,
            fields,
            doors,
            pending,
            crafters,
            master,
            kept,
            recent,
            cap,
        )
        lines[m.name] = doing
        if note:
            notes.append(note)
        if step is None:
            continue
        gearing = step.action in ("gear", "hearth")
        started = started_gear if gearing else started_jobs
        why = _step_refusal(
            m, busy, started, GEAR_STEPS_PER_GUILD if gearing else per_guild
        )
        if why:
            notes.append(why)
            continue
        started[m.guild] = started.get(m.guild, 0) + 1
        busy.add(m.name)
        steps.append(step)
    return JobsPlan(
        steps=tuple(steps),
        lines=lines,
        trades=trades,
        doors=doors,
        notes=tuple(notes),
    )


def _member_step(
    m, offer, trades, fields, doors, pending, crafters, master, kept, recent, cap
):
    """Gear first, then the member's ordinary job, keeping both notes."""
    step, doing, gear_note = _gear_first(m, offer, recent, cap, kept)
    if step is not None:
        return step, doing, gear_note
    step, doing, note = _plan_member(
        m, trades, fields, doors, pending, crafters, master, kept, recent, cap
    )
    return step, doing, "; ".join(n for n in (gear_note, note) if n)


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
    m, trades, fields, doors, pending, crafters, master, kept, recent, cap
):
    if not m.eligible:
        return None, "waits for its natural restart; nothing it holds is counted", ""
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
            )
        )
    return tuple(out)


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
