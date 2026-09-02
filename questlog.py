"""Pure builder for the Family tab's quest logs: what each of the five is on.

WHY THIS EXISTS. Every other surface says where the family IS. None of them
says what the family is DOING, and the two defects that most shape how a play
session goes are both invisible for exactly that reason:

  mod-overseer#73 - a quest log at the client's hard cap of 25. Measured on
  the leader on 2026-08-29 at 24 of 25 with one quest complete; measured again
  while this module was written it had moved to Bork, at 22 of 25 with one
  complete. A character whose log is full cannot accept a quest, and a
  character that CANNOT accept quests looks exactly like one that has chosen
  not to. That is why it hid: nothing counted the slots.

  mod-overseer#28 - five characters, five different quest logs, so the same
  kill pays only whoever happens to be holding the quest. Live while writing
  this: 41 distinct quests held across the family, 26 of them by exactly ONE
  member, and not a single one held by all five. Turn-ins had spread to
  Grug 50, Bork 35, Og 35, Ugga 22, Grog 18.

Both are arithmetic over rows anybody could have run at any point in the last
month. Nobody did, because there was nowhere for the answer to go. This module
is that arithmetic, and the Family tab is where it goes - five logs side by
side, which is the only arrangement in which "only one of them holds it" is a
thing you can see rather than a thing you have to work out.

Same seam rule as map_core, panel, family and armory (infra#2597): the HTTP
adapter fetches rows and does nothing else. Which rows count as being IN the
log, what a slot count means, whether a quest is dead weight and who else is
carrying it are all judgements, so they live here where the stdlib suite can
reach them without a database.

WHY THIS IS A NEW MODULE AND NOT questbook.py. questbook answers "who is
behind and what could be handed to them", for the council to read out loud:
it needs quest_template_addon, prerequisite chains, class and race masks, and
it deliberately says nothing about progress. This answers "what is in the log
right now and how far along is it", for a person looking at a phone. They read
the same two tables and share nothing else; folding them together would give
one module two audiences and two reasons to change.
"""
from __future__ import annotations

import bonds
import family
from panel import _CLASS_NAMES

# character_queststatus.status, spelled as the core spells it (QuestStatus in
# QuestDef.h): 0 NONE, 1 COMPLETE, 2 UNAVAILABLE, 3 INCOMPLETE, 4 AVAILABLE,
# 5 FAILED, 6 REWARDED.
COMPLETE = 1
INCOMPLETE = 3
FAILED = 5

# WHAT ACTUALLY OCCUPIES A LOG SLOT, and the one thing here that would be a
# guess if it had not been measured. The obvious reading - "every row in
# character_queststatus is in the log" - is wrong, and provably so: the five
# carry 30, 37, 22, 30 and 25 rows each while the client's log holds 25.
# Three of those are over the cap, so the plain row count cannot be the log.
# Filtering to these three statuses gives 9, 22, 4, 16 and 14, which fit. The
# rows dropped are status NONE - the core remembering progress on a quest that
# is no longer being carried.
#
# FAILED IS KEPT, deliberately. A failed quest stays in the log holding its
# slot until somebody abandons or retries it, which is exactly the dead weight
# #73 is about; dropping it here would hide the thing this view exists to
# show. bridge.py's quest reads filter `status IN (1, 3)` instead, and are
# right to: a failed quest is nothing a character can be AIMED at. Different
# question, so a deliberately different set - and see infra#3106 for what
# happens when the status filter is left off altogether.
IN_LOG = (COMPLETE, INCOMPLETE, FAILED)

# The 3.3.5a client's hard cap. MAX_QUEST_LOG_SIZE in the core; a character at
# this number silently refuses every further accept.
LOG_SLOTS = 25

# How near the cap counts as full. NOT the cap itself: at 25 the damage is
# already done and the quest drive has already been refusing accepts for a
# while. Three slots is about one quest chain, so a log inside this is one
# hub's worth of quests away from being stuck - which is early enough for the
# number to be a warning rather than a post-mortem.
FULL_WITHIN = 3

# Objective slots, as the columns are laid out: four npc-or-gameobject and six
# item. The asymmetry is the game's, not a typo.
NPC_SLOTS = 4
ITEM_SLOTS = 6

# How far above a quest's level a character has to be for the quest to read as
# dead weight. A judgement, and it lives here with a test on it rather than
# inside a render function. Eight is what separates #73's evidence - two level
# 7 quests in a level 20 log - from ordinary play, where the family runs
# quests two to five levels under themselves all day and flagging those would
# make the marker meaningless.
OUTLEVEL_GAP = 8

# The words a quest's status renders as. Named here so the page and the tests
# agree on the vocabulary, the same way family.py owns DEAD/HURT/OK/GONE.
READY = "ready"        # complete, and the walk to the questgiver is all that is left
ACTIVE = "active"      # in progress
STUCK = "failed"       # failed, still holding its slot

_STATUS_WORDS = {COMPLETE: READY, INCOMPLETE: ACTIVE, FAILED: STUCK}

# Sort buckets, in the order a person wants them: what can be handed in now,
# then what is being worked on, then what has never been touched, then what
# has failed. A log read top to bottom is then a to-do list, and the dead
# weight sinks to the bottom where it reads as dead weight.
_BUCKET_READY, _BUCKET_STARTED, _BUCKET_UNTOUCHED, _BUCKET_FAILED = 0, 1, 2, 3


def _target(entry) -> tuple[str, int] | None:
    """RequiredNpcOrGo -> which table names it, and under which entry.

    NEGATIVE MEANS GAMEOBJECT, and the id is the absolute value. Reading the
    sign as a creature entry looks up -1735 in creature_template, misses, and
    renders "them" over a perfectly nameable chest.
    """
    entry = int(entry or 0)
    if entry > 0:
        return ("creatures", entry)
    if entry < 0:
        return ("gameobjects", -entry)
    return None


def objective_entries(rows: list[dict]) -> dict:
    """Every creature, gameobject and item id these quest rows name.

    The adapter needs this to look the names up, and the column spellings are
    already in this module - so it is answered here rather than making
    map_server.py know that RequiredNpcOrGo can be negative. Returns sorted
    lists so the SQL that follows is stable between polls and its parameters
    are reproducible in a test.
    """
    found: dict[str, set] = {"creatures": set(), "gameobjects": set(), "items": set()}
    for row in rows:
        for i in range(1, NPC_SLOTS + 1):
            target = _target(row.get("RequiredNpcOrGo%d" % i))
            if target is not None:
                found[target[0]].add(target[1])
        for i in range(1, ITEM_SLOTS + 1):
            entry = int(row.get("RequiredItemId%d" % i) or 0)
            if entry > 0:
                found["items"].add(entry)
    return {kind: sorted(ids) for kind, ids in found.items()}


def _named(names: dict, kind: str, entry: int, fallback: str) -> str:
    """The row's name, or a fallback that still says WHICH thing it is.

    A missing name is a custom or removed entry, not a reason to drop the
    objective: "8 of #1735" is worse than "8 of Riverpaw Scout" and far better
    than pretending the objective is not there.
    """
    got = (names.get(kind) or {}).get(entry)
    return got if got else "%s #%d" % (fallback, entry)


def _objectives(row: dict, names: dict) -> list[dict]:
    """One quest row plus its template into the countable things left to do.

    Empty is a real answer, not a failure: plenty of quests are "go and speak
    to somebody", and there is no honest number to put on those.
    """
    out = []
    for i in range(1, NPC_SLOTS + 1):
        need = int(row.get("RequiredNpcOrGoCount%d" % i) or 0)
        if not need:
            continue
        target = _target(row.get("RequiredNpcOrGo%d" % i))
        # ObjectiveText is the quest's own wording for this objective and it
        # beats the creature's name whenever it is set - it is what the client
        # itself prints, and it is written for the case where the name alone
        # would be wrong ("Defias Bandits slain" over four different mobs).
        text = (row.get("ObjectiveText%d" % i) or "").strip()
        if text:
            what = text
        elif target is None:
            what = "them"
        else:
            what = _named(names, target[0], target[1],
                          "creature" if target[0] == "creatures" else "object")
        out.append(_objective(what, row.get("mobcount%d" % i), need))
    for i in range(1, ITEM_SLOTS + 1):
        need = int(row.get("RequiredItemCount%d" % i) or 0)
        if not need:
            continue
        entry = int(row.get("RequiredItemId%d" % i) or 0)
        what = _named(names, "items", entry, "item") if entry else "it"
        out.append(_objective(what, row.get("itemcount%d" % i), need))
    kills = int(row.get("RequiredPlayerKills") or 0)
    if kills:
        out.append(_objective("enemy players", row.get("playercount"), kills))
    return out


def _objective(what: str, have, need: int) -> dict:
    # Clamped at the target. The core keeps counting past it on some quests,
    # and "12 / 10" on a card reads as a bug in the page rather than a quirk
    # of the row - while the honest thing to say is that it is done.
    have = min(int(have or 0), need)
    return {"what": what, "have": have, "need": need, "done": have >= need}


def _progress_pct(objectives: list[dict]) -> int | None:
    """How far along, over every objective at once, or None if nothing counts.

    None rather than 0 on purpose. A quest with no countable objective is not
    a quest at zero percent, and drawing an empty bar under one is the page
    inventing a fact about it.
    """
    need = sum(o["need"] for o in objectives)
    if not need:
        return None
    return round(100 * sum(o["have"] for o in objectives) / need)


def _bucket(status: int, started: bool) -> int:
    if status == COMPLETE:
        return _BUCKET_READY
    if status == FAILED:
        return _BUCKET_FAILED
    return _BUCKET_STARTED if started else _BUCKET_UNTOUCHED


def _quest(row: dict, level: int, names: dict, holders: dict) -> dict:
    quest_id = int(row["quest"])
    status = int(row["status"])
    objectives = _objectives(row, names)
    started = any(o["have"] > 0 for o in objectives)
    quest_level = int(row.get("QuestLevel") or 0)
    held_by = holders.get(quest_id, ())
    return {
        "id": quest_id,
        # LogTitle is what the client puts in the log; a blank one is a broken
        # template row, and the id is still enough to look it up.
        "title": row.get("LogTitle") or "quest #%d" % quest_id,
        "level": quest_level,
        "status": _STATUS_WORDS.get(status, ACTIVE),
        # Sorted on, not drawn: the page reads `status` for its words. Sent
        # rather than recomputed in the browser so the order five cards come
        # out in is decided once, here, where a test can pin it.
        "bucket": _bucket(status, started),
        "ready": status == COMPLETE,
        "failed": status == FAILED,
        "started": started,
        "objectives": objectives,
        "progress_pct": _progress_pct(objectives),
        # WHO ELSE IS CARRYING IT. The whole of mod-overseer#28 in one field:
        # a quest with one name against it is a fight that pays one character.
        "held_by": list(held_by),
        "alone": len(held_by) <= 1,
        # A quest level of 0 is a template that never set one (escort and
        # class quests do this), and subtracting from it would flag every one
        # of them as ancient.
        "outleveled": bool(quest_level) and level - quest_level >= OUTLEVEL_GAP,
    }


def _sort_key(quest: dict) -> tuple:
    # Level DESCENDING inside each bucket: the newest work is what a person is
    # looking for, and it puts the stragglers from ten levels ago at the foot
    # of the list where their own marker can be read against them.
    return (quest["bucket"], -quest["level"], quest["id"])


def _member(name: str, char_row: dict | None, rows: list[dict], names: dict,
            holders: dict, turned_in: int) -> dict:
    bond = bonds.FAMILY[name]
    if char_row is None:
        # No `characters` row at all. Like the Armory and unlike the Family
        # tab there is no freshness window here: a quest log is SAVED state,
        # so a logged-out character still has one and still gets a column.
        return {
            "name": name,
            "role": bond.role,
            "class": bond.char_class.title(),
            "present": False,
            "quests": [],
        }
    level = int(char_row["level"])
    quests = sorted((_quest(r, level, names, holders) for r in rows), key=_sort_key)
    used = len(quests)
    free = max(0, LOG_SLOTS - used)
    return {
        "name": char_row["name"],
        "role": bond.role,
        "present": True,
        "level": level,
        "class": _CLASS_NAMES.get(int(char_row["class"]),
                                 "class %s" % char_row["class"]),
        "online": bool(char_row.get("online")),
        # THE #73 NUMBERS. used/slots is the whole defect, and it is one
        # subtraction that nothing on any surface was doing.
        "used": used,
        "slots": LOG_SLOTS,
        "free": free,
        "full": free <= FULL_WITHIN,
        "ready": sum(1 for q in quests if q["ready"]),
        "failed": sum(1 for q in quests if q["failed"]),
        "outleveled": sum(1 for q in quests if q["outleveled"]),
        # THE #28 NUMBER, per character: how much of this log nobody else is
        # helping with. Every one of these is a fight that pays one of them.
        "alone": sum(1 for q in quests if q["alone"]),
        "turned_in": turned_in,
        "quests": quests,
    }


def _holders(rows: list[dict]) -> dict:
    """quest id -> which family members hold it, in roster order.

    Roster order rather than alphabetical, because the family is already
    ordered - bonds.speaking_order decides who comes first everywhere else on
    this page, and a second ordering would be a second opinion about the same
    five people.
    """
    order = {name: i for i, name in enumerate(family.roster())}
    found: dict[int, set] = {}
    for row in rows:
        found.setdefault(int(row["quest"]), set()).add(row["name"])
    return {quest: sorted(names, key=lambda n: order.get(n, len(order)))
            for quest, names in found.items()}


def _turn_in_spread(members: list[dict]) -> dict | None:
    """The turn-in counts, furthest apart first, or None if nobody is there.

    THIS IS THE EVIDENCE FOR #28, and it is the number the issue was opened
    with: Og 17, Grug 13, Bork 13, Ugga 3, Grog 3, from five characters who
    stand in the same fight. A gap in this is not five characters playing
    differently - it is five quest logs, and the log is the thing this view
    puts on screen beside it.
    """
    present = [m for m in members if m["present"]]
    if not present:
        return None
    most = max(present, key=lambda m: m["turned_in"])
    least = min(present, key=lambda m: m["turned_in"])
    return {
        "most": most["name"],
        "most_count": most["turned_in"],
        "least": least["name"],
        "least_count": least["turned_in"],
        "gap": most["turned_in"] - least["turned_in"],
    }


def build_questlog(char_rows: list[dict], quest_rows: list[dict],
                   rewarded_rows: list[dict], names: dict) -> dict:
    """Five quest logs, side by side and in roster order.

    All four inputs arrive keyed by character name or entry id and unfiltered;
    splitting them per member is this module's job so the adapter stays a
    handful of queries and no logic. A member with no rows still gets a
    column, for the same reason the Family tab keeps a card for somebody who
    logged out: a view that quietly drops a person is how that person stops
    being noticed.

    `names` is {"creatures": {entry: name}, "gameobjects": {...},
    "items": {...}} - whatever the adapter could look up for the ids
    objective_entries() asked for. A miss is survivable everywhere.
    """
    chars = {r["name"]: r for r in char_rows}
    turned_in = {r["name"]: int(r["turned_in"]) for r in rewarded_rows}
    by_member: dict[str, list] = {}
    for row in quest_rows:
        by_member.setdefault(row["name"], []).append(row)
    holders = _holders(quest_rows)
    members = [
        _member(name, chars.get(name), by_member.get(name, []), names, holders,
                turned_in.get(name, 0))
        for name in family.roster()
    ]
    alone = sum(1 for who in holders.values() if len(who) <= 1)
    everyone = sum(1 for who in holders.values() if len(who) >= len(members))
    return {
        "members": members,
        "slots": LOG_SLOTS,
        "expected": len(members),
        # Distinct quests, not rows: five characters holding the same quest is
        # ONE piece of work the family is doing, and counting it five times is
        # what makes a badly-shared log look busy.
        "held": len(holders),
        "alone": alone,
        "shared": len(holders) - alone,
        "everyone": everyone,
        "turn_in_spread": _turn_in_spread(members),
    }
