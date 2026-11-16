"""Which guild member an enchanter should enchant, with which recipe, on which
worn piece (the caller of the module's `enchant-for` verb).

WHY IT EXISTS. A guild's enchanters disenchant (ITEMPLAN_DISENCHANT) and the
materials are routed to them, but the module's own enchant craft only ever
casts on the enchanter's OWN items, so nothing spent those materials on
anyone else's gear. The module now answers `kind='trade'` rows whose command
is `enchant-for target:<guid> slot:<n> spell:<id>`: the enchanter opens a
trade with the member, the member's worn item goes in the "will not be
traded" slot, the enchanter casts the recipe at it and both accept. The item
never changes owner and the enchanter pays the reagents from its own bags.
This module is the decision of what to ask for.

THE RULE, in the order it decides.
  1. Only an enchanter that KNOWS the recipe (a `character_spell` row: a
     positive fact only, an absent row is "unknown", never "not known" the
     other way round), holds the reagents and a Runed Rod of the tier the
     recipe needs, and is online.
  2. Only a guild member in the SAME guild, online, on the same map and close
     enough to trade (TOGETHER_YARDS, inside the core's 11.11 yard trade
     distance). The module checks the same things again and refuses.
  3. Only a WORN piece the recipe fits (the core's item class, subclass and
     inventory type masks, read from the Spell.dbc rows frozen in
     data/enchants.json by tools/gen_enchants.py), whose current permanent
     enchant is empty or one of the Enchanting enchants in that file. An
     enchant from another source (a libram, a kit) is never written over.
  4. The gain is the member's own judge's: `gearscore.score` for its spec with
     the new enchant's stats instead of the current one's, or the role weights
     of `statweights` where the spec has no opinion (the same two rungs
     `equipscore.value` uses). A gain of nothing, or a loss, is never asked for.
  5. Who goes first: raid seats (`raidteams.seats`), then tanks and healers,
     then everybody else; inside a rank the biggest gain first. One job per
     enchanter and one per member each pass, so a pass never asks two
     enchants of one pair of hands or two casts at one window.

Nothing is granted: this writes no item, spell, skill or gold, and the recipe
must already be known. PURE: rows in, jobs out. No MySQL, no clock.
"""

from __future__ import annotations

import functools
import json
import math
import os
from typing import NamedTuple

import equipscore
import fireplan
import gearscore
import raidroles
import raidteams
import statweights
import world_data

ENV_SWITCH = "ENCHANT_FOR"
PREFIX = "enchant-for:"
SOURCE = "enchant-for"
# The build fact the module reports (overseer_build.enchant_for) when it
# answers the verb. A realm that does not report it is never sent a row.
CAPABILITY_FACT = "enchant_for"
CAPABILITY = "trade"

# Inside the core's TRADE_DISTANCE (11.11 yards), because the position read is
# minutes stale.
TOGETHER_YARDS = 8.0

# Item stat type -> the name gearscore scores, from gearscore itself.
KIND_RESIST, KIND_DAMAGE, KIND_STAT = 4, 2, 5
ARMOR_RESIST_ARG = 0

# Runed Rods by tier, lowest first: the item that answers each TotemCategory
# (6 copper .. 9 truesilver, 10 arcanite). A higher rod answers a lower rung.
ROD_CATEGORY_FIRST = 6
ROD_ITEMS = (6218, 6339, 11130, 11145, 16207)

CATALOGUE_PATH = str(world_data.DATA_ROOT / "data" / "enchants.json")

PRIORITY_SEAT, PRIORITY_ROLE, PRIORITY_REST = 0, 1, 2


def enabled(environ=None) -> bool:
    """On unless ENCHANT_FOR says off/0/false/no; the module's own capability
    fact is the gate that keeps it inert until the verb exists."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")


class Recipe(NamedTuple):
    spell: int
    name: str
    enchant: int
    enchant_name: str
    effects: tuple  # ((kind, amount, arg), ...) of the enchantment
    reagents: tuple  # ((item entry, count), ...)
    tools: tuple  # TotemCategory ids
    item_class: int
    subclass_mask: int
    invtype_mask: int


@functools.lru_cache(maxsize=None)
def catalogue(path: str = CATALOGUE_PATH) -> tuple:
    """Every Enchanting recipe that enchants an item, from the frozen file."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    out = []
    for r in data["recipes"]:
        if r["item_class"] not in (2, 4):
            continue
        out.append(
            Recipe(
                spell=int(r["spell"]),
                name=str(r["name"]),
                enchant=int(r["enchant"]),
                enchant_name=str(r["enchant_name"]),
                effects=tuple(tuple(int(v) for v in e) for e in r["effects"]),
                reagents=tuple((int(i), int(c)) for i, c in r["reagents"]),
                tools=tuple(int(t) for t in r["tools"]),
                item_class=int(r["item_class"]),
                subclass_mask=int(r["subclass_mask"]),
                invtype_mask=int(r["invtype_mask"]),
            )
        )
    return tuple(out)


def enchant_ids(recipes=None) -> frozenset:
    """The enchantment ids Enchanting makes: the only ones ever written over."""
    return frozenset(
        r.enchant for r in (recipes if recipes is not None else catalogue())
    )


class Enchanter(NamedTuple):
    name: str
    guild: str
    known: frozenset  # spell ids it holds in character_spell
    bags: dict  # item entry -> count in its bags


class Member(NamedTuple):
    name: str
    guid: int
    guild: str
    online: bool
    map_id: int
    x: float
    y: float
    z: float


class Job(NamedTuple):
    enchanter: str
    member: str
    member_guid: int
    slot: int
    spell: int
    recipe: str
    enchant: int
    item_entry: int
    item_name: str
    gain: float
    priority: int
    reagents: tuple


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def together(a: Member, b: Member) -> bool:
    """Both online, one map, within TOGETHER_YARDS of each other."""
    if not (a.online and b.online) or a.map_id != b.map_id:
        return False
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z)) <= TOGETHER_YARDS


def fits(recipe: Recipe, row: dict) -> bool:
    """The core's own item test for an enchant recipe: item class, then the
    subclass mask, then the inventory type mask (a zero mask is no limit)."""
    if _int(row.get("item_class")) != recipe.item_class:
        return False
    if recipe.subclass_mask and not recipe.subclass_mask & (
        1 << _int(row.get("item_subclass"))
    ):
        return False
    if recipe.invtype_mask and not recipe.invtype_mask & (
        1 << _int(row.get("inventory_type"))
    ):
        return False
    return True


def has_tools(recipe: Recipe, bags: dict) -> bool:
    """Every Runed Rod category the recipe names is answered by a rod of that
    tier or higher in the bags. A tool category that is not a rod is never met."""
    for category in recipe.tools:
        tier = category - ROD_CATEGORY_FIRST
        if not 0 <= tier < len(ROD_ITEMS):
            return False
        if not any(_int(bags.get(rod)) > 0 for rod in ROD_ITEMS[tier:]):
            return False
    return True


def has_reagents(recipe: Recipe, bags: dict) -> bool:
    return all(_int(bags.get(item)) >= count for item, count in recipe.reagents)


def stats_of_effects(effects, row: dict) -> tuple:
    """The enchantment's worth as ({item stat type: amount}, {name: amount}).

    The first is what `gearscore.add_stats` folds in (stats); the second is
    what it has no stat type for (armor, weapon damage per second). A proc, an
    equip spell or a resistance adds nothing here."""
    typed: dict = {}
    named: dict = {}
    delay = _int(row.get("delay"))
    for kind, amount, arg in effects:
        if kind == KIND_STAT:
            typed[arg] = typed.get(arg, 0) + amount
        elif kind == KIND_RESIST and arg == ARMOR_RESIST_ARG:
            named["armor"] = named.get("armor", 0) + amount
        elif kind == KIND_DAMAGE and delay > 0:
            named["weapon_dps"] = named.get("weapon_dps", 0) + amount * 1000.0 / delay
    return typed, named


def _with(base: dict, effects, row: dict) -> dict:
    typed, named = stats_of_effects(effects, row)
    out = gearscore.add_stats(base, typed)
    for name, amount in named.items():
        out[name] = out.get(name, 0) + amount
    return out


def _worth(stats: dict, wearer, key: str) -> tuple:
    gs = gearscore.score(stats, wearer.spec, wearer.level, key) if wearer.spec else 0.0
    return gs, equipscore.role_score(stats, wearer.role)


KIND_RESIST_FIRE_ARG = 2
# What one point of fire resistance a seat is SHORT of its Molten Core target
# is worth, in gear score points. The spec weights price fire resistance at
# about a half point, which is nothing beside +7 strength; for a seat the raid
# asks fire resistance of (fireplan.FIRE_TARGET) the shortfall is the point of
# the night, so it is priced like the best stat a point of tanking buys.
MC_FIRE_WEIGHT = 2.0


def fire_targets(guilds) -> dict:
    """name -> the fire resistance the Molten Core plan asks of that seat.

    The first tank seat of a guild's first group is its main tank
    (fireplan.FIRE_TARGET's 200), another tank takes 120, a healer 60 and a
    damage seat none (raidsupply.fire_target's own numbers, read from
    fireplan). Only the approved raid seats are named: the guild's plan is the
    Molten Core lineup, the one raid this realm models."""
    out: dict = {}
    for guild in guilds:
        main_taken = False
        for seat in raidteams.seats(guild):
            if seat.seat == raidroles.SEAT_TANK:
                key = fireplan.TANK if main_taken else fireplan.MAIN_TANK
                main_taken = True
            elif seat.seat == raidroles.SEAT_HEALER:
                key = fireplan.HEALER
            else:
                continue
            out[seat.name] = fireplan.FIRE_TARGET[key]
    return out


def _fire_of(effects) -> int:
    return sum(
        int(amount)
        for kind, amount, arg in effects
        if kind == KIND_RESIST and arg == KIND_RESIST_FIRE_ARG
    )


def fire_credit(effects, shortfall: int) -> int:
    """The fire resistance an enchant adds that the seat still needs: what it
    gives, never more than the points the seat is short of its target."""
    return min(_fire_of(effects), max(0, int(shortfall)))


def gain_of(
    row: dict, current_effects, recipe: Recipe, wearer, fire_short: int = 0
) -> float:
    """What the recipe's enchant adds over the current one, in the member's
    own judge's units: gear score where the spec has an opinion of either
    piece, else the role score. Zero or less means not worth a cast."""
    base = equipscore.stats_of(row, None)
    key = equipscore._KEY.get(_int(row.get("inventory_type")), "")
    old = _with(base, current_effects, row)
    new = _with(base, recipe.effects, row)
    old_gs, old_role = _worth(old, wearer, key)
    new_gs, new_role = _worth(new, wearer, key)
    if max(old_gs, new_gs) >= equipscore.SCORE_FLOOR:
        gain = new_gs - old_gs
    else:
        gain = new_role - old_role
    credit = fire_credit(recipe.effects, fire_short) - fire_credit(
        current_effects, fire_short
    )
    return gain + credit * MC_FIRE_WEIGHT


def priority_of(wearer, seat_names) -> int:
    if wearer.name in seat_names:
        return PRIORITY_SEAT
    if wearer.role in (statweights.TANK, statweights.HEALER):
        return PRIORITY_ROLE
    return PRIORITY_REST


def _worn(worn_rows) -> dict:
    out: dict = {}
    for row in worn_rows or ():
        if row.get("equipment_slot") is None:
            continue
        out.setdefault(str(row.get("holder") or ""), {})[
            _int(row["equipment_slot"])
        ] = row
    return out


def _current_effects(row: dict, book, own_enchants: frozenset):
    """(effects of the permanent enchant, ok). ok is False for an enchant that
    Enchanting does not make or that the book cannot describe."""
    ids = _permanent_id(row)
    if not ids:
        return (), True
    if ids not in own_enchants or book is None:
        return (), False
    entry = book.enchants.get(ids)
    if entry is None:
        return (), False
    return tuple(tuple(int(v) for v in e) for e in entry[1]), True


def _permanent_id(row: dict) -> int:
    text = str(row.get("enchantments") or "").split()
    return _int(text[0]) if text else 0


def _usable(enchanter: Enchanter, recipes) -> list:
    """The recipes this enchanter knows and can pay for right now."""
    return [
        r
        for r in recipes
        if r.spell in enchanter.known
        and has_reagents(r, enchanter.bags)
        and has_tools(r, enchanter.bags)
    ]


def _reachable(
    enchanter: Enchanter, e_member: Member, name: str, members
) -> Member | None:
    """The member `name` when the enchanter may enchant them: another person of
    the same guild, in the world and standing within trade distance."""
    member = members.get(name)
    if (
        member is None
        or name == enchanter.name
        or not enchanter.guild
        or member.guild != enchanter.guild
        or not together(e_member, member)
    ):
        return None
    return member


def _job_for(
    enchanter, member, wearer, slot, row, recipe, effects, seat_names, fire_short=0
):
    """One Job when the recipe fits the worn piece and gains something, else None."""
    if not fits(recipe, row) or recipe.enchant == _permanent_id(row):
        return None
    gain = gain_of(row, effects, recipe, wearer, fire_short)
    if gain <= equipscore.EPSILON:
        return None
    return Job(
        enchanter=enchanter.name,
        member=member.name,
        member_guid=member.guid,
        slot=slot,
        spell=recipe.spell,
        recipe=recipe.name,
        enchant=recipe.enchant,
        item_entry=_int(row.get("entry")),
        item_name=str(row.get("name") or ""),
        gain=gain,
        priority=priority_of(wearer, seat_names),
        reagents=recipe.reagents,
    )


def _fire_short(pieces: dict, target: int) -> int:
    """How far the worn pieces' own fire resistance is below the seat's target."""
    worn = sum(_int(row.get("fire_res")) for row in pieces.values())
    return max(0, int(target) - worn)


def _jobs_on(
    enchanter,
    member,
    wearer,
    pieces,
    usable,
    book,
    own_enchants,
    seat_names,
    fire_target=0,
) -> list:
    """Every job one enchanter could do on one member's worn pieces."""
    fire_short = _fire_short(pieces, fire_target)
    out = []
    for slot, row in pieces.items():
        effects, ok = _current_effects(row, book, own_enchants)
        if not ok:
            continue
        for recipe in usable:
            job = _job_for(
                enchanter,
                member,
                wearer,
                slot,
                row,
                recipe,
                effects,
                seat_names,
                fire_short,
            )
            if job is not None:
                out.append(job)
    return out


def candidates(
    enchanters,
    members,
    wearer_rows,
    worn_rows,
    *,
    book=None,
    seat_names=frozenset(),
    tanks=(),
    recipes=None,
    fire_targets=None,
) -> list:
    """Every (job) worth asking for this pass, before one-per-person is applied."""
    recipes = tuple(recipes if recipes is not None else catalogue())
    own_enchants = enchant_ids(recipes)
    wearers = equipscore._wearers(
        wearer_rows, [str(r.get("name") or "") for r in wearer_rows or ()], tanks
    )
    worn = _worn(worn_rows)
    out = []
    for enchanter in enchanters:
        e_member = members.get(enchanter.name)
        usable = _usable(enchanter, recipes) if e_member and e_member.online else []
        for name, wearer in wearers.items() if usable else ():
            member = _reachable(enchanter, e_member, name, members)
            if member is not None:
                out += _jobs_on(
                    enchanter,
                    member,
                    wearer,
                    worn.get(name, {}),
                    usable,
                    book,
                    own_enchants,
                    seat_names,
                    (fire_targets or {}).get(name, 0),
                )
    return out


def plan(
    enchanters,
    members,
    wearer_rows,
    worn_rows,
    *,
    book=None,
    seat_names=frozenset(),
    tanks=(),
    recipes=None,
    fire_targets=None,
) -> tuple:
    """The jobs to write, best first: seats, then tanks and healers, then the
    rest, the biggest gain first inside a rank, one per enchanter and per
    member."""
    pool = candidates(
        enchanters,
        members,
        wearer_rows,
        worn_rows,
        book=book,
        seat_names=seat_names,
        tanks=tanks,
        recipes=recipes,
        fire_targets=fire_targets,
    )
    pool.sort(
        key=lambda j: (j.priority, -j.gain, j.member, j.enchanter, j.slot, j.spell)
    )
    busy_enchanters: set = set()
    busy_members: set = set()
    chosen = []
    for job in pool:
        if job.enchanter in busy_enchanters or job.member in busy_members:
            continue
        busy_enchanters.add(job.enchanter)
        busy_members.add(job.member)
        chosen.append(job)
    return tuple(chosen)


def command(job: Job) -> str:
    """The row's command, in the module's grammar."""
    return "enchant-for target:%d slot:%d spell:%d" % (
        job.member_guid,
        job.slot,
        job.spell,
    )


def lines(jobs) -> tuple:
    """One log line per job, naming who, what, where and how much it gains."""
    return tuple(
        "%s %s puts %s (%d) on %s's %s (entry %d, slot %d), gain %.2f, rank %d, "
        "reagents %s"
        % (
            PREFIX,
            j.enchanter,
            j.recipe,
            j.spell,
            j.member,
            j.item_name,
            j.item_entry,
            j.slot,
            j.gain,
            j.priority,
            ",".join("%dx%d" % pair for pair in j.reagents) or "none",
        )
        for j in jobs
    )
