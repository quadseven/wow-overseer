"""Why a run wiped, failed or cleared, told the way a guildmate would tell it.

WHY IT EXISTS. A wiped guild run used to say only "everybody inside is dead"
and its counts. The rows already hold more than that: who was in the group and
at what level, the dungeon's level range, and for every death who died, where,
when and to what. This module reads one run and the deaths of its members
around it and writes three things:

- `story`: two to four plain sentences, the run as a recap in guild chat;
- `cause`: one line, the cause, with anything inferred marked "likely";
- `causes`: tags from TAGS, so a later change can count causes across runs.

HONESTY RULES. A sentence states only what a row holds. When a death was
recorded on the dungeon's own map it was inside; when it came before the group
got in and off that map it was on the way in. Whether a level was too low, or
one healer too few, is a judgment, and the cause line says "likely" for it.
Nothing is said about the order of a boss kill and a death, because no row
records when a boss went down on a guild run.

It is pure: it reads dicts and returns dicts, and map_server.py does the
reading. The guild runs are overseer_guild_run rows as guildrun.page shapes
them; the family runs are runtimeline's runs, and their deaths carry the
database's own age in seconds so the two clocks cannot disagree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import guildrun

# Deaths this many seconds before a guild run was formed still belong to it:
# the group gathers from wherever its members were.
LEAD_SECONDS = 300
# Rows are written on a poll, so the recorded end can trail the last death.
SLACK_SECONDS = 90
# Deaths no further apart than this are one fight.
FIGHT_GAP_SECONDS = 15
# A group whose mean level is less than this far above the door's floor is at
# the bottom of the dungeon's range.
BOTTOM_MARGIN = 2
MAX_SENTENCES = 4
# The cause line names at most this many causes, the most telling first.
CAUSE_PHRASES = 3

# The phases of a family run in which the family is inside (runtimeline.PHASES).
INSIDE_PHASES = frozenset({"STAGED_INSIDE", "CLEARING"})

# Every tag this module writes. Inferred ones make the cause line "likely".
TAGS = {
    "under_levelled": "under-leveled for the elites",
    "single_healer": "only one healer",
    "boss_burst": "burst from a boss",
    "pack_wipe": "a pull too big for the group",
    "died_on_the_way": "deaths on the way in",
    "restart_lost": "a world server restart lost the run",
    "unexplained": "not clear from the death records",
    "refused_in_combat": "a member was in combat when the run was formed",
    "refused": "the world server refused the run",
    "never_entered": "the dungeon finder never took the group in",
    "group_gone": "the group broke up",
    "left_dungeon": "nobody stayed inside",
    "roles_down": "the tank and healer were not both alive inside",
    "timed_out": "the run ran out of time",
    "family_split": "the family split up",
    "never_gathered": "the family never gathered at the door",
    "reset_failed": "the dungeon would not reset",
    "bags_full": "the family ran out of bag room",
    "stalled": "the run stalled",
    "released": "the run was let go",
}
INFERRED = frozenset(
    {
        "under_levelled",
        "single_healer",
        "boss_burst",
        "pack_wipe",
        "died_on_the_way",
        "restart_lost",
    }
)

_NUMBERS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight")


@dataclass(frozen=True)
class Death:
    name: str
    at: float
    level: int
    map_id: int
    zone: int
    killer: str
    killer_type: str
    boss: bool


@dataclass(frozen=True)
class Story:
    story: str
    cause: str
    causes: tuple

    def payload(self) -> dict:
        return {"story": self.story, "cause": self.cause, "causes": list(self.causes)}


NO_STORY = {"story": "", "cause": "", "causes": []}


# --- words ----------------------------------------------------------------------


def _num(n: int) -> str:
    return _NUMBERS[n] if 0 <= n < len(_NUMBERS) else str(n)


def _join(parts: list) -> str:
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return "".join(parts)
    return "%s and %s" % (", ".join(parts[:-1]), parts[-1])


def _plural(word: str) -> str:
    """ "Deviate Viper" -> "Deviate Vipers", "Druid of the Fang" -> "Druids
    of the Fang", "Defias Henchman" -> "Defias Henchmen"."""
    head, sep, tail = word.partition(" of ")
    if head.endswith("man"):
        head = head[:-3] + "men"
    elif re.search(r"[^aeiou]y$", head):
        head = head[:-1] + "ies"
    elif re.search(r"(s|x|ch|sh)$", head):
        head += "es"
    else:
        head += "s"
    return head + sep + tail


def _a(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def _seconds(n: int) -> str:
    return "at once" if n <= 0 else "within %d second%s" % (n, "" if n == 1 else "s")


def _plain(why: str) -> str:
    """A module's reason as a reader says it: "900s" as "15 minutes", the
    quotes off a name."""

    def minutes(m: re.Match) -> str:
        secs = int(m.group(1))
        if secs >= 120:
            return "%d minutes" % round(secs / 60.0)
        return "%d seconds" % secs

    text = re.sub(r"\b(\d+)s\b", minutes, str(why or "").strip())
    return text.replace("'", "")


def _levels(levels: list) -> str:
    lo, hi = min(levels), max(levels)
    return "level %d" % lo if lo == hi else "levels %d to %d" % (lo, hi)


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith(".") else text + "."


# --- deaths ---------------------------------------------------------------------


def _when(value) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("T", " ")).replace(tzinfo=None)
    except ValueError:
        return None


_EPOCH = datetime(1970, 1, 1)


def _clock(value) -> float | None:
    at = _when(value)
    return None if at is None else (at - _EPOCH).total_seconds()


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _death(row: dict, at: float, bosses: frozenset) -> Death:
    entry = _int(row.get("killer_entry"))
    kind = str(row.get("killer_type") or "")
    return Death(
        name=str(row.get("character_name") or ""),
        at=at,
        level=_int(row.get("level")),
        map_id=_int(row.get("map")),
        zone=_int(row.get("zone")),
        killer=str(row.get("killer_name") or ""),
        killer_type=kind,
        boss=kind == "creature" and entry in bosses,
    )


def _fights(deaths: list) -> list:
    fights: list = []
    for d in sorted(deaths, key=lambda d: d.at):
        if fights and d.at - fights[-1][-1].at <= FIGHT_GAP_SECONDS:
            fights[-1].append(d)
        else:
            fights.append([d])
    return fights


def _killers(fight: list) -> str:
    counts: dict = {}
    for d in fight:
        key = (d.killer, d.killer_type, d.boss)
        counts[key] = counts.get(key, 0) + 1
    parts = []
    for (name, kind, boss), n in counts.items():
        if not name:
            parts.append(
                "the fall or the elements"
                if kind == "environment"
                else "something the record does not name"
            )
        elif boss or kind == "player":
            parts.append(name)
        else:
            parts.append(_plural(name) if n > 1 else _a(name))
    return _join(parts)


def _victims(fight: list, classes: dict) -> str:
    names = [d.name for d in fight]
    if len(names) == 1:
        return names[0]
    kinds = {classes.get(n) or "" for n in names}
    if len(kinds) == 1 and "" not in kinds:
        word = "both" if len(names) == 2 else "all %s" % _num(len(names))
        return "%s %s" % (word, _plural(kinds.pop()))
    return _join(names)


def _fight_line(fight: list, classes: dict, last_of_wipe: bool) -> tuple:
    """One fight as a sentence, and the tag it earns ("" for none)."""
    span = int(fight[-1].at - fight[0].at)
    killers = _killers(fight)
    n = len(fight)
    if all(d.boss for d in fight) and n > 1:
        return "%s dropped %s %s" % (
            killers,
            _victims(fight, classes),
            _seconds(span),
        ), "boss_burst"
    if all(d.boss for d in fight):
        return "%s killed %s" % (killers, fight[0].name), ""
    tag = "pack_wipe" if n >= 3 else ""
    if last_of_wipe and n > 1:
        return "the last %s went down together to %s" % (_num(n), killers), tag
    if n > 1:
        return "%s went down together to %s" % (_victims(fight, classes), killers), tag
    return "%s died to %s" % (fight[0].name, killers), ""


def _burst_boss(inside: list) -> str:
    """The boss of the first fight a boss alone won with more than one kill."""
    for fight in _fights(inside):
        if len(fight) > 1 and all(d.boss for d in fight):
            return fight[0].killer
    return "a boss"


def _way_in_line(deaths: list, zones: dict) -> str:
    names = []
    for d in deaths:
        if d.name not in names:
            names.append(d.name)
    where = {zones.get(d.zone, "") for d in deaths}
    place = where.pop() if len(where) == 1 else ""
    line = "lost %s on the way in, to %s" % (_join(names), _killers(deaths))
    return line + (" in %s" % place if place else "")


def _tell_fights(inside: list, classes: dict, wiped: bool) -> tuple:
    """Up to two fights: the first boss burst and the last fight of a wipe;
    else the deadliest. Returns (sentences in time order, tags, the boss
    sentence index or -1)."""
    fights = _fights(inside)
    if not fights:
        return [], [], -1
    told: list = []
    for i, fight in enumerate(fights):
        if all(d.boss for d in fight) and len(fight) > 1:
            told.append(i)
            break
    last = len(fights) - 1
    if wiped and last not in told:
        told.append(last)
    if not told:
        told.append(max(range(len(fights)), key=lambda i: (len(fights[i]), i)))
    lines, tags, boss_at = [], [], -1
    for i in sorted(told)[:2]:
        line, tag = _fight_line(fights[i], classes, wiped and i == last)
        if tag and tag not in tags:
            tags.append(tag)
        if tag == "boss_burst" and boss_at < 0:
            boss_at = len(lines)
        lines.append(line)
    return lines, tags, boss_at


def _cause_line(tags: list, facts: dict) -> str:
    """ "Cause: x." when every tag is a fact, "Likely cause: x." when every
    tag is a judgment, and "Cause: x; likely y." when both. The line names
    the first CAUSE_PHRASES tags; `causes` keeps them all."""
    tags = tags[:CAUSE_PHRASES]
    said = []
    for tag in tags:
        said.append(facts.get(tag) or TAGS[tag])
    known = [s for t, s in zip(tags, said, strict=True) if t not in INFERRED]
    guessed = [s for t, s in zip(tags, said, strict=True) if t in INFERRED]
    if known and guessed:
        return "Cause: %s; likely %s." % (_join(known), _join(guessed))
    if known:
        return "Cause: %s." % _join(known)
    return "Likely cause: %s." % _join(guessed)


def _story(sentences: list) -> str:
    return " ".join(_sentence(s) for s in sentences[:MAX_SENTENCES] if s)


# --- guild runs -----------------------------------------------------------------


def _door(keyword: str):
    for door in guildrun.doors():
        if door.keyword == keyword:
            return door
    return None


def death_scope(views: list) -> tuple:
    """The names whose deaths the given guild runs need, and the windows
    (start, end) worth reading, overlapping ones merged, oldest first.

    A window runs from LEAD_SECONDS before the run was formed to
    SLACK_SECONDS after it ended. A run without both times has none."""
    names: set = set()
    spans = []
    for view in views:
        start, end = _when(view.get("created_at")), _when(view.get("ended_at"))
        if start is None or end is None:
            continue
        names |= {m["name"] for m in _members(view)}
        spans.append(
            (
                start - timedelta(seconds=LEAD_SECONDS),
                end + timedelta(seconds=SLACK_SECONDS),
            )
        )
    merged: list = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sorted(names), merged


def _members(run: dict) -> list:
    members = run.get("members") or []
    if isinstance(members, str):
        members = guildrun._member_list(members)
    return [m for m in members if isinstance(m, dict) and m.get("name")]


def _guild_deaths(
    run: dict, deaths: list, bosses: frozenset, entered: float, start: float, end: float
) -> tuple:
    """(on the way in, inside) for one guild run, each oldest first."""
    door = _door(str(run.get("keyword") or ""))
    dungeon = door.map_id if door else 0
    names = {m["name"] for m in _members(run)}
    way, inside = [], []
    for row in deaths:
        if row.get("character_name") not in names:
            continue
        at = _clock(row.get("created_at"))
        if at is None or not (start - LEAD_SECONDS <= at <= end + SLACK_SECONDS):
            continue
        d = _death(row, at, bosses)
        if dungeon and d.map_id == dungeon:
            inside.append(d)
        elif at < entered:
            way.append(d)
        elif not dungeon:
            inside.append(d)
    return sorted(way, key=lambda d: d.at), sorted(inside, key=lambda d: d.at)


def _range_clause(levels: list, door) -> tuple:
    """(" at levels 17 to 19, the bottom of its 17 to 24 range", under?)"""
    if not levels:
        return "", False
    said = " at " + _levels(levels)
    if door is None:
        return said, False
    mean = sum(levels) / len(levels)
    span = "%d to %d" % (door.floor, door.ceiling)
    if mean < door.floor + BOTTOM_MARGIN:
        return said + ", the bottom of its %s range" % span, True
    if mean > door.ceiling:
        return said + ", above its %s range" % span, False
    return said, False


def guild_story(run: dict, deaths: list, bosses=frozenset(), zones=None) -> dict:
    """One ended guild run (a guildrun.page view, or an overseer_guild_run
    row) as {story, cause, causes}. `deaths` are overseer_death rows of any
    characters; only this run's members inside its window are read.
    A run that has not ended has no story yet."""
    if str(run.get("state") or "") != guildrun.ENDED:
        return dict(NO_STORY)
    zones = zones or {}
    bosses = frozenset(bosses)
    keyword = str(run.get("keyword") or "")
    door = _door(keyword)
    place = door.place if door else (run.get("place") or keyword or "the dungeon")
    outcome = str(run.get("outcome") or "")
    why = str(run.get("why") or "")
    members = _members(run)
    classes = {m["name"]: str(m.get("class") or "") for m in members}
    levels = [_int(m.get("level")) for m in members if _int(m.get("level"))]
    healers = [m for m in members if m.get("seat") == guildrun.HEALER]
    inside_secs = _int(run.get("seconds_inside"))
    done, total = _int(run.get("bosses_done")), _int(run.get("bosses_total"))
    end = _clock(run.get("ended_at"))
    start = _clock(run.get("created_at"))
    if end is None:
        end = start
    entered = (end - inside_secs) if end is not None else None
    way, inside = ([], [])
    if end is not None and start is not None:
        way, inside = _guild_deaths(run, deaths, bosses, entered, start, end)

    tags: list = []
    facts: dict = {}
    sentences: list = []

    if outcome == guildrun.CLEARED:
        minutes = round(inside_secs / 60.0)
        n = _int(run.get("deaths"))
        who = (
            "nobody dying"
            if n == 0
            else "%s death%s" % (_num(n), "" if n == 1 else "s")
        )
        sentences.append(
            "cleared %s%s%s with %s"
            % (
                place,
                " in %d minutes" % minutes if minutes else "",
                " at " + _levels(levels) if levels else "",
                who,
            )
        )
        if "finder" in why and total:
            sentences.append(
                "the finder called it finished after %d of %d bosses" % (done, total)
            )
        elif total:
            sentences.append("all %d bosses went down" % total)
        if way:
            sentences.append(_way_in_line(way, zones))
            tags.append("died_on_the_way")
        if inside:
            lines, _fight_tags, _ = _tell_fights(inside, classes, wiped=False)
            sentences.extend(lines[:1])
        cause = "Cleared: %s." % (why or "the run finished")
        return Story(_story(sentences), cause, tuple(tags)).payload()

    if outcome == "lost":
        sentences.append("no result ever came back from the world server for this run")
        if way:
            sentences.append(_way_in_line(way, zones))
        tags.append("restart_lost")
        return Story(_story(sentences), _cause_line(tags, facts), tuple(tags)).payload()

    if outcome == "refused":
        said = _plain(why) or "no reason given"
        sentences.append(
            "the world server would not start the %s run: %s" % (place, said)
        )
        if "in combat" in why:
            tags.append("refused_in_combat")
            facts["refused_in_combat"] = said + " when the run was formed"
        else:
            tags.append("refused")
            facts["refused"] = "the world server refused the run (%s)" % said
        return Story(_story(sentences), _cause_line(tags, facts), tuple(tags)).payload()

    if outcome == "not entered":
        sentences.append(
            "never got into %s: %s" % (place, _plain(why) or "no reason given")
        )
        if way:
            sentences.append(_way_in_line(way, zones))
            tags.append("died_on_the_way")
        tags.insert(0, "never_entered")
        return Story(_story(sentences), _cause_line(tags, facts), tuple(tags)).payload()

    # The run went in and did not clear: wiped, abandoned or timed out.
    range_said, under = _range_clause(levels, door)
    healer_low = False
    if len(healers) == 1 and levels:
        level = _int(healers[0].get("level"))
        floor = door.floor if door else 0
        healer_low = level <= floor or (level == min(levels) < max(levels))
    opener = "went into %s%s" % (place, range_said)
    if healer_low:
        opener += ", with one level %d healer" % _int(healers[0].get("level"))
    sentences.append(opener)
    if under:
        tags.append("under_levelled")
    if healer_low:
        tags.append("single_healer")
        facts["single_healer"] = "a lone level %d healer" % _int(
            healers[0].get("level")
        )

    if way:
        sentences.append(_way_in_line(way, zones))

    wiped = outcome == "wiped"
    lines, fight_tags, boss_at = _tell_fights(inside, classes, wiped)
    bosses_said = ""
    if total:
        bosses_said = (
            "got %d of %d bosses down" % (done, total)
            if done
            else "got none of the %d bosses down" % total
        )
    if bosses_said and boss_at == 0 and lines:
        lines[0] = "%s, and %s" % (bosses_said, lines[0])
    elif bosses_said:
        lines.insert(0, bosses_said)
    sentences.extend(lines)
    for tag in fight_tags:
        if tag == "boss_burst":
            facts["boss_burst"] = "burst from %s" % _burst_boss(inside)
        tags.append(tag)
    if way:
        tags.append("died_on_the_way")

    if outcome == "abandoned":
        if "group is gone" in why:
            tags.insert(0, "group_gone")
        elif "nobody has been inside" in why:
            tags.insert(0, "left_dungeon")
        else:
            tags.insert(0, "roles_down")
        sentences.append("the run was called off: %s" % _plain(why))
    elif outcome == "timed out":
        tags.insert(0, "timed_out")
        sentences.append(
            "the run was called off after %d minutes inside" % round(inside_secs / 60.0)
        )
    elif wiped and not inside:
        n = _int(run.get("deaths"))
        sentences.append(
            "everybody inside died%s, and no death record says to what"
            % (" (%s death%s)" % (_num(n), "" if n == 1 else "s") if n else "")
        )

    if wiped and not any(
        t in tags
        for t in ("under_levelled", "single_healer", "boss_burst", "pack_wipe")
    ):
        tags.append("unexplained")
    # Keep the narrative short: the bosses line and the last fight matter
    # more than the way in when there is room for only four sentences.
    if len(sentences) > MAX_SENTENCES and way:
        sentences = [s for s in sentences if not s.startswith("lost ")]
    return Story(_story(sentences), _cause_line(tags, facts), tuple(tags)).payload()


def tell_guild_runs(views: list, deaths: list, bosses=frozenset(), zones=None) -> list:
    """Each view with its story, cause and causes added. Returns the views."""
    for view in views:
        view.update(guild_story(view, deaths, bosses, zones))
    return views


# --- family runs ----------------------------------------------------------------

# How each family outcome word (runtimeline.OUTCOMES) is told, and its tag.
_FAMILY_ENDS = {
    "left": ("the family walked out", ""),
    "emptied": ("the dungeon was already empty", ""),
    "split_failed": ("the family split up", "family_split"),
    "staging_failed": ("the family never gathered at the door", "never_gathered"),
    "reset_failed": ("the dungeon would not reset", "reset_failed"),
    "evacuated": ("the family was walked out with no bag room left", "bags_full"),
}


def _boss_counts(rows: list) -> tuple:
    credited, in_all = 0, 0
    for row in rows:
        if row.get("kind") != "boss":
            continue
        detail = str(row.get("detail") or "")
        got = re.match(r"(\d+) encounters? credited", detail)
        if got:
            credited += int(got.group(1))
        total = re.search(r"(\d+) in all", detail)
        if total:
            in_all = int(total.group(1))
    return credited, max(credited, in_all)


def family_story(
    run: dict,
    deaths: list,
    names: list,
    bosses=frozenset(),
    zones=None,
    latest: bool = False,
) -> dict:
    """One family run (a runtimeline.split_runs run) as {story, cause,
    causes}. `deaths` are overseer_death rows with an `age_seconds` column;
    `names` are the family's members. A run still under way has no story."""
    rows = run.get("rows") or []
    if not rows:
        return dict(NO_STORY)
    zones = zones or {}
    bosses = frozenset(bosses)
    ended = run.get("ended")
    if ended is None and latest:
        return dict(NO_STORY)
    portal = next((r.get("portal") for r in rows if r.get("portal")), "")
    door = _door(portal) if portal else None
    place = door.place if door else "the dungeon"
    dungeon = door.map_id if door else 0

    def at(row) -> float:
        return -float(_int(row.get("age_seconds")))

    start = at(rows[0])
    end = at(ended) if ended is not None else at(rows[-1])
    went_in = next((at(r) for r in rows if r.get("phase") in INSIDE_PHASES), None)
    family = set(names)
    way, inside = [], []
    for row in deaths:
        if row.get("character_name") not in family or row.get("age_seconds") is None:
            continue
        when = at(row)
        if not (start <= when <= end + SLACK_SECONDS):
            continue
        d = _death(row, when, bosses)
        if dungeon and d.map_id == dungeon:
            inside.append(d)
        elif went_in is None or when < went_in:
            way.append(d)
    outcome = ""
    reason = ""
    if ended is not None:
        if ended.get("kind") == "released":
            outcome, reason = "released", str(ended.get("detail") or "")
        else:
            word, _, reason = str(ended.get("detail") or "").partition(":")
            outcome = word.strip()

    tags: list = []
    facts: dict = {}
    sentences: list = []
    credited, in_all = _boss_counts(rows)
    bosses_said = "%s boss%s down" % (_num(credited), "" if credited == 1 else "es")

    if outcome == "complete":
        sentences.append(
            "cleared %s, %s" % (place, bosses_said)
            if credited
            else "cleared %s" % place
        )
    elif went_in is None and not inside:
        sentences.append("never got inside %s" % place)
    else:
        sentences.append("went into %s and got %s" % (place, bosses_said))
    if way:
        sentences.append(_way_in_line(way, zones))
        tags.append("died_on_the_way")
    wiped = outcome == "wipe"
    lines, fight_tags, _ = _tell_fights(inside, {}, wiped)
    sentences.extend(lines)
    for tag in fight_tags:
        if tag == "boss_burst":
            facts["boss_burst"] = "burst from %s" % _burst_boss(inside)
        tags.append(tag)

    if outcome in _FAMILY_ENDS:
        said, tag = _FAMILY_ENDS[outcome]
        reason = _plain(reason.replace("BARRIER", "the wait at the door"))
        sentences.append(said + (" (%s)" % reason if reason else ""))
        if tag:
            tags.insert(0, tag)
            if reason:
                facts[tag] = "%s (%s)" % (TAGS[tag], reason)
    elif outcome == "released":
        sentences.append("the run was let go: %s" % _plain(reason))
        tags.insert(0, "released")
    elif wiped and not inside:
        sentences.append("everybody died, and no death record says to what")
    elif ended is None:
        sentences.append("no end was recorded")
        tags.append("restart_lost")
    if any(r.get("kind") == "stalled" for r in rows) and outcome != "complete":
        tags.append("stalled")
    if wiped and not any(t in tags for t in ("boss_burst", "pack_wipe")):
        tags.append("unexplained")
    if len(sentences) > MAX_SENTENCES and way:
        sentences = [s for s in sentences if not s.startswith("lost ")]
    if outcome == "complete":
        cause = "Cleared: every encounter the map credits went down."
        if tags:
            cause += " %s" % _cause_line(tags, facts)
    elif outcome in ("left", "emptied") and not tags:
        cause = "Cause: %s." % _FAMILY_ENDS[outcome][0]
    elif tags:
        cause = _cause_line(tags, facts)
    else:
        cause = ""
    return Story(_story(sentences), cause, tuple(tags)).payload()
