"""Whether the family should be out gathering right now, or standing crafting.

Pure module, same seam as bag_pressure.py, disposition.py and craft_supply.py:
facts about held reagents in, a job mode and a sentence out. Nothing here talks
to MySQL, to Discord or to the worldserver.

WHY THIS EXISTS (infra#3696, the keystone of infra#3731). `job='craft'` is a
PERMISSION in mod_overseer.cpp's DriveCraft - "jobIt->second != 'craft'" skips
anyone it was not told about - and the SAME column read one layer up stands the
quest drive down for every non-quest value. So the two halves of a profession
exclude each other by construction:

  * on `job='craft'` nobody gathers, so a family that runs out of its own
    reagent stands still for ever;
  * on `job='quest'` DriveCraft skips everyone, so a family sitting on a
    mountain of reagents never casts anything.

Measured live 2026-09-13 19:15, with all five on `job='craft'` and every one of
them carrying a correct standing errand:

    Bork   Light Leather (2881)          needs Ruined Leather Scraps (2934)  0
    Grog   Rough Blasting Powder (3918)  needs Rough Stone (2835)            0
    Grug   Rough Sharpening Stone (2660) needs Rough Stone (2835)            0
    Og     Bolt of Linen Cloth (2963)    needs 2x Linen Cloth (2589)         1
    Ugga   Minor Healing Potion (2330)   needs Peacebloom (2447)             0

DriveCraft's reagent pre-filter skips all five and it skips them SILENTLY - a
bare `continue`, no log line, no row in any table - so "employed and producing
nothing" looks exactly like "busy". The operator has been alternating the
column by hand all afternoon. This module is what stops that being a person's
job, and `report` below is what stops the starvation being invisible.

WHAT IT DECIDES, AND WHAT IT DELIBERATELY DOES NOT. It answers one question:
given what each character's own recipe consumes and what they are carrying,
should the family be in the gathering mode or the crafting mode. It does NOT
choose recipes (craft.craft_errand), it does NOT buy anything
(craft_supply.py), and it writes nothing at all - `bridge._craft_rhythm_once`
is the only caller and it goes through `bridge._set_job`, which is the
sanctioned write path precisely because it asks `jobs.why_not` first.

IT NEVER WRITES `travel_npc`, AND THAT IS A RULE RATHER THAN AN OVERSIGHT. This
project has been burned repeatedly by a second writer for that column
(infra#3703, infra#3708, infra#3728): a background pass that latches it pins
the family in a shop for half an hour. The only sanctioned writers are the
existing economy passes. This module's whole output is a job mode.
"""

from __future__ import annotations

from dataclasses import dataclass

import craft
import jobs

# ---------------------------------------------------------------------------
# THE TWO MODES, AND WHY THE GATHERING ONE IS `quest` AND NOT `farm`.
#
# `farm` is the obvious answer and it is the wrong one. It is a real entry in
# jobs.MODES ("gather deliberately for a named material") and a real entry in
# mod_overseer.cpp's own JobModes(), so DoJob would accept it happily - and
# then nothing whatsoever would happen. `farm` is not in `jobs.IMPLEMENTED`,
# so `bridge._set_job` refuses it outright through `jobs.why_not`; and even if
# it did not, mod_overseer.cpp reads every non-quest value as "the quest drive
# stands down, full stop, until each mode gets its own drive built". Setting
# `farm` would stand the family down harder than `craft` does, with nothing in
# its place. That is infra#3338's whole lesson, one mode along.
#
# `quest` is the mode that actually gathers, and the evidence is not a guess.
# craft.py's own docstring records it: "GATHERING trades (mining, herbalism,
# skinning) already climb on their own as a side effect of ordinary
# `job='quest'` play (verified live: Ugga's herbalism sat at 132/225 with no
# drive ever built for it)". The operator measured the other half the same day:
# five minutes of `job='quest'` earned the family +2,400 XP. Roaming picks
# things up; that is the whole mechanism, and it needs no new drive.
#
# READ OUT OF `jobs.IMPLEMENTED` RATHER THAN SPELLED, the same shape and the
# same reasoning as `craft_supply.VENDOR_ROLE` reading its keyword out of
# `travel.ROLES`: a second spelling of a mode name is a second thing to get
# wrong, and a mode dropped from IMPLEMENTED becomes a StopIteration at import
# - which the container's own startup surfaces at once - instead of an order
# refused six hours later with the family idle in between.
MODE_GATHER = next(mode for mode in jobs.IMPLEMENTED if mode == "quest")
MODE_CRAFT = next(mode for mode in jobs.IMPLEMENTED if mode == craft.MODE)

# What one character's own reagents say about them. Four words rather than a
# pair of booleans, because the interesting answers are the middle two and a
# flag pair is exactly how they would collapse into each other: BETWEEN means
# "keep doing whatever you are doing" and UNJUDGED means "this module has no
# opinion at all", and those are opposite things that both read as "not short".
SHORT = "short"
BETWEEN = "between"
STOCKED = "stocked"
UNJUDGED = "unjudged"


@dataclass(frozen=True)
class Reagent:
    """One gathered material a recipe consumes, and how much of it per cast.

    `per_cast` IS THE UNIT EVERYTHING HERE COUNTS IN, and it is carried per
    reagent for the same reason `craft_supply.REAGENTS` carries one: a flat
    unit count cannot be compared across recipes. Bolt of Runecloth eats four
    Runecloth a cast and Rough Sharpening Stone eats one Rough Stone, so
    "twenty units" is five casts of the first and twenty of the second. The
    thresholds below are in CASTS, which is the only unit in which "enough to
    be worth sitting down for" means the same thing for every recipe.
    """

    entry: int
    label: str
    per_cast: int


# ---------------------------------------------------------------------------
# THE GATHERED REAGENT PER RECIPE (infra#3696).
#
# THIS IS NOT A THIRD COPY OF A MAP THAT ALREADY EXISTS TWICE. That was the
# first thing checked, because `craft_supply.REAGENT` and
# `craft_supply.REAGENTS` really do hold a spell-to-reagent map and a third
# would be a third thing to keep in step. They hold the BOUGHT half and only
# the bought half - every entry in both is a vendor good, and their own module
# docstring is explicit that a gathered item "must never" appear in them,
# because `reagent_errand` would then log "no reachable vendor stocks it" for
# ever. The GATHERED half had no machine-readable home at all: it existed only
# inside `craft.Recipe.note`, which is free prose the module's own docstring
# says is "for a human reading this table, not for anything the code checks".
# So this table is the missing half of a partition, not a duplicate of either
# existing one, and `test_craft_rhythm.py` holds it to being exactly that: no
# item entry may appear both here and in either craft_supply table, and every
# spell named here must be a real `craft.RECIPES` entry.
#
# THE PROSE IS STILL THE ANCHOR, WHICH IS WHAT KEEPS THIS FROM DRIFTING.
# `test_every_reagent_is_the_one_the_recipe_note_names` requires the exact
# string "<per_cast>x <label>" to appear in that recipe's own `note`. So a
# quantity changed in one place and not the other fails on the pull request,
# and an entry invented here for a reagent the recipe does not use cannot be
# added at all. The note remains the single human-readable source of truth;
# this table is a machine-readable projection of it that cannot disagree.
#
# EVERY LINE BELOW WAS VERIFIED AGAINST THE RUNNING WORLDSERVER'S OWN
# `Spell.dbc`, NOT AGAINST A WIKI. That file (/azerothcore/env/dist/data/dbc/
# Spell.dbc in the worldserver pod, 49839 records x 234 fields) is the one the
# server itself loaded, so it cannot disagree with the world the family lives
# in - the same source infra#3689 used to catch two wrong facts in the
# Tailoring table, and the same one `acore_world` cannot substitute for
# (`spell_dbc` holds 4492 override rows, none of them these, and
# `skilllineability_dbc` is an empty shell). The parse was proved against a
# known-good value before any new fact was read off it: spell 2963 resolves to
# Reagent[0]=2589, ReagentCount[0]=2, which is exactly what infra#3689
# established by hand. Reagent[] is fields 52-59 and ReagentCount[] 60-67.
#
# ALL SIXTY-TWO RECIPES IN `craft.RECIPES` WERE READ, AND EVERY REAGENT NOTE IN
# THAT TABLE PROVED CORRECT - spell id, output item, reagent ids and per-cast
# counts, with no discrepancy anywhere. That is worth recording rather than
# passing over: the notes were assembled from guides and secondary databases
# over many passes, one of which (Mageweave's reagent count) was known to have
# been wrong once, and this is the first time the whole table has been checked
# against the server in one go. It is also why this projection can be trusted.
#
# WHAT "GATHERED" MEANS HERE, AND HOW IT WAS DECIDED. A reagent is gathered if
# the family can obtain it by killing, mining, skinning, herbing or fishing -
# which is to say, by ordinary `job='quest'` roaming. That was settled against
# acore_world rather than by judgement, on two facts per item:
#
#   BUYABLE means at least one `npc_vendor` row with `maxcount = 0`. That is
#   the bar `craft_supply` already holds every one of its own entries to
#   ("confirmed sold with unlimited stock"), and on this world it partitions
#   the two sets perfectly with no overlap at all. Measured: all 143 Empty
#   Vial rows, all 156 Coarse Thread rows, all 220 Weak Flux rows - every
#   vendor row of every craft_supply reagent - carry maxcount = 0. Not one
#   vendor row of any reagent below does.
#
#   THAT DISTINCTION IS LOAD-BEARING AND IT CORRECTS THE ISSUE'S OWN PROSE.
#   infra#3696 and infra#3731 both state that none of the five live materials
#   is vendor-buyable. Six NPCs do in fact sell Peacebloom, twelve sell
#   Bruiseweed, and one sells Linen Cloth. Every one of those rows is limited
#   stock on a restock timer: 1 to 3 units every 3600 to 43200 seconds. A
#   counter that offers two Peacebloom every two and a half hours is not a
#   supply line for a loop that consumes one per cast at roughly three casts a
#   minute, and `craft_supply.REAGENT` would be wrong to name it. The issues'
#   conclusion is right; the reason they give for it is not, and the correct
#   reason is the one this table is built on.
#
#   GATHERABLE means the item appears in this world's own loot tables. Each
#   was counted directly: Linen Cloth has 788 `creature_loot_template` rows,
#   Rough Stone 78 plus 10 `gameobject_loot_template` (mining nodes), Ruined
#   Leather Scraps 13 `skinning_loot_template`, Peacebloom 97 plus 6 herb
#   nodes, Thick Leather 318 skinning rows. Nothing below has zero.
#
# WHAT IS DELIBERATELY ABSENT, AND WHY THE GAPS MATTER MORE THAN THE ENTRIES.
# A recipe with no entry here is UNJUDGED (see `stand`), which means this
# module declines to have an opinion and says so out loud rather than guessing.
# Three kinds of recipe are left out on purpose:
#
#   OWN-CRAFTED INTERMEDIATES. Lesser Healing Potion (2337) consumes a Minor
#   Healing Potion, Linen Belt (8776) a Bolt of Linen Cloth, and Barbaric
#   Shoulders (7151) and Guardian Gloves (7156) a Cured Heavy Hide. Cured Heavy
#   Hide was checked against every loot table and every vendor on this world
#   and has zero rows in all of them: it exists only because somebody cast
#   3818. No gathering trip produces any of these, so calling a character short
#   of one "go and gather" would send the family out for something roaming
#   cannot return with.
#
#   SMELTED BARS. Every Engineering recipe consuming Copper, Bronze, Silver,
#   Steel, Mithril or Thorium Bar is absent for the same reason and it is the
#   sharper case, because it is not obvious: Copper Bar, Steel Bar, Mithril Bar
#   and Thorium Bar have ZERO rows in npc_vendor and zero in every loot table
#   on this world. A bar is smelted from ore by the Mining skill, and nothing
#   in this codebase drives smelting. So Grog's Engineering has a hard ceiling
#   at skill 31 (Handful of Copper Bolts, 1x Copper Bar) that no amount of
#   gathering will lift, and this module's job is to say so rather than to send
#   the family roaming for an item the world will never drop. Filed as its own
#   gap rather than papered over here.
#
#   THE BARS STAY ABSENT AND THE ORE HAS NOW ARRIVED (infra#3738 -> #3747 ->
#   #3748). The obvious fix was to name a smelt spell in `craft_spell` and let
#   DriveCraft cast it, since smelting is the same SPELL_EFFECT_CREATE_ITEM
#   shape as everything else here. Checked against the running worldserver's own
#   Spell.dbc, that alone does not work: EVERY smelt spell in the game carries
#   `RequiresSpellFocus = 3`, which SpellFocusObject.dbc resolves to "Forge",
#   and DriveCraft casts in place. So infra#3747 added the focus field and left
#   BOTH the bars and the ore out of this table, with an explicit reason for the
#   ore: "adding Copper Ore here would make Grog read as SHORT and send the
#   whole family mining for something he still could not turn into a bar, which
#   is the deadlock `rhythm`'s own UNJUDGED rule exists to prevent. The ore
#   entries belong in the same change that lands the forge aim, not before it."
#
#   THIS IS THAT CHANGE, SO THAT REASONING INVERTS - and it inverts completely
#   rather than partially, which is the bit worth being precise about. The
#   deadlock infra#3747 feared needs BOTH halves to be true: the ore must be
#   judgeable AND the ore must be useless. `bridge._forge_once` walks the
#   leader to a spawned Forge and `craft.RECIPES` now carries Smelt Copper, so
#   the second half is false: a mining trip that comes back with Copper Ore
#   produces Copper Bars, which is the item Grog's Engineering has been stalled
#   on since skill 31. "Grog is SHORT of Copper Ore, send the family mining" is
#   now a true and actionable sentence, and 2657's entry below is what lets
#   this module say it. It is also nearly free: Rough Stone, which Grug's
#   Blacksmithing and Grog's own blasting powders already want, comes off the
#   SAME copper veins, so one trip restocks the ore and the stone together.
#
#   THE BARS THEMSELVES STILL DO NOT BELONG HERE, and that is not an oversight
#   left over from the old reasoning. `GATHERED` means "a gathering trip
#   produces this". Copper Bar is produced by a CAST, so it is an own-crafted
#   intermediate exactly like Minor Healing Potion and Cured Heavy Hide above,
#   and a character short of one is still correctly UNJUDGED here - sending the
#   family roaming would not return with one. What answers a character short of
#   bars is `errand` below, which hands them the smelt instead of the spend.
#   See craft.py's "MINING AND SMELTING" comment for the measurements.
#
#   PURELY VENDOR-SUPPLIED RECIPES. There are none in craft.RECIPES today -
#   every recipe that names a bought reagent also names a gathered one - but if
#   one is ever added, it belongs to craft_supply and not here, and the absence
#   of an entry is what keeps this module from sending the family roaming for a
#   vial.
#
# A RECIPE'S BOUGHT REAGENTS ARE SIMPLY NOT LISTED. Embossed Leather Gloves
# needs 3x Light Leather AND 2x Coarse Thread; only the Light Leather is here,
# because the thread is `craft_supply.REAGENTS`' business and is already bought
# on its own pass. The two modules answer different halves of the same recipe
# and neither needs to know the other's half.
#
# WHAT THIS TABLE STILL CANNOT SEE, SAID PLAINLY. It knows that a reagent is
# gatherable SOMEWHERE on this world; it does not know whether THIS character
# can currently reach it. Medium Leather comes off creatures a skinner needs
# far more than Bork's Skinning 12 to skin. That is not a hole this module can
# close honestly - the gathering-skill-to-creature-level map is not in the
# world database in any form Python can read - and it does not need to be: a
# character is only ever aimed at a recipe `craft.recipe_for` picked for the
# crafting skill they already hold, and by the time Leatherworking is at 126
# the Skinning that fed it is long past 12. It is recorded because the next
# reader will wonder, and because a future bracket could break the assumption.
GATHERED: dict[int, tuple[Reagent, ...]] = {
    # TAILORING - the bolt family. Cloth is a humanoid kill drop, which is why
    # Og needs no gathering PROFESSION at all to restock: he needs to be out
    # in the world killing things, which is exactly what MODE_GATHER is.
    2963: (Reagent(2589, "Linen Cloth", 2),),
    2964: (Reagent(2592, "Wool Cloth", 3),),
    3839: (Reagent(4306, "Silk Cloth", 4),),
    3865: (Reagent(4338, "Mageweave Cloth", 4),),
    18401: (Reagent(14047, "Runecloth", 4),),
    # FIRST AID - the same Linen the bolts want, which is the competition
    # infra#3731 names between Tailoring and First Aid for one material.
    # Nothing here arbitrates that; both simply read as short at once, and one
    # gathering trip answers both. And it is not a hypothetical competition:
    # live on 2026-09-13 the whole family held ONE Linen Cloth between them
    # (Og's), because Og's own Bolt of Linen Cloth errand consumes two per cast
    # of the exact item Linen Bandage consumes one of. One gathering trip does
    # answer both, but a short trip answers whichever asks first.
    3275: (Reagent(2589, "Linen Cloth", 1),),
    # 3276 Heavy Linen Bandage is deliberately absent, because craft.RECIPES no
    # longer carries it: it is a trainer purchase for every class but Death
    # Knight, and this family has no Death Knight. See craft.RECIPES' First Aid
    # comment. Do not re-add it here without re-adding it there.
    #
    # COOKING is absent for a different reason and it is not a gap in this
    # table: every Cooking recipe reachable below the family's 75 cap requires
    # RequiresSpellFocus 4 ("Cooking Fire"), so craft.RECIPES carries none of
    # them. Charred Wolf Meat (2538, 1x Stringy Wolf Meat 2672) was here and is
    # removed with it. The reagent was never the blocker - see craft.RECIPES'
    # Cooking comment for the one cast that unblocks the whole ladder.
    # ENGINEERING - the blasting powders only. Every other bracket consumes a
    # smelted bar; see the module comment above for why they are absent and
    # why that is a real ceiling rather than a gap in this table.
    3918: (Reagent(2835, "Rough Stone", 1),),
    3929: (Reagent(2836, "Coarse Stone", 1),),
    3945: (Reagent(2838, "Heavy Stone", 1),),
    12585: (Reagent(7912, "Solid Stone", 2),),
    19788: (Reagent(12365, "Dense Stone", 2),),
    # MINING - the ore a smelt consumes, which is the entry infra#3747 wrote
    # down as deferred and this change lands (see the block above). Copper Ore
    # is gathered exactly the way Rough Stone is - 14 `gameobject_loot_template`
    # rows, the copper veins the family's two miners already walk past - so a
    # character short of it reads SHORT and one trip serves every stone-eater in
    # the family at the same time. The Copper BAR this produces is not here and
    # must not be: it comes off a cast, not a walk.
    2657: (Reagent(2770, "Copper Ore", 1),),
    # ALCHEMY - herbs, every one of them a herb-node gather plus a long tail of
    # creature drops. The vial each of these also needs is craft_supply's.
    # Lesser Healing Potion (2337) is absent: its second reagent is the
    # previous bracket's own output.
    2330: (Reagent(2447, "Peacebloom", 1), Reagent(765, "Silverleaf", 1)),
    3447: (Reagent(2453, "Bruiseweed", 1), Reagent(2450, "Briarthorn", 1)),
    3173: (Reagent(785, "Mageroyal", 1), Reagent(3820, "Stranglekelp", 1)),
    7181: (Reagent(3357, "Liferoot", 1), Reagent(3356, "Kingsblood", 1)),
    11449: (Reagent(3820, "Stranglekelp", 1), Reagent(3821, "Goldthorn", 1)),
    11450: (Reagent(3355, "Wild Steelbloom", 1), Reagent(3821, "Goldthorn", 1)),
    11457: (Reagent(8838, "Sungrass", 1), Reagent(3358, "Khadgar's Whisker", 1)),
    11460: (Reagent(8836, "Arthas' Tears", 1),),
    17553: (Reagent(8838, "Sungrass", 2), Reagent(8839, "Blindweed", 2)),
    17556: (Reagent(13464, "Golden Sansam", 2),
            Reagent(13465, "Mountain Silversage", 1)),
    # BLACKSMITHING - the stone family, mining byproduct. Grug and Grog are
    # short of the same Rough Stone from different trades, which is the
    # cheapest possible case for a family-wide mode: one trip serves both.
    2660: (Reagent(2835, "Rough Stone", 1),),
    3320: (Reagent(2835, "Rough Stone", 2),),
    # 2665 Coarse Sharpening Stone is GONE from craft.RECIPES - its realm learn
    # floor is 75, not the guide's 65, and Coarse Grinding Stone already owns
    # 75-90 with a better grey. See craft.py's COLOUR BANDS block.
    3326: (Reagent(2836, "Coarse Stone", 2),),
    3337: (Reagent(2838, "Heavy Stone", 3),),
    9920: (Reagent(7912, "Solid Stone", 4),),
    16641: (Reagent(12365, "Dense Stone", 1),),
    # LEATHERWORKING - skinning output throughout. Light Leather and Heavy
    # Leather are BOTH own-crafted (2881, 20649) and skinned directly (31 and
    # 84 skinning_loot_template rows), so unlike Cured Heavy Hide a gathering
    # trip genuinely does restock them and they belong here.
    2881: (Reagent(2934, "Ruined Leather Scraps", 3),),
    2152: (Reagent(2318, "Light Leather", 1),),
    9058: (Reagent(2318, "Light Leather", 2),),
    3756: (Reagent(2318, "Light Leather", 3),),
    3763: (Reagent(2318, "Light Leather", 6),),
    2167: (Reagent(2319, "Medium Leather", 4),),
    7135: (Reagent(2319, "Medium Leather", 12),),
    20649: (Reagent(2319, "Medium Leather", 5),),
    3818: (Reagent(4235, "Heavy Hide", 1),),
    3780: (Reagent(4234, "Heavy Leather", 5),),
    10487: (Reagent(4304, "Thick Leather", 5),),
    10507: (Reagent(4304, "Thick Leather", 5),),
    10548: (Reagent(4304, "Thick Leather", 14),),
    10558: (Reagent(4304, "Thick Leather", 16),),
    19049: (Reagent(8170, "Rugged Leather", 8),),
    19082: (Reagent(8170, "Rugged Leather", 14),
            Reagent(14047, "Runecloth", 10)),
}


# ---------------------------------------------------------------------------
# THE HYSTERESIS. TWO NUMBERS, AND THE GAP BETWEEN THEM IS THE DESIGN.
#
# A family that flips mode every poll is strictly worse than one stuck in
# either: each flip costs five `overseer_command` rows and a worldserver round
# trip, it abandons whatever the family was standing at, and it produces
# neither skill-ups nor materials. So the question is not "how much is enough"
# but "how far apart must 'enough to sit down' and 'too little to bother' be".
#
# BOTH NUMBERS ARE IN CASTS, never in units - see `Reagent.per_cast`.
#
# WHY 3 IS THE FLOOR. Below three casts there is nothing left to do: a session
# that short ends inside one poll, so the five command rows buy almost nothing.
# It is not lower because "out" and "briefly between stacks" are different
# states and only the first is worth a trip; it is not higher because the cost
# of an unnecessary gathering trip is genuinely low, for a reason that is easy
# to miss and is argued below.
#
# WHY 12 IS THE CEILING, AND WHY IT IS NOT 50. The honest upper bound would be
# one save interval of crafting (see the staleness argument below), which at
# the measured cast rate is thirty to fifty casts. It is 12 instead because
# 12 is inside what this family has actually been MEASURED to accumulate for
# its thinnest reagent, and 50 is not: on the night Alchemy went 1 to 14, Ugga
# held 13 Peacebloom and 20 Silverleaf, which is thirteen casts of Minor
# Healing Potion and no more. A threshold above what the family can reach is a
# threshold that never fires, and "the family never crafts again" is a worse
# failure than "the crafting session was shorter than ideal". Og's 279 Linen
# Cloth (139 casts) shows the other end of the same distribution; 12 clears the
# thin end with a little room and the fat end by an order of magnitude.
#
# THE RATIO IS THE POINT: STOCKED is four times SHORT, and the 3-to-11 band
# between them is where nobody changes anything. A family already crafting
# keeps crafting down through the band until it hits 3; a family already
# gathering keeps gathering up through the band until every member clears 12.
# That is an ordinary Schmitt trigger, and the band is what stops a single
# reagent hovering at one boundary from re-aiming the whole family every poll.
#
# ---------------------------------------------------------------------------
# WHY A TABLE THAT IS MINUTES STALE IS SAFE TO DECIDE ON, WHICH IS NOT OBVIOUS
# AND WAS VERY NEARLY THE REASON TO ABANDON THIS SHAPE.
#
# Held counts come from `item_instance`, which is written on the player-save
# timer. That timer was read off the running worldserver's own config rather
# than assumed: `PlayerSaveInterval = 900000` with `PlayerSave.AdditionalSaves
# = 0`, so FIFTEEN MINUTES, not the "a few minutes" the surrounding modules
# say. At the measured cast rate (Og: six Bolts of Linen in three minutes;
# Ugga: seven Minor Healing Potions in two) that is thirty to fifty casts of
# drift between the truth and the reading. Compared against thresholds of 3 and
# 12, the reading can be wrong by four times the whole band.
#
# IT IS SAFE ANYWAY, AND THE REASON IS STRUCTURAL RATHER THAN LUCKY. Each
# threshold is only ever consulted as an EXIT from the mode the family is
# already in, and in each mode the drift runs in the direction that makes that
# exit conservative:
#
#   CRAFTING. The count only falls. A stale reading therefore OVERSTATES the
#   stock, so the `short` exit fires LATE and never early. It is not possible
#   for staleness to send a family gathering while they still held reagents.
#
#   GATHERING. The count only rises. A stale reading therefore UNDERSTATES the
#   stock, so the `stocked` exit fires LATE and never early. It is not possible
#   for staleness to sit a family down to craft with empty bags.
#
# So staleness costs LATENESS, bounded by the save interval, and never costs a
# WRONG MODE. That is the whole of why a stale table is usable here, and it is
# why neither threshold carries a staleness margin: a margin would buy nothing
# that the direction of the drift does not already guarantee.
#
# THE RESIDUAL IS NAMED RATHER THAN HIDDEN. A crafting session can in truth end
# up to one save interval before the database admits it, and for that window
# the family stands still. That window is bounded at 900 seconds, it is
# strictly better than the unbounded idle this issue is about, and `report`
# names every starved character by reagent so the window is visible while it
# lasts. Shortening it wants a time-boxed craft session rather than a bigger
# threshold, and that is a follow-up, not this change.
#
# ONE HAPPY CONSEQUENCE WORTH RECORDING: because the inputs themselves only
# change every 900 seconds, and the decision is a pure function of those
# inputs, a flip-every-poll oscillation is arithmetically impossible at any
# poll faster than the save timer - consecutive polls simply read the same
# numbers and reach the same answer. The hysteresis above is therefore not
# protection against fast chatter, which cannot happen; it is protection
# against the family crossing a single boundary and being dragged back over it
# by the next genuine reading.
SHORT_CASTS = 3
STOCK_CASTS = 12


@dataclass(frozen=True)
class Stand:
    """Where one character stands on its own recipe's gathered reagents.

    `casts` is how many more casts the THINNEST reagent allows, which is the
    only number that matters: a recipe needing a herb and a leaf is stopped by
    whichever one runs out first, and Ugga holding seven Silverleaf against
    zero Peacebloom can cast exactly nothing.

    `why` is never empty, for the reason `craft_supply.SupplyTrip` gives for
    its own: a verdict that cannot say why is the silent idle this whole family
    of modules exists to end.
    """

    name: str
    craft_spell: int = 0
    verdict: str = UNJUDGED
    casts: int = 0
    thinnest: str = ""
    why: str = ""


@dataclass(frozen=True)
class Rhythm:
    """What the family's `job` should be, and whether that is a change.

    `mode` is '' for a pass that should write nothing at all, the same "'' means
    nobody" convention `craft_supply.SupplyTrip.target` and
    `professions.traveller` both use. `changed` is the caller's whole write
    gate: re-asserting a mode the family is already in would insert five
    `overseer_command` rows every poll for ever, which is command spam rather
    than a decision.
    """

    mode: str = ""
    changed: bool = False
    why: str = ""
    stands: tuple = ()


def casts_in_hand(craft_spell: int, held: dict) -> int | None:
    """How many more casts of this recipe the gathered reagents allow.

    None means "this module has no opinion about this recipe" - no GATHERED
    entry, which is either a recipe whose non-bought reagents are own-crafted
    or smelted, or one nothing has verified yet. A caller must not invent a
    fallback; the same permission discipline `craft.recipe_for` holds for a
    profession with no bracket.

    `held` is `{item entry: count carried}`, read from the world's own
    item_instance, exactly the shape `craft_supply.craft_reagent_errands`
    already takes. A reagent absent from it is zero held, not unknown: the
    bridge's own count query LEFT JOINs and returns 0 for a character carrying
    none, so an absent key can only mean the caller did not ask, and the
    fail-closed reading of that is "they have none".
    """
    reagents = GATHERED.get(int(craft_spell or 0))
    if not reagents:
        return None
    return min(
        int(held.get(r.entry, 0)) // r.per_cast
        for r in reagents
        if r.per_cast > 0
    )


@dataclass(frozen=True)
class Errand:
    """Which of a character's two possible recipes it should be casting.

    `smelting` is not derivable from `spell` by the caller without re-reading
    `craft.RECIPES`, and the one caller that needs it - the forge pass's log
    line, and `bridge._craft_once`'s - would then be a third reader of that
    table. Carried here instead.

    `why` is never empty, the same rule `Stand.why` holds and for the same
    reason: this decision silently swaps what a character spends its whole
    crafting session on, and a swap nobody can explain is indistinguishable
    from the planner having lost track of the recipe.
    """

    name: str
    spell: int = 0
    smelting: bool = False
    why: str = ""


def reagents_to_count(name: str, skills: dict) -> set:
    """Every item entry a decision about this character could need to count.

    THE UNION OF BOTH CANDIDATES, ASKED BEFORE EITHER IS CHOSEN, which is the
    only order that works: `errand` picks between the spend and the smelt by
    comparing what is held for each, so a caller that fetched counts for the
    chosen recipe would have to choose first, and choosing needs the counts.
    One extra item entry per miner is the whole cost.

    A SET OF ENTRIES RATHER THAN A QUERY, because this module talks to nothing.
    `bridge._fetch_item_counts` takes (name, entry) pairs and batches one round
    trip per DISTINCT entry across the family, so handing it a couple more
    entries costs nothing per character.
    """
    wanted = set()
    for spell in (craft.craft_errand(name, skills), craft.smelt_errand(name, skills)):
        for reagent in GATHERED.get(int(spell or 0), ()):
            wanted.add(reagent.entry)
    return wanted


def errand(name: str, skills: dict, held: dict) -> Errand:
    """Spend, or smelt? The one `craft_spell` this character should carry.

    THE ALTERNATION infra#3748 ASKED FOR, AND IT LIVES HERE RATHER THAN IN
    `craft` FOR THE REASON THAT ISSUE GAVE: "a character holds one
    `craft_spell`, so something must choose when Grog smelts ore into bars and
    when he spends bars on bolts. This needs held-inventory counts that
    `craft.craft_errand` deliberately cannot see, so it belongs with
    `craft_rhythm`, not `craft`." This module already reads held counts to
    decide the family's MODE; deciding one character's recipe from the same
    numbers is the same question one level down, and it needs no new input.

    THE RULE, IN ONE LINE: SMELT ONLY WHEN THERE IS ORE AND THE CRAFT CANNOT
    RUN. Spelled out, in the order the branches below take:

      * A character with no smeltable gathering trade keeps its craft errand.
        Nothing changes for Og, Ugga or Bork, ever.
      * A miner holding no ore keeps its craft errand. This matters more than
        it looks: it is what makes a miner short of BOTH read as short of the
        thing `GATHERED` can send the family after, rather than reading as
        short of ore for a smelt that would produce a bar nobody is waiting
        for.
      * A miner holding ore smelts IF its crafting recipe cannot run - either
        because it is short of that recipe's own gathered reagent (0 casts in
        hand) or because `casts_in_hand` has no opinion about it at all. That
        second case is the one this whole chain of issues is about: every
        bar-consuming Engineering bracket is UNJUDGED here precisely because a
        bar is not gathered, so "no opinion" is exactly the signature of a
        recipe waiting on a smelt.
      * Otherwise it spends. A miner who CAN craft, crafts.

    WHY THE CRAFT WINS THE TIE RATHER THAN THE SMELT. infra#3731 is about the
    crafting trades; Mining is the supply line, not the goal. A miner who can
    cast its real recipe should be casting it, and the bars it is not smelting
    this session are not lost - the ore keeps. The reverse preference would
    have every miner smelt down to its last ore before crafting anything, which
    maximises Mining and stalls Blacksmithing and Engineering, which is the
    exact complaint infra#3738 was filed about wearing different clothes.

    AND THE SMELT CANNOT STARVE THE CRAFT OF ITS OWN REAGENT, because the two
    never consume the same item. Copper Ore feeds only the smelt; Rough Stone
    feeds only the powders and the sharpening stones. They arrive on the same
    mining trip and are spent by different recipes.
    """
    spend = craft.craft_errand(name, skills)
    smelt = craft.smelt_errand(name, skills)

    if not smelt:
        return Errand(
            name=name, spell=spend,
            why="%s has no smeltable gathering trade at a value any bracket "
                "covers, so there is no choice to make and its craft errand "
                "(spell %d) stands" % (name, spend),
        )

    ore = casts_in_hand(smelt, held) or 0
    if ore < 1:
        return Errand(
            name=name, spell=spend,
            why="%s could smelt with spell %d but holds ore for %d cast(s), so "
                "its craft errand (spell %d) stands and the gathering trip that "
                "restocks one restocks the other" % (name, smelt, ore, spend),
        )

    casts = casts_in_hand(spend, held)
    if casts is None:
        return Errand(
            name=name, spell=smelt, smelting=True,
            why="%s smelts (spell %d, ore for %d cast(s)) because no gathering "
                "trip produces what its craft errand (spell %d) consumes - a "
                "smelted bar or an own-crafted intermediate - so casting is the "
                "only thing that can move it" % (name, smelt, ore, spend),
        )
    if casts < 1:
        return Errand(
            name=name, spell=smelt, smelting=True,
            why="%s smelts (spell %d, ore for %d cast(s)) because its craft "
                "errand (spell %d) has reagents for %d cast(s) - the ore is "
                "here and the craft's own material is not" % (
                    name, smelt, ore, spend, casts),
        )
    return Errand(
        name=name, spell=spend,
        why="%s spends rather than smelts: its craft errand (spell %d) has "
            "reagents for %d cast(s) in hand, and the %d cast(s) of ore keep "
            "until it runs out" % (name, spend, casts, ore),
    )


def stand(name: str, craft_spell: int, held: dict) -> Stand:
    """One character's verdict on its own recipe, and the sentence for it."""
    spell = int(craft_spell or 0)
    if not spell:
        return Stand(
            name=name,
            why="%s has no standing craft errand, so there is nothing to be "
                "short of - craft.craft_errand found no recipe in any bracket "
                "this character's skills reach" % name,
        )

    reagents = GATHERED.get(spell)
    if not reagents:
        return Stand(
            name=name, craft_spell=spell,
            why="%s's recipe (spell %d) names no reagent a gathering trip "
                "produces - every reagent it needs is vendor-bought "
                "(craft_supply's business), own-crafted, or a smelted bar, so "
                "this pass has no opinion about %s and leaves the rest of the "
                "family to decide" % (name, spell, name),
        )

    # THE THINNEST REAGENT DECIDES, and it is named, because "Ugga is short"
    # and "Ugga is short of Peacebloom while carrying seven Silverleaf" are
    # different sentences and only the second can be acted on.
    thin = min(reagents, key=lambda r: int(held.get(r.entry, 0)) // r.per_cast)
    casts = int(held.get(thin.entry, 0)) // thin.per_cast
    carried = int(held.get(thin.entry, 0))

    if casts < SHORT_CASTS:
        verdict = SHORT
        why = ("%s holds %d %s against %d per cast of spell %d, which is %d "
               "more cast(s) - short of the %d it takes to be worth staying "
               "put" % (name, carried, thin.label, thin.per_cast, spell,
                        casts, SHORT_CASTS))
    elif casts >= STOCK_CASTS:
        verdict = STOCKED
        why = ("%s holds %d %s, enough for %d casts of spell %d - at or past "
               "the %d that makes a crafting session worth sitting down for"
               % (name, carried, thin.label, casts, spell, STOCK_CASTS))
    else:
        verdict = BETWEEN
        why = ("%s holds %d %s, enough for %d casts of spell %d - between the "
               "%d that would send the family gathering and the %d that would "
               "sit it down, so %s argues for neither"
               % (name, carried, thin.label, casts, spell, SHORT_CASTS,
                  STOCK_CASTS, name))

    return Stand(name=name, craft_spell=spell, verdict=verdict, casts=casts,
                 thinnest=thin.label, why=why)


def standing_mode(job_by_name: dict) -> str:
    """The one mode the whole family is currently in, or '' if they disagree.

    A JOB IS FAMILY-WIDE BY CONSTRUCTION (jobs.py's docstring has the full
    argument: mod-overseer gates `new rpg` to the leader alone, so a per
    character mode is infra#2812's 937-yard scatter one layer up). The column
    is per row all the same, and a fan-out can land partially - `_set_job`
    itself counts written against called and reports the difference. So the
    rows CAN disagree, and when they do this module must not act: deciding a
    transition from a mode that is not uniformly held would write over whatever
    half-landed order is still settling. '' means "ask again next pass", which
    is the honest answer and costs one cycle.
    """
    modes = {str(mode or "").strip() for mode in job_by_name.values()}
    if len(modes) != 1:
        return ""
    return modes.pop()


def rhythm(stands, standing: str) -> Rhythm:
    """The mode the family should be in, given where everyone stands.

    ONLY EVER BETWEEN THE TWO MODES THIS OWNS. If `standing` is anything else -
    `dungeon` while a campaign runs, `train` while somebody walks to a trainer,
    `rest` - this returns no mode at all. That is not caution for its own sake:
    the dungeon coordinator's SOLE trigger is the leader's `job` being
    `dungeon` (mod-overseer#88/#144), so a pass that helpfully switched the
    family to `quest` mid-run would end the run. A background decision must
    never outrank a standing order it knows nothing about.

    ANY SHORT MEANS GATHER; ALL STOCKED MEANS CRAFT; ANYTHING ELSE HOLDS. The
    asymmetry is a fact about the world rather than a preference. A gathering
    trip is NON-EXCLUSIVE: the family roams together and every member picks up
    their own reagents on the same walk, so one trip serves all five at once.
    A crafting session is EXCLUSIVE: it produces nothing for a member who has
    no materials, and leaves them standing at a counter in exactly the silent
    idle infra#3696 was filed about. So one short member is enough to make
    gathering the better use of everyone's time, while crafting has to earn
    every member before it is worth sitting the family down.

    Gathering is also never wasted, which is what makes that asymmetry cheap.
    infra#3731 wants Skinning, Mining and Herbalism maxed too, and those climb
    only while roaming; the same roaming earns the levels the higher-rank
    trainers need. An unnecessary gathering trip still makes progress on three
    of the professions the epic is about. An unnecessary crafting session makes
    none on any of them.

    UNJUDGED MEMBERS ARE EXCLUDED FROM THE VOTE ENTIRELY, and that is what
    stops a deadlock rather than a nicety. Grog's Engineering hits a hard
    ceiling at skill 31, where the recipe wants a smelted Copper Bar that this
    world drops nowhere and sells nowhere. Counting him as permanently short
    would hold the other four in gathering mode for ever, waiting for an item
    no walk can return with. He is named in `report` instead, every pass, which
    is the visibility half of the same issue.
    """
    stands = tuple(stands or ())
    if standing not in (MODE_GATHER, MODE_CRAFT):
        return Rhythm(
            why="The family is on job=%r, which this pass does not arbitrate - "
                "it alternates %s and %s and nothing else, so a standing order "
                "for anything else is left exactly where it is."
                % (standing or "nothing agreed", MODE_GATHER, MODE_CRAFT),
            stands=stands,
        )

    judged = [s for s in stands if s.verdict != UNJUDGED]
    if not judged:
        return Rhythm(
            why="Nobody in the family holds a recipe whose reagents a "
                "gathering trip produces, so there is no reason here to change "
                "job=%s." % standing,
            stands=stands,
        )

    short = [s for s in judged if s.verdict == SHORT]
    if short:
        wanted = MODE_GATHER
        why = ("%s cannot cast: %s. One walk restocks all of them at once, so "
               "the family gathers." % (
                   ", ".join(s.name for s in short),
                   "; ".join(s.why for s in short)))
    elif all(s.verdict == STOCKED for s in judged):
        wanted = MODE_CRAFT
        why = ("Every crafter with a gathered recipe is stocked for at least "
               "%d casts (%s), so the family sits down and crafts." % (
                   STOCK_CASTS,
                   "; ".join("%s %d" % (s.name, s.casts) for s in judged)))
    else:
        wanted = standing
        why = ("Nobody is under %d casts and not everybody is over %d, so the "
               "family stays on job=%s rather than re-aiming across the band "
               "(%s)." % (SHORT_CASTS, STOCK_CASTS, standing,
                          "; ".join("%s %d" % (s.name, s.casts)
                                    for s in judged)))

    return Rhythm(mode=wanted, changed=wanted != standing, why=why,
                  stands=stands)


def report(plan: Rhythm) -> str:
    """One line for the log, naming what a person would otherwise have to run
    a query to discover.

    THIS IS HALF THE DELIVERABLE, NOT DECORATION. infra#3696's own words: "a
    character with a correct errand and no materials is indistinguishable from
    one with nothing to do", because DriveCraft's reagent pre-filter is a bare
    `continue`. So every pass says which characters are starved, of what, and
    by how much - whether or not the mode changes - and names the members it
    could form no opinion about, because a permanently unjudged member is the
    one thing here that will never fix itself.
    """
    said = plan.why
    unjudged = [s for s in plan.stands if s.verdict == UNJUDGED]
    if unjudged:
        said += " No opinion formed about: " + "; ".join(s.why for s in unjudged)
    if plan.mode and not plan.changed:
        said += " Already on job=%s, so nothing is written." % plan.mode
    return said
