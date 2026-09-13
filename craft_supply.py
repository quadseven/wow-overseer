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

WHAT IS DELIBERATELY OUT OF SCOPE. Tailoring/Leatherworking thread and dye
(infra#3609/#3611) are the same class of gap but their item ids and prices
were not verified this pass - `REAGENT` below names only what was checked.
A future entry should be added with the same live-database verification,
not a guessed id.

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
