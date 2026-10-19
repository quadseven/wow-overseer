"""Every class quest a guild member can do, and the next move toward it.

WHY THIS EXISTS. Measured on the dev realm on 2026-10-06: every Bonkers
warrior at level 14 or above (Bigzug, Chillmon, Dreadlox, Fleshless, Ghoulish,
Eyesocket) and three of Cave's (Durg, Hurk, Gronk) lacked Defensive Stance,
Taunt and Sunder Armor. Those spells are the reward of the warrior's level-10
class quest chain (reward spell 8121; the trainers of this realm do not teach
Defensive Stance: trainer_spell holds no row for spell 71). The members HELD
the quest (1498, 1819, 1678 at status 3 in character_queststatus) and never
finished it: nothing sent them to its objective, which is level 9-11 content,
and the leveling walk (guildlevel.py) took them past it to higher hubs. A
warrior that tanks the Deadmines in Battle Stance with no Taunt cannot hold
threat, and the party died in one pull, 0 of 46 clears at those doors.

WHAT A PLAYER DOES. Takes the class quest at its trainer as soon as the level
allows, does the objective, hands it in, and learns the spell. This is that
for one guild member, for every class: the next quest of the chain of every
class reward it lacks, as one move:

  take    walk to the quest giver, then `take quest:<id>`;
  hunt    walk to the creature spawn the objective names (the creature to kill,
          or the creature whose loot is the item), where the member's own grind
          and loot strategies work, as a skinner's field does;
  turnin  walk to the quest ender, then `turnin quest:<id>`.

WHAT IS READ, NOT WRITTEN HERE. The table is built from acore_world at run
time (QUESTS_SQL and its companions), never typed in: a quest is a class quest
when quest_template_addon.AllowableClasses names one class or its QuestSortID
is a class sort, and a reward quest when it grants a spell (RewardSpell or
RewardDisplaySpell). Its chain is the PrevQuestID links back to the first
quest. A member has a reward when it knows the spell or has been rewarded any
quest of the same class and reward.

WHAT IT REFUSES, WITH A NAMED BLOCKER (a member never waits in silence):
  group    a quest that suggests a group or whose objective is an elite: left
           for the ask path (guildsocial), named so here;
  object   an objective that needs a gameobject used and no spawn of it is on
           record, or one this worldserver cannot use yet;
  source   an item with no creature that drops it, no chest that holds it and
           no quest that hands it over, or no spawn row;
  item     a quest item the member must use and no longer carries;
  map      every giver or objective spawn is on another map than the member's:
           walk-to-spawn refuses a spawn on another map. When the spawns are
           on the other classic continent the move is a CROSS (a
           `cross-to-map map:<id>` row) instead; the blocker stands only when
           the module has refused the crossing for good (Member.no_crossing:
           the verb is off, or no transport serves the faction), or when the
           spawns are on a map no boat or zeppelin reaches.
  level    every spawn of the objective is more than OVERLEVEL_MAX levels over
           the member: no pack is chosen that would kill it.

A HUNT LEAVES WHAT THE MODULE REFUSED. A spawn the module refused, or a walk to
which did not reach it (SPAWN_REFUSALS), is left for SPAWN_REFUSED_MINUTES and
the member goes to the next pack of the objective (guildjobs.class_avoid).

WHAT A PLAYER USES (quadseven/mod-overseer#865). Two verbs on kind='quest'
rows, written beside `take quest:` and `turnin quest:`:

  use-item-on creature:<entry> item:<entry>   a carried item used on a creature
  use-gameobject <entry>                      the nearest gameobject clicked

Both fire only when the member already stands beside the target, so a USE move
is a walk to the target's spawn and then the row, as a take is a walk and then
a row. They are read from the world, never typed in:

  item on a creature  an item the quest hands over (StartItem), uses (its
                      source items, ItemDrop1-4) or requires, whose on-use
                      spell (item_template.spellid_1, spelltrigger_1 = 0) is
                      bound by `conditions` (source type 17, condition 31,
                      object type 3) to named creatures: the hunter's Taming
                      Rod and Taming Totem, a druid's Curative Animal Salve;
  gameobject          a required item no creature drops that a chest holds
                      (gameobject_loot_template through a type 3
                      gameobject_template), a use's item that a chest holds
                      and the take does not hand over (Use.fetch), and a
                      negative RequiredNpcOrGo.

THE TAKE HANDS OVER StartItem AND NOTHING ELSE (2026-10-09). The core gives a
quest's StartItem on accept (Player::AddQuest -> GiveQuestSourceItem).
ItemDrop1-4 are source items the quest uses and takes back when it is
abandoned; they are never given. Brug was sent to use a Battle-worn Sword the
take of The Emblazoned Runeblade never gave him, and dropped and took the quest
again and again for it. An item a use needs that the take does not hand over is
fetched first from a chest that holds it; any other item the member must
already hold, and one it does not is a named blocker (the class step buys
nothing). A worldserver that predates the verbs answers `malformed
request: want take quest:...` (classuse.py); the bridge then plans from
Book.plain(), the same book with no uses, and every use quest is named as it
was before. What the verbs do NOT cover stays blocked and named: an item cast
at nothing in particular, at a spell focus (the warlock's Summoning Circle, a
water source) or on a corpse nearby, and a creature a script summons.

WHAT A MEMBER OWES (OWED_*). The operator's rule of 2026-10-06 is that every
class quest is mandatory and comes before anything else, so a member with an
eligible unfinished class quest is held out of every dungeon formation (the
guild's asks, its runs, the pick-up groups, a family's stand-in guests), not
only while a hunt is under way: `owed` reads the book, not the plan line, so a
member waiting out a far walk wall, in combat, dead or in line for a far walk
slot is held too. The blockers no work of the module can lift today (PERMANENT)
do not hold anybody. The hold is bounded by an Owing clock (OWED_HOURS).

PURE MODULE: rows in, a Move out. No MySQL, no clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

# The class a class QuestSortID names, and the class bit AllowableClasses holds.
CLASS_OF_SORT = {
    -81: 1,  # warrior
    -141: 2,  # paladin
    -261: 3,  # hunter
    -372: 6,  # death knight
    -162: 4,  # rogue
    -262: 5,  # priest
    -82: 7,  # shaman
    -161: 8,  # mage
    -61: 9,  # warlock
    -263: 11,  # druid
}
CLASS_NAMES = {
    1: "warrior",
    2: "paladin",
    3: "hunter",
    6: "death knight",
    4: "rogue",
    5: "priest",
    7: "shaman",
    8: "mage",
    9: "warlock",
    11: "druid",
}
# AllowableClasses is a bit mask: bit (class id - 1).
SINGLE_CLASS_MASKS = tuple(1 << (c - 1) for c in sorted(CLASS_NAMES))

WARRIOR = 1

# The classic range: a class quest is built for a member that can take it by
# this level. Beyond it (Outland and Northrend class quests) is another job.
MAX_QUEST_LEVEL = 45

# THE DEATH KNIGHT STARTS AT 55 (2026-10-08). Its starting chain (QuestSortID
# -372, 71 quests, all level 55) is the class's only class quest range this
# module reads, and a death knight is stranded in its starting zone until it is
# done. The class is read to its own level, not the classic cap.
DEATH_KNIGHT = 6
# The death knight's starting zone (map 609): a death knight that stands in it is
# stranded until its chain is done (2026-10-08).
DEATH_KNIGHT_START_MAP = 609
MAX_DEATH_KNIGHT_QUEST_LEVEL = 60

# The core's QuestStatus values a character_queststatus row carries.
STATUS_COMPLETE, STATUS_INCOMPLETE = 1, 3

# The step's action word, in the command log's source (guildjobs.source_for).
ACTION = "classquest"

# A member's plan line carries this while it works a class quest.
MARK = "class quest"

# Move kinds. USE writes a use-item-on or use-gameobject row at a target.
TAKE, HUNT, TURN_IN, USE, BLOCKED = "take", "hunt", "turnin", "use", "blocked"
# A quest dropped to be taken again, so the core hands the member the StartItem
# it lost (a quest item cannot be bought). Only a StartItem comes back so: the
# take gives nothing else, so an item the take never handed over is no reason to
# drop a quest (2026-10-09: the Battle-worn Sword of The Emblazoned Runeblade is
# an ItemDrop, looted from a chest, and dropping the quest never brought it).
ABANDON = "abandon"
# Not asked of the same quest again for this long: if the item is lost again the
# fault is not the quest, and a loop of dropping and taking helps no one.
ABANDON_HOLD_MINUTES = 240
# A quest taken this recently is not judged by the saved bags: the database trails
# the live game, and the StartItem the take handed over may not be in it yet.
TAKE_SETTLE_MINUTES = 45
# CROSS carries the member to the continent its quest is on (a `cross-to-map`
# row); it is the move in place of a MAP blocker while a crossing may be asked.
CROSS = "cross"
# Blockers.
GROUP, OBJECT, SOURCE, MAP, UNKNOWN = "group", "object", "source", "map", "unknown"
# A quest item the member must use and does not carry.
ITEM = "item"
# A hunt that made no progress through every field it was sent to.
STALLED = "stalled"
# Every spawn of the objective is too many levels over the member to hunt.
LEVEL = "level"
# A use the world refused for good, or that changed nothing through every
# target it was sent to.
USE_STALLED = "usestalled"
# The blockers a guildmate can help with: the rest are the module's to fix.
HELPABLE = frozenset({GROUP, STALLED, USE_STALLED})
# THE BLOCKERS NO WORK OF THE MODULE CAN LIFT TODAY: a creature no spawn row
# names (a script summons it), a gameobject no verb uses, a quest item the
# member no longer carries. A member whose every way to a reward ends in one of
# these is not held from the dungeons: nothing it could do would clear them. The
# rest are not permanent: a group or a stalled hunt is asked for in guild chat, a
# far map needs the member to travel (CROSSING_VERB), a level gap closes as it
# levels, and a quest log that has not caught up catches up.
PERMANENT = frozenset({SOURCE, OBJECT, ITEM})

# The two verbs of kind='quest' (quadseven/mod-overseer#865).
USE_ITEM, USE_OBJECT = "use-item-on", "use-gameobject"
# A carried item used where the member stands, beside a spell-focus gameobject
# (mod-overseer `use-item-here`, 2026-10-08).
USE_HERE = "use-item-here"
# A known spell cast at a creature (mod-overseer `use-spell-on`, 2026-10-10): a
# hunter's Tame Beast at the beast it tames (hunterpet.py). No class quest step
# writes it.
USE_SPELL = "use-spell-on"
# The items whose on-use spell works only near a spell-focus gameobject, and
# the focus. The world data does not say it (the spell is in the client DBC, not
# the database), so each is written down: 38607 Battle-worn Sword (spell 51769,
# the death knight's The Emblazoned Runeblade) works beside a Runeforge, spell
# focus 1552; the gameobjects are read from gameobject_template (type 8). The
# take does not hand the sword over (it is the quest's ItemDrop4, not its
# StartItem): it is looted from a Battle-worn Sword chest (gameobject 190584)
# on Acherus, so these items are read in the chest read (CHEST_SQL) too.
#
# THE WARLOCK'S BINDINGS (2026-10-10). Each The Binding hands its item over on
# the take and asks for one Summoned Voidwalker (5676), Succubus (5677) or
# Felhunter (6268) killed. No creature row spawns them: the item's spell needs a
# summoning circle (Spell.dbc RequiresSpellFocus) and sends an event whose
# event_scripts row summons the demon beside it. Voidwalker: 6284 Runes of
# Summoning (Undercity, 43), 7464 Glyphs of Summoning (Orgrimmar, 203), 6928
# Bloodstone Choker (Stormwind, 83), 23732 Voidstone (the Rune of Summoning on
# map 530, 1375). Succubus: 6286 Pure Hearts (43), 6626 Dogran's Pendant (203),
# 6913 Heartswood Core (83). Felhunter: 6999 Tome of the Cabal (the Barrens
# circle, 103, which has no spawn row on the dev realm, so it stays named).
FOCUS_ITEMS = {
    38607: 1552,
    6284: 43,
    7464: 203,
    6928: 83,
    23732: 1375,
    6286: 43,
    6626: 203,
    6913: 83,
    6999: 103,
    # THE SHAMAN'S CALL OF WATER (2026-10-10). 1535, 1536 and 1534 hand over an
    # Empty Waterskin whose spell fills it only beside a water spell focus
    # (Spell.dbc RequiresSpellFocus): 7766 Brown (9586) at the Quilboar Watering
    # Hole (224), 7768 Red (9583) at the Spring Well (226), 7767 Blue (9584) at
    # the Ruins of Stardust Fountain or the Wrathscale Fountain (223).
    7766: 224,
    7768: 226,
    7767: 223,
}

# GROUND A SCRIPT WATCHES (2026-10-10). Two class quest objectives appear only
# when a member stands at one place, so no spawn row holds them and the book
# named both blocked for good:
#   The Affray (1719): Twiggy Flathead's script (npc_twiggy_flathead) starts
#     the fight when a warrior holding the quest comes within 10 yards of him
#     and steps on the grate (x -1684 to -1674, y -4334 to -4324), and summons
#     six challengers and then Big Will (6238). Spawn 13575, a Muck Frenzy
#     (8236), lies on the grate's center, 9.4 yards from Twiggy.
#   The Binding (1795): Acolyte Magaz (6252) summons the Barrens Summoning
#     Circle (gameobject 92388, spell focus 103) at (-770.5, -3720.4) when the
#     quest is taken from Strahad Farsan (smart_scripts 6251 and 625200), and it
#     lasts until the felhunter dies or Strahad walks on, about 15 minutes. The
#     static spawn was deleted upstream (2021_06_11_01.sql). Magaz's spawn 14370
#     stands 4.7 yards from it, inside the circle's 10 yard focus.
# Each names (the creature entry whose spawn marks the ground, that spawn's
# guid); the spawn is read with the objective's (scripted_entries), and the
# walk there ends SCRIPTED_NEAR yards from it, not the place radius of 20.
SCRIPTED_KILLS = {6238: (8236, 13575)}
SCRIPTED_FOCI = {103: (6252, 14370)}
SCRIPTED_NEAR = 2


def scripted_entries() -> frozenset:
    """The creature entries whose spawns mark scripted ground, for the spawn
    read (SPAWNS_SQL)."""
    return frozenset(e for e, _g in (*SCRIPTED_KILLS.values(), *SCRIPTED_FOCI.values()))


# A member this near its target (yards) is already beside it: the use row is
# written with no walk. The module's creature reach is 8 yards.
USE_NEAR = 4.0

# A GROUP-BLOCKED QUEST ASKS FOR THIS MANY HELPERS when the world data names no
# group size (an elite objective): the asker and two make a party of three.
ELITE_HELPERS = 2
MAX_HELPERS = 4

# HOW LONG A MEMBER IS HELD FOR A CLASS QUEST IT MAKES NO PROGRESS ON. Six
# hours: a hunt takes three packs of HUNT_STALL_MINUTES (an hour and a half)
# and GIVE_UP_MINUTES (two hours) before it is asked for in guild chat, and the
# realm's far walk slots are few (nine tank warriors wait their turn at four a
# time, a walk taking up to half an hour), so a member that is making its way
# through the line has made progress inside six hours. One that has not
# (no quest taken, no kill or item counted, nothing handed in) is released
# from the hold, with its ask and its named blocker kept, so a quest nobody can
# finish never keeps a member out of the dungeons for ever.
OWED_HOURS = 6

# THE VERB A CROSS-CONTINENT CLASS QUEST USES. walk-to-spawn refuses a spawn on
# another map; the module's `cross-to-map map:<id>` row (kind='job', any bot,
# guild or roster) walks to the berth of the member's own faction's boat or
# zeppelin, waits for it to dock, boards, rides and walks off on the far
# continent. The module prices the route from its own transport catalogue and
# answers a refusal in the row's result: the bridge keeps no catalogue of its
# own. Overseer.Cross.Enable (default 0) and Overseer.Cross.AtOnce bound it.
CROSSING_VERB = "cross-to-map"
# The source action of a crossing row (guildjobs.source_for), apart from the
# class quest's walks so that none of their clocks read it.
CROSS_ACTION = ACTION + "-cross"
# A member is not asked to cross again for this long after its last crossing
# row: longer than the module's own 30 minute crossing backstop, so one
# crossing is in flight per member and a crossing back and forth never
# runs faster than one an hour.
CROSS_COOLDOWN_MINUTES = 35
# A refusal the module calls retryable (the realm's crossing cap, a fight, a
# dead character) is asked again sooner.
CROSS_RETRY_MINUTES = 10
# The module's refusals that say no crossing will come of asking, in its own
# words (overseer_decisions.h, CrossRefusal): the verb is switched off, or no
# transport serves the member's faction between the two maps. The destination
# stays a named MAP blocker for this long.
CROSS_WALLS = frozenset(
    {
        "crossing is off (Overseer.Cross.Enable)",
        "no transport the module knows sails from this map to that map for this faction",
        "the character is not a bot",
    }
)
CROSS_WALL_MINUTES = 6 * 60

# THE HUNT'S CLOCK. A hunt that makes no progress (the quest's kill and item
# counts do not move) for HUNT_STALL_MINUTES is sent to another pack of the
# objective's spawns, at most MAX_REROLLS times; the last stall gives the quest
# up for GIVE_UP_MINUTES and the member asks guild chat for help instead
# (classask.py). The numbers come from the guild-step conventions in
# guildjobs.COOLDOWN_MINUTES: a farm or a door is asked of a member every 45
# minutes and a craft every 15, so a hunt is judged on 30 (a few respawn cycles
# of an ordinary creature, whose spawn time is 2 to 10 minutes, plus the walk,
# and under the 45 of a farm that would otherwise replace it). Three packs at
# 30 minutes is an hour and a half before the member gives the quest up, and
# 120 minutes is the cool-down the level walk and a sale use for a step that
# keeps failing, long enough that the member is not walked at the same quest
# every pass.
HUNT_STALL_MINUTES = 30
MAX_REROLLS = 2
GIVE_UP_MINUTES = 120
# Two walk rows in a row that ended in error or unchanged are a stall at once:
# the spawn cannot be reached.
FAILED_WALKS = 2

# NEVER A SPAWN WHOSE CREATURE IS MORE THAN THIS MANY LEVELS OVER THE MEMBER. On
# the dev realm on 2026-10-06 members walked to spawns and were killed on the
# way or at them (8 of 163 class quest walks ended "died on the way to the
# spawn"). Three is the module's own lethal gap: it holds a revived character
# out of combat on ground reaching three levels over it.
OVERLEVEL_MAX = 3

# A MEMBER THIS MANY LEVELS OVER A QUEST'S MIN LEVEL SOLOS IT INSTEAD OF
# ASKING FOR HELP (#1094). A level 28 paladin on Redemption (min level 12)
# waited 1h 22m for guild help that never came; at 16 over, the member should
# attempt the quest alone. The solo attempt still goes through the normal
# hunt: if it stalls, the STALLED blocker (in HELPABLE) asks for help.
OVERLEVEL_SOLO_GAP = 10

# A SPAWN THE MODULE REFUSED, OR THAT A WALK DID NOT REACH, IS NOT ASKED OF THE
# SAME MEMBER AGAIN FOR THIS LONG: the member is sent to the next pack of the
# objective instead (guildjobs.class_avoid). These are the module's refusals
# that say the spawn or the way to it is the trouble, in its own words
# (SpawnWalkRefusal): the first step goes over a drop, the way crosses the
# other side's ground, the ground does not hold, the walk stopped getting
# nearer, ran out of time or ended in the member's death, and the spawn is not
# in the world, on this map or in season. The words that name the member's
# state (dead, in combat, held, in flight, a far walk wall) are not here: they
# say nothing about the spawn. The time is GIVE_UP_MINUTES, the hold a hunt
# gets when it stalled through every pack, so a refused spawn and a stalled
# pack are left alone for as long.
SPAWN_REFUSED_MINUTES = 120
# ONLY WORDS THAT SAY THE SPAWN OR THE WAY TO IT IS THE TROUBLE ARE HERE. A walk
# that ran out of time is not (it says the walk was slow, not that the spawn is
# out of reach), nor is anything that names the member's state.
SPAWN_REFUSALS = frozenset(
    {
        "the first step toward the creature goes over a drop",
        "the way to the spawn crosses the other side's ground",
        "the ground toward the spawn does not hold",
        "stopped getting nearer the spawn",
        "died on the way to the spawn",
        "no such spawn in the world",
        "the spawn is on another map than the character",
        "the spawn belongs to a world event that is not running",
    }
)
# A stall or a death on the way is a pack to leave for a short while, not two
# hours: the ground was passable on another try and a member that died comes
# back revived. The other words (a drop, ground that does not hold, the other
# side's ground, no such spawn) are lasting and keep SPAWN_REFUSED_MINUTES.
SPAWN_SHORT_REFUSALS = frozenset(
    {"stopped getting nearer the spawn", "died on the way to the spawn"}
)
SPAWN_SHORT_MINUTES = 30
# A WAY THAT KILLS THE MEMBER TWICE IS NOT A WAY (2026-10-08). The dwarf and the
# gnome warrior whose trainer stands in Stormwind died on the 15,000 yard land
# road three times in a morning, one thirty minute mark after another, because a
# death alone is a short mark and the trainer has one spawn. Two deaths on the
# way to the same spawn within DEATH_WINDOW_MINUTES hold the spawn for
# DEATH_BACKOFF_MINUTES, so the member levels where it is safe meanwhile.
DEATH_REASON = "died on the way to the spawn"
DEATHS_BEFORE_LONG_HOLD = 2
DEATH_WINDOW_MINUTES = 720
DEATH_BACKOFF_MINUTES = 360
# WHEN EVERY PACK IS LEFT, THE ONE LEFT LONGEST IS ASKED AGAIN once its mark is
# this old: a member is never reported stalled while a pack's mark is older.
SPAWN_RETRY_MINUTES = 30
# THE TRIED-STATE EPOCH. Rows of overseer_command with an id at or below this
# are not read as evidence that a pack is out of reach (refused_spawns,
# guildjobs.failed_class_walks): on 2026-10-06 they were filled by refusals the
# module has since fixed (a drop guard, held characters) and by hunts that ended
# because the bags were full. Row ids only grow, so the rows that were there at
# the deploy are ignored once, and the first row after it counts. Bump it past
# the newest row id when a fix makes the older rows untrustworthy again.
TRIED_EPOCH = 632500

# THE REALM'S FAR WALKS ARE FEW (mod-overseer's FarWalkBudgetGate: a handful
# under way at once on the whole realm, a couple of starts per bot per hour).
# A class quest walk the realm refuses for either wall is RETRYABLE: the wall
# moves, the member is not at fault and the spawn is not out of reach. The
# worldserver names the two walls in these words (FarWalkRefusal).
REALM_FULL_REASON = "the realm has as many far walks under way as it allows"
BOT_BUDGET_REASON = "this character has started as many far walks this hour as one may"
# A walk refused because another verb holds the character. The longest hold
# the module places is the one after a revival, 690 seconds; 32 of 163 class
# quest walks on 2026-10-06 were refused this way.
HELD_REASON = "character is held by another verb"
# HOW LONG A MEMBER IS LEFT ALONE AFTER EITHER REFUSAL. The realm wall: a far
# walk on the dev realm took 4 to 266 seconds to finish on 2026-10-06, so a slot
# frees within minutes; 15 minutes is three times the longest of those and more
# than the 10 minute cooldown any class row gets, so a refusal is asked again no
# sooner than a success would be. The member wall: a bot's starts leave the budget window one at a time
# over an hour, so asking sooner than half of it is another refusal; 30 minutes
# is also still inside the window of the oldest start, so no member waits more
# than the hour. Neither doubles: both are bounded by the wall's own clock.
REALM_FULL_BACKOFF_MINUTES = 15
BOT_BUDGET_BACKOFF_MINUTES = 30
# 690 seconds is 11.5 minutes: asked again at 12, the hold has lapsed.
HELD_BACKOFF_MINUTES = 12
# A hunt that killed its target and found no respawn due before its clock ran
# out (mod-overseer#871): a creature with one spawn comes back in many minutes
# (rare and single spawns take 10 to 120), so the member is left alone for
# 15, the same as a full realm, and asks again then; the second such answer in a
# row sends it to another pack (guildjobs.failed_class_walks).
NO_RESPAWN_REASON = "nothing respawns before the clock runs out"
NO_RESPAWN_BACKOFF_MINUTES = 15
# A hunt refused because no living creature of the entry stands in reach
# (mod-overseer answers it `later`). For a creature with SLOW_SPAWNS or fewer
# spawns in the world the one that was there is dead, and the next comes back
# after its `spawntimesecs`: the member waits that long (at least
# RESPAWN_MIN_MINUTES, at most RESPAWN_CAP_MINUTES) instead of asking every
# minute. The refusal is no failure: it never counts toward the hunt clock.
NO_LIVING_REASON = "no living creature of the entry within reach"
SLOW_SPAWNS = 2
RESPAWN_MIN_MINUTES = 5
RESPAWN_CAP_MINUTES = 30
BACKOFF_MINUTES = {
    NO_RESPAWN_REASON: NO_RESPAWN_BACKOFF_MINUTES,
    REALM_FULL_REASON: REALM_FULL_BACKOFF_MINUTES,
    BOT_BUDGET_REASON: BOT_BUDGET_BACKOFF_MINUTES,
    HELD_REASON: HELD_BACKOFF_MINUTES,
}


class FarSlots:
    """The far walk slots the realm has free this pass, spent as a pass starts
    class quest walks so the bridge never writes more rows than the realm can
    take. `free` None means the count is unknown and nothing is held back."""

    def __init__(self, free=None):
        self.free = None if free is None else max(0, int(free))
        self.holders: set = set()

    def take(self, name) -> bool:
        """Spend one slot for `name`; False when none is left."""
        if name in self.holders:
            return True
        if self.free is not None:
            if self.free <= 0:
                return False
            self.free -= 1
        self.holders.add(name)
        return True

    def release(self, name) -> None:
        """Give back the slot `name` took, for a step the plan then refused."""
        if name in self.holders:
            self.holders.discard(name)
            if self.free is not None:
                self.free += 1


# A member this near its hunting ground is hunting; this near a giver is there.
HUNT_REACH = 400.0
# Spawns this close are one pack, for choosing the densest part of a field.
PACK_YARDS = 120.0
# A creature of this rank or above (elite, rare elite, boss) is a group kill.
ELITE_RANK = 1

_SORTS = ", ".join(str(s) for s in sorted(CLASS_OF_SORT))
_MASKS = ", ".join(str(m) for m in SINGLE_CLASS_MASKS)

_NPCS = "".join(
    "q.RequiredNpcOrGo%d AS npc%d, q.RequiredNpcOrGoCount%d AS npc_count%d, "
    % (i, i, i, i)
    for i in range(1, 5)
)
_ITEMS = "".join(
    "q.RequiredItemId%d AS item%d, q.RequiredItemCount%d AS item_count%d, "
    % (i, i, i, i)
    for i in range(1, 7)
)
# The item a quest hands over when it is taken: StartItem, and nothing else
# (Player::AddQuest -> GiveQuestSourceItem). ItemDrop1-4 are its source items:
# the quest uses them and takes them back when it is abandoned, never gives them.
_PROVIDED = "q.StartItem AS provided0, " + "".join(
    "q.ItemDrop%d AS source%d, " % (i, i) for i in range(1, 5)
)

# Every class quest of the classic range, one row each.
# Built from this module's own integer constants only (S608 does not apply).
QUESTS_SQL = (  # noqa: S608
    "SELECT q.ID AS id, q.LogTitle AS title, q.QuestSortID AS sort, "
    "q.MinLevel AS min_level, q.AllowableRaces AS races, "
    "COALESCE(a.AllowableClasses, 0) AS classes, "
    "COALESCE(a.PrevQuestID, 0) AS prev, "
    "COALESCE(a.ExclusiveGroup, 0) AS exclusive, q.RewardSpell AS reward, "
    "q.RewardDisplaySpell AS display, q.SuggestedGroupNum AS grp, "
    + _NPCS
    + _ITEMS
    + _PROVIDED
    + "0 AS pad FROM acore_world.quest_template q "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = q.ID "
    "WHERE (a.AllowableClasses IN ("
    + _MASKS
    + ") OR q.QuestSortID IN ("
    + _SORTS
    + ")) "
    "AND q.MinLevel <= CASE WHEN COALESCE(a.AllowableClasses, 0) = "
    + str(1 << (DEATH_KNIGHT - 1))
    + " OR q.QuestSortID = -372 THEN "
    + str(MAX_DEATH_KNIGHT_QUEST_LEVEL)
    + " ELSE "
    + str(MAX_QUEST_LEVEL)
    + " END AND q.LogTitle NOT LIKE '<%%' "
    "AND q.LogTitle NOT LIKE 'NOT A QUEST%%'"
)

# The creatures that start and end each quest, with every spawn of them.
GIVERS_SQL = (
    "SELECT s.quest AS quest, 'start' AS role, c.guid AS guid, c.id AS entry, "
    "c.map AS map_id, c.position_x AS x, c.position_y AS y, ct.name AS name, "
    "c.position_z AS z "
    "FROM acore_world.creature_queststarter s "
    "JOIN acore_world.creature c ON c.id = s.id "
    "JOIN acore_world.creature_template ct ON ct.entry = c.id "
    "WHERE s.quest IN ({quests}) "
    "UNION ALL "
    "SELECT e.quest, 'end', c.guid, c.id, c.map, c.position_x, c.position_y, ct.name, "
    "c.position_z "
    "FROM acore_world.creature_questender e "
    "JOIN acore_world.creature c ON c.id = e.id "
    "JOIN acore_world.creature_template ct ON ct.entry = c.id "
    "WHERE e.quest IN ({quests})"
)

# The other ways a quest starts: a gameobject offers it, or an item starts it
# when used. Neither has a verb, but the blocker names which one it is.
STARTERS_SQL = (
    "SELECT s.quest AS quest, 'gameobject' AS kind, s.id AS entry "
    "FROM acore_world.gameobject_queststarter s WHERE s.quest IN ({quests}) "
    "UNION ALL "
    "SELECT it.startquest, 'item', it.entry FROM acore_world.item_template it "
    "WHERE it.startquest IN ({quests})"
)

# The reward spells a trainer teaches for coin: not a class quest's to give.
TRAINED_SQL = (
    "SELECT DISTINCT SpellId AS spell FROM acore_world.trainer_spell "
    "WHERE SpellId IN ({spells})"
)

# Which creatures drop a required item.
LOOT_SQL = (
    "SELECT l.Item AS item, ct.entry AS entry FROM acore_world.creature_loot_template l "
    "JOIN acore_world.creature_template ct ON ct.lootid = l.Entry "
    "WHERE l.Item IN ({items})"
)

# The items whose on-use spell is bound to named creatures: the spell's target
# condition (source type 17, "object entry", type 3 = a creature, applied to
# the spell's target). A spell with no such row (a self cast, a spell focus, a
# corpse nearby) is not a use-item-on.
USE_ITEMS_SQL = (
    "SELECT it.entry AS item, c.ConditionValue2 AS target "
    "FROM acore_world.item_template it "
    "JOIN acore_world.conditions c ON c.SourceTypeOrReferenceId = 17 "
    "AND c.SourceEntry = it.spellid_1 AND c.ConditionTypeOrReference = 31 "
    "AND c.ConditionValue1 = 3 AND c.ConditionTarget = 1 "
    "AND c.NegativeCondition = 0 "
    "WHERE it.spelltrigger_1 = 0 AND it.entry IN ({items})"
)

# The spell-focus gameobjects (type 8) of the foci FOCUS_ITEMS names.
FOCUS_OBJECTS_SQL = (
    "SELECT g.Data0 AS focus, g.entry AS entry FROM acore_world.gameobject_template g "
    "WHERE g.type = 8 AND g.Data0 IN ({focus})"
)

# The chests (gameobject type 3) whose loot holds a required item, or an item a
# use needs that the take does not hand over (a source item, a FOCUS_ITEMS item).
CHEST_SQL = (
    "SELECT l.Item AS item, g.entry AS entry "
    "FROM acore_world.gameobject_loot_template l "
    "JOIN acore_world.gameobject_template g ON g.type = 3 AND g.Data1 = l.Entry "
    "WHERE l.Item IN ({items})"
)

# Every spawn of the gameobjects a quest uses (a chest, an objective, a spell
# focus), with its height: a death knight on the ground below Acherus is told
# from one beside the sword chest or the Runeforge by height alone
# (guildjobs.below_its_giver).
OBJECT_SPAWNS_SQL = (
    "SELECT o.guid AS guid, o.id AS entry, o.map AS map_id, o.position_x AS x, "
    "o.position_y AS y, gt.name AS name, 0 AS `rank`, 0 AS level, "
    "o.position_z AS z "
    "FROM acore_world.gameobject o "
    "JOIN acore_world.gameobject_template gt ON gt.entry = o.id "
    "WHERE o.id IN ({entries})"
)

# Every spawn of the creatures an objective names.
SPAWNS_SQL = (
    "SELECT c.guid AS guid, c.id AS entry, c.map AS map_id, c.position_x AS x, "
    "c.position_y AS y, ct.name AS name, ct.`rank` AS `rank`, "
    "ct.maxlevel AS level, c.spawntimesecs AS respawn "
    "FROM acore_world.creature c "
    "JOIN acore_world.creature_template ct ON ct.entry = c.id "
    "WHERE c.id IN ({entries})"
)

# What one member holds: the quests in its log, the quests it has been
# rewarded, and the spells it knows (guildjobs reads the last already).
LOG_SQL = (
    "SELECT guid, quest, status, "
    "(mobcount1 + mobcount2 + mobcount3 + mobcount4 + itemcount1 + itemcount2 + "
    "itemcount3 + itemcount4 + itemcount5 + itemcount6) AS progress "
    "FROM character_queststatus "
    "WHERE guid IN ({guids}) AND quest IN ({quests}) AND status IN (1, 3)"
)
REWARDED_SQL = (
    "SELECT guid, quest FROM character_queststatus_rewarded "
    "WHERE guid IN ({guids}) AND quest IN ({quests})"
)


@dataclass(frozen=True)
class Spawn:
    """A creature spawn row of the world, by its guid."""

    guid: int
    entry: int
    map_id: int
    x: float
    y: float
    name: str = ""
    rank: int = 0
    # The creature's top level; 0 when the row does not say.
    level: int = 0
    # The spawn's respawn time in seconds (`spawntimesecs`); 0 when not read.
    respawn: int = 0
    # The spawn's height; None when the row does not say (2026-10-09: a death
    # knight below Acherus is told from one standing on it by height alone).
    z: float | None = None
    # Scripted ground (SCRIPTED_KILLS, SCRIPTED_FOCI): the walk ends this near
    # the spawn (0: the place radius), and a focus's ground is a creature spawn.
    near: int = 0
    creature: bool = False


@dataclass(frozen=True)
class Use:
    """One thing the quest has the member use, and where.

    `verb` is USE_HERE (item `item` used where the member stands, beside a
    gameobject of `targets`), USE_ITEM (item `item` used on a creature of `targets`) or
    USE_OBJECT (a gameobject of `targets` clicked: a chest that holds `count`
    of `item`, or an objective gameobject when `item` is 0). `spots` are the
    spawns of the targets. `provided` is True for an item the quest hands over
    when it is taken (its StartItem, nothing else). `fetch` is the USE_OBJECT
    that gets `item` first, from the chests that hold it, for an item the take
    does not hand over; None when no chest holds it or the take hands it over."""

    verb: str
    item: int = 0
    count: int = 1
    targets: tuple = ()
    spots: tuple = ()
    provided: bool = False
    fetch: Use | None = None


@dataclass(frozen=True)
class Quest:
    id: int
    title: str
    klass: int
    min_level: int
    races: int
    prev: int
    reward: int
    display: int
    group: int
    # (creature entry, count) to kill, and (item entry, count) to collect.
    kills: tuple = ()
    items: tuple = ()
    # A required gameobject (a negative RequiredNpcOrGo), which no verb uses.
    objects: tuple = ()
    starters: tuple = ()
    enders: tuple = ()
    # Spawns of every creature that satisfies an objective.
    fields: tuple = ()
    # What the quest has the member use (use-item-on, use-gameobject), and the
    # item it hands over when taken (its StartItem).
    uses: tuple = ()
    provided: tuple = ()
    # Required items a creature with a spawn drops.
    droppable: frozenset = frozenset()
    # (required item, creature entry that drops it) for every dropper with a spawn.
    drops: tuple = ()
    # (kind, entry) of each non-creature start: a gameobject or an item.
    other_starts: tuple = ()
    # quest_template_addon.ExclusiveGroup: a positive group lets a player take
    # only one of its quests (taking or finishing one closes the rest).
    exclusive: int = 0
    # The quest's source items (ItemDrop1-4): what it uses and takes back when it
    # is abandoned. The take does NOT hand them over.
    sources: tuple = ()

    @property
    def spells(self) -> frozenset:
        return frozenset(s for s in (self.reward, self.display) if s)

    @property
    def rewards(self) -> bool:
        return bool(self.spells)

    def admits(self, race: int) -> bool:
        return not self.races or bool(int(self.races) & (1 << (int(race) - 1)))


@dataclass(frozen=True)
class Book:
    """Every class quest, and the reward groups they make."""

    quests: dict = field(default_factory=dict)
    # (class, reward spells) -> reward quest ids
    groups: dict = field(default_factory=dict)
    # Reward spells a trainer teaches: those groups are the trainer's, not a quest's.
    trained: frozenset = frozenset()

    def quest_ids(self) -> list:
        return sorted(self.quests)

    def spell_ids(self) -> list:
        return sorted({s for q in self.quests.values() for s in q.spells})

    def plain(self) -> "Book":
        """The same book with no uses: what the planner works from while the
        worldserver does not carry the use verbs (classuse.py)."""
        if not any(q.uses for q in self.quests.values()):
            return self
        # A quest that had a use keeps no StartItem either: a Taming Rod asked
        # back is no delivery while nothing can use it (blocker_of, _unmet).
        quests = {
            i: replace(q, uses=(), provided=()) if q.uses else q
            for i, q in self.quests.items()
        }
        return Book(quests, self.groups, self.trained)

    def watch_items(self) -> list:
        """The item entries to read from a member's bags: every use item, the
        items a use quest hands over and the items it requires."""
        out = set()
        for q in self.quests.values():
            # A dropped item is read too: the hunt asks for what is still missing.
            out.update(i for i, _n in q.items if i in q.droppable)
            if q.uses:
                out.update(q.provided)
                out.update(i for i, _n in q.items)
                out.update(u.item for u in q.uses if u.item)
        return sorted(out)

    def use_entries(self) -> tuple:
        """(creature entries, gameobject entries) the uses target, for the
        spawn reads."""
        creatures, objects = set(), set()
        for q in self.quests.values():
            for u in q.uses:
                (creatures if u.verb == USE_ITEM else objects).update(u.targets)
                if u.fetch is not None:
                    objects.update(u.fetch.targets)
        return sorted(creatures), sorted(objects)


@dataclass(frozen=True)
class Move:
    """One thing a member does toward a class quest, or why it cannot."""

    kind: str
    quest: int = 0
    klass: int = 0
    spot: Spawn | None = None
    said: str = ""
    blocker: str = ""
    why: str = ""
    # For a blocker a guildmate can help with: how many helpers, the quest's
    # title, and the objective's spawn the group would go to.
    want: int = 0
    title: str = ""
    # For a USE move: what is used at `spot`.
    use: Use | None = None
    # For a CROSS move: the map id of the continent to cross to.
    to_map: int = -1


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def klass_of(row) -> int:
    """The one class a quest row belongs to, 0 when it names none or several."""
    mask = _int(row.get("classes"))
    if mask in SINGLE_CLASS_MASKS:
        return mask.bit_length()
    return CLASS_OF_SORT.get(_int(row.get("sort")), 0)


def _pairs(row, key, count, span, positive=True) -> tuple:
    out = []
    for i in range(1, span + 1):
        entry = _int(row.get("%s%d" % (key, i)))
        if entry and (entry > 0) == positive:
            out.append((abs(entry), max(1, _int(row.get("%s%d" % (count, i))))))
    return tuple(out)


def _spawn(r) -> Spawn:
    return Spawn(
        _int(r.get("guid")),
        _int(r.get("entry")),
        _int(r.get("map_id")),
        float(r.get("x") or 0.0),
        float(r.get("y") or 0.0),
        str(r.get("name") or ""),
        _int(r.get("rank")),
        _int(r.get("level")),
        _int(r.get("respawn")),
        None if r.get("z") is None else float(r.get("z")),
    )


def _givers(giver_rows) -> tuple:
    """(quest -> start spawns, quest -> end spawns) from GIVERS_SQL's rows."""
    starts, ends = {}, {}
    for r in giver_rows or ():
        side = starts if r.get("role") == "start" else ends
        side.setdefault(_int(r.get("quest")), []).append(_spawn(r))
    return starts, ends


def _spawns_by_entry(spawn_rows) -> dict:
    out = {}
    for r in spawn_rows or ():
        out.setdefault(_int(r.get("entry")), []).append(_spawn(r))
    return out


def _ground(by_entry, mark):
    """The spawn a SCRIPTED_KILLS or SCRIPTED_FOCI entry names, None when the
    spawn read does not hold it."""
    entry, guid = mark
    return next((s for s in by_entry.get(entry, ()) if s.guid == guid), None)


def _with_scripted_kills(by_entry) -> dict:
    """`by_entry` with each script-summoned creature that has no spawn row at the
    ground its script watches (SCRIPTED_KILLS): a spawn of its own entry there."""
    out = dict(by_entry)
    for kill, mark in SCRIPTED_KILLS.items():
        ground = _ground(by_entry, mark)
        if ground is not None and not out.get(kill):
            out[kill] = [
                replace(
                    ground,
                    entry=kill,
                    rank=0,
                    level=0,
                    near=SCRIPTED_NEAR,
                    creature=True,
                )
            ]
    return out


def _droppers(loot_rows) -> dict:
    out = {}
    for r in loot_rows or ():
        out.setdefault(_int(r.get("item")), set()).add(_int(r.get("entry")))
    return out


def _targets(rows, key="item", value="target") -> dict:
    """item entry -> the sorted entries a use read names for it."""
    out: dict = {}
    for r in rows or ():
        out.setdefault(_int(r.get(key)), set()).add(_int(r.get(value)))
    return {k: tuple(sorted(v - {0})) for k, v in out.items()}


def _focus_targets(rows) -> dict:
    """item entry -> the spell-focus gameobject entries (FOCUS_OBJECTS_SQL rows
    carry the focus; FOCUS_ITEMS says which item works at which)."""
    by_focus: dict = {}
    for r in rows or ():
        by_focus.setdefault(_int(r.get("focus")), set()).add(_int(r.get("entry")))
    return {
        item: tuple(sorted(by_focus.get(focus, set()) - {0}))
        for item, focus in FOCUS_ITEMS.items()
        if by_focus.get(focus)
    }


def _provided(r) -> tuple:
    """The item the quest hands over when it is taken: its StartItem, or ()."""
    entry = _int(r.get("provided0"))
    return (entry,) if entry else ()


def _sources(r) -> tuple:
    """The quest's source items (ItemDrop1-4), which the take does not hand
    over: the quest uses them and takes them back when it is abandoned."""
    seen = []
    for i in range(1, 5):
        entry = _int(r.get("source%d" % i))
        if entry and entry not in seen:
            seen.append(entry)
    return tuple(seen)


def _chest_fetch(item, aims):
    """The USE_OBJECT that gets `item` from the chests that hold it, None when
    no chest does."""
    _item_aims, chests, _creature_spawns, object_spawns = aims[:4]
    found = chests.get(item, ())
    if not found:
        return None
    spots = tuple(s for g in found for s in object_spawns.get(g, ()))
    return Use(USE_OBJECT, item, 1, found, spots)


def _item_use(item, provided, aims):
    """The Use of one item the member uses: beside a spell-focus gameobject
    (USE_HERE), or on a creature (USE_ITEM); None when it has no target. An
    item the take does not hand over carries the chest it is fetched from."""
    item_aims, _chests, creature_spawns, object_spawns = aims[:4]
    focus = aims[4] if len(aims) > 4 else {}
    handed = item in provided
    fetch = None if handed else _chest_fetch(item, aims)
    foci = focus.get(item, ())
    if foci:
        spots = tuple(s for g in foci for s in object_spawns.get(g, ()))
        if not spots:
            spots = _scripted_focus(item, creature_spawns)
        return Use(USE_HERE, item, 1, foci, spots, handed, fetch)
    targets = item_aims.get(item, ())
    if targets:
        spots = tuple(s for t in targets for s in creature_spawns.get(t, ()))
        return Use(USE_ITEM, item, 1, targets, spots, handed, fetch)
    return None


def _scripted_focus(item, creature_spawns) -> tuple:
    """The ground beside which a script summons the spell focus `item` works at
    (SCRIPTED_FOCI), as a spawn the walk ends SCRIPTED_NEAR yards from; () when
    the focus has none or the spawn read does not hold it."""
    mark = SCRIPTED_FOCI.get(FOCUS_ITEMS.get(item))
    ground = _ground(creature_spawns, mark) if mark else None
    if ground is None:
        return ()
    return (replace(ground, near=SCRIPTED_NEAR, creature=True),)


def _uses(r, items, provided, droppers, aims) -> tuple:
    """The Uses of one quest: items used beside a forge or on creatures (each
    fetched first from a chest when the take does not hand it over), chests
    that hold a required item no creature drops, and gameobject objectives.

    `aims` is (item -> creature entries, item -> chest entries, spawns by
    creature entry, spawns by gameobject entry, item -> spell-focus
    gameobject entries)."""
    _item_aims, chests, creature_spawns, object_spawns = aims[:4]
    out = []
    required = [i for i, _n in items]
    for item in dict.fromkeys([*provided, *_sources(r), *required]):
        use = _item_use(item, provided, aims)
        if use is not None:
            out.append(use)
    for item, count in items:
        if item in provided or any(
            creature_spawns.get(e) for e in droppers.get(item, ())
        ):
            continue
        found = chests.get(item, ())
        if found:
            spots = tuple(s for g in found for s in object_spawns.get(g, ()))
            out.append(Use(USE_OBJECT, item, count, found, spots))
    for entry, count in _pairs(r, "npc", "npc_count", 4, False):
        spots = tuple(object_spawns.get(entry, ()))
        out.append(Use(USE_OBJECT, 0, count, (entry,), spots))
    return tuple(out)


def _quest(r, klass, starts, ends, by_entry, droppers, aims, others=None) -> Quest:
    kills = _pairs(r, "npc", "npc_count", 4, True)
    items = _pairs(r, "item", "item_count", 6)
    entries = {e for e, _n in kills}
    for item, _n in items:
        entries |= droppers.get(item, set())
    qid = _int(r.get("id"))
    provided = _provided(r)
    return Quest(
        qid,
        str(r.get("title") or ""),
        klass,
        _int(r.get("min_level")),
        _int(r.get("races")),
        abs(_int(r.get("prev"))),
        _int(r.get("reward")),
        _int(r.get("display")),
        _int(r.get("grp")),
        kills,
        items,
        _pairs(r, "npc", "npc_count", 4, False),
        tuple(starts.get(qid, ())),
        tuple(ends.get(qid, ())),
        tuple(s for e in sorted(entries) for s in by_entry.get(e, ())),
        _uses(r, items, provided, droppers, aims),
        provided,
        frozenset(
            i for i, _n in items if any(by_entry.get(e) for e in droppers.get(i, ()))
        ),
        tuple(
            (i, e)
            for i, _n in items
            for e in sorted(droppers.get(i, ()))
            if by_entry.get(e)
        ),
        tuple((others or {}).get(qid, ())),
        max(0, _int(r.get("exclusive"))),
        _sources(r),
    )


def _orphan(quest: Quest) -> bool:
    """A quest nothing starts: no creature, gameobject or item, and no earlier
    quest in a chain to offer it. On the dev realm (2026-10-08) the level 10
    racial priest spell quests (Desperate Prayer, Hex of Weakness, Stars of
    Elune and the rest) are all of this kind: retired in 3.3.5, their spells
    taught by the class trainer, and each one blocked a priest of both guilds
    for good with 'has no giver creature in the world data'."""
    return not quest.starters and not quest.other_starts and not quest.prev


def _other_starts(rows) -> dict:
    """quest -> sorted (kind, entry) of the gameobjects and items that start it."""
    out: dict = {}
    for r in rows or ():
        out.setdefault(_int(r.get("quest")), set()).add(
            (str(r.get("kind") or ""), _int(r.get("entry")))
        )
    return {k: tuple(sorted(v)) for k, v in out.items()}


def build(
    quest_rows,
    giver_rows,
    spawn_rows,
    loot_rows,
    trained_rows=(),
    use_rows=(),
    chest_rows=(),
    object_rows=(),
    focus_rows=(),
    start_rows=None,
    every=False,
) -> Book:
    """The Book from the world's rows.

    `giver_rows` are GIVERS_SQL's, `spawn_rows` SPAWNS_SQL's for every creature
    an objective names (a creature to kill, one that drops a required item, or
    one an item is used on) and `loot_rows` LOOT_SQL's. `use_rows` are
    USE_ITEMS_SQL's, `chest_rows` CHEST_SQL's and `object_rows`
    OBJECT_SPAWNS_SQL's: with none of them no quest has a use, as on a world
    read before the verbs existed. `start_rows` are STARTERS_SQL's: the quests a
    gameobject or an item starts.
    """
    starts, ends = _givers(giver_rows)
    others = _other_starts(start_rows)
    by_entry = _with_scripted_kills(_spawns_by_entry(spawn_rows))
    droppers = _droppers(loot_rows)
    aims = (
        _targets(use_rows),
        _targets(chest_rows, "item", "entry"),
        by_entry,
        _spawns_by_entry(object_rows),
        _focus_targets(focus_rows),
    )
    quests = {}
    for r in quest_rows or ():
        klass = klass_of(r)
        if klass or every:
            quest = _quest(r, klass, starts, ends, by_entry, droppers, aims, others)
            # With the other starters read (start_rows given), a quest nothing
            # starts is not a class quest anyone can have.
            if start_rows is not None and _orphan(quest):
                continue
            quests[_int(r.get("id"))] = quest
    groups = {}
    for q in quests.values():
        if q.rewards:
            groups.setdefault((q.klass, tuple(sorted(q.spells))), []).append(q.id)
    trained = frozenset(_int(r.get("spell")) for r in trained_rows or ())
    return Book(quests, {k: sorted(v) for k, v in groups.items()}, trained)


def chain(book: Book, quest_id: int) -> list:
    """The quests from the first of the chain to `quest_id`, oldest first. A
    quest the book does not hold ends the walk back (a prerequisite of another
    class's or an unreadable one)."""
    out, seen, at = [], set(), int(quest_id)
    while at and at in book.quests and at not in seen:
        seen.add(at)
        out.append(at)
        at = book.quests[at].prev
    return out[::-1]


def has_reward(book: Book, member, key) -> bool:
    """True when the member knows the reward's spells, or has been rewarded
    any quest that grants them."""
    klass, spells = key
    if any(s in member.known for s in spells):
        return True
    done = member.quests_done
    return any(q in done for q in book.groups.get(key, ()))


def _yards(member, spawn) -> float:
    return math.hypot(float(member.x) - spawn.x, float(member.y) - spawn.y)


def _nearest(member, spawns):
    """The spawn nearest the member on its map, None when none is."""
    here = [s for s in spawns if int(s.map_id) == int(member.map_id)]
    return min(here, key=lambda s: (_yards(member, s), s.guid)) if here else None


def _avoids(spawn, avoid) -> bool:
    return any(
        int(spawn.map_id) == int(m)
        and math.hypot(spawn.x - x, spawn.y - y) <= PACK_YARDS
        for m, x, y in avoid or ()
    )


def _densest(member, spawns, avoid=()):
    """The spawn on the member's map with the most others within PACK_YARDS,
    the nearest of those; None when none is on the map. A spawn within
    PACK_YARDS of a place in `avoid` ((map, x, y), a pack already tried) is
    left out."""
    here = [
        s
        for s in spawns
        if int(s.map_id) == int(member.map_id) and not _avoids(s, avoid)
    ]
    if not here:
        return None
    packs = _pack_sizes(here)
    best = min(
        range(len(here)),
        key=lambda i: (-packs[i], _yards(member, here[i]), here[i].guid),
    )
    return here[best]


def _pack_sizes(here) -> list:
    """For each spawn of `here`, how many spawns of `here` (itself included)
    stand within PACK_YARDS of it.

    Each spawn is measured only against the spawns of its own and the eight
    neighbouring grid cells, not against every other spawn (#833, 2026-10-18:
    after the first cut, the all-pairs count, run for each hunt move of each
    member twice a pass, was still 85% of a synthetic guild job plan of 200
    quests x 150 spawns x 142 members). A cell is a yard wider than
    PACK_YARDS, so two spawns within PACK_YARDS are always in neighbouring
    cells, float rounding at a cell edge included."""
    if not all(math.isfinite(s.x) and math.isfinite(s.y) for s in here):
        # No grid cell for a coordinate that is not a number: measure all pairs.
        return [
            sum(1 for o in here if math.hypot(o.x - s.x, o.y - s.y) <= PACK_YARDS)
            for s in here
        ]
    cell = PACK_YARDS + 1.0
    cells: dict = {}
    keys = []
    for i, s in enumerate(here):
        key = (math.floor(s.x / cell), math.floor(s.y / cell))
        keys.append(key)
        cells.setdefault(key, []).append(i)
    out = []
    for s, (cx, cy) in zip(here, keys, strict=True):
        n = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cells.get((cx + dx, cy + dy), ()):
                    o = here[j]
                    if math.hypot(o.x - s.x, o.y - s.y) <= PACK_YARDS:
                        n += 1
        out.append(n)
    return out


# The two classic continents, by map id, for the crossing sentence.
CONTINENTS = {0: "Eastern Kingdoms", 1: "Kalimdor"}


def far_map(member, spawns) -> int:
    """The classic continent a class quest's spawns are on when none is on the
    member's map and the member stands on the other one, else -1: the member
    must cross to get there (a boat, a zeppelin), as a player does."""
    here = member.map_id
    if here is None or int(here) not in CONTINENTS:
        return -1
    other = {int(s.map_id) for s in spawns if int(s.map_id) in CONTINENTS}
    other.discard(int(here))
    if not other or any(int(s.map_id) == int(here) for s in spawns):
        return -1
    return min(other)


def _walled(member, there) -> str:
    """The module's reason it will not cross the member to map `there`, "" when
    no refusal stands (Member.no_crossing, map id -> reason)."""
    return str((getattr(member, "no_crossing", None) or {}).get(int(there), ""))


def _across(member, spawns) -> str:
    """The sentence ending a MAP blocker: where the quest is and why the member
    does not cross, or "" when the spawns are not on the other continent."""
    there = far_map(member, spawns)
    if there < 0:
        return ""
    wall = _walled(member, there)
    return (
        "; it is on %s, a boat or zeppelin away, and the module will not cross "
        "the member (%s)"
        % (
            CONTINENTS[there],
            wall or "no crossing asked yet",
        )
    )


def is_cross_row(command) -> bool:
    return str(command or "").split(" ", 1)[0] == CROSSING_VERB


def cross_command(map_id) -> str:
    return "%s map:%d" % (CROSSING_VERB, int(map_id))


def _block_spawns(quest: Quest, member) -> list:
    """The spawns whose map made blocker_of say MAP."""
    if quest.uses:
        use = _pending_use(quest, member)
        if use is not None and use.spots:
            return list(use.spots)
    return list(quest.fields)


def _crossing(member, quest: Quest, why: str, blocked: Move, spawns=None) -> Move:
    """A CROSS move in place of `blocked` when it is a MAP blocker whose spawns
    (`spawns`, else the hunt's own: _block_spawns) are all on the other
    continent and the module has not refused the crossing; else `blocked`."""
    if blocked.blocker != MAP:
        return blocked
    if spawns is None:
        spawns = _block_spawns(quest, member)
    there = far_map(member, spawns)
    if there < 0 or _walled(member, there):
        return blocked
    said = "%s crosses to %s by its faction's boat or zeppelin for %s" % (
        member.name,
        CONTINENTS[there],
        why,
    )
    return Move(
        CROSS, quest.id, quest.klass, None, said, "", why, 0, quest.title, None, there
    )


def _source_blocker(quest: Quest) -> tuple:
    return SOURCE, (
        "%s needs %s no creature spawn or drop supplies (an item used on a "
        "creature, or a summoned spawn): the module has no verb for it"
        % (quest.title, "an objective" if quest.kills else "an item")
    )


def _unmet(quest: Quest) -> bool:
    """True when something the quest requires has no source at all: an item
    no creature drops, no chest holds and the quest does not hand over, or a
    kill with no spawn that no item use credits."""
    spawned = {s.entry for s in quest.fields}
    chested = {u.item for u in quest.uses if u.verb == USE_OBJECT and u.item}
    given = set(quest.provided)
    # A kill is credited by an item used on a creature, or by the creature an
    # item used beside a spell focus summons there (a warlock's Binding).
    fed = any(u.verb in (USE_ITEM, USE_HERE) for u in quest.uses)
    # An item made by using another beside a forge is no unmet source.
    made = any(u.verb == USE_HERE for u in quest.uses)
    if any(e not in spawned and not fed for e, _n in quest.kills):
        return True
    return any(
        i not in chested and i not in given and i not in quest.droppable and not made
        for i, _n in quest.items
    )


def _hunting(quest: Quest, member) -> bool:
    """True while the quest has creatures to hunt: a kill with a spawn, or a
    dropped item the member does not yet carry in full. A creature credited
    by using a quest item is a use target, not a kill target."""
    # _pending_use runs only after hunting ends. Keep item-use objectives out
    # of this set so a spawn does not make the item use unreachable.
    used = {
        entry for use in quest.uses if use.verb == USE_ITEM for entry in use.targets
    }
    kills = {e for e, _n in quest.kills if e not in used}
    if any(s.entry in kills for s in quest.fields):
        return True
    return any(member.count(i) < n for i, n in quest.items if i in quest.droppable)


def _pending_use(quest: Quest, member):
    """The Use the member has next, None when it has none or must hunt first.
    A use whose item the member lacks and the take did not hand over is its
    chest first (Use.fetch)."""
    if not quest.uses or _hunting(quest, member):
        return None
    for use in quest.uses:
        if use.verb == USE_OBJECT and use.item and member.count(use.item) >= use.count:
            continue
        if use.verb == USE_HERE and _made_here(quest, use, member):
            continue
        if use.fetch is not None and not member.carries(use.item):
            return use.fetch
        return use
    return None


def _made_here(quest: Quest, use: Use, member) -> bool:
    """True when a USE_HERE has done its work: the member carries every item it
    makes, the quest's required items other than the one it uses. A use whose
    item is the quest's only required item makes nothing to carry (a Binding's
    choker summons a demon to kill), so it is never done while the quest is
    incomplete."""
    made = [(i, n) for i, n in quest.items if i != use.item]
    return bool(made) and all(member.count(i) >= n for i, n in made)


def _missing_item_blocker(quest: Quest, member, use: Use) -> tuple:
    """(ITEM, sentence) when the item a use needs is not carried, else ("", "").
    A quest TAKEN lately handed its StartItem over, whatever the saved bags say
    yet; an item the take does not hand over is never assumed carried so."""
    handed = use.provided and quest.id in getattr(member, "recently_taken", ())
    if use.verb not in (USE_ITEM, USE_HERE) or member.carries(use.item) or handed:
        return "", ""
    how = (
        "the take handed it over and it is lost"
        if use.provided
        else "the take does not hand it over and no chest holds it"
    )
    return ITEM, (
        "%s needs item %d used and the member does not carry it (%s; the class "
        "step buys nothing)" % (quest.title, use.item, how)
    )


def _use_blocker(quest: Quest, member) -> tuple:
    """(kind, sentence) when a quest with uses cannot be done now, else
    ("", "")."""
    if _elite_only(quest):
        return GROUP, "%s's objective is an elite" % quest.title
    if _unmet(quest):
        return _source_blocker(quest)
    use = _pending_use(quest, member)
    if use is None:
        if quest.fields and _nearest(member, quest.fields) is None:
            return MAP, "%s's objective is on another map than the member%s" % (
                quest.title,
                _across(member, quest.fields),
            )
        return "", ""
    if not use.spots:
        what = "gameobject" if use.verb in (USE_OBJECT, USE_HERE) else "creature"
        return (
            OBJECT,
            "%s needs a %s used (entry %s has no spawn row in the world data)"
            % (
                quest.title,
                what,
                "/".join(str(t) for t in use.targets),
            ),
        )
    if _nearest(member, use.spots) is None:
        return MAP, "%s's use target is on another map than the member%s" % (
            quest.title,
            _across(member, use.spots),
        )
    return _missing_item_blocker(quest, member, use)


def _all_elite(spawns) -> bool:
    spawns = list(spawns)
    return bool(spawns) and all(s.rank >= ELITE_RANK for s in spawns)


def _elite_only(quest: Quest) -> bool:
    """True when some objective can be met only at an elite: every spawn of a
    creature it kills, of every creature that drops an item it needs, or of
    every creature an item is used on is elite (or rare).

    ONE ELITE AMONG THE DROPPERS IS NO GROUP (2026-10-10). The Tome of Divinity
    (1644, 1648) needs 10 Linen Cloth, which 10,501 spawns drop; 875 of them are
    elite or rare, and naming the quest GROUP for `any` of them kept every
    paladin from Redemption. The solo hunt goes to the others (solo_fields)."""
    for entry, _n in quest.kills:
        if _all_elite(s for s in quest.fields if s.entry == entry):
            return True
    for item, _n in quest.items:
        droppers = {e for i, e in quest.drops if i == item}
        if droppers and _all_elite(s for s in quest.fields if s.entry in droppers):
            return True
    return any(u.verb == USE_ITEM and _all_elite(u.spots) for u in quest.uses)


def solo_fields(quest: Quest) -> tuple:
    """The objective spawns a member hunts alone: every one but the elites,
    unless an objective is met only at elites (a group's hunt, _elite_only)."""
    if _elite_only(quest):
        return quest.fields
    return tuple(s for s in quest.fields if s.rank < ELITE_RANK)


def blocker_of(quest: Quest, member) -> tuple:
    """(kind, sentence) when this quest cannot be hunted solo, else ("", "")."""
    if quest.group >= 2:
        return GROUP, "%s suggests a group of %d" % (quest.title, quest.group)
    if quest.uses:
        return _use_blocker(quest, member)
    if quest.objects:
        return OBJECT, "%s needs a gameobject used, which no verb does" % quest.title
    if _elite_only(quest):
        return GROUP, "%s's objective is an elite" % quest.title
    if (quest.kills or quest.items) and not quest.fields and _unmet(quest):
        return _source_blocker(quest)
    if quest.fields and _nearest(member, quest.fields) is None:
        return MAP, "%s's objective is on another map than the member%s" % (
            quest.title,
            _across(member, quest.fields),
        )
    return "", ""


def _status(member, quest_id) -> int:
    return int(member.quest_log.get(int(quest_id), 0))


def _closed_by_sibling(book: Book, member, path) -> bool:
    """True when a quest of the path shares a positive ExclusiveGroup with a
    quest the member has rewarded or holds: the game offers only one of them.
    A dwarf who finished Muren Stormpike (1679) can no longer take A Warrior's
    Training (1638), though both lead to the same spell."""
    for qid in path:
        group = book.quests[qid].exclusive
        if not group:
            continue
        for other in book.quests.values():
            if other.exclusive == group and other.id != qid and other.id not in path:
                if other.id in member.quests_done or _status(member, other.id):
                    return True
    return False


def _variant_move(book: Book, member, reward_id: int):
    """The next move along one reward quest's chain, or None when it is not
    open to this member (race, level)."""
    path = chain(book, reward_id)
    done = member.quests_done
    todo = [q for q in path if q not in done]
    if not todo:
        return None
    quest = book.quests[todo[0]]
    if quest.prev and quest.prev not in book.quests and quest.prev not in done:
        return None
    if not all(
        book.quests[q].admits(member.race) for q in path[: path.index(todo[0]) + 1]
    ):
        return None
    if int(member.level) < quest.min_level:
        return None
    if _closed_by_sibling(book, member, path):
        return None
    status = _status(member, quest.id)
    if status == STATUS_COMPLETE:
        return TURN_IN, quest, _nearest(member, quest.enders), reward_id
    if status == STATUS_INCOMPLETE:
        return HUNT, quest, None, reward_id
    return TAKE, quest, _nearest(member, quest.starters), reward_id


def helpers_for(quest: Quest) -> int:
    """How many guildmates a group-blocked quest asks for: the suggested group
    less the member itself, or ELITE_HELPERS for an elite objective with no
    group size, at most MAX_HELPERS."""
    wanted = quest.group - 1 if quest.group >= 2 else ELITE_HELPERS
    return max(1, min(MAX_HELPERS, wanted))


def _groups(book: Book, member, avoid=None, held_off=frozenset()) -> list:
    """(reward key, [Move of each variant open to the member]) for every class
    reward the member lacks, the lowest quest level first."""
    out = []
    for key, rewards in sorted(
        book.groups.items(), key=lambda kv: (book.quests[kv[1][0]].min_level, kv[0])
    ):
        klass, _spells = key
        if klass != int(member.class_id) or has_reward(book, member, key):
            continue
        if book.trained.intersection(key[1]):
            continue
        options = [m for m in (_variant_move(book, member, q) for q in rewards) if m]
        if not options:
            continue
        # A variant already in the log first, then the nearest giver.
        options.sort(
            key=lambda o: (
                _status(member, o[1].id) == 0,
                _yards(member, o[2]) if o[2] else 1e12,
                o[1].id,
            )
        )
        out.append(
            (key, [_move_of(member, o, key, avoid or {}, held_off) for o in options])
        )
    return out


# A variant in the log that is held for a reason of its own (a group, a stalled
# hunt or use, ground over the member's level) is not left for a crossing to
# the other variant's chain: it is asked for in guild chat or waited on.
HOLDING = frozenset({GROUP, STALLED, USE_STALLED, LEVEL})


def _live(made, member):
    """The first Move of a reward group's variants that can be made now, None
    when there is none. A CROSS does not pass over a variant in the member's
    log that is HOLDING."""
    for i, move in enumerate(made):
        if move.kind == BLOCKED:
            continue
        if move.kind == CROSS and any(
            b.kind == BLOCKED and b.blocker in HOLDING and _status(member, b.quest)
            for b in made[:i]
        ):
            return None
        return move
    return None


def moves(book: Book, member, avoid=None, held_off=frozenset()) -> list:
    """Every class reward the member lacks and may work toward now, as Moves,
    the lowest quest level first; a blocked one is a BLOCKED Move naming why.

    `avoid` is quest id -> ((map, x, y), ...), the packs a hunt already tried
    without progress; `held_off` the quest ids whose hunt was given up for now."""
    # The first move that can be made; else the first blocker, named.
    return [
        _live(made, member) or made[0]
        for _key, made in _groups(book, member, avoid, held_off)
    ]


@dataclass(frozen=True)
class Owed:
    """A class quest a member owes: eligible, unfinished, and not proven
    impossible. `blocker` is "" when a move can be made now, else the kind of
    the blocker that stands in the way (never one of PERMANENT), `said` names
    it, and `to_map` is the continent a crossing would reach (-1 when none)."""

    quest: int
    title: str
    klass: int
    blocker: str = ""
    said: str = ""
    to_map: int = -1


def owed(book: Book, member, avoid=None, held_off=frozenset(), yielded=frozenset()):
    """The Owed row of the first class reward the member owes, or None.

    A reward group is owed when any of its variants can be worked now or is
    blocked for a reason that is not PERMANENT (a variant whose creature no spawn
    names does not clear a group whose other variant is across the sea). A
    member of a level or race no quest of its class admits owes nothing, and
    nor does one whose every open variant is permanently blocked.

    A quest that yields to levelling is not owed while it yields: one in
    `yielded` (quest ids whose asks found no party, guildjobs.class_ask_streak),
    or a helpable blocker no party can help with (no_party_spot)."""
    for _key, made in _groups(book, member, avoid, held_off):
        live = _live(made, member)
        if live is None:
            live = next((m for m in made if m.blocker not in PERMANENT), None)
        if live is None:
            continue
        if live.kind == BLOCKED and (
            int(live.quest) in yielded or no_party_spot(book, live, member)
        ):
            continue
        quest = book.quests.get(int(live.quest))
        title = live.title or (quest.title if quest else "")
        there = live.to_map if live.kind == CROSS else -1
        if live.blocker == MAP and quest is not None:
            there = far_map(
                member, list(quest.starters) + list(quest.enders) + list(quest.fields)
            )
        return Owed(live.quest, title, live.klass, live.blocker, live.said, there)
    return None


def _no_creature(quest: Quest, word: str) -> str:
    """The sentence for a quest no creature starts or ends. A take names what
    starts it instead, or says nothing in the world data does (a retired quest
    whose spell the class trainer now teaches)."""
    said = "%s has no %s creature in the world data" % (quest.title, word)
    if word != "giver":
        return said
    if quest.other_starts:
        return said + "; it is started by %s, which no verb does" % ", ".join(
            "%s %d" % (k, e) for k, e in quest.other_starts
        )
    return said + ", and no gameobject or item starts it either: it cannot be taken"


def _move_of(member, option, key, avoid=None, held_off=frozenset()) -> Move:
    kind, quest, spot, reward_id = option
    reward = key[1]
    why = "%s (%s quest %d) for spell %s" % (
        quest.title,
        MARK,
        quest.id,
        "/".join(str(s) for s in reward),
    )
    if kind == HUNT:
        return _hunt_move(member, quest, why, (avoid or {}).get(quest.id, ()), held_off)
    if spot is None:
        ends = quest.enders if kind == TURN_IN else quest.starters
        word = "ender" if kind == TURN_IN else "giver"
        block, said = (
            (
                MAP,
                "%s has no %s on the member's map%s"
                % (quest.title, word, _across(member, ends)),
            )
            if ends
            else (SOURCE, _no_creature(quest, word))
        )
        blocked = Move(BLOCKED, quest.id, quest.klass, None, said, block, why)
        return _crossing(member, quest, why, blocked, ends)
    verb = "hands in" if kind == TURN_IN else "takes"
    return Move(
        kind,
        quest.id,
        quest.klass,
        spot,
        "%s walks to %s and %s %s" % (member.name, spot.name or "its giver", verb, why),
        "",
        why,
    )


def _nearest_untried(member, spawns, avoid=()):
    """The spawn on the member's map nearest it that is not within PACK_YARDS
    of a place in `avoid` (a target already used without result)."""
    here = [
        s
        for s in spawns
        if int(s.map_id) == int(member.map_id) and not _avoids(s, avoid)
    ]
    return min(here, key=lambda s: (_yards(member, s), s.guid)) if here else None


def within_level(member, spawns) -> tuple:
    """The spawns whose creature is at most OVERLEVEL_MAX levels over the
    member; a spawn whose level the world data does not give (0) is kept."""
    top = int(member.level) + OVERLEVEL_MAX
    return tuple(s for s in spawns if int(s.level) <= top)


def _outlevels_for_solo(member, quest) -> bool:
    """True when the member is at least OVERLEVEL_SOLO_GAP levels over the
    quest's minimum level (#1094): the member hunts the quest solo instead of
    waiting for guild help."""
    return int(member.level) - int(quest.min_level) >= OVERLEVEL_SOLO_GAP


def _level_said(member, quest: Quest) -> str:
    lowest = min(int(s.level) for s in quest.fields)
    return (
        "%s: every spawn of its objective is more than %d levels over the "
        "member (the lowest is level %d, the member %d)"
        % (quest.title, OVERLEVEL_MAX, lowest, int(member.level))
    )


def refused_places(book: Book, refused) -> dict:
    """quest id -> ((map, x, y), ...) of every objective spawn whose guid is in
    `refused` (the spawns the module refused this member lately): the places a
    hunt leaves, as it leaves a pack that made no progress."""
    if not refused:
        return {}
    out = {}
    for quest in book.quests.values():
        places = tuple(
            (int(s.map_id), float(s.x), float(s.y))
            for s in quest.fields
            if s.guid in refused
        )
        if places:
            out[quest.id] = places
    return out


_BOOK_MEMO: dict = {}


def _per_book(name: str, book: Book, build):
    """`build(book)`, kept for the newest book only: the plan asks the same
    question of the same book once per member (142 times a pass), and the
    answer depends on the book alone. Callers must not mutate the result."""
    held = _BOOK_MEMO.get(name)
    if held is not None and held[0] is book:
        return held[1]
    value = build(book)
    _BOOK_MEMO[name] = (book, value)
    return value


def slow_respawns(book: Book) -> dict:
    """See _slow_respawns; computed once per book, not once per member."""
    return _per_book("slow_respawns", book, _slow_respawns)


def _slow_respawns(book: Book) -> dict:
    """creature entry -> minutes to wait for it to respawn, for every objective
    creature with SLOW_SPAWNS or fewer spawns in the world: the soonest of its
    spawns' respawn times, rounded up, within RESPAWN_MIN_MINUTES and
    RESPAWN_CAP_MINUTES."""
    seen: dict = {}
    for quest in book.quests.values():
        for s in quest.fields:
            seen.setdefault(s.entry, {})[s.guid] = int(s.respawn)
    return {
        entry: min(
            RESPAWN_CAP_MINUTES,
            max(RESPAWN_MIN_MINUTES, -(-min(times.values()) // 60)),
        )
        for entry, times in seen.items()
        if len(times) <= SLOW_SPAWNS
    }


def spawn_entries(book: Book) -> dict:
    """See _spawn_entries; computed once per book, not once per member."""
    return _per_book("spawn_entries", book, _spawn_entries)


def _spawn_entries(book: Book) -> dict:
    """spawn guid -> creature entry, for every objective spawn of the book."""
    return {s.guid: s.entry for q in book.quests.values() for s in q.fields}


def marked_places(book: Book, marks) -> dict:
    """quest id -> ((map, x, y, age), ...): like refused_places, for `marks`
    (spawn guid -> minutes since the evidence), keeping each place's age."""
    out = {}
    for quest in book.quests.values():
        places = tuple(
            (int(s.map_id), float(s.x), float(s.y), int(marks[s.guid]))
            for s in quest.fields
            if s.guid in marks
        )
        if places:
            out[quest.id] = places
    return out


def all_tried(member, quest: Quest, avoid) -> bool:
    """Whether every pack of the quest the member could hunt is in `avoid`."""
    fields = within_level(member, solo_fields(quest))
    if not fields:
        return False
    # _densest(...) is None exactly when no spawn on the member's map is left
    # outside `avoid`. Asking that directly skips the pack count, which is
    # quadratic in the spawns of a creature (2026-10-11: the guild job plan
    # held the event loop for 40 seconds).
    here = int(member.map_id)
    if not avoid:
        return not any(int(s.map_id) == here for s in fields)
    exact = {(int(m), float(x), float(y)) for m, x, y in avoid}
    return not any(
        int(s.map_id) == here
        and (int(s.map_id), float(s.x), float(s.y)) not in exact
        and not _avoids(s, avoid)
        for s in fields
    )


def roll_oldest(member, quest: Quest, avoid, marked) -> tuple:
    """`avoid` with the oldest marked pack taken out, when every pack is in it
    and that pack's mark is SPAWN_RETRY_MINUTES old: the rolling, oldest first
    retry. `marked` is ((map, x, y, age), ...). Otherwise `avoid` as it was."""
    avoid = tuple(avoid)
    if not marked:
        return avoid
    old = max(marked, key=lambda p: p[3])
    # The age test is cheap and all_tried scans the quest's spawns, so the age
    # goes first: most marks are young, and the plan calls this per quest per
    # member (2026-10-11: 40 seconds on the event loop).
    if old[3] < SPAWN_RETRY_MINUTES or not all_tried(member, quest, avoid):
        return avoid
    return tuple(
        p
        for p in avoid
        if not (
            int(p[0]) == old[0]
            and math.hypot(p[1] - old[1], p[2] - old[2]) <= PACK_YARDS
        )
    )


def _lost_item_move(member, quest: Quest, using, block: str, why: str):
    """The ABANDON move for a quest whose StartItem, a use item, the member no
    longer carries (the quest gives it out again when it is taken anew), else
    None. An item the take never handed over (a source item, ItemDrop1-4) is
    no reason to drop the quest: taking it again does not bring it."""
    if (
        block == ITEM
        and using is not None
        and using.verb in (USE_HERE, USE_ITEM)
        and using.provided
        and _status(member, quest.id) == STATUS_INCOMPLETE
    ):
        said = "%s drops %s to take it again and be handed what it lost" % (
            member.name,
            quest.title,
        )
        return Move(ABANDON, quest.id, quest.klass, None, said, "", why)
    return None


def _hunt_move(member, quest: Quest, why: str, tried, held_off) -> Move:
    """The member's work on an incomplete quest (a hunt, or a use), or why it
    is blocked."""
    using = _pending_use(quest, member)
    if quest.id in held_off:
        if using is not None:
            said = "%s: using it changed nothing through %d target(s)" % (
                quest.title,
                len(tried) + 1,
            )
            return Move(
                BLOCKED,
                quest.id,
                quest.klass,
                None,
                said,
                USE_STALLED,
                why,
                1,
                quest.title,
            )
        said = "%s: no progress through %d pack(s) of its objective" % (
            quest.title,
            len(tried) + 1,
        )
        return Move(
            BLOCKED, quest.id, quest.klass, None, said, STALLED, why, 1, quest.title
        )
    block, said = blocker_of(quest, member)
    lost = _lost_item_move(member, quest, using, block, why)
    if lost is not None:
        return lost
    if block == GROUP and _outlevels_for_solo(member, quest):
        # #1094: the member so far outlevels the quest that the group blocker
        # is ignored and the quest is hunted solo. If the solo hunt stalls,
        # the STALLED blocker below (in HELPABLE) asks for help.
        block, said = "", ""
    if block:
        want = helpers_for(quest) if block == GROUP else 0
        spot = _densest(member, quest.fields) if block == GROUP else None
        blocked = Move(
            BLOCKED, quest.id, quest.klass, spot, said, block, why, want, quest.title
        )
        return _crossing(member, quest, why, blocked)
    if using is not None:
        return _use_move(member, quest, using, why, tried)
    if quest.uses and not quest.fields:
        # Everything its uses need is carried; the quest log has not caught up.
        said = (
            "%s: the member carries what its uses need; the quest log has not caught up"
            % quest.title
        )
        return Move(
            BLOCKED, quest.id, quest.klass, None, said, UNKNOWN, why, 0, quest.title
        )
    fields = within_level(member, solo_fields(quest))
    if quest.fields and not fields:
        return Move(
            BLOCKED,
            quest.id,
            quest.klass,
            None,
            _level_said(member, quest),
            LEVEL,
            why,
            0,
            quest.title,
        )
    spot = _densest(member, fields, tried)
    if spot is None:
        said = "%s: every pack of its objective was tried" % quest.title
        return Move(
            BLOCKED, quest.id, quest.klass, None, said, STALLED, why, 1, quest.title
        )
    return Move(
        HUNT,
        quest.id,
        quest.klass,
        spot,
        "%s hunts %s for %s" % (member.name, spot.name or "its objective", why),
        "",
        why,
    )


def _use_move(member, quest: Quest, use: Use, why: str, tried) -> Move:
    """The member walks to a target of the use and writes its row there."""
    spot = _nearest_untried(member, use.spots, tried)
    if spot is None:
        said = "%s: every target of its use was tried" % quest.title
        return Move(
            BLOCKED, quest.id, quest.klass, None, said, USE_STALLED, why, 1, quest.title
        )
    if use.verb == USE_HERE:
        what = "uses item %d beside" % use.item
    else:
        what = "uses item %d on" % use.item if use.verb == USE_ITEM else "uses"
    said = "%s %s %s for %s" % (member.name, what, spot.name or "its target", why)
    return Move(USE, quest.id, quest.klass, spot, said, "", why, use=use)


def use_command(use: Use, spot: Spawn) -> str:
    """The kind='quest' command row that does this use at `spot`."""
    if use.verb == USE_HERE:
        return "%s item:%d" % (USE_HERE, int(use.item))
    if use.verb == USE_ITEM:
        return "%s creature:%d item:%d" % (USE_ITEM, int(spot.entry), int(use.item))
    return "%s %d" % (USE_OBJECT, int(spot.entry))


def blocked_sentence(member, move: Move) -> str:
    return "%s cannot do its %s class quest: %s (%s)" % (
        member.name,
        CLASS_NAMES.get(move.klass, "class"),
        move.blocker,
        move.said,
    )


def helps(book: Book, member, avoid=None, held_off=frozenset()) -> list:
    """The BLOCKED Moves a guildmate can help with (a group quest, a hunt that
    stalled) that the member has no other class move ahead of: the member asks
    for these in guild chat (classask.py)."""
    return [
        m
        for m in moves(book, member, avoid, held_off)
        if m.kind == BLOCKED and m.blocker in HELPABLE and m.want
    ]


def objective_spot(book, move: Move, member):
    """The creature spawn a party walks to for a helpable move, None when it
    has none: the group quest's own densest pack (Move.spot), or, for a hunt
    given up after it stalled, the densest pack of the quest's objective with
    no pack left out (a party can face the pack a lone member could not).

    A use that changed nothing (USE_STALLED) has no spot: a party walk only
    gets the party there, and the use is the leader's own row."""
    if move.spot is not None:
        return move.spot
    quest = book.quests.get(int(move.quest)) if book is not None else None
    if quest is None or move.blocker != STALLED:
        return None
    return _densest(member, quest.fields)


def no_party_spot(book, move: Move, member) -> bool:
    """Whether `move` is a helpable blocker (HELPABLE, with helpers wanted)
    that no party could help with: objective_spot finds it no spawn to walk
    to. Such a quest is not asked for in guild chat and yields to levelling
    until the member may try it alone again (guildjobs.class_helps)."""
    return (
        move.kind == BLOCKED
        and move.blocker in HELPABLE
        and bool(move.want)
        and objective_spot(book, move, member) is None
    )


def no_party_why(move: Move) -> str:
    """Why no party can help with a no_party_spot move, for the log."""
    if move.blocker == USE_STALLED:
        return "a party walk only gets the party there, and the use is the member's own"
    return "no spawn of its objective is on the member's map for a party to walk to"


def next_move(book: Book, member, avoid=None, held_off=frozenset()):
    """(the move to make or None, [blocker sentences]) for one member.

    The first move that is not blocked wins; every blocked one is named, so a
    member that does nothing says why."""
    blocked = []
    for move in moves(book, member, avoid, held_off):
        if move.kind == BLOCKED:
            blocked.append(blocked_sentence(member, move))
            continue
        return move, blocked
    return None, blocked


# --- the hunt's clock and the asks ----------------------------------------------

REROLL, GIVE_UP = "reroll", "giveup"


@dataclass(frozen=True)
class Hunt:
    """One member's current hunt: the quest, its progress when last seen, when
    that last changed, the packs tried without progress, and (when set) the
    moment the quest is given up until."""

    quest: int
    progress: int
    since: float
    tried: tuple = ()
    until: float | None = None


class Hunts:
    """What each member's hunt has done lately, kept in memory by the bridge.

    A restart forgets it, which only gives a stalled hunt a fresh 30 minutes.
    Times are seconds from one clock for the life of the object, any epoch
    (time.time() or time.monotonic(), which may start near 0): no time is a
    sentinel, an unset hold-off is None."""

    def __init__(self):
        self._by: dict = {}
        # The realm's free hunt slots (classhunt.Slots) for the pass being
        # planned, set by the bridge before it plans; None keeps the walk-only
        # hunt (a worldserver with no hunt verb, or one not yet read).
        self.slots = None
        # Whether the hunt row may name the item it wants (`item:`, mod-overseer
        # #871); False while the worldserver is known to reject the token.
        self.items = True

    def get(self, name):
        return self._by.get(name)

    def state(self, name, now) -> tuple:
        """(avoid, held_off) for moves(): the packs tried for the member's
        hunt, and the quest given up while its hold-off lasts."""
        hunt = self._by.get(name)
        if hunt is None:
            return {}, frozenset()
        if hunt.until is not None and hunt.until <= now:
            return {}, frozenset()
        off = frozenset({hunt.quest}) if hunt.until is not None else frozenset()
        return {hunt.quest: hunt.tried}, off

    def observe(self, name, quest, progress, spot, now, failed=False) -> str:
        """Record one pass of a hunt toward `spot`; REROLL when it has stalled
        and another pack is to be tried, GIVE_UP when it stalled through every
        retry, else ""."""
        hunt = self._by.get(name)
        fresh = hunt is None or hunt.quest != quest
        if not fresh and hunt.until is not None:
            if hunt.until > now:
                return ""
            fresh = True
        if fresh:
            hunt = Hunt(quest, progress, now)
        elif progress != hunt.progress:
            hunt = Hunt(quest, progress, now)
        idle = now - hunt.since >= HUNT_STALL_MINUTES * 60
        if not (idle or failed):
            self._by[name] = hunt
            return ""
        tried = hunt.tried + ((int(spot.map_id), float(spot.x), float(spot.y)),)
        if len(tried) > MAX_REROLLS:
            self._by[name] = Hunt(
                quest, progress, now, tried, now + GIVE_UP_MINUTES * 60
            )
            return GIVE_UP
        self._by[name] = Hunt(quest, progress, now, tried)
        return REROLL

    def productive(self, name, now) -> None:
        """A hunt that killed is reachable ground: forget the packs it tried
        and any hold-off, and restart its stall clock."""
        hunt = self._by.get(name)
        if hunt is not None and (hunt.tried or hunt.until is not None):
            self._by[name] = Hunt(hunt.quest, hunt.progress, now)
        elif hunt is not None:
            self._by[name] = replace(hunt, since=now)

    def give_up(self, name, quest, now) -> None:
        """Give a quest up for GIVE_UP_MINUTES at once: the world refused its
        use for good (classuse.NEVER), so no other target is worth a try."""
        hunt = self._by.get(name)
        tried = hunt.tried if hunt is not None and hunt.quest == quest else ()
        self._by[name] = Hunt(int(quest), 0, now, tried, now + GIVE_UP_MINUTES * 60)

    def pause(self, name, quest, now) -> None:
        """Restart the stall clock of a hunt that is waiting on the realm, not
        on the member: a far walk refused for a wall that moves (BACKOFF_MINUTES)
        or held back for want of a slot. The 30 minutes count a member hunting
        with no progress, and a member standing in a queue has not hunted."""
        hunt = self._by.get(name)
        if hunt is None or hunt.quest != quest or hunt.until is not None:
            return
        self._by[name] = replace(hunt, since=now)

    def used(self, name, quest, now) -> None:
        """Restart the stall clock of a hunt whose use the module answered as
        done (classuse.DONE). A Binding's Runes of Summoning summon the demon at
        the circle, but the quest counter moves only when the demon dies, so
        the walk, the use and the fight would otherwise count as one stall and
        a quest with one circle be called tried although the use worked. The
        packs tried stay tried and a hold-off stays: only this target worked."""
        self.pause(name, quest, now)

    def forget(self, name) -> None:
        self._by.pop(name, None)


class Owing:
    """How long each member has owed a class quest with no progress. In memory
    here; the bridge's subclass keeps it across a restart (bridge.py).

    A member's progress is a mark (guildjobs.progress_mark): when it changes the
    clock starts over. Times are seconds from one clock for the life of the
    object, any epoch."""

    def __init__(self):
        self._by: dict = {}

    def idle(self, name, mark, now) -> float:
        """Seconds since the member's mark last changed (0.0 the first time it
        is seen)."""
        seen = self._by.get(name)
        if seen is None or seen[0] != mark:
            self._by[name] = (mark, now)
            return 0.0
        return max(0.0, now - seen[1])

    def expired(self, name, mark, now, hours=OWED_HOURS) -> bool:
        """Whether the member has made no progress for `hours`."""
        return self.idle(name, mark, now) >= hours * 3600

    def forget_unowed(self, seen, owing) -> None:
        """Forget every member of `seen` (the members one pass read) that is not
        in `owing`: one that owes nothing starts a fresh clock the day it owes
        again. A member the pass did not read is left alone, so two guilds'
        passes keep each other's clocks."""
        owing = set(owing)
        for name in [n for n in seen if n not in owing]:
            self._by.pop(name, None)


@dataclass(frozen=True)
class Help:
    """A member's class quest that a guildmate could help with. `tries` is how
    many asks for it in a row came to no party (guildjobs.class_ask_streak):
    from classask.ESCALATE_AFTER_ASKS the ask goes to the server too."""

    member: str
    guild: str
    level: int
    map_id: int
    move: Move
    tries: int = 0
