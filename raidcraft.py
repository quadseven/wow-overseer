"""Which craft spells make what a raid night eats, and how far off each one is.

Pure module, same seam as craft.py and craft_rhythm.py: a skill name and a
skill value in, a spell id and a sentence out. Nothing here talks to MySQL.

WHY THIS EXISTS. The operator's ask is "a constant supply of crafted items for
raids ... max buffs always in raids to increase chance of winning". Two tables
in this repo each answer half of it and neither knows the other exists:

  craft.RECIPES     which recipe raises a crafting SKILL at a given value. It
                    is a LEVELING route. It does not know, and has never been
                    asked, whether the item that falls out of a cast is
                    something a raid wants or vendor trash.
  raidgoals.RECIPES what a Molten Core night ASKS FOR, per member, and how far
                    the guild's holdings fall short. It is a REPORTING plan
                    written in item names so the realm can refuse one. It does
                    not know which skill value a crafter has to reach, or by
                    which route, or whether the recipe can be got at all.

So a crafter's whole leveling ladder could be picked without a single rung
producing anything a raid would carry, and nothing anywhere would say so. This
module is the join: keyed by CRAFT SPELL, carrying the realm's own answer for
each raid consumable - what makes it, what skill, what rank THIS realm demands,
and how that rank is come by.

IT IS A THIRD TABLE AND THAT IS THE POINT, NOT AN OVERSIGHT. The first thing
checked was whether this belonged inside one of the two above, because a third
copy of a fact is how the reagent map came to exist twice before craft_rhythm
unified it. It belongs in neither:

  craft.RECIPES is a PARTITION - `recipe_for` returns the first bracket
  containing a skill value and `test_brackets_do_not_overlap_within_one_skill`
  holds every skill line to exactly one recipe per point. Most of the
  consumables below sit at skill values some other recipe legitimately owns, or
  above 300 where nothing is aimed at all, so they cannot be entries in it.

  raidgoals.RECIPES is deliberately written in NAMES and not ids, so that a
  name this realm spells differently is a refusal a reader can see. Putting
  measured spell ids and rank floors in it would defeat the one property that
  module is built around.

EVERY FACT BELOW WAS READ OFF THE RUNNING WORLDSERVER, NOT A WIKI AND NOT THE
ISSUE THAT ASKED FOR THIS. Two sources, because the answer genuinely lives in
two places and reading only the first is the trap this module was very nearly
built on:

  Spell.dbc / SkillLineAbility.dbc / SpellFocusObject.dbc, streamed out of
  /azerothcore/env/dist/data/dbc/ in the running worldserver pod on 2026-09-14
  and md5-verified byte-identical against the pod's own `md5sum`:

      Spell.dbc             543b9fe61355b6a77a01714d52fea2e5   49839 x 234
      SkillLineAbility.dbc  d8c11abfcfe70596cb9068c0e97a1d9a   10219 x 14
      SpellFocusObject.dbc  797c65a49ae1e6336c9d851eb18011e0

  These give: which spell CREATES an item (EffectItemType where Effect == 24),
  its reagents, its RequiresSpellFocus, its EquippedItemClass, and its colour
  band (TrivialSkillLineRankLow = yellow, TrivialSkillLineRankHigh = grey).

  acore_world.trainer_spell and acore_world.item_template, for the RANK. This
  is the half that DBC alone gets wrong, and it gets it wrong silently.

`SkillLineAbility.MinSkillLineRank` IS 1 FOR ALMOST EVERY RECIPE HERE, AND IT
IS NOT THE FLOOR. Read alone it says Flask of the Titans can be cast at Alchemy
1. The real gate for a recipe that is TAUGHT - by a trainer or by a pattern
item - is stated in the world database instead:

    trainer_spell.ReqSkillRank            for a trainer-taught recipe
    item_template.RequiredSkillRank       on the "Recipe:"/"Formula:"/"Plans:"
                                          item, beside the spellid_2 that
                                          teaches the craft

which is exactly the two-source read `raidgoals._ranks` already performs
against the live realm, and `Consumable.floor` below is the checked-in
projection of it. `craft.py`'s own `min_skill` numbers have no such second
source, which is why `tests/test_craft.py`'s MEASURED_BANDS reads 1 for
seventeen of its entries and cannot catch a bracket that starts below a
trainer's rank. That is a real hole in the existing guard and it is named here
rather than fixed here; `MEASURED_RANKS` in tests/test_raidcraft.py is the
first projection of the second source this repo has.

HOW A RECIPE IS COME BY DECIDES WHOSE PROBLEM IT IS, which is why `taught` is
a field and not prose. Counted over the table below: THIRTEEN of the twenty-two
craftable consumables are taught by a pattern ITEM and not by a trainer,
including ALL FOUR flasks, ALL of the greater protection potions, Major Mana
Potion, both weapon oils and Elemental Sharpening Stone. Nothing in this repo
buys or learns from a pattern item; a concurrent change is building exactly
that ("learn a recipe from an AH-purchased item"). So for thirteen of these the
blocker is not skill and not reagents - it is that mechanism, and this table
names the dependency instead of duplicating it.

NOTHING HERE IS CASTABLE TODAY AND THE MODULE SAYS SO OUT LOUD. Measured live
2026-09-14 against `acore_characters.character_skills`:

    Ugga   Alchemy 14/75        Og    Tailoring 50/150, Enchanting 1/75
    Grug   Blacksmithing 1/75   Bork  Leatherworking 1/75
    Grog   Engineering 1/75     all five  First Aid 1/75, Cooking 1/75

The cheapest raid consumable on this realm is Free Action Potion at Alchemy
150; the cheapest a TRAINER teaches is Elixir of Fortitude at Alchemy 175. Ugga
is at 14 with an Apprentice ceiling of 75, so the nearest one is 136 points and
at least two rank trainings away. `gap` below returns that as a number rather
than letting a table of flasks read as a plan for this evening.

WHAT THIS MODULE DOES NOT DO. It does not pick a recipe - `craft.recipe_for`
does, and this module's influence on that is exercised at TABLE-AUTHORING time
(see `preferred` and the tests that gate it) rather than by a second runtime
picker that would be a second opinion about the same question. It does not
count holdings; `raidgoals` does, from the bank and the bags, through `bank.py`.
It does not decide who raids or how many: `stockpile` takes the raider count,
for the same reason `raidgoals.roster_from_guild` refuses to hardcode five.
"""

from __future__ import annotations

from dataclasses import dataclass

import craft
import goals
import raidgoals

SKILL_IDS = goals.SKILL_IDS

# HOW THIS REALM TEACHES A RECIPE. Three values, and the difference between the
# first two is the whole reason the field exists - see the module docstring.
#
# TRAINER      `acore_world.trainer_spell` has a row: a character at the rank
#              can be walked to a trainer and taught it. professions.py owns
#              that journey, and `infra#3732`'s measurement of how far the
#              nearest usable trainer is applies.
# RECIPE_ITEM  no trainer row; an `item_template` row whose `spellid_2` is this
#              spell teaches it, and that item has to be bought, looted or
#              traded for first. Nothing in this repo does that yet.
# AUTO         `SkillLineAbility.AcquireMethod = 1` with a ClassMask this
#              family matches: granted with the skill line, so there is no
#              trainer row and no pattern item BECAUSE NOBODY NEEDS TEACHING.
#              craft.py makes this same argument twice (Smelt Copper, Linen
#              Bandage) and an earlier pass read the missing rows as evidence
#              the id was wrong.
TRAINER = "trainer"
RECIPE_ITEM = "recipe item"
AUTO = "auto"

# BOTH ROUTES EXIST FOR SIX OF THEM, and `taught` records the cheaper one to
# reach. A recipe with a trainer row AND a pattern item is TRAINER here,
# because a trainer visit is machinery this repo already has and a pattern
# purchase is machinery it does not. The pattern item is named in `note` all
# the same so the other route is not lost.


@dataclass(frozen=True)
class Consumable:
    """One thing a raid night eats, and what this realm asks to make it.

    `floor` IS THE REALM'S OWN RANK AND NOT `SkillLineAbility.MinSkillLineRank`
    - see the module docstring for why the DBC alone reads 1 here and would let
    a bracket be written twenty or three hundred points too low. It comes from
    `trainer_spell.ReqSkillRank` for a TRAINER recipe and from the teaching
    item's `item_template.RequiredSkillRank` for a RECIPE_ITEM one.

    `yellow`/`grey` are `SkillLineAbility.TrivialSkillLineRankLow` and
    `...High`, the same two numbers `craft.Recipe`'s brackets are cut against:
    below `yellow` the cast is ORANGE and rolls a skill-up most reliably, at or
    above `grey` the core rolls none at all. They are carried because "is this
    consumable a legal pick at this skill value" is `floor <= value < grey`, and
    "is it a BETTER pick than the leveling recipe" is decided on `yellow`.

    `focus` is `Spell.dbc`'s `RequiresSpellFocus`, the same field and the same
    meaning as `craft.Recipe.focus`. Every entry below reads 0, which is a
    measurement and not an assumption: the operator's brief stated that "alchemy
    has an equivalent 'Alchemy Lab' spell focus requirement for the high-tier
    flasks specifically", and that is FALSE on this realm. Alchemy Lab is focus
    id 663 and exactly six spells in the whole 49,839-record file require it -
    Alchemist's Stone (17632), Mercurial Stone (38070) and the four WotLK
    Alchemist's Stone upgrades. Not one flask, elixir, potion or oil does. Left
    in the table as a field rather than dropped, because it is the field that
    would have to change if it were ever true, and `test_no_consumable_needs_a
    _focus_nothing_walks_to` is what keeps that from being silent.

    `per_raider` is a CONVENTION and never a measurement - see the block above
    `PER_RAIDER` below. 0 means this module states no per-night number for it.
    """

    spell_id: int
    item: int
    name: str
    skill: str
    floor: int
    taught: str
    yellow: int
    grey: int
    per_raider: int = 0
    focus: int = 0
    note: str = ""


# ---------------------------------------------------------------------------
# HOW MANY OF EACH, PER RAIDER, PER NIGHT.
#
# EVERY NUMBER IN THIS BLOCK IS A CONVENTION AND NOT A MEASUREMENT, exactly as
# `raidgoals`' own per-member block already states for the four it carries: no
# raid on this realm gates anybody on consumables, no table states a
# requirement, and these are what guilds asked their raiders for. The four that
# raidgoals already names are IMPORTED rather than restated, so the Raid page
# and this module cannot come to disagree about how many flasks a night is.
FLASKS_PER_RAIDER = raidgoals.PER_MEMBER_PER_NIGHT
PROTECTION_POTIONS_PER_RAIDER = raidgoals.FIRE_PROTECTION_PER_MEMBER
HEALING_POTIONS_PER_RAIDER = raidgoals.HEALING_POTIONS_PER_MEMBER
MANA_POTIONS_PER_RAIDER = raidgoals.MANA_POTIONS_PER_MEMBER

# The three this module adds, because raidgoals models no goal they belong to.
#
# AN ELIXIR IS TWO AND A FLASK IS ONE, and the difference is a rule about the
# items rather than a preference: a flask survives death and a zone change and
# lasts two hours, an elixir dies with the raider. Two is one re-application
# after the night's first wipe, which is the number a guild that wiped once
# would actually have wanted.
#
# A WEAPON BUFF IS TWO because a sharpening stone and an oil both last half an
# hour, and a raid night is longer than that.
#
# TWENTY BANDAGES is the one number here that looks large and is not: a bandage
# is the cheapest heal in the game, it is used between pulls rather than during
# them, and it is the only consumable on this list whose reagent the family
# already gathers by accident.
ELIXIRS_PER_RAIDER = 2
WEAPON_BUFFS_PER_RAIDER = 2
BANDAGES_PER_RAIDER = 20

# ONE NIGHT AND NOT FOUR. The horizon a target is stated over is a choice, and
# a bigger one is not a safer one: a four-night stockpile of Flask of the
# Titans is 160 Black Lotus, which is a number that makes the goal read as
# impossible rather than as distant, and a goal that reads as impossible gets
# ignored rather than worked toward. One night is the smallest unit anybody
# raids in, it is the unit raidgoals' own per-member numbers are already stated
# in, and `stockpile` multiplies, so a caller that wants four asks for four.
NIGHTS_STOCKED = 1

# WHO ACTUALLY DRINKS IT IS NOT DECIDED HERE, AND THE TARGET OVER-COUNTS ON
# PURPOSE. A wizard oil is for casters, a sharpening stone for melee, a mana
# potion for whoever has a mana bar - and spec is not readable from any table
# this service reaches, which is the same wall `raidgoals` hits over which of
# three flasks suits a character. So `stockpile` multiplies every consumable by
# the WHOLE raider count and `Consumable.note` names who really uses it. The
# direction of the error is chosen the way raidgoals chose `MAKES_ONE`:
# over-counting costs an afternoon of herbing, under-counting costs a raid
# night that stops.


# ---------------------------------------------------------------------------
# THE TABLE.
#
# WHAT IS IN IT: every consumable from the operator's brief that this realm
# carries under that exact name AND that some spell in `Spell.dbc` actually
# creates, plus Stonescale Oil, which is not a raid consumable itself but is a
# Flask of the Titans reagent that is itself a craft - the one reagent
# `raidgoals` already models for the same reason.
#
# WHAT IS NOT IN IT IS RECORDED TOO, in `NOT_CRAFTED` and `MISNAMED` below,
# because a list that silently dropped nine of the brief's twenty-six entries
# would read as a list that had confirmed all twenty-six.
#
# THE REAGENTS ARE NOT RESTATED HERE, and that is `craft.py`'s own rule for its
# own table: DriveCraft's CheckCast reads them from the real SpellInfo, and
# `raidgoals.RECIPES` already carries them in item names for the seven it
# models. Naming them a third time would be a third thing to keep in step. What
# IS recorded is the count of them that had to be verified for this pass and
# what came back - see the note on `raidgoals` at the foot of this module.
CONSUMABLES: tuple[Consumable, ...] = (
    # --- ALCHEMY (Ugga, skill 171) -----------------------------------------
    #
    # FREE ACTION POTION IS THE CHEAPEST RAID CONSUMABLE ON THIS REALM, at
    # Alchemy 150, and it is a pattern purchase rather than a trainer visit:
    # `trainer_spell` has no row for 6624 at all, and `Recipe: Free Action
    # Potion` (item 5642) carries RequiredSkill 171 / RequiredSkillRank 150
    # beside `spellid_2 = 6624`. Worth naming first because "the cheapest one"
    # and "the first one reachable" are different questions and the answer to
    # the second is Elixir of Fortitude, twenty-five points higher.
    Consumable(6624, 5634, "Free Action Potion", "alchemy", 150, RECIPE_ITEM,
               175, 215, per_raider=ELIXIRS_PER_RAIDER,
               note="breaks and prevents stun/immobilise for 30s - the "
                    "Baron Geddon / Shazzrah staple. Taught by Recipe: Free "
                    "Action Potion (item 5642, rank 150); NO trainer_spell row "
                    "exists, so this needs the pattern-item mechanism"),
    # ELIXIR OF FORTITUDE IS THE ONE THIS FAMILY REACHES FIRST, and the only
    # raid consumable on the whole list that a trainer teaches below 200. It is
    # also the only one that `craft.RECIPES` can name today without displacing a
    # better leveling pick - see the RAID CONSUMABLES block in craft.py for the
    # bracket it now owns and the argument for taking 175-184 off Greater
    # Healing Potion.
    Consumable(3450, 3825, "Elixir of Fortitude", "alchemy", 175, TRAINER,
               195, 235, per_raider=ELIXIRS_PER_RAIDER,
               note="+120 health for an hour; cheap, and used by all forty "
                    "because it stacks with everything. trainer_spell rank "
                    "175 across 3 trainers for 6000 copper, and also Recipe: "
                    "Elixir of Fortitude (item 3830) at the same rank. Its "
                    "reagents are IDENTICAL to Elixir of Greater Defense "
                    "(11450), which craft.RECIPES already carries - so the "
                    "gathered half is already in craft_rhythm.GATHERED and the "
                    "Leaded Vial already in craft_supply.REAGENT"),
    Consumable(11467, 9187, "Elixir of Greater Agility", "alchemy", 240, TRAINER,
               255, 295, per_raider=ELIXIRS_PER_RAIDER,
               note="+25 agility - the melee/hunter elixir until Elixir of the "
                    "Mongoose replaces it at 280. trainer_spell rank 240"),
    # STONESCALE OIL IS NOT A CONSUMABLE AND IT IS HERE ANYWAY, which is the
    # same judgement `raidgoals.RECIPES` already made about it: it is three of
    # the reagents of Flask of the Titans and it is itself an Alchemy cast, so
    # a plan that stopped at "you need three Stonescale Oil" would send somebody
    # hunting an item nothing on this realm drops. `per_raider` is 0 because
    # nobody drinks it; the flask's own target is what pulls it.
    Consumable(17551, 13423, "Stonescale Oil", "alchemy", 250, TRAINER,
               250, 260, per_raider=0,
               note="1x Stonescale Eel (13422) -> 1x Stonescale Oil. NOT a "
                    "consumable: it is 3 of the 12 reagents of Flask of the "
                    "Titans and is made rather than found, which is why "
                    "raidgoals models it too. trainer_spell rank 250"),
    Consumable(26277, 21546, "Elixir of Greater Firepower", "alchemy", 250,
               RECIPE_ITEM, 265, 305, per_raider=ELIXIRS_PER_RAIDER,
               note="+40 fire spell damage, for the fire casters. Taught by "
                    "Recipe: Elixir of Greater Firepower (item 21547, rank "
                    "250); no trainer_spell row"),
    Consumable(17571, 13452, "Elixir of the Mongoose", "alchemy", 280,
               RECIPE_ITEM, 295, 335, per_raider=ELIXIRS_PER_RAIDER,
               note="+25 agility and +2% crit - the melee battle elixir for "
                    "the whole tier. Taught by Recipe: Elixir of the Mongoose "
                    "(item 13491, rank 280); no trainer_spell row"),
    Consumable(17556, 13446, "Major Healing Potion", "alchemy", 275, TRAINER,
               290, 330, per_raider=HEALING_POTIONS_PER_RAIDER,
               note="the tier's healing potion, carried by all forty. "
                    "trainer_spell rank 275, and Recipe: Major Healing Potion "
                    "(item 13480) at the same rank. ALREADY the top bracket of "
                    "craft.RECIPES' Alchemy ladder (285-300), which is the one "
                    "place the leveling route and the raid list already agreed "
                    "before anything here was written"),
    Consumable(17580, 13444, "Major Mana Potion", "alchemy", 295, RECIPE_ITEM,
               310, 350, per_raider=MANA_POTIONS_PER_RAIDER,
               note="the tier's mana potion, for every healer and caster. "
                    "Taught by Recipe: Major Mana Potion (item 13501, rank "
                    "295); no trainer_spell row"),
    Consumable(17574, 13457, "Greater Fire Protection Potion", "alchemy", 290,
               RECIPE_ITEM, 305, 345,
               per_raider=PROTECTION_POTIONS_PER_RAIDER,
               note="absorbs 1950 fire damage - the Molten Core potion, and "
                    "the one raidgoals already counts five of per member. "
                    "Taught by Recipe: Greater Fire Protection Potion (item "
                    "13494, rank 290); no trainer_spell row"),
    Consumable(17576, 13458, "Greater Nature Protection Potion", "alchemy", 290,
               RECIPE_ITEM, 305, 345,
               per_raider=PROTECTION_POTIONS_PER_RAIDER,
               note="absorbs 1950 nature damage - the AQ/Princess Huhuran "
                    "potion rather than a Molten Core one. Taught by Recipe: "
                    "Greater Nature Protection Potion (item 13496, rank 290); "
                    "no trainer_spell row"),
    # THE FOUR FLASKS. Identical in every measured field except their reagents:
    # rank 300, pattern-taught, yellow 315, grey 330, no focus. They are the
    # furthest thing on this list from actionable and they are recorded in full
    # because "what would it take" is a real question even when the answer is
    # "286 more skill points and a mechanism nothing has built" - the same
    # argument raidgoals makes for keeping the Field Repair Bot on its page
    # with nobody holding Engineering.
    Consumable(17635, 13510, "Flask of the Titans", "alchemy", 300, RECIPE_ITEM,
               315, 330, per_raider=FLASKS_PER_RAIDER,
               note="+1200 health for two hours, survives death - the tank "
                    "flask. Taught by Recipe: Flask of the Titans (item 13519, "
                    "and a duplicate row at 31354), rank 300; no trainer_spell "
                    "row. Its Stonescale Oil reagent is itself the 17551 craft "
                    "above"),
    Consumable(17636, 13511, "Flask of Distilled Wisdom", "alchemy", 300,
               RECIPE_ITEM, 315, 330, per_raider=FLASKS_PER_RAIDER,
               note="+2000 mana for two hours - the healer flask. Taught by "
                    "Recipe: Flask of Distilled Wisdom (item 13520, duplicate "
                    "at 31356), rank 300; no trainer_spell row"),
    Consumable(17637, 13512, "Flask of Supreme Power", "alchemy", 300,
               RECIPE_ITEM, 315, 330, per_raider=FLASKS_PER_RAIDER,
               note="+150 spell damage for two hours - the caster flask. "
                    "Taught by Recipe: Flask of Supreme Power (item 13521, "
                    "duplicate at 31355), rank 300; no trainer_spell row"),
    Consumable(17638, 13513, "Flask of Chromatic Resistance", "alchemy", 300,
               RECIPE_ITEM, 315, 330, per_raider=FLASKS_PER_RAIDER,
               note="+25 to every resistance for two hours - the Blackwing "
                    "Lair flask rather than a Molten Core one. Taught by "
                    "Recipe: Flask of Chromatic Resistance (item 13522, "
                    "duplicate at 31357), rank 300; no trainer_spell row"),
    # --- BLACKSMITHING (Grug, skill 164) -----------------------------------
    #
    # A SHARPENING STONE IS THE RAID CONSUMABLE AND A GRINDING STONE IS NOT,
    # and the two are one letter apart in every leveling guide. A sharpening
    # stone is applied to a weapon for +damage for half an hour; a grinding
    # stone is a REAGENT for armour recipes and does nothing on its own. Both
    # tiers below sit at the same skill value, from the same gathered stone,
    # with identical colour bands as their grinding-stone twin - so the choice
    # between them is free, and `craft.RECIPES` now takes it. See the RAID
    # CONSUMABLES block in craft.py.
    Consumable(9918, 7964, "Solid Sharpening Stone", "blacksmithing", 200,
               TRAINER, 200, 210, per_raider=WEAPON_BUFFS_PER_RAIDER,
               note="+6 weapon damage for 30 min, from 1x Solid Stone (7912). "
                    "trainer_spell rank 200. Its twin Solid Grinding Stone "
                    "(9920) has the same rank and the same band and eats FOUR "
                    "Solid Stone per cast for an item nothing here uses"),
    Consumable(16641, 12404, "Dense Sharpening Stone", "blacksmithing", 250,
               TRAINER, 255, 260, per_raider=WEAPON_BUFFS_PER_RAIDER,
               note="+8 weapon damage for 30 min, from 1x Dense Stone (12365) "
                    "- the level 60 melee weapon buff. trainer_spell rank 250. "
                    "ALREADY craft.RECIPES' 250-259 Blacksmithing bracket, "
                    "picked over its identical-band twin Dense Weightstone "
                    "(16640) before this module existed - undocumented and "
                    "unchecked until now"),
    Consumable(22757, 18262, "Elemental Sharpening Stone", "blacksmithing", 300,
               RECIPE_ITEM, 300, 320, per_raider=WEAPON_BUFFS_PER_RAIDER,
               note="+2% crit for 30 min - strictly better than Dense for a "
                    "raid, and the reason Dense is not the end of this line. "
                    "2x Elemental Earth (7067) + 3x Dense Stone. Taught by "
                    "Plans: Elemental Sharpening Stone (item 18264, rank 300); "
                    "no trainer_spell row"),
    # --- ENCHANTING (Og, skill 333) ----------------------------------------
    #
    # THE TWO WEAPON OILS, AND ENCHANTING IS THE TRADE THAT MAKES THEM - which
    # the brief marked "Enchanting-adjacent" with the ITEM id in the spell
    # column. Read off SkillLineAbility.dbc: both sit on skill line 333 at
    # rank 300, taught by a Formula item, with no focus and no tool.
    #
    # craft.RECIPES CARRIES NO ENCHANTING AT ALL and this pass does not change
    # that. Enchanting is not a create-item trade the way the other five are:
    # of the 33 abilities on skill 333 that create an item, the reachable ones
    # are rods (a one-time tool) and wands, and every one of them below rank
    # 300 consumes a DISENCHANT product - Strange Dust, Lesser Magic Essence,
    # a shard - which nothing in this repo produces, because nothing
    # disenchants. That is its own gap and its own issue, not a bracket this
    # pass could have filled.
    Consumable(25129, 20749, "Brilliant Wizard Oil", "enchanting", 300,
               RECIPE_ITEM, 310, 330, per_raider=WEAPON_BUFFS_PER_RAIDER,
               note="+36 spell damage for an hour, for casters. 2x Large "
                    "Brilliant Shard (14344) + 3x Firebloom (4625) + 1x Imbued "
                    "Vial (18256). Taught by Formula: Brilliant Wizard Oil "
                    "(item 20756, rank 300); no trainer_spell row"),
    Consumable(25130, 20748, "Brilliant Mana Oil", "enchanting", 300,
               RECIPE_ITEM, 310, 330, per_raider=WEAPON_BUFFS_PER_RAIDER,
               note="+12 mana every 5s and +25 healing, for healers. 2x Large "
                    "Brilliant Shard (14344) + 3x Purple Lotus (8831) + 1x "
                    "Imbued Vial (18256). Taught by Formula: Brilliant Mana "
                    "Oil (item 20757, rank 300); no trainer_spell row"),
    # --- FIRST AID (all five, skill 129) -----------------------------------
    #
    # THE BANDAGE LADDER IS REAL, IT IS RAID-RELEVANT, AND IT IS BLOCKED BY THE
    # SAME TRAINER THAT BLOCKS EVERY OTHER BANDAGE - which this repo already
    # measured and wrote down, so this table records it rather than
    # re-discovering it. `professions.SECONDARY_BLOCKED["first aid"]` has the
    # whole sentence and `craft.RECIPES`' First Aid comment has the evidence.
    #
    # THE DEATH KNIGHT SPLIT APPLIES TO EVERY ONE OF THEM, not only to Heavy
    # Linen Bandage. Read across the whole of skill line 129 in
    # SkillLineAbility.dbc: every bandage above Linen Bandage carries an
    # AcquireMethod 0 row for ClassMask 0x5DF (every ordinary class) and an
    # AcquireMethod 1 row for ClassMask 0x20, which is Death Knight and nothing
    # else. The family is a Warrior, Paladin, Rogue, Mage and Priest, so for
    # all five every rung of this ladder is a trainer purchase. Linen Bandage
    # (3275) is the sole exception - ClassMask 0, AcquireMethod 1 - and it is
    # the one rung craft.RECIPES already carries.
    Consumable(7929, 6451, "Heavy Silk Bandage", "first aid", 180, TRAINER,
               180, 240, per_raider=BANDAGES_PER_RAIDER,
               note="heals 800 over 8s from 2x Silk Cloth (4306) - the "
                    "cheapest raid consumable in the game, and the only one "
                    "whose reagent the family already gathers by accident. "
                    "trainer_spell rank 180, and Manual: Heavy Silk Bandage "
                    "(item 16112) at the same rank. BLOCKED: no First Aid "
                    "trainer is reachable (infra#3614, mod-overseer#454)"),
    Consumable(10840, 8544, "Mageweave Bandage", "first aid", 210, TRAINER,
               210, 270, per_raider=BANDAGES_PER_RAIDER,
               note="heals 1104 over 8s from 1x Mageweave Cloth (4338). "
                    "trainer_spell rank 210, and Manual: Mageweave Bandage "
                    "(item 16113). Same trainer blocker as above"),
    Consumable(18630, 14530, "Heavy Runecloth Bandage", "first aid", 290,
               TRAINER, 290, 350, per_raider=BANDAGES_PER_RAIDER,
               note="heals 2000 over 8s from 2x Runecloth (14047) - the level "
                    "60 bandage, and what a raid night actually carries. "
                    "trainer_spell rank 290. Same trainer blocker as above; "
                    "Og's own Bolt of Runecloth bracket already consumes the "
                    "same cloth, which is the competition craft.RECIPES' First "
                    "Aid comment names between Tailoring and First Aid"),
)

CONSUMABLE_BY_SPELL = {c.spell_id: c for c in CONSUMABLES}

# ---------------------------------------------------------------------------
# WHAT THE BRIEF NAMED THAT NOTHING CRAFTS, AND WHAT IT ACTUALLY IS.
#
# NINE OF THE TWENTY-SIX ITEMS IN THE BRIEF ARE NOT CRAFTABLE ON THIS REALM,
# and dropping them silently would have left a list that read as if all
# twenty-six had been confirmed. Every line was settled the same way: the item
# entry was resolved out of `item_template` by exact name, then every
# `Spell.dbc` record was scanned for a `SPELL_EFFECT_CREATE_ITEM` (Effect ==
# 24) whose `EffectItemType` is that entry. No spell creates any of these.
NOT_CRAFTED: dict[int, str] = {
    # THE SIX JUJUS, AND THE BRIEF'S OWN DOUBT ABOUT THEM WAS RIGHT FOR THE
    # WRONG REASON. It suspected they were Horde-only and asked for
    # `AllowableRace` to be checked before including them. Checked:
    # `AllowableRace = -1` on all six, which is EVERY race - they are not
    # faction-locked at all. What rules them out is what they ARE:
    # `item_template.class = 12`, which is Quest, and no craft spell anywhere
    # creates one. On this realm they also have zero `npc_vendor` rows and zero
    # `creature_loot_template` rows, so nothing here even sells or drops them.
    12451: "Juju Power: item class 12 (Quest), no create spell, 0 vendor and "
           "0 creature-loot rows on this realm. AllowableRace -1, so NOT "
           "Horde-only - the brief's doubt was right, its reason was not",
    12460: "Juju Might: same - quest item, uncraftable, unsold, undropped here",
    12457: "Juju Chill: same",
    12455: "Juju Ember: same",
    12450: "Juju Flurry: same",
    12459: "Juju Escape: same",
    21151: "Rumsey Rum Black Label: a vendor drink (item class 0 subclass 5, "
           "1 npc_vendor row). No create spell - nothing crafts it, so it is a "
           "purchase and belongs to towntrip, not to any crafter",
    23123: "Blessed Wizard Oil: NOT Enchanting and not crafted at all. No "
           "create spell; 2 npc_vendor rows. In 3.3.5a it is an Argent Dawn "
           "purchase, which is a reputation errand rather than a trade",
}

# ---------------------------------------------------------------------------
# WHAT THE BRIEF SPELLED DIFFERENTLY FROM THIS REALM, and this matters because
# the brief recorded all three as "NOT found (do not build toward these without
# re-verifying yourself)". Two of the three DO exist under a different name and
# only one is genuinely absent - which is exactly the failure mode
# `raidgoals`' name-resolution design exists to surface, arriving here from the
# other direction.
MISNAMED: dict[str, str] = {
    "Flask of Petrification":
        "this realm carries Potion of Petrification (item 13506), an Alchemy "
        "craft taught by Recipe: Potion of Petrification (item 13518). It is "
        "a self-stun rather than a buff, so it is recorded here and "
        "deliberately not in CONSUMABLES",
    "Shadowoil":
        "this realm carries Shadow Oil (item 3824, two words), Alchemy spell "
        "3448, trainer_spell rank 165 and also Recipe: Shadow Oil (item 6068). "
        "It is a weapon buff with a proc rather than a flat buff, and it is "
        "the reagent of Greater Shadow Protection Potion. Not in CONSUMABLES "
        "because the brief's list of it was a guess at a name, not a goal",
    "Dreamshard Elixir":
        "genuinely absent - no item_template row matches it or anything like "
        "it. Nothing was built toward it",
}


def by_spell(spell_id: int):
    """The consumable this craft spell makes, or None.

    None for an unknown spell, NOT an error, for the same reason
    `craft.focus_for` returns 0 for one: every caller is asking "is the thing
    this character is about to cast something a raid wants", and a spell that
    is not on this list means "no", which is a perfectly ordinary answer for
    every leveling recipe in `craft.RECIPES`.
    """
    return CONSUMABLE_BY_SPELL.get(int(spell_id or 0))


def for_skill(skill: str) -> tuple:
    """Every raid consumable on one trade, cheapest realm rank first."""
    return tuple(sorted(
        (c for c in CONSUMABLES if c.skill == skill),
        key=lambda c: (c.floor, c.spell_id),
    ))


def castable(skill: str, value: int) -> tuple:
    """The consumables a character at this skill value could cast, if taught.

    "IF TAUGHT" IS THE WHOLE CAVEAT AND IT IS IN THE NAME OF NOTHING, so it is
    said here. This answers the SKILL question only: is the character at or
    past the rank this realm states. Whether they hold the recipe is a question
    only the worldserver can answer - `character_spell` is not authoritative
    for playerbots and craft.py's infra#3695 comment is the full argument - and
    whether the recipe can be got at all is `Consumable.taught`, which is a
    pattern purchase for thirteen of these and a mechanism nothing has built.

    A consumable at or past its own `grey` is still returned: it is castable,
    it simply grants no skill-up, and "can we make flasks" and "will making one
    raise anybody" are different questions. `preferred` below is the one that
    cares about grey.
    """
    at = int(value or 0)
    return tuple(c for c in for_skill(skill) if at >= c.floor)


def nearest(skill: str, value: int):
    """The next raid consumable up this trade, and how many points short.

    Returns (Consumable, points short) or (None, 0) when there is nothing above
    this value on this trade - which is the honest answer for Tailoring,
    Leatherworking, Engineering, Mining and Cooking, none of which produce a
    raid consumable at any skill value on this realm. A caller must not invent
    a fallback, the same permission discipline `craft.recipe_for` holds.

    IT DOES NOT CARE HOW THE RECIPE IS TAUGHT, which is deliberate and is why
    `nearest_teachable` exists beside it. On Alchemy the literal nearest is
    Free Action Potion at rank 150 and it is a pattern purchase nothing here
    can make, so a sentence built on this alone would name a rung this family
    cannot step on. Both answers are true and they are different, and `gap`
    prints both when they differ rather than picking one.
    """
    at = int(value or 0)
    ahead = [c for c in for_skill(skill) if c.floor > at]
    if not ahead:
        return None, 0
    return ahead[0], ahead[0].floor - at


def nearest_teachable(skill: str, value: int):
    """The next raid consumable up this trade that something here could learn.

    THE ACTIONABLE HALF OF `nearest`. Same shape, same (None, 0) refusal, but
    restricted to `TRAINER` and `AUTO` - the two ways a recipe can reach a
    character today. On Alchemy that moves the answer from Free Action Potion
    (rank 150, pattern item) to Elixir of Fortitude (rank 175, trainer), which
    is twenty-five points further and is the first rung this family can
    actually reach.
    """
    at = int(value or 0)
    ahead = [c for c in for_skill(skill)
             if c.taught in _TEACHABLE and c.floor > at]
    if not ahead:
        return None, 0
    return ahead[0], ahead[0].floor - at


def gap(name: str, skills: dict) -> str:
    """How far this character is from making anything a raid would carry.

    NEVER EMPTY, the same rule `craft_rhythm.Stand.why` and
    `craft_supply.SupplyTrip` hold: a character that is nowhere near and a
    character this module has no opinion about are different states, and a
    blank line collapses them into each other.

    IT NAMES THE CEILING AND NOT ONLY THE DISTANCE, because the two are
    different blockers and only one of them is farming. Ugga at Alchemy 14/75
    is 161 points from Elixir of Fortitude AND cannot pass 75 without a rank
    training, and a sentence that said only "161 points" would read as an
    evening's work. `skills` is one character's trades as `professions.plan`'s
    callers already build it, and the value is `character_skills`' own, which
    craft.py's infra#3695 comment establishes is late by up to fifteen minutes
    but converges - fine for a sentence about a distance of a hundred points.
    """
    said = []
    for skill in sorted(skills):
        value = int(skills.get(skill) or 0)
        if not value:
            continue
        if not for_skill(skill):
            continue
        here = castable(skill, value)
        if here:
            said.append(
                "%s's %s %d is at or past the realm's rank for %s"
                % (name, skill, value, ", ".join(c.name for c in here)))
            continue
        want, short = nearest(skill, value)
        if want is None:
            continue
        line = ("%s's %s is %d/%d and the nearest raid consumable is %s at "
                "rank %d, %d points up (%s)"
                % (name, skill, value, _ceiling(skills, skill), want.name,
                   want.floor, short, _taught_as(want)))
        # BOTH ANSWERS WHEN THEY DIFFER, because the nearest rung and the
        # nearest rung this family can step on are different facts and naming
        # only the first would point at a pattern item nothing here buys.
        reach, further = nearest_teachable(skill, value)
        if reach is not None and reach.spell_id != want.spell_id:
            line += ("; the nearest one anything here could learn is %s at "
                     "rank %d, %d points up" % (reach.name, reach.floor,
                                                further))
        said.append(line)
    if not said:
        return ("%s holds no trade that makes anything a raid night carries - "
                "no raid consumable exists at any skill value for tailoring, "
                "leatherworking, engineering, mining or cooking on this realm"
                % name)
    return "; ".join(said)


def _ceiling(skills: dict, skill: str) -> int:
    """The rank ceiling this character is under, or 0 if the caller omitted it.

    `skills` is a skill-name-to-VALUE mapping everywhere else in this repo, so
    the max is not in it and this reads a sibling key rather than inventing
    one. It returns the Apprentice cap when nothing says otherwise, because
    that is what every one of the family's crafting trades measures at and a
    sentence with no ceiling in it is the sentence this function exists to
    avoid.
    """
    return int(skills.get(skill + " max") or 75)


def _taught_as(want: Consumable) -> str:
    """Whose problem the recipe itself is, in one clause."""
    if want.taught == TRAINER:
        return "a trainer teaches it, which professions.py's errand owns"
    if want.taught == RECIPE_ITEM:
        return ("no trainer teaches it - it is a pattern item, which is the "
                "learn-from-an-item mechanism being built separately")
    return "granted with the skill line, so nobody has to be taught it"


def preferred(skill: str, value: int):
    """The raid consumable `craft.RECIPES` should be naming at this value, or None.

    THE PRIORITY THE BRIEF ASKED FOR, AND IT IS EXERCISED WHEN THE TABLE IS
    WRITTEN RATHER THAN WHEN A CHARACTER CASTS. That is not a weaker version of
    a runtime preference; it is the only version `craft.RECIPES` can have.
    `craft.recipe_for` returns the FIRST bracket containing a skill value and
    `test_brackets_do_not_overlap_within_one_skill` holds every skill line to
    exactly one recipe per point - so a character NEVER has two candidates at
    one value and there is no runtime choice to make. The choice is made once,
    by whoever writes a bracket, and this function plus
    `test_raidcraft.ThePreferenceIsTakenWhereItIsFree` is what stops it being
    made by accident.

    LEGAL MEANS CASTABLE AND STILL WORTH CASTING: `floor <= value < grey`. At
    or past grey the core rolls no skill-up, so naming a consumable there would
    trade a skill point for an item, which is a different decision from the one
    this function is for and is not this module's to make on its own.

    AND IT MEANS TEACHABLE BY SOMETHING THIS REPO HAS, which is the clause that
    keeps the whole rule honest. A RECIPE_ITEM consumable is never offered:
    thirteen of the twenty-two are pattern-taught, nothing here buys or learns
    from a pattern item, and naming one in `craft.RECIPES` would buy a
    `craft_spell` DriveCraft drops with a WARN calling it a planner bug on
    every twenty-second poll - the identical trap Heavy Linen Bandage set for
    First Aid, which craft.py has already paid for once. The day the
    learn-from-an-item mechanism lands, deleting `_TEACHABLE` from this
    function is the whole of what opens four more brackets, and
    `test_no_pattern_taught_recipe_is_ever_preferred` is what makes that a
    deliberate edit rather than a drift.

    BEST MEANS THE HIGHEST `yellow`, because a cast below its yellow value is
    ORANGE and rolls a skill-up most reliably. Ties break on the higher floor:
    a recipe whose rank is nearer this value is the one a character just earned
    and the one a leveling route would hand over to.

    None is the ordinary answer. It means no raid consumable on this trade is
    reachable, teachable and skill-granting at this value, which is true for
    every skill point below 175 on every trade the family holds.
    """
    at = int(value or 0)
    legal = [c for c in for_skill(skill)
             if c.taught in _TEACHABLE and c.floor <= at < c.grey]
    if not legal:
        return None
    return max(legal, key=lambda c: (c.yellow, c.floor, -c.spell_id))


# The two ways a recipe can reach a character today. RECIPE_ITEM is absent on
# purpose - see `preferred`.
_TEACHABLE = frozenset({TRAINER, AUTO})


def stockpile(raiders: int, nights: int = NIGHTS_STOCKED) -> tuple:
    """How many of each consumable a raid of this size wants, as data.

    `raiders` IS A PARAMETER AND NOT A FORTY, for the reason
    `raidgoals.roster_from_guild` refuses to hardcode five: the guild this
    family is building is thirty-five members and growing, a raid is whoever
    turns up, and a number baked in here would have to be edited on the day
    that changes. Forty is the size of the raid the operator is aiming at and
    `RAID_SIZE` below names it, but nothing here reads that constant - a caller
    passes what it counted.

    RETURNS ONLY THE CONSUMABLES THAT STATE A PER-RAIDER NUMBER. Stonescale Oil
    has `per_raider = 0` because nobody drinks it; it is pulled by Flask of the
    Titans' own target and counting it separately would double it.

    THE SHAPE IS (Consumable, count) PAIRS AND NOT A DICT, so a reader gets
    them in the table's own order - cheapest trade rank first - which is the
    order in which they become reachable and therefore the order the Trades
    view would want to draw them in.
    """
    heads = max(int(raiders or 0), 0)
    span = max(int(nights or 0), 0)
    return tuple(
        (c, c.per_raider * heads * span)
        for c in CONSUMABLES
        if c.per_raider > 0
    )


# The raid this whole list is for, named once so a caller that genuinely has no
# roster to count has something honest to say rather than a number it made up.
# NOTHING IN THIS MODULE READS IT - see `stockpile`.
RAID_SIZE = 40


def report(names, skills_by_name: dict) -> str:
    """One line for the log: how far the family is from the raid's shopping list.

    THIS IS THE HALF THAT MAKES THE TABLE LIVE RATHER THAN A DOCUMENT, and it
    is deliberately the SAME shape `craft_rhythm.report` already has, for the
    same reason that one exists: a fact nobody prints is a fact nobody acts on.
    `bridge._craft_rhythm_once` already holds every input this needs - the
    protected names and their trade skills - and already logs one line per
    pass, so this costs one more line and no query at all.

    IT SAYS THE DISTANCE EVERY PASS, INCLUDING WHEN THE DISTANCE IS ENORMOUS.
    That is the point: "Ugga's alchemy is 14/75 and the nearest raid consumable
    is Elixir of Fortitude at rank 175, 161 points up" is the sentence that
    stops a table of flasks from reading as a plan for this evening, and it is
    the sentence that will quietly change on the night it stops being true.
    """
    who = sorted(names or ())
    if not who:
        return ("nobody is protected, so there is no crafter to measure "
                "against the raid's list")
    said = "; ".join(gap(name, skills_by_name.get(name, {})) for name in who)
    return ("%s. The list itself is %d craftable consumables, %d of which need "
            "a pattern item nothing here buys yet." % (
                said, len(CONSUMABLES),
                sum(1 for c in CONSUMABLES if c.taught == RECIPE_ITEM)))


# ---------------------------------------------------------------------------
# WHAT THIS PASS CHECKED IN `raidgoals` AND DID NOT HAVE TO CHANGE.
#
# `raidgoals.py`'s own docstring makes an honest admission: "The REAGENT LINES
# were read from community data for 3.3.5a and are not checked back against
# this realm, because checking them means opening the database and this module
# is not allowed to." That is the one claim on the Raid page weaker than the
# rest, and this pass was in a position to settle it, so it did.
#
# ALL SEVEN OF ITS RECIPES WERE READ OUT OF THE MD5-VERIFIED `Spell.dbc` NAMED
# ABOVE, REAGENT BY REAGENT AND COUNT BY COUNT, AND EVERY ONE IS CORRECT:
#
#   17637 Flask of Supreme Power      7x Dreamfoil(13463) 3x Mountain
#                                     Silversage(13465) 1x Black Lotus(13468)
#                                     1x Crystal Vial(8925)
#   17636 Flask of Distilled Wisdom   7x Dreamfoil 3x Icecap(13467)
#                                     1x Black Lotus 1x Crystal Vial
#   17635 Flask of the Titans         7x Gromsblood(8846) 3x Stonescale
#                                     Oil(13423) 1x Black Lotus 1x Crystal Vial
#   17574 Greater Fire Protection     1x Elemental Fire(7068) 1x Dreamfoil
#                                     1x Crystal Vial
#   17556 Major Healing Potion        2x Golden Sansam(13464) 1x Mountain
#                                     Silversage 1x Crystal Vial
#   17580 Major Mana Potion           3x Dreamfoil 2x Icecap 1x Crystal Vial
#   17551 Stonescale Oil              1x Stonescale Eel(13422)
#
# Nothing in raidgoals is edited on the strength of that, because there was
# nothing to correct - and a note is the honest way to record a check that
# found nothing, rather than a change that pretends it found something. The
# eighth recipe, the Engineering Field Repair Bot (22704), was NOT checked:
# nobody on the roster holds Engineering at a rank that could cast it and it is
# outside the brief's list, so it stays exactly as unverified as its own page
# already says it is.
