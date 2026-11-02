"""The story of every notable item the families' guilds pick up (mod-overseer#567).

The module writes three event kinds about one item instance, keyed by its
guid: `item_loot` (somebody in a family's guild looted it, or won it on a
roll), `item_given` (a module give, trade or mail moved it), and `item_equip`
(somebody put it on). This module joins them into one sentence per item and
hands the Chronicle a list of them, newest first.

THE ORDER OF EVENTS THE DATABASE CANNOT GIVE. `first_seen` is not when a thing
happened: it is when the module's five-second flush wrote it, and one flush is
one INSERT, so every row of a flush holds the same second. Nor does `id` break
the tie, because the module's queue is a map keyed by character and then kind,
which writes `item_equip` ahead of `item_loot`. Within one second the steps are
told in the order an item normally moves: looted, handed on, worn (KINDS). An
item cannot be worn before it is got, because the guid on an equip row exists
only once the loot or the roll has stored the item. A character who wears an
item and trades it inside one flush is told the other way round; a worn item
has to come off first, so that second is rare, and the record cannot tell.

EVERY WORD A READER SEES IS WRITTEN HERE, not in the page. The page draws the
item name in its quality colour, the reader's clock, and the sentence it is
given; "looted", "traded" and "mailed" are judgements about what happened and
belong where the test suite can see them.

HOW A HAND-OVER MOVED IS PART OF THE STORY. A trade face to face and a letter
from a mailbox are things a player could do. A module `give` moves an item
across any distance with no range check, so the sentence says it was done by
overseer command rather than letting it read like a trade.

JOINING. By item guid wherever the row carries one. A row without one (a
row written before the module recorded guids, or any row from a database
that has not applied the migration yet) joins the newest story for the same
item entry whose current holder is the character on the row, and otherwise
starts a story of its own. That is a guess made only where the guid is
missing, and it can only ever attach a step to the character who was last
known to hold that item.
"""

from __future__ import annotations

from datetime import datetime

import achievements
import recap
from armory import QUALITY_NAMES, UNKNOWN_QUALITY

ITEM_LOOT = "item_loot"
ITEM_GIVEN = "item_given"
ITEM_EQUIP = "item_equip"
# In the order an item moves, which breaks a tie inside one flush (see above).
KINDS = (ITEM_LOOT, ITEM_GIVEN, ITEM_EQUIP)

# ItemTemplate::Quality: 3 rare, 4 epic, 5 legendary. The module writes loot
# and hand-overs only from here up; equips below it are roster gear changes,
# which are the Armory's business.
NOTABLE_QUALITY = 3

# How many stories the page is handed. The event table keeps a fortnight.
STORY_LIMIT = 150

VIA_LOOT = "loot"
VIA_NEED = "need"
VIA_GREED = "greed"
VIA_GIVE = "give"
VIA_TRADE = "trade"
VIA_MAIL = "mail"
# Handed over by a raid's master looter on the loot council's word (#194).
VIA_COUNCIL = "council"

EMPTY = "No rare, epic or legendary item has been looted, handed over or equipped yet."
BASIS = (
    "Rare, epic and legendary items that members of the families' guilds looted, "
    "handed over or put on, newest first, from the last fortnight of the event record. "
    "A hand-over by overseer command is named as one, because it needs no trade range."
)


def _iso(t) -> str | None:
    if isinstance(t, datetime):
        return t.isoformat()
    return t or None


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def place(row: dict, zones: dict) -> str:
    """Where a row happened, or "" when the row carries no place at all.

    recap.place_name falls back to printing ids, which is right for a recap
    and wrong in the middle of a sentence, so a row with no map and no zone
    says nothing about where rather than "map 0".
    """
    map_id = _int(row.get("map"))
    zone_id = _int(row.get("zone"))
    if not map_id and not zone_id:
        return ""
    return recap.place_name(map_id, zone_id, achievements.MAP_NAMES, zones)


def _loot_clause(via: str, source: str, where: str, thing: str) -> str:
    """How the item was first got: looted, won on a roll, or awarded by the
    loot council (#194), from what and where."""
    if via in (VIA_NEED, VIA_GREED):
        text = "won %s on a %s roll" % (thing, via)
    elif via == VIA_COUNCIL:
        text = "was awarded " + thing
    else:
        text = "looted " + thing
    if source:
        text += " from " + source
    if where:
        text += " in " + where
    if via == VIA_COUNCIL:
        text += " by the loot council"
    return text


def clause(row: dict, zones: dict, thing: str) -> str:
    """One step of the story, with no subject. `thing` is what the step calls
    the item: its name the first time the sentence meets it, "it" after.

    The subject is added by `sentence`, which drops it when the same
    character did the step before.
    """
    kind = row.get("kind")
    via = row.get("via") or ""
    where = place(row, zones)
    source = row.get("source") or ""
    if kind == ITEM_LOOT:
        return _loot_clause(via, source, where, thing)
    if kind == ITEM_GIVEN:
        to = row.get("counterpart") or "somebody"
        if via == VIA_TRADE:
            text = "traded %s to %s" % (thing, to)
            if where:
                text += " in " + where
            return text
        if via == VIA_MAIL:
            text = "mailed %s to %s" % (thing, to)
            if where:
                text += " from " + where
            return text
        if via == VIA_GIVE:
            return "gave %s to %s by overseer command" % (thing, to)
        return "handed %s to %s" % (thing, to)
    if kind == ITEM_EQUIP:
        return "equipped " + thing
    return ""


def _in_a_row(clauses: list[str]) -> str:
    """ "A", "A and B", "A, B and C"."""
    if len(clauses) == 1:
        return clauses[0]
    return ", ".join(clauses[:-1]) + " and " + clauses[-1]


def sentence(steps: list[dict], zones: dict, item_name: str) -> str:
    """The whole story of one item, oldest step first, as one sentence that
    names the item once and calls it "it" after. A character's steps in a row
    share one subject; the next character's follow ", then"."""
    turns: list[tuple[str, list[str]]] = []
    thing = item_name
    for row in steps:
        text = clause(row, zones, thing)
        if not text:
            continue
        thing = "it"
        who = row.get("character_name") or "somebody"
        if turns and turns[-1][0] == who:
            turns[-1][1].append(text)
        else:
            turns.append((who, [text]))
    if not turns:
        return ""
    told = ("%s %s" % (who, _in_a_row(said)) for who, said in turns)
    return ", then ".join(told) + "."


def _holder(steps: list[dict]) -> str | None:
    """Who holds the item after these steps, as far as the record knows."""
    holder = None
    for row in steps:
        if row.get("kind") == ITEM_GIVEN and row.get("counterpart"):
            holder = row["counterpart"]
        else:
            holder = row.get("character_name")
    return holder


def _same_step(a: dict, b: dict) -> bool:
    """Two equips in a row by one character are one step in the story. The
    module writes one row per hour an item is worn and swapped, and a reader
    wants to know it went on, not how many hours it stayed there."""
    return (
        a.get("kind") == ITEM_EQUIP
        and b.get("kind") == ITEM_EQUIP
        and a.get("character_name") == b.get("character_name")
    )


def _find_story(row: dict, by_guid: dict, everything: list[dict]) -> dict | None:
    """The story this row belongs to, or None when it starts a new one.

    By guid when the row carries one. Without one, the newest story for the
    same entry whose current holder is this row's character.
    """
    guid = _int(row.get("item_guid"))
    if guid:
        return by_guid.get(guid)
    entry = _int(row.get("subject_id"))
    who = row.get("character_name")
    for candidate in reversed(everything):
        if candidate["entry"] == entry and _holder(candidate["steps"]) == who:
            return candidate
    return None


def _new_story(row: dict) -> dict:
    return {
        "entry": _int(row.get("subject_id")),
        "name": row.get("subject_name") or "",
        "quality": _int(row.get("subject_quality")),
        "guild": row.get("guild") or "",
        "steps": [],
    }


def _add_step(story: dict, row: dict) -> None:
    steps = story["steps"]
    if steps and _same_step(steps[-1], row):
        steps[-1] = dict(steps[-1], last_seen=row.get("last_seen"))
        return
    steps.append(row)
    if not story["guild"] and row.get("guild"):
        story["guild"] = row["guild"]


def stories(rows: list[dict]) -> list[dict]:
    """Group event rows into item stories, each a list of rows oldest first.

    Returns dicts with `entry`, `name`, `quality`, `guild`, and `steps`.
    """
    ordered = sorted(
        (r for r in rows if r.get("kind") in KINDS),
        key=lambda r: (
            r.get("first_seen") or datetime.min,
            KINDS.index(r["kind"]),
            _int(r.get("id")),
        ),
    )
    by_guid: dict[int, dict] = {}
    everything: list[dict] = []
    for row in ordered:
        story = _find_story(row, by_guid, everything)
        if story is None:
            story = _new_story(row)
            everything.append(story)
            guid = _int(row.get("item_guid"))
            if guid:
                by_guid[guid] = story
        _add_step(story, row)
    return everything


def _latest(story: dict):
    return max(
        (
            r.get("last_seen") or r.get("first_seen") or datetime.min
            for r in story["steps"]
        ),
        default=datetime.min,
    )


def wanted_entries(rows: list[dict]) -> list[int]:
    """The item entries the page will draw, for the item_template read."""
    return sorted(
        {_int(r.get("subject_id")) for r in rows if r.get("kind") in KINDS} - {0}
    )


def _council_for(story: dict, council: dict) -> dict | None:
    """The loot council's award for any item guid in this story, or None."""
    for row in story["steps"]:
        award = council.get(_int(row.get("item_guid")))
        if award:
            return award
    return None


def build_loot(
    rows: list[dict],
    zones: dict,
    items: dict | None = None,
    icons: dict | None = None,
    book=None,
    limit: int = STORY_LIMIT,
    council: dict | None = None,
) -> dict:
    """The payload /api/loot serves.

    `rows` are overseer_event rows of the three kinds, each optionally with a
    `guild` (the guild name of the character on the row). `council` is
    lootcouncil.by_item_guid over the loot council's rows: a story whose item
    the council handed out ends with why, when the council gave a reason (#194).
    `zones` is area id to zone name, recap.zone_names. `items`, `icons` and `book` are what
    achievements.item_payload draws an item from; without them an item still
    renders by the name the event row recorded.
    """
    items = items or {}
    icons = icons or {}
    out = []
    for story in stories(rows):
        if story["quality"] < NOTABLE_QUALITY:
            continue
        item = achievements.item_payload(story["entry"], items, icons, book)
        if story["entry"] not in items:
            # The world database did not answer for this entry, so the name
            # and quality the module recorded at the moment are the truth.
            item["name"] = story["name"] or item["name"]
            item["quality"] = story["quality"]
            item["quality_name"] = QUALITY_NAMES.get(story["quality"], UNKNOWN_QUALITY)
        line = sentence(story["steps"], zones, item["name"])
        if not line:
            continue
        award = _council_for(story, council or {})
        if award and award.get("reason"):
            line += " Loot council: %s" % award["reason"]
        latest = _latest(story)
        out.append(
            {
                "item": item,
                "guild": story["guild"],
                "line": line,
                "at": _iso(latest),
                "since": _iso(story["steps"][0].get("first_seen")),
                "_sort": latest,
            }
        )
    out.sort(key=lambda s: s["_sort"], reverse=True)
    for s in out:
        del s["_sort"]
    return {
        "stories": out[:limit],
        "more": max(0, len(out) - limit),
        "empty": EMPTY,
        "basis": BASIS,
    }
