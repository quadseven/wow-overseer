"""Molten Core supply (#275): what a raid night eats, the fire resistance each
role should wear, and what the guild corps makes or buys next to close the gap.

WHAT WAS ASKED FOR. Consumables per raid night of Molten Core (Greater Fire
Protection, Major Healing and Mana, Elixir of the Mongoose, a flask, Juju, food)
and fire resistance per role, tanks first; the guild's alchemists crafting the
potions, its gatherers feeding them, the auction house buying the rest within a
budget drawn from the guild bank, and all of it routed to the raiders who are
short. Jev picks what to make or buy next (`raid_supply`).

WHAT THE REALM SAID (dev, read-only, 2026-09-23). Cave's forty raiders wore 10
fire resistance between them and held no Greater Fire Protection Potion and no
flask. Reagents come from the running worldserver's Spell.dbc (md5
543b9fe61355b6a77a01714d52fea2e5); recipe sources from `trainer_spell`,
`item_template`, `npc_vendor` and `creature_loot_template`:

    Greater Fire Protection  17574  Elemental Fire, Dreamfoil, Crystal Vial.
                                    Recipe 13494: no trainer, no vendor; drops
                                    in Lower Blackrock Spire (about 4 percent)
    Major Healing Potion     17556  2 Golden Sansam, Mountain Silversage, Vial.
                                    Trainer, rank 275; nearly every alchemist
                                    in the guild knows it
    Major Mana Potion        17580  3 Dreamfoil, 2 Icecap, Vial. Recipe 13501,
                                    sold by Magnus Frostwake for 3 gold
    Elixir of the Mongoose   17571  2 Mountain Silversage, 2 Plaguebloom, Vial.
                                    Recipe 13491, a drop
    The three flasks                Recipes 13519, 13521, 13520: boss drops in
                                    Upper Blackrock Spire, Scholomance and
                                    Stratholme
    Smoked Desert Dumplings  24801  Sandworm Meat; most of the guild's cooks
                                    know it
    Juju Power, Juju Might          quest-class items with no vendor, no drop
                                    and no craft here: the auction house only
    Wizardweave Leggings     18421  16 fire resistance. 4 Bolt of Runecloth,
                                    Dream Dust, Rune Thread; many tailors know it

EVERY PER-RAIDER NUMBER AND EVERY RESISTANCE TARGET IS A CONVENTION, as
raidgoals.py says of its own: Molten Core gates nobody on either. They are here
so the Raid tab has something to count against and the corps something to work
toward, and they are named constants so a reader can move them.

PURE MODULE: rows in, a plan and sentences out. The bridge reads the facts,
asks Jev, and writes the rows a step names through the corps' own runner. The
only verbs used are ones the module already has: walk-to-vendor,
walk-to-mailbox, `send` and `take-item` letters, a cast of a known recipe, `use`
of a carried recipe, an auction `buy`, `guild bank withdraw`, and the playerbot
equip command. Never a give, never a GM command.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import auction
import classic
import guildcorps
import guildroute
import jev
import jev_choices
import raidlineup

SOURCE = "raidsupply"
KIND = "raid_supply"

ALCHEMY = guildcorps.ALCHEMY
TAILORING = guildcorps.TAILORING
COOKING = guildcorps.COOKING

# The corps role that works each trade (guildcorps.ROLES).
ROLE_OF_SKILL = {ALCHEMY: "alchemist", TAILORING: "tailor", COOKING: "cook"}

# ---------------------------------------------------------------------------
# WHO A RAIDER IS, FOR THE PURPOSE OF A SHOPPING LIST.

TANK = "tank"
HEALER = "healer"
PHYSICAL = "physical"
CASTER = "caster"
MAIN_TANK = "main tank"
ROLE_ORDER = (TANK, HEALER, PHYSICAL, CASTER)

WARRIOR, PALADIN, HUNTER, ROGUE, PRIEST = 1, 2, 3, 4, 5
DEATH_KNIGHT, SHAMAN, MAGE, WARLOCK, DRUID = 6, 7, 8, 9, 11
# A damage dealer of these classes hits things; the rest cast.
PHYSICAL_CLASSES = frozenset({WARRIOR, PALADIN, HUNTER, ROGUE, DEATH_KNIGHT})
# A physical damage dealer that still spends mana.
MANA_PHYSICAL = frozenset({PALADIN, HUNTER})
# Cloth is these classes' own armor; anyone else gives up armor to wear it.
CLOTH_CLASSES = frozenset({PRIEST, MAGE, WARLOCK})


def role_of(lineup_role: str, class_id) -> str:
    """tank, healer, physical or caster, from raidlineup's role and the class."""
    if lineup_role in (TANK, HEALER):
        return lineup_role
    return PHYSICAL if int(class_id or 0) in PHYSICAL_CLASSES else CASTER


@dataclass(frozen=True)
class Raider:
    """One placed raider, as the lineup and the paper doll read it."""

    name: str
    role: str
    class_id: int = 0
    main_tank: bool = False
    family: bool = False
    fire: int = 0  # worn fire resistance, summed
    worn_fire: tuple = ()  # (equipment slot, fire resistance) per worn item

    def slot_fire(self, slot) -> int:
        return sum(int(f) for s, f in self.worn_fire if int(s) == int(slot))


def raiders_from_lineup(lineup, classes, fire_rows=(), family=()) -> list:
    """Raider rows from a raidlineup result.

    `classes` maps a name to its class id; `fire_rows` are worn items with
    `name`, `slot` and `fire_res`. The main tank is the first tank the lineup
    placed: group one's, which is the group the head of the raid leads.
    """
    worn = {}
    for row in fire_rows or ():
        name = str(row.get("name") or "")
        fire = int(row.get("fire_res") or 0)
        worn.setdefault(name, []).append((int(row.get("slot") or 0), fire))
    out, main_taken = [], False
    for group in (lineup or {}).get("groups") or ():
        for member in group.get("members") or ():
            name = str(member.get("name") or "")
            if not name:
                continue
            role = role_of(member.get("role", "dps"), classes.get(name))
            main = role == TANK and not main_taken
            main_taken = main_taken or main
            items = tuple(worn.get(name, ()))
            out.append(
                Raider(
                    name=name,
                    role=role,
                    class_id=int(classes.get(name) or 0),
                    main_tank=main,
                    family=name in set(family or ()),
                    fire=sum(f for _, f in items),
                    worn_fire=items,
                )
            )
    return out


# ---------------------------------------------------------------------------
# WHAT A NIGHT EATS.


@dataclass(frozen=True)
class Make:
    """One craft that makes a supply, as the realm measured it.

    `reagents` are gathered or looted (entry, count) pairs, posted in by the
    guild; `vendor` are (entry, count, copper each) pairs a vendor sells.
    `recipe_item` is the item that teaches the craft, 0 for a trainer recipe;
    `recipe_price` is its vendor price, 0 when no vendor sells it.
    """

    spell: int
    skill: int
    reagents: tuple
    vendor: tuple = ()
    recipe_item: int = 0
    recipe_price: int = 0


@dataclass(frozen=True)
class Supply:
    """One thing a Molten Core night eats, per raider of each role."""

    entry: int
    name: str
    per_role: tuple  # (tank, healer, physical, caster)
    make: Make | None = None
    source: str = ""

    def per_raider(self, raider: Raider) -> int:
        count = dict(zip(ROLE_ORDER, self.per_role)).get(raider.role, 0)
        if self.entry == MAJOR_MANA and raider.role == PHYSICAL:
            return MANA_FOR_PHYSICAL if raider.class_id in MANA_PHYSICAL else 0
        return int(count)


CRYSTAL_VIAL = (8925, 1, 2500)
ELEMENTAL_FIRE, DREAMFOIL, GOLDEN_SANSAM = 7068, 13463, 13464
MOUNTAIN_SILVERSAGE, PLAGUEBLOOM, ICECAP = 13465, 13466, 13467
BLACK_LOTUS, GROMSBLOOD, STONESCALE_OIL = 13468, 8846, 13423
SANDWORM_MEAT, BOLT_OF_RUNECLOTH, DREAM_DUST, RUNE_THREAD = 20424, 14048, 11176, 14341
GREATER_FIRE_PROTECTION, MAJOR_HEALING, MAJOR_MANA = 13457, 13446, 13444
MANA_FOR_PHYSICAL = 2

# THE NIGHT, per raider, in the order the heuristic works it: the fire potion
# first because Ragnaros is the night's wall, then the potions every role
# drinks, then the flasks, the elixir, food and Juju.
SUPPLIES = (
    Supply(
        GREATER_FIRE_PROTECTION,
        "Greater Fire Protection Potion",
        (4, 2, 2, 2),
        Make(
            17574,
            ALCHEMY,
            ((ELEMENTAL_FIRE, 1), (DREAMFOIL, 1)),
            (CRYSTAL_VIAL,),
            13494,
        ),
        "Recipe 13494: no trainer and no vendor; it drops from Firebrand "
        "Invokers and Pyromancers in Lower Blackrock Spire (about 4 percent) "
        "and from a world-drop table, else the auction house",
    ),
    Supply(
        MAJOR_HEALING,
        "Major Healing Potion",
        (5, 2, 3, 2),
        Make(
            17556,
            ALCHEMY,
            ((GOLDEN_SANSAM, 2), (MOUNTAIN_SILVERSAGE, 1)),
            (CRYSTAL_VIAL,),
        ),
        "a trainer teaches it at Alchemy 275",
    ),
    Supply(
        MAJOR_MANA,
        "Major Mana Potion",
        (0, 5, 0, 3),
        Make(
            17580, ALCHEMY, ((DREAMFOIL, 3), (ICECAP, 2)), (CRYSTAL_VIAL,), 13501, 30000
        ),
        "Recipe 13501 is sold by Magnus Frostwake for 3 gold and drops from "
        "Darkmaster Gandling",
    ),
    Supply(
        13510,
        "Flask of the Titans",
        (1, 0, 0, 0),
        Make(
            17635,
            ALCHEMY,
            ((GROMSBLOOD, 7), (STONESCALE_OIL, 3), (BLACK_LOTUS, 1)),
            (CRYSTAL_VIAL,),
            13519,
        ),
        "Recipe 13519 drops from General Drakkisath (3 percent)",
    ),
    Supply(
        13511,
        "Flask of Distilled Wisdom",
        (0, 1, 0, 0),
        Make(
            17636,
            ALCHEMY,
            ((DREAMFOIL, 7), (ICECAP, 3), (BLACK_LOTUS, 1)),
            (CRYSTAL_VIAL,),
            13520,
        ),
        "Recipe 13520 drops from Balnazzar (3 percent)",
    ),
    Supply(
        13512,
        "Flask of Supreme Power",
        (0, 0, 0, 1),
        Make(
            17637,
            ALCHEMY,
            ((DREAMFOIL, 7), (MOUNTAIN_SILVERSAGE, 3), (BLACK_LOTUS, 1)),
            (CRYSTAL_VIAL,),
            13521,
        ),
        "Recipe 13521 drops from Ras Frostwhisper (4 percent)",
    ),
    Supply(
        13452,
        "Elixir of the Mongoose",
        (1, 0, 1, 0),
        Make(
            17571,
            ALCHEMY,
            ((MOUNTAIN_SILVERSAGE, 2), (PLAGUEBLOOM, 2)),
            (CRYSTAL_VIAL,),
            13491,
        ),
        "Recipe 13491 drops from Legashi and Jadefire Rogues (about 4 percent)",
    ),
    Supply(
        20452,
        "Smoked Desert Dumplings",
        (2, 0, 2, 0),
        Make(24801, COOKING, ((SANDWORM_MEAT, 1),)),
        "a quest teaches it, and most of the guild's cooks know it; Sandworm "
        "Meat drops in Silithus",
    ),
    Supply(
        13931,
        "Nightfin Soup",
        (0, 2, 0, 2),
        None,
        "nobody in either guild knows the recipe, so it is bought",
    ),
    Supply(
        12451,
        "Juju Power",
        (1, 0, 1, 0),
        None,
        "a quest-class item with no vendor, no drop and no craft on this realm: "
        "the auction house only",
    ),
    Supply(
        12460,
        "Juju Might",
        (0, 0, 1, 0),
        None,
        "a quest-class item with no vendor, no drop and no craft on this realm: "
        "the auction house only",
    ),
)
SUPPLY_BY_ENTRY = {s.entry: s for s in SUPPLIES}

# ---------------------------------------------------------------------------
# FIRE RESISTANCE, PER ROLE. The Ragnaros tank first, as classic guilds asked
# (raidgoals' own range tops out at the same 200); other tanks next, because
# one of them takes over when the first dies; healers second.
FIRE_TARGET = {MAIN_TANK: 200, TANK: 120, HEALER: 60}


def fire_target(raider: Raider) -> int:
    if raider.main_tank:
        return FIRE_TARGET[MAIN_TANK]
    return FIRE_TARGET.get(raider.role, 0)


@dataclass(frozen=True)
class FireGear:
    """A fire resistance piece the guild can make, and who it is meant for."""

    entry: int
    name: str
    fire: int
    slot: int  # the equipment slot it goes in (EQUIPMENT_SLOT_*)
    make: Make
    wearers: frozenset


LEGS = 6
FIRE_GEAR = (
    FireGear(
        14132,
        "Wizardweave Leggings",
        16,
        LEGS,
        Make(
            18421,
            TAILORING,
            ((BOLT_OF_RUNECLOTH, 4), (DREAM_DUST, 1)),
            ((RUNE_THREAD, 1, 5000),),
        ),
        CLOTH_CLASSES,
    ),
)
FIRE_GEAR_BY_ENTRY = {g.entry: g for g in FIRE_GEAR}

# WHERE THE REST OF THE FIRE RESISTANCE COMES FROM, and why the corps does not
# make it. Said on the page so a tank's gap has a named road.
FIRE_ROADS = (
    "Enchant Cloak - Fire Resistance (+7): many of the guild's enchanters know "
    "it, but no executor applies an enchantment to another character's cloak",
    "Flarecore gloves, mantle, leggings and robe (tailoring): Fiery Core and "
    "Lava Core drop inside Molten Core, and the patterns are Thorium "
    "Brotherhood's, so they follow the first clears",
    "Dark Iron plate (blacksmithing): Dark Iron bars and Thorium Brotherhood "
    "plans, which nobody in the guild holds yet",
    "the auction house: no fire resistance piece worth wearing is listed",
    "a paladin's Fire Resistance Aura in the tank's group, which gear totals "
    "here do not count",
)

# ---------------------------------------------------------------------------
# THE PLAN.

MAKE = "make"
LEARN = "learn"
VENDOR_RECIPE = "vendor recipe"
BUY = "buy"
ROUTES = (MAKE, LEARN, VENDOR_RECIPE, BUY)


@dataclass(frozen=True)
class Line:
    """One supply against the night: wanted, held, short, and how it closes."""

    entry: int
    name: str
    want: int
    have: int
    route: str
    said: str
    makers: tuple = ()

    @property
    def short(self) -> int:
        return max(0, self.want - self.have)


@dataclass(frozen=True)
class FireLine:
    raider: Raider
    target: int

    @property
    def short(self) -> int:
        return max(0, self.target - self.raider.fire)


def night_wants(raiders) -> dict:
    """entry -> {raider name: count} for one night, only counts above zero."""
    out = {}
    for supply in SUPPLIES:
        for raider in raiders or ():
            n = supply.per_raider(raider)
            if n > 0:
                out.setdefault(supply.entry, {})[raider.name] = n
    return out


def _route(make, knowers, carriers, vendor_recipes) -> str:
    if make is None:
        return BUY
    if knowers:
        return MAKE
    if carriers:
        return LEARN
    if make.recipe_item and make.recipe_price and make.recipe_item in vendor_recipes:
        return VENDOR_RECIPE
    return BUY


def _route_said(supply, route, knowers, short) -> str:
    if not short:
        return "stocked for the night"
    if route == MAKE:
        return "%d %s it: %s" % (
            len(knowers),
            "knows" if len(knowers) == 1 else "know",
            ", ".join(sorted(knowers)[:3]) + (" and more" if len(knowers) > 3 else ""),
        )
    if route == LEARN:
        return "a guild member carries the recipe and learns it first"
    if route == VENDOR_RECIPE:
        return "an alchemist buys the recipe at a vendor first; " + supply.source
    return "bought on the auction house within the guild's budget; " + supply.source


def supply_lines(raiders, have, knowers, carriers=None, vendor_recipes=()) -> list:
    """One Line per supply the night wants, in the heuristic's order.

    `have` maps an entry to what the guild holds of it; `knowers` maps a craft
    spell to the names who know it; `carriers` maps a recipe item to the names
    carrying one; `vendor_recipes` are recipe items a vendor on some crafter's
    map sells.
    """
    wants = night_wants(raiders)
    lines = []
    for supply in SUPPLIES:
        want = sum((wants.get(supply.entry) or {}).values())
        if not want:
            continue
        make = supply.make
        who = tuple(sorted((knowers or {}).get(make.spell, ()))) if make else ()
        held = tuple((carriers or {}).get(make.recipe_item, ())) if make else ()
        route = _route(make, who, held, frozenset(vendor_recipes or ()))
        got = int((have or {}).get(supply.entry, 0))
        lines.append(
            Line(
                supply.entry,
                supply.name,
                want,
                got,
                route,
                _route_said(supply, route, who, max(0, want - got)),
                who,
            )
        )
    return lines


def fire_lines(raiders) -> list:
    """Every raider with a fire resistance target, main tank first."""
    rows = [FireLine(r, fire_target(r)) for r in raiders or () if fire_target(r)]
    order = {TANK: 0, HEALER: 1}
    rows.sort(
        key=lambda f: (
            not f.raider.main_tank,
            order.get(f.raider.role, 2),
            -f.short,
            f.raider.name,
        )
    )
    return rows


# ---------------------------------------------------------------------------
# JEV: WHAT TO MAKE OR BUY NEXT.
#
# One Choice per guild per pass over the actionable options: make or buy each
# short supply, and make each fire resistance piece somebody short can wear.
# The heuristic takes the first actionable one in SUPPLIES order, with the fire
# gear after the fire potion. ACT by default above FOCUS_THRESHOLD; below it,
# or with no answer, the heuristic's focus stands. The focus only reorders the
# corps' steps and the auction's shopping list; it never adds a step the
# heuristic would not also take.

FOCUS_THRESHOLD = 0.6


def option_for(line) -> str:
    if isinstance(line, FireGear):
        return "fire:%d" % line.entry
    return "%s:%d" % ("buy" if line.route == BUY else "make", line.entry)


def options(lines, fire, gear_wanted) -> list:
    """(option, sentence) in the heuristic's order; only what is short."""
    out = []
    for line in lines:
        if line.short:
            verb = "buy on the auction house" if line.route == BUY else "craft"
            out.append(
                (
                    option_for(line),
                    "%s %d more %s (%d held of %d wanted)"
                    % (verb, line.short, line.name, line.have, line.want),
                )
            )
        if line.entry == GREATER_FIRE_PROTECTION:
            for gear in gear_wanted:
                short = [
                    f.raider.name
                    for f in fire
                    if f.short and f.raider.class_id in gear.wearers
                ]
                out.append(
                    (
                        option_for(gear),
                        "craft %s (%d fire resistance) for %s"
                        % (gear.name, gear.fire, ", ".join(short[:4])),
                    )
                )
    return out


def heuristic_focus(opts) -> str:
    return opts[0][0] if opts else ""


def policy(environ=None) -> jev.Policy:
    return jev.policy(
        KIND, environ=environ, default_mode=jev.ACT, default_threshold=FOCUS_THRESHOLD
    )


def question(guild, lines, fire, opts, budget_left):
    """(state, questions) for "what should the guild make or buy next"."""
    state = {
        "guild": guild,
        "raid": "Molten Core, one night, forty raiders",
        "supplies": [
            {
                "item": line.name,
                "wanted": line.want,
                "held": line.have,
                "route": line.route,
            }
            for line in lines
        ],
        "fire_resistance": [
            {
                "raider": f.raider.name,
                "role": "main tank" if f.raider.main_tank else f.raider.role,
                "worn": f.raider.fire,
                "target": f.target,
            }
            for f in fire[:10]
        ],
        "auction_budget_copper": int(budget_left),
    }
    criteria = dict(opts)
    instructions = (
        "`guild` is a World of Warcraft guild preparing its first night in "
        "Molten Core. `supplies` is what the night needs against what the guild "
        "holds, and how each can be closed (make: a guild crafter knows the "
        "recipe; buy: only the auction house has it). `fire_resistance` is what "
        "each tank and healer wears against the target for Ragnaros. Choose the "
        "one thing the guild should make or buy next: what most raises the "
        "chance the raid succeeds, given what can actually be made and the "
        "auction budget."
    )
    return state, {"next": jev.choice(instructions, criteria)}


@dataclass(frozen=True)
class SupplyJudgment(jev_choices.DungeonJudgment):
    """One raid_supply choice, shaped for overseer_jev_judgment."""

    kind: str = KIND

    @property
    def signature(self) -> tuple:
        """What has to change for a new record to be worth writing."""
        return (
            self.heuristic,
            self.jev,
            self.jev and round(self.confidence or 0, 2),
            self.acted,
        )

    def line(self) -> str:
        answer = (
            "jev=%s conf=%.2f" % (self.jev, self.confidence or 0.0)
            if self.jev
            else "jev=-"
        )
        return (
            "raid supply: guild=%s focus=%s; kind=%s heuristic=%s %s status=%s "
            "latency_ms=%d mode=%s acted=%s facts=%r"
            % (
                self.subject,
                self.chosen,
                self.kind,
                self.heuristic,
                answer,
                self.status,
                self.latency_ms,
                self.mode,
                self.acted,
                self.facts,
            )
        )


async def ask(client, guild, lines, fire, opts, budget_left, rule):
    """The raid_supply judgment, or None when there is nothing to choose."""
    pick = heuristic_focus(opts)
    if rule.mode == jev.OFF or len(opts) < 2:
        return None
    facts = "; ".join("%s %d/%d" % (line.name, line.have, line.want) for line in lines)[
        :1000
    ]
    base = SupplyJudgment(
        subject=str(guild)[:12] or "?",
        heuristic=pick,
        heuristic_why="the first short supply in the night's order, the fire "
        "potion and fire gear first",
        mode=rule.mode,
        status="",
        facts=facts,
    )
    state, questions = question(guild, lines, fire, opts, budget_left)
    outcome = await client.ask(KIND, state, questions)
    if outcome.answers is None:
        return replace(base, status=outcome.status, latency_ms=outcome.latency_ms)
    answer = outcome.answers["next"]
    offered = {o for o, _ in opts}
    return replace(
        base,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
        model=outcome.model,
        jev=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        acted=rule.acted(
            pick, answer.choice, answer.confidence, can_act=answer.choice in offered
        ),
    )


def focus_of(judgment, opts) -> str:
    """The option the plan works first: Jev's where it acted, else the heuristic's."""
    pick = heuristic_focus(opts)
    if judgment is None or judgment.acted != jev.JEV:
        return pick
    return judgment.jev


def _focused(items, focus, key):
    """`items` with the focused one moved to the front, the rest in order."""
    first = [i for i in items if key(i) == focus]
    return first + [i for i in items if key(i) != focus]


# ---------------------------------------------------------------------------
# THE STEPS. A crafter's step is the first of: post a finished item to the
# raider who needs it most, collect letters, learn a carried recipe, buy a
# vendor recipe, craft, buy the vendor's reagent, or ask the guild by post for
# the gathered ones. Built from guildcorps' own Step and Row, so the bridge
# runs them with the corps' runner, walks and cooldowns.

CRAFT_BATCH = 10
STEPS_PER_GUILD = 4
LETTERS_PER_GUILD = 2
COOLDOWN_MINUTES = {
    "craft": 5,
    "learn": 30,
    "buy": 120,
    "collect": 30,
    "post": 30,
    "supply": 120,
    "equip": 60,
}


def source_for(action, key) -> str:
    return "%s:%s:%d" % (SOURCE, action, int(key))


def _walk(action, key, cap) -> guildcorps.Row:
    return guildcorps.Row(
        "mail",
        guildroute.mailbox_walk_command(cap),
        "",
        source_for(action + "-walk", key),
    )


def _stack(member, entry):
    held = [h for h in member.carried if int(h.entry) == int(entry)]
    return max(held, key=lambda h: (int(h.count), -int(h.guid))) if held else None


def _can_make(member, make) -> int:
    if make.spell not in member.known:
        return 0
    counts = [member.count(e) // int(n) for e, n in make.reagents]
    counts += [member.count(e) // int(n) for e, n, _ in make.vendor]
    return min(counts) if counts else 0


def _gathered_casts(member, make) -> int:
    counts = [member.count(e) // int(n) for e, n in make.reagents]
    return min(counts) if counts else 0


def post_step(crafter, entry, name, recipients, cap):
    """Post the crafter's stack of `entry` to the first raider still short.

    `recipients` are (name, gap) in order. There is no split verb, so the whole
    stack goes; the craft batch is sized to the gaps, which keeps it close.
    """
    stack = _stack(crafter, entry)
    if stack is None:
        return None
    taker = next((n for n, _ in recipients if n != crafter.name), None)
    if taker is None:
        return None
    return guildcorps.Step(
        crafter.name,
        "post",
        entry,
        "raid supply: %s posts %d %s to %s, who is short for Molten Core"
        % (crafter.name, int(stack.count), name, taker),
        rows=(
            guildcorps.Row(
                "mail",
                "send item:%d subject:%s" % (int(stack.guid), name[:40]),
                taker,
                source_for("post", entry),
            ),
        ),
        walk=_walk("post", entry, cap),
    )


def collect_step(member, entries, cap):
    ready = [x for x in member.mail if x.ready and int(x.entry) in entries]
    if not ready:
        return None
    return guildcorps.Step(
        member.name,
        "collect",
        int(ready[0].entry),
        "raid supply: %s walks to a mailbox to collect %d letter(s) for the raid"
        % (member.name, min(len(ready), 6)),
        rows=tuple(
            guildcorps.Row(
                "mail",
                "take-item mail:%d item:%d" % (int(x.mail_id), int(x.guid)),
                "",
                source_for("collect", x.entry),
            )
            for x in ready[:6]
        ),
        walk=_walk("collect", ready[0].entry, cap),
    )


def _buy_step(member, entry, count, price, what, cap):
    ceiling = (
        int(price)
        * int(count)
        * guildcorps.BUY_CEILING_NUM
        // guildcorps.BUY_CEILING_DEN
    )
    return guildcorps.Step(
        member.name,
        "buy",
        entry,
        "raid supply: %s walks to a vendor to buy %d %s" % (member.name, count, what),
        rows=(
            guildcorps.Row(
                "buy",
                "entry:%d count:%d max:%d" % (entry, count, ceiling),
                "",
                source_for("buy", entry),
            ),
        ),
        walk=guildcorps.Row(
            "buy",
            "walk-to-vendor item:%d%s" % (entry, guildroute.errand_cap_word(cap)),
            "",
            source_for("buy-walk", entry),
        ),
    )


def craft_step(crafter, make, name, want, vendors, cap):
    """The crafter's own step toward `want` more of this make, or None."""
    if make.spell not in crafter.known:
        held = _stack(crafter, make.recipe_item) if make.recipe_item else None
        if held is not None:
            return guildcorps.Step(
                crafter.name,
                "learn",
                make.recipe_item,
                "raid supply: %s learns %s from the recipe it carries"
                % (crafter.name, name),
                rows=(
                    guildcorps.Row(
                        "cast",
                        "use guid:%d" % int(held.guid),
                        "",
                        source_for("learn", make.recipe_item),
                    ),
                ),
            )
        if make.recipe_price and make.recipe_item in vendors:
            return _buy_step(
                crafter,
                make.recipe_item,
                1,
                make.recipe_price,
                "the %s recipe" % name,
                cap,
            )
        return None
    n = min(_can_make(crafter, make), CRAFT_BATCH, max(1, int(want)))
    if n > 0:
        return guildcorps.Step(
            crafter.name,
            "craft",
            make.spell,
            "raid supply: %s crafts %d %s for Molten Core" % (crafter.name, n, name),
            rows=(
                guildcorps.Row(
                    "cast", str(make.spell), "", source_for("craft", make.spell)
                ),
            ),
            repeat=n,
        )
    casts = min(_gathered_casts(crafter, make), CRAFT_BATCH, max(1, int(want)))
    for entry, per, price in make.vendor:
        if casts > 0 and crafter.count(entry) < casts * per and entry in vendors:
            count = casts * per - crafter.count(entry)
            return _buy_step(
                crafter,
                entry,
                count,
                price,
                "vials" if entry == CRYSTAL_VIAL[0] else "thread",
                cap,
            )
    return None


def letters_for(crafter, make, want, members, busy, room, recent, cap) -> list:
    """Letters from guildmates carrying the gathered reagents the crafter lacks."""
    casts = min(CRAFT_BATCH, max(1, int(want)))
    steps = []
    for entry, per in make.reagents:
        lacking = casts * int(per) - crafter.count(entry) - crafter.incoming(entry)
        if lacking <= 0:
            continue
        asked = (recent or {}).get(("to:" + crafter.name, "supply", int(entry)))
        if asked is not None and asked < COOLDOWN_MINUTES["supply"]:
            continue
        senders = sorted(
            (
                m
                for m in members
                if m.name != crafter.name
                and not m.family
                and m.online
                and m.name not in busy
                and not classic.is_expansion_map(m.map_id)
                and m.count(entry) > 0
            ),
            key=lambda m: (-m.count(entry), m.name),
        )
        for sender in senders:
            if lacking <= 0 or len(steps) >= room:
                break
            stack = _stack(sender, entry)
            steps.append(
                guildcorps.Step(
                    sender.name,
                    "supply",
                    entry,
                    "raid supply: %s posts %d of item %d to %s for the raid's potions"
                    % (sender.name, int(stack.count), entry, crafter.name),
                    rows=(
                        guildcorps.Row(
                            "mail",
                            "send item:%d subject:For the raid" % int(stack.guid),
                            crafter.name,
                            source_for("supply", entry),
                        ),
                    ),
                    walk=_walk("supply", entry, cap),
                )
            )
            busy.add(sender.name)
            lacking -= int(stack.count)
    return steps


def equip_step(raider_member, raider, gear):
    """A raider off the family puts on a fire resistance piece it carries."""
    stack = _stack(raider_member, gear.entry)
    if stack is None or raider.family or raider.class_id not in gear.wearers:
        return None
    if raider.slot_fire(gear.slot) >= gear.fire or raider.fire >= fire_target(raider):
        return None
    return guildcorps.Step(
        raider.name,
        "equip",
        gear.entry,
        "raid supply: %s puts on %s for %d fire resistance"
        % (raider.name, gear.name, gear.fire),
        rows=(
            guildcorps.Row(
                "bot", "e Hitem:%d:0" % gear.entry, "", source_for("equip", gear.entry)
            ),
        ),
    )


def _cooling(step, recent) -> bool:
    minutes = COOLDOWN_MINUTES.get(step.action, 30)
    age = (recent or {}).get((step.holder, step.action, int(step.key)))
    return age is not None and age < minutes


@dataclass(frozen=True)
class GuildFacts:
    """One guild's facts for the supply plan, as the bridge read them."""

    guild: str
    members: tuple  # guildcorps.Member, every member of the guild
    raiders: tuple  # Raider
    posts: tuple  # guildcorps.Post
    vendors_by_map: dict


def guild_facts(guild, members, worn_rows, posts, vendors_by_map) -> GuildFacts:
    """One guild's GuildFacts from every family guild's corps Members.

    The raiders are the lineup the Raid tab shows, chosen by
    raidlineup.build_lineup over the same members with the family guaranteed.
    """
    crew = [m for m in members or () if m.guild == guild]
    names = {m.name for m in crew}
    family = {m.name for m in crew if m.family}
    lineup = raidlineup.build_lineup(
        [{"name": m.name, "level": m.level, "class_id": m.class_id} for m in crew],
        guaranteed=family,
    )
    raiders = raiders_from_lineup(
        lineup,
        {m.name: m.class_id for m in crew},
        [r for r in worn_rows or () if r.get("name") in names],
        family,
    )
    return GuildFacts(
        guild, tuple(crew), tuple(raiders), tuple(posts), vendors_by_map or {}
    )


@dataclass(frozen=True)
class SupplyPlan:
    guild: str
    lines: tuple
    fire: tuple
    steps: tuple = ()
    notes: tuple = ()


def with_letters(members, letter_rows) -> list:
    """The members with the raid's letters added to what the corps read.

    The corps reads letters for its crew only; a raider's letters (the potions
    the corps posted it) come from `letter_rows`, which carry the receiver's
    `name`. A letter the member already has is not added twice.
    """
    extra = {}
    for row in letter_rows or ():
        letter = guildcorps.Letter(
            int(row.get("mail_id") or 0),
            int(row.get("item_guid") or 0),
            int(row.get("entry") or 0),
            int(row.get("count") or 1),
            bool(int(row.get("ready") or 0)),
        )
        extra.setdefault(str(row.get("name") or ""), []).append(letter)
    out = []
    for m in members or ():
        seen = {(x.mail_id, x.guid) for x in m.mail}
        more = tuple(
            x for x in extra.get(m.name, ()) if (x.mail_id, x.guid) not in seen
        )
        out.append(replace(m, mail=tuple(m.mail) + more) if more else m)
    return out


def hold_back(money_rows, ledger_rows) -> list:
    """guildbank.plan_deposits rows with each master's unspent raid gold held back.

    A master that withdrew gold for the raid and has not spent it yet would
    otherwise deposit it straight back at the next vault visit.
    """
    out = []
    for row in money_rows or ():
        name = str(row.get("name") or "")
        kept = reserve(*ledger(ledger_rows, name))
        if kept:
            row = dict(row, money=max(0, int(row.get("money") or 0) - kept))
        out.append(row)
    return out


def have_from(members) -> dict:
    """entry -> what the guild carries of it, and what is in its letters."""
    out = {}
    for m in members:
        for h in m.carried:
            out[int(h.entry)] = out.get(int(h.entry), 0) + int(h.count)
        for x in m.mail:
            out[int(x.entry)] = out.get(int(x.entry), 0) + int(x.count)
    return out


def _knowers(members, posts) -> dict:
    """craft spell -> names of the corps' crafters who know it."""
    posted = {p.name: p.role for p in posts}
    out = {}
    for m in members:
        role = posted.get(m.name)
        for make in _makes():
            if role == ROLE_OF_SKILL.get(make.skill) and make.spell in m.known:
                out.setdefault(make.spell, []).append(m.name)
    return out


def _makes():
    return [s.make for s in SUPPLIES if s.make] + [g.make for g in FIRE_GEAR]


def _recipients(entry, raiders, members_by_name) -> list:
    """(name, gap) for raiders still short of `entry`: the main tank, then
    tanks, healers and the rest, the biggest gap first inside each."""
    wants = night_wants(raiders).get(entry) or {}
    order = {TANK: 0, HEALER: 1, PHYSICAL: 2, CASTER: 3}
    short = []
    for r in raiders:
        m = members_by_name.get(r.name)
        held = (m.count(entry) + m.incoming(entry)) if m else 0
        gap = int(wants.get(r.name, 0)) - held
        if gap > 0:
            short.append((not r.main_tank, order.get(r.role, 4), -gap, r.name))
    return [(name, -neg) for _, _, neg, name in sorted(short)]


def _gear_recipients(gear, raiders, members_by_name) -> list:
    """(name, 1) for raiders under their fire target who can wear `gear`, would
    gain from it, and have none on the way."""
    out = []
    for f in fire_lines(raiders):
        r = f.raider
        m = members_by_name.get(r.name)
        on_way = (m.count(gear.entry) + m.incoming(gear.entry)) if m else 0
        if (
            f.short
            and r.class_id in gear.wearers
            and r.slot_fire(gear.slot) < gear.fire
            and not on_way
        ):
            out.append((r.name, 1))
    return out


def _crafters(role, members, posts, busy):
    names = [p.name for p in posts if p.role == role]
    by = {m.name: m for m in members}
    return [
        by[n]
        for n in names
        if n in by
        and by[n].online
        and n not in busy
        and not classic.is_expansion_map(by[n].map_id)
    ]


def _work_item(make, name, entry, recipients, facts, busy, recent, cap, room):
    """Steps for one supply or gear piece: a crafter's own step, else letters."""
    role = ROLE_OF_SKILL.get(make.skill)
    want = sum(gap for _, gap in recipients) or 1
    crafters = _crafters(role, facts.members, facts.posts, busy)
    # A crafter who knows the craft first, then one carrying the recipe.
    crafters.sort(
        key=lambda m: (
            make.spell not in m.known,
            _stack(m, make.recipe_item) is None,
            m.name,
        )
    )
    steps, notes = [], []
    for crafter in crafters:
        vendors = frozenset((facts.vendors_by_map or {}).get(crafter.map_id, ()))
        step = post_step(crafter, entry, name, recipients, cap)
        step = step or collect_step(crafter, SUPPLY_ENTRIES, cap)
        step = step or craft_step(crafter, make, name, want, vendors, cap)
        if step is not None and not _cooling(step, recent):
            busy.add(crafter.name)
            return [step], notes
        if step is not None:
            notes.append(
                "%s's %s for %s waits out its cooldown"
                % (crafter.name, step.action, name)
            )
            continue
        if make.spell in crafter.known and room > 0:
            letters = [
                s
                for s in letters_for(
                    crafter, make, want, facts.members, busy, room, recent, cap
                )
                if not _cooling(s, recent)
            ]
            if letters:
                return letters, notes
        notes.append(_why_not(crafter, make, name, facts.members))
    if not crafters:
        notes.append("no %s is free to make %s" % (role, name))
    return steps, notes


# The reagents by name, for the sentence that says which one the guild lacks.
REAGENT_NAMES = {
    ELEMENTAL_FIRE: "Elemental Fire",
    DREAMFOIL: "Dreamfoil",
    GOLDEN_SANSAM: "Golden Sansam",
    MOUNTAIN_SILVERSAGE: "Mountain Silversage",
    PLAGUEBLOOM: "Plaguebloom",
    ICECAP: "Icecap",
    BLACK_LOTUS: "Black Lotus",
    GROMSBLOOD: "Gromsblood",
    STONESCALE_OIL: "Stonescale Oil",
    SANDWORM_MEAT: "Sandworm Meat",
    BOLT_OF_RUNECLOTH: "Bolt of Runecloth",
    DREAM_DUST: "Dream Dust",
}


def _why_not(crafter, make, name, members) -> str:
    """Why a crafter took no step toward `name`: the recipe, or which reagent."""
    if make.spell not in crafter.known:
        return "%s does not know %s and carries no recipe for it" % (crafter.name, name)
    missing = [
        REAGENT_NAMES.get(e, "item %d" % e)
        for e, n in make.reagents
        if sum(m.count(e) + m.incoming(e) for m in members) < int(n)
    ]
    if missing:
        return "%s knows %s, but nobody in the guild holds %s" % (
            crafter.name,
            name,
            " or ".join(missing),
        )
    return (
        "%s knows %s; the reagents are with members who cannot post them this pass"
        % (
            crafter.name,
            name,
        )
    )


def handout_steps(lines, facts, by_name, busy, recent, cap, room) -> list:
    """Stacks a guild member off the raid and off the family already carries,
    posted to the raider who needs them most: stock is routed before more is
    made. One step per supply, at most `room`."""
    raiding = {r.name for r in facts.raiders}
    wanted = [(line.entry, line.name) for line in lines if line.short]
    wanted += [(g.entry, g.name) for g in FIRE_GEAR]
    steps = []
    for entry, name in wanted:
        if len(steps) >= room:
            break
        gear = FIRE_GEAR_BY_ENTRY.get(entry)
        recipients = (
            _gear_recipients(gear, facts.raiders, by_name)
            if gear
            else _recipients(entry, facts.raiders, by_name)
        )
        if not recipients:
            continue
        holders = sorted(
            (
                m
                for m in facts.members
                if m.name not in raiding
                and not m.family
                and m.online
                and m.name not in busy
                and not classic.is_expansion_map(m.map_id)
                and m.count(entry) > 0
            ),
            key=lambda m: (-m.count(entry), m.name),
        )
        for holder in holders:
            step = post_step(holder, entry, name, recipients, cap)
            if step is not None and not _cooling(step, recent):
                steps.append(step)
                busy.add(holder.name)
                break
    return steps


SUPPLY_ENTRIES = frozenset(
    {s.entry for s in SUPPLIES}
    | {g.entry for g in FIRE_GEAR}
    | {
        e
        for m in [s.make for s in SUPPLIES if s.make] + [g.make for g in FIRE_GEAR]
        for e, _ in m.reagents
    }
    | {
        e
        for m in [s.make for s in SUPPLIES if s.make] + [g.make for g in FIRE_GEAR]
        for e, _, _ in m.vendor
    }
    | {s.make.recipe_item for s in SUPPLIES if s.make and s.make.recipe_item}
)
SUPPLY_SPELLS = frozenset(
    m.spell for m in [s.make for s in SUPPLIES if s.make] + [g.make for g in FIRE_GEAR]
)


def plan_guild(
    facts, recent, busy, focus="", cap=guildroute.MAIL_RUN_YARDS
) -> SupplyPlan:
    """One guild's supply plan this pass: lines for the page, steps to run.

    `busy` is shared with the corps' own plan and is added to, so no member
    takes two steps. `focus` is the option Jev (or the heuristic) put first.
    """
    by_name = {m.name: m for m in facts.members}
    have = have_from(facts.members)
    knowers = _knowers(facts.members, facts.posts)
    carriers = {}
    for m in facts.members:
        for h in m.carried:
            carriers.setdefault(int(h.entry), []).append(m.name)
    vendor_recipes = (
        frozenset().union(*(facts.vendors_by_map or {}).values())
        if facts.vendors_by_map
        else frozenset()
    )
    lines = supply_lines(facts.raiders, have, knowers, carriers, vendor_recipes)
    fire = fire_lines(facts.raiders)
    steps, notes = [], []

    # Raiders first: a raider carrying fire gear it should wear puts it on, and
    # one with letters from the corps collects them. Neither needs a crafter.
    for raider in facts.raiders:
        member = by_name.get(raider.name)
        if member is None or raider.family or not member.online or raider.name in busy:
            continue
        if classic.is_expansion_map(member.map_id):
            continue
        step = None
        for gear in FIRE_GEAR:
            step = step or equip_step(member, raider, gear)
        step = step or collect_step(member, SUPPLY_ENTRIES, cap)
        if step is not None and not _cooling(step, recent):
            steps.append(step)
            busy.add(raider.name)
        if len(steps) >= STEPS_PER_GUILD // 2:
            break

    steps.extend(
        handout_steps(
            lines, facts, by_name, busy, recent, cap, STEPS_PER_GUILD - len(steps)
        )
    )

    work = []
    for line in lines:
        supply = SUPPLY_BY_ENTRY[line.entry]
        if line.short and supply.make is not None and line.route != BUY:
            work.append((option_for(line), supply.make, supply.name, supply.entry))
        if line.entry == GREATER_FIRE_PROTECTION:
            for gear in FIRE_GEAR:
                work.append((option_for(gear), gear.make, gear.name, gear.entry))
    work = _focused(work, focus, key=lambda w: w[0])
    letters = 0
    for _option, make, name, entry in work:
        if len(steps) >= STEPS_PER_GUILD:
            break
        gear = FIRE_GEAR_BY_ENTRY.get(entry)
        recipients = (
            _gear_recipients(gear, facts.raiders, by_name)
            if gear
            else _recipients(entry, facts.raiders, by_name)
        )
        if not recipients:
            continue
        taken, said = _work_item(
            make,
            name,
            entry,
            recipients,
            facts,
            busy,
            recent,
            cap,
            LETTERS_PER_GUILD - letters,
        )
        steps.extend(taken)
        letters += sum(1 for s in taken if s.action == "supply")
        notes.extend(said)
    return SupplyPlan(
        facts.guild, tuple(lines), tuple(fire), tuple(steps), tuple(notes)
    )


# ---------------------------------------------------------------------------
# THE AUCTION HOUSE AND THE GUILD BANK'S GOLD.
#
# THE BUDGET is a share of the guild bank's gold per day, capped. Only the
# guild master withdraws (the name comes from `guild.leaderguid`, never from a
# rank the bridge guesses), only through `guild bank withdraw <copper>` at a
# vault, and only what the wanted listings on its own house cost. What it
# withdrew and has not yet spent is held back from the guild bank pass's
# deposits (`reserve`), so the gold is not put straight back.
#
# THE LEDGER IS THE COMMAND LOG, so a restart forgets nothing: a withdrawal is
# an applied `bank withdraw` row under `raidsupply:withdraw`, and a purchase is
# an auction row whose source carries the copper it committed,
# `raidsupply:ah:<entry>:<copper>`.

BUDGET_PERCENT = 10
BUDGET_CAP_COPPER = 100 * 10000
MIN_WITHDRAW_COPPER = 10000
WITHDRAW_SOURCE = SOURCE + ":withdraw"
AH_SOURCE = SOURCE + ":ah"


def daily_budget(bank_copper) -> int:
    return max(0, min(int(bank_copper or 0) * BUDGET_PERCENT // 100, BUDGET_CAP_COPPER))


def ah_source(entry, copper) -> str:
    return "%s:%d:%d" % (AH_SOURCE, int(entry), int(copper))


def ledger(rows, master) -> tuple:
    """(withdrawn, spent) copper for this master over the rows given.

    `rows` carry target_name, command, source and status; the caller bounds
    them to the last day. A withdrawal counts once applied; a purchase counts
    as soon as it is queued, and stops counting only when it failed.
    """
    withdrawn = spent = 0
    for row in rows or ():
        if str(row.get("target_name") or "") != master:
            continue
        source = str(row.get("source") or "")
        status = str(row.get("status") or "")
        if source == WITHDRAW_SOURCE and status not in ("error", "unchanged"):
            words = str(row.get("command") or "").split()
            if (
                len(words) == 3
                and words[:2] == ["bank", "withdraw"]
                and words[2].isdigit()
            ):
                withdrawn += int(words[2])
        elif source.startswith(AH_SOURCE + ":") and status not in (
            "error",
            "unchanged",
        ):
            tail = source.rsplit(":", 1)[-1]
            spent += int(tail) if tail.isdigit() else 0
    return withdrawn, spent


def reserve(withdrawn, spent) -> int:
    """What the master withdrew for the raid and has not spent yet."""
    return max(0, int(withdrawn) - int(spent))


def market_needs(plan, master, focus="") -> list:
    """auction.Need rows for the master, in the plan's order, focus first.

    A supply only the auction house has; a recipe item nobody carries and no
    vendor sells, for a supply nobody knows; nothing the corps can make.
    """
    needs = []
    for line in _focused(list(plan.lines), focus, key=option_for):
        supply = SUPPLY_BY_ENTRY.get(line.entry)
        if not line.short or supply is None:
            continue
        if line.route == BUY:
            needs.append(auction.Need(master, line.entry, line.name, line.short))
            if supply.make is not None and supply.make.recipe_item:
                needs.append(
                    auction.Need(
                        master, supply.make.recipe_item, "recipe for " + line.name, 1
                    )
                )
    return needs


def market_cost(needs, listings, house) -> int:
    """What buying every need would cost at the cheapest listings, in copper."""
    total = 0
    for need in needs:
        left = int(need.short)
        for listing in auction.usable(listings, need.entry, house):
            if left <= 0:
                break
            total += int(listing.buyout)
            left -= int(listing.count)
    return total


def withdrawal(bank_copper, withdrawn, spent, cost) -> tuple:
    """(copper to withdraw now, why) for the guild master; 0 when nothing."""
    allowance = daily_budget(bank_copper) - int(withdrawn)
    need = int(cost) - reserve(withdrawn, spent)
    amount = min(allowance, need, int(bank_copper or 0))
    if cost <= 0:
        return 0, "nothing the raid needs is listed on the master's auction house"
    if allowance <= 0:
        return (
            0,
            "today's raid budget of %d copper is already withdrawn"
            % daily_budget(bank_copper),
        )
    if need <= 0:
        return 0, "the master still carries %d copper withdrawn for the raid" % reserve(
            withdrawn, spent
        )
    if amount < MIN_WITHDRAW_COPPER:
        return 0, "a withdrawal of %d copper is below the %d floor" % (
            max(0, amount),
            MIN_WITHDRAW_COPPER,
        )
    return amount, "the listings cost %d copper; %d of today's %d budget is left" % (
        int(cost),
        allowance,
        daily_budget(bank_copper),
    )


def plan_market(
    needs, listings, house, master, purse, withdrawn, spent, free_slots
) -> tuple:
    """(buys, notes): what the master buys where it stands, within the budget.

    The purse is what it withdrew for the raid and has not spent, and never
    more than it carries. Needs are bought in order, so the focus goes first.
    """
    left = min(int(purse or 0), reserve(withdrawn, spent))
    buys, notes = [], []
    if left <= 0:
        return [], ["the master has no unspent raid budget to buy with"]
    slots = int(free_slots or 0)
    for need in needs:
        if left <= 0:
            break
        got, said = auction.plan_buys(
            [need], listings, house, {master: left}, {master: slots}, cap=left
        )
        for buy in got:
            left -= int(buy.spend)
            slots -= 1
        buys.extend(got)
        notes.extend(said)
    return buys, notes


# ---------------------------------------------------------------------------
# THE RAID TAB'S CARD.

SUPPLY_COLUMNS = ("supply", "wanted", "held", "short", "how it closes")
FIRE_COLUMNS = ("raider", "role", "target", "worn", "short")


def card(raiders, have, knowers, carriers=None, bank_copper=None) -> dict:
    """The supply section of one guild's readiness card; the page decides nothing.

    `have` counts bags, bank and guild bank, which is what the guild holds;
    the corps pass counts bags and letters, which is what it can move.
    """
    lines = supply_lines(raiders, have, knowers, carriers)
    fire = fire_lines(raiders)
    short = [line for line in lines if line.short]
    fire_short = [f for f in fire if f.short]
    head = (
        "A night of Molten Core for %d raiders wants %d kinds of consumable; "
        "%d are short. %d of %d tanks and healers are under their fire "
        "resistance target."
        % (len(raiders), len(lines), len(short), len(fire_short), len(fire))
    )
    budget = (
        "The guild bank holds %d gold; the auction house may spend %d gold a "
        "day of it, withdrawn only by the guild master."
        % (int(bank_copper) // 10000, daily_budget(bank_copper) // 10000)
        if bank_copper is not None
        else "The guild bank's gold was not read, so no auction budget is stated."
    )
    return {
        "line": head,
        "budget_line": budget,
        "supply_columns": list(SUPPLY_COLUMNS),
        "supplies": [
            {
                "entry": line.entry,
                "short": line.short,
                "route": line.route,
                "cells": [
                    line.name,
                    str(line.want),
                    str(line.have),
                    str(line.short),
                    line.said,
                ],
            }
            for line in lines
        ],
        "fire_columns": list(FIRE_COLUMNS),
        "fire": [
            {
                "short": f.short,
                "cells": [
                    f.raider.name,
                    "main tank" if f.raider.main_tank else f.raider.role,
                    str(f.target),
                    str(f.raider.fire),
                    str(f.short),
                ],
            }
            for f in fire
        ],
        "fire_line": (
            "Targets: the Ragnaros tank %d, other tanks %d, healers %d, from "
            "worn gear only. The guild makes %s; the rest comes from: %s."
            % (
                FIRE_TARGET[MAIN_TANK],
                FIRE_TARGET[TANK],
                FIRE_TARGET[HEALER],
                ", ".join(
                    "%s (%d, for cloth wearers)" % (g.name, g.fire) for g in FIRE_GEAR
                ),
                "; ".join(FIRE_ROADS),
            )
        ),
        "basis": (
            "Per-raider counts and resistance targets are conventions, not the "
            "instance's rules: the Ragnaros tank carries 4 fire potions, 5 "
            "healing potions and the tank flask; healers 5 mana potions and "
            "their flask; physical damage 2 fire potions, the Mongoose elixir, "
            "dumplings and Juju; casters 3 mana potions and Supreme Power. "
            "Reagents were read from the worldserver's Spell.dbc and recipe "
            "sources from the realm's own tables."
        ),
    }


def knowers_from_rows(spell_rows) -> dict:
    """craft spell -> names who know it, from {name, spell} rows."""
    out = {}
    for row in spell_rows or ():
        spell = int(row.get("spell") or 0)
        if spell in SUPPLY_SPELLS:
            out.setdefault(spell, []).append(str(row.get("name") or ""))
    return out


def have_from_holdings(holding_rows, guild_bank_rows=()) -> dict:
    """entry -> count across bags, bank and the guild bank, from item rows
    carrying `entry` and `count`."""
    out = {}
    for row in list(holding_rows or ()) + list(guild_bank_rows or ()):
        entry = int(row.get("entry") or 0)
        if entry in SUPPLY_ENTRIES:
            out[entry] = out.get(entry, 0) + int(row.get("count") or 0)
    return out


def summary(plan) -> str:
    """One log line for a guild's plan."""
    short = [
        "%s %d/%d" % (line.name, line.have, line.want)
        for line in plan.lines
        if line.short
    ]
    fire = [
        "%s %d/%d" % (f.raider.name, f.raider.fire, f.target)
        for f in plan.fire
        if f.short
    ][:4]
    return "raid supply: %s: short %s; fire resistance short %s; %d step(s)" % (
        plan.guild,
        ", ".join(short) or "nothing",
        ", ".join(fire) or "nobody",
        len(plan.steps),
    )
