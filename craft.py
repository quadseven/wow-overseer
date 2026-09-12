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
    """

    spell_id: int
    name: str
    min_skill: int
    max_skill: int
    note: str = ""


# One profession, one verified entry, per the module docstring's own
# discipline. Grow this table by adding entries with the SAME care, not by
# filling every profession at once from memory.
#
# TAILORING - the "Bolt of X Cloth" family (infra#2757 follow-up to #440).
# Every entry below is a plain cloth->bolt SPELL_EFFECT_CREATE_ITEM spell,
# same shape as the original verified Linen entry: no
# SpellInfo::RequiresSpellFocus (a tailor needs no workbench for any bolt
# recipe), one cloth reagent, no vendor-bought thread/dye. That is a
# deliberate v1 scoping decision, not an oversight - see
# docs/design/profession-crafting-drive.md's follow-up note and infra's
# craft-leveling follow-up issue: the thread/dye-dependent recipes between
# these brackets (Linen Belt, Silk Headband, Runecloth Belt, ...) need
# bridge.py's town-trip `kind='buy'` plumbing extended to also buy craft
# reagents, which this pass deferred rather than guessing at. Real thread-
# and-dye recipes are worth more skill per cast, so a character sits idle
# in the gaps between these brackets instead of the y-axis staying full -
# that is the accepted cost of only shipping what could be verified.
#
# Each spell id and its reagent were checked against two independent public
# WotLK/classic spell databases (wowhead.com and classicdb.ch), cross-
# referenced against the wow-professions.com guide's own stated cloth-to-
# bolt ratios (e.g. 470 Mageweave Cloth -> 94 bolts = 5 cloth/bolt) to catch
# a source disagreement before trusting it - one source (warcraft.wiki.gg)
# gave a stale reagent count of 4 for both Mageweave and Runecloth, which the
# 5-per-bolt ratio from the guide's own totals and both database sources
# rejected, so the wiki page was NOT used.
#
#   Bolt of Linen Cloth    spell 3910  item 2996  2x Linen Cloth (2589)
#   Bolt of Woolen Cloth   spell 2964  item 2997  3x Wool Cloth
#   Bolt of Silk Cloth     spell 3839  item 4305  4x Silk Cloth
#   Bolt of Mageweave      spell 3865  item 4339  5x Mageweave Cloth
#   Bolt of Runecloth      spell 18401 item 14048 5x Runecloth
#
# Brackets below are the wow-professions.com guide's own stated ranges for
# each bolt (a leveling guide's "worth casting here" bracket, same kind of
# source the existing Linen entry's 1-60 already leaned on before this pass
# extended it slightly past the guide's stated 1-45). Gaps between brackets
# (61-124, 146-174, 186-249, 261-300) are exactly where the deferred thread/
# dye recipes belong - `recipe_for` correctly returns None there rather than
# inventing a bolt recipe that would not grant a skill-up.
RECIPES: dict = {
    SKILL_IDS["tailoring"]: (
        Recipe(3910, "Bolt of Linen Cloth", min_skill=1, max_skill=60,
               note="2x Linen Cloth -> 1x Bolt of Linen Cloth, no focus needed"),
        Recipe(2964, "Bolt of Woolen Cloth", min_skill=61, max_skill=100,
               note="3x Wool Cloth -> 1x Bolt of Woolen Cloth, no focus needed"),
        Recipe(3839, "Bolt of Silk Cloth", min_skill=125, max_skill=145,
               note="4x Silk Cloth -> 1x Bolt of Silk Cloth, no focus needed"),
        Recipe(3865, "Bolt of Mageweave", min_skill=175, max_skill=185,
               note="5x Mageweave Cloth -> 1x Bolt of Mageweave, no focus needed"),
        Recipe(18401, "Bolt of Runecloth", min_skill=250, max_skill=260,
               note="5x Runecloth -> 1x Bolt of Runecloth, no focus needed"),
    ),
}


def recipe_for(skill_id: int, skill_value: int):
    """The recipe worth casting for this skill at this value, or None.

    None means "nothing in RECIPES covers this profession or this bracket
    yet" - a caller must not invent a fallback, the same permission
    discipline `professions.assigned` holds for who may hold a trade at all.
    Picks the first bracket that contains `skill_value`; RECIPES entries for
    one skill are expected to be kept in ascending bracket order, though
    today's table has exactly one entry per skill and cannot yet disagree
    with itself.
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
    return 0
