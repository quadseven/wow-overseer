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
"""

from __future__ import annotations

import towntrip

# spell_id -> (item entry, display name, BuyPrice in copper). Verified
# against acore_world.item_template directly; see module docstring. Built
# from craft.RECIPES' own reagent notes for the ten (of eleven) Alchemy
# recipes that name a vial - Lesser Healing Potion (2337) is the one
# exception, since its second reagent is the previous recipe's own output,
# not a fresh vial - plus Engineering's Bronze Tube (Weak Flux only; Moss
# Agate is deliberately absent, see module docstring).
REAGENT: dict[int, tuple[int, str, int]] = {
    2330: (3371, "Empty Vial", 20),      # Minor Healing Potion
    3173: (3371, "Empty Vial", 20),      # Lesser Mana Potion
    3447: (3372, "Leaded Vial", 200),    # Healing Potion
    7181: (3372, "Leaded Vial", 200),    # Greater Healing Potion
    11449: (3372, "Leaded Vial", 200),   # Elixir of Agility
    11450: (3372, "Leaded Vial", 200),   # Elixir of Greater Defense
    11457: (8925, "Crystal Vial", 2500), # Superior Healing Potion
    11460: (8925, "Crystal Vial", 2500), # Elixir of Detect Undead
    17553: (8925, "Crystal Vial", 2500), # Superior Mana Potion
    17556: (8925, "Crystal Vial", 2500), # Major Healing Potion
    3938: (2880, "Weak Flux", 100),      # Bronze Tube (Engineering)
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
            f"{name} cannot afford {short} x {label} "
            f"({ceiling} copper against {money})"
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
    8776: ((2320, "Coarse Thread", 10, 1),),                # Linen Belt (Tailoring)
    # 9058 (Handstitched Leather Cloak) deliberately absent - that spell id
    # could not be verified against this world's live database and was
    # pulled from craft.RECIPES for the same reason; see that table's own
    # comment beside the 46-55 Leatherworking bracket.
    3756: ((2320, "Coarse Thread", 10, 2),),                # Embossed Leather Gloves
    3763: ((2320, "Coarse Thread", 10, 2),),                # Fine Leather Belt
    2167: (
        (2321, "Fine Thread", 100, 2),                      # Dark Leather Boots
        (4340, "Gray Dye", 350, 1),
    ),
    7135: (
        (2321, "Fine Thread", 100, 1),                      # Dark Leather Pants
        (4340, "Gray Dye", 350, 1),
    ),
    3818: ((4289, "Salt", 50, 3),),                          # Cured Heavy Hide
    3780: ((2321, "Fine Thread", 100, 1),),                 # Heavy Armor Kit
    7151: ((2321, "Fine Thread", 100, 2),),                 # Barbaric Shoulders
    7156: ((4291, "Silken Thread", 500, 1),),               # Guardian Gloves
    10487: ((4291, "Silken Thread", 500, 1),),              # Thick Armor Kit
    10507: ((4291, "Silken Thread", 500, 2),),              # Nightscape Headband
    10548: ((4291, "Silken Thread", 500, 4),),              # Nightscape Pants
    10558: ((8343, "Heavy Silken Thread", 2000, 2),),       # Nightscape Boots
    19049: (
        (2325, "Black Dye", 1000, 1),                       # Wicked Leather Gauntlets
        (14341, "Rune Thread", 5000, 1),
    ),
    19082: ((14341, "Rune Thread", 5000, 1),),              # Runic Leather Headband
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
