"""Which dungeon is worth running next, and for whom (infra#3500).

THE QUESTION THIS ANSWERS is asked about a hundred times and the site could
not answer it once: "what page shows all dungeons and what upgrades they can
get at them". The Chronicle's loot board answers it for ONE map, the map the
family is standing in or the map a query string names, so choosing where to go
next meant opening that board twenty-odd times and holding the answers in your
head.

WHAT IT DOES NOT DO IS DECIDE. It ranks, it says what it ranked on, and it
reports a tie as a tie. The rule that a page renders and does not decide is
`test_recap_tab.ThePageDecidesNothing`, and this module keeps the other half of
it: every sentence a reader sees is written here, so a Python test can read it.

ONE DEFINITION OF "UPGRADE", AND IT IS NOT THIS MODULE'S. `recap.verdict`
already decides whether a drop beats what a character is wearing, and it
already handles inventory type, required level, allowable class, armour grade
and - since mod-overseer#411 - whether the character may hold the thing at all,
read from their own `character_skills` rows rather than guessed from a class
table. A second definition here would be a second answer to one question, free
to disagree with the loot board about the same drop on the same evening. So
this module owns the CROSS PRODUCT and the RANKING, and borrows the verdict.

THE COST, BECAUSE IT IS A CROSS PRODUCT. Twenty-odd dungeons times every boss
drop in each times five characters. The reads are batched the way the recap's
are: the catalogue, the encounters and the loot arrive as three whole-world
queries rather than one query per dungeon, and nothing in here goes back to the
database. The verdict itself is arithmetic over rows already in memory.
"""
from __future__ import annotations

import re

import recap

# The continents a character can stand on. Anything else is an instance, and
# an instance is placed by the entrance that leads into it.
CONTINENT_MAPS = (0, 1, 530, 571)

# Verdicts that mean this character would be better off after the run. The
# same two the loot board counts, and deliberately the same two: "would gain"
# has to mean one thing on both pages.
GAIN_VERDICTS = (recap.UPGRADE, recap.EMPTY)

# Which list a dungeon's row came from. Recorded per row rather than inferred
# from a missing level range, because "the access table says nothing about the
# levels" and "the access table has never heard of this place" are two
# different admissions and a reader acting on them would act differently.
ACCESS_TABLE = "access table"
SITE_LIST = "site list"

# A PARTY SIZE THE TABLE'S OWN COMMENT HAPPENS TO NAME, AND NOTHING MORE.
# `dungeon_access_template` spans classic through Wrath on this realm - 74
# distinct maps, raids among them - and it carries no player-count column at
# all. The only signal is inside `comment`, which is FREE TEXT a person wrote:
#
#     229  Blackrock Spire - Both Lower (LBRS) & Upper (UBRS) - 5/10man
#     409  Molten Core - 40man
#     544  Hellfire Citadel: Magtheridon's Lair - 25man
#
# THIS IS READ TO SHOW AND NEVER TO FILTER, and the two are not the same risk.
# A marker this misses is a chip that does not appear and a row that is exactly
# as useful as it was before. A FILTER built on the same match would silently
# drop a real dungeon the first time somebody edited a string - and it would
# have to, because several entries name no size whatsoever (Uldaman,
# Scholomance, Mana Tombs) and one names two at once. So no size is ever
# inferred from a missing marker, nothing is removed from the list on the
# strength of one, and the matched text is shown exactly as the table wrote it
# rather than tidied into a number this module would then be asserting.
#
# For the same reason the marker is not stripped out of the NAME when the
# comment is standing in as one: reading text to add a chip is additive and
# reversible, editing text to remove part of it is neither.
_PARTY_SIZE = re.compile(r"\b\d+(?:\s*/\s*\d+)*\s*man\b", re.IGNORECASE)


def party_size(comment: str | None) -> str:
    """The party size this row's comment names, verbatim, or "" for none.

    "" is "the comment does not say", which is NOT "five". A reader drawing
    that conclusion from a missing chip would be drawing it themselves, and
    the footer says so rather than letting the gap imply an answer.
    """
    found = _PARTY_SIZE.search(comment or "")
    return found.group(0).strip() if found else ""


def _dungeon_count(count: int) -> str:
    """"1 dungeon" or "7 dungeons".

    A HELPER FOR A REASON A ONE-LINE FORMAT DOES NOT HAVE. Every count on this
    page comes from a list the world handed over, so every one of them can be
    one: a degraded schema leaves a single readable map, and a roster is
    whatever bonds returns. "1 dungeons read" is the same class of mistake as
    the hardcoded "five" this module already refuses, and it appears the day
    something goes wrong, which is the day the page is being read closely.
    """
    return "1 dungeon" if count == 1 else "%d dungeons" % count


def _level_line(entry: dict, levels: list[int]) -> str:
    """The dungeon's level range against the family's, in one sentence.

    THE ZEROES ARE THE TRAP. `dungeon_access_template` carries a min_level and
    a max_level per map, and a row that has never been filled in carries 0 in
    both. Printed straight through that becomes "for levels 0 to 0", which is
    a confident statement about a dungeon nothing here knows the level of, and
    a reader would take it as "anybody can go".
    """
    low = int(entry.get("min_level") or 0)
    high = int(entry.get("max_level") or 0)
    if not levels:
        span = ""
    elif min(levels) == max(levels):
        span = "; the family is %d" % min(levels)
    else:
        span = "; the family is %d to %d" % (min(levels), max(levels))
    if not low and not high:
        return "the access table gives no level range for this one" + span
    if low and high:
        return "the access table asks for level %d to %d%s" % (low, high, span)
    if low:
        return "the access table asks for level %d and no maximum%s" % (low, span)
    return "the access table gives no minimum, and a maximum of %d%s" % (high, span)


def _under_minimum(entry: dict, members: list[dict]) -> list[str]:
    """Who is not high enough to zone in, by the access table's own minimum.

    Empty when the table gives no minimum, which is NOT the same as "everybody
    can go": it is "nothing here knows", and the level line says so rather
    than this list implying an answer.
    """
    low = int(entry.get("min_level") or 0)
    if not low:
        return []
    return [m["name"] for m in members if int(m.get("level") or 0) < low]


def _entry_line(blocked: list[str], members: list[dict]) -> str:
    """What the minimum level means for the characters being compared.

    COUNTED, NEVER THE WORD "FIVE". The roster is whatever bonds hands over,
    and the first version of this sentence said "not one of the five" over a
    family of three because five is what the roster happened to be the day it
    was written. Empty when the minimum means nothing, so the page prints
    nothing rather than an empty reassurance.
    """
    if not blocked:
        return ""
    if len(blocked) == len(members):
        # NAMED WHEN SOME ARE BLOCKED, COUNTED BY NOBODY WHEN ALL ARE. The
        # count was in this sentence and read "not one of the 1 is high
        # enough" on a roster of one. The number it was carrying is already on
        # the level line above and in the chip beside it, so dropping it costs
        # a reader nothing and it cannot be got wrong.
        return "nobody here is high enough to zone in yet"
    return "too low to zone in: " + ", ".join(blocked)


def _continent_of(map_id: int | None, entrances: dict) -> int | None:
    """The continent a map sits on, or the continent its entrance sits on.

    A character inside Wailing Caverns is on map 43, which is not a continent
    and tells a reader nothing about how far away they are. The entrance to
    map 43 stands on Kalimdor, and that IS the answer to "how far away".

    `entrances` is the committed entrances.json, generated by
    tools/gen_geometry.py from AreaTrigger.dbc joined to
    acore_world.areatrigger_teleport. It is the same join as reading those two
    tables live, done once against frozen client data, and it is what the live
    map already places instance dwellers with.
    """
    if map_id is None:
        return None
    map_id = int(map_id)
    if map_id in CONTINENT_MAPS:
        return map_id
    entrance = entrances.get(str(map_id))
    return int(entrance["map"]) if entrance else None


def _continent_name(continent: int | None, continents: dict) -> str:
    """zones.json's own name for a continent. "somewhere this page cannot
    place" rather than a map number, because a map number is not an answer to
    "how far is it"."""
    if continent is None:
        return "somewhere this page cannot place"
    region = continents.get(str(continent))
    return region["name"] if region else "map %d" % continent


def _where_line(continent: int | None, members: list[dict],
                continents: dict) -> str:
    """Whether this dungeon is on the ground the family is already standing on.

    THE CROSSING IS THE EXPENSIVE PART for this family, which is why this is on
    the card at all rather than left to the map. Counted per character, not
    assumed for the group: they are not always together.
    """
    name = _continent_name(continent, continents)
    if continent is None:
        return "this page cannot place its entrance, so it cannot say how far it is"
    here = [m for m in members if m.get("continent") == continent]
    if not members:
        return "its entrance is on %s" % name
    if len(here) == len(members):
        return "its entrance is on %s, where all %d of them are" % (name, len(members))
    if not here:
        return "its entrance is on %s, and not one of them is on that continent" % name
    return ("its entrance is on %s, where %d of the %d are"
            % (name, len(here), len(members)))


def _gain_line(count: int, best: int | None, name: str) -> str:
    """What this dungeon holds for one character, counted rather than judged.

    `best` is None when every gain is an empty slot, which has no delta to be
    best by: see _delta_note. The sentence says "pieces" and never "upgrades",
    because an empty slot is a piece that is all gain and not an upgrade over
    anything.
    """
    pieces = "1 piece" if count == 1 else "%d pieces" % count
    if best is None:
        where = "into an empty slot" if count == 1 else "into empty slots"
        return "%s for %s, %s" % (pieces, name, where)
    return "%s for %s, the best of them %d item levels" % (pieces, name, best)


def _drop_line(verdict: dict, boss: str) -> str:
    """One gain, in the verdict's own words, with the boss that drops it.

    `verdict["why"]` is recap.py's sentence and is not rewritten here. It
    already names the comparison it made, which is the half a reader has to be
    able to disagree with.
    """
    return "%s, from %s: %s" % (verdict["slot"], boss, verdict["why"])


def _dungeon_line(gainers: list[str], members: list[dict],
                  pieces: int) -> str:
    """The headline on a dungeon card. The count first, because the count is
    what a reader scans a list of twenty for.

    "NOTHING IN HERE BEATS WHAT THEY WEAR" AND "NOTHING IS LISTED IN HERE" ARE
    DIFFERENT ANSWERS, and the first version gave the first one for both. A
    dungeon whose bosses are all summoned rather than spawned comes back with
    no loot at all, and saying its drops lost a comparison that never ran is
    the page asserting something nothing here checked.
    """
    total = len(members)
    if not total:
        return "nothing here knows who the family are, so it cannot say"
    if not pieces:
        return ("the world database lists no boss loot for this one, so "
                "there was nothing to compare")
    if not gainers:
        return "nothing in here beats what is already worn"
    if len(gainers) == total:
        return "all %d would gain something: %s" % (total, ", ".join(gainers))
    return ("%d of the %d would gain something: %s"
            % (len(gainers), total, ", ".join(gainers)))


def _tie_line(name: str, peers: list[str]) -> str:
    """Who this dungeon is level with, said out loud.

    A RANKED LIST INVENTS AN ORDER WHERE THERE IS NONE, and that is the
    dishonest half of ranking: two dungeons that scored identically are
    printed one above the other, and the one on top reads as the better
    answer. Naming the tie is what stops the order being read as a finding.
    """
    others = [peer for peer in peers if peer != name]
    if not others:
        return ""
    if len(others) == 1:
        return "level with %s on both counts" % others[0]
    return "level with %s on both counts" % ", ".join(others)


def _delta_note(empties: int) -> str:
    """Why the item level total does not count the empty slots.

    AN EMPTY SLOT HAS NO DELTA. recap.verdict calls it all gain, and it is,
    but "all gain" is not a number that can be added to a number measured
    against something worn: counting the whole item level of a trinket into a
    slot nobody has filled would rank a dungeon full of trinkets above one
    with a real weapon in it. It counts toward who would gain and not toward
    by how much, and this says so on the card rather than in a footer nobody
    reaches.
    """
    if not empties:
        return ""
    if empties == 1:
        return ("1 of these goes into an empty slot, which is all gain and has "
                "no item level to measure it against, so it is counted here "
                "and not in the total")
    return ("%d of these go into empty slots, which are all gain and have no "
            "item level to measure them against, so they are counted here and "
            "not in the total" % empties)


def _chips(entry: dict, continent: int | None, members: list[dict],
           continents: dict, total: int, shut: bool) -> list[dict]:
    """The three or four words that have to survive being collapsed.

    THE LIST IS TWENTY ROWS LONG ON A PHONE, and a reader scanning it is not
    going to open every one. These are the facts from the sentences below,
    cut to chip length, and they are cut HERE: a page that trimmed
    "the access table asks for level 15 to 25" down to "15 to 25" would be
    writing the short version itself, and the two would drift the first time
    either was reworded.

    `tone` is a ROLE NAME and never a colour. The stylesheet decides what "no"
    looks like on each of the two grounds this page is drawn on.
    """
    out = []
    low = int(entry.get("min_level") or 0)
    high = int(entry.get("max_level") or 0)
    if low and high:
        out.append({"text": "levels %d to %d" % (low, high), "tone": ""})
    elif low:
        out.append({"text": "level %d and up" % low, "tone": ""})
    elif high:
        out.append({"text": "up to level %d" % high, "tone": ""})
    else:
        out.append({"text": "no level range", "tone": "unsure"})
    # NEXT TO THE LEVELS, because it answers the same question: can these five
    # do this at all. Drawn in the body tone and never in a warning one - a
    # 40man marker beside a family of five speaks for itself, and painting it
    # as a refusal would be this module deciding the thing it went out of its
    # way not to decide. No chip at all when the comment names nothing, which
    # is the honest shape of "the table does not say".
    if entry.get("party_size"):
        out.append({"text": entry["party_size"], "tone": ""})
    if continent is None:
        out.append({"text": "entrance not placed", "tone": "unsure"})
    else:
        here = len([m for m in members if m.get("continent") == continent])
        out.append({"text": _continent_name(continent, continents),
                    "tone": ("up" if members and here == len(members)
                             else "no" if not here else "")})
    if total:
        out.append({"text": "%d item levels" % total, "tone": "up"})
    if shut:
        out.append({"text": "too low to enter", "tone": "no"})
    return out


def _member_gains(drops: list[dict], member: dict) -> dict:
    """Every gain this dungeon holds for one character, and what they add to.

    ONE SLOT IS WORN ONCE, and that is the whole reason `total` is not a sum
    over `gains`. A dungeon that drops five chest pieces each beating what a
    character wears is five entries in the list and ONE chest they can put on,
    so summing the list would rank that dungeon five times better than it is.
    The total takes the best gain per slot and nothing else.
    """
    gains = []
    for drop, verdict, boss in drops:
        if verdict["verdict"] not in GAIN_VERDICTS:
            continue
        delta = verdict.get("gain")
        entry = dict(drop)
        entry.update(
            slot=verdict["slot"],
            boss=boss,
            worn=verdict.get("worn"),
            worn_ilvl=verdict.get("worn_ilvl"),
            delta=(int(delta) if delta is not None else None),
            line=_drop_line(verdict, boss),
            caveats=verdict.get("caveats") or [],
        )
        gains.append(entry)
    # Best first, and an empty slot last within its own tier: a gain with a
    # number on it is the one a reader can check.
    gains.sort(key=lambda g: (-(g["delta"] or 0), g["slot"], g["name"]))
    best_by_slot: dict = {}
    for gain in gains:
        if gain["delta"] is None:
            continue
        slot = gain["slot"]
        if gain["delta"] > best_by_slot.get(slot, 0):
            best_by_slot[slot] = gain["delta"]
    total = sum(best_by_slot.values())
    best = max(best_by_slot.values()) if best_by_slot else None
    empties = len([g for g in gains if g["delta"] is None])
    return {
        "who": member["name"],
        "level": member.get("level"),
        "gains": gains,
        "total": total,
        "best": best,
        "line": _gain_line(len(gains), best, member["name"]),
        "delta_note": _delta_note(empties),
    }


def _member_places(char_rows: list[dict], members: list[dict],
                   entrances: dict) -> None:
    """Stamp each member with the continent they are standing on.

    Mutates `members` rather than returning a second list keyed by name,
    because two lists keyed by name is how a member ends up carrying somebody
    else's position.
    """
    where = {row["name"]: row.get("map") for row in char_rows}
    for member in members:
        member["continent"] = _continent_of(where.get(member["name"]), entrances)


def _family_line(members: list[dict], continents: dict) -> str:
    """Who is being compared against, and where they are standing.

    THE SECOND HALF MATTERS AS MUCH AS THE FIRST. Every "on their continent"
    on every card below is measured against this, so a reader who disagrees
    with a distance has to be able to see what it was measured from.
    """
    if not members:
        return "nothing here knows who the family are"
    who = ", ".join("%s %s" % (m["name"], m.get("level") or "?")
                    for m in members)
    places = {m.get("continent") for m in members}
    if len(places) == 1:
        only = places.pop()
        return "%s; all of them on %s" % (who, _continent_name(only, continents))
    named = ", ".join(sorted(_continent_name(p, continents) for p in places))
    return "%s; spread across %s" % (who, named)


def _headline(ranked: list[dict], members: list[dict]) -> str:
    """The one line at the top. Counts, never a recommendation."""
    if not ranked:
        return ("the world database listed no dungeons this page could read, "
                "so there is nothing to compare")
    worth = len([d for d in ranked if d["gainers"]])
    if not worth:
        return ("%s read, and not one of them holds anything that beats what "
                "is already worn" % _dungeon_count(len(ranked)))
    holds = "1 of them holds" if worth == 1 else "%d of them hold" % worth
    return "%s read, %s something for somebody" % (_dungeon_count(len(ranked)),
                                                   holds)


def map_ids(catalogue_rows: list[dict], names: dict) -> list[int]:
    """Every map this page will have a row for, so the reads can cover them all.

    PUBLIC, AND CALLED BEFORE THE ENCOUNTER AND LOOT READS, because those two
    bind a map list and a map they do not name comes back with no bosses. The
    fetch used to build that list from the catalogue alone, which was right
    only while the catalogue and the page's rows were the same set. They are
    not, since _catalogue started taking this union, and a map added to the
    page but missing from the reads would have rendered as "no boss loot" over
    a dungeon whose loot was simply never asked for.
    """
    return sorted({int(row["map_id"]) for row in catalogue_rows}
                  | {int(map_id) for map_id in names})


def _catalogue(catalogue_rows: list[dict], names: dict) -> dict:
    """map id -> the one catalogue entry this page uses for it.

    THE UNION OF TWO LISTS, AND THAT IS A DEFECT FIX RATHER THAN A PREFERENCE
    (found reviewing infra#3500). The first version built a row per
    `dungeon_access_template` map and nothing else, so a dungeon that table
    does not list did not appear on this page AT ALL - no row, no sentence,
    no count. The failure that makes that unacceptable is specific: the family
    are running one dungeon a hundred times right now, and the one thing this
    page must never do is leave that dungeon out in a way a reader cannot tell
    from "there is nothing there for you".

    So a map this SITE already names gets a row even when the access table has
    nothing to say about it, and `source` records which list it came from. The
    access table stays the primary list, because it is the world's own and it
    carries the level range; `names` is a floor under it and never a filter on
    it - a map in the access table and not in `names` is still listed.

    TWO ROWS PER MAP IS NORMAL. `dungeon_access_template` is keyed per
    difficulty, so a map can arrive twice with two level ranges. Widening them
    into one range by taking the lowest minimum and the highest maximum would
    print a span neither row states, so the LOWEST DIFFICULTY row wins whole
    and the rest are dropped. On a world with one difficulty per dungeon that
    is every row.

    THE NAME IS THE SITE'S OWN WHERE THE SITE HAS ONE. achievements.MAP_NAMES
    is what the Chronicle, the recap and the current-goal banner call these
    places, and a second spelling of "The Deadmines" on one site is a place a
    reader has to work out is the same place. The catalogue's `comment` is the
    fallback, because it is what the world database calls it, and "map %d" is
    the fallback to that.
    """
    best: dict = {}
    for map_id in names:
        map_id = int(map_id)
        best[map_id] = {
            "map_id": map_id, "difficulty": 0, "min_level": 0, "max_level": 0,
            "name": names[map_id], "source": SITE_LIST, "party_size": "",
        }
    for row in catalogue_rows:
        map_id = int(row["map_id"])
        difficulty = int(row.get("difficulty") or 0)
        # A row already taken from the access table wins over a later one at a
        # higher difficulty; a placeholder seeded from the site's list above
        # always loses, because a real row is what this page would rather have.
        seated = best.get(map_id)
        if (seated is not None and seated["source"] == ACCESS_TABLE
                and seated["difficulty"] <= difficulty):
            continue
        comment = (row.get("comment") or "").strip()
        best[map_id] = {
            "map_id": map_id,
            "difficulty": difficulty,
            "min_level": int(row.get("min_level") or 0),
            "max_level": int(row.get("max_level") or 0),
            "name": names.get(map_id) or comment or "map %d" % map_id,
            "source": ACCESS_TABLE,
            "party_size": party_size(comment),
        }
    return best


def _source_line(entry: dict) -> str:
    """Where this dungeon's row came from, said only when it is not the usual
    place. Empty for an access-table row, so the page prints nothing rather
    than captioning twenty rows with the same unremarkable fact."""
    if entry.get("source") == ACCESS_TABLE:
        return ""
    return ("the world's dungeon access table does not list this one, so it is "
            "here because this site names it; its level range is unknown "
            "rather than absent")


def _coverage_line(dungeons: list[dict], catalogue_rows: list[dict]) -> str:
    """How many dungeons this page had to work with, and where they came from.

    THE ANSWER TO "WHY IS THE ONE WE ARE RUNNING NOT IN HERE". A list that is
    simply SHORT reads exactly like a list that is complete, and a reader
    scanning twenty rows has no way to tell that a twenty-first was never
    offered. Three states have to stay apart, and this sentence is the only
    thing that can keep the third of them visible:

      listed, and somebody gains        - the row says who
      listed, nothing readable in it    - the row says no boss loot is listed
      never listed at all               - ONLY this sentence can say it

    So it counts both source lists and says plainly that a map on neither
    cannot appear, rather than letting an absence pass for an answer.
    """
    if not dungeons:
        return ""
    from_access = len({int(row["map_id"]) for row in catalogue_rows})
    added = len([d for d in dungeons if d["source"] == SITE_LIST])
    readable = len([d for d in dungeons if d["pieces"]])
    where = ("%s listed: %d from the world's own dungeon access table"
             % (_dungeon_count(len(dungeons)), from_access))
    if added:
        where += (" and 1 more this site names that the table does not"
                  if added == 1 else
                  " and %d more this site names that the table does not" % added)
    return ("%s. %d of them had boss loot this page could read, and the rest "
            "say so on their own row. A map on neither list does not appear "
            "here at all." % (where, readable))


def _drops_on(map_id: int, bosses_on: dict, by_creature: dict,
              boss_name: dict, members: list[dict], icons: dict,
              proficiency_checked: bool, book=None) -> list[tuple]:
    """One (payload, verdict, boss) per drop per member, on one map.

    ONE VERDICT PER PAIR, COMPUTED ONCE. The per-member gain lists are filtered
    views of this list, not five more passes over the loot, which is what keeps
    a cross product of twenty dungeons against five characters cheap.

    A boss whose loot id is shared with another boss on the same map would
    otherwise list the same sword twice, which `seen` is for.
    """
    drops: list[tuple] = []
    seen: set = set()
    for creature in sorted(bosses_on.get(map_id, ())):
        for row in by_creature.get(creature, []):
            if not recap.slots_for(row.get("inventory_type")):
                continue
            item = int(row["Item"])
            if (creature, item) in seen:
                continue
            seen.add((creature, item))
            payload = recap.item_payload(item, row, icons, book)
            payload["caveats"] = recap.caveats_for(row, proficiency_checked)
            for member in members:
                verdict = recap.verdict(row, member)
                verdict["caveats"] = payload["caveats"]
                drops.append((payload, verdict, boss_name[creature]))
    return drops


def _dungeon_card(entry: dict, drops: list[tuple], members: list[dict],
                  bosses: int, entrances: dict, continents: dict) -> dict:
    """One dungeon as the page draws it, minus its place in the order.

    `rank` and `tie_line` are stamped on afterwards, because neither is a fact
    about this dungeon on its own: both are facts about where it landed among
    the others, and a card that filled them in here would be guessing at an
    order that has not been decided yet.
    """
    per_member = [found for found in
                  (_member_gains([d for d in drops
                                  if d[1]["who"] == member["name"]], member)
                   for member in members)
                  if found["gains"]]
    gainers = [found["who"] for found in per_member]
    pieces = len({payload["entry"] for payload, _, _ in drops})
    blocked = _under_minimum(entry, members)
    levels = [int(m.get("level") or 0) for m in members if m.get("level")]
    continent = _continent_of(entry["map_id"], entrances)
    total = sum(found["total"] for found in per_member)
    # A dungeon nobody can reach yet is still listed, because "not yet" is an
    # answer somebody planning a week wants. It is ordered below the ones they
    # can walk into today.
    shut = bool(blocked) and len(blocked) == len(members)
    return {
        "map_id": entry["map_id"],
        "name": entry["name"],
        "gainers": gainers,
        "members": per_member,
        "total": total,
        "bosses": bosses,
        "pieces": pieces,
        "line": _dungeon_line(gainers, members, pieces),
        "level_line": _level_line(entry, levels),
        "where_line": _where_line(continent, members, continents),
        "entry_line": _entry_line(blocked, members),
        "source": entry.get("source", ACCESS_TABLE),
        "source_line": _source_line(entry),
        "shut": shut,
        "chips": _chips(entry, continent, members, continents, total, shut),
    }


def _place_them(dungeons: list[dict]) -> None:
    """Put the cards in order and tell each one where it landed.

    THE ORDER IS ONE RULE AND THE PAGE PRINTS IT: nobody can gain here at all
    last, then how many would gain, then the item levels that gain would add,
    then the name so the list does not move on its own.
    """
    dungeons.sort(key=lambda d: (d["shut"], -len(d["gainers"]), -d["total"],
                                 d["name"]))
    scores: dict = {}
    for dungeon in dungeons:
        scores.setdefault(_score(dungeon), []).append(dungeon["name"])
    for place, dungeon in enumerate(dungeons, start=1):
        # A DUNGEON WITH NOTHING IN IT IS NOT TIED WITH ANYTHING, it is empty.
        # Without this the fifteen dungeons that hold nothing each print a
        # fourteen-name tie line, which is noise standing where a finding
        # should be and is also not what "tied" means.
        dungeon["tie_line"] = (_tie_line(dungeon["name"], scores[_score(dungeon)])
                               if dungeon["gainers"] else "")
        # THE PLACE IN THE LIST IS DECIDED HERE, not counted by the page off
        # the position it drew a row at. The page would get the same number
        # today, and a different one the first time it filtered or paged the
        # list, with nothing failing and the tie lines still naming the old
        # order.
        dungeon["rank"] = place


def _score(dungeon: dict) -> tuple:
    """What two dungeons have to match on to be called tied. The sort key
    without the name, which is the tie-break rather than part of the score."""
    return (dungeon["shut"], len(dungeon["gainers"]), dungeon["total"])


def build_dungeonplan(catalogue_rows: list[dict], encounter_rows: list[dict],
                      loot_rows: list[dict], char_rows: list[dict],
                      equipped_rows: list[dict], icons: dict,
                      roster: list[str], names: dict,
                      entrances: dict, continents: dict,
                      skill_rows: list[dict] | None = None,
                      book=None) -> dict:
    """Every dungeon, who would gain in it, and what they would gain.

    `catalogue_rows` are `dungeon_access_template` rows and are the list of
    dungeons. A hand-written list is what put a boss in the Chronicle the core
    does not count (infra#3189), and it also cannot follow the family into a
    dungeon nobody has added to it yet.

    `encounter_rows` carry the map each boss is spawned on, which is how a
    whole-world encounter table is bucketed into dungeons at all:
    `instance_encounters` has no map column, because the worldserver reads
    that from DungeonEncounter.dbc, which this service will never see.

    `skill_rows` are `character_skills` rows and are what lets the verdict
    answer proficiency (mod-overseer#411). They default to None so a caller
    that has not got them still gets a page, with the basis saying that a
    weapon was ranked on item level alone.

    `book` is an armory.ItemBook and is what turns a drop's name into a
    TOOLTIP (infra#3501). It matters more here than anywhere else on the site:
    this page ranks by item level and says in its own footer that it applies no
    stat weighting, so the tooltip is how a reader does the weighting the page
    refuses to do. Optional for the same reason it is optional in
    recap.item_payload - without it every row still renders, with its name in
    its quality colour and its link out.
    """
    members = recap.family_members(char_rows, equipped_rows, roster, skill_rows)
    _member_places(char_rows, members, entrances)
    # EVERY MEMBER OR THE BASIS STILL WARNS, exactly as the loot board's does:
    # one character whose skills are missing is one character whose verdicts
    # are the old item-level ones, and that is a fact about the page rather
    # than about that character.
    proficiency_checked = bool(members) and all(
        member["skills"] is not None for member in members)
    catalogue = _catalogue(catalogue_rows, names)

    boss_name: dict = {}
    bosses_on: dict = {}
    for row in encounter_rows:
        creature = int(row["creature"])
        boss_name[creature] = row["name"]
        bosses_on.setdefault(int(row["map_id"]), set()).add(creature)

    by_creature: dict = {}
    for row in loot_rows:
        by_creature.setdefault(int(row["creature"]), []).append(row)

    dungeons = [
        _dungeon_card(entry,
                      _drops_on(map_id, bosses_on, by_creature, boss_name,
                                members, icons, proficiency_checked, book),
                      members, len(bosses_on.get(map_id, ())), entrances,
                      continents)
        for map_id, entry in catalogue.items()]
    _place_them(dungeons)

    return {
        "line": _headline(dungeons, members),
        "family_line": _family_line(members, continents),
        "coverage": _coverage_line(dungeons, catalogue_rows),
        "dungeons": dungeons,
        "basis": _basis(proficiency_checked),
        "order": (
            "Ordered by how many of the five would gain something, then by the "
            "item levels that gain would add, then by name so the order does "
            "not move on its own. A dungeon the access table says nobody is "
            "high enough for is ordered last whatever it holds. A tie says so "
            "on the card it is tied on, rather than letting the one printed "
            "higher read as the better answer."),
        "empty_note": ("the world database listed no dungeons this page could "
                       "read, so there is nothing to compare"
                       if not dungeons else ""),
    }


def _basis(proficiency_checked: bool) -> str:
    """What this page read, and the four things it does not know.

    THE HOUSE RULE IS THAT THE LIST SAYS WHAT IT DOES NOT COVER, and the loot
    board's own footer is the precedent. Ranking by item level with no stat
    weighting is the weakest claim on this page and it is stated first,
    because a reader who takes the order as a strength ranking will act on it.
    """
    return (
        "Dungeons from the core's own dungeon_access_template, which is also "
        "where the level range comes from. Bosses from instance_encounters, "
        "narrowed to the credit creatures actually spawned on each map, so an "
        "encounter whose creature is summoned rather than spawned is not "
        "listed and neither is its loot. BOSS loot only: what trash drops on "
        "the way, what a quest inside hands over and what a reputation earned "
        "there buys are all real reasons to run a dungeon and none of them are "
        "counted here. Drops from creature_loot_template, "
        "direct rows only: loot behind reference_loot_template is not "
        "followed, so this is not a complete drop list and a dungeon can hold "
        "more than it says here. Ranked by item level only: no stat weighting "
        "is applied anywhere, a piece that is worse for a character with a "
        "higher item level on it will still be called a gain, and a tie is "
        "reported as a tie. How likely any of it is to drop is not asked here "
        "at all; the loot board on the Chronicle asks that one dungeon at a "
        "time. Where the entrance stands comes from the committed "
        "entrances.json, generated from areatrigger_teleport joined to the "
        "client's own AreaTrigger table. A party size on a chip is whatever "
        "that dungeon's own row in the access table happens to say in its "
        "comment, which is free text rather than a column: it is read to show "
        "and never to narrow the list, several dungeons name no size at all "
        "and at least one names two, so a row WITHOUT that chip is not a claim "
        "that it takes five. The list of dungeons is the world's "
        "dungeon_access_template plus any map this site already names, and a "
        "map on neither list does not appear above at all, which is not the "
        "same as a map that appears saying nothing in it was readable. " + (
            "Whether a character can hold a thing is read from their own "
            "character_skills rows, using the core's own subclass-to-skill "
            "map, so a weapon or a shield nobody can use is refused by name "
            "rather than counted as a gain."
            if proficiency_checked else
            "Proficiency could not be read for every character this time, so "
            "a weapon is ranked on item level alone and the drop says so."))
