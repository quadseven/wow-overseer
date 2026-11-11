"""The questers' play (#924): every quest in reach, and a quest that stops is broken.

WHY THIS EXISTS. The questers (#922, raidteams.QUESTERS) are there to prove
that every quest works. A guild member follows the levelling route
(levelroute.py, guildlevel.py) and the class chains (classquest.py), so most
quests are never tried, and a quest that cannot be finished blocks a member
until somebody notices. A quester does the other thing: it takes every quest
open to it where it stands, works them, hands them in, and moves on only when
nothing in reach is left. A quest that cannot be finished is written down as
broken with the reason, dropped, and left behind.

IN REACH (`open_to`, `in_reach`). A quest of the catalogue (`catalogue`) is in
reach of a quester when:

  * its zone is the quester's zone (a starting area counts as the zone it lies
    in, `START_AREAS`: Northshire Valley is Elwynn Forest);
  * its race and class masks hold the quester's, its minimum level is met and
    its own level is at most levelroute.ABOVE over the quester's;
  * the quest before it is rewarded (or held, for a negative PrevQuestID), and
    no quest of its exclusive group is rewarded or held. "The quest before it"
    is the world's list, not the row's: its own PrevQuestID or any quest whose
    NextQuestID names it, a quest of a negative exclusive group standing for
    its whole group (#1732);
  * the quest its RewardNextQuest names is not held or rewarded, no quest
    whose RewardNextQuest names it is held, a breadcrumb's target is not held
    or rewarded and a target's breadcrumb is not held;
  * the quester's stored reputation meets the quest's reputation gate;
  * a quest that hands over an item (StartItem) has a free bag slot for it:
    the world refuses the take as "not eligible" otherwise (CanAddQuest), and
    a quester with full bags walked to Westfall Stew and A Rogue's Deal and
    filed them broken (#1732, #1716);
  * the quester has not finished it, does not hold it, and has not found it
    broken.

What the catalogue leaves out is what a five cannot reach: dungeon, raid and
PvP quests (`OUT_OF_REACH_INFO`), quests over the classic level cap, and
quests outside the classic world and the Blood Elf and Draenei starting lands.

WHAT A QUESTER DOES NEXT (`next_move`), one move a pass, in this order:

  1. drop a quest it holds that is broken (`classquest.ABANDON`);
  2. hand in a complete quest, the nearest turn-in NPC first;
  3. take a quest in reach while the log has a free slot (questlog.LOG_SLOTS),
     the nearest quest giver first;
  4. work a quest it holds: walk to the nearest objective spawn at most
     classquest.OVERLEVEL_MAX levels over it and hunt its creature there with
     the module's `hunt-spawn` row, as a class hunt does (`step_for`);
  5. with nothing left in reach, go to the next zone (`next_zone`): the zone
     whose band (levelroute.bands, the catalogue's own levels) is lowest of the
     zones holding a quest in reach for it whose giver it can go to (a quest
     only an item or a gameobject starts takes no one anywhere, and a giver
     of the other side or hostile to its own gives it nothing,
     `hostile_givers`), a zone with a quest near its level before a zone of
     grey leftovers, the most quests first on a tie.
     The move is the take of that zone's nearest quest; a zone on the other
     continent is a `cross-to-map` row (classquest.CROSSING_VERB) first. While
     its last crossing to a continent failed and the crossing clock holds it
     (`failed_crossings`), a zone only across it is passed over for the best
     zone it can reach without crossing, when there is one.

The party works together through questshare (the bridge shares among the five
as it does for the family), and every take, hand-in and drop is the module's
own verb (`take quest:`, `turnin quest:`, `abandon quest:`). Nothing is ever
granted: a quest is never completed, skipped or rewarded by a command.

BROKEN (`Broken`, `failures`). A quest is broken when:

  * FAILED: the log holds it as failed (an escort died, a timer ran out);
  * STALLED: its objectives (status and counters) have not moved for
    STALL_SECONDS of play while the quester was working it (`Clock`). Play is
    time online and alive between two looks, at most PLAY_GAP_SECONDS each, so
    a bridge restart or a night offline is not play. A quest is being worked
    while it is the quest the quester's last move was for, or while it is in
    its log, of the zone it stands in, and has no objective spawn the quester
    could hunt (`_working`): nothing works that one, so its clock is the
    world's, not the quester's;
  * GIVER_MISSING: a creature is named as its giver, none is spawned, and
    no gameobject or item starts it either;
  * ENDER_MISSING: nothing is named to hand it in to, or the creature named is
    not spawned, or the world refused every spawn of it as gone;
  * OBJECT_ENDER_MISSING: only a gameobject is named to hand it in to, and it
    has no spawn in the world, or the world refused every spawn of it as gone
    (#1594). An incomplete quest one of whose enders is an object with no
    static spawn is not judged on its ender at all: a script or an event
    summons that object, so it is worked and only a stall breaks it (#1606);
  * SOURCE_MISSING: the world refused every spawn of its objective as gone.
    A quest whose objective no spawned creature is or drops is not judged on
    that alone (a script may summon it, a chest or a vendor may hold the
    item): it stalls, and its stall says so (STALLED_UNSOURCED);
  * REFUSED_TAKE / REFUSED_TURN_IN: the world refused the take or the hand-in
    FAILS_BEFORE_BROKEN times in a day, with its own words appended;
  * CANNOT_TURN_IN: the world refused the hand-in once and said no retry
    can help (`"retryable":false`, mod-overseer#19), with its own
    words appended. That is "could not", not "did not yet": the quest is
    reported at once and its hand-in is not asked again while the refusal is
    in the rows the pass reads (`turn_in_held`).

A broken quest the quester holds is dropped (the move in 1 above); one it
never held (a giver that is not there) is only recorded, and so is a complete
one: the module refuses to abandon a complete quest ("it is complete; hand it
in"), so it is handed in when it can be and otherwise left in the log (#1085). The bridge writes
each into the quest ledger (questledger.py, #923) with its reason.

A HAND-IN THE WORLD KEEPS REFUSING IS HELD (`turn_in_held`). A complete quest
whose hand-in was refused FAILS_BEFORE_BROKEN times is not handed in again
until TURN_IN_RETRY_MINUTES have passed since the last refusal, the hold
doubling with each refusal past those; then it is tried once more.
A hand-in refused as never retryable (CANNOT_TURN_IN) is held from its
first refusal while that row is in the rows the pass reads.

A QUESTER WITH FULL BAGS SELLS FIRST (`sell_step`, #1813). A quest that hands
over an item waits on a free bag slot (above), and the questers never sold,
so every quester of #1732 and #1716 stood with none and took no such quest.
A quester at SELL_FLOOR free general bag slots or fewer walks to any vendor
that buys (`walk-to-vendor any`) and sells what it has no use for, the guild
members' own sale (guildjobs.vendor_stacks, vendorsale.py): grey, junk,
outgrown gear and gear that is no upgrade over what it wears, and trade goods
no quest of the catalogue asks for (a quester has no guild bank to keep them
for). Kept: every item a catalogue quest needs, hands over or uses, quest
items, an upgrade, a piece judged while its worn gear is unread, and a stack
reserved in overseer_keep (keep.py; unread reservations sell nothing). The
sale is asked at most once in SELL_COOLDOWN_MINUTES, and before the move.

A TAKE REFUSED FOR BAG ROOM IS A WAIT, NOT A BROKEN QUEST (#1992). The module
refuses a take whose start item will not fit in the bags with its own words
(BAG_ROOM_REFUSAL, retryable, mod-overseer#1393). Bags can read as having room
and still be full to the core (a free slot only in a profession bag), so that
refusal is never counted toward FAILS_BEFORE_BROKEN: the quester sells first,
whatever its bags read (`needs_sale`), and the take of that quest is left for
SELL_COOLDOWN_MINUTES (`bag_room_refused`), then asked again.

PURE MODULE: rows in, moves and verdicts out. No MySQL; the clock is passed in.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace

import classhunt
import classic
import classquest
import guildcorps
import guildjobs
import guildroute
import levelroute
import questlog
import vendorsale

# The step's action word, in the command log's source (guildjobs.source_for).
ACTION = "quester"
WALK_ACTION = ACTION + "-walk"
# The sale of a quester with full bags (`sell_step`, #1813): its own action
# word, under ACTION's source prefix so the pass's recent read holds its rows,
# and not one `attempts` reads as a quest's take, hand-in or walk.
SELL_ACTION = ACTION + "-sell"
SELL_WALK_ACTION = SELL_ACTION + "-walk"
# Free general bag slots at or under which a quester sells: one for the item a
# quest hands over and one for the loot of the next kill.
SELL_FLOOR = 1
# A sale is asked again only this long after the last, sold or refused: the
# walk and the rows run inside it, and a vendor out of reach is not asked
# every pass.
SELL_COOLDOWN_MINUTES = 20
# A quester's crossing row has its own source action (quest takes, hand-ins
# and hunts are ACTION), so it shares the one crossing clock and the walls of
# the class quest's and the level step's crossings (guildjobs.CROSS_ACTIONS).
#
# ONE CROSSING ROW EVERY PASS (2026-10-18). Written under ACTION, a quester's
# `cross-to-map` row was outside that clock, and the quester pass asks every
# two minutes: of 4,252 crossing rows the dev realm took in a day, 3,717 were
# seven questers', refused 1,286 times as having no transport (two death
# knights in Acherus, map 609, and a Blood Elf on map 530 asking for Kalimdor),
# 491 times as held by another job (the revived sickness hold after a death)
# and 413 times at the realm's crossing cap. The module said each of these
# once; the rest is the same question asked again.
CROSS_ACTION = guildjobs.QUESTER_CROSS_ACTION

# Two hours of play with no objective moving is a broken quest (#924).
STALL_SECONDS = 2 * 60 * 60
# The longest gap between two looks counted as play. Twice the bridge's pass
# at its default, so one slow pass is still play and a restart or an outage of
# the bridge is not.
PLAY_GAP_SECONDS = 10 * 60

# The quest log's hard cap (MAX_QUEST_LOG_SIZE): a full log refuses every take.
LOG_SLOTS = questlog.LOG_SLOTS

# QuestInfoID of the quests a party of five does not reach: PvP (41), raid
# (62), dungeon (81), heroic (85), 10 and 25 player raid (88, 89).
OUT_OF_REACH_INFO = frozenset({41, 62, 81, 85, 88, 89})

# A starting area's quests carry the area as their QuestSortID; the character
# stands in the zone around it (its `zone` column is the zone). Both are read as
# the zone. AreaTable: the nine starting areas of #922 and their zones.
START_AREAS = {
    9: 12,  # Northshire Valley, Elwynn Forest
    132: 1,  # Coldridge Valley, Dun Morogh
    188: 141,  # Shadowglen, Teldrassil
    3526: 3524,  # Ammen Vale, Azuremyst Isle
    363: 14,  # Valley of Trials, Durotar
    154: 85,  # Deathknell, Tirisfal Glades
    220: 215,  # Camp Narache, Mulgore
    3431: 3430,  # Sunstrider Isle, Eversong Woods
}

STATUS_COMPLETE = classquest.STATUS_COMPLETE
STATUS_INCOMPLETE = classquest.STATUS_INCOMPLETE
# A failed quest (an escort that died, a timer that ran out) holds its log slot
# until it is dropped (questlog.FAILED).
STATUS_FAILED = questlog.FAILED


def _quest_complete(quest, status, progress=0) -> bool:
    """True when the quest in the log is complete: the core's complete
    status, or objectives (their sum, as LOG_SQL reads them) that reach what
    the quest requires."""
    try:
        if int(status) == STATUS_COMPLETE:
            return True
        if quest is None:
            return False
        target = classhunt.wanted(quest)
        return 0 < target <= int(progress or 0)
    except (TypeError, ValueError):
        return False


# The reasons a quest is broken, as the ledger records them. FAILED is the
# ledger's own words for it (questledger.FAILED_REASON, #923).
FAILED = "the quest failed in the log"
STALLED = "its objectives did not move for 2 hours of play"
GIVER_MISSING = "the quest giver is not in the world"
# Further Concerns and Report to Gryan Stoutmantle require speaking to an NPC
# for objective credit. Questers can hunt and use quest verbs, but cannot speak
# to satisfy these objectives.
UNSUPPORTED_OBJECTIVE = "it requires speaking to an NPC, which questers cannot do"
CRAFTED_CRAB_CAKES = "requires crafted Crab Cakes (item 2683); questers cannot cook"
FORGOTTEN_HEIRLOOM = (
    "The Forgotten Heirloom (quest 64) requires an item no spawned creature drops"
)
FARGODEEP_EXPLORATION = (
    "requires exploring Fargodeep Mine; questers cannot earn exploration credit"
)
SELLING_FISH = "Selling Fish (quest 127) requires fishing; questers cannot fish"
UNDERBELLY_SCALES = "Underbelly Scales (quest 122) requires Black Dragonspawn with no spawns in Redridge Mountains"
DEFIAS_BROTHERHOOD = (
    "The Defias Brotherhood (quest 132) requires Wiley's Note (item 1327), "
    "which no spawned creature drops"
)
GHOST_HAIR_THREAD = (
    "Ghost Hair Thread (quest 149) requires Spectral Comb (item 1453), "
    "which no spawned creature drops"
)
ENDER_MISSING = "the turn-in NPC is not in the world"
OBJECT_ENDER_MISSING = "the turn-in object is not in the world"
NO_TURN_IN_NAMED = "the quest names no creature or object to take it in"
# The kind of spawn a gameobject ender's walk names (`walk-to-spawn gameobject:`).
OBJECT_KIND = "gameobject"
SOURCE_MISSING = "an objective's creature or item is never found in the world"
STALLED_UNSOURCED = (
    STALLED
    + ", no huntable source supplies what it asks for, and questers cannot buy items from vendors"
)
REFUSED_TAKE = "the quest giver would not give it"
REFUSED_TURN_IN = "the turn-in NPC would not take it"
# The module refused the hand-in and marked it never retryable (#19 in
# quadseven/mod-overseer): the world names nothing that takes the quest in,
# or no such quest. Distinct from REFUSED_TURN_IN so the ledger never reads a
# quest nobody can hand in as one that was merely slow to go through.
CANNOT_TURN_IN = "the world says no hand-in of it can go through"
# The module's non-retryable refusals that are about the quest log's state at
# that moment, not about the quest: a later read of the log settles them, so
# they never make a held quest a could-not.
LOG_STATE_REFUSALS = frozenset(
    {"already turned in", "not in the quest log", "already in the quest log"}
)
# The module's words for a take refused only because the giver's start item
# will not fit in the bags (mod-overseer#1393, retryable). A wall that moves:
# never counted toward a broken quest, and the quester sells before the take
# is asked again (#1992).
BAG_ROOM_REFUSAL = "no bag room for the item the giver hands over"

# The world's own words for a spawn that is not there (classquest.SPAWN_REFUSALS).
GONE = "no such spawn in the world"
# The world's own words when an abandon is refused for a quest that is
# complete: hand it in instead of dropping it (#1085).
COMPLETE_HAND_IN = "it is complete; hand it in"
# A take or a hand-in the world refused this many times in a day is broken.
FAILS_BEFORE_BROKEN = 3
# A hand-in the world refused FAILS_BEFORE_BROKEN times is held this long after
# its last refusal before it is tried once more, the hold doubling with each
# refusal past those (`turn_in_held`).
TURN_IN_RETRY_MINUTES = 6 * 60
# The quest ledger's reason column.
REASON_WIDTH = 255
# Quest errands find their NPC within the walk's arrival radius (20 yards).
# Keep questers well inside that radius even when the spawn is above or below
# the character on uneven ground.
QUESTER_NPC_NEAR = 12
QUESTER_HUNT_NEAR = 12

_FAILED = ("error", "failed", "refused", "expired")
_WENT = ("applied", "delivered")
_CHAIN_ROW = re.compile(r"^(take|turnin|abandon) quest:(\d+)")

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
_PROVIDED = "q.StartItem AS provided0, " + "".join(
    "q.ItemDrop%d AS source%d, " % (i, i) for i in range(1, 5)
)
_ITEM_OBJECTIVES = "".join(
    "q.RequiredItemId%d AS item%d, s.itemcount%d, " % (i, i, i) for i in range(1, 7)
)

# Every quest with a zone, of the classic level range, that a five may reach.
# The world's quests, the same columns classquest.QUESTS_SQL reads and the
# quest's own level, zone and type. Built from this module's integer constants
# only, no outside value (S608 does not apply; ruff reports it on the first
# string, so the noqa sits there).
QUESTS_SQL = (
    "SELECT q.ID AS id, q.LogTitle AS title, q.QuestSortID AS sort, "  # noqa: S608
    "q.QuestSortID AS zone, q.QuestLevel AS level, q.QuestInfoID AS info, "
    "q.MinLevel AS min_level, q.AllowableRaces AS races, "
    "COALESCE(a.AllowableClasses, 0) AS classes, "
    "COALESCE(a.PrevQuestID, 0) AS prev_signed, "
    "COALESCE(a.PrevQuestID, 0) AS prev, "
    "COALESCE(a.ExclusiveGroup, 0) AS exclusive, q.RewardSpell AS reward, "
    "q.RewardDisplaySpell AS display, q.SuggestedGroupNum AS grp, "
    "q.RewardNextQuest AS chain_next, "
    "COALESCE(a.BreadcrumbForQuestId, 0) AS crumb_for, "
    "COALESCE(a.RequiredMinRepFaction, 0) AS min_rep_faction, "
    "COALESCE(a.RequiredMinRepValue, 0) AS min_rep_value, "
    "COALESCE(a.RequiredMaxRepFaction, 0) AS max_rep_faction, "
    "COALESCE(a.RequiredMaxRepValue, 0) AS max_rep_value, "
    + _NPCS
    + _ITEMS
    + _PROVIDED
    + "0 AS pad FROM acore_world.quest_template q "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = q.ID "
    "WHERE q.QuestSortID > 0 AND q.MinLevel <= "
    + str(classic.MAX_LEVEL)
    + " AND q.QuestLevel <= "
    + str(classic.MAX_LEVEL)
    + " AND q.QuestInfoID NOT IN ("
    + ", ".join(str(i) for i in sorted(OUT_OF_REACH_INFO))
    + ") AND q.LogTitle NOT LIKE '<%%' AND q.LogTitle NOT LIKE 'NOT A QUEST%%'"
)

# The quest relations the world builds at load (ObjectMgr::LoadQuests) that a
# quest's own row does not carry, over every quest and not only the ones a
# quester may take: a quest whose NextQuestID names X is a quest before X, a
# quest whose RewardNextQuest names X is X's previous quest in the chain, a
# breadcrumb names its target, and a negative exclusive group is every-of-all
# (#1732). One constant string, no outside value.
LINKS_SQL = (
    "SELECT a.ID AS id, a.NextQuestID AS next, a.BreadcrumbForQuestId AS crumb_for, "
    "a.ExclusiveGroup AS exclusive, 0 AS chain_next "
    "FROM acore_world.quest_template_addon a "
    "WHERE a.NextQuestID <> 0 OR a.BreadcrumbForQuestId <> 0 OR a.ExclusiveGroup < 0 "
    "UNION ALL "
    "SELECT q.ID, 0, 0, 0, q.RewardNextQuest FROM acore_world.quest_template q "
    "WHERE q.RewardNextQuest <> 0"
)

# Each quester's standing with each faction it has met, for a quest's
# reputation gate (#1732).
REPUTATION_SQL = (
    "SELECT guid, faction, standing FROM character_reputation WHERE guid IN ({guids})"
)

# What starts each quest besides a spawned creature (classquest.STARTERS_SQL),
# and every creature named as a giver whether it is spawned or not, so a giver
# that is named and not in the world is told from a quest nothing gives. Two
# constant strings joined; `{quests}` is filled with integer ids only
# (bridge._quester_catalogue), so S608 does not apply.
STARTERS_SQL = (
    classquest.STARTERS_SQL + " UNION ALL "  # noqa: S608
    "SELECT s.quest, 'creature', s.id FROM acore_world.creature_queststarter s "
    "WHERE s.quest IN ({quests})"
)

# Everything named to hand each quest in to: a creature or a gameobject. A
# gameobject comes with each of its spawns (guid 0 when it has none), since
# classquest.GIVERS_SQL reads creature spawns only: a quest whose only ender is
# a gameobject had nowhere to walk to and sat complete in the log (#1594).
ENDERS_SQL = (
    "SELECT e.quest AS quest, 'creature' AS kind, e.id AS entry, 0 AS guid, "
    "0 AS map_id, 0 AS x, 0 AS y, '' AS name "
    "FROM acore_world.creature_questender e WHERE e.quest IN ({quests}) "
    "UNION ALL "
    "SELECT e.quest, 'gameobject', e.id, COALESCE(o.guid, 0), COALESCE(o.map, 0), "
    "COALESCE(o.position_x, 0), COALESCE(o.position_y, 0), COALESCE(gt.name, '') "
    "FROM acore_world.gameobject_questender e "
    "LEFT JOIN acore_world.gameobject o ON o.id = e.id "
    "LEFT JOIN acore_world.gameobject_template gt ON gt.entry = e.id "
    "WHERE e.quest IN ({quests})"
)

# The questers: where each stands (the snapshot, fresh within two minutes),
# its quest log with each quest's counters summed, and what it was rewarded.
MEMBERS_SQL = (
    "SELECT c.guid, c.name, c.class AS class_id, c.race, c.level, c.online, "
    "c.map AS map_id, c.zone AS saved_zone, s.pos_x, s.pos_y, s.zone_id, s.health, "
    "EXISTS (SELECT 1 FROM corpse k WHERE k.guid = c.guid) AS has_corpse "
    "FROM characters c "
    "LEFT JOIN overseer_snapshot s ON s.name = c.name "
    "AND s.updated_at > NOW() - INTERVAL 120 SECOND "
    "WHERE c.name IN ({names})"
)
LOG_SQL = (
    "SELECT s.guid, s.quest, s.status, "
    "(mobcount1 + mobcount2 + mobcount3 + mobcount4 + itemcount1 + itemcount2 + "
    "itemcount3 + itemcount4 + itemcount5 + itemcount6) AS progress, "
    "q.RequiredNpcOrGo1 AS npc1, q.RequiredNpcOrGo2 AS npc2, "
    "q.RequiredNpcOrGo3 AS npc3, q.RequiredNpcOrGo4 AS npc4, "
    + _ITEM_OBJECTIVES
    + "s.mobcount1, s.mobcount2, s.mobcount3, s.mobcount4 "
    "FROM character_queststatus s JOIN acore_world.quest_template q ON q.ID = s.quest "
    "WHERE s.guid IN ({guids}) AND s.status IN (1, 3, 5)"
)
REWARDED_SQL = (
    "SELECT guid, quest FROM character_queststatus_rewarded WHERE guid IN ({guids})"
)
# The quest ledger (questledger.py, #923): what is recorded of each quester's
# quests, and a broken quest written into it. A quest already in the ledger
# keeps the time it was first taken.
LEDGER_SQL = (
    "SELECT l.quest, c.name, l.state, l.reason FROM overseer_quest_ledger l "
    "JOIN characters c ON c.guid = l.guid WHERE c.name IN ({names})"
)
# A LEDGER STALL IS NOT A FACT ABOUT THE QUEST (#1867). "Its objectives did not
# move for 2 hours of play" says how one quester's play went, judged by the
# stall clock; the bridge's broken memo holds the stalls that clock judged and
# drops those the clock before #1809 judged (QUESTER_STALL_CLOCK_KEY, #1957).
# The ledger row stays broken after that, so reading every broken ledger row
# as broken put the old stalls straight back: on the dev realm Blackrock Bounty
# (quest 128) was shared to the Cave questers 69 times between 2026-10-20 and
# 2026-11-07 and dropped 104 times, each drop within minutes of its share or
# of the quest coming back, and no quester ever wrote one walk or hunt row for
# its Blackrock Champions (creature 435, 24 spawns in Redridge). A broken
# ledger row whose reason is a stall reads LEDGER_STALLED: still broken for the
# ledger's own writes, but the quest is held broken only while the memo holds
# that stall.
LEDGER_BROKEN = "broken"
LEDGER_STALLED = "stalled"


def ledger_state(state, reason) -> str:
    """The quester pass's reading of one ledger row: LEDGER_STALLED for a
    broken row whose reason is a stall, else the row's own state."""
    state = str(state or "")
    if state == LEDGER_BROKEN and str(reason or "").startswith(STALLED):
        return LEDGER_STALLED
    return state


def ledger_says_broken(state) -> bool:
    """True when the ledger row already records the quest as broken."""
    return state in (LEDGER_BROKEN, LEDGER_STALLED)


def known_broken(name, held, ledger) -> frozenset:
    """The quests the quester holds broken: every quest of its memo (`held`)
    and each quest the ledger records broken for a fact about the world, never
    one the ledger records broken only for a stall the memo no longer holds."""
    return frozenset(int(q) for q in held) | frozenset(
        q
        for (who, q), state in ledger.items()
        if who == name and state == LEDGER_BROKEN
    )


BROKEN_SQL = (
    "INSERT INTO overseer_quest_ledger "
    "(quest, guid, character_name, state, first_taken, finished, reason) "
    "SELECT %s, c.guid, c.name, 'broken', IF(%s, NOW(), NULL), NOW(), %s "
    "FROM characters c WHERE c.name = %s "
    "ON DUPLICATE KEY UPDATE state = 'broken', finished = NOW(), reason = VALUES(reason)"
)


def members_from_rows(rows, log_rows, rewarded_rows, reputation_rows=None) -> list:
    """Member rows from MEMBERS_SQL's, LOG_SQL's and REWARDED_SQL's rows. The
    position and zone come from a fresh snapshot only, so a walk is never judged
    from an old one; with none the quester is offline or unplaced.

    `reputation_rows` are REPUTATION_SQL's; None (not read) leaves each
    member's reputation unknown, and a reputation gate is then not judged."""
    log_by, progress_by, objectives_by, item_objectives_by, done_by = _logs_by_guid(
        log_rows, rewarded_rows
    )
    rep_by = None
    if reputation_rows is not None:
        rep_by = {}
        for r in reputation_rows:
            rep_by.setdefault(_int(r.get("guid")), {})[_int(r.get("faction"))] = _int(
                r.get("standing")
            )
    out = []
    for r in rows or ():
        guid = _int(r.get("guid"))
        member = _member_from_row(
            r,
            log_by.get(guid, {}),
            frozenset(done_by.get(guid, ())),
            progress_by.get(guid, {}),
            objectives_by.get(guid, {}),
            item_objectives_by.get(guid, {}),
        )
        if rep_by is not None:
            member = replace(member, reputation=rep_by.get(guid, {}))
        out.append(member)
    return out


def _logs_by_guid(log_rows, rewarded_rows) -> tuple:
    """Status, total, creature and item objective progress, and rewards by guid."""
    log_by, progress_by, objectives_by, item_objectives_by, done_by = {}, {}, {}, {}, {}
    for r in log_rows or ():
        guid, qid = _int(r.get("guid")), _int(r.get("quest"))
        log_by.setdefault(guid, {})[qid] = _int(r.get("status"))
        progress_by.setdefault(guid, {})[qid] = _int(r.get("progress"))
        objectives = {
            _int(r.get("npc%d" % i)): _int(r.get("mobcount%d" % i))
            for i in range(1, 5)
            if _int(r.get("npc%d" % i)) > 0
        }
        objectives_by.setdefault(guid, {})[qid] = objectives
        item_objectives = {
            _int(r.get("item%d" % i)): _int(r.get("itemcount%d" % i))
            for i in range(1, 7)
            if _int(r.get("item%d" % i)) > 0
        }
        item_objectives_by.setdefault(guid, {})[qid] = item_objectives
    for r in rewarded_rows or ():
        done_by.setdefault(_int(r.get("guid")), set()).add(_int(r.get("quest")))
    return log_by, progress_by, objectives_by, item_objectives_by, done_by


def _alive(row) -> bool:
    """Alive with no health read, above 1, or at 1 with no corpse (a ghost has one)."""
    health = row.get("health")
    if health is None:
        return True
    return _int(health) > 1 or (_int(health) == 1 and not row.get("has_corpse"))


def _member_from_row(
    r,
    quest_log,
    quests_done,
    quest_progress,
    quest_objectives,
    quest_item_objectives,
):
    fresh = r.get("pos_x") is not None and r.get("pos_y") is not None
    map_id = r.get("map_id")
    return Member(
        name=str(r.get("name") or ""),
        level=_int(r.get("level")),
        race=_int(r.get("race")),
        class_id=_int(r.get("class_id")),
        map_id=_int(map_id) if map_id is not None else None,
        x=float(r["pos_x"]) if fresh else None,
        y=float(r["pos_y"]) if fresh else None,
        zone_id=_int(r.get("zone_id") if fresh else r.get("saved_zone")),
        online=bool(_int(r.get("online"))) and fresh,
        alive=_alive(r),
        quest_log=quest_log,
        quests_done=quests_done,
        quest_progress=quest_progress,
        quest_objectives=quest_objectives,
        quest_item_objectives=quest_item_objectives,
    )


def zone_of(zone_id) -> int:
    """The zone a quest's sort or a character's zone column stands for."""
    z = int(zone_id or 0)
    return START_AREAS.get(z, z)


def side_of(race) -> str:
    return (
        levelroute.HORDE if int(race) in levelroute.HORDE_RACES else levelroute.ALLIANCE
    )


@dataclass(frozen=True)
class Facts:
    """What the catalogue knows of a quest beyond classquest.Quest."""

    zone: int
    level: int
    classes: int = 0
    # quest_template_addon.PrevQuestID as stored: positive, rewarded first;
    # negative, held first.
    prev: int = 0
    # A creature is named as its giver (spawned or not).
    giver_named: bool = False
    # What is named to hand it in to: creatures, gameobjects.
    ender_npcs: bool = False
    ender_objects: bool = False
    # The spawns of the gameobjects named to take it (ObjectSpawn), #1594.
    object_enders: tuple = ()
    # A gameobject named to take it has no static spawn: a script or an event
    # summons it, so its absence says nothing of the quest (#1606).
    object_unspawned: bool = False
    # The ways the quests before it can be met (SatisfyQuestPreviousQuest):
    # each a tuple of signed quest ids that must all hold, a positive id
    # rewarded, a negative one held. Its own PrevQuestID and every quest whose
    # NextQuestID names it; a quest before it of a negative exclusive group
    # stands for its whole group. Empty: nothing before it (#1732).
    before: tuple = ()
    # The item the world hands over on the take (StartItem): the take needs a
    # free bag slot for it (CanAddQuest).
    provided_item: int = 0
    # RewardNextQuest, and the quests whose RewardNextQuest names this one
    # (SatisfyQuestNextChain, SatisfyQuestPrevChain).
    chain_next: int = 0
    chain_before: tuple = ()
    # BreadcrumbForQuestId, and the breadcrumbs that name this one
    # (SatisfyQuestBreadcrumb).
    breadcrumb_for: int = 0
    breadcrumbs: tuple = ()
    # (faction, value) of RequiredMinRepFaction / RequiredMaxRepFaction, or
    # None (SatisfyQuestReputation).
    min_rep: tuple | None = None
    max_rep: tuple | None = None


@dataclass(frozen=True)
class ObjectSpawn(classquest.Spawn):
    """A gameobject's spawn a quest is handed in at: its walk is a walk to a
    gameobject spawn, not a creature's (#1594)."""


@dataclass(frozen=True)
class Catalogue:
    """Every quest a quester may take, as a classquest.Book, with each quest's
    zone and level, and each side's zone bands."""

    book: classquest.Book
    facts: dict = field(default_factory=dict)
    # side -> zone -> (floor, ceiling, count), levelroute.bands of these quests
    bands: dict = field(default_factory=dict)
    # side -> the guids of quest givers hostile to that side (`hostile_givers`)
    hostile: dict = field(default_factory=dict)

    def quest(self, quest_id):
        return self.book.quests.get(int(quest_id))


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def catalogue(
    quest_rows, giver_rows, spawn_rows, loot_rows, start_rows, ender_rows, link_rows=()
):
    """The Catalogue from the world's rows: QUESTS_SQL's, classquest's
    GIVERS_SQL, SPAWNS_SQL and LOOT_SQL rows for these quests, STARTERS_SQL's,
    ENDERS_SQL's and LINKS_SQL's.

    Only the classic world: a quest is kept when its zone holds a quest whose
    giver is spawned on a classic continent, or is one of the starting lands.
    """
    rows = list(quest_rows or ())
    book = classquest.build(
        rows, giver_rows, spawn_rows, loot_rows, start_rows=start_rows, every=True
    )
    named, npc_enders, object_enders = _named(start_rows, ender_rows)
    object_spots = _object_ender_spots(ender_rows)
    summoned = _unspawned_object_enders(ender_rows)
    zones = {_int(r.get("id")): zone_of(r.get("zone")) for r in rows}
    classic_zones = _classic_zones(book, zones)
    links = _links(rows, link_rows)
    facts = {}
    kept = {}
    band_rows = []
    for r in rows:
        qid = _int(r.get("id"))
        quest = book.quests.get(qid)
        if quest is None or zones.get(qid, 0) not in classic_zones:
            continue
        facts[qid] = Facts(
            zone=zones[qid],
            level=max(_int(r.get("level")), quest.min_level, 1),
            classes=_int(r.get("classes")),
            prev=_int(r.get("prev_signed")),
            giver_named=qid in named,
            ender_npcs=qid in npc_enders,
            ender_objects=qid in object_enders,
            object_enders=object_spots.get(qid, ()),
            object_unspawned=qid in summoned,
            before=links.before(qid, _int(r.get("prev_signed"))),
            provided_item=_int(r.get("provided0")),
            chain_next=_int(r.get("chain_next")),
            chain_before=tuple(sorted(links.chain_before.get(qid, ()))),
            breadcrumb_for=_int(r.get("crumb_for")),
            breadcrumbs=tuple(sorted(links.breadcrumbs.get(qid, ()))),
            min_rep=_rep(r, "min"),
            max_rep=_rep(r, "max"),
        )
        kept[qid] = quest
        band_rows.append(
            {
                "zone": zones[qid],
                "level": facts[qid].level,
                "races": quest.races,
                "classes": facts[qid].classes,
            }
        )
    bands = {side: levelroute.bands(band_rows, side) for side in levelroute.RACE_MASK}
    return Catalogue(classquest.Book(kept), facts, bands, hostile_givers(giver_rows))


def hostile_givers(giver_rows) -> dict:
    """side -> frozenset of the guids of quest givers that side cannot take a
    quest from: a member of the other side (FactionGroup) or a creature
    hostile to this side (EnemyGroup), off GIVERS_SQL's start rows.

    A HORDE QUEST SENT AN ALLIANCE QUESTER TO DUROTAR (#1998, 2026-11-07).
    The New Horde (787) carries AllowableRaces 0, so the race mask let every
    quester take it, and its band in Durotar was 1, the lowest of any zone.
    Velo, a level 31 Draenei, and Tharn, a level 19 Night Elf, were sent to
    Eitrigg in Orgrimmar (FactionGroup Horde, EnemyGroup Alliance) on every
    pass for hours, and a Tauren was sent to Denalan in Teldrassil the same
    way. A quest is taken only from a giver its side can speak to."""
    out = {side: set() for side in levelroute.RACE_MASK}
    for r in giver_rows or ():
        if r.get("role") != "start":
            continue
        group, enemy = _int(r.get("faction_group")), _int(r.get("enemy_group"))
        for side in out:
            mine = levelroute.GROUP_BIT[side]
            theirs = levelroute.GROUP_BIT[levelroute.OTHER[side]]
            if enemy & mine or group & theirs:
                out[side].add(_int(r.get("guid")))
    return {side: frozenset(guids) for side, guids in out.items()}


def friendly_starters(cat: Catalogue, member, quest) -> tuple:
    """The creature spawns that give the quest which the quester's side can
    take it from (`hostile_givers`)."""
    hostile = cat.hostile.get(side_of(member.race), frozenset())
    return tuple(s for s in quest.starters if s.guid not in hostile)


def _rep(row, end):
    faction = _int(row.get(end + "_rep_faction"))
    return (faction, _int(row.get(end + "_rep_value"))) if faction else None


@dataclass(frozen=True)
class _Links:
    """The relations ObjectMgr::LoadQuests builds across quests (LINKS_SQL)."""

    # quest -> the quests whose NextQuestID names it
    named_next: dict
    # negative exclusive group -> its quests
    groups: dict
    # quest -> its exclusive group
    group_of: dict
    chain_before: dict
    breadcrumbs: dict

    def before(self, qid, prev) -> tuple:
        """Facts.before of a quest: its PrevQuestID (`prev`, signed) and every
        quest whose NextQuestID names it, each as the ids that must all hold."""
        signed = ([prev] if prev else []) + sorted(self.named_next.get(qid, ()))
        out = []
        for p in signed:
            group = self.group_of.get(abs(p), 0)
            way = tuple(sorted(self.groups[group])) if p > 0 and group < 0 else (p,)
            if way not in out:
                out.append(way)
        return tuple(out)


def _links(quest_rows, link_rows) -> _Links:
    named_next, groups, group_of, chain_before, breadcrumbs = {}, {}, {}, {}, {}
    for r in list(quest_rows) + list(link_rows or ()):
        qid = _int(r.get("id"))
        group = _int(r.get("exclusive"))
        if group < 0:
            groups.setdefault(group, set()).add(qid)
            group_of[qid] = group
        if _int(r.get("next")):
            named_next.setdefault(_int(r.get("next")), set()).add(qid)
        if _int(r.get("crumb_for")):
            breadcrumbs.setdefault(_int(r.get("crumb_for")), set()).add(qid)
        if _int(r.get("chain_next")):
            chain_before.setdefault(_int(r.get("chain_next")), set()).add(qid)
    return _Links(named_next, groups, group_of, chain_before, breadcrumbs)


def _named(start_rows, ender_rows) -> tuple:
    """(quests a creature is named to give, quests a creature is named to take,
    quests a gameobject is named to take) from STARTERS_SQL's and ENDERS_SQL's
    rows."""
    named = {
        _int(r.get("quest"))
        for r in start_rows or ()
        if str(r.get("kind") or "") == "creature"
    }
    npc_enders, object_enders = set(), set()
    for r in ender_rows or ():
        kind = str(r.get("kind") or "")
        (npc_enders if kind == "creature" else object_enders).add(_int(r.get("quest")))
    return named, npc_enders, object_enders


def _object_ender_spots(ender_rows) -> dict:
    """quest -> the ObjectSpawn of each spawn of a gameobject named to take it,
    from ENDERS_SQL's rows (a row with guid 0 is an object with no spawn)."""
    out: dict = {}
    for r in ender_rows or ():
        guid = _int(r.get("guid"))
        if str(r.get("kind") or "") != "gameobject" or not guid:
            continue
        spot = ObjectSpawn(
            guid,
            _int(r.get("entry")),
            _int(r.get("map_id")),
            float(r.get("x") or 0.0),
            float(r.get("y") or 0.0),
            str(r.get("name") or ""),
        )
        spots = out.setdefault(_int(r.get("quest")), [])
        if spot not in spots:
            spots.append(spot)
    return {qid: tuple(spots) for qid, spots in out.items()}


def _unspawned_object_enders(ender_rows) -> set:
    """The quests a gameobject with no spawn in the world is named to take
    (ENDERS_SQL's guid 0 rows): one a script or an event summons (#1606)."""
    return {
        _int(r.get("quest"))
        for r in ender_rows or ()
        if str(r.get("kind") or "") == "gameobject" and not _int(r.get("guid"))
    }


def _classic_zones(book, zones) -> set:
    """The starting lands, and every zone holding a quest whose giver is
    spawned on a classic continent."""
    out = set(classic.STARTING_LAND_ZONES)
    for qid, quest in book.quests.items():
        if any(int(s.map_id) in classic.CLASSIC_CONTINENTS for s in quest.starters):
            out.add(zones.get(qid, 0))
    return out


@dataclass(frozen=True)
class Member:
    """One quester as the pass reads it."""

    name: str
    level: int
    race: int
    class_id: int
    map_id: int | None = None
    x: float | None = None
    y: float | None = None
    zone_id: int = 0
    online: bool = False
    alive: bool = True
    # quest id -> status (1 complete, 3 incomplete), the quests in its log
    quest_log: dict = field(default_factory=dict)
    quests_done: frozenset = frozenset()
    # quest id -> the sum of its objective counters
    quest_progress: dict = field(default_factory=dict)
    # quest id -> creature entry -> its objective counter
    quest_objectives: dict = field(default_factory=dict)
    # Free general bag slots (bag_pressure.general_bag_room); None when not
    # read, and a provided item's slot is then not judged (#1732).
    free_slots: int | None = None
    # faction id -> stored standing (REPUTATION_SQL); None when not read.
    reputation: dict | None = None
    # quest id -> required item id -> its objective counter
    quest_item_objectives: dict = field(default_factory=dict)

    @property
    def zone(self) -> int:
        return zone_of(self.zone_id)

    @property
    def placed(self) -> bool:
        return self.map_id is not None and self.x is not None and self.y is not None


@dataclass(frozen=True)
class Broken:
    """A quest found broken: `held` when the quester holds it and drops it."""

    name: str
    quest: int
    title: str
    reason: str
    held: bool = False

    @property
    def ledger_reason(self) -> str:
        return self.reason[:REASON_WIDTH]


@dataclass(frozen=True)
class Attempt:
    """One of a quester's recent rows: what it asked and how it ended."""

    name: str
    command: str
    status: str
    reason: str = ""
    spawn: int = 0
    age_minutes: int = 0
    # What `spawn` is a spawn of: a creature's or a gameobject's. The two
    # number their spawns apart, so a gone object spawn never stands for a
    # creature spawn of the same id (#1594).
    spawn_kind: str = "creature"
    # False only when the module said so (`"retryable":false` in the row's
    # result). A refusal without the field, from a world image older than
    # mod-overseer#19, is retryable, so it keeps the three-strike
    # rule instead of being reported as could-not.
    retryable: bool = True

    @property
    def failed(self) -> bool:
        return self.status in _FAILED

    @property
    def final(self) -> bool:
        """The module refused this row and said no retry can help."""
        return self.failed and not self.retryable


def attempts(rows) -> tuple:
    """Attempt rows from the command log's rows of this pass's source (id,
    target_name, command, source, status, result, age), with the module's
    reason and the spawn a walk named read as guildjobs reads them."""
    out = []
    for row in rows or ():
        if guildjobs.action_of(row.get("source")) not in (ACTION, WALK_ACTION):
            continue
        read = guildjobs.recent_from_rows([row])
        recent = read[0] if read else None
        spawn, kind = _spawn_named(row.get("command"), recent)
        out.append(
            Attempt(
                name=str(row.get("target_name") or ""),
                command=str(row.get("command") or ""),
                status=str(row.get("status") or ""),
                reason=(recent.reason or recent.refusal) if recent else "",
                spawn=spawn,
                spawn_kind=kind,
                age_minutes=_int(row.get("age"), 10**6),
                retryable='"retryable":false' not in str(row.get("result") or ""),
            )
        )
    return tuple(out)


def _spawn_named(command, recent) -> tuple:
    """(spawn id, kind) a walk row named: guildjobs reads a creature walk's
    spawn only (`_spawn_of`), so a walk to a gameobject ender's spawn
    (`walk-to-spawn gameobject:<id>`, #1594) is read here, else the world's
    "no such spawn" for it never reached the quest's broken check."""
    if recent is not None and recent.spawn:
        return int(recent.spawn), "creature"
    found = re.match(r"walk-to-spawn gameobject:(\d+)\b", str(command or ""))
    return (int(found.group(1)), OBJECT_KIND) if found else (0, "creature")


def gone_spawns(name, tried, kind="creature") -> frozenset:
    """The spawn ids of `kind` the world told this quester are not in the
    world."""
    return frozenset(
        a.spawn
        for a in tried or ()
        if a.name == name and a.spawn and a.reason == GONE and a.spawn_kind == kind
    )


def left_spawns(name, tried, kind="creature") -> frozenset:
    """The spawn ids this quester leaves for now: the gone ones, and those a
    walk was refused for a lasting reason (classquest.SPAWN_REFUSALS: a drop on
    the way, the other side's ground, a road through ground far above its
    level) inside classquest.SPAWN_REFUSED_MINUTES,
    or for a short one (stopped getting nearer, died on the way) inside
    classquest.SPAWN_SHORT_MINUTES. Only the gone ones say the quest is broken:
    the rest say the way there is, for now."""
    out = set(gone_spawns(name, tried, kind))
    for a in tried or ():
        if a.name != name or not a.spawn or a.reason not in classquest.SPAWN_REFUSALS:
            continue
        if a.spawn_kind != kind:
            continue
        short = a.reason in classquest.SPAWN_SHORT_REFUSALS
        hold = (
            classquest.SPAWN_SHORT_MINUTES
            if short
            else classquest.SPAWN_REFUSED_MINUTES
        )
        if a.age_minutes < hold:
            out.add(a.spawn)
    return frozenset(out)


# THE FAR WALK WALLS A QUESTER WAITS OUT (#1295). The module refuses a far walk
# while the realm has as many under way as it allows, once the bot has started
# as many this hour as one may, and while another verb holds the character
# (classquest.REALM_FULL_REASON, BOT_BUDGET_REASON, HELD_REASON). None of these
# says the giver or the way to it is the trouble, and each lifts on its own
# clock, so the quester waits the class quest's time for it
# (classquest.BACKOFF_MINUTES) instead of asking the same walk every pass:
# from 2026-10-18 to 2026-10-20 the twenty questers' walks were refused 2,276
# times for the budget and 2,453 times as held, about every two minutes.
#
# A walk refused as across the water (classquest.ACROSS_WATER_REASON, #2194) is
# a wall too, at any distance: asking it again unchanged gets the same answer.
WALK_WALLS = (
    classquest.REALM_FULL_REASON,
    classquest.BOT_BUDGET_REASON,
    classquest.HELD_REASON,
    classquest.ACROSS_WATER_REASON,
)
# The walls that hold a near walk as well as a far one.
NEAR_WALLS = (classquest.HELD_REASON, classquest.ACROSS_WATER_REASON)


def walk_wall(name, tried) -> tuple:
    """(the wall's words, minutes still to wait) when this quester's newest row
    was refused for a far walk wall (WALK_WALLS) younger than its
    classquest.BACKOFF_MINUTES; ("", 0) otherwise. A row of the same minute
    that was not refused for a wall lifts it."""
    mine = [a for a in tried or () if a.name == name]
    if not mine:
        return "", 0
    age = min(a.age_minutes for a in mine)
    newest = [a for a in mine if a.age_minutes == age]
    if not all(a.failed and a.reason in WALK_WALLS for a in newest):
        return "", 0
    reason = newest[0].reason
    wait = classquest.BACKOFF_MINUTES[reason] - age
    return (reason, wait) if wait > 0 else ("", 0)


def refusals(name, tried) -> dict:
    """(verb, quest id) -> (times refused, the last words) for this quester's
    takes and hand-ins the world refused."""
    out: dict = {}
    for a in sorted(tried or (), key=lambda a: -a.age_minutes):
        if a.name != name or not a.failed or a.reason in LOG_STATE_REFUSALS:
            continue
        if a.reason == BAG_ROOM_REFUSAL:
            continue
        found = _CHAIN_ROW.match(a.command)
        if not found:
            continue
        key = (found.group(1), int(found.group(2)))
        count, _words = out.get(key, (0, ""))
        out[key] = (count + 1, a.reason)
    return out


def bag_room_refused(name, tried) -> frozenset:
    """The quest ids whose take this quester's world refused for bag room
    (BAG_ROOM_REFUSAL) inside SELL_COOLDOWN_MINUTES: the sale goes first, and
    the take is asked again after it (#1992)."""
    out = set()
    for a in tried or ():
        if a.name != name or not a.failed or a.reason != BAG_ROOM_REFUSAL:
            continue
        if a.age_minutes >= SELL_COOLDOWN_MINUTES:
            continue
        found = _CHAIN_ROW.match(a.command)
        if found and found.group(1) == "take":
            out.add(int(found.group(2)))
    return frozenset(out)


def cannot_turn_in(name, tried) -> dict:
    """quest id -> the module's words, for each hand-in of this quester the
    module refused as never retryable (CANNOT_TURN_IN), newest words kept.
    A refusal about the log's state (LOG_STATE_REFUSALS) is left out."""
    out: dict = {}
    for a in sorted(tried or (), key=lambda a: -a.age_minutes):
        if a.name != name or not a.final or a.reason in LOG_STATE_REFUSALS:
            continue
        found = _CHAIN_ROW.match(a.command)
        if found and found.group(1) == "turnin":
            out[int(found.group(2))] = a.reason
    return out


def _module_complete(name, tried) -> frozenset:
    """The quest ids the module told this quester are complete, by refusing
    their abandon with its complete words: they are due a turn-in, never a
    drop (#1085)."""
    return frozenset(
        qid
        for (verb, qid), (_count, words) in refusals(name, tried).items()
        if verb == "abandon" and COMPLETE_HAND_IN in (words or "")
    )


def turn_in_held(name, tried) -> frozenset:
    """The quest ids whose hand-in this quester leaves for now: the world
    refused it FAILS_BEFORE_BROKEN times or more, and its last refusal is
    newer than TURN_IN_RETRY_MINUTES, doubled for each refusal past those.

    A REFUSED HAND-IN WAS ASKED EVERY PASS FOREVER (2026-10-20). A complete
    quest whose hand-in was refused three times was found broken and its
    abandon was refused as complete (#1085); the module-complete quest then
    came back as the nearest hand-in every pass, past the broken skip. Kellan
    walked to Farmer Saldean and handed in The Killing Fields 216 times in
    42 hours, Pindle Return to Bellowfiz 511 times, each refused for the same
    lasting reason ("no taker of that quest in reach"). Asked again only after
    the hold, the quester gets on with the rest of its zone meanwhile.

    A hand-in the module refused as never retryable (`cannot_turn_in`) is held
    from the first refusal for as long as that row is in the rows the pass
    reads: asking again cannot change the answer."""
    count: dict = {}
    newest: dict = {}
    for a in tried or ():
        if a.name != name or not a.failed:
            continue
        found = _CHAIN_ROW.match(a.command)
        if not found or found.group(1) != "turnin":
            continue
        qid = int(found.group(2))
        count[qid] = count.get(qid, 0) + 1
        newest[qid] = min(newest.get(qid, a.age_minutes), a.age_minutes)
    return frozenset(
        qid
        for qid, times in count.items()
        if times >= FAILS_BEFORE_BROKEN
        and newest[qid] < TURN_IN_RETRY_MINUTES * 2 ** (times - FAILS_BEFORE_BROKEN)
    ) | frozenset(cannot_turn_in(name, tried))


class Clock:
    """Play time with no objective moving, per quester and quest.

    `observe` is told each pass what the quest's objectives read (its status and
    counters) and whether the quester was working it; it answers the seconds of
    play since they last moved. Its state is plain data (`dump`, `load`), so the
    bridge keeps it across restarts."""

    def __init__(self):
        # (name, quest) -> [value, seconds played without a move, last look]
        self._by: dict = {}

    def observe(self, name, quest, value, now, playing) -> float:
        key = (str(name), int(quest))
        value = list(value)
        held = self._by.get(key)
        if held is None or held[0] != value:
            self._by[key] = [value, 0.0, float(now)]
            return 0.0
        gap = float(now) - float(held[2])
        if playing and 0 < gap:
            held[1] += min(gap, PLAY_GAP_SECONDS)
        held[2] = float(now)
        return held[1]

    def played(self, name, quest) -> float:
        held = self._by.get((str(name), int(quest)))
        return held[1] if held else 0.0

    def forget(self, name, keep) -> None:
        """Drop every quest of `name` not in `keep` (no longer in its log)."""
        keep = {int(q) for q in keep}
        for key in [k for k in self._by if k[0] == name and k[1] not in keep]:
            del self._by[key]

    def reset(self, name, quest) -> None:
        """Start a fresh no-progress interval for one quest."""
        self._by.pop((str(name), int(quest)), None)

    def dump(self) -> dict:
        return {"%s:%d" % k: v for k, v in self._by.items()}

    def load(self, data) -> None:
        for key, held in (data or {}).items():
            name, _, quest = str(key).rpartition(":")
            try:
                value, played, last = held
                self._by[(name, int(quest))] = [list(value), float(played), float(last)]
            except (TypeError, ValueError):
                continue


def _yards(member, spawn) -> float:
    return math.hypot(float(member.x) - spawn.x, float(member.y) - spawn.y)


def _here(member, spawns, gone=frozenset()) -> list:
    if not member.placed:
        return []
    return [
        s for s in spawns if int(s.map_id) == int(member.map_id) and s.guid not in gone
    ]


def _nearest(member, spawns, gone=frozenset()):
    here = _here(member, spawns, gone)
    return min(here, key=lambda s: (_yards(member, s), s.guid)) if here else None


def _class_ok(facts: Facts, class_id) -> bool:
    return not facts.classes or bool(facts.classes & (1 << (int(class_id) - 1)))


def _exclusive_closed(cat: Catalogue, member, quest) -> bool:
    if not quest.exclusive:
        return False
    return any(
        other.exclusive == quest.exclusive
        and other.id != quest.id
        and (other.id in member.quests_done or other.id in member.quest_log)
        for other in cat.book.quests.values()
    )


def open_to(cat: Catalogue, member, quest_id, broken=frozenset()) -> bool:
    """Whether the quester may take this quest now: race, class, level, the
    quest before it, its exclusive group, and not done, held or broken."""
    qid = int(quest_id)
    quest, facts = cat.quest(qid), cat.facts.get(qid)
    if quest is None or facts is None:
        return False
    if qid in member.quests_done or qid in member.quest_log or qid in broken:
        return False
    if not quest.admits(member.race) or not _class_ok(facts, member.class_id):
        return False
    if quest.starters and not friendly_starters(cat, member, quest):
        return False
    if int(member.level) < quest.min_level:
        return False
    if facts.level > int(member.level) + levelroute.ABOVE:
        return False
    if facts.before and not any(
        all(_before_met(member, p) for p in way) for way in facts.before
    ):
        return False
    if _chain_closed(member, facts) or _breadcrumb_closed(member, facts):
        return False
    if not _reputation_ok(member, facts):
        return False
    if facts.provided_item and member.free_slots is not None and member.free_slots < 1:
        return False
    return not _exclusive_closed(cat, member, quest)


def _before_met(member, signed) -> bool:
    """A quest before this one is met: rewarded (positive), or held or
    rewarded (negative: GetQuestStatus is not NONE)."""
    if signed > 0:
        return signed in member.quests_done
    return -signed in member.quest_log or -signed in member.quests_done


def _chain_closed(member, facts: Facts) -> bool:
    """The quest its RewardNextQuest names is held or rewarded, or a quest
    whose RewardNextQuest names it is held."""
    nxt = facts.chain_next
    if nxt and (nxt in member.quest_log or nxt in member.quests_done):
        return True
    return any(q in member.quest_log for q in facts.chain_before)


def _breadcrumb_closed(member, facts: Facts) -> bool:
    """A breadcrumb whose target is held or rewarded, or a target while one of
    its breadcrumbs is held."""
    target = facts.breadcrumb_for
    if target and (target in member.quest_log or target in member.quests_done):
        return True
    return any(q in member.quest_log for q in facts.breadcrumbs)


def _reputation_ok(member, facts: Facts) -> bool:
    """The stored standing meets RequiredMinRepValue and is under
    RequiredMaxRepValue. Unread reputation is not judged. The stored standing
    leaves out the faction's base reputation (ReputationMgr adds it): 0 for
    most factions these gates name (Warsong Outriders, Silverwing Sentinels,
    Argent Dawn), and below 0 for a few, where this check is looser than the
    world's and the take is refused as before."""
    if member.reputation is None:
        return True
    if facts.min_rep and member.reputation.get(facts.min_rep[0], 0) < facts.min_rep[1]:
        return False
    return not (
        facts.max_rep and member.reputation.get(facts.max_rep[0], 0) >= facts.max_rep[1]
    )


def in_reach(cat: Catalogue, member, zone, broken=frozenset()) -> list:
    """The quest ids of `zone` the quester may take now, in id order."""
    return [
        qid
        for qid, facts in sorted(cat.facts.items())
        if facts.zone == int(zone) and open_to(cat, member, qid, broken)
    ]


def _working(cat: Catalogue, member, last_quest=0, left=frozenset()) -> set:
    """The quests whose stall clock runs now: the quest the quester's last move
    was for, and each quest of its log of the zone it stands in that it has
    no objective spawn to hunt (`_unhuntable`).

    A QUEST WAITING ITS TURN WAS DROPPED AS STALLED (2026-11-02). A quester
    takes every quest in reach first and then hunts them one at a time, the
    nearest spawn first (`next_move`). The clock ran for every quest of the
    zone, so while it hunted one, each of the others reached two hours of play
    with nothing moved, was dropped and was filed as broken: Westfall Stew,
    Bounty on Murlocs, Red Linen Goods, The Night Watch, Kobold Candles and
    a dozen more in one day, each one a quest no quester had yet gone after.
    A quest it could hunt waits its turn; one it cannot hunt has nothing to
    wait for, so its clock still runs and a quest nobody can work still
    stalls (STALLED_UNSOURCED)."""
    out = {
        qid
        for qid in member.quest_log
        if (
            cat.facts.get(qid) is not None
            and cat.facts[qid].zone == member.zone
            and _unhuntable(cat, member, qid, left)
        )
    }
    if last_quest and int(last_quest) in member.quest_log:
        out.add(int(last_quest))
    return out


def _unhuntable(cat: Catalogue, member, qid, left=frozenset()) -> bool:
    """True when the quester has no objective spawn of this quest to hunt
    (`_hunt`'s own choice: a solo field within its level, on its map, not one
    it leaves for now, or on the other classic continent, which `_hunt`
    crosses to)."""
    quest = cat.quest(qid)
    if quest is None:
        return True
    fields = classquest.within_level(member, classquest.solo_fields(quest))
    if _nearest(member, fields, left) is not None:
        return False
    if member.placed:
        routable = tuple(s for s in fields if s.guid not in left)
        return classquest.far_map(member, routable) < 0
    return True


def _fields_gone(quest, gone) -> bool:
    """Every spawn of the objective was refused as not in the world."""
    return bool(quest.fields) and all(s.guid in gone for s in quest.fields)


def _ender_missing(quest, facts: Facts, gone, object_gone=frozenset()) -> str:
    """Why there is nothing to hand the quest in to, "" when there is: no
    named creature is spawned and no named gameobject is either (or every
    spawn of them was refused as gone). A quest only a gameobject takes is
    missing its object, not its NPC (#1594)."""
    if _ender_spots(quest, facts, gone, object_gone):
        return ""
    if not facts.ender_npcs and not facts.ender_objects:
        return NO_TURN_IN_NAMED
    if facts.ender_objects and not facts.ender_npcs:
        return OBJECT_ENDER_MISSING
    return ENDER_MISSING


def _ender_spots(quest, facts, gone=frozenset(), object_gone=frozenset()) -> tuple:
    """Every spawn the quest is handed in at: its creature enders' not in
    `gone` and, after them, its gameobject enders' (ObjectSpawn) not in
    `object_gone`. Each kind is weighed against its own spawn ids."""
    objects = facts.object_enders if facts is not None else ()
    return tuple(s for s in quest.enders if s.guid not in gone) + tuple(
        s for s in objects if s.guid not in object_gone
    )


def failures(cat: Catalogue, member, clock, now, tried=(), last_quest=0) -> list:
    """Broken rows for the quests the quester holds that cannot be finished:
    a stall of STALL_SECONDS of play, a turn-in NPC or an objective the world
    does not hold, or a take or a hand-in the world keeps refusing. The clock
    is told every quest in the log, so it must be asked once a pass."""
    gone = gone_spawns(member.name, tried)
    object_gone = gone_spawns(member.name, tried, OBJECT_KIND)
    refused = refusals(member.name, tried)
    final = cannot_turn_in(member.name, tried)
    working = _working(cat, member, last_quest, left_spawns(member.name, tried))
    playing = bool(member.online and member.alive)
    out = []
    for qid in sorted(member.quest_log):
        status = int(member.quest_log[qid])
        prog = int(member.quest_progress.get(qid, 0))
        value = (status, prog)
        played = clock.observe(member.name, qid, value, now, playing and qid in working)
        quest, facts = cat.quest(qid), cat.facts.get(qid)
        if quest is None or facts is None:
            continue
        reason = _broken_reason(
            quest, facts, status, played, gone, refused, final, object_gone, prog
        )
        if reason:
            out.append(Broken(member.name, qid, quest.title, reason, held=True))
    clock.forget(member.name, member.quest_log)
    return out


def _broken_reason(
    quest,
    facts: Facts,
    status,
    played,
    gone,
    refused,
    final=None,
    object_gone=frozenset(),
    progress=0,
) -> str:
    """Why a quest the quester holds is broken, "" when it is not (yet). A
    complete quest's objectives cannot move, so stillness never stalls it:
    it is due a turn-in, not a drop (#1085)."""
    if status == STATUS_FAILED:
        return FAILED
    if quest.id in (35, 109):
        return UNSUPPORTED_OBJECTIVE
    if quest.id == 93 and status == STATUS_INCOMPLETE and (2683, 6) in quest.items:
        return CRAFTED_CRAB_CAKES
    if quest.id == 64 and status == STATUS_INCOMPLETE and played >= STALL_SECONDS:
        return FORGOTTEN_HEIRLOOM
    if quest.id == 62 and status == STATUS_INCOMPLETE and played >= STALL_SECONDS:
        return FARGODEEP_EXPLORATION
    if quest.id == 127 and status == STATUS_INCOMPLETE and played >= STALL_SECONDS:
        return SELLING_FISH
    if quest.id == 122 and status == STATUS_INCOMPLETE and played >= STALL_SECONDS:
        return UNDERBELLY_SCALES
    if (
        quest.id == 132
        and status == STATUS_INCOMPLETE
        and (1327, 1) in quest.items
        and played >= STALL_SECONDS
    ):
        return DEFIAS_BROTHERHOOD
    if (
        quest.id == 149
        and status == STATUS_INCOMPLETE
        and (1453, 1) in quest.items
        and played >= STALL_SECONDS
    ):
        return GHOST_HAIR_THREAD
    missing = _ender_missing(quest, facts, gone, object_gone)
    # An incomplete quest one of whose enders is an object with no static
    # spawn is not judged on its ender: a script or an event summons that
    # object, so the quest is worked, and only a stall breaks it (#1606).
    complete = _quest_complete(quest, status, progress)
    if missing and not (not complete and facts.object_unspawned):
        return missing
    if not complete and _fields_gone(quest, gone):
        return SOURCE_MISSING
    if quest.id in (final or {}):
        return _refused_words(CANNOT_TURN_IN, final[quest.id])
    count, words = refused.get(("turnin", quest.id), (0, ""))
    if count >= FAILS_BEFORE_BROKEN:
        return _refused_words(REFUSED_TURN_IN, words)
    if played < STALL_SECONDS or complete:
        return ""
    unsourced = (quest.kills or quest.items) and not quest.fields
    return STALLED_UNSOURCED if unsourced else STALLED


def _refused_words(reason, words) -> str:
    return "%s: %s" % (reason, words) if words else reason


def _giver_failure(cat: Catalogue, member, qid, gone, refused):
    """The reason a quest in reach cannot be taken, "" when it can or when what
    stands in the way is no fault of the quest (a giver on another map, or a
    quest a gameobject or an item starts, which no verb takes)."""
    quest, facts = cat.quest(qid), cat.facts[qid]
    if int(qid) in (35, 109):
        return UNSUPPORTED_OBJECTIVE
    count, words = refused.get(("take", qid), (0, ""))
    if count >= FAILS_BEFORE_BROKEN:
        return _refused_words(REFUSED_TAKE, words)
    if any(kind != "creature" for kind, _entry in quest.other_starts):
        return ""
    if facts.giver_named and not [s for s in quest.starters if s.guid not in gone]:
        return GIVER_MISSING
    return ""


@dataclass(frozen=True)
class Plan:
    """One quester's pass: its move (None for none), the quests it found broken,
    and a line saying what it does or why it waits."""

    name: str
    move: classquest.Move | None = None
    broken: tuple = ()
    line: str = ""
    # The island boat step that takes the place of the move's walk when its
    # spot is across the island's shore (guildjobs.island_boat_step, #2194).
    boat: object = None


def _move(kind, member, quest, spot, said, to_map=-1) -> classquest.Move:
    return classquest.Move(
        kind,
        quest.id,
        quest.klass,
        spot,
        said,
        "",
        "quester",
        title=quest.title,
        to_map=to_map,
    )


def _giver_to_go_to(
    cat: Catalogue, member, quest_id, gone=frozenset(), unsailed=frozenset()
) -> bool:
    """Whether a creature that gives the quest stands where the quester can go
    and take it: on the quester's own map or on a classic continent it can
    cross to and has not just failed to cross to (`unsailed`), and not one it
    leaves for now (`left_spawns`). A quest only an item or a gameobject starts
    has none: no verb takes it, so it is no reason to go to its zone."""
    here = int(member.map_id) if member.placed else None
    return any(
        s.guid not in gone
        and (
            int(s.map_id) == here
            or (
                int(s.map_id) in classquest.CONTINENTS and int(s.map_id) not in unsailed
            )
        )
        for s in friendly_starters(cat, member, cat.quest(quest_id))
    )


def failed_crossings(name, crossings) -> frozenset:
    """The maps the quester is not sent across to for now: each map the module
    refused for good (guildjobs.class_walls, classquest.CROSS_WALL_MINUTES),
    and the map of its newest crossing row when the module refused that row
    and the crossing clock still holds it (guildjobs.crossing_cooling,
    classquest.CROSS_RETRY_MINUTES or CROSS_COOLDOWN_MINUTES). A crossing
    still under way refused nothing and is not one of these.

    A FAILED CROSSING CHOSE THE SAME ZONE AGAIN (2026-10-19). Alliance
    questers of 15 and 16 in Dun Morogh had one quest left in reach in
    Durotar, and its band was the lowest, so `next_zone` chose Durotar every
    pass. The module's walk to the berth gave up on the ground, the crossing
    clock held the quester where it stood ("waits on its last crossing"), and
    when the clock lapsed it chose Durotar and failed again, for hours. While
    the crossing is held, the quester goes on to the best zone it can reach
    without it, and only with none is it held as before."""
    out = set(guildjobs.class_walls(name, crossings))
    rows = [
        r
        for r in crossings or ()
        if r.name == name and r.action in guildjobs.CROSS_ACTIONS
    ]
    if rows and guildjobs.crossing_cooling(name, crossings):
        newest = min(rows, key=lambda r: int(r.age_minutes))
        if newest.refusal and (newest.dest or classquest.is_cross_row(newest.command)):
            out.add(int(newest.dest))
    return frozenset(out)


def next_zone(
    cat: Catalogue, member, broken=frozenset(), gone=frozenset(), unsailed=frozenset()
):
    """(zone, its open quest ids) of the zone the quester goes to next, or
    (0, []) when no zone holds a quest in reach for it: the lowest band of
    its side among those zones, the most quests first on a tie. A quest counts
    only when a giver of it is one the quester can go to (`_giver_to_go_to`):
    a zone whose open quests an item or a gameobject starts, or whose givers
    are all gone or left, is passed over, not chosen and then found to have no
    way there, pass after pass. A giver on a continent in `unsailed` (the maps
    its last crossings failed to reach for now, `failed_crossings`) counts only
    when it stands on the quester's own map.

    A zone holding a quest near the quester's level (no more than
    levelroute.GREEN_BELOW under it) comes before a zone of grey leftovers,
    whatever their bands (#1998: Velo at 31 was sent to a level 1 quest in
    Durotar, and Morwick at 29 to a level 18 one in Redridge, because the
    lowest band always came first)."""
    bands = cat.bands.get(side_of(member.race), {})
    floor = int(member.level) - levelroute.GREEN_BELOW
    best = None
    for zone in sorted({f.zone for f in cat.facts.values()} - {member.zone}):
        opens = [
            qid
            for qid in in_reach(cat, member, zone, broken)
            if _giver_to_go_to(cat, member, qid, gone, unsailed)
        ]
        if not opens:
            continue
        band = bands.get(zone, (0, 0, 0))
        grey = all(cat.facts[qid].level < floor for qid in opens)
        key = (grey, int(band[0]), -len(opens), zone)
        if best is None or key < best[0]:
            best = (key, zone, opens)
    return (best[1], best[2]) if best else (0, [])


def _travel(cat: Catalogue, member, broken, gone, unsailed=frozenset()):
    """The move that takes the quester to the next zone: the take of that
    zone's nearest quest on its map, or a crossing to the continent the zone's
    quests are on; (None, why) when there is no zone to go to. A zone across
    a crossing that just failed (`unsailed`) is passed over while another zone
    is left; with none, the zone is chosen as before and its crossing waits
    on the crossing clock (`crossing_held`)."""
    zone, opens = next_zone(cat, member, broken, gone, unsailed)
    if not zone and unsailed:
        zone, opens = next_zone(cat, member, broken, gone)
    if not zone:
        return None, "%s has no quest in reach in any zone" % member.name
    name = levelroute.zone_name(zone)
    options = []
    for qid in opens:
        quest = cat.quest(qid)
        spot = _nearest(member, friendly_starters(cat, member, quest), gone)
        if spot is not None:
            options.append((_yards(member, spot), qid, quest, spot))
    if options:
        _d, _q, quest, spot = min(options, key=lambda o: (o[0], o[1]))
        said = (
            "%s has nothing left in reach here and goes on to %s: walks to %s and takes %s"
            % (member.name, name, spot.name or "its giver", quest.title)
        )
        return _move(classquest.TAKE, member, quest, spot, said), ""
    maps = sorted(
        {
            int(s.map_id)
            for qid in opens
            for s in friendly_starters(cat, member, cat.quest(qid))
            if int(s.map_id) in classquest.CONTINENTS and s.guid not in gone
        }
    )
    if maps and member.placed and int(member.map_id) not in maps:
        quest = cat.quest(opens[0])
        said = "%s crosses to %s for %s" % (
            member.name,
            classquest.CONTINENTS[maps[0]],
            name,
        )
        return _move(classquest.CROSS, member, quest, None, said, to_map=maps[0]), ""
    return None, "%s would go on to %s and has no way there from where it stands" % (
        member.name,
        name,
    )


def next_move(
    cat: Catalogue, member, broken=frozenset(), found=(), tried=(), crossings=()
):
    """(move or None, why there is none, quests found broken that it never
    held): the quester's next move toward every quest in reach.

    `broken` is the quest ids already found broken for this quester, `found`
    this pass's Broken rows for the quests it holds (`failures`), `crossings`
    the realm's recent crossing rows (`failed_crossings`)."""
    left = left_spawns(member.name, tried)
    # Quests the module told this quester are complete: due a turn-in, never
    # a drop, even when their log row still says otherwise (#1085).
    complete = _module_complete(member.name, tried)
    # The quests its log holds complete. The module refuses to abandon any of
    # them ("it is complete; hand it in"), so none is ever dropped, whatever
    # broke it: a stall the ledger kept from before #1085, a turn-in NPC that
    # is not there, a hand-in the world keeps refusing (#1085).
    logged_complete = {
        qid
        for qid, status in member.quest_log.items()
        if _quest_complete(cat.quest(qid), status, member.quest_progress.get(qid, 0))
    }
    # 1. A broken quest it holds is dropped.
    move = _drop(cat, member, broken, found, complete | logged_complete)
    if move is not None:
        return move, "", []
    skip = set(broken) | {b.quest for b in found}
    # A take just refused for bag room waits on the sale (#1992).
    take_skip = skip | bag_room_refused(member.name, tried)
    # 2. A complete quest, the nearest turn-in NPC first. One only the ledger
    # holds broken is still handed in; one whose turn-in NPC this pass found
    # missing is left, and so is one whose hand-in the world keeps refusing,
    # until its hold is over (`turn_in_held`), the module-complete ones too.
    hand_skip = turn_in_held(member.name, tried) | {
        b.quest for b in found if b.reason in (ENDER_MISSING, OBJECT_ENDER_MISSING)
    }
    object_left = left_spawns(member.name, tried, OBJECT_KIND)
    move = _hand_in(cat, member, hand_skip, left, complete, object_left)
    if move is not None:
        return move, "", []
    # 3. A quest in reach in its zone, the nearest giver first, while the log
    # has room.
    takes, never_held = _takes(cat, member, take_skip, left, tried)
    skip |= {b.quest for b in never_held}
    if takes and len(member.quest_log) < LOG_SLOTS:
        _d, _q, quest, spot = min(takes, key=_by_yards)
        said = "%s walks to %s and takes %s" % (
            member.name,
            spot.name or "its giver",
            quest.title,
        )
        return _move(classquest.TAKE, member, quest, spot, said), "", never_held
    # 4. A quest it holds: the nearest objective spawn within its level.
    move = _hunt(cat, member, skip, left)
    crossing_wait = ""
    if move is not None and move.kind == classquest.CROSS:
        crossing_wait = crossing_held(member.name, move, crossings)
        if crossing_wait:
            move = None
    if move is not None:
        return move, "", never_held
    if takes:
        return (
            None,
            "%s's quest log is full (%d of %d)"
            % (member.name, len(member.quest_log), LOG_SLOTS),
            never_held,
        )
    # 5. Nothing left in reach here: the next zone.
    unsailed = failed_crossings(member.name, crossings)
    move, why = _travel(cat, member, skip, left, unsailed)
    if move is None and crossing_wait:
        why = crossing_wait
    return move, why, never_held


def _by_yards(option):
    """The sort key of a (yards, quest id, quest, spot) option: nearest first,
    then the lowest quest id."""
    return option[0], option[1]


def _drop(cat: Catalogue, member, broken, found, complete=frozenset()):
    """The drop of the first broken quest the quester holds, or None. A quest
    in `complete` (the module called it complete, or the log holds it
    complete) is never dropped: the module refuses that abandon (#1085)."""
    held_broken = [b for b in found if b.held and b.quest not in complete] + [
        Broken(member.name, q, cat.quest(q).title if cat.quest(q) else "", "", True)
        for q in sorted(member.quest_log)
        if q in broken and q not in complete
    ]
    if not held_broken:
        return None
    b = held_broken[0]
    quest = cat.quest(b.quest) or classquest.Quest(
        b.quest, b.title, 0, 0, 0, 0, 0, 0, 0
    )
    said = "%s drops %s: %s" % (
        member.name,
        b.title or b.quest,
        b.reason or "it is broken",
    )
    return _move(classquest.ABANDON, member, quest, None, said)


def _held(cat: Catalogue, member, status, skip):
    """(quest id, quest) of each quest in the log at `status`, not in `skip`."""
    for qid, held in member.quest_log.items():
        quest = cat.quest(qid)
        if quest is not None and int(held) == status and qid not in skip:
            yield qid, quest


def _hand_in(
    cat: Catalogue, member, skip, left, complete=frozenset(), object_left=frozenset()
):
    """The hand-in of the complete quest whose turn-in NPC or object is
    nearest, or None. A quest the module called complete is handed in even when its log
    row still says otherwise (#1085); `skip` leaves it as it leaves any other."""
    due = {
        qid
        for qid, status in member.quest_log.items()
        if qid not in skip
        and _quest_complete(cat.quest(qid), status, member.quest_progress.get(qid, 0))
    }
    due |= {qid for qid in complete if qid in member.quest_log and qid not in skip}
    ready = []
    for qid in due:
        quest = cat.quest(qid)
        spot = (
            _nearest(member, _ender_spots(quest, cat.facts.get(qid), left, object_left))
            if quest is not None
            else None
        )
        if spot is not None:
            ready.append((_yards(member, spot), qid, quest, spot))
    if not ready:
        return None
    _d, _q, quest, spot = min(ready, key=_by_yards)
    said = "%s walks to %s and hands in %s" % (
        member.name,
        spot.name or "its ender",
        quest.title,
    )
    return _move(classquest.TURN_IN, member, quest, spot, said)


def _takes(cat: Catalogue, member, skip, left, tried) -> tuple:
    """(the (yards, quest id, quest, giver) of each quest in reach in the
    quester's zone with a giver it can walk to, Broken rows for those whose
    giver fails). A quest found broken here is added to `skip`."""
    gone = gone_spawns(member.name, tried)
    refused = refusals(member.name, tried)
    never_held = []
    takes = []
    for qid in in_reach(cat, member, member.zone, skip):
        why = _giver_failure(cat, member, qid, gone, refused)
        if why:
            never_held.append(Broken(member.name, qid, cat.quest(qid).title, why))
            skip.add(qid)
            continue
        spot = _nearest(member, friendly_starters(cat, member, cat.quest(qid)), left)
        if spot is not None:
            takes.append((_yards(member, spot), qid, cat.quest(qid), spot))
    return takes, never_held


def _hunt(cat: Catalogue, member, skip, left):
    """The hunt at the nearest objective spawn within the quester's level of
    an incomplete quest it holds, or a crossing to one on the other classic
    continent. A nearby hunt always takes priority over a crossing."""
    hunts = []
    crossings = []
    for qid, quest in _held(cat, member, STATUS_INCOMPLETE, skip):
        if _quest_complete(quest, STATUS_INCOMPLETE, member.quest_progress.get(qid, 0)):
            continue
        fields = tuple(
            spot
            for spot in _held_objective_fields(member, qid, quest)
            if spot.guid not in left
        )
        spot = _nearest(member, fields, left)
        if spot is not None:
            hunts.append((_yards(member, spot), qid, quest, spot))
            continue
        # A held quest can outlive the trip that took it. If its eligible
        # objectives are only on the other continent, cross to them before
        # choosing a new zone. Otherwise an incomplete Redridge quest held in
        # Darnassus is invisible to both the local hunt and next-zone search.
        to_map = classquest.far_map(member, fields)
        if to_map >= 0:
            crossings.append((qid, quest, to_map))
    if not hunts:
        if not crossings:
            return None
        _qid, quest, to_map = min(crossings, key=lambda option: option[0])
        said = "%s crosses to %s for %s" % (
            member.name,
            classquest.CONTINENTS[to_map],
            quest.title,
        )
        return _move(classquest.CROSS, member, quest, None, said, to_map=to_map)
    _d, _q, quest, spot = min(hunts, key=_by_yards)
    said = "%s works %s at %s" % (
        member.name,
        quest.title,
        spot.name or "its objective",
    )
    return _move(classquest.HUNT, member, quest, spot, said)


def stalled_holds_with_actionable_objectives(
    cat, member, held, tried=(), crossings=()
) -> frozenset:
    """Stalled memo entries whose incomplete objectives can now be pursued.

    World-fact holds remain durable. A stall is only retried when this pass can
    route to an eligible local objective or across a known classic continent.
    """
    if not member.placed:
        return frozenset()
    left = left_spawns(member.name, tried)
    retry = set()
    for qid, reason in held.items():
        if not str(reason).startswith(STALLED):
            continue
        if member.quest_log.get(qid) != STATUS_INCOMPLETE:
            continue
        quest = cat.quest(qid)
        if quest is None or _quest_complete(
            quest, STATUS_INCOMPLETE, member.quest_progress.get(qid, 0)
        ):
            continue
        fields = tuple(
            spot
            for spot in _held_objective_fields(member, qid, quest)
            if spot.guid not in left
        )
        if _nearest(member, fields, left) is not None:
            retry.add(qid)
            continue
        to_map = classquest.far_map(member, fields)
        if to_map < 0:
            continue
        crossing = _move(classquest.CROSS, member, quest, None, "", to_map=to_map)
        if not crossing_held(member.name, crossing, crossings):
            retry.add(qid)
    return frozenset(retry)


def _held_objective_fields(member, qid: int, quest: classquest.Quest) -> tuple:
    """Eligible kill and item-drop fields for one incomplete held quest."""
    progress = member.quest_objectives.get(qid)
    item_progress = member.quest_item_objectives.get(qid, {})
    kills = dict(quest.kills)
    if progress:
        kills = {
            entry: count
            for entry, count in kills.items()
            if int(progress.get(entry, 0)) < count
        }
    # Item-only objectives have no creature counter. Keep only droppers for
    # item objectives whose own counters are still short; the aggregate quest
    # counter cannot distinguish which ingredient a shared collection quest
    # still needs.
    items = dict(quest.items)
    targets = set(kills) | {
        entry
        for item, entry in quest.drops
        if int(item_progress.get(item, 0)) < items.get(item, 0)
    }
    return classquest.within_level(
        member,
        tuple(s for s in classquest.solo_fields(quest) if s.entry in targets),
    )


# The module's verb for each move that is one quest row.
_QUEST_VERBS = {
    classquest.TAKE: "take",
    classquest.TURN_IN: "turnin",
    classquest.ABANDON: "abandon",
}


def step_for(member, move, cap, quest=None, hunt=True, item_form=True):
    """The guildcorps.Step that makes the move, or None when there is nothing
    to write: a walk-only hunt the quester already stands at.

    A hunt is the walk to the objective's spawn and then the module's
    `hunt-spawn` row for its creature (classhunt.command), the way a class
    hunt is: a bot left to its own grind strategy at the field never looted a
    quest drop (classhunt.py), and a quest that stalls for that reason would be
    recorded broken for no fault of its own. A quester already beside the spawn
    (classhunt.HUNT_NEAR) writes the hunt row alone. With `hunt` False (a
    worldserver without the verb, bridge._class_hunt_row) the hunt is the walk
    alone, as it was, and nothing within classquest.HUNT_REACH."""
    source = guildjobs.source_for(ACTION, member.name)
    walk = _walk_row(member, move, cap)
    if move.kind == classquest.HUNT:
        item_progress = member.quest_item_objectives.get(int(move.quest), {})
        row = (
            classhunt.command(
                quest,
                move.spot.entry,
                lambda item: item_progress.get(int(item), 0),
                item_form,
            )
            if (hunt and quest is not None)
            else ""
        )
        yards = _yards(member, move.spot)
        if not row and yards <= classquest.HUNT_REACH:
            return None
        rows = (guildcorps.Row("job", row, "", source),) if row else ()
        if row and yards <= QUESTER_HUNT_NEAR:
            walk = None
    elif move.kind == classquest.CROSS:
        rows = _move_rows(move, guildjobs.source_for(CROSS_ACTION, member.name))
    else:
        rows = _move_rows(move, source)
    goal = move.spot.name if move.spot is not None else member.name
    return guildcorps.Step(
        member.name,
        ACTION,
        int(move.quest),
        move.said,
        rows=rows,
        walk=walk,
        goal=goal,
        spot=move.spot if move.kind == classquest.HUNT else None,
    )


def _seller(member, carried, worn) -> guildjobs.Member:
    """The quester as the guild members' sale reads it (guildjobs.vendor_judge):
    its level, class, worn gear and bags, and no guild bank forecast, so a trade
    good no quest needs is sold (an empty `reserved`, not an unread one)."""
    return guildjobs.Member(
        name=member.name,
        guild="",
        role=guildjobs.RAIDER,
        level=int(member.level),
        class_id=int(member.class_id),
        race=int(member.race),
        online=bool(member.online),
        alive=bool(member.alive),
        carried=tuple(carried or ()),
        free_slots=member.free_slots,
        worn=worn,
        reserved=frozenset(),
    )


def _selling_lately(name, recent) -> bool:
    """A sale row of this quester's younger than SELL_COOLDOWN_MINUTES."""
    return any(
        r.name == name
        and r.action in (SELL_ACTION, SELL_WALK_ACTION)
        and int(r.age_minutes) < SELL_COOLDOWN_MINUTES
        for r in recent or ()
    )


def needs_sale(member, tried=()) -> bool:
    """Whether the quester's bags are read and at SELL_FLOOR or under, or the
    world just refused one of its takes for bag room (`bag_room_refused`),
    whatever its bags read (#1992)."""
    if bag_room_refused(member.name, tried):
        return True
    return member.free_slots is not None and int(member.free_slots) <= SELL_FLOOR


def sell_step(member, carried, worn, kept, cat: Catalogue, recent, cap, tried=()):
    """The guildcorps.Step that sends a quester with full bags to a vendor, or
    None: its bags have room or are unread, it is offline, dead or unplaced,
    its last sale is younger than SELL_COOLDOWN_MINUTES, the reservations are
    unread, or it carries nothing it may sell.

    `carried` is its guildjobs.Carried stacks, `worn` its gear.CharacterState
    (None unread: no weapon or armor short of outgrown is sold), `kept` the
    keep.py reservations, `recent` guildjobs.Recent rows of the questers' own
    sources. What it sells is guildjobs.vendor_stacks with every item a quest
    of the catalogue needs, hands over or uses protected. `tried` is its
    Attempt rows: a take refused for bag room sends it too (#1992)."""
    if not needs_sale(member, tried) or kept is None:
        return None
    if not member.online or not member.alive or not member.placed:
        return None
    if _selling_lately(member.name, recent):
        return None
    seller = _seller(member, carried, worn)
    stacks = guildjobs.vendor_stacks(
        seller, kept, guildjobs._protected_entries(cat.book)
    )
    if not stacks:
        return None
    source = guildjobs.source_for(SELL_ACTION, member.name)
    free = member.free_slots
    if bag_room_refused(member.name, tried):
        room = "was refused a quest for %s" % BAG_ROOM_REFUSAL
    else:
        room = "has %d free bag slot%s" % (int(free), "" if int(free) == 1 else "s")
    return guildcorps.Step(
        member.name,
        SELL_ACTION,
        len(stacks),
        "%s %s and walks to a vendor to sell %d stack(s) it has no use for, "
        "worth %dc" % (member.name, room, len(stacks), vendorsale.worth(stacks)),
        rows=tuple(
            guildcorps.Row("sell", "guid:%d" % int(c.guid), "", source) for c in stacks
        ),
        walk=guildcorps.Row(
            "buy",
            "walk-to-vendor any%s" % guildroute.errand_cap_word(cap),
            "",
            guildjobs.source_for(SELL_WALK_ACTION, member.name),
        ),
        sales=guildjobs.sale_notes(stacks),
    )


def _walk_row(member, move, cap):
    """The walk to the move's spawn, None for a move with no spot."""
    if move.spot is None:
        return None
    spot = guildjobs.Spot(
        OBJECT_KIND if isinstance(move.spot, ObjectSpawn) else "creature",
        int(move.spot.guid),
        int(move.spot.map_id),
        float(move.spot.x),
        float(move.spot.y),
        near=QUESTER_NPC_NEAR
        if move.kind in (classquest.TAKE, classquest.TURN_IN)
        else QUESTER_HUNT_NEAR,
    )
    return guildcorps.Row(
        "job",
        spot.command + guildroute.errand_cap_word(cap),
        "",
        guildjobs.source_for(WALK_ACTION, member.name),
    )


def _move_rows(move, source) -> tuple:
    """The rows of a take, a hand-in, a drop or a crossing; () for any other."""
    verb = _QUEST_VERBS.get(move.kind)
    if verb:
        return (
            guildcorps.Row("quest", "%s quest:%d" % (verb, move.quest), "", source),
        )
    if move.kind == classquest.CROSS:
        return (
            guildcorps.Row("job", classquest.cross_command(move.to_map), "", source),
        )
    return ()


def settled(member, tried):
    """The quester with what its rows did inside classquest.TAKE_SETTLE_MINUTES
    put into its log: the saved log trails the live game by up to a save
    (guildjobs.with_recent_takes), so a quest just taken is in the log, one
    just handed in is done and one just dropped is gone."""
    log_now = dict(member.quest_log)
    done = set(member.quests_done)
    for a in sorted(tried or (), key=lambda a: -a.age_minutes):
        if a.name != member.name or a.status not in _WENT:
            continue
        if a.age_minutes >= classquest.TAKE_SETTLE_MINUTES:
            continue
        found = re.match(r"^(take|turnin|abandon) quest:(\d+)", a.command)
        if not found:
            continue
        verb, qid = found.group(1), int(found.group(2))
        if verb == "take" and qid not in done:
            log_now.setdefault(qid, STATUS_INCOMPLETE)
        elif verb == "turnin":
            log_now.pop(qid, None)
            done.add(qid)
        else:
            log_now.pop(qid, None)
    if log_now == member.quest_log and done == set(member.quests_done):
        return member
    return replace(member, quest_log=log_now, quests_done=frozenset(done))


def plan(
    cat: Catalogue,
    member,
    clock,
    now,
    broken=frozenset(),
    tried=(),
    last_quest=0,
    crossings=(),
) -> Plan:
    """One quester's Plan for this pass. Offline, dead or unplaced, it is
    given no move, but the clock still reads its log (and counts no play).

    `crossings` is the realm's recent crossing rows (guildjobs.Recent of
    guildjobs.CROSS_ACTIONS): a crossing is held while the member's last one is
    young (guildjobs.crossing_cooling) or the module refused that map for good
    (guildjobs.class_walls), as the class quest's and the level step's are.
    A move that walks waits while the quester's newest row was refused for a
    far walk wall (`walk_wall`)."""
    member = settled(member, tried)
    found = failures(cat, member, clock, now, tried, last_quest)
    if not member.online:
        return Plan(
            member.name, None, tuple(found), "%s is not in the world" % member.name
        )
    if not member.alive:
        return Plan(member.name, None, tuple(found), "%s is dead" % member.name)
    if not member.placed:
        return Plan(
            member.name, None, tuple(found), "%s has no fresh position" % member.name
        )
    move, why, never_held = next_move(cat, member, broken, found, tried, crossings)
    if move is not None and move.kind == classquest.CROSS:
        held = crossing_held(member.name, move, crossings)
        if held:
            move, why = None, held
    boat = None
    if move is not None and move.spot is not None:
        # A spot across the island's shore is reached by the boat, or held with
        # a named reason (#2194), as a class quest's is (#2182).
        island = guildjobs.island_boat_step(
            member,
            move,
            move.spot,
            crossings,
            ACTION,
            CROSS_ACTION,
            guildjobs.crossing_cooling,
        )
        if island is not None:
            boat, _said, note = island
            if boat is None:
                move, why = None, note or "%s waits on its last crossing" % member.name
    if boat is None and move is not None and move.spot is not None:
        # A drop does not walk. Only a far walk waits out the far walk
        # ceiling and budget, but another verb's hold is on the character, so
        # a near walk waits it out too (#1295: a 170-yard hunt walk was refused
        # as held every pass, about every two minutes). A walk refused as across
        # the water waits too, at any distance (#2194).
        wall, wait = walk_wall(member.name, tried)
        far = _yards(member, move.spot) > guildroute.TRAINER_WALK_YARDS
        if wall and (far or wall in NEAR_WALLS):
            move, why = (
                None,
                "%s waits %d more minute%s to walk: %s"
                % (
                    member.name,
                    wait,
                    "" if wait == 1 else "s",
                    wall,
                ),
            )
    return Plan(
        member.name,
        move,
        tuple(found) + tuple(never_held),
        move.said if move else why,
        boat,
    )


def crossing_held(name, move, crossings) -> str:
    """Why the quester's crossing `move` is not asked this pass, "" when it is:
    the module refused that map for good inside classquest.CROSS_WALL_MINUTES
    (guildjobs.class_walls), or the member's last crossing row is still young
    (guildjobs.crossing_cooling)."""
    continent = classquest.CONTINENTS.get(int(move.to_map), "map %d" % move.to_map)
    wall = guildjobs.class_walls(name, crossings).get(int(move.to_map))
    if wall:
        return "%s would cross to %s, and the world refused it: %s" % (
            name,
            continent,
            wall,
        )
    if guildjobs.crossing_cooling(name, crossings):
        return "%s waits on its last crossing before it crosses to %s" % (
            name,
            continent,
        )
    return ""
