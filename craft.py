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

    `focus` IS `Spell.dbc`'s OWN `RequiresSpellFocus`, AND IT IS THE ONE FACT
    THIS TABLE USED TO CARRY ONLY AS PROSE (infra#3738). Every entry's `note`
    has always said "no focus needed", and that claim is load-bearing -
    DriveCraft casts in place and does NOT walk anyone to a forge or an anvil,
    so a recipe that needs one sits refused on every poll for ever
    (SPELL_FAILED_REQUIRES_SPELL_FOCUS) rather than eventually succeeding. But
    a claim that lives only in free prose is a claim nothing checks, and
    infra#3738 was filed proposing to add exactly such a recipe on the
    strength of a spell id that turned out to name a different spell. So the
    number moved into the dataclass, where
    `test_no_recipe_requires_a_spell_focus` holds the WHOLE table to
    `focus == 0` on every pull request.

    The value is a `SpellFocusObject.dbc` id rather than a boolean, because
    the eventual fix is per-object rather than a flag: 1 is Anvil, 2 is Loom,
    3 is Forge (read out of the running worldserver's own
    SpellFocusObject.dbc, see the SMELTING comment below).

    THAT "UNTIL THEN" HAS ARRIVED FOR EXACTLY ONE OF THE THREE (infra#3748).
    `bridge._forge_once` now walks the leader to the nearest spawned Forge
    before a smelt is cast, so `focus = 3` is a value this system can honour
    and the Mining entries below carry it. Anvil and Loom still have no walk,
    so `focus = 1` or `focus = 2` remains exactly as refusable as every
    non-zero value used to be - see `FOCUS_AIMS` directly below, which is the
    machine-readable list of which focus ids something actually stands a
    character at, and the test that holds this field to it. Zero still means
    "castable anywhere", which is every entry but Mining's.
    """

    spell_id: int
    name: str
    min_skill: int
    max_skill: int
    note: str = ""
    repeatable: bool = True
    focus: int = 0


# WHICH SPELL FOCUS OBJECTS SOMETHING IN THIS REPO ACTUALLY WALKS TO
# (infra#3748). SpellFocusObject.dbc id -> the name of the pass that stands a
# character in it.
#
# THIS IS THE GUARD infra#3747 ASKED FOR, ONE TURN ON. That change added
# `Recipe.focus` and a test holding the WHOLE table to `focus == 0`, because at
# the time nothing anywhere could stand a character next to a focus object and
# a recipe that needed one would have sat refused on every twenty-second poll
# for ever. "Zero" was the right rule while the true answer was "none of them".
# It is the wrong rule now that the answer is "one of them", and widening it to
# "any non-zero value is fine" would be the wrong rule in the other direction -
# it would let infra#3617's Anvil-gated Blacksmithing recipes in, which still
# have no walk AND still need a Blacksmith Hammer equipped.
#
# So the test now holds every entry's `focus` to zero OR to a key of this dict,
# and a second test holds every key of this dict to a walk that really exists
# (tests/test_craft.py's SpellFocusTests). A focus id can only be added here by
# the change that adds its walk, which is what stops this becoming a list of
# intentions.
FOCUS_AIMS = {
    # 3 = Forge. `bridge._forge_once` reads the nearest spawned forge on the
    # smelter's own map out of `acore_world.gameobject` and writes its surveyed
    # position to `travel_npc` as `travel.forge_aim`'s `at:<map>:<x>,<y>,<z>`,
    # through the one sanctioned writer (`bridge._write_trade_errand`).
    3: "forge",
}


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
# ---------------------------------------------------------------------------
# MINING AND SMELTING ARE IN THIS TABLE NOW, AND THE FORGE IS WHY THEY WERE NOT
# (infra#3738 found the gap, infra#3747 proved the cause, infra#3748 shipped
# the walk; part of infra#3731).
#
# Everything from here to "WHAT THIS PASS ADDED" is infra#3747's investigation,
# kept intact because it is the expensive part and because two of its facts
# were wrong in ways worth recording. Read it as the argument for the walk, not
# as a reason the table is still empty.
#
# This is the gap that caps Grog's Engineering at skill 31. From that value on,
# every Engineering bracket above except the four plain blasting powders
# consumes a SMELTED BAR, and infra#3738 measured that Copper, Steel, Mithril
# and Thorium Bar have zero `npc_vendor` rows and no loot source anywhere on
# this world. Re-counted here and confirmed: Copper Bar (2840) has 0 vendor, 0
# creature-loot and 0 gameobject-loot rows. A bar is smelted from ore by the
# Mining skill, and nothing in this system smelts.
#
# THE EXACT COUNT, RECOUNTED RATHER THAN QUOTED. infra#3738 says "12 of the 19
# Engineering entries". The table above holds EIGHTEEN Engineering entries, not
# nineteen, and classifying each one's reagents against Spell.dbc gives ELEVEN
# that consume a bar directly: Handful of Copper Bolts, Arclight Spanner and
# Rough Copper Bomb (Copper Bar), Silver Contact (Silver), Bronze Tube
# (Bronze), Gyromatic Micro-Adjustor (Steel), Mithril Tube, Unstable Trigger
# and Mithril Casing (Mithril), Thorium Widget and Thorium Tube (Thorium).
#
# A TWELFTH IS BLOCKED TRANSITIVELY, which is where the issue's 12 comes from
# and is worth spelling out because it is the only one not obvious from its own
# reagent line: Hi-Explosive Bomb (12619) names no bar itself, but both of its
# crafted reagents - Mithril Casing and Unstable Trigger - are bar-gated, so it
# cannot be reached either. That leaves SIX brackets genuinely castable today
# (Rough, Coarse, Heavy, Solid and Dense Blasting Powder, plus Coarse Dynamite,
# which runs on Coarse Blasting Powder and Linen Cloth). The issue's own list of
# survivors names only the four plain powders and misses Rough Blasting Powder
# and Coarse Dynamite.
#
# So: 12 of 18 unreachable, 6 reachable, and the ceiling is real.
#
# infra#3738 PROPOSED A PLANNER-ONLY FIX AND IT WOULD NOT HAVE WORKED. Its
# words: "Smelt Copper is spell 2659 ... the same SPELL_EFFECT_CREATE_ITEM
# shape DriveCraft already handles - so this may be a planner change rather
# than a C++ one. Worth checking whether `craft_spell` can simply name 2659".
# It was checked, against the running worldserver's own `Spell.dbc`
# (/azerothcore/env/dist/data/dbc/Spell.dbc, md5-verified byte-identical to the
# copy the server loaded, 49839 records x 234 fields), with the parse proved
# first against infra#3689's known-good anchor: spell 2963 resolves to
# Reagent[0]=2589, ReagentCount[0]=2. Two things came back, and both of them
# kill the proposal:
#
#   SPELL 2659 IS NOT SMELT COPPER. It is SMELT BRONZE: 1x Copper Bar (2840)
#   plus 1x Tin Bar (3576) -> 1x Bronze Bar (2841). Naming it would have aimed
#   Grog at a recipe consuming the very bar he cannot make, which is the
#   ceiling one rung higher up rather than a way past it. Smelt Copper is
#   spell 2657 (1x Copper Ore 2770 -> 1x Copper Bar 2840). Recorded rather
#   than quietly corrected, because the failure mode is the lesson this table's
#   header already teaches twice: a spell id that "everyone knows" is still a
#   guess until the server's own DBC agrees.
#
#   EVERY SMELT SPELL IN THE GAME REQUIRES A FORGE. All twenty-odd of them,
#   read straight off Spell.dbc: `RequiresSpellFocus = 3`, and
#   SpellFocusObject.dbc resolves 3 to "Forge" (1 is Anvil, 2 is Loom). Smelt
#   Dark Iron wants focus 543 ("Black Forge") and Smelt Jagged Shards 1580
#   ("Malykriss Furnace"), which are worse, not better. There is no
#   forge-free smelt recipe at any skill value, so this is not a bracket
#   problem that a different pick could dodge.
#
# WHAT A FORGE ACTUALLY COSTS, MEASURED RATHER THAN ASSUMED. The requirement is
# proximity, not possession: `acore_world.gameobject_template` rows for the
# Forge object carry `type = 8` (GAMEOBJECT_TYPE_SPELL_FOCUS), `Data0 = 3` (the
# focus id CheckCast matches) and `Data1 = 10` (the radius, in yards). So a
# character must be standing within ten yards of a spawned forge at the moment
# of the cast.
#
# TWO CHEAP-LOOKING WAYS OUT WERE TRIED AND BOTH FAIL, which is why this is
# filed as a gap rather than shipped:
#
#   "THEY ALREADY STAND NEAR ONE." Very nearly true, and that is the trap. The
#   family camps in Gadgetzan, and forge spawn guid 17240 (entry 141838) sits
#   at (-7198.8, -3766.4, 9.2) on map 1. Measured against `characters`: Grug
#   9.02 yards, Grog 9.05, Og 10.01, Ugga 11.65. Two are inside the ten-yard
#   radius, one is on the boundary and one is outside, and those coordinates
#   are up to fifteen minutes stale (PlayerSaveInterval = 900000). Worse, the
#   playerbot AI wanders even on a standing job - the same fact recorded for
#   job='rest' elsewhere in this project - so a character parked at a forge
#   does not stay parked. Shipping on this would buy intermittent success that
#   looks like a flaky bug, which is strictly worse than an honest refusal.
#
#   "AIM THEM AT A REPAIR NPC." Blacksmith and repair vendors do tend to stand
#   at forges, `repair` is already a keyword in `travel.ROLES`, and in
#   Gadgetzan it would even work: Krinkle Goodsteel (entry 5411, npcflag 4227,
#   UNIT_NPC_FLAG_REPAIR set) stands 3.8 yards from that forge. It does not
#   generalise. Counted across both continents: of 947 repair-flagged creature
#   spawns on maps 0 and 1, exactly 45 stand within ten yards of a forge. That
#   is 4.8%, so the keyword resolves to the wrong place nineteen times in
#   twenty. `travel.ROLES` is also a test-enforced mirror of mod-overseer's own
#   `TravelRoles()`, so a new keyword cannot be added from this side at all.
#
# THE ROUTE THAT DOES WORK, AND IT IS SMALLER THAN infra#3617 CONCLUDED. That
# issue investigated the sibling question for Blacksmithing's anvil and
# concluded that walking to a focus object "means indexing GameObject spawns
# the same way creatures are indexed today - a new second index". That is not
# so, and the counter-example is already shipped: `_guild_bank_once` walks the
# leader to a Guild Vault, which is a GAMEOBJECT and not a creature, by
# querying `acore_world.gameobject JOIN gameobject_template` for the nearest
# spawn on the character's own map and handing its position to
# `travel.ground_aim`, which produces the `at:<map>:<x>,<y>,<z>` form that
# `ResolveTravelTarget` already accepts. That path never touches the
# creature-only `_travelSpawns` index at all. A forge aim is the same shape
# with `gt.type = 8 AND gt.Data0 = 3`, and it fits the column: the Gadgetzan
# forge renders as `at:1:-7198.8,-3766.4,9.2`, 24 of the 32 characters
# `travel_npc` allows.
#
# AND SMELTING IS THE ONE CASE THAT NEEDS ONLY THAT HALF. infra#3617 left the
# forge work parked because every Blacksmithing recipe behind it ALSO needs a
# Blacksmith Hammer equipped (`EquippedItemClass`), which is an unsolved
# "swap a tool in and put the weapon back" problem, and it noted that the
# travel half "could ship alone ... for Anvil-only recipes if any existed
# without a tool requirement (none do here)". Smelting is that case. Every
# smelt spell read above carries `EquippedItemClass = -1`: no tool, no
# gear-swap, nothing but the ten yards. So the forge aim unblocks the whole
# smelting chain on its own, with the hammer question still parked.
#
# ---------------------------------------------------------------------------
# WHAT THIS PASS ADDED, AND THE TWO THINGS ABOVE THAT IT HAD TO CORRECT FIRST
# (infra#3748).
#
# THE DBC FIELD INDEX ABOVE WAS READ FROM THE WRONG COLUMN, AND THE ANSWER WAS
# RIGHT ANYWAY. Re-deriving the smelt facts from the same md5-verified
# `Spell.dbc` (543b9fe61355b6a77a01714d52fea2e5, matched against the running
# worldserver pod's own `md5sum` on 2026-09-13) reproduced infra#3747's
# conclusion only after the field offsets were fixed: `RequiresSpellFocus` is
# field 18 and `EquippedItemClass` is field 68 in the 234-field 3.3.5a layout,
# NOT 23 and 69. Read at 23, every smelt spell answers `focus = 0` and only
# ELEVEN spells in the whole 49,839-record file carry any value at all - which
# is the tell, because the real field is non-zero for 647 Anvil-gated spells
# alone. The anchor infra#3747 used (spell 2963 -> Reagent[0]=2589,
# ReagentCount[0]=2) proves Reagent/ReagentCount/EffectItemType/SpellName and
# does NOT touch focus or tool, so it passes either way. Recorded because an
# anchor only proves the fields it reads, and the next reader re-deriving this
# will hit the same trap.
#
# WITH THE RIGHT FIELDS, infra#3747 AND infra#3748 ARE EXACTLY RIGHT:
#
#   29 spells are named "Smelt ..."; 24 of them create an item; all 24 require
#   a focus and NOT ONE has `focus = 0`. 22 of the 24 need Forge (focus 3); the
#   other two are Smelt Dark Iron (543, "Black Forge") and Smelt Jagged Shards
#   (1580, "Malykriss Furnace"). Every one of the 24 reads
#   `EquippedItemClass = -1`: no tool, which is what makes smelting the
#   forge-only case infra#3617 said did not exist.
#
# THE FOCUS RADIUS IS NOT ALWAYS TEN, which infra#3748's fact table states as a
# flat value and which matters because the travel drive lands an `at:` aim
# within five yards, not on top of the point. Counted live:
#
#     SELECT Data1, COUNT(*) FROM gameobject_template
#      WHERE type = 8 AND Data0 = 3 GROUP BY Data1;
#     -> 10:136   8:4   12:3   15:2   30:2   4:1   5:1      (149 templates)
#
# So thirteen forge templates carry a radius other than ten and two of them are
# at or inside the arrival tolerance. `travel.forge_aim` refuses those with a
# sentence and `_FORGE_SQL` does not offer them as candidates - see
# travel.ARRIVED_POSITION_YARDS for the whole argument.
#
# AND THE "THEY ALREADY STAND NEAR ONE" MEASUREMENT HAS EXPIRED, which is worth
# knowing before anyone re-runs infra#3747's coin-flip argument. That pass
# measured the family 9.02 to 11.65 yards from the Gadgetzan forge and
# concluded a dry run there would prove nothing. Measured again 2026-09-13
# 22:21 against a snapshot 25 seconds old: the family is SPLIT, Grug and Ugga
# 178 yards from that same forge and Bork, Og and Grog 1,435 to 1,659 yards
# from theirs. Nobody is inside any focus. The walk is not a formality.
#
# ONLY SMELT COPPER IS SHIPPED, AND `SkillLineAbility.dbc` IS WHY. Every smelt
# ability sits on skill line 186 (Mining) with `MinSkillLineRank = 1`, but the
# ninth field - AcquireMethod - separates them:
#
#   spell  name              acquire  yellow  grey   reagent
#   2657   Smelt Copper       1        25      70    1x Copper Ore (2770)
#   3304   Smelt Tin          0        65      75    1x Tin Ore (2771)
#   2658   Smelt Silver       0       115     130    1x Silver Ore (2775)
#   2659   Smelt Bronze       0        65     115    1x Copper Bar + 1x Tin Bar
#   3307   Smelt Iron         0       130     160    1x Iron Ore (2772)
#   3308   Smelt Gold         0       170     185    1x Gold Ore (2776)
#   3569   Smelt Steel        0       165     165    1x Iron Bar + 1x Coal
#   10097  Smelt Mithril      0       175     230    1x Mithril Ore (3858)
#   10098  Smelt Truesilver   0       250     290    1x Truesilver Ore (7911)
#   16153  Smelt Thorium      0       250     290    1x Thorium Ore (10620)
#
# `AcquireMethod = 1` means the ability is granted with the skill line itself.
# Smelt Copper is the only smelt in the game that carries it, and the live
# `trainer_spell` table agrees from the other side: the other nine all have
# trainer rows (ReqSkillLine 186, ReqSkillRank 65 to 230) and 2657 has NONE,
# because nobody ever needs to be taught it. So Smelt Copper is the one smelt
# this module may name under its own "never name a spell the character does not
# yet hold" rule - the same rule that keeps First Aid to the two bandages
# Apprentice teaches together. DriveCraft's `!HasSpell` branch drops a recipe a
# character does not hold, with a WARN calling it "a planner bug", so naming a
# trainer-taught smelt would be loud and wrong rather than quiet and wrong.
#
# THE OTHER NINE, AND WHY EACH IS DEFERRED RATHER THAN FORGOTTEN:
#
#   2659 Smelt Bronze and 3569 Smelt Steel consume TWO smelted bars each
#   (Copper+Tin, Iron+Coal). A character holds ONE `craft_spell`, so it can
#   never stand up two producers at once - the identical "this module can only
#   stand one recipe up per skill window" argument that leaves the 151-174
#   Engineering bracket empty above. They are not a trainer problem and adding
#   a Mining trainer visit would not unblock them.
#
#   3304 Tin, 2658 Silver, 3307 Iron, 3308 Gold, 10097 Mithril, 10098
#   Truesilver, 16153 Thorium are all `AcquireMethod = 0`: a Mining trainer
#   teaches them and nothing in this repo sends anybody to a Mining trainer for
#   an individual recipe (`professions.py`'s errand opens a TRADE, it does not
#   buy a rank's worth of recipes). They become addable the day that exists,
#   and their brackets are already measured in the table above so that pass
#   does not have to re-derive them.
#
# WHERE MINING SITS RELATIVE TO CRAFTING AND GATHERING, since that was
# infra#3748's own open question. Mining STAYS in `professions.GATHERING` and
# nothing about `professions.plan` changes: it is gathered from nodes, it costs
# a primary slot as a gathering trade, and the family's two miners hold it for
# that reason. What changes is only that `RECIPES` - which is keyed by SKILL
# ID, not by trade class - gains a Mining bracket, and a SECOND reader
# (`smelt_errand` below) answers for it. `craft_errand` is untouched and still
# considers `professions.CRAFTING` then `professions.SECONDARY` only, so a
# smelt can never displace a crafting recipe by accident; which of the two a
# character should actually be casting is a question about held ore and held
# bars, and that lives in `craft_rhythm.errand` where the inventory counts are.
# ---------------------------------------------------------------------------
# COLOUR BANDS: EVERY BRACKET EDGE IN THIS TABLE IS NOW THE REALM'S OWN NUMBER,
# AND TEN OF THEM WERE NOT (this pass, part of infra#3731).
#
# Until now a bracket edge came from a leveling guide's stated range, shifted by
# a point where two entries collided. That is the right source for the ROUTE -
# which recipe, in what order - and it is the WRONG source for the edges, because
# an edge is a fact about this worldserver's own `SkillLineAbility.dbc` and a
# guide cannot know it. Every entry was re-derived against the md5-verified DBCs
# (`Spell.dbc` 543b9fe61355b6a77a01714d52fea2e5, `SkillLineAbility.dbc`
# d8c11abfcfe70596cb9068c0e97a1d9a, both matched against the running
# worldserver pod's own `md5sum`), with this table's two required anchors
# asserted before any new fact was read: 2963 -> Reagent[0]=2589,
# ReagentCount[0]=2, and 2657 -> RequiresSpellFocus=3.
#
# TWO RULES, AND TEN ENTRIES BROKE ONE OF THEM:
#
#   max_skill < TrivialSkillLineRankHigh (grey). At or past grey the core rolls
#   NO skill-up, so a bracket that reaches its own grey value spends its last
#   points casting for free. Seven entries did: Bolt of Silk Cloth, Bolt of
#   Mageweave, Bolt of Runecloth, Heavy Blasting Powder, Dense Blasting Powder,
#   Solid Grinding Stone, Dense Sharpening Stone - and Bolt of Linen Cloth,
#   which ran to 60 against a grey of FIFTY.
#
#   min_skill >= MinSkillLineRank (the learn floor). Below it the character
#   cannot hold the spell at all, so DriveCraft's `!HasSpell` branch drops the
#   errand and logs "a planner bug" on every poll. Two entries did: Coarse
#   Sharpening Stone (bracket from 65, floor 75) and Lesser Healing Potion
#   (bracket from 60, floor 80).
#
# THIS IS THE ANSWER TO "THREE CHARACTERS HAVE MADE NO PROGRESS", and it is not
# the one the table's size suggests. The table is not short of recipes - it
# holds sixty-one across eight skills and covers 1-75 continuously for every
# trade the family owns. It was short of CORRECT EDGES, and the three stalls
# line up exactly with the three broken ones:
#
#   Og    Tailoring 50      grey 50    casting Bolt of Linen Cloth for nothing
#   Ugga  Alchemy 14        floor 80   walls at 60, twenty points early
#   Grug  Blacksmithing 1   floor 75   walls at 65, ten points early
#
# A wrong edge is invisible in a way a missing recipe is not: `recipe_for`
# answers, `craft_errand` writes a spell id, DriveCraft casts it, and the item
# even appears in the bag. Only the skill never moves.
#
# COARSE SHARPENING STONE IS REMOVED RATHER THAN RE-BRACKETED, which is the one
# judgement call here. Its realm learn floor is 75 and its grey is 80, so its
# honest bracket would be 75-79 - a window Coarse Grinding Stone already owns
# with a grey of 100 and a floor of 1. Keeping it would mean handing Grug the
# strictly worse of two recipes for five points. Rough Grinding Stone absorbs
# 65-74 instead (its own grey is 85, so it was never finished at 64), and the
# ladder stays continuous. The same "remove rather than ship unreachable"
# precedent Heavy Linen Bandage already set above.
#
# `tests/test_craft.py`'s `MEASURED_BANDS` is the checked-in projection that
# keeps this true, exactly as `MEASURED_FOCUS` does for the focus field, and
# `tools/spell_bands_from_dbc.py` regenerates it in one command.
# ---------------------------------------------------------------------------
# WHERE TWO RECIPES ARE EQUALLY GOOD FOR SKILL, THE ONE A RAID EATS WINS
# (this pass, for the operator's "a constant supply of crafted items for raids
# ... max buffs always in raids"). FOUR BRACKETS CHANGED; see raidcraft.py.
#
# THIS TABLE HAS ONLY EVER ASKED ONE QUESTION - which recipe raises this skill
# fastest at this value - and it has never asked what falls out of the cast.
# For most of its sixty-one entries that is the right and only question: there
# is one sane recipe at a given value and the item is whatever it is. But at a
# handful of values the realm offers TWO recipes with identical or near
# identical colour bands, one producing vendor trash and one producing
# something forty people drink on a raid night, and this table has been
# choosing between them silently and by accident.
#
# IT IS A CHOICE MADE WHEN THE TABLE IS WRITTEN, NOT WHEN A CHARACTER CASTS,
# and that is forced rather than preferred. `recipe_for` returns the FIRST
# bracket containing a skill value and `test_brackets_do_not_overlap_within_
# one_skill` holds every skill line to exactly one recipe per point - so a
# character never has two candidates at one value and there is no runtime
# choice to make. `raidcraft.preferred` plus
# `test_raidcraft.ThePreferenceIsTakenWhereItIsFree` is what makes the
# authoring-time choice checkable instead of accidental.
#
# THE RULE, AND EVERY CLAUSE OF IT EARNS ITS PLACE:
#
#   LEGAL. `floor <= value < grey`. Below the realm's own rank the character
#   cannot hold the spell; at or past grey the core rolls no skill-up, so
#   naming it there would trade a skill point for an item, which is a
#   different decision and not this table's.
#
#   NOT WORSE FOR SKILL. The consumable's `yellow` must be >= the incumbent's.
#   A cast below its yellow value is ORANGE and rolls a skill-up most
#   reliably, so a higher yellow is at least as good at EVERY value in the
#   bracket - which is what makes this comparable without per-value colour
#   arithmetic the core does not expose. This clause is why Elixir of Fortitude
#   does NOT take 185-209 from Elixir of Agility (195 against 205): the raid
#   item is there for the taking and taking it would cost skill.
#
#   TRAINER-TAUGHT OR AUTO-LEARNED, NEVER PATTERN-TAUGHT. This is the clause
#   that keeps the table honest, and without it the rule would have demanded
#   four more brackets this family can never cast. THIRTEEN of the twenty-two
#   raid consumables on this realm are taught by a `Recipe:`/`Formula:`/
#   `Plans:` ITEM and have no `trainer_spell` row at all - including all four
#   flasks, every Greater Protection Potion, Major Mana Potion, both weapon
#   oils and Elemental Sharpening Stone. Nothing in this repo buys or learns
#   from a pattern item (a concurrent change is building exactly that), so
#   naming one here would buy a `craft_spell` DriveCraft drops with a WARN
#   calling it a planner bug on every twenty-second poll - the identical trap
#   Heavy Linen Bandage set for First Aid and that this table already paid for
#   once. Elixir of the Mongoose (17571) at 280-284 is the bracket that rule
#   costs, and it is named here so the next reader knows it was measured and
#   declined rather than missed.
#
# THE FOUR THAT PASSED ALL THREE CLAUSES:
#
#   175-184  Elixir of Fortitude (3450) takes ten points off Greater Healing
#            Potion, which had 155-184. Better on BOTH axes: 3450's yellow is
#            195 against 7181's 175, so those ten points move from YELLOW to
#            ORANGE, and the output is a +120 health hour-long buff every one
#            of forty raiders drinks instead of a potion that vendors.
#   240-264  Elixir of Greater Agility (11467) takes twenty-five points off
#            Elixir of Detect Undead, which had 230-264. yellow 255 against
#            245, and Elixir of Detect Undead is the purest vendor trash in
#            this table - it detects undead.
#   275-300  Major Healing Potion (17556) reaches down ten points into
#            Superior Mana Potion's old 265-284. yellow 290 against 275, and
#            17556 was ALREADY this ladder's top bracket - this is the same
#            recipe starting at the rank the realm actually teaches it (275,
#            `trainer_spell`) instead of ten points late.
#   200-209  Solid Sharpening Stone (9918) REPLACES Solid Grinding Stone
#            (9920) outright rather than splitting with it. Identical skill
#            line, identical rank 200, identical yellow 200 and grey 210,
#            identical reagent - and 9918 eats ONE Solid Stone per cast where
#            9920 eats FOUR, for a +6 weapon damage buff instead of an armour
#            reagent nothing in this table consumes. There is no value at
#            which 9920 was the better pick; it was simply the one a leveling
#            guide happened to list.
#
# AND THE ONE THAT WAS ALREADY RIGHT, WHICH IS WHY THIS IS A GUARD AND NOT A
# REWRITE. Dense Sharpening Stone (16641) has held Blacksmithing 250-259 since
# that bracket was written, over its twin Dense Weightstone (16640) - same
# rank 250, same yellow 255, same grey 260, same one Dense Stone. Somebody
# picked the raid consumable and nothing anywhere recorded that they had, so
# the next edit could have flipped it for free. It is pinned by name now.
#
# ---------------------------------------------------------------------------
# A MEASUREMENT THE ABOVE FORCED, AND IT IS ABOUT THIS WHOLE TABLE RATHER THAN
# ABOUT THE FOUR BRACKETS: NINE OF THESE SIXTY-THREE RECIPES ARE AUTO-LEARNED
# AND FIFTY-FOUR ARE TAUGHT.
#
# The First Aid and Mining comments above both state a rule - "never name a
# spell the character does not yet hold" - and both enforce it by keeping to
# `SkillLineAbility.AcquireMethod = 1` entries (Linen Bandage, Smelt Copper).
# Before adding a trainer-taught recipe to Alchemy and Blacksmithing this pass
# checked whether that rule was being kept for the PRIMARY trades too. It is
# not, and it never has been. Every entry in this table was read against the
# same md5-verified `SkillLineAbility.dbc`, keeping only the rows this family's
# five classes can match. All nine auto-learned entries carry ClassMask 0:
#
#   2963 Bolt of Linen Cloth        3275 Linen Bandage
#   3918 Rough Blasting Powder      2657 Smelt Copper
#   2330 Minor Healing Potion       2660 Rough Sharpening Stone
#   2881 Light Leather              2152 Light Armor Kit
#   9058 Handstitched Leather Cloak
#
# They are exactly the FIRST rung of each ladder - which is what an auto-learn
# is for - and every rung above the first, on every trade, is AcquireMethod 0.
# So Lesser Healing Potion at Alchemy 80, Bolt of Woolen Cloth at Tailoring 68
# and Coarse Grinding Stone at Blacksmithing 75 have all been named here from
# the beginning and are all taught. What makes that work at all is the fact
# this module's own infra#3695 comment already establishes from the other side:
# these are PLAYERBOTS, and mod-playerbots grants profession recipes at init,
# which is why `character_spell` is empty for recipes the family has been
# WATCHED casting. The table has always relied on that grant, silently.
#
# THE TWO NEW TRAINER ENTRIES ARE THEREFORE NO NEW RISK, AND THAT IS THE POINT
# OF WRITING THIS DOWN rather than a reason to relax. If the grant turns out
# not to reach rank 175 recipes, Elixir of Fortitude fails EXACTLY as Lesser
# Healing Potion at 80 would - DriveCraft's `!HasSpell` branch drops the errand
# with a WARN calling it a planner bug - and the fix is the same one for both,
# which is an Alchemy trainer visit `professions.py` already knows how to make.
# What would have been a NEW risk is a pattern-taught recipe, which no grant
# and no trainer can supply, and that is the clause `preferred` refuses on.
RECIPES: dict = {
    SKILL_IDS["tailoring"]: (
        Recipe(
            2963,
            "Bolt of Linen Cloth",
            min_skill=1,
            max_skill=49,
            note="2x Linen Cloth (2589) -> 1x Bolt of Linen Cloth (2996), "
            "no focus needed. NOT spell 3910 - that id is 'Tailoring', "
            "the Expert rank profession spell, which creates nothing; "
            "see this table's own header comment for how that went "
            "unnoticed (infra#3689). max_skill was 60 against a "
            "TrivialSkillLineRankHigh of 50 - see the COLOUR BANDS "
            "block above; Og sat at exactly 50 casting this for free",
        ),
        Recipe(
            8776,
            "Linen Belt",
            min_skill=50,
            max_skill=67,
            note="1x Bolt of Linen Cloth (2996), 1x Coarse Thread (2320, "
            "vendor-bought) -> 1x Linen Belt (item 7026), no focus "
            "needed. min_skill was 61; MinSkillLineRank is 1 and "
            "TrivialSkillLineRankLow is 50, so 50 is where this stops "
            "being a guess and starts being the yellow band",
        ),
        Recipe(
            2964,
            "Bolt of Woolen Cloth",
            min_skill=68,
            max_skill=100,
            note="3x Wool Cloth -> 1x Bolt of Woolen Cloth, no focus "
            "needed; min_skill shifted from the guide's 61 to make "
            "room for Linen Belt directly above, see this table's "
            "own header comment",
        ),
        Recipe(
            3839,
            "Bolt of Silk Cloth",
            min_skill=125,
            max_skill=144,
            note="4x Silk Cloth -> 1x Bolt of Silk Cloth, no focus needed; "
            "max_skill was 145, its own grey value",
        ),
        Recipe(
            3865,
            "Bolt of Mageweave",
            min_skill=175,
            max_skill=184,
            note="4x Mageweave Cloth -> 1x Bolt of Mageweave, no focus "
            "needed; FOUR, not the five an earlier pass wrote - "
            "Spell.dbc, see this table's header comment; max_skill "
            "was 185, its own grey value",
        ),
        Recipe(
            18401,
            "Bolt of Runecloth",
            min_skill=250,
            max_skill=259,
            note="4x Runecloth -> 1x Bolt of Runecloth, no focus needed; "
            "FOUR, not the five an earlier pass wrote - Spell.dbc, "
            "see this table's header comment; max_skill was 260, its "
            "own grey value",
        ),
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
    # ONLY ONE ENTRY, AND THE SECOND ONE WAS REMOVED RATHER THAN RE-BRACKETED
    # (infra#3614). An earlier pass shipped Linen Bandage 1-39 and Heavy Linen
    # Bandage 40-74 on the belief that both are "taught TOGETHER the moment
    # Apprentice First Aid is learned". `SkillLineAbility.dbc`, pulled from the
    # running worldserver and parsed with the anchor this table's header
    # requires (2963 -> Reagent[0]=2589, ReagentCount[0]=2), says otherwise:
    #
    #   3275 Linen Bandage        skill 129  req 1   yellow 30  grey 60
    #                             AcquireMethod 1 (auto-learn)  ClassMask 0
    #   3276 Heavy Linen Bandage  skill 129  req 1   yellow 50  grey 100
    #                             AcquireMethod 0 (TRAINER)     ClassMask 0x5DF
    #                             skill 129  req 40  yellow 50  grey 100
    #                             AcquireMethod 1 (auto-learn)  ClassMask 0x20
    #
    # ClassMask 0x20 is 32, which is DEATH KNIGHT AND NOTHING ELSE, and 0x5DF
    # is every other class - so the row that grants Heavy Linen Bandage for
    # free is the one row this family can never match. Live: Grug is a Warrior,
    # Grog a Paladin, Bork a Rogue, Og a Mage, Ugga a Priest (acore_characters,
    # 2026-09-13). For all five, 3276 is `trainer_spell` at ReqSkillRank 40 for
    # 100 copper - and the nearest Alliance-usable First Aid trainer is 15,513
    # yards away across an ocean `ResolveTravelTarget` will not cross
    # (infra#3732). Naming it here bought a `craft_spell` DriveCraft drops as a
    # planner bug the moment the bracket is entered, so First Aid stalled dead
    # at 39 with nothing saying why.
    #
    # THE BRACKET WAS ALSO SHORT BY TWENTY POINTS. 3275's own grey value is 60,
    # not 40; 40 was only ever where the (unreachable) Heavy Linen Bandage was
    # to take over. With 3276 gone, Linen Bandage runs to 59 - its last
    # skill-granting value - and First Aid's headroom goes from 0 to 58 points
    # with no trainer, no purchase, no spell focus and no C++ change. That is
    # the whole of the reachable First Aid progression today; 60-75 needs the
    # trainer, which infra#3614 owns and mod-overseer#454 unblocks.
    #
    # WHY 3275 IS TREATED AS HELD WHEN `character_spell` HAS NO ROW FOR IT, and
    # this is the reading infra#3732 got backwards, so the control matters.
    # That PR concluded "auto-learn has never fired on this realm" from 0 of
    # 1175 First Aid holders having 3275 while 1008 have 3276, and inferred the
    # family therefore knows no bandage recipe at all. The same query run
    # against two spells this repo has WATCHED BEING CAST falsifies it:
    #
    #   2963 Bolt of Linen Cloth   AcquireMethod 1   0 rows of 457 tailors
    #   2330 Minor Healing Potion  AcquireMethod 1   0 rows of 950 alchemists
    #
    # Og cast 2963 and Ugga cast 2330 seven times on 2026-09-13, both logged by
    # mod-overseer, both with zero rows in `character_spell` - see this
    # module's own infra#3695 comment above. So AcquireMethod 1 spells are
    # simply never written to that table (`Player::_SaveSpells` skips an
    # UNCHANGED spell), for anybody, ever; their absence is the save gap and
    # not evidence. AcquireMethod 0 spells persist perfectly - 1008 of 1008
    # characters at First Aid 45 or above hold 3276, with no exceptions - which
    # is why 3276's absence for exactly the five family members at 1/75 IS
    # real. The two classes of spell need opposite readings, and 37836 being
    # present proves nothing about 3275: 37836 is AcquireMethod 0 and is held
    # by all 1013 bots identically.
    #
    # Reagent verified the same way: 1x Linen Cloth (2589) -> 1x Linen Bandage
    # (item 1251), RequiresSpellFocus 0.
    SKILL_IDS["first aid"]: (
        Recipe(
            3275,
            "Linen Bandage",
            min_skill=1,
            max_skill=59,
            note="1x Linen Cloth (2589) -> 1x Linen Bandage (item 1251), "
            "no focus needed. Auto-learned with Apprentice First Aid "
            "for every class (SkillLineAbility AcquireMethod 1, "
            "ClassMask 0); grey at 60, so 59 is the last value it can "
            "grant a point at. NOT 39 - that was Heavy Linen Bandage's "
            "old hand-off, and 3276 is a trainer purchase for every "
            "class but Death Knight",
        ),
    ),
    # COOKING (infra#2757's Cooking/First Aid slice) - also SECONDARY, same
    # reasoning as First Aid above: every one of the five holds it at 1/75
    # already (character_skills skill 185, verified live 2026-09-12).
    #
    # COOKING HAS NO ENTRY AT ALL, AND THE ONE IT HAD WAS INERT (infra#3614).
    # Charred Wolf Meat (2538) shipped here reading "taught with Apprentice
    # Cooking", which is true - AcquireMethod 1, ClassMask 0, req 1. What it
    # did not say, because nothing checked, is that `Spell.dbc` gives it
    # `RequiresSpellFocus = 4`, and `SpellFocusObject.dbc` resolves 4 to
    # "Cooking Fire". DriveCraft casts in place and walks nobody anywhere, so
    # CheckCast refused it with SPELL_FAILED_REQUIRES_SPELL_FOCUS on every poll
    # and logged a bare numeric SpellCastResult at INFO - the exact silent
    # failure `Recipe.focus` was added to prevent (infra#3747), which it did
    # not catch because the entry predates the field and defaulted to 0.
    #
    # IT IS NOT ONE RECIPE, IT IS THE WHOLE SKILL LINE. All 181 abilities on
    # skill 185 were read out of `SkillLineAbility.dbc` and joined to
    # `Spell.dbc`. Every single one that creates an item and is reachable below
    # the family's 75 cap carries `RequiresSpellFocus = 4`. The only focus-free
    # rows are the six "Cooking" rank spells (which create nothing), spell 818,
    # and three recipes whose yellow values are 100, 350 and 375 - far above 75
    # and none of them auto-learned. There is no cooking-without-a-fire bracket
    # to pick instead, at any skill value this family can reach.
    #
    # SO SPICE BREAD IS NOT THE WAY IN EITHER, and it was specifically proposed
    # as one. infra#3732 named 37836 "the cheapest real point of secondary
    # progress available" on the strength of the family already owning it. They
    # do own it - it is the one secondary recipe `character_spell` records for
    # all five, because it is AcquireMethod 0. But 37836 is
    # `RequiresSpellFocus = 4` as well, and its bracket is yellow 30 / grey 40,
    # which is WORSE than the Charred Wolf Meat it would replace (yellow 45 /
    # grey 85). Adding it would have bought a second inert entry with a shorter
    # ladder. `test_no_cooking_recipe_needs_a_fire` names its id so the
    # proposal cannot land again without the drive that makes it castable.
    #
    # THE FIX IS SMALL AND IT IS NOT THIS TABLE'S. Unlike the Forge (focus 3),
    # which is a world spawn a character must be walked to, a Cooking Fire is
    # something the caster CONJURES WHERE IT STANDS: spell 818 "Basic Campfire"
    # is on skill 185 at req 1, AcquireMethod 1, ClassMask 0, needs no reagent
    # and no focus of its own, and summons gameobject 29784 - live in
    # `acore_world.gameobject_template` as `type = 8`
    # (GAMEOBJECT_TYPE_SPELL_FOCUS), `Data0 = 4` (Cooking Fire), `Data1 = 10`
    # (radius, yards). The caster is standing at the centre of its own ten-yard
    # radius, so no travel, no gameobject index and no proximity race is
    # involved - the whole of what Cooking needs is for something to cast 818
    # before the recipe and let the fire stand. That is one ordered pair of
    # casts in DriveCraft, filed separately rather than faked from here by
    # naming a spell that cannot go off.
    #
    # WHAT DOES NOT BLOCK IT, recorded so the next reader does not re-derive
    # it: the reagents are fine. 1x Stringy Wolf Meat (2672) -> 1x Charred Wolf
    # Meat (2679) and 1x Chunk of Boar Meat (769) -> Roasted Boar Meat (2681)
    # are both ordinary beast drops at the family's level, both AcquireMethod 1
    # ClassMask 0, both yellow 45 / grey 85. The moment a fire can be lit,
    # Cooking is a 44-point ladder with no trainer and no purchase.
    SKILL_IDS["cooking"]: (),
    # ELEVEN OF THESE EIGHTEEN NEED AN ANVIL, AND UNTIL NOW EVERY ONE OF THEM
    # SAID IT DID NOT (infra#3760, corrected here as part of infra#3748).
    #
    # `Spell.dbc` gives each of the eleven marked `focus=1` below
    # `RequiresSpellFocus = 1`, which `SpellFocusObject.dbc` resolves to Anvil.
    # Each declared `focus=0` for its whole life, and the test that was supposed
    # to catch that compared `recipe.focus` against 0 while `Recipe.focus`
    # DEFAULTS to 0 - it compared the declared field against itself and could
    # never fail. See tests/test_craft.py's `MEASURED_FOCUS`, which is the
    # projection of the server's own answer that replaces it.
    #
    # NOTHING IS REMOVED HERE AND NOTHING IS UNBLOCKED HERE. Correcting the
    # field makes the table HONEST - `focus_for` now tells the truth about these
    # eleven, `FOCUS_AIMS` has no anvil walk, and the test below pins them as a
    # named, counted debt instead of eleven silent lies. Grog's Engineering
    # therefore still stops at skill 31, for a reason the table now states.
    #
    # AND infra#3617'S HAMMER IS NOT WHY, WHICH IS THE EXPENSIVE PART OF THIS
    # NOTE. That issue parked the whole anvil question on a second blocker -
    # "every 'worn' Blacksmithing recipe requires an Anvil PLUS an equipped
    # Blacksmith Hammer (SpellInfo::EquippedItemClass)" - and called the
    # swap-a-tool-in-and-put-the-weapon-back problem "a new class of problem,
    # not a known pattern". Counted against the same md5-verified `Spell.dbc`:
    # of the 647 spells in the entire file that carry `RequiresSpellFocus = 1`,
    # 645 read `EquippedItemClass = -1`. The only two that need a tool are
    # Socket Bracer (55628) and Socket Gloves (55641), and they want class 4
    # (armour), not a hammer. Every one of the eleven below reads -1, and so
    # does every one of the thirteen Blacksmithing recipes infra#3617 names by
    # hand - Runed Copper Belt (2666), Silver Rod (7818), Rough Bronze Leggings
    # (2668), Patterned Bronze Bracers (2672), Golden Rod (14379), Green Iron
    # Bracers (3501), Green Iron Leggings (3506), Golden Scale Bracers (7223),
    # Heavy Mithril Gauntlet (9928), Steel Plate Helm (9935), Mithril Spurs
    # (9964), Imperial Plate Bracers (16649), Imperial Plate Boots (16657). So
    # the anvil half needs only a walk, exactly as the forge half did, and the
    # tool half is a blocker that does not exist. That is infra#3617's and
    # infra#3760's to act on, not this change's - but it is written down here
    # so nobody pays for the measurement twice.
    #
    # THE WALK IS ALSO NEARLY FREE WHEN IT COMES. Counted live against
    # `acore_world.gameobject` on 2026-09-13: of the 83 Forge spawns on maps 0
    # and 1, 71 have an Anvil within ten yards and 39 within five. The Gadgetzan
    # forge the family lives beside (spawn of entry 141838) has Anvil 141839
    # 2.69 yards away, radius 10 - so the forge aim this change ships already
    # stands a character inside an anvil's focus there, and the anvil work is a
    # table correction plus a ranking preference rather than a second journey.
    SKILL_IDS["engineering"]: (
        Recipe(
            3918,
            "Rough Blasting Powder",
            min_skill=1,
            max_skill=30,
            note="1x Rough Stone -> 1x Rough Blasting Powder (item 4357)",
        ),
        Recipe(
            3922,
            "Handful of Copper Bolts",
            min_skill=31,
            max_skill=50,
            focus=1,
            note="1x Copper Bar -> 1x Handful of Copper Bolts (item 4359)",
        ),
        Recipe(
            7430,
            "Arclight Spanner",
            min_skill=51,
            max_skill=51,
            focus=1,
            repeatable=False,
            note="TOOL, craft once - 6x Copper Bar -> 1x Arclight Spanner "
            "(item 6219). Not Unique/Unique-Equipped - verified "
            "against wowhead+classicdb tooltip data, not assumed - so "
            "nothing in the core refuses a second cast; the "
            "single-point bracket is what stops this module from "
            "recasting it, not an item flag",
        ),
        Recipe(
            3923,
            "Rough Copper Bomb",
            min_skill=52,
            max_skill=75,
            focus=1,
            note="1x Copper Bar, 1x Handful of Copper Bolts, 2x Rough "
            "Blasting Powder, 1x Linen Cloth -> 1x Rough Copper Bomb "
            "(item 4360)",
        ),
        Recipe(
            3929,
            "Coarse Blasting Powder",
            min_skill=76,
            max_skill=90,
            note="1x Coarse Stone -> 1x Coarse Blasting Powder (item 4364)",
        ),
        Recipe(
            3931,
            "Coarse Dynamite",
            min_skill=91,
            max_skill=100,
            note="3x Coarse Blasting Powder, 1x Linen Cloth -> 1x Coarse "
            "Dynamite (item 4365). NOT spell 4061 - that id is the "
            "crafted item's own throw/damage spell, a different "
            "spell that happens to share the display name",
        ),
        Recipe(
            3973,
            "Silver Contact",
            min_skill=101,
            max_skill=105,
            note="1x Silver Bar -> Silver Contact (item 4404); per-cast "
            "yield could not be independently confirmed for the "
            "3.3.5a era (a later, Cataclysm-only patch changed it) - "
            "verify against this deployment's own cast if it matters",
        ),
        Recipe(
            3938,
            "Bronze Tube",
            min_skill=106,
            max_skill=124,
            focus=1,
            note="2x Bronze Bar (2841), 1x Weak Flux (2880, vendor-bought "
            "- see craft_supply.REAGENT) -> 1x Bronze Tube (item "
            "4371); trainer floor is skill 105 (acore_world."
            "trainer_spell), guide range 105-125, clipped to 106-124 "
            "so it does not collide with Silver Contact's own "
            "max_skill=105. Standard Scope, the guide's next "
            "bracket, is deliberately NOT added here - see the "
            "module-level comment above",
        ),
        Recipe(
            3945,
            "Heavy Blasting Powder",
            min_skill=125,
            max_skill=144,
            note="1x Heavy Stone -> 1x Heavy Blasting Powder (item 4377); "
            "real trainer skill floor is 125, not the guide's stated "
            "135 - also the reagent Hi-Explosive Bomb needs later. "
            "max_skill was 150, past its own grey of 145",
        ),
        # 151-174 deliberately empty - Whirring Bronze Gizmo / Bronze
        # Framework / Explosive Sheep, see the module-level comment above.
        Recipe(
            12585,
            "Solid Blasting Powder",
            min_skill=175,
            max_skill=194,
            note="2x Solid Stone -> 1x Solid Blasting Powder (item 10505)",
        ),
        Recipe(
            12590,
            "Gyromatic Micro-Adjustor",
            min_skill=195,
            max_skill=195,
            focus=1,
            repeatable=False,
            note="TOOL, craft once - 4x Steel Bar -> 1x Gyromatic "
            "Micro-Adjustor (item 10498). Unique-Equipped (toolkit "
            "slot, limit 1) - verified, not assumed - so a duplicate "
            "cast is not blocked by the core either, same reasoning "
            "as Arclight Spanner above: the single-point bracket is "
            "the actual stop",
        ),
        Recipe(
            12589,
            "Mithril Tube",
            min_skill=196,
            max_skill=200,
            focus=1,
            note="3x Mithril Bar -> 1x Mithril Tube (item 10559)",
        ),
        Recipe(
            12591,
            "Unstable Trigger",
            min_skill=201,
            max_skill=215,
            focus=1,
            note="1x Mithril Bar, 1x Mageweave Cloth, 1x Solid Blasting "
            "Powder -> 1x Unstable Trigger (item 10560); also a Hi-"
            "Explosive Bomb reagent",
        ),
        Recipe(
            12599,
            "Mithril Casing",
            min_skill=216,
            max_skill=238,
            focus=1,
            note="3x Mithril Bar -> 1x Mithril Casing (item 10561); also "
            "a Hi-Explosive Bomb reagent",
        ),
        Recipe(
            12619,
            "Hi-Explosive Bomb",
            min_skill=239,
            max_skill=250,
            focus=1,
            note="2x Mithril Casing, 1x Unstable Trigger, 2x Solid "
            "Blasting Powder -> 1x Hi-Explosive Bomb (item 10562); "
            "NOT spell 12543 - that id is the 2022 Classic-relaunch "
            "tree's id for the same name and carries no 3.3.5a "
            "reagent data. All three reagents come from the three "
            "brackets directly above, in order, so this recipe is "
            "reagent-ready by the time a character reaches it",
        ),
        Recipe(
            19788,
            "Dense Blasting Powder",
            min_skill=251,
            max_skill=259,
            note="2x Dense Stone -> 1x Dense Blasting Powder (item 15992); "
            "max_skill was 260, its own grey value",
        ),
        Recipe(
            19791,
            "Thorium Widget",
            min_skill=261,
            max_skill=285,
            focus=1,
            note="3x Thorium Bar, 1x Runecloth (item 14047) -> 1x Thorium "
            "Widget (item 15994)",
        ),
        Recipe(
            19795,
            "Thorium Tube",
            min_skill=286,
            max_skill=300,
            focus=1,
            note="6x Thorium Bar -> 1x Thorium Tube (item 16000)",
        ),
    ),
    # MINING (Grug 8/75, Grog 1/75 as of 2026-09-13) - the smelt half of a
    # GATHERING trade, and the only entry in this table that needs a spell
    # focus. See the MINING AND SMELTING block above for the whole argument:
    # why only Smelt Copper, what the other nine are waiting on, and why the
    # ore in the note is judged by `craft_rhythm.GATHERED` while the BAR it
    # produces deliberately is not.
    #
    # THE BRACKET IS THE DBC'S OWN COLOUR BAND, not a guide's. `Spell.dbc` and
    # `SkillLineAbility.dbc` (both md5-verified against the running worldserver
    # pod) give Smelt Copper `TrivialSkillLineRankLow = 25` and
    # `TrivialSkillLineRankHigh = 70` - yellow at 25, grey at 70 - so 1-69 is
    # "worth casting", ending one point short of the value at which the core
    # stops rolling a skill-up for it. That is the same conservative reading of
    # `max_skill` the dataclass docstring already describes for every other
    # entry, and here it comes from the server rather than from arithmetic over
    # a leveling guide's totals.
    #
    # NOTHING FOLLOWS IT, ON PURPOSE. Smelt Tin's own bracket would be 70-74
    # (trainer floor 65, grey 75) and Smelt Silver's 115-129, but both are
    # trainer-taught and unreachable today, so `recipe_for` correctly answers
    # None above 69 rather than naming a spell the character does not hold -
    # exactly as it does in Tailoring's 146-174 thread gap.
    SKILL_IDS["mining"]: (
        Recipe(
            2657,
            "Smelt Copper",
            min_skill=1,
            max_skill=69,
            focus=3,
            note="1x Copper Ore (2770) -> 1x Copper Bar (2840); "
            "RequiresSpellFocus = 3 (Forge), which bridge._forge_once "
            "walks the leader to, and EquippedItemClass = -1 (no tool, "
            "which is why this ships while infra#3617's Anvil-gated "
            "Blacksmithing recipes do not). AcquireMethod = 1: granted "
            "with Apprentice Mining, so no trainer visit is needed and "
            "no trainer_spell row exists for it",
        ),
    ),
    SKILL_IDS["alchemy"]: (
        Recipe(
            2330,
            "Minor Healing Potion",
            min_skill=1,
            max_skill=79,
            note="1x Peacebloom (2447), 1x Silverleaf (765), "
            "1x Empty Vial (3371) -> item 118, no focus needed; grey "
            "at 95, so 79 is conservative. max_skill was 59, which "
            "handed Ugga to a recipe she cannot learn until 80",
        ),
        Recipe(
            2337,
            "Lesser Healing Potion",
            min_skill=80,
            max_skill=109,
            note="1x Minor Healing Potion (118), 1x Briarthorn (2450) "
            "-> item 858 - THE POTION-AS-REAGENT BRACKET, see the "
            "table's own header comment; no focus needed. min_skill "
            "was 60 against a MinSkillLineRank of 80 - a twenty-point "
            "dead zone, see the COLOUR BANDS block above",
        ),
        Recipe(
            3447,
            "Healing Potion",
            min_skill=110,
            max_skill=139,
            note="1x Bruiseweed (2453), 1x Briarthorn (2450), "
            "1x Leaded Vial (3372) -> item 929, no focus needed",
        ),
        Recipe(
            3173,
            "Lesser Mana Potion",
            min_skill=140,
            max_skill=154,
            note="1x Mageroyal (785), 1x Stranglekelp (3820), "
            "1x Empty Vial (3371) -> item 3385, no focus needed",
        ),
        Recipe(
            7181,
            "Greater Healing Potion",
            min_skill=155,
            max_skill=174,
            note="1x Liferoot (3357), 1x Kingsblood (3356), "
            "1x Leaded Vial (3372) -> item 1710, no focus needed. "
            "max_skill was 184; 175-184 went to Elixir of Fortitude "
            "directly below, which is ORANGE there where this is "
            "YELLOW - see the RAID CONSUMABLES block above",
        ),
        # THE FIRST RAID CONSUMABLE THIS FAMILY WILL EVER REACH, and the only
        # one on the whole realm that a TRAINER teaches below Alchemy 200.
        # Every other raid-tier elixir, potion, flask, oil and stone is either
        # 240+ or taught by a pattern item nothing here buys - see
        # raidcraft.CONSUMABLES for all twenty-two, measured.
        #
        # ITS REAGENTS ARE THE SAME THREE AS Elixir of Greater Defense (11450)
        # ALREADY IN THIS TABLE, item for item and count for count, which is
        # why this bracket costs nothing to supply: `craft_rhythm.GATHERED`
        # already gathers Wild Steelbloom and Goldthorn for 11450 and
        # `craft_supply.REAGENT` already buys the Leaded Vial for it.
        Recipe(
            3450,
            "Elixir of Fortitude",
            min_skill=175,
            max_skill=184,
            note="1x Wild Steelbloom (3355), 1x Goldthorn (3821), "
            "1x Leaded Vial (3372) -> item 3825, no focus needed. "
            "+120 health for an hour, which all forty drink. "
            "trainer_spell rank 175 is the realm's own floor - "
            "SkillLineAbility.MinSkillLineRank reads 1 for this and "
            "cannot be used for it, see raidcraft.py's docstring; "
            "yellow 195, grey 235, so 175-184 is entirely orange",
        ),
        Recipe(
            11449,
            "Elixir of Agility",
            min_skill=185,
            max_skill=209,
            note="1x Stranglekelp (3820), 1x Goldthorn (3821), "
            "1x Leaded Vial (3372) -> item 8949, no focus needed",
        ),
        Recipe(
            11450,
            "Elixir of Greater Defense",
            min_skill=210,
            max_skill=214,
            note="1x Wild Steelbloom (3355), 1x Goldthorn (3821), "
            "1x Leaded Vial (3372) -> item 8951, no focus needed",
        ),
        Recipe(
            11457,
            "Superior Healing Potion",
            min_skill=215,
            max_skill=229,
            note="1x Sungrass (8838), 1x Khadgar's Whisker (3358), "
            "1x Crystal Vial (8925) -> item 3928, no focus needed",
        ),
        Recipe(
            11460,
            "Elixir of Detect Undead",
            min_skill=230,
            max_skill=239,
            note="1x Arthas' Tears (8836), 1x Crystal Vial (8925) "
            "-> item 9154 - only two reagent types, no focus needed. "
            "max_skill was 264; 240-264 went to Elixir of Greater "
            "Agility directly below, which is ORANGE across all "
            "twenty-five of them where this is yellow from 245 - see "
            "the RAID CONSUMABLES block above",
        ),
        # A REAL MELEE ELIXIR INSTEAD OF TWENTY-FIVE POINTS OF DETECTING
        # UNDEAD. trainer_spell rank 240, yellow 255, grey 295, no focus. Its
        # Sungrass and Crystal Vial are already gathered and bought for
        # Superior Healing Potion (11457) and Superior Mana Potion (17553)
        # respectively, and its Goldthorn for Elixir of Agility (11449), so
        # like Elixir of Fortitude above it costs nothing new to supply.
        Recipe(
            11467,
            "Elixir of Greater Agility",
            min_skill=240,
            max_skill=264,
            note="1x Sungrass (8838), 1x Goldthorn (3821), "
            "1x Crystal Vial (8925) -> item 9187, no focus needed. "
            "+25 agility for an hour, for every melee and hunter. "
            "trainer_spell rank 240 is the realm's own floor; "
            "SkillLineAbility.MinSkillLineRank reads 1 and cannot be "
            "used for it",
        ),
        Recipe(
            17553,
            "Superior Mana Potion",
            min_skill=265,
            max_skill=274,
            note="2x Sungrass (8838), 2x Blindweed (8839), "
            "1x Crystal Vial (8925) -> item 13443, no focus needed. "
            "max_skill was 284; 275-284 went to Major Healing Potion "
            "below, which the realm teaches at exactly 275 and which "
            "is orange to 290 where this is yellow from 275",
        ),
        Recipe(
            17556,
            "Major Healing Potion",
            min_skill=275,
            max_skill=300,
            note="2x Golden Sansam (13464), 1x Mountain Silversage (13465), "
            "1x Crystal Vial (8925) -> item 13446, no focus needed. "
            "min_skill was 285, ten points later than the realm's own "
            "trainer_spell rank of 275 - the top of this ladder was "
            "already a raid consumable and was simply starting late",
        ),
    ),
    SKILL_IDS["blacksmithing"]: (
        Recipe(
            2660,
            "Rough Sharpening Stone",
            min_skill=1,
            max_skill=29,
            note="1x Rough Stone -> 1x Rough Sharpening Stone, no focus needed",
        ),
        # 30-74, not the 30-64 an earlier pass wrote, and the ten points it
        # gains are the ten Coarse Sharpening Stone could never have covered.
        # TrivialSkillLineRankHigh is 85, so this still rolls a skill-up the
        # whole way; the guide hands off at 65 only because a human can visit a
        # trainer between casts, which this family cannot.
        Recipe(
            3320,
            "Rough Grinding Stone",
            min_skill=30,
            max_skill=74,
            note="2x Rough Stone -> 1x Rough Grinding Stone, no focus "
            "needed; grey at 85, so 74 is conservative and 64 was "
            "simply the guide's hand-off to a recipe this realm does "
            "not teach until 75",
        ),
        Recipe(
            3326,
            "Coarse Grinding Stone",
            min_skill=75,
            max_skill=90,
            note="2x Coarse Stone -> 1x Coarse Grinding Stone, no focus "
            "needed; MinSkillLineRank 1, grey 100",
        ),
        Recipe(
            3337,
            "Heavy Grinding Stone",
            min_skill=125,
            max_skill=140,
            note="3x Heavy Stone -> 1x Heavy Grinding Stone, no focus needed",
        ),
        # SOLID SHARPENING STONE REPLACED SOLID GRINDING STONE HERE, and the
        # two are one word apart in every leveling guide. A SHARPENING stone
        # goes on a weapon for +6 damage for half an hour and is what a raider
        # carries; a GRINDING stone is a reagent for armour recipes and does
        # nothing on its own. Measured against the same md5-verified DBCs: same
        # skill line 164, same trainer_spell rank 200, same
        # TrivialSkillLineRankLow 200 and High 210, same Solid Stone (7912)
        # reagent - and 9918 consumes ONE per cast where 9920 consumed FOUR. So
        # this is four times cheaper to supply for an item the raid actually
        # uses, with no skill cost at any value in the bracket. See the RAID
        # CONSUMABLES block above. max_skill stays 209 for the reason 9920's
        # own note gave: 210 is the grey value.
        Recipe(
            9918,
            "Solid Sharpening Stone",
            min_skill=200,
            max_skill=209,
            note="1x Solid Stone -> 1x Solid Sharpening Stone (item 7964), "
            "no focus needed; max_skill is 209 because 210 is its grey "
            "value. NOT 9920 Solid Grinding Stone, which held this "
            "bracket and ate 4x Solid Stone for an armour reagent",
        ),
        Recipe(
            16641,
            "Dense Sharpening Stone",
            min_skill=250,
            max_skill=259,
            note="1x Dense Stone -> 1x Dense Sharpening Stone, no focus "
            "needed; max_skill was 260, its own grey value",
        ),
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
        Recipe(
            2881,
            "Light Leather",
            min_skill=1,
            max_skill=19,
            note="3x Ruined Leather Scraps -> 1x Light Leather, recycle, "
            "no focus needed",
        ),
        # spell 2152, creates item 2304 from 1x Light Leather (2318).
        # Cross-checked: wowhead tooltip API (wotlk) + classicdb.ch spell
        # page, both agreeing on a single Light Leather reagent and a
        # SPELL_EFFECT_CREATE_ITEM effect.
        Recipe(
            2152,
            "Light Armor Kit",
            min_skill=20,
            max_skill=45,
            note="1x Light Leather -> 1x Light Armor Kit, no focus needed",
        ),
        # 46-55 IS FILLED NOW, AND THE EVIDENCE THAT EMPTIED IT WAS READ
        # BACKWARDS (this pass, part of infra#3731).
        #
        # The gap's own comment refused spell 9058 because "no `trainer_spell`
        # row teaches it (unlike every other recipe in this table, all
        # confirmed there) and no pattern item in `item_template` names it
        # either", and concluded the id was a wiki guess. Both observations are
        # true. The conclusion does not follow, and this module already knows
        # why in two other places: `SkillLineAbility.dbc` gives 9058
        # `AcquireMethod = 1`, and an auto-learned ability has NO trainer row
        # and NO pattern item BECAUSE NOBODY EVER NEEDS TO BE TAUGHT IT. That
        # is the identical argument Smelt Copper's own note makes ("no trainer
        # visit is needed and no trainer_spell row exists for it") and that
        # Linen Bandage's makes above. Absence from `trainer_spell` is the
        # SIGNATURE of an auto-learned recipe, not evidence against its id.
        #
        # Read straight out of the md5-verified DBCs the header names, with
        # both anchors asserted first:
        #
        #   9058  Handstitched Leather Cloak   skill 165 (Leatherworking)
        #         MinSkillLineRank 1   AcquireMethod 1   ClassMask 0
        #         TrivialSkillLineRankLow 40   TrivialSkillLineRankHigh 70
        #         RequiresSpellFocus 0   EquippedItemClass -1
        #         2x Light Leather (2318) + 1x Coarse Thread (2320) -> 7276
        #
        # ClassMask 0 is every class, so unlike Heavy Linen Bandage's Death
        # Knight row this one really is granted to all five. The reagents are
        # the two this table already buys and gathers for its neighbours
        # (Coarse Thread is in craft_supply.REAGENTS for Linen Belt and
        # Embossed Leather Gloves; Light Leather is 2152's own gathered
        # reagent), so nothing new has to be stocked for it.
        #
        # It stops at 55 rather than at its grey of 69 because Embossed
        # Leather Gloves is ORANGE from 56 (yellow 85) and therefore strictly
        # the better cast there - the hand-off the guide's route already had
        # right.
        Recipe(
            9058,
            "Handstitched Leather Cloak",
            min_skill=46,
            max_skill=55,
            note="2x Light Leather (2318), 1x Coarse Thread (2320, "
            "vendor-bought) -> 1x Handstitched Leather Cloak (item "
            "7276), no focus needed. AcquireMethod 1 / ClassMask 0, "
            "which is why no trainer_spell row names it - see the "
            "comment directly above for the read that got this wrong",
        ),
        Recipe(
            3756,
            "Embossed Leather Gloves",
            min_skill=56,
            max_skill=100,
            note="3x Light Leather, 2x Coarse Thread (2320, "
            "vendor-bought) -> item 4239, no focus needed",
        ),
        Recipe(
            3763,
            "Fine Leather Belt",
            min_skill=101,
            max_skill=125,
            note="6x Light Leather, 2x Coarse Thread (2320, "
            "vendor-bought) -> item 4246, no focus needed",
        ),
        Recipe(
            2167,
            "Dark Leather Boots",
            min_skill=126,
            max_skill=137,
            note="4x Medium Leather, 2x Fine Thread (2321, vendor-bought "
            "- see craft_supply.REAGENTS), 1x Gray Dye (4340, "
            "vendor-bought) -> item 2315, no focus needed",
        ),
        Recipe(
            7135,
            "Dark Leather Pants",
            min_skill=138,
            max_skill=149,
            note="12x Medium Leather, 1x Gray Dye (4340, vendor-bought), "
            "1x Fine Thread (2321, vendor-bought) -> item 5961, no "
            "focus needed",
        ),
        # spell 20649, creates item 4234 from 5x Medium Leather (2319).
        # Cross-checked: wowhead tooltip API (wotlk) + classicdb.ch spell
        # page, both agreeing on a single Medium Leather x5 reagent.
        Recipe(
            20649,
            "Heavy Leather",
            min_skill=150,
            max_skill=155,
            note="5x Medium Leather -> 1x Heavy Leather, recycle, no focus needed",
        ),
        Recipe(
            3818,
            "Cured Heavy Hide",
            min_skill=156,
            max_skill=165,
            note="1x Heavy Hide, 3x Salt (4289, vendor-bought - see "
            "craft_supply.REAGENTS) -> item 4236, no focus needed",
        ),
        Recipe(
            3780,
            "Heavy Armor Kit",
            min_skill=166,
            max_skill=180,
            note="5x Heavy Leather, 1x Fine Thread (2321, vendor-bought) "
            "-> item 4265, no focus needed",
        ),
        Recipe(
            7151,
            "Barbaric Shoulders",
            min_skill=181,
            max_skill=190,
            note="8x Heavy Leather, 1x Cured Heavy Hide (own-crafted), "
            "2x Fine Thread (2321, vendor-bought) -> item 5964, no "
            "focus needed",
        ),
        Recipe(
            7156,
            "Guardian Gloves",
            min_skill=191,
            max_skill=200,
            note="4x Heavy Leather, 1x Cured Heavy Hide (own-crafted), "
            "1x Silken Thread (4291, vendor-bought) -> item 5966, "
            "no focus needed",
        ),
        Recipe(
            10487,
            "Thick Armor Kit",
            min_skill=201,
            max_skill=205,
            note="5x Thick Leather, 1x Silken Thread (4291, "
            "vendor-bought) -> item 8173, no focus needed",
        ),
        Recipe(
            10507,
            "Nightscape Headband",
            min_skill=206,
            max_skill=235,
            note="5x Thick Leather, 2x Silken Thread (4291, "
            "vendor-bought) -> item 8176, no focus needed",
        ),
        Recipe(
            10548,
            "Nightscape Pants",
            min_skill=236,
            max_skill=250,
            note="14x Thick Leather, 4x Silken Thread (4291, "
            "vendor-bought) -> item 8193, no focus needed",
        ),
        Recipe(
            10558,
            "Nightscape Boots",
            min_skill=251,
            max_skill=260,
            note="16x Thick Leather, 2x Heavy Silken Thread (8343, "
            "vendor-bought) -> item 8197, no focus needed; "
            "trainer-verified learn floor is 235, see this table's "
            "header comment for why 251 is used instead",
        ),
        Recipe(
            19049,
            "Wicked Leather Gauntlets",
            min_skill=261,
            max_skill=290,
            note="8x Rugged Leather, 1x Black Dye (2325, vendor-bought), "
            "1x Rune Thread (14341, vendor-bought - NOT item 24288, "
            "a same-named item with zero npc_vendor rows) -> item "
            "15083, no focus needed",
        ),
        Recipe(
            19082,
            "Runic Leather Headband",
            min_skill=291,
            max_skill=300,
            note="14x Rugged Leather, 10x Runecloth (own Tailoring "
            "output), 1x Rune Thread (14341, vendor-bought) -> item "
            "15094, no focus needed; trainer-verified learn floor "
            "is 270, see this table's header comment for why 291 "
            "is used instead",
        ),
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


def focus_for(spell_id: int) -> int:
    """The `SpellFocusObject.dbc` id this recipe needs nearby, or 0 for none.

    THE READ THAT LETS A CALLER HONOUR `Recipe.focus` WITHOUT KNOWING THE TABLE
    (infra#3748). `bridge._forge_once` has to answer "does anybody's standing
    `craft_spell` need a forge right now" from a roster column holding a bare
    spell id, and the alternative to this function is that pass walking
    `RECIPES` itself - a second reader of the table's shape, which is how the
    reagent map ended up existing twice before `craft_rhythm` unified it.

    0 FOR AN UNKNOWN SPELL, NOT AN ERROR. A roster row can legitimately carry a
    spell this table no longer names: a bracket was retired, an operator set
    the column by hand, or mod-overseer has not yet cleared an errand it
    refused. Every one of those means the same thing to the only caller - this
    is not a recipe we owe a walk to - and raising would turn a stale column
    into a dead pass.
    """
    wanted = int(spell_id or 0)
    if not wanted:
        return 0
    for recipes in RECIPES.values():
        for recipe in recipes:
            if recipe.spell_id == wanted:
                return recipe.focus
    return 0


def smelt_errand(name: str, skills: dict) -> int:
    """The smelt `craft_spell` this character could carry, or 0.

    THE GATHERING-TRADE SIBLING OF `craft_errand`, AND DELIBERATELY A SECOND
    FUNCTION RATHER THAN A WIDER LOOP IN THAT ONE (infra#3748). Both read the
    same `RECIPES` table; they differ in which of a character's assigned trades
    they are allowed to answer for, and that difference is the whole safety
    property. `craft_errand` considers `professions.CRAFTING` then
    `professions.SECONDARY`; widening it to include `professions.GATHERING`
    would have silently changed what every existing caller gets, because
    `professions.assigned` lists Grug as ("mining", "blacksmithing") and Grog as
    ("mining", "engineering") - mining FIRST in both - so the first matching
    bracket would have become the smelt for both of the family's miners, for
    ever, and their crafting trades would have stopped dead the day this
    shipped. Two readers and an explicit choice between them is the honest
    shape; `craft_rhythm.errand` is where the choice is made, because it needs
    held-inventory counts neither of these functions can see.

    0 means "this character has no smeltable gathering trade at a value any
    bracket covers" - a character with no mining, with mining not yet learned,
    or with mining above 69 where the next bracket is trainer-gated and
    deliberately absent. A caller must not invent a fallback, the same
    permission discipline `recipe_for` and `craft_errand` already hold.
    """
    for skill_name in professions.assigned(name):
        if skill_name not in professions.GATHERING:
            continue
        value = skills.get(skill_name, 0)
        if not value:
            continue  # not learned yet - professions.py's trainer errand owns this
        recipe = recipe_for(SKILL_IDS[skill_name], value)
        if recipe:
            return recipe.spell_id
    return 0


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
