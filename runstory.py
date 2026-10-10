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
recorded on the dungeon's own map it was inside; when it came after the run was
formed but before the group got in, and off that map, it was on the way in. A
death before the run was formed is not the run's. Whether a level was too low,
or which death broke a wipe, is a judgment, and the cause line says "likely"
for it. Nothing is said about the order of a boss kill and a death, because no
row records when a boss went down on a guild run, and nothing is said of a
member's mana, which no death row holds. When nothing in the rows explains a
wipe the cause line says so: "Cause not measured."

ONE HEALER IS NO CAUSE. A classic five-man group is a tank, a healer and three
damage dealers, and guildrun seats exactly that; since #721 the healer stands at
the bosses' level. Cards that said "Likely cause: a lone level 20 healer." for
every Deadmines wipe named the group's normal shape as its fault. A seat's
level is told only against the bosses' level (guildrun.carry_floor), for any
seat, and who died first in the wipe is told from the death rows.

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

# Rows are written on a poll, so the recorded end can trail the last death.
SLACK_SECONDS = 90
# Deaths no further apart than this are one fight.
FIGHT_GAP_SECONDS = 15
# Deaths no further apart than this are one wipe: a wipe spreads over a minute
# as the last members are run down (run 493: 42 seconds, gaps up to 33).
WIPE_GAP_SECONDS = 60
# Deaths this close to the wipe's first are first with it.
FIRST_TIE_SECONDS = 1
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
    "below_bosses": "seats below the bosses' level",
    "tank_died_first": "the tank died first in the wipe",
    "healer_died_first": "the healer died first in the wipe",
    "died_alone_after": "one member died alone again and again after the wipe",
    "boss_burst": "burst from a boss",
    "pack_wipe": "a pull too big for the group",
    "died_on_the_way": "deaths on the way in",
    "restart_lost": "a world server restart lost the run",
    "unexplained": "cause not measured",
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
        "below_bosses",
        "tank_died_first",
        "healer_died_first",
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
    if tags and all(t == "unexplained" for t in tags):
        return "Cause not measured."
    tags = [t for t in tags if t != "unexplained"][:CAUSE_PHRASES]
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


def _door(keyword: str, boss_levels: dict | None = None):
    for door in guildrun.doors(None, boss_levels):
        if door.keyword == keyword:
            return door
    return None


def death_scope(views: list) -> tuple:
    """The names whose deaths the given guild runs need, and the windows
    (start, end) worth reading, overlapping ones merged, oldest first.

    A window runs from the moment the run was formed to SLACK_SECONDS
    after it ended. A run without both times has none."""
    names: set = set()
    spans = []
    for view in views:
        start, end = _when(view.get("created_at")), _when(view.get("ended_at"))
        if start is None or end is None:
            continue
        names |= {m["name"] for m in _members(view)}
        spans.append((start, end + timedelta(seconds=SLACK_SECONDS)))
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
        if at is None or not (start <= at <= end + SLACK_SECONDS):
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


class _Tale:
    """A story being told: its sentences, its cause tags, and the words a
    tag takes when this run knows more than TAGS says."""

    def __init__(self):
        self.sentences: list = []
        self.tags: list = []
        self.facts: dict = {}

    def say(self, sentence: str) -> None:
        if sentence:
            self.sentences.append(sentence)

    def tag(self, tag: str, fact: str = "", first: bool = False) -> None:
        if tag in self.tags:
            return
        if first:
            self.tags.insert(0, tag)
        else:
            self.tags.append(tag)
        if fact:
            self.facts[tag] = fact

    def way_in(self, way: list, zones: dict) -> None:
        if way:
            self.say(_way_in_line(way, zones))
            self.tag("died_on_the_way")

    def fights(self, inside: list, classes: dict, wiped: bool, lead: str = "") -> None:
        """The told fights, with `lead` (the bosses line) joined onto a first
        boss fight or said before the fights."""
        lines, tags, boss_at = _tell_fights(inside, classes, wiped)
        if lead and boss_at == 0 and lines:
            lines[0] = "%s, and %s" % (lead, lines[0])
        elif lead:
            lines.insert(0, lead)
        for line in lines:
            self.say(line)
        for tag in tags:
            fact = "burst from %s" % _burst_boss(inside) if tag == "boss_burst" else ""
            self.tag(tag, fact)

    def unexplained_if(self, wiped: bool, explaining: tuple) -> None:
        if wiped and not any(t in self.tags for t in explaining):
            self.tag("unexplained")

    def story(self) -> str:
        sentences = self.sentences
        # The bosses line and the last fight matter more than the way in when
        # there is room for only four sentences.
        if len(sentences) > MAX_SENTENCES:
            sentences = [s for s in sentences if not s.startswith("lost ")]
        return _story(sentences)

    def told(self, cause: str | None = None) -> dict:
        if cause is None:
            cause = _cause_line(self.tags, self.facts) if self.tags else ""
        return Story(self.story(), cause, tuple(self.tags)).payload()


@dataclass(frozen=True)
class _GuildRun:
    """What one ended guild run's rows say, read once."""

    place: str
    door: object
    outcome: str
    why: str
    classes: dict
    seats: dict
    levels: list
    members: list
    seconds_inside: int
    deaths: int
    done: int
    total: int
    way: list
    inside: list


def _read_guild_run(
    run: dict, deaths: list, bosses: frozenset, boss_levels: dict | None = None
) -> _GuildRun:
    keyword = str(run.get("keyword") or "")
    door = _door(keyword, boss_levels)
    members = _members(run)
    inside_secs = _int(run.get("seconds_inside"))
    start = _clock(run.get("created_at"))
    end = _clock(run.get("ended_at"))
    end = start if end is None else end
    way, inside = [], []
    if start is not None and end is not None:
        way, inside = _guild_deaths(run, deaths, bosses, end - inside_secs, start, end)
    return _GuildRun(
        place=door.place if door else (run.get("place") or keyword or "the dungeon"),
        door=door,
        outcome=str(run.get("outcome") or ""),
        why=str(run.get("why") or ""),
        classes={m["name"]: str(m.get("class") or "") for m in members},
        seats={m["name"]: str(m.get("seat") or "") for m in members},
        levels=[_int(m.get("level")) for m in members if _int(m.get("level"))],
        members=members,
        seconds_inside=inside_secs,
        deaths=_int(run.get("deaths")),
        done=_int(run.get("bosses_done")),
        total=_int(run.get("bosses_total")),
        way=way,
        inside=inside,
    )


def _deaths_said(n: int) -> str:
    return "%s death%s" % (_num(n), "" if n == 1 else "s")


def _tell_cleared(g: _GuildRun, zones: dict) -> dict:
    tale = _Tale()
    minutes = round(g.seconds_inside / 60.0)
    tale.say(
        "cleared %s%s%s with %s"
        % (
            g.place,
            " in %d minutes" % minutes if minutes else "",
            " at " + _levels(g.levels) if g.levels else "",
            "nobody dying" if g.deaths == 0 else _deaths_said(g.deaths),
        )
    )
    if "finder" in g.why and g.total:
        tale.say(
            "the finder called it finished after %d of %d bosses" % (g.done, g.total)
        )
    elif g.total:
        tale.say("all %d bosses went down" % g.total)
    tale.way_in(g.way, zones)
    lines, _tags, _ = _tell_fights(g.inside, g.classes, wiped=False)
    for line in lines[:1]:
        tale.say(line)
    return tale.told("Cleared: %s." % (g.why or "the run finished"))


def _tell_lost(g: _GuildRun, zones: dict) -> dict:
    tale = _Tale()
    tale.say("no result ever came back from the world server for this run")
    if g.way:
        tale.say(_way_in_line(g.way, zones))
    tale.tag("restart_lost")
    return tale.told()


def _tell_refused(g: _GuildRun, zones: dict) -> dict:
    tale = _Tale()
    said = _plain(g.why) or "no reason given"
    tale.say("the world server would not start the %s run: %s" % (g.place, said))
    if "in combat" in g.why:
        tale.tag("refused_in_combat", said + " when the run was formed")
    else:
        tale.tag("refused", "the world server refused the run (%s)" % said)
    return tale.told()


def _tell_not_entered(g: _GuildRun, zones: dict) -> dict:
    tale = _Tale()
    tale.say("never got into %s: %s" % (g.place, _plain(g.why) or "no reason given"))
    tale.tag("never_entered")
    tale.way_in(g.way, zones)
    return tale.told()


def _below_bosses(g: _GuildRun) -> list:
    """The members under the bosses' level (the door's carry_floor), in seat
    order; none when that level is unread."""
    level = g.door.carry_floor if g.door else 0
    if level <= 0:
        return []
    return [m["name"] for m in g.members if 0 < _int(m.get("level")) < level]


def _wipe(inside: list) -> list:
    """The deaths of the wipe: the run of deaths no more than
    WIPE_GAP_SECONDS apart that took the most members, the first such.
    Empty when no two members died together."""
    best: list = []
    run: list = []
    for d in inside:
        if run and d.at - run[-1].at > WIPE_GAP_SECONDS:
            run = []
        run.append(d)
        if len({x.name for x in run}) > len({x.name for x in best}):
            best = list(run)
    return best if len({d.name for d in best}) >= 2 else []


def _seat_word(name: str, seats: dict) -> str:
    seat = seats.get(name, "")
    if seat == guildrun.TANK:
        return "the tank"
    if seat == guildrun.HEALER:
        return "the healer"
    return name


def _tell_wipe(tale: _Tale, g: _GuildRun, wipe: list) -> None:
    """Who the wipe took first, when it was the tank or the healer."""
    first = [d for d in wipe if d.at - wipe[0].at <= FIRST_TIE_SECONDS]
    seats = [g.seats.get(d.name, "") for d in first]
    if guildrun.TANK in seats:
        tag = "tank_died_first"
    elif guildrun.HEALER in seats:
        tag = "healer_died_first"
    else:
        return
    who = [w for w in ("the tank", "the healer") if w[4:] in seats]
    fact = "%s killed %s first" % (_killers(first), _join(who))
    healer = next((n for n, s in g.seats.items() if s == guildrun.HEALER), "")
    if tag == "tank_died_first" and healer and healer not in {d.name for d in wipe}:
        if not any(d.name == healer for d in g.inside):
            fact += " while the healer lived"
    tale.tag(tag, fact)


def _alone_after(g: _GuildRun, after: list) -> str:
    """ "the tank died alone 5 more times after the wipe" when every death
    after the wipe was one member's; else ""."""
    names = {d.name for d in after}
    if len(names) != 1:
        return ""
    return "%s died alone %d more time%s after the wipe" % (
        _seat_word(after[0].name, g.seats),
        len(after),
        "" if len(after) == 1 else "s",
    )


def _after_line(after: list) -> str:
    names = []
    for d in after:
        if d.name not in names:
            names.append(d.name)
    n = len(after)
    if len(names) == 1:
        return "after the wipe only %s died again, %d more time%s, to %s" % (
            names[0],
            n,
            "" if n == 1 else "s",
            _killers(after),
        )
    return "after the wipe %s died %d more times, to %s" % (
        _join(names),
        n,
        _killers(after),
    )


def _bosses_said(g: _GuildRun) -> str:
    if not g.total:
        return ""
    if g.done:
        return "got %d of %d bosses down" % (g.done, g.total)
    return "got none of the %d bosses down" % g.total


_ABANDONED = (
    ("group is gone", "group_gone"),
    ("nobody has been inside", "left_dungeon"),
)


_EXPLAINING = (
    "under_levelled",
    "below_bosses",
    "tank_died_first",
    "healer_died_first",
    "died_alone_after",
    "boss_burst",
    "pack_wipe",
)


def _tell_went_in(g: _GuildRun, zones: dict) -> dict:
    """A run that went in and did not clear: wiped, abandoned or timed out."""
    tale = _Tale()
    range_said, under = _range_clause(g.levels, g.door)
    low = _below_bosses(g)
    level = g.door.carry_floor if g.door else 0
    tale.say(
        "went into %s%s%s"
        % (
            g.place,
            range_said,
            ", with %s below the bosses' level %d" % (_join(low), level) if low else "",
        )
    )
    if low:
        tale.tag(
            "below_bosses",
            "%s seat%s below the bosses' level %d"
            % (_num(len(low)), "" if len(low) == 1 else "s", level),
        )
    if under:
        tale.tag("under_levelled")
    if g.way:
        tale.say(_way_in_line(g.way, zones))
    wiped = g.outcome == "wiped"
    told, after = g.inside, []
    wipe = _wipe(g.inside) if wiped else []
    if wipe:
        told = [d for d in g.inside if d.at <= wipe[-1].at]
        after = [d for d in g.inside if d.at > wipe[-1].at]
        alone = _alone_after(g, after)
        if alone:
            tale.tag("died_alone_after", alone, first=True)
        _tell_wipe(tale, g, wipe)
    tale.fights(told, g.classes, wiped, _bosses_said(g))
    if after:
        tale.say(_after_line(after))
    if g.way:
        tale.tag("died_on_the_way")
    if g.outcome == "abandoned":
        tag = next((t for said, t in _ABANDONED if said in g.why), "roles_down")
        tale.tag(tag, first=True)
        tale.say("the run was called off: %s" % _plain(g.why))
    elif g.outcome == "timed out":
        fact = (
            "the run ran out of time after %d of %d bosses" % (g.done, g.total)
            if g.total
            else ""
        )
        tale.tag("timed_out", fact, first=True)
        tale.say(
            "the run was called off after %d minutes inside"
            % round(g.seconds_inside / 60.0)
        )
    elif wiped and not g.inside:
        counted = " (%s)" % _deaths_said(g.deaths) if g.deaths else ""
        tale.say("everybody inside died%s, and no death record says to what" % counted)
    tale.unexplained_if(wiped, _EXPLAINING)
    return tale.told()


_GUILD_TELLERS = {
    guildrun.CLEARED: _tell_cleared,
    "lost": _tell_lost,
    "refused": _tell_refused,
    "not entered": _tell_not_entered,
}


def guild_story(
    run: dict, deaths: list, bosses=frozenset(), zones=None, boss_levels=None
) -> dict:
    """One ended guild run (a guildrun.page view, or an overseer_guild_run
    row) as {story, cause, causes}. `deaths` are overseer_death rows of any
    characters; only this run's members inside its window are read.
    `boss_levels` is map id -> its bosses' level (guildrun.BOSS_LEVELS_SQL);
    unread, no seat is called low. A run that has not ended has no story yet."""
    if str(run.get("state") or "") != guildrun.ENDED:
        return dict(NO_STORY)
    g = _read_guild_run(run, deaths, frozenset(bosses), boss_levels)
    teller = _GUILD_TELLERS.get(g.outcome, _tell_went_in)
    return teller(g, zones or {})


def tell_guild_runs(
    views: list, deaths: list, bosses=frozenset(), zones=None, boss_levels=None
) -> list:
    """Each view with its story, cause and causes added. Returns the views."""
    for view in views:
        view.update(guild_story(view, deaths, bosses, zones, boss_levels))
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


def _age(row: dict) -> float:
    """A row's moment on one axis: minus its age in seconds."""
    return -float(_int(row.get("age_seconds")))


def _family_deaths(
    rows: list, ended, deaths: list, names: list, bosses, dungeon: int
) -> tuple:
    """(on the way in, inside, whether the family got in) for one run."""
    start = _age(rows[0])
    end = _age(ended) if ended is not None else _age(rows[-1])
    went_in = next((_age(r) for r in rows if r.get("phase") in INSIDE_PHASES), None)
    family = set(names)
    way, inside = [], []
    for row in deaths:
        if row.get("character_name") not in family or row.get("age_seconds") is None:
            continue
        when = _age(row)
        if not (start <= when <= end + SLACK_SECONDS):
            continue
        d = _death(row, when, bosses)
        if dungeon and d.map_id == dungeon:
            inside.append(d)
        elif went_in is None or when < went_in:
            way.append(d)
    return way, inside, went_in is not None


def _family_outcome(ended) -> tuple:
    """(outcome word, reason) of an `ended` or `released` row."""
    if ended is None:
        return "", ""
    if ended.get("kind") == "released":
        return "released", str(ended.get("detail") or "")
    word, _, reason = str(ended.get("detail") or "").partition(":")
    return word.strip(), reason


def _family_opener(place: str, outcome: str, credited: int, got_in: bool) -> str:
    down = "%s boss%s down" % (_num(credited), "" if credited == 1 else "es")
    if outcome == "complete":
        return "cleared %s, %s" % (place, down) if credited else "cleared %s" % place
    if not got_in:
        return "never got inside %s" % place
    return "went into %s and got %s" % (place, down)


def _family_ending(tale: _Tale, outcome: str, reason: str, ended, inside: list) -> None:
    if outcome in _FAMILY_ENDS:
        said, tag = _FAMILY_ENDS[outcome]
        reason = _plain(reason.replace("BARRIER", "the wait at the door"))
        tale.say(said + (" (%s)" % reason if reason else ""))
        if tag:
            tale.tag(tag, "%s (%s)" % (TAGS[tag], reason) if reason else "", first=True)
    elif outcome == "released":
        tale.say("the run was let go: %s" % _plain(reason))
        tale.tag("released", first=True)
    elif outcome == "wipe" and not inside:
        tale.say("everybody died, and no death record says to what")
    elif ended is None:
        tale.say("no end was recorded")
        tale.tag("restart_lost")


def _family_cause(tale: _Tale, outcome: str) -> str:
    if outcome == "complete":
        cause = "Cleared: every encounter the map credits went down."
        return cause + (" " + _cause_line(tale.tags, tale.facts) if tale.tags else "")
    if outcome in ("left", "emptied") and not tale.tags:
        return "Cause: %s." % _FAMILY_ENDS[outcome][0]
    return _cause_line(tale.tags, tale.facts) if tale.tags else ""


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
    ended = run.get("ended")
    if not rows or (ended is None and latest):
        return dict(NO_STORY)
    portal = next((r.get("portal") for r in rows if r.get("portal")), "")
    door = _door(portal) if portal else None
    way, inside, got_in = _family_deaths(
        rows, ended, deaths, names, frozenset(bosses), door.map_id if door else 0
    )
    outcome, reason = _family_outcome(ended)
    credited, _in_all = _boss_counts(rows)
    tale = _Tale()
    tale.say(
        _family_opener(
            door.place if door else "the dungeon",
            outcome,
            credited,
            got_in or bool(inside),
        )
    )
    tale.way_in(way, zones or {})
    tale.fights(inside, {}, outcome == "wipe")
    _family_ending(tale, outcome, reason, ended, inside)
    if outcome != "complete" and any(r.get("kind") == "stalled" for r in rows):
        tale.tag("stalled")
    tale.unexplained_if(outcome == "wipe", ("boss_burst", "pack_wipe"))
    return tale.told(_family_cause(tale, outcome))
