"""Which recipe a character should stand and cast, to level a crafting trade.

Pure module, same seam as professions.py and council.py: a skill id and a
skill value in, a spell id (or nothing) out. Nothing here talks to MySQL.

WHY THIS EXISTS (infra#440, the crafting half of infra#2757's sibling gap).
professions.py already answers "how does a character LEARN a trade" - walk to
a trainer, buy the skill, infra#2757's `learn_skill` errand. It does not
answer "how does a character RAISE a trade it already holds past 1/75" for
the CRAFTING trades specifically (blacksmithing, leatherworking, tailoring,
engineering, alchemy, enchanting) - GATHERING trades (mining, herbalism,
skinning) already climb on their own as a side effect of ordinary `job='quest'`
play (verified live: Ugga's herbalism sat at 132/225 with no drive ever built
for it), but nothing crafts an item, so nothing ever calls the core's own
skill-up roll for a production trade. See
docs/design/profession-crafting-drive.md in quadseven/mod-overseer for the
full argument and why a direct spell cast (SPELL_EFFECT_CREATE_ITEM, the
mechanism a real player's "Create" click runs) is the right primitive rather
than driving mod-playerbots' own SetCraftAction, which is built for an
attended master trading reagents across a live trade window.

SECONDARY SKILLS (First Aid, Cooking - infra#2757's Cooking/First Aid slice,
sibling to whichever primary profession each other pass covers) ARE COVERED
TOO, and by design apply to ALL FIVE characters at once rather than to
whoever `professions.assigned` gave a trade to - `professions.SECONDARY`
already names them as free, held by everyone, and never an assignment
question. `craft_errand` below checks them for every character regardless of
its primaries, which is the whole reason this slice is worth more than any
one primary profession: five characters gain from one verified bracket
instead of one.

WHAT THIS MODULE DOES NOT DO. It does not verify a character holds the
reagents a recipe needs - that check happens in mod_overseer.cpp's DriveCraft,
against the character's REAL bags, using the core's own CheckCast path. A
character short of mats simply has its cast refused and its errand left
standing for the next poll; that is expected, not an error, and duplicating
the check here would be a second source of truth for a fact only the
worldserver can see. This module answers exactly one question: for a
character who already holds a crafting skill at a given value, is there a
recipe cheap enough, and known enough, to be worth aiming them at right now.

RECIPE IDS ARE VERIFIED INDIVIDUALLY, NOT ASSUMED. `acore_world` carries no
DBC-derived recipe table on this deployment (skill_line_ability is client
data, same reason goals.SKILL_IDS was verified against character_skills
instead of a world table that does not exist) - so each entry below is a
real, well-established WotLK-era spell id, checked against public
AzerothCore/vanilla spell references rather than guessed. A profession with
no entry here returns nothing rather than a made-up id - v1 covers what could
actually be checked, and grows the table entry by entry rather than shipping
a full set some of which would be wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

import goals
import professions

SKILL_IDS = goals.SKILL_IDS

# The job mode this module is the planner for, named here rather than spelled
# as a literal at each call site - the same shape trainjob.MODE already uses,
# and for the same reason: `bridge._set_job` asks "is this the craft order"
# once and must not drift from the string `jobs.MODES` and DriveCraft's own
# gate both spell.
MODE = "craft"

# ---------------------------------------------------------------------------
# WHY THIS MODULE MUST NOT PREDICT WHAT THE WORLDSERVER WILL DO (infra#3695).
#
# It is tempting to add a `readiness()` here that answers "can the family
# craft right now" before the order is written, the way trainjob.readiness
# does for `train`. It was tried in infra#3687 and it was WRONG, and the
# reason is worth the space because the next reader will be tempted the same
# way and the evidence looks convincing right up until it is tested.
#
# The check asked whether each character KNOWS the recipe it would be aimed
# at, by reading `character_spell`. Every row said no - all five characters,
# not one of their standing `craft_spell` errands present in the table - and
# on that basis the guard refused the order. Then the worldserver crafted
# anyway: 2026-09-13 17:15-17:17, `overseer: 'Ugga' crafted 'Minor Healing
# Potion' (2330)`, seven times, while `character_spell` held no 2330 row for
# her. Og followed on 2963 shortly after. Both would have been refused.
#
# THE CAUSE: these are playerbots. mod-playerbots grants profession recipes
# at init, and `Player::_SaveSpells` writes only spells whose state is not
# UNCHANGED, so a runtime-granted recipe never reaches `character_spell` at
# all - a forced `.saveall` does not move the count. `Player::HasSpell`,
# which is what DriveCraft actually gates on, reads the in-memory spell map
# and sees them.
#
# SPELLS ARE ABSENT; SKILLS ARE MERELY LATE - and the difference is worth
# keeping straight, because over-distrusting `character_skills` would be its
# own wrong conclusion. Both were measured across the SAME fifteen minutes,
# which is what makes the comparison mean anything:
#
#   character_skills  Ugga's Alchemy read 1/75 at 17:15 while she was
#                     crafting, and 14 by 17:25. It converges.
#   character_spell   Ugga's total sat at 152 with no 2330 row at 17:15 and
#                     again at 17:30; Og's 2963 never appeared either, though
#                     he was casting it. It does not converge, because the
#                     write never happens.
#
# Choosing a recipe bracket from a skill value that is a few points stale is
# fine, and is all `craft_errand` below does with it. Concluding "this
# character knows no recipes" from `character_spell` is not fine, ever.
#
# HasSpell IS GENUINELY PER-CHARACTER, so this is not a blanket "the table is
# useless" - it is specifically unreadable from Python. Bork's errand was set
# to 2963 by hand and refused ("does not know the recipe") in the same minute
# Og was casting 2963 successfully. The worldserver's answer is precise; the
# saved copy of it is simply not there.
#
# THE RULE THAT FOLLOWS: a guard that refuses the true state is worse than
# the missing guard it replaced. Anything in Python that needs to know
# whether a craft can actually happen must consume the worldserver's OWN
# recorded answer - DriveCraft already decides correctly, clears
# `craft_spell` when it refuses, and logs why - rather than forecasting that
# decision from acore_characters. Forecasting is not a weaker version of
# asking; it is a different and wrong question.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Recipe:
    """One craftable recipe: the spell to cast, and the bracket it belongs to.

    `min_skill`/`max_skill` are the skill VALUE range this recipe is worth
    spamming across - below `min_skill` the character has not learned it yet
    (a trainer/recipe-vendor problem, not this module's), at or above
    `max_skill` it stops granting skill-ups at all and a different recipe (or
    a trainer visit for the next rank) is needed instead. `max_skill` here is
    deliberately conservative - the real cutoff a recipe stops granting
    skill-ups at is a grey/green/yellow/orange band the core computes per
    cast, not a fixed number - so this is "worth aiming at", not "guaranteed
    to grant a point every time".

    `repeatable` is the TOOL-VS-CONSUMABLE distinction (infra#440's Engineering
    follow-up). Most recipes are worth casting many times in a row - a Bolt of
    Linen Cloth, a Rough Blasting Powder - and `repeatable=True` (the default)
    is exactly that: DriveCraft keeps recasting the same errand every poll
    until skill_value walks past `max_skill`. A handful of Engineering recipes
    (Arclight Spanner, Gyromatic Micro-Adjustor) create a PERMANENT TOOL - the
    family wants exactly one, ever, not sixty. Neither the core nor this
    module blocks a second cast outright (these items are not "Unique" -
    verified against a real WotLK/3.3.5a spell+item lookup, not assumed - so
    CheckCast will not refuse a duplicate the way it would for a
    Unique-Equipped item), so `repeatable=False` is enforced the ONLY way this
    module can reach the C++ side today: a single-skill-point bracket
    (`min_skill == max_skill`). One successful cast raises skill_value past
    `max_skill` and the character falls out of the bracket on the very next
    poll, the same "walked out of range" exit every other recipe already
    uses - no new mechanism, no inventory check this module cannot make. A
    test in test_craft.py holds every `repeatable=False` entry to that
    single-point shape so a future entry cannot reintroduce a wide "craft one
    of these sixty times" bracket for a tool by mistake.
    """

    spell_id: int
    name: str
    min_skill: int
    max_skill: int
    note: str = ""
    repeatable: bool = True


# One profession, one verified entry, per the module docstring's own
# discipline. Grow this table by adding entries with the SAME care, not by
# filling every profession at once from memory.
#
# ENGINEERING (Grog, skill 202; infra#440's Engineering follow-up, sibling of
# infra#2757). Every spell id below was checked against two independent
# WotLK/3.3.5a spell+item references (wowhead's /wotlk/ and /classic/ trees,
# wotlkdb.com, classicdb.ch, warcraft.wiki.gg), not read off wowhead's
# `/wotlk/` (2022 Classic-relaunch) pages alone - that tree silently diverges
# from original 3.3.5a ids for at least two of these recipes (Explosive
# Sheep: relaunch uses 8209, an on-use "Summon NPC" spell, not the CREATE
# spell; Hi-Explosive Bomb: relaunch's 12543 has no reagent data at all on a
# 3.3.5a-targeted database). The id used below is always the one a 3.3.5a-era
# reference agrees on, cross-checked against the guide's own cumulative
# reagent totals for each bracket (total / per-cast count = the number of
# casts the bracket implies, and every entry below passed that arithmetic).
#
# BRACKETS ARE A CONTINUOUS, NON-OVERLAPPING PARTITION, not a copy of the
# leveling guide's own ranges - the guide happily lists two simultaneous
# recipes for one skill window (real Engineering, unlike Tailoring, offers
# several parallel "good enough" recipes at many skill values) but
# `recipe_for` picks one bracket per skill value, so two RECIPES entries
# cannot legally claim the same point. Adjacent brackets below therefore
# start one point after the previous one's `max_skill`, even where the guide
# itself listed a lower or equal number - this only ever costs a skill point
# of aiming-precision at a boundary, never wrongness, and
# `test_brackets_do_not_overlap_within_one_skill` already holds the whole
# table to this.
#
# 106-124 (infra#3616): Bronze Tube (spell 3938) needs Weak Flux, a plain
# vendor-bought reagent - craft_supply.REAGENT (infra#3613's reagent-buying
# module, generalized past Alchemy's vials to cover this) now keeps it
# stocked, so Bronze Tube is filled in below rather than left empty.
# Standard Scope (spell 3978, the guide's next bracket) is NOT added: it
# also needs Moss Agate, which the issue that filed this gap assumed was
# vendor-bought like Weak Flux - checked directly against
# acore_world.npc_vendor and found FALSE. Moss Agate carries zero npc_vendor
# rows on this world; it is `item_template.class=3` (Gem) dropped by mining
# nodes (gameobject_loot_template: 5% off Tin Vein/Silver Vein) and mob
# loot, the same GATHERED shape as Blacksmithing's mining-byproduct stones,
# not a buyable one. Adding Standard Scope here would create exactly the
# "recipe that can never complete" trap the 151-174 gap below was already
# left empty to avoid - no drive in this codebase aims a character at a
# specific gem drop, so it stays deferred rather than shipped broken. See
# craft_supply.py's own module docstring for the full verification.
#
#   151-174 (Whirring Bronze Gizmo, Bronze Framework, Explosive Sheep) -
#   verified real, but they collide with Heavy Blasting Powder for the SAME
#   skill window instead of sitting in their own like the Mithril/Thorium
#   chains below do (Whirring Bronze Gizmo's own trainer-verified skill floor
#   is 125, identical to Heavy Blasting Powder's, not the guide's stated 135).
#   Explosive Sheep needs BOTH of those plus Bronze Framework as reagents
#   (30/15/15 per the guide), and this module can only stand one recipe up
#   per skill window - it cannot craft Heavy Blasting Powder AND Whirring
#   Bronze Gizmo in parallel to stock Explosive Sheep the way a human
#   leveling guide assumes. Picking Heavy Blasting Powder alone would leave
#   Explosive Sheep's errand permanently reagent-short (not the ordinary
#   "gatherer is running behind" case DriveCraft's comments describe -
#   permanently, because nothing in this table ever produces the other two
#   reagents). Left out rather than shipped as a recipe that can never
#   complete; see the follow-up issue for what a multi-recipe stockpile
#   primitive would need to look like before this gap can close.
#
# Unlike Tailoring's SpellInfo, this module does not restate reagents in
# code - DriveCraft's CheckCast already reads them from the real SpellInfo,
# and duplicating them here would be a second source of truth this module's
# own docstring already argues against. The `note` on each entry names them
# for a human reading this table, not for anything the code checks.
#
# ALCHEMY (infra#2757, the Alchemy slice) - the full skill 1-300 potion/elixir
# progression from wow-professions.com's classic Alchemy guide, with every
# spell id, reagent, and output item cross-checked against two independent
# public WotLK spell/item databases (wowhead.com/wotlk and classicdb.ch) - no
# id here was carried over from the guide unverified, per the module's own
# rule. None of these `SpellInfo::RequiresSpellFocus` (Alchemy has no
# forge/anvil equivalent), so all eleven fit DriveCraft's v1 shape.
#
# THE POTION-AS-REAGENT CHAIN (Lesser Healing Potion needs 1x Minor Healing
# Potion, not a raw herb). This needs NO special handling here or in
# DriveCraft: brackets are ordered by ascending min_skill and recipe_for
# returns the FIRST bracket containing skill_value, so while skill sits in
# Minor Healing Potion's own 1-59 range the drive keeps casting it - and every
# successful cast produces one Minor Healing Potion into the bag regardless of
# whether that particular cast also rolled a skill-up, since item creation and
# the skill-up roll are independent SpellEffects. By the time skill crosses
# into Lesser Healing Potion's bracket the character has typically crafted far
# more than the guide's suggested 65, because skill-ups are probabilistic but
# casts are not. If a character DOES cross the boundary short on stock,
# DriveCraft's own CheckCast simply refuses the cast for insufficient reagents
# and leaves the errand standing - the same "fail closed, wait for the next
# poll" shape the module docstring already states for every other recipe, not
# a new failure mode this bracket introduces.
#
# VIAL-BUYING IS NOT WIRED YET - EVERY RECIPE BELOW NEEDS ONE. Empty Vial,
# Leaded Vial and Crystal Vial are vendor-bought, never gathered, and
# `towntrip.py`'s `kind='buy'` plumbing (mod-overseer#227) only knows how to
# restock food and drink today - the same gap PR #3608 already found and
# deferred for Tailoring's thread/dye recipes, except there every recipe
# past the plain cloth bolts needed it and here EVERY recipe does. Shipping
# the table anyway (rather than shipping nothing) is deliberate: a vial that
# arrives by loot, quest reward, starting kit, or a manual restock still lets
# DriveCraft actually cast these, and the alternative - holding back a fully
# verified table because ONE dependency is unmet - repeats the mistake
# `craft.py`'s own docstring already warns against for guessed ids, just
# aimed at a missing feature instead of a wrong number. Follow-up filed to
# wire vial-buying through `kind='buy'` (see the PR this shipped with).
#
# BLACKSMITHING (Grug, skill 164) - the Sharpening/Grinding Stone family
# only (infra#2757 follow-up to #440). Every entry below creates a plain
# stone item from smelted-ore-adjacent mining byproduct (Rough/Coarse/
# Heavy/Solid/Dense Stone - the "junk" stone mining also yields alongside
# ore, which Grug's own mining already carries as a side effect), and every
# one of them was checked to have NO SpellInfo::RequiresSpellFocus and NO
# EquippedItemClass tool requirement - the same "no travel, no gear-swap
# needed" shape DriveCraft's v1 assumes for Tailoring's bolts.
#
# THIS IS DELIBERATELY NOT THE WHOLE BLACKSMITHING PROGRESSION. Every
# "worn" recipe in the wow-professions.com guide between these brackets
# (Runed Copper Belt, Silver Rod, Rough Bronze Leggings, Patterned Bronze
# Bracers, Golden Rod, Green Iron Leggings/Bracers, Golden Scale Bracers,
# Heavy Mithril Gauntlet, Steel Plate Helm, Mithril Spurs, Imperial Plate
# Bracers/Boots) was checked and every one of them requires an Anvil
# (SpellInfo::RequiresSpellFocus) PLUS a Blacksmith Hammer equipped as a
# tool (SpellInfo::EquippedItemClass) - neither of which DriveCraft's v1
# satisfies (it casts in place, it does not walk anyone to a forge, and it
# does not swap gear). Casting one of those today would sit refused on
# every single poll (SPELL_FAILED_REQUIRES_SPELL_FOCUS or
# SPELL_FAILED_EQUIPPED_ITEM_CLASS) forever, not eventually succeed - so
# they are left out rather than shipped to fail closed silently. Green Iron
# Leggings/Bracers carry a second, independent blocker on top of the anvil
# one: Green Dye, which nothing in the family gathers and bridge.py's
# town-trip `kind='buy'` plumbing does not yet buy craft reagents (only
# food/drink) - see infra's craft-leveling follow-up issue.
#
# Each spell id, its reagent, and its RequiresSpellFocus/EquippedItemClass
# status was checked against two independent public WotLK/classic spell
# databases (wowhead.com/wotlk and classicdb.ch), cross-referenced against
# the wow-professions.com guide's own stated stone-to-item ratios. The
# guide's own brackets touch or overlap at their edges (the same shape
# Tailoring's brackets did) - adjacent entries below are shifted by one
# skill point off the guide's stated numbers so RECIPES brackets never
# overlap; the real gaps between entries (91-124, 141-199, 211-249) are the
# Anvil-gated brackets above, left empty on purpose rather than stretched
# to cover them.
#
#   Rough Sharpening Stone   spell 2660   item 2862   1x Rough Stone (2835)
#   Rough Grinding Stone     spell 3320   item 3470   2x Rough Stone (2835)
#   Coarse Sharpening Stone  spell 2665   item 2863   1x Coarse Stone (2836)
#   Coarse Grinding Stone    spell 3326   item 3478   2x Coarse Stone (2836)
#   Heavy Grinding Stone     spell 3337   item 3486   3x Heavy Stone (2838)
#   Solid Grinding Stone     spell 9920   item 7966   4x Solid Stone (7912)
#   Dense Sharpening Stone   spell 16641  item 12404  1x Dense Stone (12365)
#
# LEATHERWORKING - originally three verified entries (Light Leather, Light
# Armor Kit, Heavy Leather), each checked against the same clean source:
# wowhead's own tooltip API (nether.wowhead.com/wotlk/tooltip/spell/<id>),
# which renders the SpellInfo reagent table directly with none of a spell
# page's "related recipes" sidebar to confuse a reader (that sidebar DID leak
# into a first pass at Heavy Leather and Light Armor Kit read off the
# rendered page - the tooltip API does not carry one and is corroborated
# below by a second, independent database each time). Those three are the
# wow-professions.com guide's own "recycle a gathered good into armor"
# bracket - every reagent is Skinning output, none bought from a vendor.
#
# infra#3611 ADDED FOURTEEN MORE (Embossed Leather Gloves through Runic
# Leather Headband) once craft_supply.REAGENTS existed to buy their
# thread/dye - see that table's own header comment, directly above the
# `leatherworking` entry below, for the verification and bracket-shifting
# detail. (Its own dict entries sit below Cooking's, in insertion order.)
# The bracket's own 46-55 entry (Handstitched Leather Cloak) is deliberately
# NOT among them - see the comment beside its bracket's own gap, below.
#
# TAILORING - the "Bolt of X Cloth" family (infra#2757 follow-up to #440).
# Every bolt entry below is a plain cloth->bolt SPELL_EFFECT_CREATE_ITEM
# spell: no SpellInfo::RequiresSpellFocus (a tailor needs no workbench for
# any bolt recipe), one cloth reagent, no vendor-bought thread/dye. That was
# a deliberate v1 scoping decision, not an oversight - see
# docs/design/profession-crafting-drive.md's follow-up note. infra#3609
# closed the FIRST thread-dependent gap once craft_supply.REAGENTS existed
# to buy it (Linen Belt, added directly below the Linen bolt entry - see its
# own comment for the verification and the Woolen-bolt bracket shift it
# needed). Silk Headband, Crimson Silk Vest, Runecloth Belt/Bag/Gloves and
# the rest of the guide's thread/dye recipes are still deferred to a
# follow-up - infra#3609's own acceptance criteria asked only for "at least
# the next Tailoring bracket that needs thread", which Linen Belt satisfies.
# Real thread-and-dye recipes are worth more skill per cast, so a character
# still sits idle in the remaining gaps between these brackets instead of
# the y-axis staying full - the accepted cost of only shipping what this
# pass could verify.
#
# THIS BLOCK WAS RE-VERIFIED AGAINST THE SERVER ITSELF (infra#3689) and two
# of the facts it stated were wrong. The earlier pass used "two independent
# public WotLK/classic spell databases (wowhead.com and classicdb.ch)"
# cross-referenced against a leveling guide's cumulative reagent totals.
# This pass read `Spell.dbc` and `SkillLineAbility.dbc` straight out of the
# RUNNING worldserver pod (/azerothcore/env/dist/data/dbc/) - the files the
# server itself loaded, and so the only source that cannot disagree with the
# world the family lives in. Note that `acore_world` still cannot answer
# this: `skilllineability_dbc` exists but is an empty shell (0 rows) and
# `spell_dbc` holds only 4492 override rows, none of them these. The DBC
# FILES, not a SQL table, are the thing to check.
#
# WHAT CHANGED, AND WHY IT MATTERED:
#
#   * "Bolt of Linen Cloth spell 3910" was NOT Bolt of Linen Cloth. Spell
#     3910 is named "Tailoring", has no reagents and creates no item: it is
#     the EXPERT TAILORING rank spell, which a character receives at skill
#     125. So the 1-60 bracket named a non-recipe, and DriveCraft dropped
#     every errand built from it - `'Og' has a craft errand for 'Tailoring'
#     (3910) and does not know the recipe` on a 300-second loop, for as long
#     as the entry has existed. The real Bolt of Linen Cloth is 2963 (2x
#     Linen Cloth 2589 -> Bolt of Linen Cloth 2996), exactly as this block's
#     own reagent note always described. Corroborated three ways: no
#     `trainer_spell` row teaches 3910; 3 of ~1000 characters hold it, none
#     below skill 125; and with 2963 written to his roster row Og crafted
#     six Bolts of Linen Cloth in three minutes and took Tailoring 1 -> 7.
#
#   * Mageweave and Runecloth take FOUR cloth per bolt, not five. The
#     earlier pass found a source (warcraft.wiki.gg) saying 4, rejected it
#     as "a stale reagent count" on the strength of a guide's arithmetic,
#     and wrote 5. Spell.dbc says 4 for both. The rejected source was right
#     and three agreeing secondary sources were wrong. Recorded in full
#     rather than quietly corrected, because the failure mode is the lesson:
#     agreement between secondary sources is not evidence, and the note that
#     wrote the disagreement down is the only reason this was cheap to
#     settle.
#
# Reagent counts below are Spell.dbc's `Reagent[]`/`ReagentCount[]` and the
# item is its `EffectItemType[]`:
#
#   Bolt of Linen Cloth    spell 2963  item 2996  2x Linen Cloth (2589)
#   Bolt of Woolen Cloth   spell 2964  item 2997  3x Wool Cloth (2592)
#   Bolt of Silk Cloth     spell 3839  item 4305  4x Silk Cloth (4306)
#   Bolt of Mageweave      spell 3865  item 4339  4x Mageweave Cloth (4338)
#   Bolt of Runecloth      spell 18401 item 14048 4x Runecloth (14047)
#
# Brackets below are the wow-professions.com guide's own stated ranges for
# each bolt (a leveling guide's "worth casting here" bracket, same kind of
# source the existing Linen entry's 1-60 already leaned on before this pass
# extended it slightly past the guide's stated 1-45). Gaps between brackets
# (146-174, 186-249, 261-300) are exactly where the still-deferred thread/
# dye recipes belong (infra#3609's own body: "Reinforced Linen Cape, Silk
# Headband, Crimson Silk Vest, Runecloth Belt/Bag/Gloves, and more") -
# `recipe_for` correctly returns None there rather than inventing a bolt
# recipe that would not grant a skill-up.
#
# LINEN BELT (infra#3609, the minimum bracket its own acceptance criteria
# asked for once craft_supply's buy plumbing existed - see
# craft_supply.REAGENTS). Spell 8776 creates item 7026 from 1x Bolt of Linen
# Cloth (2996) + 1x Coarse Thread (2320, vendor-bought - see
# craft_supply.REAGENTS); cross-checked against two independent public
# WotLK/classic spell databases (wowhead.com/wotlk and classicdb.ch, both
# agreeing on id, output and reagents). The guide's own stated range is
# ~40-67, which overlaps BOTH the Linen (1-60) and Woolen (was 61-100) bolt
# brackets above - this table allows only one recipe per skill point, so
# Woolen Cloth's own `min_skill` is shifted from 61 to 68 (the same
# "adjacent entries shifted by one skill point off the guide's stated
# numbers" convention the Blacksmithing table already documents) rather than
# stretching Linen Belt across a range something else already legitimately
# covers.
RECIPES: dict = {
    SKILL_IDS["tailoring"]: (
        Recipe(2963, "Bolt of Linen Cloth", min_skill=1, max_skill=60,
               note="2x Linen Cloth (2589) -> 1x Bolt of Linen Cloth (2996), "
                    "no focus needed. NOT spell 3910 - that id is 'Tailoring', "
                    "the Expert rank profession spell, which creates nothing; "
                    "see this table's own header comment for how that went "
                    "unnoticed (infra#3689)"),
        Recipe(8776, "Linen Belt", min_skill=61, max_skill=67,
               note="1x Bolt of Linen Cloth (2996), 1x Coarse Thread (2320, "
                    "vendor-bought) -> 1x Linen Belt (item 7026), no focus "
                    "needed"),
        Recipe(2964, "Bolt of Woolen Cloth", min_skill=68, max_skill=100,
               note="3x Wool Cloth -> 1x Bolt of Woolen Cloth, no focus "
                    "needed; min_skill shifted from the guide's 61 to make "
                    "room for Linen Belt directly above, see this table's "
                    "own header comment"),
        Recipe(3839, "Bolt of Silk Cloth", min_skill=125, max_skill=145,
               note="4x Silk Cloth -> 1x Bolt of Silk Cloth, no focus needed"),
        Recipe(3865, "Bolt of Mageweave", min_skill=175, max_skill=185,
               note="4x Mageweave Cloth -> 1x Bolt of Mageweave, no focus "
                    "needed; FOUR, not the five an earlier pass wrote - "
                    "Spell.dbc, see this table's header comment"),
        Recipe(18401, "Bolt of Runecloth", min_skill=250, max_skill=260,
               note="4x Runecloth -> 1x Bolt of Runecloth, no focus needed; "
                    "FOUR, not the five an earlier pass wrote - Spell.dbc, "
                    "see this table's header comment"),
    ),
    # FIRST AID (infra#2757's Cooking/First Aid slice) - a SECONDARY skill,
    # not a CRAFTING one: every one of the five already holds it at 1/75
    # (verified live, character_skills skill 129, 2026-09-12) rather than
    # having to be assigned it, so `craft_errand` below checks it for every
    # character, not only whoever `professions.assigned` names. This is the
    # closest fit to the module's own verified pattern - plain cloth
    # reagent, no vendor purchase, no SpellInfo::RequiresSpellFocus - and the
    # family already carries cloth from humanoid kills while questing.
    #
    # Both entries below are taught TOGETHER the moment Apprentice First Aid
    # is learned (which the family already has - that is what "1/75" means),
    # so neither needs a trainer visit before `craft_errand` may aim a
    # character at it. Capped at 74, one short of Apprentice's own 75 cap
    # (character_skills.max, live-verified for all five): sitting exactly at
    # 75/75 with nothing left in this bracket is a `craft_spell = 0` "go
    # train Journeyman" state (professions.secondary_rank_errand), not a
    # wasted cast on a recipe that has stopped granting skill-ups.
    #
    # Spell ids and reagents cross-checked against two independent public
    # WotLK/classic spell databases (wowhead.com and classicdb.ch, both
    # returning the same id and reagent count for every entry below):
    #
    #   Linen Bandage        spell 3275  item 1251  1x Linen Cloth (2589)
    #   Heavy Linen Bandage  spell 3276  item 2581  2x Linen Cloth (2589)
    #
    # Wool Bandage/Heavy Wool Bandage (spells 3277/3278, verified the same
    # way) are the next bracket - taught together at Journeyman - and are
    # deferred to a follow-up issue until `professions.secondary_rank_errand`
    # actually lands a character at that trainer, per the same "never name a
    # spell the character does not yet hold" rule DriveCraft enforces
    # (mod-overseer's own bad-id-vs-not-known distinction in DriveCraft would
    # otherwise drop the errand as a "planner bug" the moment it were tried).
    SKILL_IDS["first aid"]: (
        Recipe(3275, "Linen Bandage", min_skill=1, max_skill=39,
               note="1x Linen Cloth -> 1x Linen Bandage, taught with "
                    "Apprentice First Aid"),
        Recipe(3276, "Heavy Linen Bandage", min_skill=40, max_skill=74,
               note="2x Linen Cloth -> 1x Heavy Linen Bandage, taught "
                    "alongside Linen Bandage at Apprentice"),
    ),
    # COOKING (infra#2757's Cooking/First Aid slice) - also SECONDARY, same
    # reasoning as First Aid above: every one of the five holds it at 1/75
    # already (character_skills skill 185, verified live 2026-09-12).
    #
    # Cooking's own reagents are raw meat, a creature drop rather than a
    # crafting material - closer to gathering than the cloth/ore-consuming
    # trades - so v1 ships exactly the one bracket that needs neither a
    # vendor purchase nor a recipe scroll: Charred Wolf Meat, taught with
    # Apprentice Cooking (the rank the family already holds), reagent a
    # common humanoid/beast-kill drop the family already gets from
    # questing. Every bracket past this one in the wow-professions.com guide
    # needs either vendor-bought meat (Bear Meat) or a purchased recipe (Crab
    # Cake, Curiously Tasty Omelet, Roast Raptor, ...) - the same "buy a
    # recipe scroll first" problem First Aid's Wool Bandage bracket has past
    # this pass, and is deferred to the same follow-up issue rather than
    # guessed at.
    #
    # Cross-checked against two independent public WotLK/classic spell
    # databases (wowhead.com and classicdb.ch, matching id and reagent):
    #
    #   Charred Wolf Meat  spell 2538  item 2679  1x Stringy Wolf Meat
    SKILL_IDS["cooking"]: (
        Recipe(2538, "Charred Wolf Meat", min_skill=1, max_skill=50,
               note="1x Stringy Wolf Meat -> 1x Charred Wolf Meat, taught "
                    "with Apprentice Cooking"),
    ),
    SKILL_IDS["engineering"]: (
        Recipe(3918, "Rough Blasting Powder", min_skill=1, max_skill=30,
               note="1x Rough Stone -> 1x Rough Blasting Powder (item 4357)"),
        Recipe(3922, "Handful of Copper Bolts", min_skill=31, max_skill=50,
               note="1x Copper Bar -> 1x Handful of Copper Bolts (item 4359)"),
        Recipe(7430, "Arclight Spanner", min_skill=51, max_skill=51,
               repeatable=False,
               note="TOOL, craft once - 6x Copper Bar -> 1x Arclight Spanner "
                    "(item 6219). Not Unique/Unique-Equipped - verified "
                    "against wowhead+classicdb tooltip data, not assumed - so "
                    "nothing in the core refuses a second cast; the "
                    "single-point bracket is what stops this module from "
                    "recasting it, not an item flag"),
        Recipe(3923, "Rough Copper Bomb", min_skill=52, max_skill=75,
               note="1x Copper Bar, 1x Handful of Copper Bolts, 2x Rough "
                    "Blasting Powder, 1x Linen Cloth -> 1x Rough Copper Bomb "
                    "(item 4360)"),
        Recipe(3929, "Coarse Blasting Powder", min_skill=76, max_skill=90,
               note="1x Coarse Stone -> 1x Coarse Blasting Powder (item 4364)"),
        Recipe(3931, "Coarse Dynamite", min_skill=91, max_skill=100,
               note="3x Coarse Blasting Powder, 1x Linen Cloth -> 1x Coarse "
                    "Dynamite (item 4365). NOT spell 4061 - that id is the "
                    "crafted item's own throw/damage spell, a different "
                    "spell that happens to share the display name"),
        Recipe(3973, "Silver Contact", min_skill=101, max_skill=105,
               note="1x Silver Bar -> Silver Contact (item 4404); per-cast "
                    "yield could not be independently confirmed for the "
                    "3.3.5a era (a later, Cataclysm-only patch changed it) - "
                    "verify against this deployment's own cast if it matters"),
        Recipe(3938, "Bronze Tube", min_skill=106, max_skill=124,
               note="2x Bronze Bar (2841), 1x Weak Flux (2880, vendor-bought "
                    "- see craft_supply.REAGENT) -> 1x Bronze Tube (item "
                    "4371); trainer floor is skill 105 (acore_world."
                    "trainer_spell), guide range 105-125, clipped to 106-124 "
                    "so it does not collide with Silver Contact's own "
                    "max_skill=105. Standard Scope, the guide's next "
                    "bracket, is deliberately NOT added here - see the "
                    "module-level comment above"),
        Recipe(3945, "Heavy Blasting Powder", min_skill=125, max_skill=150,
               note="1x Heavy Stone -> 1x Heavy Blasting Powder (item 4377); "
                    "real trainer skill floor is 125, not the guide's stated "
                    "135 - also the reagent Hi-Explosive Bomb needs later"),
        # 151-174 deliberately empty - Whirring Bronze Gizmo / Bronze
        # Framework / Explosive Sheep, see the module-level comment above.
        Recipe(12585, "Solid Blasting Powder", min_skill=175, max_skill=194,
               note="2x Solid Stone -> 1x Solid Blasting Powder (item 10505)"),
        Recipe(12590, "Gyromatic Micro-Adjustor", min_skill=195, max_skill=195,
               repeatable=False,
               note="TOOL, craft once - 4x Steel Bar -> 1x Gyromatic "
                    "Micro-Adjustor (item 10498). Unique-Equipped (toolkit "
                    "slot, limit 1) - verified, not assumed - so a duplicate "
                    "cast is not blocked by the core either, same reasoning "
                    "as Arclight Spanner above: the single-point bracket is "
                    "the actual stop"),
        Recipe(12589, "Mithril Tube", min_skill=196, max_skill=200,
               note="3x Mithril Bar -> 1x Mithril Tube (item 10559)"),
        Recipe(12591, "Unstable Trigger", min_skill=201, max_skill=215,
               note="1x Mithril Bar, 1x Mageweave Cloth, 1x Solid Blasting "
                    "Powder -> 1x Unstable Trigger (item 10560); also a Hi-"
                    "Explosive Bomb reagent"),
        Recipe(12599, "Mithril Casing", min_skill=216, max_skill=238,
               note="3x Mithril Bar -> 1x Mithril Casing (item 10561); also "
                    "a Hi-Explosive Bomb reagent"),
        Recipe(12619, "Hi-Explosive Bomb", min_skill=239, max_skill=250,
               note="2x Mithril Casing, 1x Unstable Trigger, 2x Solid "
                    "Blasting Powder -> 1x Hi-Explosive Bomb (item 10562); "
                    "NOT spell 12543 - that id is the 2022 Classic-relaunch "
                    "tree's id for the same name and carries no 3.3.5a "
                    "reagent data. All three reagents come from the three "
                    "brackets directly above, in order, so this recipe is "
                    "reagent-ready by the time a character reaches it"),
        Recipe(19788, "Dense Blasting Powder", min_skill=251, max_skill=260,
               note="2x Dense Stone -> 1x Dense Blasting Powder (item 15992)"),
        Recipe(19791, "Thorium Widget", min_skill=261, max_skill=285,
               note="3x Thorium Bar, 1x Runecloth (item 14047) -> 1x Thorium "
                    "Widget (item 15994)"),
        Recipe(19795, "Thorium Tube", min_skill=286, max_skill=300,
               note="6x Thorium Bar -> 1x Thorium Tube (item 16000)"),
    ),
    SKILL_IDS["alchemy"]: (
        Recipe(2330, "Minor Healing Potion", min_skill=1, max_skill=59,
               note="1x Peacebloom (2447), 1x Silverleaf (765), "
                    "1x Empty Vial (3371) -> item 118, no focus needed"),
        Recipe(2337, "Lesser Healing Potion", min_skill=60, max_skill=109,
               note="1x Minor Healing Potion (118), 1x Briarthorn (2450) "
                    "-> item 858 - THE POTION-AS-REAGENT BRACKET, see the "
                    "table's own header comment; no focus needed"),
        Recipe(3447, "Healing Potion", min_skill=110, max_skill=139,
               note="1x Bruiseweed (2453), 1x Briarthorn (2450), "
                    "1x Leaded Vial (3372) -> item 929, no focus needed"),
        Recipe(3173, "Lesser Mana Potion", min_skill=140, max_skill=154,
               note="1x Mageroyal (785), 1x Stranglekelp (3820), "
                    "1x Empty Vial (3371) -> item 3385, no focus needed"),
        Recipe(7181, "Greater Healing Potion", min_skill=155, max_skill=184,
               note="1x Liferoot (3357), 1x Kingsblood (3356), "
                    "1x Leaded Vial (3372) -> item 1710, no focus needed"),
        Recipe(11449, "Elixir of Agility", min_skill=185, max_skill=209,
               note="1x Stranglekelp (3820), 1x Goldthorn (3821), "
                    "1x Leaded Vial (3372) -> item 8949, no focus needed"),
        Recipe(11450, "Elixir of Greater Defense", min_skill=210, max_skill=214,
               note="1x Wild Steelbloom (3355), 1x Goldthorn (3821), "
                    "1x Leaded Vial (3372) -> item 8951, no focus needed"),
        Recipe(11457, "Superior Healing Potion", min_skill=215, max_skill=229,
               note="1x Sungrass (8838), 1x Khadgar's Whisker (3358), "
                    "1x Crystal Vial (8925) -> item 3928, no focus needed"),
        Recipe(11460, "Elixir of Detect Undead", min_skill=230, max_skill=264,
               note="1x Arthas' Tears (8836), 1x Crystal Vial (8925) "
                    "-> item 9154 - only two reagent types, no focus needed"),
        Recipe(17553, "Superior Mana Potion", min_skill=265, max_skill=284,
               note="2x Sungrass (8838), 2x Blindweed (8839), "
                    "1x Crystal Vial (8925) -> item 13443, no focus needed"),
        Recipe(17556, "Major Healing Potion", min_skill=285, max_skill=300,
               note="2x Golden Sansam (13464), 1x Mountain Silversage (13465), "
                    "1x Crystal Vial (8925) -> item 13446, no focus needed"),
    ),
    SKILL_IDS["blacksmithing"]: (
        Recipe(2660, "Rough Sharpening Stone", min_skill=1, max_skill=29,
               note="1x Rough Stone -> 1x Rough Sharpening Stone, no focus needed"),
        Recipe(3320, "Rough Grinding Stone", min_skill=30, max_skill=64,
               note="2x Rough Stone -> 1x Rough Grinding Stone, no focus needed"),
        Recipe(2665, "Coarse Sharpening Stone", min_skill=65, max_skill=74,
               note="1x Coarse Stone -> 1x Coarse Sharpening Stone, no focus needed"),
        Recipe(3326, "Coarse Grinding Stone", min_skill=75, max_skill=90,
               note="2x Coarse Stone -> 1x Coarse Grinding Stone, no focus needed"),
        Recipe(3337, "Heavy Grinding Stone", min_skill=125, max_skill=140,
               note="3x Heavy Stone -> 1x Heavy Grinding Stone, no focus needed"),
        Recipe(9920, "Solid Grinding Stone", min_skill=200, max_skill=210,
               note="4x Solid Stone -> 1x Solid Grinding Stone, no focus needed"),
        Recipe(16641, "Dense Sharpening Stone", min_skill=250, max_skill=260,
               note="1x Dense Stone -> 1x Dense Sharpening Stone, no focus needed"),
    ),
    # LEATHERWORKING'S THREAD/DYE BRACKETS (infra#3611) - the fifteen
    # recipes the issue named, every one now that craft_supply.REAGENTS
    # exists to buy their thread/dye. Every spell id, output item and
    # reagent list was cross-checked against at least two independent
    # public WotLK/classic sources (wowhead.com/wotlk and classicdb.ch,
    # cross-referenced against wow-professions.com's own stated brackets).
    # One genuine source disagreement was found and resolved the same way
    # the Tailoring bolt table's own header comment already resolved one:
    # Runecloth Gloves is NOT in this pass (it is a Tailoring recipe, not
    # Leatherworking - infra#3609's remaining scope, not this issue's).
    #
    # A SCRAPING ARTIFACT WAS CAUGHT AND DISCARDED, not shipped. Wowhead's
    # rendered spell pages for Handstitched Leather Cloak and Embossed
    # Leather Gloves both showed an extra "Ruined Leather Scraps" reagent
    # line that classicdb.ch's own reagent table does NOT show and that
    # does not match wow-professions.com's stated per-batch totals - the
    # same "related recipe sidebar leaked into a first pass" failure mode
    # this table's own header comment already documented for Heavy Leather
    # and Light Armor Kit above. Spot-verified directly against classicdb.ch
    # (Handstitched Leather Cloak: 2x Light Leather, 1x Coarse Thread, no
    # Ruined Leather Scraps) before trusting either source alone.
    #
    # BRACKETS ARE CONTINUOUS AND NON-OVERLAPPING, the same "shift by one
    # skill point off the guide's own stated numbers" convention the
    # Blacksmithing/Tailoring tables above already use, chosen so this
    # closes the ENTIRE 1-300 gap this issue complained about ("most of the
    # profession's leveling range undriven") rather than leaving new gaps
    # between the old zero-reagent brackets and these new ones. Two of the
    # fifteen (Nightscape Boots, Runic Leather Headband) have a real,
    # unresolved skill-range disagreement between sources: two independent
    # WotLK trainer-data lookups put their real learn-floor at 235 and 270,
    # while the wow-professions.com guide (and infra#3611's own body) states
    # 250 and 290. The LATER, more conservative number from the guide is
    # used below - a character able to learn Nightscape Boots at the
    # trainer-verified 235 is trivially also able to at 251, so this never
    # aims a cast the trainer would refuse, it only starts the bracket a
    # little later than the true floor might allow.
    SKILL_IDS["leatherworking"]: (
        # spell 2881, creates item 2318 from 3x Ruined Leather Scraps (2934).
        # Cross-checked: wowhead tooltip API (wotlk) + classicdb.ch spell
        # search naming the same id for the same name. Every leatherworker
        # knows this from skill 1 - it is not trainer-gated separately.
        Recipe(2881, "Light Leather", min_skill=1, max_skill=19,
               note="3x Ruined Leather Scraps -> 1x Light Leather, recycle, "
                    "no focus needed"),
        # spell 2152, creates item 2304 from 1x Light Leather (2318).
        # Cross-checked: wowhead tooltip API (wotlk) + classicdb.ch spell
        # page, both agreeing on a single Light Leather reagent and a
        # SPELL_EFFECT_CREATE_ITEM effect.
        Recipe(2152, "Light Armor Kit", min_skill=20, max_skill=45,
               note="1x Light Leather -> 1x Light Armor Kit, no focus needed"),
        # 46-55 DELIBERATELY EMPTY. Handstitched Leather Cloak (the
        # wow-professions.com guide's own pick for this bracket) creates
        # item 7276 - that item genuinely exists on this world - but spell
        # 9058 itself could not be verified against this world's live
        # database: no `trainer_spell` row teaches it (unlike every other
        # recipe in this table, all confirmed there) and no pattern item in
        # `item_template` names it either. The only "verification" behind
        # it was two external wiki pages, which is exactly the guessed-id
        # risk this table's own discipline exists to refuse - see the
        # module-level comment on the 151-174 Engineering gap for the same
        # reasoning applied there. Left empty rather than shipped unverified;
        # a future pass should confirm the real teaching spell (trainer or
        # pattern) before filling this in.
        Recipe(3756, "Embossed Leather Gloves", min_skill=56, max_skill=100,
               note="3x Light Leather, 2x Coarse Thread (2320, "
                    "vendor-bought) -> item 4239, no focus needed"),
        Recipe(3763, "Fine Leather Belt", min_skill=101, max_skill=125,
               note="6x Light Leather, 2x Coarse Thread (2320, "
                    "vendor-bought) -> item 4246, no focus needed"),
        Recipe(2167, "Dark Leather Boots", min_skill=126, max_skill=137,
               note="4x Medium Leather, 2x Fine Thread (2321, vendor-bought "
                    "- see craft_supply.REAGENTS), 1x Gray Dye (4340, "
                    "vendor-bought) -> item 2315, no focus needed"),
        Recipe(7135, "Dark Leather Pants", min_skill=138, max_skill=149,
               note="12x Medium Leather, 1x Gray Dye (4340, vendor-bought), "
                    "1x Fine Thread (2321, vendor-bought) -> item 5961, no "
                    "focus needed"),
        # spell 20649, creates item 4234 from 5x Medium Leather (2319).
        # Cross-checked: wowhead tooltip API (wotlk) + classicdb.ch spell
        # page, both agreeing on a single Medium Leather x5 reagent.
        Recipe(20649, "Heavy Leather", min_skill=150, max_skill=155,
               note="5x Medium Leather -> 1x Heavy Leather, recycle, "
                    "no focus needed"),
        Recipe(3818, "Cured Heavy Hide", min_skill=156, max_skill=165,
               note="1x Heavy Hide, 3x Salt (4289, vendor-bought - see "
                    "craft_supply.REAGENTS) -> item 4236, no focus needed"),
        Recipe(3780, "Heavy Armor Kit", min_skill=166, max_skill=180,
               note="5x Heavy Leather, 1x Fine Thread (2321, vendor-bought) "
                    "-> item 4265, no focus needed"),
        Recipe(7151, "Barbaric Shoulders", min_skill=181, max_skill=190,
               note="8x Heavy Leather, 1x Cured Heavy Hide (own-crafted), "
                    "2x Fine Thread (2321, vendor-bought) -> item 5964, no "
                    "focus needed"),
        Recipe(7156, "Guardian Gloves", min_skill=191, max_skill=200,
               note="4x Heavy Leather, 1x Cured Heavy Hide (own-crafted), "
                    "1x Silken Thread (4291, vendor-bought) -> item 5966, "
                    "no focus needed"),
        Recipe(10487, "Thick Armor Kit", min_skill=201, max_skill=205,
               note="5x Thick Leather, 1x Silken Thread (4291, "
                    "vendor-bought) -> item 8173, no focus needed"),
        Recipe(10507, "Nightscape Headband", min_skill=206, max_skill=235,
               note="5x Thick Leather, 2x Silken Thread (4291, "
                    "vendor-bought) -> item 8176, no focus needed"),
        Recipe(10548, "Nightscape Pants", min_skill=236, max_skill=250,
               note="14x Thick Leather, 4x Silken Thread (4291, "
                    "vendor-bought) -> item 8193, no focus needed"),
        Recipe(10558, "Nightscape Boots", min_skill=251, max_skill=260,
               note="16x Thick Leather, 2x Heavy Silken Thread (8343, "
                    "vendor-bought) -> item 8197, no focus needed; "
                    "trainer-verified learn floor is 235, see this table's "
                    "header comment for why 251 is used instead"),
        Recipe(19049, "Wicked Leather Gauntlets", min_skill=261, max_skill=290,
               note="8x Rugged Leather, 1x Black Dye (2325, vendor-bought), "
                    "1x Rune Thread (14341, vendor-bought - NOT item 24288, "
                    "a same-named item with zero npc_vendor rows) -> item "
                    "15083, no focus needed"),
        Recipe(19082, "Runic Leather Headband", min_skill=291, max_skill=300,
               note="14x Rugged Leather, 10x Runecloth (own Tailoring "
                    "output), 1x Rune Thread (14341, vendor-bought) -> item "
                    "15094, no focus needed; trainer-verified learn floor "
                    "is 270, see this table's header comment for why 291 "
                    "is used instead"),
    ),
}


def recipe_for(skill_id: int, skill_value: int):
    """The recipe worth casting for this skill at this value, or None.

    None means "nothing in RECIPES covers this profession or this bracket
    yet" - a caller must not invent a fallback, the same permission
    discipline `professions.assigned` holds for who may hold a trade at all.
    Picks the first bracket that contains `skill_value`; RECIPES entries for
    one skill are expected to be kept in ascending, non-overlapping bracket
    order (Engineering's table is the first with more than one entry, and
    `test_brackets_do_not_overlap_within_one_skill` holds it, and every
    profession after it, to that).
    """
    for recipe in RECIPES.get(skill_id, ()):
        if recipe.min_skill <= skill_value <= recipe.max_skill:
            return recipe
    return None


def craft_errand(name: str, skills: dict) -> int:
    """The `craft_spell` this character's roster row should carry, or 0.

    `skills` is one character's profession skills as `professions.plan`'s
    callers already build it (skill name -> value, private per the same rule
    council.py enforces). 0 means "no standing craft errand" - the schema's
    own sentinel for the column, so a caller can write this value straight
    through with no translation.

    CRAFTING FIRST, THEN SECONDARY - and the order is deliberate, not
    incidental. `professions.assigned(name)` names the one or two PRIMARY
    trades this specific character was given, which cost a slot and were
    chosen for them; a secondary skill (`professions.SECONDARY`) costs no
    slot and every character already holds all of them, so it is checked for
    EVERY name, not only whoever `assigned` names. A character with a live
    primary recipe keeps casting it; one with no primary recipe available
    (no RECIPES entry yet, or between brackets) falls through to whatever
    secondary bracket its First Aid/Cooking value is in, rather than sitting
    on job='craft' doing nothing while a free skill-up sits unclaimed.
    """
    for skill_name in professions.assigned(name):
        if skill_name not in professions.CRAFTING:
            continue
        value = skills.get(skill_name, 0)
        if not value:
            continue  # not learned yet - professions.py's trainer errand owns this
        recipe = recipe_for(SKILL_IDS[skill_name], value)
        if recipe:
            return recipe.spell_id
    for skill_name in sorted(professions.SECONDARY):
        value = skills.get(skill_name, 0)
        if not value:
            continue  # not learned yet - same permission discipline as above
        recipe = recipe_for(SKILL_IDS[skill_name], value)
        if recipe:
            return recipe.spell_id
    return 0
