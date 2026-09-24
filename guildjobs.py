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
                  lets it go and its own gather and grind strategies work.
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
import dungeonpath
import guildcorps
import guildroute
import keep

HERBALISM = guildcorps.HERBALISM
MINING = guildcorps.MINING
SKINNING = guildcorps.SKINNING
GATHERING = (HERBALISM, MINING, SKINNING)
SKILL_NAMES = {HERBALISM: "Herbalism", MINING: "Mining", SKINNING: "Skinning"}

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
    "train": 60,
    "tool": 60,
    "post": 60,
    "sell": 120,
    "farm": 45,
    "door": 45,
}

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
    return any(
        r.name == member.name and r.action == action and int(r.age_minutes) < minutes
        for r in recent or ()
    )


# ---------------------------------------------------------------------------
# THE TRADE SPLIT.


def split_trades(members) -> dict:
    """name -> (skill, skill): the two gathering trades each maintenance
    member works, per guild. See TRADE SPLIT in the module docstring."""
    out = {}
    crews = {}
    for m in members or ():
        if m.role == MAINTENANCE:
            crews.setdefault(m.guild, []).append(m)
    for _guild, crew in sorted(crews.items()):
        counts = {s: 0 for s in GATHERING}
        crew = sorted(crew, key=lambda m: m.name)
        # What the crew already holds is counted first, so a member who
        # learned a trade on its own keeps it and the split fills round it.
        for m in crew:
            for s in GATHERING:
                if m.holds(s):
                    counts[s] += 1
        for m in crew:
            held = [s for s in GATHERING if m.holds(s)]
            others = [s for s in m.primaries if s not in GATHERING]
            room = max(0, MAX_PRIMARY - len(held) - len(others))
            wanted = list(held)
            while room > 0:
                free = [s for s in GATHERING if s not in wanted]
                if not free:
                    break
                pick = min(free, key=lambda s: (counts[s], GATHERING.index(s)))
                wanted.append(pick)
                counts[pick] += 1
                room -= 1
            out[m.name] = tuple(wanted)
    return out


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


def _train_step(member, trades, cap):
    """Buy the next rank of one of its trades, the cheapest first."""
    wants = []
    for skill in trades.get(member.name, ()):
        value, ceiling = member.skill(skill)
        rank = next_rank(skill, value, ceiling, member.level)
        if rank is not None:
            wants.append((rank.cost, skill, rank))
    if not wants:
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


def recipient_for(item: Carried, crafters: dict, master: str) -> tuple:
    """(who, why) a material goes to: the guild's crafter of the trade that
    uses it, else the guild master for the Materials tab.

    `crafters` maps a skill line to [(name, value)] of the family members of
    this guild who hold it.
    """
    for skill in CONSUMERS.get(int(item.subclass), ()):
        holders = sorted(crafters.get(skill, ()), key=lambda p: (-int(p[1]), p[0]))
        if holders:
            return holders[0][0], "its crafter"
    return master, "the guild bank's Materials tab"


def postable(member: Member, kept) -> list:
    """The material stacks this member would post, biggest first."""
    bar = POST_MIN.get(member.role, POST_MIN[RAIDER])
    out = [
        c
        for c in member.carried
        if c.material and int(c.count) >= bar and not _kept(member.name, c, kept)
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
                "send item:%d subject:%s" % (int(c.guid), "Guild materials"),
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
    if not _cooling(m, "train", recent):
        step, why = _train_step(m, trades, cap)
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
    shared = _shared_step(m, crafters, master, kept, recent, cap)
    if shared[0]:
        return shared
    if shared[2]:
        notes.append(shared[2])
    spot = fields.get(m.name)
    gathering = [SKILL_NAMES[s] for s in GATHERING if m.holds(s)]
    if spot is not None and not _near(m, spot, FIELD_REACH):
        if not _cooling(m, "farm", recent):
            said = "%s walks to %s to gather (%s)" % (
                m.name,
                spot.name or "a field",
                spot.why,
            )
            return _spot_step(m, spot, "farm", cap, said), said, ""
    if spot is not None:
        doing = "gathers %s at %s" % (
            " and ".join(gathering) or "what it can",
            spot.name,
        )
    elif gathering:
        doing = "gathers %s where it levels" % " and ".join(gathering)
    else:
        doing = "levels, and learns its trades once it can pay a trainer"
    return None, doing, "; ".join(notes)


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
) -> JobsPlan:
    """Every member's job this pass, and the steps to start.

    `masters` guild -> guild master; `crafters` guild -> {skill: [(family
    name, value)]}; `fields` name -> Spot a maintenance member gathers at;
    `doors` name -> Door (assign_doors); `pending` names a summon waits on;
    `kept` keep.Reservations; `recent` Recent rows; `busy`
    names another pass has on a walk.
    """
    masters = masters or {}
    crafters = crafters or {}
    fields = fields or {}
    doors = doors or {}
    busy = {str(n) for n in busy or ()}
    pending = {str(n) for n in pending or ()}
    trades = split_trades(members)
    steps, lines, notes = [], {}, []
    started = {}
    order = {MAINTENANCE: 0, SUMMONER: 1, RAIDER: 2}
    for m in sorted(
        members or (), key=lambda m: (order.get(m.role, 3), m.guild, m.name)
    ):
        if m.role not in order:
            continue
        if not m.eligible:
            lines[m.name] = "waits for its natural restart; nothing it holds is counted"
            continue
        master = str(masters.get(m.guild) or "")
        if m.role == MAINTENANCE:
            step, doing, note = _maintenance_step(
                m, trades, fields, crafters, master, kept, recent, cap
            )
        elif m.role == SUMMONER:
            step, doing, note = _summoner_step(
                m, doors, pending, crafters, master, kept, recent, cap
            )
        else:
            step, doing, note = _shared_step(m, crafters, master, kept, recent, cap)
            doing = doing or "levels toward the raid and raids when the guild does"
        lines[m.name] = doing
        if note:
            notes.append(note)
        if step is None:
            continue
        why = ""
        if not m.online:
            why = "%s is offline" % m.name
        elif m.in_combat:
            why = "%s is in combat" % m.name
        elif m.name in busy:
            why = "%s is already on another guild walk" % m.name
        elif started.get(m.guild, 0) >= int(per_guild):
            why = "%s waits: %d guild job steps per guild per pass" % (
                m.name,
                int(per_guild),
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

    def put(member, role):
        name = member.get("name")
        member["job"] = role
        member["work"] = job_line(
            role, doing.get(name, ""), posted.get(name), dues.get(name)
        )
        t = totals[role]
        t["copper"] += int((dues.get(name) or {}).get("copper") or 0)
        t["items"] += int((posted.get(name) or {}).get("items") or 0)
        t["sold"] += int((posted.get(name) or {}).get("sold") or 0)

    for group in lineup.get("groups") or ():
        for member in group.get("members") or ():
            if member.get("name") not in family:
                put(member, RAIDER)
    for member in lineup.get("maintenance") or ():
        put(member, MAINTENANCE)
    for member in lineup.get("summoners") or ():
        put(member, SUMMONER)
    lineup["given"] = {
        "by_role": totals,
        "said": "given: "
        + "; ".join(
            "%s %s in dues, %d item(s) posted, %s of grey loot sold"
            % (
                role,
                _gold(totals[role]["copper"]),
                totals[role]["items"],
                _gold(totals[role]["sold"]),
            )
            for role in ROLE_ORDER
        ),
    }
    return lineup


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
            )
        )
    return tuple(out)


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
