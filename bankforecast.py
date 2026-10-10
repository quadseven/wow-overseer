"""What the guild really needs in its bank, and what it can let go.

WHAT WAS ASKED FOR. The operator, 2026-10-10: the guild keeps "so much
linen". Once members have levelled their trades past a material the guild
does not need it, and it can go on the auction house for players who are
new. There must be a banking model that knows what the guild as a whole
needs for its goals.

WHAT THE REALM SAID (dev, read-only, 2026-10-10). Cave's one tab held 98 of
98 slots, 14 of them Linen Cloth (280), all deposited by one tailor between
2026-09-27 and 2026-09-29 after its own trade had climbed past linen. The
keeper rule (bank.storage_reason) stores any tradable material a family trade
claims and has no ceiling, and nothing has ever left a guild bank tab: the
module has no item verb that takes from one. Since 2026-10-06 the full tab
has sent every new keeper to the holder's personal bank instead. Measured
against that, the guild's crew ate 201 Linen Cloth in Linen Bandage casts in
seven days, and Cave's members held another 1,115 in their bags, banks and
post: the vault's linen was past anything the guild would eat in a fortnight.

THE MODEL, ONE MATERIAL AT A TIME.

  need     what the guild eats over HORIZON_DAYS: the crew's measured pace
           (`cast` rows over the last PACE_DAYS) times the horizon, plus what
           each family member's current rung still eats (the family crafts
           through its craft errand, which writes no rows to measure).
  ladder   the most every member can still eat: each trade's rungs
           (craft.RECIPES, reagents from craft_rhythm) from its skill to the
           ceiling its level can buy (guildjobs.RANKS). Need is never above it.
  target   need, plus SAFETY_STACKS full stacks while the ladder is not done.
           A ladder every member has climbed past has a target of nothing.
  surplus  what the guild holds past the target, counting the members' own
           stock first, because a material is eaten from the bags.

A gathered material is replenished as members play (cloth drops from every
humanoid), so the bank keeps the horizon's need and not the whole ladder's.

THE OTHER KINDS. A recipe is kept once for each member whose trade can reach
its rank at its level; past that it is surplus. A gem is surplus while nobody
cuts gems. A trade good no rung eats is kept while somebody works a trade that
uses it (guildshare.FEEDS), and is surplus otherwise. Raid supplies and their
reagents (bankpolicy) are never sold. A grey item is junk. Anything else is
not judged here and is kept.

WHERE SURPLUS GOES, IN ORDER: into the hands of a member whose current rung
needs it and whose bags are short; else the auction house, at a fair price
read from the house's own history, when it beats the vendor by
disposition.AUCTION_BEATS_VENDOR_BY; else a vendor. A surplus item with no
price history and no vendor price is kept, because a guess is not a price.

WHAT IT CHANGES TODAY. The keeper rule sends the vault nothing the guild
already holds past its target (the holder's own bank takes it, as before),
and clearance lists or sells a carried material past the target at the fair
price. The vault's own stacks cannot leave it yet: mod-overseer has no verb
that takes an item out of a guild bank tab, so their decisions are the plan
the bridge logs, and they wait for that verb.

NATURAL ONLY. Nothing here creates or grants anything. A member lists its own
stack, posts it to a guildmate, or sells it to a vendor: what a player does.

PURE MODULE apart from `read`, which runs SELECTs on a cursor it is handed.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, replace

import bankpolicy
import craft
import craft_rhythm
import disposition
import guildjobs
import guildshare

# How far ahead the bank keeps. Two weeks of measured eating: long enough to
# ride out a day the crew is away, short enough that a trade the guild has
# climbed past stops holding slots.
HORIZON_DAYS = 14
# The window the crew's pace is measured over.
PACE_DAYS = 7
# Full stacks kept above the need while somebody still climbs on it.
SAFETY_STACKS = 1
# Casts per skill point on a rung. A rung is chosen while it is orange or
# yellow, and a yellow cast misses a point now and then: five casts for four
# points is a judgement, named so it can be argued with.
CASTS_PER_POINT = (5, 4)
# An ask that expired did not sell, so it was too high: a fair price from
# asks alone is this fraction of their median.
EXPIRED_ASK = (3, 4)
# The classic ceilings by level when a trade has no measured rank table:
# Apprentice 75, Journeyman 150 at 10, Expert 225 at 20, Artisan 300 at 35.
LEVEL_CEILINGS = ((35, 300), (20, 225), (10, 150), (0, 75))

ITEM_CLASS_CONSUMABLE = 0
ITEM_CLASS_GEM = 3
ITEM_CLASS_TRADE_GOODS = 7
ITEM_CLASS_RECIPE = 9
POOR = 0

JEWELCRAFTING = guildshare.SKILL_LINES["jewelcrafting"]

# What a holding is, which is also the word the line shows.
NOW = "needed now"
LATER = "needed later"
RAID = "raid reserve"
SURPLUS = "surplus"
JUNK = "junk"
UNJUDGED = "not judged"

# What happens to a stack.
KEEP = "keep"
GIVE = "give"
SELL = "sell"
VENDOR = "vendor"

# What each action is called on a line, in the order a line names them.
ACTION_WORDS = ((KEEP, "keep"), (GIVE, "give"), (SELL, "list"), (VENDOR, "vendor"))

RAID_ENTRIES = frozenset(bankpolicy.RAID_REAGENTS) | frozenset(
    bankpolicy.RAID_CONSUMABLES
)


@dataclass(frozen=True)
class Member:
    """One guild member: level, skill line id -> value, and whether it is family."""

    name: str
    level: int
    skills: dict = field(default_factory=dict)
    family: bool = False

    def skill(self, skill_id) -> int:
        try:
            return int((self.skills or {}).get(int(skill_id), 0) or 0)
        except (TypeError, ValueError):
            return 0


@dataclass(frozen=True)
class Item:
    """An item template, as the vault and the forecast read it."""

    entry: int
    name: str
    item_class: int = ITEM_CLASS_TRADE_GOODS
    subclass: int = 0
    quality: int = 1
    max_stack: int = 1
    sell_price: int = 0
    required_skill: int = 0
    required_rank: int = 0


@dataclass(frozen=True)
class Stack:
    """One stack in the guild bank."""

    guid: int
    entry: int
    count: int
    tab: int = 0


@dataclass
class Need:
    """What the guild eats of one material."""

    entry: int
    rungs: int = 0  # units the family's current rungs still eat
    ladder: int = 0  # the most every member can still eat
    pace: float = 0.0  # units a day, measured
    casts: int = 0  # the casts the pace was measured from
    # member -> units its current rung eats, for the hand-off.
    by_member: dict = field(default_factory=dict)

    @property
    def horizon(self) -> int:
        """Units eaten over the horizon, never above the ladder."""
        eaten = math.ceil(self.pace * HORIZON_DAYS) + self.rungs
        return min(self.ladder, eaten)


@dataclass(frozen=True)
class Decision:
    """What happens to one vault stack, and why."""

    stack: Stack
    item: str
    action: str  # KEEP, GIVE, SELL or VENDOR
    kind: str  # NOW, LATER, RAID, SURPLUS, JUNK or UNJUDGED
    why: str
    taker: str = ""
    price: int = 0  # copper per unit, for SELL
    # What this decision adds to the item's judgement: the price, the vendor
    # comparison, or the member's shortfall.
    note: str = ""

    @property
    def line(self) -> str:
        if self.action == SELL:
            what = "list %d at %s each" % (self.stack.count, money(self.price))
        elif self.action == GIVE:
            what = "give %d to %s" % (self.stack.count, self.taker)
        else:
            what = "%s %d" % (self.action, self.stack.count)
        return "%s: %s (%s) - %s%s" % (
            self.item,
            what,
            self.kind,
            self.why,
            "; " + self.note if self.note else "",
        )


@dataclass(frozen=True)
class Line:
    """One item's forecast: what the vault holds, what the guild needs."""

    entry: int
    item: str
    vault: int
    stacks: int
    held: int  # guild-wide, vault included
    target: int
    kind: str
    why: str
    decisions: tuple = ()

    def count(self, action) -> int:
        return sum(1 for d in self.decisions if d.action == action)

    @property
    def summary(self) -> str:
        """`Linen Cloth: 14 stack(s) (280) in the vault, 1395 guild-wide, need
        777; list 14 at 5s 46c each - <why>`: one line per item, every
        decision on it named."""
        if not self.stacks:
            return (
                "%s: none in the vault, %d guild-wide, need %s; members hold %d past it - %s"
                % (
                    self.item,
                    self.held,
                    _need_words(self.target),
                    max(0, self.held - self.target),
                    self.why,
                )
            )
        parts = []
        notes = []
        for action, word in ACTION_WORDS:
            chosen = [d for d in self.decisions if d.action == action]
            if not chosen:
                continue
            if action == SELL:
                parts.append(
                    "list %d at %s each" % (len(chosen), money(chosen[0].price))
                )
            elif action == GIVE:
                takers = sorted({d.taker for d in chosen})
                parts.append("give %d to %s" % (len(chosen), ", ".join(takers)))
            else:
                parts.append("%s %d" % (word, len(chosen)))
            if action != KEEP and chosen[0].note:
                notes.append(chosen[0].note)
        return (
            "%s: %d stack(s) (%d) in the vault, %d guild-wide, need %s; %s - %s%s"
            % (
                self.item,
                self.stacks,
                self.vault,
                self.held,
                _need_words(self.target),
                ", ".join(parts),
                self.why,
                "".join("; " + n for n in notes),
            )
        )


@dataclass(frozen=True)
class Forecast:
    """The vault's lines, and what every other pass reads from them."""

    lines: tuple = ()
    # entry -> why, for every item the guild holds past its target: the
    # guild vault takes no more of it (bank._plan_deposits), and clearance
    # passes a carried stack to a short member, the house or a vendor.
    over_target: dict = field(default_factory=dict)
    # entry -> a fair copper price per unit, from the house's history.
    fair: dict = field(default_factory=dict)
    # entry -> the members whose current rung eats more of it than they carry.
    short: dict = field(default_factory=dict)
    # The guild's name, for the headline.
    guild: str = ""

    def decisions(self) -> tuple:
        return tuple(d for line in self.lines for d in line.decisions)

    def headline(self, guild: str = "the guild") -> str:
        """`Cave's vault holds 98 stack(s): 41 surplus, ...; keep 56, give 1,
        list 19, vendor 22`."""
        decisions = self.decisions()
        kinds: dict = {}
        for d in decisions:
            kinds[d.kind] = kinds.get(d.kind, 0) + 1
        actions = [
            "%s %d" % (word, n)
            for action, word in ACTION_WORDS
            for n in [sum(1 for d in decisions if d.action == action)]
            if n
        ]
        return "%s's vault holds %d stack(s): %s; %s" % (
            guild,
            len(decisions),
            ", ".join("%d %s" % (n, k) for k, n in sorted(kinds.items())) or "none",
            ", ".join(actions) or "nothing to do",
        )


def _need_words(units: int) -> str:
    return "nothing" if units <= 0 else "%d" % units


def money(copper: int) -> str:
    """`5s 47c`, `1g 2s`, `13c`."""
    copper = max(0, int(copper))
    gold, rest = divmod(copper, 10_000)
    silver, cop = divmod(rest, 100)
    parts = []
    if gold:
        parts.append("%dg" % gold)
    if silver:
        parts.append("%ds" % silver)
    if cop or not parts:
        parts.append("%dc" % cop)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# WHAT A MEMBER EATS


def skill_ceiling(skill_id, level) -> int:
    """The highest skill a member at `level` can buy the rank for."""
    try:
        level = int(level)
    except (TypeError, ValueError):
        return 0
    ranks = guildjobs.RANKS.get(int(skill_id))
    if ranks:
        caps = [r.cap for r in ranks if r.level <= level]
        return max(caps) if caps else 0
    return next(cap for floor, cap in LEVEL_CEILINGS if level >= floor)


def _casts(points: int) -> int:
    num, den = CASTS_PER_POINT
    return -(-max(0, points) * num // den)


def _eats(spell: int) -> tuple:
    """(entry, units per cast) for everything one cast of `spell` eats, the
    rung's own earlier output and what that output was made of included."""
    out = [
        (int(r.entry), int(r.per_cast)) for r in craft_rhythm.GATHERED.get(spell, ())
    ]
    fed = craft_rhythm.BOLT_FED.get(spell)
    if fed is not None:
        weave, bolt = fed
        out.append((int(bolt.entry), int(bolt.per_cast)))
        out += [
            (int(r.entry), int(r.per_cast) * int(bolt.per_cast))
            for r in craft_rhythm.GATHERED.get(weave, ())
        ]
    return tuple(out)


def ladder_entries() -> frozenset:
    """Every material a rung of any trade eats."""
    out = set()
    for recipes in craft.RECIPES.values():
        for recipe in recipes:
            out.update(entry for entry, _n in _eats(recipe.spell_id))
    return frozenset(out)


LADDER_ENTRIES = ladder_entries()


def climb(skill_id, value, ceiling) -> tuple:
    """({entry: units the current rung eats}, {entry: units the whole climb
    eats}) for one member's trade at `value` up to `ceiling`."""
    rung: dict = {}
    ladder: dict = {}
    try:
        value, ceiling = int(value), int(ceiling)
    except (TypeError, ValueError):
        return rung, ladder
    if value <= 0:
        return rung, ladder
    for recipe in craft.RECIPES.get(int(skill_id), ()):
        low = max(value, recipe.min_skill)
        high = min(recipe.max_skill, ceiling - 1)
        if high < low:
            continue
        casts = _casts(high - low + 1)
        current = recipe.min_skill <= value <= recipe.max_skill
        for entry, per_cast in _eats(recipe.spell_id):
            ladder[entry] = ladder.get(entry, 0) + casts * per_cast
            if current:
                rung[entry] = rung.get(entry, 0) + casts * per_cast
    return rung, ladder


def needs(members, casts=(), days=PACE_DAYS) -> dict:
    """entry -> Need, over every member's trades and the measured casts.

    `casts` are (name, spell, count) for the applied `cast` rows in the last
    `days`: the crew's craft steps. The family's rungs count whole, because
    the family crafts through its craft errand, which writes no rows.
    """
    out: dict = {}
    for member in members:
        for skill_id in craft.RECIPES:
            value = member.skill(skill_id)
            rung, ladder = climb(skill_id, value, skill_ceiling(skill_id, member.level))
            for entry, units in ladder.items():
                out.setdefault(entry, Need(entry)).ladder += units
            for entry, units in rung.items():
                need = out.setdefault(entry, Need(entry))
                need.by_member[member.name] = need.by_member.get(member.name, 0) + units
                if member.family:
                    need.rungs += units
    for name, spell, count in casts:
        try:
            spell, count = int(spell), int(count)
        except (TypeError, ValueError):
            continue
        for entry, per_cast in _eats(spell):
            need = out.setdefault(entry, Need(entry))
            need.pace += count * per_cast / float(max(1, days))
            need.casts += count
    return out


# ---------------------------------------------------------------------------
# A FAIR PRICE, FROM THE HOUSE'S OWN HISTORY


def _per_unit(row) -> int:
    try:
        count = max(1, int(row.get("item_count") or 1))
        if str(row.get("outcome")) == "sold":
            paid = int(row.get("price_paid") or 0)
        else:
            paid = int(row.get("buyout") or 0) or int(row.get("bid") or 0)
    except (TypeError, ValueError):
        return 0
    return paid // count


def fair_price(rows, entry, house=0) -> tuple:
    """(copper per unit, why) for `entry` from `overseer_auction_history` rows.

    The median of what sold, when anything sold; else EXPIRED_ASK of the
    median ask that expired, because an ask nobody took was too high; else 0,
    which means no price. The family's house first, every house when it has
    no row for the item.
    """
    mine = [r for r in rows or () if _int(r.get("item_entry")) == int(entry)]
    local = [r for r in mine if house and _int(r.get("house")) == int(house)]
    rows = local or mine
    sold = [p for p in (_per_unit(r) for r in rows if r.get("outcome") == "sold") if p]
    if sold:
        price = int(statistics.median(sold))
        return price, "the house sold %d at a median %s each" % (
            len(sold),
            money(price),
        )
    asks = [
        p for p in (_per_unit(r) for r in rows if r.get("outcome") == "expired") if p
    ]
    if asks:
        median = int(statistics.median(asks))
        num, den = EXPIRED_ASK
        price = max(1, median * num // den)
        return price, (
            "the house's %d ask(s) for it expired unsold at a median %s, so "
            "%d/%d of that" % (len(asks), money(median), num, den)
        )
    return 0, "the house has no history for it"


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# THE VAULT, ITEM BY ITEM


def _recipe_users(item: Item, members) -> tuple:
    """(names who can learn it now, names whose trade reaches it later)."""
    now, later = [], []
    for m in members:
        value = m.skill(item.required_skill)
        if value <= 0:
            continue
        if value >= item.required_rank:
            now.append(m.name)
        elif skill_ceiling(item.required_skill, m.level) >= item.required_rank:
            later.append(m.name)
    return tuple(sorted(now)), tuple(sorted(later))


# THE TRADE GOODS guildshare.FEEDS DOES NOT MAP, by item_template.subclass:
# parts, explosives and devices are an engineer's (Copper Modulator, Heavy
# Blasting Powder, Bronze Tube), and the elementals go into every crafting
# trade's patterns. Kept while somebody works one of them.
MORE_FEEDS = {
    1: ("engineering",),
    2: ("engineering",),
    3: ("engineering",),
    10: (
        "alchemy",
        "blacksmithing",
        "enchanting",
        "engineering",
        "leatherworking",
        "tailoring",
    ),
}


def _feeders(item: Item, members) -> tuple:
    """Members who work a trade that uses this trade good (guildshare.FEEDS)."""
    subclass = int(item.subclass)
    trades = guildshare.FEEDS.get(subclass, ()) or MORE_FEEDS.get(subclass, ())
    lines = [guildshare.SKILL_LINES[t] for t in trades if t in guildshare.SKILL_LINES]
    return tuple(sorted(m.name for m in members if any(m.skill(s) > 0 for s in lines)))


def judge(item: Item, held: int, members, need: Need | None) -> tuple:
    """(kind, target units, why) for one item the guild holds `held` of.

    The target is what the guild keeps; past it a material is surplus. RAID,
    UNJUDGED and LATER keep everything, which is a target of `held`.
    """
    if item.entry in RAID_ENTRIES:
        return RAID, held, "a Molten Core supply or its reagent, never sold"
    if item.quality <= POOR:
        return JUNK, 0, "grey, and nothing uses it"
    if need is not None and need.ladder > 0:
        horizon = need.horizon
        target = horizon + SAFETY_STACKS * max(1, item.max_stack)
        why = (
            "the guild eats %d over %d days (%s, family rungs %d), its ladders "
            "can still eat %d; target %d with %d stack(s) of safety"
            % (
                horizon,
                HORIZON_DAYS,
                "%.1f a day from %d cast(s) in %d days"
                % (need.pace, need.casts, PACE_DAYS)
                if need.casts
                else "no casts measured",
                need.rungs,
                need.ladder,
                target,
                SAFETY_STACKS,
            )
        )
        if horizon <= 0:
            # NEEDED LATER: nobody eats it this fortnight, and a member will
            # climb the rungs that do. It is kept whole until then.
            return (
                LATER,
                held,
                (
                    "nobody eats it in the next %d days; members' ladders can still eat %d"
                    % (HORIZON_DAYS, need.ladder)
                ),
            )
        return NOW, target, why
    if item.entry in LADDER_ENTRIES:
        # A rung eats it, and every member has climbed past that rung, or no
        # member climbs a trade whose rungs eat it.
        return SURPLUS, 0, "no member still climbs a rung that eats it"
    if item.item_class == ITEM_CLASS_RECIPE and item.required_skill > 0:
        now, later = _recipe_users(item, members)
        users = now + later
        if not users:
            return (
                SURPLUS,
                0,
                "nobody in the guild works the trade it teaches to rank %d"
                % (item.required_rank),
            )
        kind = NOW if now else LATER
        return (
            kind,
            len(users),
            "%d member(s) can learn it%s: %s"
            % (
                len(users),
                "" if now else " once their trade reaches %d" % item.required_rank,
                ", ".join(users[:4]) + (" and more" if len(users) > 4 else ""),
            ),
        )
    if item.item_class == ITEM_CLASS_GEM:
        cutters = tuple(m.name for m in members if m.skill(JEWELCRAFTING) > 0)
        if not cutters:
            return SURPLUS, 0, "nobody in the guild cuts gems and no rung eats it"
        return LATER, held, "%s cut(s) gems" % ", ".join(cutters[:3])
    if item.item_class == ITEM_CLASS_TRADE_GOODS:
        feeders = _feeders(item, members)
        if not feeders:
            return SURPLUS, 0, "no rung eats it and nobody works a trade that uses it"
        return (
            LATER,
            held,
            "no rung eats it, and %d member(s) work a trade that uses it"
            % (len(feeders)),
        )
    return UNJUDGED, held, "not a material, recipe or gem this model judges"


def _give(stacks, need: Need, carried: dict, item: Item, given: dict) -> dict:
    """guid -> (taker, why) for kept vault stacks a short member's rung eats.

    The shortest member first: what its current rung eats, less what it
    carries and what this plan already gave it. `given` is updated in place.
    """
    out = {}
    for stack in stacks:
        short = []
        for name, units in (need.by_member or {}).items():
            have = _int((carried.get(name) or {}).get(item.entry))
            gap = units - have - given.get(name, 0)
            if gap > 0:
                short.append((-gap, name, units, have))
        if not short:
            break
        _gap, name, units, have = min(short)
        out[stack.guid] = (
            name,
            "%s's current rung eats %d %s and it carries %d"
            % (name, units, item.name, have),
        )
        given[name] = given.get(name, 0) + stack.count
    return out


def _sell_or_vendor(stack, item, price, price_why, kind, why) -> Decision:
    """SELL at the fair price when it beats the vendor, else VENDOR, else KEEP."""
    beats = disposition.AUCTION_BEATS_VENDOR_BY
    if price > 0 and price >= max(1, item.sell_price) * beats:
        return Decision(stack, item.name, SELL, kind, why, price=price, note=price_why)
    if item.sell_price > 0:
        return Decision(
            stack,
            item.name,
            VENDOR,
            kind,
            why,
            note="%s, which does not beat the vendor's %s by %dx"
            % (price_why, money(item.sell_price), beats),
        )
    return Decision(
        stack,
        item.name,
        KEEP,
        kind,
        why,
        note="%s and no vendor buys it, so it waits" % price_why,
    )


def plan(
    stacks,
    items: dict,
    members,
    held: dict,
    *,
    casts=(),
    history=(),
    house: int = 0,
    carried=None,
    entries=(),
) -> Forecast:
    """The vault's forecast.

    `stacks` are the vault's Stack rows, `items` entry -> Item, `held` entry ->
    units the guild holds outside the vault (members' bags, banks and post),
    `carried` name -> {entry: units in that member's bags and bank}, for the
    hand-off. `entries` names more items to judge beside the vault's, so a
    material no vault holds (a guild with no tab) still gets its target.
    """
    carried = carried or {}
    need_of = needs(members, casts)
    by_entry: dict = {}
    for stack in stacks:
        by_entry.setdefault(int(stack.entry), []).append(stack)
    lines = []
    over: dict = {}
    fair: dict = {}
    given: dict = {}
    judged = set(by_entry) | {int(e) for e in entries}
    for entry in sorted(
        judged,
        key=lambda e: (items.get(e) is None, getattr(items.get(e), "name", ""), e),
    ):
        item = items.get(entry)
        if item is None:
            continue
        mine = sorted(by_entry.get(entry, ()), key=lambda s: (-s.count, s.guid))
        vault = sum(s.count for s in mine)
        outside = max(0, _int(held.get(entry)))
        total = vault + outside
        kind, target, why = judge(item, total, members, need_of.get(entry))
        surplus = max(0, total - target)
        price, price_why = fair_price(history, entry, house)
        if surplus and kind in (NOW, LATER, SURPLUS, JUNK):
            over[entry] = "the guild holds %d %s against a target of %d" % (
                total,
                item.name,
                target,
            )
            if price:
                fair[entry] = price
        if not mine:
            if surplus and kind != RAID:
                lines.append(Line(entry, item.name, 0, 0, total, target, kind, why))
            continue
        # THE MEMBERS' OWN STOCK IS EATEN FIRST: it is in the bags where the
        # casts happen. The vault keeps only what the target still asks for.
        keep_units = max(0, target - outside) if kind not in (RAID, UNJUDGED) else vault
        decisions = []
        kept = 0
        keep_stacks = []
        for stack in mine:
            if kind == JUNK:
                decisions.append(
                    _sell_or_vendor(stack, item, 0, "it is grey", kind, why)
                )
                continue
            if kept < keep_units:
                kept += stack.count
                keep_stacks.append(stack)
                continue
            decisions.append(
                _sell_or_vendor(stack, item, price, price_why, SURPLUS, why)
            )
        need = need_of.get(entry)
        gives = (
            _give(keep_stacks, need, carried, item, given)
            if need and kind == NOW
            else {}
        )
        for stack in keep_stacks:
            if stack.guid in gives:
                taker, because = gives[stack.guid]
                decisions.append(
                    Decision(
                        stack, item.name, GIVE, kind, why, taker=taker, note=because
                    )
                )
            else:
                decisions.append(Decision(stack, item.name, KEEP, kind, why))
        lines.append(
            Line(
                entry,
                item.name,
                vault,
                len(mine),
                total,
                target,
                kind,
                why,
                tuple(sorted(decisions, key=lambda d: d.stack.guid)),
            )
        )
    short = {}
    for entry, need in need_of.items():
        names = frozenset(
            name
            for name, units in need.by_member.items()
            if units > _int((carried.get(name) or {}).get(entry))
        )
        if names:
            short[entry] = names
    return Forecast(tuple(lines), over, fair, short)


# ---------------------------------------------------------------------------
# THE FACTS, READ THE SAME WAY BY THE BRIDGE AND THE SITE.

_TEMPLATE_COLUMNS = (
    "it.entry AS entry, it.name AS name, it.class AS item_class, "
    "it.subclass AS subclass, it.Quality AS quality, it.stackable AS max_stack, "
    "it.SellPrice AS sell_price, it.RequiredSkill AS required_skill, "
    "it.RequiredSkillRank AS required_rank"
)

GUILD_SQL = (
    "SELECT gm.guildid AS guildid, g.name AS guild FROM guild_member gm "
    "JOIN characters c ON c.guid = gm.guid JOIN guild g ON g.guildid = gm.guildid "
    "WHERE c.name IN (%s) ORDER BY gm.guildid LIMIT 1"
)

VAULT_SQL = (
    "SELECT gbi.item_guid AS guid, gbi.TabId AS tab, ii.itemEntry AS item_entry, "
    "ii.count AS count, " + _TEMPLATE_COLUMNS + " FROM guild_bank_item gbi "
    "JOIN item_instance ii ON ii.guid = gbi.item_guid "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE gbi.guildid = %s"
)

MEMBERS_SQL = (
    "SELECT c.name AS name, c.level AS level, cs.skill AS skill, cs.value AS value "
    "FROM guild_member gm JOIN characters c ON c.guid = gm.guid "
    "LEFT JOIN character_skills cs ON cs.guid = c.guid AND cs.skill IN ("
    + ", ".join(
        str(s)
        for s in sorted(set(craft.RECIPES) | set(guildshare.SKILL_LINES.values()))
    )
    + ") WHERE gm.guildid = %s"
)

# Every member's stacks in its bags and bank (the worn slots are gear, never a
# material), by entry. The vault's own entries and the ladder's materials.
CARRIED_SQL = (
    "SELECT c.name AS name, ii.itemEntry AS entry, SUM(ii.count) AS units "
    "FROM guild_member gm JOIN characters c ON c.guid = gm.guid "
    "JOIN character_inventory ci ON ci.guid = c.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "WHERE gm.guildid = %%s AND NOT (ci.bag = 0 AND ci.slot < 19) "
    "AND ii.itemEntry IN (%s) GROUP BY c.name, ii.itemEntry"
)

POSTED_SQL = (
    "SELECT ii.itemEntry AS entry, SUM(ii.count) AS units "
    "FROM guild_member gm JOIN mail m ON m.receiver = gm.guid "
    "JOIN mail_items mi ON mi.mail_id = m.id "
    "JOIN item_instance ii ON ii.guid = mi.item_guid "
    "WHERE gm.guildid = %%s AND ii.itemEntry IN (%s) GROUP BY ii.itemEntry"
)

CASTS_SQL = (
    "SELECT oc.target_name AS name, oc.command AS spell, COUNT(*) AS n "
    "FROM overseer_command oc JOIN characters c ON c.name = oc.target_name "
    "JOIN guild_member gm ON gm.guid = c.guid "
    "WHERE gm.guildid = %s AND oc.kind = 'cast' AND oc.status = 'applied' "
    "AND oc.created_at > NOW() - INTERVAL %s DAY "
    "GROUP BY oc.target_name, oc.command"
)

HISTORY_SQL = (
    "SELECT house, item_entry, item_count, bid, buyout, price_paid, outcome "
    "FROM overseer_auction_history WHERE item_entry IN (%s) "
    "AND occurred_at > NOW() - INTERVAL 30 DAY"
)

TEMPLATES_SQL = (
    "SELECT "
    + _TEMPLATE_COLUMNS
    + " FROM acore_world.item_template it WHERE it.entry IN (%s)"
)


def item_from_row(row) -> Item:
    return Item(
        entry=_int(row.get("entry") or row.get("item_entry")),
        name=str(row.get("name") or ""),
        item_class=_int(row.get("item_class")),
        subclass=_int(row.get("subclass")),
        quality=_int(row.get("quality"), 1),
        max_stack=max(1, _int(row.get("max_stack"), 1)),
        sell_price=_int(row.get("sell_price")),
        required_skill=_int(row.get("required_skill")),
        required_rank=_int(row.get("required_rank")),
    )


def members_from_rows(rows, family=()) -> tuple:
    family = {str(n) for n in family}
    levels: dict = {}
    skills: dict = {}
    for row in rows:
        name = str(row.get("name") or "")
        if not name:
            continue
        levels[name] = _int(row.get("level"))
        skills.setdefault(name, {})
        if row.get("skill") is not None:
            skills[name][_int(row.get("skill"))] = _int(row.get("value"))
    return tuple(
        Member(name, levels[name], skills[name], name in family)
        for name in sorted(levels)
    )


@dataclass(frozen=True)
class Facts:
    guild: str = ""
    stacks: tuple = ()
    items: dict = field(default_factory=dict)
    members: tuple = ()
    held: dict = field(default_factory=dict)
    carried: dict = field(default_factory=dict)
    casts: tuple = ()
    history: tuple = ()

    def plan(self, house: int = 0) -> Forecast:
        """The forecast over these facts, named for their guild."""
        forecast = plan(
            self.stacks,
            self.items,
            self.members,
            self.held,
            casts=self.casts,
            history=self.history,
            house=house,
            carried=self.carried,
            entries=LADDER_ENTRIES,
        )
        return replace(forecast, guild=self.guild)


def _marks(values) -> str:
    return ",".join(["%s"] * len(values))


def read(cur, names) -> Facts:
    """Every fact `plan` needs for the guild of `names`, over `cur`."""
    names = [str(n) for n in names or () if n]
    if not names:
        return Facts()
    cur.execute(GUILD_SQL % _marks(names), names)
    row = cur.fetchone()
    if not row:
        return Facts()
    guild_id = _int(row["guildid"])
    cur.execute(VAULT_SQL, (guild_id,))
    vault_rows = [dict(r) for r in cur.fetchall()]
    stacks = tuple(
        Stack(
            _int(r["guid"]),
            _int(r["item_entry"]),
            max(1, _int(r["count"], 1)),
            _int(r.get("tab")),
        )
        for r in vault_rows
    )
    items = {i.entry: i for i in (item_from_row(r) for r in vault_rows)}
    cur.execute(MEMBERS_SQL, (guild_id,))
    members = members_from_rows([dict(r) for r in cur.fetchall()], names)
    entries = sorted(set(items) | LADDER_ENTRIES)
    missing = [e for e in entries if e not in items]
    if missing:
        cur.execute(TEMPLATES_SQL % _marks(missing), missing)
        items.update(
            {i.entry: i for i in (item_from_row(dict(r)) for r in cur.fetchall())}
        )
    cur.execute(CARRIED_SQL % _marks(entries), (guild_id, *entries))
    carried: dict = {}
    held: dict = {}
    for r in cur.fetchall():
        name, entry, units = str(r["name"]), _int(r["entry"]), _int(r["units"])
        carried.setdefault(name, {})[entry] = units
        held[entry] = held.get(entry, 0) + units
    cur.execute(POSTED_SQL % _marks(entries), (guild_id, *entries))
    for r in cur.fetchall():
        held[_int(r["entry"])] = held.get(_int(r["entry"]), 0) + _int(r["units"])
    cur.execute(CASTS_SQL, (guild_id, PACE_DAYS))
    casts = tuple(
        (str(r["name"]), _int(r["spell"]), _int(r["n"])) for r in cur.fetchall()
    )
    cur.execute(HISTORY_SQL % _marks(entries), entries)
    history = tuple(dict(r) for r in cur.fetchall())
    return Facts(
        str(row.get("guild") or ""),
        stacks,
        items,
        members,
        held,
        carried,
        casts,
        history,
    )
