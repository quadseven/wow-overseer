"""A member that keeps dying in one zone without gaining a level (#1464).

WHY THIS EXISTS. Measured on the dev realm on 2026-10-25: Cave's lowest member,
a level 21 priest, died 167 times in a day and stayed level 21, four to ten
deaths every hour, nearly all in Redridge Mountains and the Wetlands, half of
them to Great Goretusks four levels under it. The stuck reader counted no
deaths, so it listed two other members and not this one, and no step ever
walked it out: its own AI kept picking the same zone after every spirit
healer and corpse run. A player who dies five times in an hour in one place
stops, goes to town, and quests somewhere else.

WHAT A DEATH LOOP IS (`loops`). Read off overseer_death, the module's own row
per death with the level and zone recorded at the moment of death:

  * MIN_DEATHS or more deaths in one zone within WINDOW_SECONDS of each
    other,
  * every one of them at the same level, and the member's level now still
    that level (no level was gained in the hour, or since),
  * and the member's newest death in that zone under QUIET_SECONDS old.

So the entry clears by itself once the member gains a level or goes
QUIET_SECONDS without dying in the loop zone. The quiet clock is the zone's
own (#1569): a member that left the zone and died once or twice elsewhere is
out of the loop, where a clock over every zone kept a loop three hours old
listed. Nothing is kept between passes: each read sees the last READ_SECONDS
of deaths and judges them again.

WHAT IT IS FOR. The stuck reader (apiv2/members.py) lists the member with kind
KIND and the blocker sentence (`Loop.blocker`), and the guild jobs pass
(guildjobs.death_loop_step) sends the member to town and plans its next quest
hub outside the zone.

PURE: rows in, loops out. No MySQL, no clock: SQL returns each death's age in
seconds, measured by the database's own clock.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import levelroute

# Five deaths in one zone inside an hour is a loop.
MIN_DEATHS = 5
WINDOW_SECONDS = 3600
# A member that has not died for this long is out of the loop.
QUIET_SECONDS = 2 * 3600
# How far back the deaths are read: a window that ended up to QUIET_SECONDS ago
# is still seen whole.
READ_SECONDS = WINDOW_SECONDS + QUIET_SECONDS
# The stuck reader's kind for the entry.
KIND = "death-loop"

SQL = (
    "SELECT character_name AS name, zone, map, level, killer_name AS killer, "
    "TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age FROM overseer_death "
    "WHERE character_name IN ({holes}) "
    "AND created_at > NOW() - INTERVAL %s SECOND ORDER BY id"
)


@dataclass(frozen=True)
class Loop:
    """One member's death loop: where, how many deaths, to what, at what level.

    `first_age` and `last_age` are the seconds since the window's oldest and
    newest death."""

    name: str
    zone: int
    map_id: int
    deaths: int
    killer: str
    level: int
    first_age: int
    last_age: int

    @property
    def place(self) -> str:
        return levelroute.zone_name(self.zone)

    def reason(self) -> str:
        """'died 7 times in Redridge Mountains within an hour, mostly to Great
        Goretusk, with no level gained'"""
        killer = ", mostly to %s" % self.killer if self.killer else ""
        return "died %d times in %s within an hour%s, with no level gained" % (
            self.deaths,
            self.place,
            killer,
        )

    def blocker(self) -> str:
        """The stuck reader's sentence: `reason`, capitalised, with a stop."""
        reason = self.reason()
        return reason[0].upper() + reason[1:] + "."


@dataclass(frozen=True)
class _Death:
    age: int
    zone: int
    map_id: int
    level: int
    killer: str


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _deaths_of(rows) -> dict:
    """name -> its deaths, newest first. A row without an age is skipped."""
    out: dict = {}
    for row in rows or ():
        name = str(row.get("name") or "")
        age = row.get("age")
        if not name or age is None:
            continue
        out.setdefault(name, []).append(
            _Death(
                age=max(0, _int(age)),
                zone=_int(row.get("zone")),
                map_id=_int(row.get("map")),
                level=_int(row.get("level")),
                killer=str(row.get("killer") or ""),
            )
        )
    for deaths in out.values():
        deaths.sort(key=lambda d: d.age)
    return out


def _top_killer(window) -> str:
    """The killer named most often in the window, the newest of a tie."""
    counts = Counter(d.killer for d in window if d.killer)
    if not counts:
        return ""
    newest = {}
    for d in window:
        newest.setdefault(d.killer, d.age)
    return min(counts, key=lambda k: (-counts[k], newest[k], k))


def _zone_loop(name, deaths, level_now) -> Loop | None:
    """The newest window of one zone's deaths (newest first) that is a loop."""
    for i, newest in enumerate(deaths):
        window = [d for d in deaths[i:] if d.age - newest.age <= WINDOW_SECONDS]
        if len(window) < MIN_DEATHS:
            continue
        levels = {d.level for d in window}
        if len(levels) != 1:
            continue
        level = levels.pop()
        if level_now is not None and int(level_now) != level:
            continue
        return Loop(
            name=name,
            zone=newest.zone,
            map_id=newest.map_id,
            deaths=len(window),
            killer=_top_killer(window),
            level=level,
            first_age=window[-1].age,
            last_age=newest.age,
        )
    return None


RISK_WINDOW_SECONDS = 30 * 60
RISK_DEATHS = 3


@dataclass(frozen=True)
class Risk:
    """One member heading into a death loop (#2591): where its newest death
    was, how many deaths the trigger counts, to what, at what level, and the
    trigger phrase naming the rule that flagged it."""

    name: str
    zone: int
    map_id: int
    deaths: int
    killer: str
    level: int
    first_age: int
    last_age: int
    trigger: str

    @property
    def place(self) -> str:
        return levelroute.zone_name(self.zone)

    def reason(self) -> str:
        return "%s, with no level gained" % self.trigger

    def blocker(self) -> str:
        reason = self.reason()
        return reason[0].upper() + reason[1:] + "."


def _risk_at(name, window, trigger) -> Risk:
    newest = window[0]
    return Risk(
        name=name,
        zone=newest.zone,
        map_id=newest.map_id,
        deaths=len(window),
        killer=_top_killer(window),
        level=newest.level,
        first_age=window[-1].age,
        last_age=newest.age,
        trigger=trigger,
    )


def _anchored_window(deaths, span):
    """The deaths within `span` seconds of the newest one (deaths[0])."""
    return [d for d in deaths if d.age - deaths[0].age <= span]


def _level_flat(window, level_now) -> bool:
    """Every death in the window is at one level, and the member's level
    now is still that level: a level gained since the first of those
    deaths clears the risk, as it clears a loop."""
    return len({d.level for d in window}) == 1 and (
        level_now is None or int(level_now) == window[0].level
    )


def _same_killer_risk(name, window) -> Risk | None:
    """The risk when one killer killed the member twice in the window."""
    killers = Counter(d.killer for d in window if d.killer)
    if killers and max(killers.values()) >= 2:
        group = [d for d in window if d.killer == _top_killer(window)]
        return _risk_at(
            name,
            group,
            "died %d times to the same killer within 30 minutes" % len(group),
        )
    return None


def _same_zone_risk(name, window) -> Risk | None:
    """The risk when one zone saw the member die twice in the window."""
    zones = Counter(d.zone for d in window if d.zone)
    if zones and max(zones.values()) >= 2:
        zone = max(zones, key=lambda z: zones[z])
        group = [d for d in window if d.zone == zone]
        return _risk_at(
            name, group, "died %d times in the same zone within 30 minutes" % len(group)
        )
    return None


def _window_risk(name, deaths, level_now) -> Risk | None:
    """The risk in the window anchored at deaths[0] (newest first), or None.

    A window counts only when every death in it is at one level and the
    member's level now is still that level: a level gained since the first
    of those deaths clears the risk, as it clears a loop."""
    window = _anchored_window(deaths, WINDOW_SECONDS)
    if len(window) >= RISK_DEATHS and _level_flat(window, level_now):
        return _risk_at(name, window, "died %d times within an hour" % len(window))
    window = _anchored_window(deaths, RISK_WINDOW_SECONDS)
    if len(window) < 2 or not _level_flat(window, level_now):
        return None
    return _same_killer_risk(name, window) or _same_zone_risk(name, window)


def risks(rows, levels=None) -> dict:
    """name -> Risk for every member heading into a death loop (#2591).

    At risk when (a) two or more deaths to the same killer or in the same
    zone within 30 minutes, or (b) three or more deaths across any zones
    within an hour, in each case with no level gained since the first of
    those deaths. Pure, like `loops`: rows in, risk entries out."""
    levels = levels or {}
    out = {}
    for name, deaths in _deaths_of(rows).items():
        for i in range(len(deaths)):
            found = _window_risk(name, deaths[i:], levels.get(name))
            if found is not None:
                out[name] = found
                break
    return out


def avoided_zones(rows, levels=None) -> dict:
    """name -> the zones a formed loop leaves avoided until a level gain.

    `loops` clears on its quiet window alone; a loop's zone stays avoided
    after that window lapses (#2591), so this read ignores the quiet clock
    and judges every window the rows hold. A level gained since the loop
    (the member's level now differs from the loop's) clears the avoidance."""
    levels = levels or {}
    out = {}
    for name, deaths in _deaths_of(rows).items():
        by_zone: dict = {}
        for d in deaths:
            by_zone.setdefault(d.zone, []).append(d)
        zones = {
            zone
            for zone, zone_deaths in by_zone.items()
            if zone and _zone_loop(name, zone_deaths, levels.get(name)) is not None
        }
        if zones:
            out[name] = zones
    return out


def loops(rows, levels=None) -> dict:
    """name -> Loop for every member of SQL's rows in a death loop.

    `levels` is name -> the member's level now; a member it does not name is
    judged by its deaths' levels alone."""
    levels = levels or {}
    out = {}
    for name, deaths in _deaths_of(rows).items():
        by_zone: dict = {}
        for d in deaths:
            by_zone.setdefault(d.zone, []).append(d)
        # The quiet clock is each zone's own (#1569): deaths elsewhere do not
        # keep a zone the member has left listed.
        found = [
            loop
            for zone, zone_deaths in by_zone.items()
            if zone and zone_deaths[0].age <= QUIET_SECONDS
            for loop in (_zone_loop(name, zone_deaths, levels.get(name)),)
            if loop is not None
        ]
        if found:
            out[name] = min(found, key=lambda lp: (lp.last_age, -lp.deaths, lp.zone))
    return out
