"""Which vendor-bought reagent a craft errand needs, and whether to buy it.

WHY THIS EXISTS (infra#3613, the first slice of the reagent-buying gap every
craft-leveling PR tonight found and deferred rather than guessed at). Every
verified Alchemy recipe in craft.RECIPES needs a vial - Empty, Leaded or
Crystal - that nothing in the family gathers; it is vendor-bought or the
recipe simply cannot be cast, which is exactly what stalled Ugga live
tonight (20x Silverleaf, 13x Peacebloom, 0 Empty Vial). craft.py's own
docstring is explicit that it does not verify reagents at all - "a character
short of mats simply has its cast refused" - so this is a second, narrow
module rather than an addition to craft.py, the same separation towntrip.py
already draws between "what to buy" and "can we cast it".

WHY A NEW LOOP AND NOT A STEP INSIDE _towntrip_once, though the issue
suggested extending towntrip.py's existing shape directly. `_towntrip_once`
is gated on `_mid_run` and walks only the party LEADER to a repair/vendor
counter between dungeon runs - correct for durability and food/drink, which
are shared, leader-carried errands. A vial need is neither: it belongs to
whichever character's OWN craft_spell names it, is unrelated to whether a
dungeon run just ended, and every follower needs their own trip regardless
of who leads. Reusing `_towntrip_once` would mean teaching it to walk
followers too and to run outside the dungeon-cycle gate - changing what that
function means for its two existing callers - rather than adding a third,
narrower one alongside it. `bridge.py`'s `_craft_supply_once` is that third
one, and it is deliberately per-candidate rather than leader-only, the same
way `_vendor_once`'s per-holder sell pass already is.

WHY towntrip.Errand AND NOT A NEW SHAPE. mod-overseer's DoBuy (verified by
reading it directly, not assumed) is already fully generic: it parses
`entry:<id> count:<n> max:<price>` off ANY kind='buy' row and finds any
reachable vendor that stocks that entry - nothing about it is food/drink
specific. towntrip.py's own `_buy` already writes exactly this row shape for
FOOD/DRINK; reusing `towntrip.Errand` and the same command string means the
C++ side needs no change at all, and none was made.

REAGENT IDS AND PRICES ARE READ FROM THE LIVE WORLD DATABASE
(acore_world.item_template), not from a wiki or guide - the most
authoritative source available on this box - cross-checked against the
reagent names craft.RECIPES' own verified comments already cite for each
Alchemy spell id, so no new web verification was needed to trust the pairing:

    entry  name          BuyPrice
    3371   Empty Vial          20
    3372   Leaded Vial        200
    8925   Crystal Vial      2500

All three are confirmed sold with unlimited stock (npc_vendor.maxcount = 0)
by real vendors on this world (checked live, not assumed).

TAILORING/LEATHERWORKING THREAD AND DYE (infra#3609/#3611) - VERIFIED AND
ADDED THIS PASS, as `REAGENTS` (plural) below, a SECOND dict alongside
`REAGENT` rather than more entries in it. `REAGENT` assumes exactly one
purchasable reagent per spell, which held for every Alchemy vial and for
Weak Flux, but not here: three of the fifteen verified Leatherworking
recipes (Dark Leather Boots, Dark Leather Pants, Wicked Leather Gauntlets)
need TWO vendor reagents on the same cast (thread AND dye), which a
`spell_id -> single (entry, label, price)` mapping cannot express without
either dropping the second reagent or picking one arbitrarily - both wrong.
`REAGENTS` maps `spell_id` to a TUPLE of reagents instead, and
`craft_reagent_errands` (the plural sibling of `reagent_errand`) walks every
one of them, returning every errand and every refusal rather than just the
first - the same list-returning shape `towntrip._buy`'s own FOOD/DRINK
callers already use. `REAGENT`/`reagent_errand` are untouched: every recipe
that already used them still fits the single-reagent shape, and widening it
for a case it never needed would be a second migration for no behavior
change.

Every id and price below was read from acore_world.item_template directly
and cross-checked against npc_vendor for unlimited stock (maxcount = 0), the
same discipline as `REAGENT`'s own vials:

    entry  name                  BuyPrice  sold unlimited
    2320   Coarse Thread               10  yes (156 vendor rows)
    2321   Fine Thread                 100  yes (146 vendor rows)
    4291   Silken Thread                500  yes (134 vendor rows)
    8343   Heavy Silken Thread         2000  yes (127 vendor rows)
    14341  Rune Thread                 5000  yes (186 vendor rows)
    4340   Gray Dye                     350  yes (127 vendor rows)
    2325   Black Dye                   1000  yes (127 vendor rows)
    4289   Salt                          50  yes (121 vendor rows)

`item_template` carries a SECOND "Rune Thread" row (entry 24288, a
class=11/subclass=11 reagent, BuyPrice 60000) - checked and confirmed it has
ZERO npc_vendor rows on this world, so 14341 (class=7 Trade Goods) is the
only one `REAGENTS` may ever name; the wrong one would silently log "no
reachable vendor stocks it" forever, the same failure mode the module
docstring already warns about for Moss Agate below.

WHY A PER-RECIPE TARGET (`CASTS_PER_TRIP` x each entry's own per-cast
quantity), NOT ONE FLAT COUNT LIKE `TARGET`. infra#3609's own body names
this decision directly: "probably enough for one recipe run, matching the
batch sizes the guide already states." A vial is consumed exactly once per
cast, so `TARGET = 5` cheaply covers five casts of ANY vial recipe. Thread
and dye are not one-per-cast: Nightscape Pants consumes 4x Silken Thread per
cast while Handstitched Leather Cloak consumes 1x Coarse Thread, and Rune
Thread costs 5000 copper against Coarse Thread's 10 - a flat unit count
would either strand the four-per-cast recipes after little more than one
success, or spend a fortune buying the cheap ones up to the same number
needed by the priciest. Each `REAGENTS` entry therefore carries its own
per-cast quantity as a fourth tuple element, and the restock target is
`CASTS_PER_TRIP` casts' worth of it - small and affordable (the same
five-casts-of-headroom size `REAGENT`'s own `TARGET` already uses), scaled
to what the recipe actually consumes instead of assuming every reagent
behaves like a vial.

Every spell_id named in `REAGENTS` is verified present in `craft.RECIPES`
by `test_every_reagents_spell_is_a_real_crafting_recipe`, the same
reverse-lookup discipline `test_every_vial_recipe_is_a_real_crafting_recipe`
already holds `REAGENT` to.

ENGINEERING'S WEAK FLUX (infra#3616) - VERIFIED AND ADDED, MOSS AGATE -
VERIFIED AND DELIBERATELY LEFT OUT. infra#3616 assumed both Weak Flux
(Bronze Tube, spell 3938) and Moss Agate (Standard Scope, spell 3978) were
"vendor-only purchases", the same shape as Alchemy's vials. Checking that
assumption against the live database (not trusting the issue's prose, the
same discipline this module's own docstring already demands of item ids)
found it true for only one of the two:

    entry  name         BuyPrice  npc_vendor rows
    2880   Weak Flux         100  200+ general-goods vendors, maxcount=0
    1206   Moss Agate       1600  ZERO - no npc_vendor row anywhere

Moss Agate is `item_template.class=3` (Gem), not a general good, and its
only sources on this world are drop tables - `gameobject_loot_template`
(5% off Tin Vein/Silver Vein, the same ore nodes mining already gathers
from as a side effect) and a long tail of `creature_loot_template` rows.
It is a GATHERED item, the same class as the mining-byproduct stones
Blacksmithing's recipes already consume, not a buyable one - `REAGENT`
must never carry an `entry` that `town.stocks` can never contain, since
`reagent_errand` would then log "no reachable vendor stocks it" on every
single poll forever rather than the character simply finding one while
questing/mining. Standard Scope (spell 3978) is therefore NOT added to
`craft.RECIPES` alongside Bronze Tube - adding a bracket this module can
never supply would repeat the exact mistake craft.py's own docstring
already rejected for the 151-174 Explosive Sheep gap (a recipe that can
never complete, shipped anyway). Bronze Tube's own single reagent (Weak
Flux) is fully vendor-solvable, so it is added on its own.

WHERE THE FAMILY MUST WALK WHEN NOTHING IN REACH SELLS IT (infra#3692), AND
THE TWO THINGS THAT WERE WRONG WITH THE ANSWER BEFORE `supply_trip` EXISTED.
Everything above answers "what should be bought once somebody is standing in
front of a vendor that stocks it". Nothing here answered "and if they are
not". `bridge._craft_supply_once` did answer it, twice, and both answers were
wrong - measured live in Gadgetzan on 2026-09-13, not reasoned about:

  1. IT AIMED AT THE ROLE KEYWORD `vendor`, which mod-overseer's
     `ResolveTravelTarget` resolves to the NEAREST vendor this character may
     deal with. That is a criterion with nothing to do with stocking the
     reagent, so the sentence in the log ("is not near a vendor stocking
     Empty Vial") was answered by a walk chosen on a different question
     entirely. Ugga reached creature 5411 (Krinkle Goodsteel, seven
     `npc_vendor` rows, no Empty Vial) and bought nothing. The one vendor
     within 120 yards that does stock Empty Vial (3371) is creature 5594,
     Alchemist Pestlezugg, 83 yards off at the time; the next nearest on the
     whole of map 1 is 2,071 yards away. "The nearest vendor" and "the
     nearest vendor that stocks it" are not near-misses of each other here.
  2. IT AIMED THE CANDIDATE, WHO CANNOT MOVE. The family carries exactly one
     `new rpg` and it is on the LEADER, deliberately - it acts at relevance
     3.0-11.0 against follow's 1.0, so a follower holding both wanders off
     every tick, which is infra#2812's 937-yard scatter.
     `professions.traveller` is the whole written argument for that. And
     mod-overseer says so out loud when it happens: "'Ugga' was sent to
     '5594' but does not carry `new rpg` - nothing walks it anywhere.
     Followers travel by following the leader; aim the leader instead."

WHY A CREATURE ENTRY AND NOT A BETTER KEYWORD. `ResolveTravelTarget` already
accepts a bare numeric creature entry, and applies its own faction gate,
guard sweep and route-safety check to it on the character's own map. That is
the same mechanism `flight master:<nodeId>` uses and for the same stated
reason (quadseven/mod-overseer#388: "the bare keyword means the nearest one,
and that is the wrong answer for a deliberate errand"). So no C++ change was
needed and none was made - and crucially NO COORDINATE IS EVER AUTHORED HERE.
Naming an entry and letting the module resolve the spawn is the whole point:
a hand-written z has no navmesh under it, which once lifted one character and
killed another in the void at full health.

NO VENDOR IS HARDCODED EITHER, which is what keeps this inside
`towntrip.town_from_rows`' own standing rule that "no vendor entry, name or
coordinate appears anywhere in this repository". The entry is READ LIVE from
`acore_world.npc_vendor` joined to `creature` on every pass, by `bridge`, and
handed to `supply_trip` as rows. This module still names no NPC and holds no
table of them.

ONE TRIP PER PASS AND THE REST WAIT - the same restraint `trainjob.plan`
already states for the same reason ("two aims is the 937-yard scatter of
infra#2812 with a fresh reason attached"). It is also, unexpectedly, what
makes the two-vendor recipes work with no special case at all. A REAGENTS
recipe needing thread AND dye from vendors that do not share a counter simply
resolves one of the two this pass; next pass that reagent is carried, is no
longer short, and the other one's vendor is the only trip left to take. So
the multi-reagent shape needed no second mechanism, only the willingness to
take more than one pass over it. `waiting` names whoever is queued, so a wait
reads as a wait rather than as a pass that did nothing.

THE SHOPPER DOES NOT HAVE TO BE THE TRAVELLER, and this is where the shape
differs from `trainjob`/`professions.traveller` on purpose. A trainer errand's
transaction is performed BY the aimed character (mod-overseer's
`TrainOnArrival`), so the learner has to be the one who walks, and leadership
has to move to it. A purchase is not: `DoBuy` runs for whoever
`overseer_command.target_name` names and looks for a vendor near THAT buyer,
exactly as `_vendor_once`'s per-holder sell rows already rely on. So the
leader walks, the family follows, and each shopper's own buy fires where they
are standing. Nothing here borrows leadership, and `_head_now` /
`_errand_traveller` are untouched.

WHAT THIS STILL CANNOT SEE, SAID PLAINLY. `creature_template.faction` is in
the world database but the REACTION that decides whether a given character
may deal with that faction is in `FactionTemplate.dbc`, which is not - so
this module deliberately does not pre-filter on faction and cannot.
`ResolveTravelTarget` is the authority, and it refuses and logs its own
refusal by name (quadseven/mod-overseer#234). What this module owes in
exchange is that the chosen entry, its faction and the alternatives it beat
are all NAMED in `report`, so a silent refusal on the C++ side is something a
person can look up in one query rather than a journey that simply never
happens.
"""

from __future__ import annotations

from dataclasses import dataclass

import towntrip
import travel

# spell_id -> (item entry, display name, BuyPrice in copper). Verified
# against acore_world.item_template directly; see module docstring. Built
# from craft.RECIPES' own reagent notes for the ten (of eleven) Alchemy
# recipes that name a vial - Lesser Healing Potion (2337) is the one
# exception, since its second reagent is the previous recipe's own output,
# not a fresh vial - plus Engineering's Bronze Tube (Weak Flux only; Moss
# Agate is deliberately absent, see module docstring).
#
# TWELVE OF THIRTEEN NOW, and the two that arrived are the raid-consumable
# brackets craft.RECIPES gained (see its RAID CONSUMABLES block). Neither
# needs a vial this table did not already buy: Elixir of Fortitude (3450)
# takes the same Leaded Vial as the Elixir of Greater Defense it sits above,
# and Elixir of Greater Agility (11467) the same Crystal Vial as the Superior
# Healing Potion it sits above. Verified the same way every line here was -
# the reagent read straight out of the running worldserver's own Spell.dbc
# (543b9fe61355b6a77a01714d52fea2e5), the price out of item_template.
REAGENT: dict[int, tuple[int, str, int]] = {
    2330: (3371, "Empty Vial", 20),  # Minor Healing Potion
    3173: (3371, "Empty Vial", 20),  # Lesser Mana Potion
    3447: (3372, "Leaded Vial", 200),  # Healing Potion
    3450: (3372, "Leaded Vial", 200),  # Elixir of Fortitude (raid consumable)
    7181: (3372, "Leaded Vial", 200),  # Greater Healing Potion
    11449: (3372, "Leaded Vial", 200),  # Elixir of Agility
    11450: (3372, "Leaded Vial", 200),  # Elixir of Greater Defense
    11457: (8925, "Crystal Vial", 2500),  # Superior Healing Potion
    11460: (8925, "Crystal Vial", 2500),  # Elixir of Detect Undead
    11467: (8925, "Crystal Vial", 2500),  # Elixir of Greater Agility (raid)
    17553: (8925, "Crystal Vial", 2500),  # Superior Mana Potion
    17556: (8925, "Crystal Vial", 2500),  # Major Healing Potion
    3938: (2880, "Weak Flux", 100),  # Bronze Tube (Engineering)
}

# Vials are cheap and cast-consumed one at a time, so a small standing stock
# restocked often beats hoarding a full stack (20) that eats a bag slot for
# weeks - the same "a stack is a slot" reasoning towntrip.STACK states for
# food and drink, just a smaller number because a vial costs a slot too.
TARGET = 5


def reagent_errand(
    name: str,
    craft_spell: int,
    held: int,
    money: int,
    free_slots: int,
    town: "towntrip.Town",
) -> tuple["towntrip.Errand | None", "str | None"]:
    """The buy errand this character's craft errand needs, or why not.

    `held` is how many of the needed vial this character already carries -
    read from the world's own item_instance, never assumed. Returns
    (errand, None) when a row should be written, or (None, note) when
    something stopped it - the same two-outcome shape towntrip._buy uses, so
    a caller can log the note exactly like every other town-trip refusal.
    """
    need = REAGENT.get(craft_spell)
    if not need:
        return None, None  # this recipe needs no vendor reagent this module knows

    entry, label, price = need
    short = TARGET - held
    if short <= 0:
        return None, None

    if entry not in town.stocks:
        return None, f"no reachable vendor stocks {label} ({entry}) for {name}"

    if free_slots < 1:
        return None, f"{name} has no free bag slot for {label}"

    ceiling = price * short
    if money < ceiling:
        return None, (
            f"{name} cannot afford {short} x {label} ({ceiling} copper against {money})"
        )

    return (
        towntrip.Errand(
            name,
            "buy",
            f"entry:{entry} count:{short} max:{ceiling}",
            f"carries {held} {label}, wants {TARGET} for craft_spell {craft_spell}",
            ceiling,
        ),
        None,
    )


# spell_id -> tuple of (item entry, display name, BuyPrice in copper,
# quantity consumed PER CAST). See the module docstring for why this is a
# second dict rather than more entries in REAGENT (some recipes need two
# vendor reagents on one cast, which REAGENT's single-tuple shape cannot
# hold) and why the quantity is per-recipe rather than REAGENT's flat
# TARGET. Every id/price verified live against acore_world.item_template
# and npc_vendor; see the module docstring for the full table.
REAGENTS: dict[int, tuple[tuple[int, str, int, int], ...]] = {
    8776: ((2320, "Coarse Thread", 10, 1),),  # Linen Belt (Tailoring)
    3755: ((2320, "Coarse Thread", 10, 3),),  # Linen Bag (craft.BAG_RECIPES)
    # 9058 IS BACK, because the reason it was absent was a misread rather than
    # a missing fact: an AcquireMethod 1 ability has no trainer_spell row by
    # definition, which is what "could not be verified" was actually seeing.
    # Verified against the worldserver's own SkillLineAbility.dbc/Spell.dbc -
    # see craft.RECIPES' comment beside the 46-55 Leatherworking bracket.
    9058: ((2320, "Coarse Thread", 10, 1),),  # Handstitched Leather Cloak
    3756: ((2320, "Coarse Thread", 10, 2),),  # Embossed Leather Gloves
    3763: ((2320, "Coarse Thread", 10, 2),),  # Fine Leather Belt
    2167: (
        (2321, "Fine Thread", 100, 2),  # Dark Leather Boots
        (4340, "Gray Dye", 350, 1),
    ),
    7135: (
        (2321, "Fine Thread", 100, 1),  # Dark Leather Pants
        (4340, "Gray Dye", 350, 1),
    ),
    3818: ((4289, "Salt", 50, 3),),  # Cured Heavy Hide
    3780: ((2321, "Fine Thread", 100, 1),),  # Heavy Armor Kit
    7151: ((2321, "Fine Thread", 100, 2),),  # Barbaric Shoulders
    7156: ((4291, "Silken Thread", 500, 1),),  # Guardian Gloves
    10487: ((4291, "Silken Thread", 500, 1),),  # Thick Armor Kit
    10507: ((4291, "Silken Thread", 500, 2),),  # Nightscape Headband
    10548: ((4291, "Silken Thread", 500, 4),),  # Nightscape Pants
    10558: ((8343, "Heavy Silken Thread", 2000, 2),),  # Nightscape Boots
    19049: (
        (2325, "Black Dye", 1000, 1),  # Wicked Leather Gauntlets
        (14341, "Rune Thread", 5000, 1),
    ),
    19082: ((14341, "Rune Thread", 5000, 1),),  # Runic Leather Headband
}

# How many casts' worth of a REAGENTS reagent to keep in stock - see the
# module docstring for why this scales per-recipe (via each entry's own
# quantity-per-cast) instead of being a flat unit count like REAGENT's
# TARGET.
CASTS_PER_TRIP = 5


def craft_reagent_errands(
    name: str,
    craft_spell: int,
    held: dict[int, int],
    money: int,
    free_slots: int,
    town: "towntrip.Town",
) -> tuple[list["towntrip.Errand"], list[str]]:
    """Every buy errand this character's craft errand needs, from REAGENTS.

    The plural sibling of `reagent_errand`: a recipe in REAGENTS may name one
    or two vendor reagents (a plain thread-only recipe, or a thread-and-dye
    one), so this returns every errand it can write and every refusal note
    it hit, rather than stopping at the first - the same shape
    `towntrip._buy`'s FOOD/DRINK callers already return in. `held` is
    `{item entry: count carried}` for every reagent this craft_spell names,
    read from the world's own item_instance the same as `reagent_errand`'s
    single `held` int.

    `money` IS CHECKED INDEPENDENTLY PER REAGENT, NOT DEDUCTED ACROSS THEM -
    the same simplification `towntrip._buy` already makes checking FOOD and
    DRINK separately for one character. A character who can afford either
    reagent alone but not both in the same pass may see two errands queued
    that together exceed their purse; DoBuy's own execution still refuses
    whichever one actually runs out of money, so this never spends more than
    the character has - it can just queue a trip that lands partially
    unfunded rather than a perfectly costed one.
    """
    errands: list["towntrip.Errand"] = []
    notes: list[str] = []
    for entry, label, price, qty_per_cast in REAGENTS.get(craft_spell, ()):
        target = CASTS_PER_TRIP * qty_per_cast
        carried = held.get(entry, 0)
        short = target - carried
        if short <= 0:
            continue

        if entry not in town.stocks:
            notes.append(f"no reachable vendor stocks {label} ({entry}) for {name}")
            continue

        if free_slots < 1:
            notes.append(f"{name} has no free bag slot for {label}")
            continue

        ceiling = price * short
        if money < ceiling:
            notes.append(
                f"{name} cannot afford {short} x {label} "
                f"({ceiling} copper against {money})"
            )
            continue

        errands.append(
            towntrip.Errand(
                name,
                "buy",
                f"entry:{entry} count:{short} max:{ceiling}",
                f"carries {carried} {label}, wants {target} for craft_spell {craft_spell}",
                ceiling,
            )
        )
    return errands, notes


# The vendor role keyword, READ FROM travel.ROLES rather than spelled here -
# the same reasoning trainjob.TRAINER_ROLE gives for its own: a second
# spelling of a keyword is a second thing to get wrong, and a rename in
# travel.py becomes an ImportError at startup instead of an errand that
# resolves to nothing six hours later. It is named at all because this is the
# aim the numeric one REPLACES, and bridge's write guard has to know which
# standing value a reagent aim is allowed to refine.
VENDOR_ROLE = next(role for role in travel.ROLES if role == "vendor")

# How many runners-up `report` names beside the vendor it chose. This is the
# whole of this side's answer to "the faction gate lives in the C++ and can
# refuse silently": three alternatives, with their entry ids, factions and
# distances, is enough for a person to run one npc_vendor query by hand and
# tell "it was refused for its faction" apart from "it was simply never
# reached". Three rather than all of them because map 1 has a long tail - the
# Empty Vial list runs to dozens - and a log line nobody reads to the end is
# not observability.
SHORTLIST = 3


@dataclass(frozen=True)
class VendorSpawn:
    """One creature ENTRY whose npc_vendor rows list a reagent, and how far
    off its nearest spawn stands.

    READ FROM THE WORLD, NEVER AUTHORED. `bridge._fetch_reagent_vendors`
    builds these from `acore_world.npc_vendor` joined to `creature` and
    `creature_template` on every pass; nothing in this repository holds a
    table of vendors, which is the rule `towntrip.town_from_rows` already
    states and this module is careful not to be the first to break.

    `yards` IS A 2D DISTANCE, deliberately: it is the same measurement
    `ResolveTravelTarget` itself ranks candidates by (`bot->GetDistance2d`),
    so this side's idea of "nearest" and the C++'s cannot come to different
    answers about which spawn was meant. `faction` is carried purely so
    `report` can name it - see the module docstring for why this side cannot
    turn it into a verdict.
    """

    entry: int
    name: str = ""
    faction: int = 0
    map_id: int = 0
    yards: float = 0.0


@dataclass(frozen=True)
class Need:
    """One character's outstanding reagent that nothing in reach will sell.

    Built by `reagent_need` / `craft_reagent_needs` for exactly the case
    `reagent_errand` and `craft_reagent_errands` answer with "no reachable
    vendor stocks it" - that note is a fact about where the character is
    STANDING, and this is the errand that changes where they stand.
    """

    shopper: str
    entry: int
    label: str = ""


@dataclass(frozen=True)
class SupplyTrip:
    """The one walk this pass should take, or why it is taking none.

    `target` is what to write into `overseer_roster.travel_npc`, and it is ''
    for a pass that should write nothing - the same "'' means nobody"
    convention `trainjob.TrainPlan.traveller` and `professions.traveller`
    both use. `why_not` is never empty when `target` is, for the reason
    TrainPlan's own docstring gives: a plan that declines to act and cannot
    say why is the silent idle this whole family of modules exists to end.

    `unreachable` IS SEPARATE FROM `why_not` AND OUTLIVES IT. A reagent that
    nothing on this map sells is not a reason the pass did nothing - the pass
    may well have taken a perfectly good trip for somebody else - it is a
    standing fact about a craft errand that can never be supplied where the
    family is, and it needs saying every time, at a level a person sees.
    That is precisely what "vendor aim taken=True" and then silence forever
    was hiding.
    """

    traveller: str = ""
    target: str = ""
    shopper: str = ""
    entry: int = 0
    label: str = ""
    vendor: VendorSpawn | None = None
    passed_over: tuple = ()
    also_served: tuple = ()
    waiting: tuple = ()
    unreachable: tuple = ()
    why_not: str = ""


def reagent_need(name: str, craft_spell: int, held: int, town: "towntrip.Town"):
    """The trip this character's craft errand needs, or None.

    THE SIBLING OF `reagent_errand`, AND THE OTHER HALF OF THE SAME QUESTION.
    That function answers "can this be bought where they are standing"; this
    one answers "and if not, is it worth going somewhere". Both refusals
    matter and they are not the same refusal: a character already carrying
    TARGET of the reagent needs no trip at all, and walking the whole family
    across a zone for one is a journey with nothing at the end of it. The
    bridge asked only `entry not in town.stocks` before this existed, which
    is exactly the half that cannot tell those apart.

    IT IS A SEPARATE FUNCTION AND NOT A THIRD RETURN VALUE FROM
    `reagent_errand`, because `reagent_errand` needs `money` and `free_slots`
    and this does not: whether to WALK somewhere has nothing to do with what
    is in the purse, and a character who cannot afford the vial today can
    perfectly well be at the counter tomorrow when they can.
    `test_a_need_and_an_errand_never_disagree` is what keeps the shortfall
    arithmetic here from drifting away from the copy over there.
    """
    need = REAGENT.get(craft_spell)
    if not need:
        return None
    entry, label, _price = need
    if TARGET - held <= 0:
        return None
    if entry in town.stocks:
        return None
    return Need(name, entry, label)


def craft_reagent_needs(
    name: str, craft_spell: int, held: dict, town: "towntrip.Town"
) -> list:
    """Every trip this character's REAGENTS recipe needs, one per reagent.

    The plural sibling of `reagent_need`, the same way
    `craft_reagent_errands` is `reagent_errand`'s. A recipe naming thread AND
    dye produces TWO needs when neither is in reach, and they are kept apart
    rather than merged because nothing says one vendor sells both - see the
    module docstring for how one trip per pass resolves them in turn.
    """
    out = []
    for entry, label, _price, qty_per_cast in REAGENTS.get(craft_spell, ()):
        if CASTS_PER_TRIP * qty_per_cast - held.get(entry, 0) <= 0:
            continue
        if entry in town.stocks:
            continue
        out.append(Need(name, entry, label))
    return out


def _usable(spawns, map_id: int) -> list:
    """One reagent's vendor spawns that the family could actually walk to,
    nearest first.

    THE SAME-MAP FILTER IS APPLIED HERE AND NOT LEFT TO THE SQL, even though
    the bridge's query already carries `cr.map = %s` in its WHERE clause. It
    is a hard constraint - `ResolveTravelTarget` refuses a spawn that is not
    on the character's own map, because `MoveFarTo` paths through
    PathGenerator and there is no navmesh across an ocean - and a hard
    constraint belongs where a test with no database can reach it. The
    duplication is the point: if that query is ever widened, or a caller
    hands rows in from somewhere else, the rule still holds.

    Sorted by (yards, entry) rather than by yards alone so two spawns at an
    identical distance never make the answer depend on the row order MySQL
    happened to return - the same "so the answer never depends on sweep
    order" tie-break `ResolveTravelTarget` applies to its own shortlist.
    """
    return sorted(
        (s for s in (spawns or ()) if int(s.map_id) == int(map_id)),
        key=lambda s: (float(s.yards), int(s.entry)),
    )


def supply_trip(
    needs, spawns, leader: str, map_id: int, shopper_maps=None
) -> SupplyTrip:
    """Where to send the family so one outstanding reagent can be bought.

    `needs` is every (shopper, reagent) pair that has nowhere in reach
    selling it. `spawns` is `{item entry: [VendorSpawn, ...]}` - what the
    world says stocks each of those reagents - and `map_id` is the map the
    LEADER is standing on, because the leader is the one who has to walk
    there and everybody else arrives by following.

    `shopper_maps` IS `{name: map id}` FOR THE SHOPPERS, AND IT IS THE OTHER
    HALF OF "arrives by following". Following only works between characters
    on one map: a shopper stranded on the other continent - which this family
    has managed before, three of five hearth to Eastern Kingdoms while the
    work is on Kalimdor - never reaches the counter however well the leader
    walks, so taking their trip would be a journey that cannot end in a
    purchase. Passing None skips the check, which is what the pure tests do
    when the question they are asking is not about maps; the bridge always
    passes it.

    THE NEAREST NEED WINS, NOT THE FIRST ONE BY NAME. Ranking on the chosen
    vendor's own distance means a shopper whose vendor is twenty yards away
    is served before one whose vendor is three thousand, which is both more
    useful and perfectly stable: every tie is broken by (shopper, entry), so
    the same world always produces the same trip and the pass cannot
    oscillate between two equally good answers, aiming and re-aiming forever.

    A NEED WITH NO VENDOR ANYWHERE ON THIS MAP IS NOT A REFUSAL OF THE PASS.
    It is recorded in `unreachable` and the pass carries on to whoever CAN be
    served - one unsupplyable recipe must not hold up the other four
    characters, which is the same reasoning `craft_reagent_errands` already
    applies within a single recipe's two reagents.
    """
    trimmed = sorted(
        (n for n in (needs or ()) if n and n.shopper and int(n.entry) > 0),
        key=lambda n: (str(n.shopper), int(n.entry)),
    )
    if not trimmed:
        return SupplyTrip(
            traveller=leader or "",
            why_not="Nobody is short of a vendor reagent.",
        )
    if not leader:
        # Not a theoretical branch: `_head_now` reads the world and can
        # legitimately answer nobody. Aiming '' would write the errand onto
        # no row at all and report nothing, which is the failure mode this
        # whole issue is about, one layer up.
        return SupplyTrip(
            why_not="Nobody leads the family right now, and a follower aimed "
            "at a vendor does not walk - so this pass takes no trip.",
        )

    unreachable = []
    reachable = []
    for need in trimmed:
        if shopper_maps is not None:
            standing = shopper_maps.get(need.shopper)
            if standing is None or int(standing) != int(map_id):
                unreachable.append(
                    "%s is on map %s and %s leads on map %d, so no walk the "
                    "leader takes puts %s in front of a counter - following "
                    "does not cross a map"
                    % (
                        need.shopper,
                        "nowhere visible" if standing is None else int(standing),
                        leader,
                        int(map_id),
                        need.shopper,
                    )
                )
                continue
        usable = _usable((spawns or {}).get(int(need.entry)), map_id)
        if not usable:
            unreachable.append(
                "nothing on map %d sells %s (%d) at all, so %s's craft errand "
                "cannot be supplied from this continent - no walk will change "
                "that, and either the recipe or the map has to"
                % (
                    int(map_id),
                    need.label or "that reagent",
                    int(need.entry),
                    need.shopper,
                )
            )
            continue
        reachable.append(
            (float(usable[0].yards), str(need.shopper), int(need.entry), need, usable)
        )

    unreachable = tuple(unreachable)
    if not reachable:
        return SupplyTrip(
            traveller=leader,
            unreachable=unreachable,
            why_not="Every outstanding reagent is one nothing on this map sells.",
        )

    reachable.sort(key=lambda row: (row[0], row[1], row[2]))
    _yards, _shopper, _entry, need, usable = reachable[0]
    chosen = usable[0]

    # THE COLUMN IS THE LAST GATE, AND IT IS ASKED RATHER THAN ASSUMED.
    # `travel.resolve` is the one place that knows what a valid `travel_npc`
    # value looks like, and it is also what rejects entry 0 - the
    # worldserver's own "no creature" sentinel, which would otherwise be
    # written as a perfectly plausible-looking aim that resolves to nothing.
    # The width check is `travel.COLUMN_WIDTH`'s own, for the reason that
    # constant states: a value that does not fit is a value the module can
    # never read back, and a truncated creature entry is a different
    # creature. Every entry on this world is five or six digits against a
    # column of 32, so this has room to spare - it is asked anyway, because
    # "there was room last time somebody looked" is not a check.
    target = travel.resolve(str(int(chosen.entry)))
    if not target or len(target) > travel.COLUMN_WIDTH:
        return SupplyTrip(
            traveller=leader,
            unreachable=unreachable,
            why_not="creature %r is not something overseer_roster.travel_npc "
            "can hold, so no aim was written" % (chosen.entry,),
        )

    # WHO ELSE THIS ONE WALK ALREADY ANSWERS FOR. A second need whose own
    # nearest vendor is the SAME creature is not waiting for anything - the
    # family is about to stand in front of it, and that shopper's own DoBuy
    # fires there like everybody else's. Calling that "waiting its turn"
    # would be a log line that is simply untrue, and a person reading it
    # would go looking for a second trip that is never going to be needed.
    also_served = []
    waiting = []
    for row in reachable[1:]:
        said = "%s's %s" % (row[3].shopper, row[3].label or "reagent %d" % row[2])
        (also_served if row[4][0].entry == chosen.entry else waiting).append(said)

    return SupplyTrip(
        traveller=leader,
        target=target,
        shopper=need.shopper,
        entry=int(need.entry),
        label=need.label,
        vendor=chosen,
        passed_over=tuple(usable[1 : 1 + SHORTLIST]),
        also_served=tuple(also_served),
        waiting=tuple(waiting),
        unreachable=unreachable,
    )


def report(trip) -> str:
    """One sentence for the log, naming everything a person would otherwise
    have to run a query to find out.

    The line this replaces was "X is not near a vendor stocking Y; vendor aim
    taken=True", which named neither where anybody was sent nor why there,
    and was followed by silence for as long as the errand went nowhere. This
    names the creature entry, so the aim can be checked against npc_vendor by
    hand; its faction, because the gate that can refuse it lives in the C++
    and reads exactly that column; and the runners-up, so that "it went to
    the wrong one" and "it was refused and there was no other" are different
    sentences rather than the same silence.
    """
    if not trip.target:
        return trip.why_not
    vendor = trip.vendor
    said = (
        "%s is aimed at creature %s (%s, faction %s, %d yards) so %s can buy "
        "%s (%d) - the family follows the leader, and each shopper's own buy "
        "fires where they end up standing"
        % (
            trip.traveller,
            trip.target,
            vendor.name or "unnamed",
            vendor.faction,
            round(float(vendor.yards)),
            trip.shopper,
            trip.label or "that reagent",
            trip.entry,
        )
    )
    if trip.passed_over:
        said += ". Also stocking it, further off: " + ", ".join(
            "%d %s (faction %s, %d yards)"
            % (s.entry, s.name or "unnamed", s.faction, round(float(s.yards)))
            for s in trip.passed_over
        )
    if trip.also_served:
        said += ". The same counter also answers: " + ", ".join(trip.also_served)
    if trip.waiting:
        said += ". Waiting their turn: " + ", ".join(trip.waiting)
    return said
