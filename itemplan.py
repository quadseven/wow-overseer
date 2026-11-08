"""One plan for every stack a guild member carries or banks (#1967).

WHY. Six passes each hold a piece of the answer and none sees the whole bag.
`bag_pressure.sellable` refuses any reagent, any stack a family trade uses,
anything above common and anything with no vendor price. `jev_keep` asks Jev
about the protected stacks one at a time, in shadow. `bankpolicy` files gear
for later and raid supplies. `clearance` routes gems and recipes. `disposition`
judges gear. `guildshare` feeds guildmates. Each says "not mine" to the rest,
so a stack nobody owns stays. Measured 2026-11-07 on the Zug family (level 54):
two members carried 67 and 60 items in 72 and 68 slots, held 28 of 28 bank
slots, and shared a guild bank tab that was 98 of 98 full. The sale pass saw 2
and 10 candidates of about 90 stacks. The dungeon run waits for 8 free slots.

THE QUESTION. For every stack, for every member: where should it be, and why.
One of KEEP_CARRY, BANK_PERSONAL, GUILD_BANK (a tab), GIVE (a family member),
AUCTION, SELL_VENDOR, DISENCHANT or DESTROY, each with a reason string, the
goal it serves and the rule that decided it.

MEASURED. `tools/itemplan_simulate.py` runs this over the 2026-11-07 dump of
both families (10 members, 1,299 rows). `docs/ITEM_PLAN.md` holds the table.

PURE. Rows in, a Plan out. No MySQL, no HTTP, no clock, no randomness. The
only imports are this repo's own tables (craft ladders, supplies, guild bank
tabs) so a recipe or tab change reaches this plan without a second copy.
`itemplan_shadow` runs it beside the economy pass (#1972).

THE ORDERED RULES. The first rule that claims a stack decides its options; the
allocation step then picks the first option that has room. Goals are ranked by
TIER, and inside a tier by vendor copper per slot, so "lowest value per slot
leaves first" is one fixed order, not a mood.

  R1  fail closed. A row with a binding or quality this module cannot read is
      kept. (`disposition`: every unknown resolves to KEEP.)
  R2  worn bags, keys and the hearthstone stay. Extends `bag_upgrade`.
  R3  quest items. An open quest names the item: KEEP_CARRY. A quest log that
      was not read keeps every quest-class stack and never sells or destroys
      one. Extends `bag_pressure.QUEST_NEEDED_SQL`.
  R4  the holder's equipped or about-to-wear gear (gear pass verdict).
  R5  a trade tool for a member who works the trade (`disposition.TOOL_TRADES`).
  R6  Molten Core: raid supplies, their reagents, fire resistance gear go to
      the Raid Supplies tab, or stay banked with the member who crafts them.
      Extends `bankpolicy` rule 3 and `raidsupply.SUPPLIES`.
  R7  trade stock. A member's trade at its CURRENT skill range keeps the
      reagents of recipes still giving skill points, carried. The NEXT range
      keeps a smaller stock, banked. The family member who works the trade
      gets the surplus from the others (GIVE). Replaces
      `disposition.profession_keeps` and `material_keeps` for this plan.
  R8  gear for anybody in the family, by binding: soulbound gear belongs to its
      holder only; bind-on-equip gear goes to the sibling who will wear it.
      Rare and better for a later level goes to the Gear for Later tab.
      Extends `bankpolicy` rule 4 and `disposition.decide`.
  R9  recipes: learnable by a family member within a range, kept or given;
      raid recipes never sold; the rest to the guild or the vendor.
      Extends `clearance`.
  R10 surplus materials: guild Materials tab, then vendor. Extends
      `clearance` and `guildshare.FEEDS`.
  R11 everything else with a vendor price: AUCTION when a price beats the
      vendor by `AUCTION_BEATS_VENDOR_BY`, else SELL_VENDOR.
  R12 no price, no use: DESTROY, and only then, after bank and give.

THE SAFE LINE (requirement 5). DESTROY needs a vendor price of 0, no market
price, quality 2 or less, no binding that someone could use and no claimant.
Every SELL_VENDOR, DISENCHANT and DESTROY row is `irreversible` and
`refusable`: the executor may skip it and the next pass asks again. A stack
worth `CONFIRM_VALUE` copper or more, or of quality 3 or better, is marked
`confirm`: shadow shows it, a person or a later rollout step releases it.

CAPACITY. A member has `BAG_FLOOR` free slots to protect (the town-first guard
and dungeon admission need 8) plus `BAG_MARGIN`. Eviction starts when free
carried slots fall under `TRIGGER_FREE` and stops at `TARGET_FREE`. That gap
is the hysteresis: a stack evicted at 9 free is not pulled back at 10.

NO FLIP-FLOP. Decisions depend only on the stack, the member and the world
facts, never on random order. `Context.previous` carries last pass's routes:
a stack planned for a bank or the vendor is not pulled back to the bag by a
discretionary goal, a planned irreversible route changes only when a real need
appears, and an auction listing holds down to `AUCTION_HOLD_FACTOR` where it
needed `AUCTION_BEATS_VENDOR_BY` to start.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Mapping

import craft
import craft_rhythm
import craft_supply
import disposition
import guildbank
import guildshare
import raidsupply

# ---------------------------------------------------------------------------
# Routes, goals, tiers.

KEEP_CARRY = "KEEP_CARRY"
BANK_PERSONAL = "BANK_PERSONAL"
GUILD_BANK = "GUILD_BANK"
GIVE = "GIVE"
AUCTION = "AUCTION"
SELL_VENDOR = "SELL_VENDOR"
DISENCHANT = "DISENCHANT"
DESTROY = "DESTROY"
ROUTES = (
    KEEP_CARRY,
    BANK_PERSONAL,
    GUILD_BANK,
    GIVE,
    AUCTION,
    SELL_VENDOR,
    DISENCHANT,
    DESTROY,
)
IRREVERSIBLE = frozenset({SELL_VENDOR, DISENCHANT, DESTROY})
# The reason prefix of a stack that no destination had room for (#1973). The
# stack stays where it is; a reader of the log searches for this word.
NO_ROOM = "NO_ROOM"

# Goal -> tier. Higher is more protected. A stack's priority is (tier, vendor
# copper per slot); the lowest priority leaves a full bag first.
QUEST, EQUIPMENT, ATTUNEMENT, FAMILY_UPGRADE, TOOLS = (
    "quest",
    "equipment",
    "attunement",
    "family upgrade",
    "trade tools",
)
TRADE_NOW, RAID_NIGHT, CONSUMABLE, TRADE_NEXT, GEAR_LATER = (
    "trade skill-up now",
    "raid night",
    "run consumables",
    "trade skill-up next range",
    "gear for later",
)
BAG_ROOM, RECIPE, SURPLUS, ROOM = (
    "bag room",
    "recipe",
    "surplus to a better place",
    "bag room (no use)",
)
TIER = {
    QUEST: 100,
    EQUIPMENT: 90,
    ATTUNEMENT: 85,
    FAMILY_UPGRADE: 80,
    TOOLS: 75,
    TRADE_NOW: 70,
    RAID_NIGHT: 65,
    CONSUMABLE: 60,
    TRADE_NEXT: 50,
    GEAR_LATER: 40,
    BAG_ROOM: 38,
    RECIPE: 35,
    SURPLUS: 20,
    ROOM: 0,
}
# A discretionary carry (a tier under this) never pulls a banked stack back.
MANDATORY_TIER = TIER[TRADE_NOW]

# Item locations in the dump.
BACKPACK, CARRIED_BAG, BANK, BANK_BAG, WORN = (
    "backpack",
    "carried_bag",
    "bank",
    "bank_bag",
    "equipped_or_other",
)
CARRIED = frozenset({BACKPACK, CARRIED_BAG})
BANKED = frozenset({BANK, BANK_BAG})
_LOC_ORDER = {BACKPACK: 0, CARRIED_BAG: 1, BANK: 2, BANK_BAG: 3, WORN: 4}

# item_template.Bonding.
BIND_NONE, BIND_PICKUP, BIND_EQUIP, BIND_USE, BIND_QUEST = 0, 1, 2, 3, 4
_KNOWN_BINDS = frozenset({BIND_NONE, BIND_PICKUP, BIND_EQUIP, BIND_USE, BIND_QUEST})

# item_template.class.
C_CONSUMABLE, C_CONTAINER, C_WEAPON, C_GEM, C_ARMOR = 0, 1, 2, 3, 4
C_REAGENT, C_TRADE, C_RECIPE, C_QUEST, C_KEY, C_MISC = 5, 7, 9, 12, 13, 15
HEARTHSTONE = 6948

# ---------------------------------------------------------------------------
# Conventions. Each is a judgment, named so a reader can move it.

BAG_FLOOR = 8  # free carried slots the town-first guard and dungeon admission need
BAG_MARGIN = 2
TRIGGER_FREE = BAG_FLOOR + BAG_MARGIN  # evict when free carried slots fall under this
TARGET_FREE = TRIGGER_FREE + 2  # ...and stop here (the hysteresis gap)
BANK_RESERVE = 2  # personal bank slots kept free for the next deposit
BANK_JUNK_FLOOR = 6  # junk with no price banks only while this many slots stay free
GIVE_FLOOR = 3  # a recipient keeps this many free carried slots after a gift
# Only the best few unjudged soulbound pieces are a second set, not a hoard
# (`bankpolicy` rule 2: "a set is a set and not a hoard").
SPARE_SET_MAX = 6
UPGRADE_WINDOW = 5  # a piece up to this many levels above a member is for later
OUTGROWN_MARGIN = 10  # `disposition.outgrown`'s margin
NOW_CASTS = craft_rhythm.STOCK_CASTS  # casts stocked for a recipe in the current range
NEXT_CASTS = craft_rhythm.SHORT_CASTS  # casts stocked for a recipe in the next range
NEED_CAP = disposition.MATERIAL_KEEP  # units one member keeps of one material
BAND_KEEP = disposition.REAGENT_KEEP  # units kept by the band rule (no recipe data)
RANGE = 75  # a skill range: 1-75, 75-150, 150-225, 225-300
AUCTION_BEATS_VENDOR_BY = disposition.AUCTION_BEATS_VENDOR_BY
AUCTION_HOLD_FACTOR = 3  # a listing holds down to this multiple of the vendor price
AUCTION_CUT_PERCENT = 5
AUCTION_MIN_GAIN = 5_000  # copper a listing must clear over the vendor, net of the cut
CONFIRM_VALUE = 10_000  # copper (1 gold): a sale this large waits for a release
DE_VENDOR_CEILING = 50_000  # copper: dearer gear than this is sold, not broken down
FOOD_STACKS_KEPT = 3  # carried food and drink stacks kept per member
GUILD_TAB_MATERIALS = guildbank.TABS[0].tab_id
GUILD_TAB_GEAR = guildbank.TABS[1].tab_id
GUILD_TAB_RAID = guildbank.TABS[2].tab_id
TAB_SLOTS = 98
BANK_WORTH = 5_000  # copper per slot: a stack worth more banks before it is sold
PERSONAL_BANK_SLOTS = 28
BACKPACK_SLOTS = 16
CARRIED_BAGS = 4

TRADE_OF_SKILL = {v: k for k, v in guildshare.SKILL_LINES.items()}
FISHING = 356

# Recipe item subclass -> trade (class 9).
RECIPE_TRADE = {
    1: "leatherworking",
    2: "tailoring",
    3: "engineering",
    4: "blacksmithing",
    5: "cooking",
    6: "alchemy",
    7: "first aid",
    8: "enchanting",
    9: "fishing",
    10: "jewelcrafting",
}


# Disenchant skill by item level (classic): 5 * (ilvl - 21) from ilvl 26, 1 up
# to it. A convention until the data ticket reads the core's own table; the
# plan only breaks down what an enchanter at that skill can break down.
def disenchant_skill(item_level: int) -> int:
    return max(1, 5 * (int(item_level) - 21)) if item_level > 25 else 1


# Armor each class wears, by item level of the member (classic proficiencies).
CLOTH, LEATHER, MAIL, PLATE, SHIELD = 1, 2, 3, 4, 6
WARRIOR, PALADIN, HUNTER, ROGUE, PRIEST, SHAMAN, MAGE, WARLOCK, DRUID = (
    1,
    2,
    3,
    4,
    5,
    7,
    8,
    9,
    11,
)


def preferred_armor(class_id: int, level: int) -> int:
    """The armor type a class actually wants at a level."""
    if class_id in (PRIEST, MAGE, WARLOCK):
        return CLOTH
    if class_id in (ROGUE, DRUID):
        return LEATHER
    if class_id in (HUNTER, SHAMAN):
        return MAIL if level >= 40 else LEATHER
    if class_id in (WARRIOR, PALADIN):
        return PLATE if level >= 40 else MAIL
    return CLOTH


_SHIELD_CLASSES = frozenset({WARRIOR, PALADIN, SHAMAN})
# Weapon subclass -> proficient classes (classic).
_WEAPON_CLASSES = {
    0: {WARRIOR, PALADIN, HUNTER, SHAMAN},
    1: {WARRIOR, PALADIN, HUNTER, SHAMAN},
    2: {WARRIOR, HUNTER, ROGUE},
    3: {WARRIOR, HUNTER, ROGUE},
    4: {WARRIOR, PALADIN, ROGUE, PRIEST, SHAMAN, DRUID},
    5: {WARRIOR, PALADIN, SHAMAN, DRUID},
    6: {WARRIOR, PALADIN, HUNTER, DRUID},
    7: {WARRIOR, PALADIN, HUNTER, ROGUE, MAGE, WARLOCK},
    8: {WARRIOR, PALADIN, HUNTER},
    10: {WARRIOR, HUNTER, PRIEST, SHAMAN, MAGE, WARLOCK, DRUID},
    13: {WARRIOR, HUNTER, ROGUE, SHAMAN, DRUID},
    15: {WARRIOR, HUNTER, ROGUE, PRIEST, SHAMAN, MAGE, WARLOCK, DRUID},
    16: {WARRIOR, HUNTER, ROGUE},
    18: {WARRIOR, HUNTER, ROGUE},
    19: {PRIEST, MAGE, WARLOCK},
}

# Class reagents carried for a spell: entry -> classes that cast with it.
CLASS_REAGENTS = {17056: frozenset({PRIEST})}  # Light Feather: Levitate


# ---------------------------------------------------------------------------
# Inputs.


@dataclass(frozen=True)
class Stack:
    """One occupied slot, as the dump or the item query reports it."""

    holder: str
    loc: str
    entry: int
    name: str
    item_class: int
    subclass: int
    quality: int
    count: int
    sell: int  # vendor copper per unit
    bind: int | None
    req_level: int = 0
    item_level: int = 0
    stackable: int = 1
    index: int = 0  # row order within the holder, the last tie-break
    required_skill_rank: int | None = None
    container_slots: int | None = None
    fire_res: int | None = None
    soulbound: bool | None = None

    @property
    def key(self) -> tuple:
        return (self.holder, _LOC_ORDER.get(self.loc, 9), self.entry, self.index)

    @property
    def value(self) -> int:
        return max(0, self.sell) * max(1, self.count)

    @property
    def carried(self) -> bool:
        return self.loc in CARRIED

    @property
    def banked(self) -> bool:
        return self.loc in BANKED

    @property
    def gear(self) -> bool:
        return self.item_class in (C_WEAPON, C_ARMOR)

    @property
    def tradable(self) -> bool:
        """Soulbound and quest-bound stacks cannot be given or listed."""
        return self.soulbound is False and self.bind in (
            BIND_NONE,
            BIND_EQUIP,
            BIND_USE,
        )


@dataclass(frozen=True)
class Member:
    name: str
    family: str
    level: int
    class_id: int
    skills: tuple = ()  # ((skill id, value, max), ...)
    carried_slots: int = BACKPACK_SLOTS + CARRIED_BAGS * 12
    bank_slots: int = PERSONAL_BANK_SLOTS
    empty_bank_positions: int = 0

    def skill(self, trade: str) -> int:
        line = guildshare.SKILL_LINES.get(trade, -1)
        return max((v for s, v, _m in self.skills if s == line), default=0)

    def trades(self) -> tuple:
        return tuple(
            sorted(
                {
                    TRADE_OF_SKILL[s]
                    for s, v, _m in self.skills
                    if s in TRADE_OF_SKILL and s != FISHING and v > 0
                }
            )
        )


@dataclass(frozen=True)
class Context:
    """World facts the plan reads. Every field has a conservative default."""

    # None means the quest log was not read: every quest-class stack is kept.
    open_quest_items: Mapping[str, frozenset] | None = None
    # (holder, entry) -> "wear" | "not better": the gear passes' own verdict.
    gear_verdict: Mapping[tuple, str] = field(default_factory=dict)
    # entry -> (copper per unit, live listings). Absent means no price data.
    market: Mapping[int, tuple] = field(default_factory=dict)
    # (family, tab id) -> free slots. Absent means unknown, treated as full.
    guild_free: Mapping[tuple, int] = field(default_factory=dict)
    # guildmates outside the family who work a trade: ((name, trade, skill), ...)
    guild_crafters: tuple = ()
    # None means per-item fire resistance was not read.
    fire_gear: frozenset | None = None
    # entries an attunement or a key quest needs besides the open quests
    attunement_items: frozenset = frozenset()
    # (holder, entry) -> route chosen on the previous pass
    previous: Mapping[tuple, str] = field(default_factory=dict)
    raid_night: bool = False


@dataclass(frozen=True)
class Decision:
    holder: str
    entry: int
    name: str
    count: int
    from_loc: str
    route: str
    goal: str
    reason: str
    rule: str
    target: str = ""  # tab name, recipient, or ""
    tab: int = -1
    value: int = 0
    irreversible: bool = False
    refusable: bool = False
    confirm: bool = False
    stuck: bool = False
    key: tuple = ()
    options: tuple = ()  # the routes considered, best first


@dataclass(frozen=True)
class Option:
    route: str
    goal: str
    reason: str
    rule: str
    target: str = ""
    tab: int = -1
    cap_group: tuple = ()  # (group id, max members) shares a limited place
    cap_rank: tuple = ()  # lower sorts first inside the group
    carry_forced: bool = False
    cap_units: bool = False  # the group's size counts units, not stacks


@dataclass(frozen=True)
class Plan:
    decisions: tuple
    members: tuple
    notes: tuple = ()

    def by_holder(self, holder: str) -> tuple:
        return tuple(d for d in self.decisions if d.holder == holder)

    def routes(self) -> dict:
        return {(d.holder, d.entry): d.route for d in self.decisions}

    def count(self, holder: str, route: str) -> int:
        return sum(1 for d in self.by_holder(holder) if d.route == route)


# ---------------------------------------------------------------------------
# Capacity.


def capacities(
    worn_bags: Iterable[Stack], bank_positions: int
) -> tuple[int, int, int, tuple]:
    """(carried slots, bank slots, empty bank positions, spare positions' bags).

    The dump does not say which worn bag sits where. The four largest are the
    carried bags (a player wears the biggest) and the rest are bank bags.
    """
    bags = sorted(
        (b for b in worn_bags if b.item_class == C_CONTAINER),
        key=lambda b: (-(b.container_slots or 0), b.entry, b.index),
    )
    sizes = [max(0, int(b.container_slots or 0)) for b in bags]
    carried = sizes[:CARRIED_BAGS]
    bank = sizes[CARRIED_BAGS:]
    empty = max(0, int(bank_positions) - len(bank))
    return (
        BACKPACK_SLOTS + sum(carried),
        PERSONAL_BANK_SLOTS + sum(bank),
        empty,
        tuple(bank),
    )


# ---------------------------------------------------------------------------
# What a trade needs.


def _recipe_inputs(spell: int) -> list:
    """(entry, label, per cast) for everything one cast of `spell` consumes."""
    out = []
    for r in craft_rhythm.GATHERED.get(spell, ()):
        out.append((r.entry, r.label, r.per_cast))
    for row in craft_supply.REAGENTS.get(spell, ()):
        out.append((row[0], row[1], row[3]))
    single = craft_supply.REAGENT.get(spell)
    if single:
        out.append((single[0], single[1], 1))
    fed = craft_rhythm.BOLT_FED.get(spell)
    if fed:
        bolt_spell, bolt = fed
        out.append((bolt.entry, bolt.label, bolt.per_cast))
        # The bolt itself is cut from raw cloth: its inputs per bolt.
        for r in craft_rhythm.GATHERED.get(bolt_spell, ()):
            out.append((r.entry, r.label, r.per_cast * bolt.per_cast))
    return out


def range_top(skill: int) -> int:
    return RANGE * (int(skill) // RANGE + 1)


def trade_needs(member: Member) -> dict:
    """entry -> {"now": units, "next": units, "trades": [..]} for one member.

    A recipe whose grey value is under the member's skill gives no skill-up and
    asks for nothing. A recipe overlapping [skill, top of this range] is NOW;
    one overlapping the next range is NEXT. One recipe is cast at a time, so a
    trade's need for a material is the largest recipe's, and trades add up.
    """
    needs: dict = {}
    for skill_id, value, _max in member.skills:
        trade = TRADE_OF_SKILL.get(skill_id)
        if not trade or skill_id == FISHING or value <= 0:
            continue
        top = range_top(value)
        per_trade: dict = {}
        for r in craft.RECIPES.get(skill_id, ()):
            if r.max_skill < value:
                continue
            if r.min_skill <= top:
                window, casts = "now", NOW_CASTS
            elif r.min_skill <= top + RANGE:
                window, casts = "next", NEXT_CASTS
            else:
                continue
            for entry, _label, per_cast in _recipe_inputs(r.spell_id):
                cell = per_trade.setdefault(entry, {"now": 0, "next": 0})
                cell[window] = max(cell[window], per_cast * casts)
        for entry, cell in per_trade.items():
            slot = needs.setdefault(entry, {"now": 0, "next": 0, "trades": []})
            slot["now"] = min(NEED_CAP, slot["now"] + cell["now"])
            slot["next"] = min(NEED_CAP, slot["next"] + cell["next"])
            slot["trades"].append(trade)
    return needs


def _covered_trades() -> frozenset:
    return frozenset(TRADE_OF_SKILL[s] for s in craft.RECIPES if s in TRADE_OF_SKILL)


def tier_skill(item_level: int) -> int:
    """The skill a raw material's tier asks, from its item level (band rule)."""
    return max(1, (int(item_level) - 5) * 5)


def band_need(member: Member, stack: Stack) -> str | None:
    """The band rule, for a trade the craft tables do not cover.

    A material that FEEDS a trade the member works is in range when its tier is
    within the current range and the next one. Returns the trade, else None.
    """
    covered = _covered_trades()
    for trade in guildshare.FEEDS.get(stack.subclass, ()):
        if trade in covered:
            continue
        value = member.skill(trade)
        if value > 0 and tier_skill(stack.item_level) <= range_top(value) + RANGE:
            return trade
    return None


# ---------------------------------------------------------------------------
# Who wears what.


def wearable(stack: Stack, member: Member) -> bool:
    if stack.item_class == C_WEAPON:
        return member.class_id in _WEAPON_CLASSES.get(stack.subclass, ())
    if stack.item_class != C_ARMOR:
        return False
    if stack.subclass == 0:  # rings, necklaces, trinkets
        return True
    if stack.subclass == SHIELD:
        return member.class_id in _SHIELD_CLASSES
    return stack.subclass == preferred_armor(member.class_id, member.level)


def wanted_by(stack: Stack, member: Member) -> str | None:
    """ "now", "later" or None: would `member` wear this piece."""
    if not wearable(stack, member):
        return None
    if stack.req_level + OUTGROWN_MARGIN <= member.level:
        return None
    if stack.req_level > member.level + UPGRADE_WINDOW:
        return None
    return "now" if stack.req_level <= member.level else "later"


# ---------------------------------------------------------------------------
# Rules. Each returns a list of Options (best first) or None.


def _opt(route, goal, reason, rule, **kw) -> Option:
    return Option(route, goal, reason, rule, **kw)


def _vendor_options(stack: Stack, rule: str, why: str, goal=ROOM) -> list:
    out = []
    if stack.sell > 0 and stack.quality <= 3:
        out.append(_opt(SELL_VENDOR, goal, why, rule))
    return out


def _destroy_allowed(stack: Stack, ctx: Context) -> bool:
    return (
        stack.sell <= 0
        and stack.quality <= 2
        and stack.entry not in ctx.market
        and stack.bind in (BIND_NONE, BIND_EQUIP, BIND_USE, BIND_PICKUP)
        and stack.item_class
        not in (C_QUEST, C_KEY, C_CONTAINER, C_RECIPE, C_GEM, C_TRADE, C_REAGENT)
    )


class _World:
    """Facts shared by every rule for one run."""

    def __init__(self, stacks, members, ctx):
        self.ctx = ctx
        self.members = {m.name: m for m in members}
        self.by_family: dict = {}
        for m in sorted(members, key=lambda m: m.name):
            self.by_family.setdefault(m.family, []).append(m)
        self.needs = {m.name: trade_needs(m) for m in members}
        self.stacks = stacks
        held: dict = {}
        for s in stacks:
            held[(s.holder, s.entry)] = held.get((s.holder, s.entry), 0) + s.count
        self.held = held
        self.enchanters = self._enchanters()

    def siblings(self, holder: str) -> list:
        me = self.members[holder]
        return [m for m in self.by_family.get(me.family, []) if m.name != holder]

    def _enchanters(self) -> list:
        out = [
            (m.name, m.skill("enchanting"), m.family)
            for m in self.members.values()
            if m.skill("enchanting") > 0
        ]
        out += [
            (n, sk, "") for n, tr, sk in self.ctx.guild_crafters if tr == "enchanting"
        ]
        return sorted(out)

    def worker_of(self, holder: str, stack: Stack):
        """The family member (not the holder) who needs this material most."""
        best = None
        for m in self.siblings(holder):
            need = self.needs[m.name].get(stack.entry)
            if need:
                want = need["now"] + need["next"]
                short = want - self.held.get((m.name, stack.entry), 0)
                if short > 0 and (best is None or short > best[0]):
                    best = (short, m.name)
        return best[1] if best else None

    def guild_worker(self, stack: Stack):
        trades = guildshare.FEEDS.get(stack.subclass, ())
        for name, trade, _skill in sorted(self.ctx.guild_crafters):
            if trade in trades:
                return name
        return None


def _rule_quest(w: _World, s: Stack, me: Member):
    if s.item_class != C_QUEST:
        if s.entry in w.ctx.attunement_items:
            return [
                _opt(KEEP_CARRY, ATTUNEMENT, "attunement item", "R3", carry_forced=True)
            ]
        return None
    known = w.ctx.open_quest_items
    if known is not None and s.entry in known.get(s.holder, frozenset()):
        return [
            _opt(KEEP_CARRY, QUEST, "an open quest needs it", "R3", carry_forced=True)
        ]
    if known is None:
        return [
            _opt(
                KEEP_CARRY,
                QUEST,
                "quest item and the quest log was not read: never sold or destroyed",
                "R3",
                carry_forced=True,
            ),
            _opt(BANK_PERSONAL, QUEST, "quest item banked, quest log not read", "R3"),
        ]
    # The log was read and no open quest names it: it is only a leftover.
    out = [
        _opt(BANK_PERSONAL, ROOM, "quest-class leftover, no open quest names it", "R3")
    ]
    if s.sell > 0 and s.bind in (BIND_NONE, BIND_USE):
        out.append(_opt(SELL_VENDOR, ROOM, "quest-class leftover with a price", "R3"))
    return out


def _rule_basics(w: _World, s: Stack, me: Member):
    if s.bind not in _KNOWN_BINDS or s.soulbound is None:
        return [
            _opt(
                KEEP_CARRY,
                EQUIPMENT,
                "binding or soulbound flag unreadable: failing closed",
                "R1",
                carry_forced=True,
            )
        ]
    if s.loc == WORN:
        return [
            _opt(
                KEEP_CARRY,
                EQUIPMENT,
                "worn bag or key ring item",
                "R2",
                carry_forced=True,
            )
        ]
    if s.entry == HEARTHSTONE:
        return [_opt(KEEP_CARRY, EQUIPMENT, "hearthstone", "R2", carry_forced=True)]
    if s.item_class == C_KEY:
        return [_opt(KEEP_CARRY, EQUIPMENT, "key", "R2", carry_forced=True)]
    return None


def _rule_bag(w: _World, s: Stack, me: Member):
    if s.item_class != C_CONTAINER:
        return None
    slots = max(0, int(s.container_slots or 0))
    if slots == 0:
        return [
            _opt(
                KEEP_CARRY,
                BAG_ROOM,
                "bag capacity was not read; keep the bag",
                "R2",
                carry_forced=True,
            )
        ]
    worn = [
        max(0, int(b.container_slots or 0))
        for b in w.stacks
        if b.holder == s.holder and b.loc == WORN and b.item_class == C_CONTAINER
    ]
    out = []
    smallest_carried = sorted(worn, reverse=True)[:CARRIED_BAGS]
    if (
        smallest_carried
        and len(smallest_carried) >= CARRIED_BAGS
        and slots > min(smallest_carried)
    ):
        out.append(
            _opt(
                KEEP_CARRY,
                BAG_ROOM,
                "bigger than a worn bag: bag_upgrade swaps it in",
                "R2",
                carry_forced=True,
            )
        )
    if me.empty_bank_positions > 0:
        out.append(
            _opt(
                BANK_PERSONAL,
                BAG_ROOM,
                "fits an empty bank bag position: +%d bank slots" % slots,
                "R2",
                cap_group=("bankbag", s.holder, me.empty_bank_positions),
                cap_rank=(-slots, s.entry, s.index),
            )
        )
    for sib in w.siblings(s.holder):
        if sib.empty_bank_positions > 0:
            out.append(
                _opt(
                    GIVE,
                    BAG_ROOM,
                    "%s has an empty bank bag position" % sib.name,
                    "R2",
                    target=sib.name,
                )
            )
            break
    out += _vendor_options(s, "R2", "spare bag no bigger than a worn one")
    if not out:
        out.append(_opt(BANK_PERSONAL, ROOM, "spare bag", "R2"))
    return out


def _rule_gear_now(w: _World, s: Stack, me: Member):
    if not s.gear:
        return None
    verdict = w.ctx.gear_verdict.get((s.holder, s.entry))
    if verdict == "wear":
        return [
            _opt(
                KEEP_CARRY,
                EQUIPMENT,
                "the gear pass says wear it",
                "R4",
                carry_forced=True,
            )
        ]
    return None


def _rule_tool(w: _World, s: Stack, me: Member):
    trades = disposition.TOOL_TRADES.get(s.entry)
    if not trades:
        return None
    if any(me.skill(t) > 0 for t in trades):
        return [
            _opt(
                KEEP_CARRY,
                TOOLS,
                "tool for %s" % "/".join(trades),
                "R5",
                carry_forced=True,
            )
        ]
    for sib in w.siblings(s.holder):
        if any(sib.skill(t) > 0 for t in trades) and s.tradable:
            return [
                _opt(
                    GIVE,
                    TOOLS,
                    "%s works %s" % (sib.name, "/".join(trades)),
                    "R5",
                    target=sib.name,
                ),
                _opt(BANK_PERSONAL, TOOLS, "tool nobody here uses yet", "R5"),
            ]
    return [_opt(BANK_PERSONAL, TOOLS, "tool for a trade nobody here works", "R5")]


_RAID_ENTRIES: dict = {}


def raid_entries() -> dict:
    """entry -> (kind, trade or "") for every Molten Core supply and reagent."""
    if _RAID_ENTRIES:
        return _RAID_ENTRIES
    for sup in raidsupply.SUPPLIES:
        _RAID_ENTRIES.setdefault(sup.entry, ("supply", ""))
        if sup.make:
            trade = {
                raidsupply.ALCHEMY: "alchemy",
                raidsupply.TAILORING: "tailoring",
                raidsupply.COOKING: "cooking",
            }.get(sup.make.skill, "")
            for entry, _n in sup.make.reagents:
                _RAID_ENTRIES.setdefault(entry, ("reagent", trade))
    for gear in raidsupply.FIRE_GEAR:
        _RAID_ENTRIES.setdefault(gear.entry, ("fire gear", ""))
    return _RAID_ENTRIES


def _raid_fire(w: _World, s: Stack) -> tuple[bool, bool]:
    if s.fire_res is not None:
        return s.fire_res > 0, True
    if w.ctx.fire_gear is not None:
        return s.entry in w.ctx.fire_gear, True
    return False, False


def _rule_raid(w: _World, s: Stack, me: Member):
    kind = raid_entries().get(s.entry)
    fire, fire_known = _raid_fire(w, s)
    if not fire_known and s.gear:
        return [
            _opt(
                KEEP_CARRY,
                EQUIPMENT,
                "fire resistance was not read; keep the gear",
                "R6",
                carry_forced=True,
            )
        ]
    if not kind and not fire:
        return None
    if not s.tradable:
        return [
            _opt(
                BANK_PERSONAL,
                RAID_NIGHT,
                "soulbound raid item: banked for the night",
                "R6",
            )
        ]
    name, trade = kind if kind else ("fire gear", "")
    # Reagents a member's own trade window uses are the trade's, not the raid's.
    if kind and kind[0] == "reagent" and s.entry in w.needs[s.holder]:
        return None
    out = []
    if w.ctx.raid_night:
        out.append(
            _opt(
                KEEP_CARRY,
                RAID_NIGHT,
                "Molten Core night: %s" % name,
                "R6",
                carry_forced=True,
            )
        )
    if trade and me.skill(trade) > 0:
        out.append(
            _opt(
                BANK_PERSONAL,
                RAID_NIGHT,
                "raid %s stock held by its crafter" % name,
                "R6",
            )
        )
    out.append(
        _opt(
            GUILD_BANK,
            RAID_NIGHT,
            "raid %s for the Raid Supplies tab" % name,
            "R6",
            target="Raid Supplies",
            tab=GUILD_TAB_RAID,
        )
    )
    out.append(_opt(BANK_PERSONAL, RAID_NIGHT, "raid %s, tab full" % name, "R6"))
    return out


def _food(s: Stack) -> bool:
    return s.item_class == C_CONSUMABLE and s.subclass == 5


def _rule_consumable(w: _World, s: Stack, me: Member):
    if s.item_class != C_CONSUMABLE:
        return None
    if _food(s):
        out = [
            _opt(
                KEEP_CARRY,
                CONSUMABLE,
                "food or drink for the run",
                "R7",
                cap_group=("food", s.holder, FOOD_STACKS_KEPT),
                cap_rank=(-s.count, s.entry, s.index),
            )
        ]
        out += _vendor_options(s, "R11", "surplus food with a price")
        if _destroy_allowed(s, w.ctx):
            out.append(
                _opt(DESTROY, ROOM, "surplus food: no price, replaced at will", "R12")
            )
        return out
    return None


def _rule_material(w: _World, s: Stack, me: Member):
    """Trade stock, then surplus. Trade goods, gems and plain reagents."""
    if s.item_class not in (C_TRADE, C_GEM, C_REAGENT, C_CONSUMABLE, C_MISC):
        return None
    if s.item_class == C_CONSUMABLE and s.subclass in (5,):
        return None
    need = w.needs[s.holder].get(s.entry)
    trade = None
    now_units = next_units = 0
    if need:
        now_units, next_units = need["now"], need["next"]
        trade = "/".join(sorted(set(need["trades"])))
    else:
        band = band_need(me, s)
        if band:
            now_units, trade = 0, band
            next_units = BAND_KEEP
    if CLASS_REAGENTS.get(s.entry) and me.class_id in CLASS_REAGENTS[s.entry]:
        return [
            _opt(
                KEEP_CARRY,
                CONSUMABLE,
                "class spell reagent",
                "R7",
                cap_group=("classreagent", s.holder, s.entry, 1),
                cap_rank=(-s.count, s.index),
            ),
            *_vendor_options(s, "R10", "spare class reagent"),
        ]
    if now_units or next_units:
        opts = []
        if now_units:
            opts.append(
                _opt(
                    KEEP_CARRY,
                    TRADE_NOW,
                    "%s skill-up stock" % trade,
                    "R7",
                    cap_group=("now", s.holder, s.entry, now_units),
                    cap_rank=(-s.count, s.index),
                    cap_units=True,
                )
            )
            opts.append(
                _opt(
                    BANK_PERSONAL,
                    TRADE_NOW,
                    "%s skill-up stock, banked while the bags are full" % trade,
                    "R7",
                    cap_group=("now", s.holder, s.entry, now_units),
                    cap_rank=(-s.count, s.index),
                    cap_units=True,
                )
            )
        if next_units:
            opts.append(
                _opt(
                    BANK_PERSONAL,
                    TRADE_NEXT,
                    "%s stock for the next range" % trade,
                    "R7",
                    cap_group=("next", s.holder, s.entry, next_units),
                    cap_rank=(-s.count, s.index),
                    cap_units=True,
                )
            )
        return opts + _surplus_material(w, s, me)
    return _surplus_material(w, s, me)


def _bank_if_worth(s: Stack, rule: str, goal=SURPLUS) -> list:
    if s.value >= BANK_WORTH or (s.item_class == C_GEM and s.quality >= 2):
        return [
            _opt(
                BANK_PERSONAL,
                goal,
                "worth more than a vendor sale; a taker may appear",
                rule,
            )
        ]
    return []


def _surplus_material(w: _World, s: Stack, me: Member) -> list:
    out = []
    if s.tradable and w.worker_of(s.holder, s):
        who = w.worker_of(s.holder, s)
        out.append(
            _opt(
                GIVE, SURPLUS, "%s works the trade that uses it" % who, "R7", target=who
            )
        )
    guild_who = w.guild_worker(s) if s.tradable else None
    if guild_who:
        out.append(
            _opt(
                GIVE,
                SURPLUS,
                "guildmate %s works a trade that uses it" % guild_who,
                "R10",
                target=guild_who,
            )
        )
    if s.tradable:
        out.append(
            _opt(
                GUILD_BANK,
                SURPLUS,
                "surplus material for the Materials tab",
                "R10",
                target="Materials",
                tab=GUILD_TAB_MATERIALS,
            )
        )
        out += _market_options(w, s, "R11")
    out += _bank_if_worth(s, "R10")
    out += _vendor_options(s, "R10", "surplus past every trade's need")
    if not out:
        out.append(_opt(BANK_PERSONAL, SURPLUS, "no buyer and no price", "R10"))
        if _destroy_allowed(s, w.ctx):
            out.append(_opt(DESTROY, ROOM, "no vendor price and nobody's use", "R12"))
    return out


def _market_options(w: _World, s: Stack, rule: str) -> list:
    quote = w.ctx.market.get(s.entry)
    if not quote or s.sell <= 0 or not s.tradable:
        return []
    price = int(quote[0])
    net = price * (100 - AUCTION_CUT_PERCENT) // 100
    factor = AUCTION_BEATS_VENDOR_BY
    if w.ctx.previous.get((s.holder, s.entry)) == AUCTION:
        factor = AUCTION_HOLD_FACTOR
    gain = (net - s.sell) * max(1, s.count)
    if net >= factor * s.sell and gain >= AUCTION_MIN_GAIN:
        return [
            _opt(
                AUCTION,
                SURPLUS,
                "market %d beats vendor %d by %dx or more" % (price, s.sell, factor),
                rule,
            )
        ]
    return []


def _gear_surplus(w: _World, s: Stack, me: Member, why: str) -> list:
    """Gear nobody in the family will wear. Never lose a rare or epic."""
    out = []
    de = _disenchant_option(w, s, me)
    if de:
        out.append(de)
    if s.tradable and s.quality >= 3:
        out += _market_options(w, s, "R8")
        out.append(
            _opt(
                GUILD_BANK,
                GEAR_LATER,
                "%s: rare gear for the Gear for Later tab" % why,
                "R8",
                target="Gear for Later",
                tab=GUILD_TAB_GEAR,
            )
        )
    elif s.tradable:
        out += _market_options(w, s, "R8")
    if s.quality >= 4:
        out.append(_opt(BANK_PERSONAL, GEAR_LATER, "epic gear is never sold", "R8"))
        return out
    out += _vendor_options(s, "R8", why)
    if not out:
        out.append(_opt(BANK_PERSONAL, ROOM, "no price and no wearer", "R8"))
        if _destroy_allowed(s, w.ctx):
            out.append(
                _opt(
                    DESTROY,
                    ROOM,
                    "no vendor price, no wearer, not bound for anyone",
                    "R12",
                )
            )
    return out


def _disenchant_option(w: _World, s: Stack, me: Member):
    if s.quality < 2 or s.quality > 4 or not s.gear:
        return None
    need = disenchant_skill(s.item_level)
    if me.skill("enchanting") >= need and s.value < DE_VENDOR_CEILING:
        return _opt(
            DISENCHANT,
            SURPLUS,
            "enchanting %d breaks down ilvl %d"
            % (me.skill("enchanting"), s.item_level),
            "R8",
        )
    return None


def _rule_gear(w: _World, s: Stack, me: Member):
    if not s.gear:
        return None
    own = wanted_by(s, me)
    sibs = []
    if s.tradable:
        for m in w.siblings(s.holder):
            when = wanted_by(s, m)
            if when:
                sibs.append((0 if when == "now" else 1, m.level, m.name, m))
        sibs.sort()
    out = []
    if own:
        rank = (0 if own == "later" else 1, -s.item_level, -s.quality, s.index)
        out.append(
            _opt(
                BANK_PERSONAL,
                EQUIPMENT if own == "now" else GEAR_LATER,
                "wearable by its holder (%s), gear pass has not judged it: second set"
                % own,
                "R4",
                cap_group=("spare", s.holder, SPARE_SET_MAX),
                cap_rank=rank,
            )
        )
    if sibs:
        when, _lvl, _name, sib = sibs[0]
        if when == 0:
            out.append(
                _opt(
                    GIVE,
                    FAMILY_UPGRADE,
                    "%s can wear it now" % sib.name,
                    "R8",
                    target=sib.name,
                )
            )
        else:
            out.append(
                _opt(
                    GUILD_BANK,
                    GEAR_LATER,
                    "for %s at level %d" % (sib.name, s.req_level),
                    "R8",
                    target="Gear for Later",
                    tab=GUILD_TAB_GEAR,
                )
            )
            out.append(
                _opt(
                    GIVE,
                    FAMILY_UPGRADE,
                    "%s will wear it at level %d" % (sib.name, s.req_level),
                    "R8",
                    target=sib.name,
                )
            )
    if s.bind == BIND_PICKUP and not own:
        why = "soulbound and outgrown or unwearable by its holder"
    else:
        why = "nobody in the family will wear it"
    out += _gear_surplus(w, s, me, why)
    return out


def _recipe_member_option(s: Stack, me: Member, trade: str | None, rank: int):
    if not trade or me.skill(trade) <= 0:
        return None
    skill = me.skill(trade)
    if rank > range_top(skill) + RANGE:
        return None
    goal = TRADE_NOW if rank <= skill else TRADE_NEXT
    return _opt(
        KEEP_CARRY if goal == TRADE_NOW else BANK_PERSONAL,
        goal,
        "%s recipe within reach of skill %d" % (trade, skill),
        "R9",
    )


def _recipe_sibling_option(w: _World, s: Stack, trade: str | None, rank: int):
    if not trade or not s.tradable:
        return None
    for sib in w.siblings(s.holder):
        if sib.skill(trade) > 0 and rank <= range_top(sib.skill(trade)) + RANGE:
            return _opt(
                GIVE,
                RECIPE,
                "%s works %s and reaches it" % (sib.name, trade),
                "R9",
                target=sib.name,
            )
    return None


def _recipe_guild_option(w: _World, s: Stack, trade: str | None, rank: int):
    if not trade or not s.tradable:
        return None
    for name, gtrade, skill in sorted(w.ctx.guild_crafters):
        if gtrade == trade and rank <= range_top(skill) + RANGE:
            return _opt(
                GIVE,
                RECIPE,
                "guildmate %s works %s" % (name, trade),
                "R9",
                target=name,
            )
    return None


def _recipe_raid_options():
    return [
        _opt(
            GUILD_BANK,
            RAID_NIGHT,
            "raid recipe: never sold",
            "R9",
            target="Raid Supplies",
            tab=GUILD_TAB_RAID,
        ),
        _opt(BANK_PERSONAL, RAID_NIGHT, "raid recipe: never sold", "R9"),
    ]


def _rule_recipe(w: _World, s: Stack, me: Member):
    if s.item_class != C_RECIPE:
        return None
    if s.required_skill_rank is None:
        return [
            _opt(
                KEEP_CARRY,
                RECIPE,
                "recipe skill rank was not read; keep the recipe",
                "R9",
                carry_forced=True,
            )
        ]
    trade = RECIPE_TRADE.get(s.subclass)
    rank = s.required_skill_rank
    drop = s.entry in raidsupply.DROP_RECIPES
    out = []
    member_option = _recipe_member_option(s, me, trade, rank)
    if member_option:
        out.append(member_option)
    sibling_option = _recipe_sibling_option(w, s, trade, rank)
    if sibling_option:
        out.append(sibling_option)
    if drop:
        return out + _recipe_raid_options()
    guild_option = _recipe_guild_option(w, s, trade, rank)
    if guild_option:
        out.append(guild_option)
    if s.tradable:
        out.append(
            _opt(
                GUILD_BANK,
                RECIPE,
                "recipe nobody here can learn yet",
                "R9",
                target="Materials",
                tab=GUILD_TAB_MATERIALS,
            )
        )
        out += _market_options(w, s, "R11")
    out += _bank_if_worth(s, "R9", RECIPE)
    out += _vendor_options(s, "R9", "recipe for a trade nobody in reach works", RECIPE)
    if not out:
        out.append(_opt(BANK_PERSONAL, RECIPE, "recipe, no taker and no price", "R9"))
    return out


def _rule_misc(w: _World, s: Stack, me: Member):
    out = []
    if s.item_class == C_MISC and s.subclass == 0 and s.name.endswith("Lockbox"):
        for m in w.members.values():
            if m.class_id == ROGUE and m.family == me.family and m.name != s.holder:
                out.append(
                    _opt(
                        GIVE,
                        SURPLUS,
                        "%s is the family rogue" % m.name,
                        "R7",
                        target=m.name,
                    )
                )
                break
    out += _market_options(w, s, "R11")
    out += _vendor_options(s, "R11", "vendor goods, nobody needs it")
    if not out:
        out.append(_opt(BANK_PERSONAL, ROOM, "no price", "R12"))
        if _destroy_allowed(s, w.ctx):
            out.append(_opt(DESTROY, ROOM, "no vendor price and no use", "R12"))
    return out


_RULES = (
    _rule_basics,
    _rule_quest,
    _rule_bag,
    _rule_gear_now,
    _rule_tool,
    _rule_raid,
    _rule_consumable,
    _rule_material,
    _rule_gear,
    _rule_recipe,
    _rule_misc,
)


def options_for(w: _World, s: Stack) -> list:
    me = w.members[s.holder]
    for rule in _RULES:
        got = rule(w, s, me)
        if got:
            return _stick(w, s, _banked_stays(s, _terminal(w, s, got)))
    return [
        _opt(KEEP_CARRY, EQUIPMENT, "no rule claimed it: kept", "R1", carry_forced=True)
    ]


_TERMINAL = frozenset({KEEP_CARRY, BANK_PERSONAL, SELL_VENDOR, DISENCHANT, DESTROY})


def _terminal(w: _World, s: Stack, options: list) -> list:
    """Every chain ends somewhere that has room: bank, then destroy if safe.

    A guild tab, a gift or a listing can all be full or refused; without this a
    stack whose only options were those would sit where it is, unexplained.
    """
    if any(o.route in _TERMINAL for o in options):
        return options
    options = list(options) + [
        _opt(BANK_PERSONAL, ROOM, "no taker and no price: banked", "R12")
    ]
    if _destroy_allowed(s, w.ctx):
        options.append(_opt(DESTROY, ROOM, "no vendor price and no use", "R12"))
    return options


def _banked_stays(s: Stack, options: list) -> list:
    """No route fetches a stack out of the bank, so a banked stack that would be
    carried stays banked (a data and executor gap, see docs/ITEM_PLAN.md)."""
    if not s.banked:
        return options
    out = []
    for o in options:
        if o.route == KEEP_CARRY:
            o = replace(
                o,
                route=BANK_PERSONAL,
                carry_forced=False,
                reason=o.reason + "; stays banked",
            )
        out.append(o)
    return out


def _stick(w: _World, s: Stack, options: list) -> list:
    """Hysteresis against last pass's route (see the module docstring)."""
    prev = w.ctx.previous.get((s.holder, s.entry))
    if not prev or prev == options[0].route:
        return options
    first = options[0]
    tier = TIER[first.goal]
    if prev in (BANK_PERSONAL, GUILD_BANK) and first.route == KEEP_CARRY:
        if not first.carry_forced:
            return _front(options, prev)
    if prev in IRREVERSIBLE and tier < MANDATORY_TIER and not first.carry_forced:
        return _front(options, prev)
    return options


def _front(options: list, route: str) -> list:
    pick = [o for o in options if o.route == route]
    if not pick:
        return options
    rest = [o for o in options if o is not pick[0]]
    return [pick[0]] + rest


# ---------------------------------------------------------------------------
# Allocation.


def _priority(s: Stack, opt: Option) -> tuple:
    per_slot = s.value
    return (TIER[opt.goal], per_slot)


def plan(
    stacks: Iterable[Stack], members: Iterable[Member], ctx: Context | None = None
) -> Plan:
    """The plan for every stack of every member. Deterministic."""
    ctx = ctx or Context()
    stacks = sorted(stacks, key=lambda s: s.key)
    members = sorted(members, key=lambda m: m.name)
    w = _World(stacks, members, ctx)
    todo = [s for s in stacks if s.holder in w.members]
    opts = {s.key: options_for(w, s) for s in todo}
    pinned: set = set()
    result: dict = {}
    for _ in range(4):
        result, stuck = _allocate(w, todo, opts, pinned)
        newly = {k for k in stuck if k not in pinned}
        if not newly:
            break
        pinned |= newly
    out = tuple(_to_decision(s, result[s.key], opts[s.key], ctx) for s in todo)
    return Plan(out, tuple(members))


def _allocate(w: _World, todo: list, opts: dict, pinned: set):
    members = w.members
    carried_now = {m: 0 for m in members}
    for s in todo:
        if s.carried:
            carried_now[s.holder] += 1
    free_now = {m: members[m].carried_slots - carried_now[m] for m in members}
    forced = {m: 0 for m in members}
    for s in todo:
        o = opts[s.key][0]
        if s.carried and (o.route == KEEP_CARRY and (o.carry_forced or s.loc == WORN)):
            forced[s.holder] += 1
    limit = {
        m: members[m].carried_slots
        - (TARGET_FREE if free_now[m] < TRIGGER_FREE else TRIGGER_FREE)
        for m in members
    }
    carry_used = {m: 0 for m in members}
    bank_cap = {m: members[m].bank_slots - BANK_RESERVE for m in members}
    bank_used = {m: 0 for m in members}
    tab_used: dict = {}
    incoming = {m: 0 for m in members}
    groups: dict = {}
    spare_bag_gain = {m: 0 for m in members}
    result: dict = {}
    stuck: set = set()
    order = sorted(
        todo,
        key=lambda s: (
            0 if s.key in pinned else 1,
            -_priority(s, opts[s.key][0])[0],
            -_priority(s, opts[s.key][0])[1],
            s.key,
        ),
    )
    for s in order:
        chosen = None
        skipped: list = []
        options = opts[s.key]
        if s.key in pinned:
            place = KEEP_CARRY if s.carried else BANK_PERSONAL
            fixed = [
                replace(
                    o,
                    reason="%s: no destination had room, stays (%s)"
                    % (NO_ROOM, o.reason),
                    rule="R0",
                )
                for o in options
                if o.route == place
            ] or [_opt(place, ROOM, NO_ROOM + ": no destination had room: stays", "R0")]
            options = fixed
        for o in options:
            ok, why = _feasible(
                w,
                s,
                o,
                groups,
                carry_used,
                forced,
                limit,
                bank_used,
                bank_cap,
                tab_used,
                incoming,
                free_now,
                spare_bag_gain,
            )
            if ok:
                chosen = o
                break
            skipped.append("%s: %s" % (o.route, why))
        if chosen is None:
            place = KEEP_CARRY if s.carried else BANK_PERSONAL
            chosen = _opt(
                place,
                ROOM,
                "%s: no destination had room (%s): stays put"
                % (NO_ROOM, "; ".join(skipped)),
                "R0",
            )
            stuck.add(s.key)
            if s.carried:
                carry_used[s.holder] += 1
            else:
                bank_used[s.holder] += 1
        else:
            _commit(
                w,
                s,
                chosen,
                groups,
                carry_used,
                bank_used,
                tab_used,
                incoming,
                spare_bag_gain,
                bank_cap,
            )
        result[s.key] = (chosen, tuple(skipped))
    return result, stuck


def _feasible(
    w,
    s,
    o,
    groups,
    carry_used,
    forced,
    limit,
    bank_used,
    bank_cap,
    tab_used,
    incoming,
    free_now,
    spare_bag_gain,
):
    m = s.holder
    if o.cap_group:
        gid, size = o.cap_group[:-1], o.cap_group[-1]
        used = groups.get(gid, [])
        if not _in_cap(used, o, size):
            return False, "its share of %s is full" % (gid[0],)
    if o.route == KEEP_CARRY:
        if o.carry_forced or s.loc == WORN:
            return True, ""
        if forced[m] + carry_used[m] >= limit[m]:
            return False, "carried bags are at their budget"
        return True, ""
    if o.route == BANK_PERSONAL:
        cap = bank_cap[m] + spare_bag_gain[m]
        if o.cap_group and o.cap_group[0] == "bankbag":
            return True, ""
        if bank_used[m] >= cap:
            return False, "personal bank is full"
        if s.item_class not in (C_QUEST, C_RECIPE) and s.sell <= 0 and o.goal == ROOM:
            if cap - bank_used[m] <= BANK_JUNK_FLOOR:
                return False, "junk does not take the last bank slots"
        return True, ""
    if o.route == GUILD_BANK:
        key = (w.members[m].family, o.tab)
        free = w.ctx.guild_free.get(key, 0)
        if tab_used.get(key, 0) >= free:
            return False, "guild bank tab is full"
        return True, ""
    if o.route == GIVE:
        r = w.members.get(o.target)
        if r is None:
            return True, ""  # a guildmate: mail
        room = free_now[r.name] - incoming[r.name]
        if room <= GIVE_FLOOR:
            return False, "%s has no room" % r.name
        return True, ""
    return True, ""


def _in_cap(used: list, o: Option, size: int) -> bool:
    """Is there room in the group. Whole stacks: one may cross the line."""
    return (sum(u for _k, u in used) if o.cap_units else len(used)) < size


def _commit(
    w, s, o, groups, carry_used, bank_used, tab_used, incoming, spare_bag_gain, bank_cap
):
    m = s.holder
    if o.cap_group:
        gid = o.cap_group[:-1]
        groups.setdefault(gid, []).append((s.key, s.count))
    if o.route == KEEP_CARRY:
        if not (o.carry_forced or s.loc == WORN):
            carry_used[m] += 1
    elif o.route == BANK_PERSONAL:
        if o.cap_group and o.cap_group[0] == "bankbag":
            spare_bag_gain[m] += max(0, int(s.container_slots or 0))
        else:
            bank_used[m] += 1
    elif o.route == GUILD_BANK:
        key = (w.members[m].family, o.tab)
        tab_used[key] = tab_used.get(key, 0) + 1
    elif o.route == GIVE and o.target in w.members:
        incoming[o.target] += 1


def _to_decision(s: Stack, chosen_and_skipped, options: list, ctx: Context) -> Decision:
    o, skipped = chosen_and_skipped
    irreversible = o.route in IRREVERSIBLE
    confirm = irreversible and (s.value >= CONFIRM_VALUE or s.quality >= 3)
    reason = o.reason
    if skipped:
        reason += " (first choice failed: %s)" % "; ".join(skipped)
    return Decision(
        holder=s.holder,
        entry=s.entry,
        name=s.name,
        count=s.count,
        from_loc=s.loc,
        route=o.route,
        goal=o.goal,
        reason=reason,
        rule=o.rule,
        target=o.target,
        tab=o.tab,
        value=s.value,
        irreversible=irreversible,
        refusable=irreversible,
        confirm=confirm,
        stuck=o.rule == "R0",
        key=s.key,
        options=tuple(x.route for x in options),
    )


# ---------------------------------------------------------------------------
# Measures.


def free_after(
    plan_: Plan, member: Member, stacks: Iterable[Stack], sales: bool = True
) -> int:
    """Free carried slots once the plan has run.

    A stuck stack stays. With `sales` False, every irreversible route is
    treated as not run (the vendor is out of reach, wow-overseer#1592), so the
    figure is what bank, guild bank and give alone free.
    """
    staying = 0
    for d in plan_.by_holder(member.name):
        if d.from_loc not in CARRIED:
            continue
        if d.route == KEEP_CARRY or (not sales and d.route in IRREVERSIBLE):
            staying += 1
        elif d.route == AUCTION and not sales:
            staying += 1
    return member.carried_slots - staying


def free_now(member: Member, stacks: Iterable[Stack]) -> int:
    return member.carried_slots - sum(
        1 for s in stacks if s.holder == member.name and s.carried
    )


def tab_slot_cost(position: int = 1) -> tuple:
    """(gold copper, copper per slot) of guild bank tab number `position`."""
    cost = guildbank.tab_cost(position)
    return cost, cost // TAB_SLOTS
