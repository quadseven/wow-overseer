"""Where each worn item came from, for the character sheet's tooltip (#371).

The character sheet on the Watch wall shows what a member wears. This says,
per worn item, how the member got it: a quest reward, a drop, a purchase, a
craft or a hand-over from another member, with the date. Every word is built
here, so the suite can reach it; the page prints the line it is given.

ONLY WHAT THE RECORD HOLDS. Nothing here guesses at a source. The sources:

  overseer_event item_loot    a loot or a roll won, with the source and place
  overseer_event item_given   a trade, a letter or an overseer give
  overseer_event quest_reward a turn-in, matched to the item by quest_template
  overseer_event craft        a craft, matched to the item by the craft book
  overseer_event item_equip   the first time the record saw the item worn
  overseer_command buy        a vendor purchase this service asked for
  overseer_command auction    an auction purchase this service asked for

item_loot and item_given are written for rare and better items only, so a
green piece a member looted says "origin not recorded" and, when the equip
record has it, where it was first worn. That is the honest reading, and the
gap is a recording gap, not something to fill in here.

WHICH SOURCE WINS. A loot story joined by the item's own guid is exact and
wins outright. Otherwise the candidates for the same item entry (quest
rewards, purchases, crafts) are timed against the item's first equip: the
latest one at or before it (with a short grace for a slow save) is the
answer. With no equip on record, the latest candidate is.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import lootstory

QUEST_REWARD = "quest_reward"
CRAFT = "craft"
BUY = "buy"
AUCTION = "auction"
BOUGHT = "bought"

# An equip is written on the module's next gear scan, which can land a little
# after the purchase, turn-in or craft that put the item in the bags. A source
# up to this long after the first equip still counts as before it.
GRACE = timedelta(minutes=5)

NOT_RECORDED = "Origin not recorded"


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _day(t) -> str:
    """A date as the other provenance lines write it: 12 September 2026."""
    if not isinstance(t, datetime):
        return ""
    return "%d %s" % (t.day, t.strftime("%B %Y"))


def _with_date(text: str, t) -> str:
    day = _day(t)
    return "%s, %s" % (text, day) if day else text


def craft_items(craftbook: dict) -> dict[int, int]:
    """craft spell id -> the item entry it makes, from the committed craft book.

    The book is skill -> spell -> [name, ..., created item entry]; a spell
    that makes no item (a First Aid rank, an enchant) carries 0 and is left
    out.
    """
    out: dict[int, int] = {}
    for spells in (craftbook or {}).values():
        if not isinstance(spells, dict):
            continue
        for spell, row in spells.items():
            if isinstance(row, list) and row:
                made = _int(row[-1])
                if made:
                    out[_int(spell)] = made
    return out


def _parse(result) -> dict:
    if isinstance(result, dict):
        return result
    try:
        parsed = json.loads(result or "")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _purchases(command_rows: list[dict]) -> dict[int, list[tuple]]:
    """item entry -> [(time, line)] for every purchase that read back as bought.

    The module writes its result as JSON: a vendor buy names the item and the
    vendor, an auction buy names the item. Anything else (a refusal, a bid,
    a row still queued) is not a purchase.
    """
    out: dict[int, list[tuple]] = {}
    for row in command_rows:
        result = _parse(row.get("result"))
        if result.get("outcome") != BOUGHT:
            continue
        item = result.get("item") if isinstance(result.get("item"), dict) else {}
        entry = _int(item.get("entry"))
        if not entry:
            continue
        if row.get("kind") == AUCTION:
            text = "Bought at auction"
        else:
            vendor = (
                result.get("vendor") if isinstance(result.get("vendor"), dict) else {}
            )
            name = vendor.get("name") or ""
            text = "Bought from " + name if name else "Bought from a vendor"
        at = row.get("updated_at") or row.get("created_at")
        out.setdefault(entry, []).append((at, text))
    return out


def _quests(event_rows: list[dict], who: str, quest_rewards: dict) -> dict:
    """item entry -> [(time, line)] for every turn-in whose rewards hold it."""
    out: dict[int, list[tuple]] = {}
    for row in event_rows:
        if row.get("kind") != QUEST_REWARD or row.get("character_name") != who:
            continue
        reward = quest_rewards.get(_int(row.get("subject_id"))) or {}
        entries = {_int(e) for e, _count in reward.get("items", [])}
        entries |= {_int(e) for e in reward.get("choices", [])}
        title = row.get("subject_name") or "quest %d" % _int(row.get("subject_id"))
        for entry in entries - {0}:
            out.setdefault(entry, []).append(
                (row.get("first_seen"), "Quest reward: " + title)
            )
    return out


def _crafts(event_rows: list[dict], who: str, makes: dict[int, int]) -> dict:
    """item entry -> [(time, line)] for every craft of it by this member."""
    out: dict[int, list[tuple]] = {}
    for row in event_rows:
        if row.get("kind") != CRAFT or row.get("character_name") != who:
            continue
        entry = makes.get(_int(row.get("subject_id")))
        if entry:
            out.setdefault(entry, []).append((row.get("first_seen"), "Crafted"))
    return out


def _loot_line(row: dict, zones: dict) -> str:
    via = row.get("via") or ""
    where = lootstory.place(row, zones)
    source = row.get("source") or ""
    if via in (lootstory.VIA_NEED, lootstory.VIA_GREED):
        text = "Won on a %s roll" % via
        if source:
            text += " for " + source
    elif via == lootstory.VIA_COUNCIL:
        text = "Awarded by the loot council"
    else:
        text = "Dropped by " + source if source else "Dropped"
    if where:
        text += " in " + where
    return text


_GIVEN_HOW = {
    lootstory.VIA_TRADE: " by trade",
    lootstory.VIA_MAIL: " by mail",
    lootstory.VIA_GIVE: " by overseer command",
    lootstory.VIA_COUNCIL: " on the loot council's word",
}


def _from_story(story: dict, who: str, zones: dict) -> tuple | None:
    """(time, line) for how `who` came to hold the item in this story."""
    steps = story["steps"]
    for row in reversed(steps):
        if row.get("kind") == lootstory.ITEM_GIVEN and row.get("counterpart") == who:
            giver = row.get("character_name") or "another member"
            how = _GIVEN_HOW.get(row.get("via") or "", "")
            return row.get("first_seen"), "Handed down from %s%s" % (giver, how)
    for row in steps:
        if row.get("kind") == lootstory.ITEM_LOOT and row.get("character_name") == who:
            return row.get("first_seen"), _loot_line(row, zones)
    return None


def _story_for(stories: list[dict], who: str, entry: int, guid: int) -> dict | None:
    """The loot story for this worn item: by its guid, or else the newest
    guid-less story of the same entry that `who` was part of."""
    if guid:
        for story in stories:
            if any(_int(r.get("item_guid")) == guid for r in story["steps"]):
                return story
    # A realm whose event rows predate the guid column: the same entry, in a
    # story that carries no guid at all, so a story about another copy of the
    # item is never borrowed.
    for story in reversed(stories):
        if story["entry"] != entry:
            continue
        if any(_int(r.get("item_guid")) for r in story["steps"]):
            continue
        if any(
            r.get("character_name") == who or r.get("counterpart") == who
            for r in story["steps"]
        ):
            return story
    return None


def _pick(candidates: list[tuple], first_worn) -> tuple | None:
    """The latest candidate at or before the first equip, or the latest one
    when there is no equip on record. Candidates with no time are dropped."""
    timed = [c for c in candidates if isinstance(c[0], datetime)]
    if isinstance(first_worn, datetime):
        timed = [c for c in timed if c[0] <= first_worn + GRACE]
    if not timed:
        return None
    return max(timed, key=lambda c: c[0])


def origins(
    who: str,
    worn: list[dict],
    event_rows: list[dict],
    command_rows: list[dict],
    quest_rewards: dict,
    craftbook: dict,
    zones: dict,
) -> dict[str, dict]:
    """str(item entry) -> {"known", "line"} for every item `who` wears.

    `worn` is {"entry", "item_guid"} per worn item. `event_rows` are this
    member's overseer_event rows of the kinds above, plus item_given rows
    that name them as the receiver. `command_rows` are this member's buy and
    auction rows with their results. `quest_rewards` is
    achievements.quest_rewards_from_rows over the quests in `event_rows`.
    `zones` is recap.zone_names.
    """
    stories = lootstory.stories(
        [r for r in event_rows if r.get("kind") in lootstory.KINDS]
    )
    firsts: dict[int, dict] = {}
    for row in event_rows:
        if row.get("kind") != lootstory.ITEM_EQUIP or row.get("character_name") != who:
            continue
        entry = _int(row.get("subject_id"))
        seen = firsts.get(entry)
        if seen is None or (row.get("first_seen") or datetime.max) < (
            seen.get("first_seen") or datetime.max
        ):
            firsts[entry] = row
    bought = _purchases(command_rows)
    quests = _quests(event_rows, who, quest_rewards)
    crafts = _crafts(event_rows, who, craft_items(craftbook))
    out: dict[str, dict] = {}
    for item in worn:
        entry = _int(item.get("entry"))
        if not entry or str(entry) in out:
            continue
        first = firsts.get(entry)
        first_worn = first.get("first_seen") if first else None
        story = _story_for(stories, who, entry, _int(item.get("item_guid")))
        found = _from_story(story, who, zones) if story else None
        if found is None:
            found = _pick(
                bought.get(entry, []) + quests.get(entry, []) + crafts.get(entry, []),
                first_worn,
            )
        if found is not None:
            out[str(entry)] = {"known": True, "line": _with_date(found[1], found[0])}
            continue
        line = NOT_RECORDED
        if first:
            where = lootstory.place(first, zones)
            worn_at = "first worn in " + where if where else "first worn"
            line += "; " + _with_date(worn_at, first_worn)
        out[str(entry)] = {"known": False, "line": line}
    return out
