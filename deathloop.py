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

PREVENTION (#2591). Deaths one through four are invisible to `loops`, so a
member visibly heading into a loop got no intervention until the loop had
fully formed, and the escape then relocated it into the next zone to start
again. `risk` is the pre-loop read beside `loops`, off the same rows: a
member is at risk when, with no level gained since the first of those
deaths, it has died two or more times to the same killer or in the same zone
within RISK_WINDOW_SECONDS, or three or more times across any zones within
WINDOW_SECONDS. The guild jobs pass intervenes on it (guildjobs'
death_risk_first) before the loop forms. And `avoided` is the memory
`loops` does not keep: a zone a loop formed in stays avoided for that member
until a level gain, even after the loop's quiet window lapses, so an escaped
member cannot drift back into the same zone at the same strength. It is
judged over a longer read (AVOID_READ_SECONDS) than `loops`.

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

# Prevention (#2591): two deaths to one killer, or in one zone, inside half
# an hour is a member heading into a loop; three deaths inside an hour
# across any zones is one too.
RISK_MIN_DEATHS = 2
RISK_WINDOW_SECONDS = 30 * 60
RISK_DEATHS = 3
# How far back the avoided read looks: a loop that formed within the last
# week still holds its zone avoided while the member is at the loop's level.
AVOID_READ_SECONDS = 7 * 24 * 3600

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


def _windows(deaths, span):
    """The sliding windows of `deaths` (newest first): for each death, the
    deaths no more than `span` seconds older than it, that death first. The
    loop, risk and formed-loop reads all judge windows of this one shape."""
    for i, newest in enumerate(deaths):
        yield [d for d in deaths[i:] if d.age - newest.age <= span]


def _zone_loop(name, deaths, level_now) -> Loop | None:
    """The newest window of one zone's deaths (newest first) that is a loop."""
    for window in _windows(deaths, WINDOW_SECONDS):
        if len(window) < MIN_DEATHS:
            continue
        levels = {d.level for d in window}
        if len(levels) != 1:
            continue
        level = levels.pop()
        if level_now is not None and int(level_now) != level:
            continue
        newest = window[0]
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


@dataclass(frozen=True)
class Risk:
    """One member heading into a death loop (#2591): how many deaths so far,
    where the newest of them happened, to what, at what level, and which
    rule named it (`trigger`: "killer", "zone" or "deaths").

    `first_age` and `last_age` are the seconds since the window's oldest and
    newest death, as Loop's."""

    name: str
    zone: int
    map_id: int
    deaths: int
    killer: str
    level: int
    trigger: str
    first_age: int
    last_age: int

    @property
    def place(self) -> str:
        return levelroute.zone_name(self.zone)

    def reason(self) -> str:
        """'died 2 times to Great Goretusk within 30 minutes, with no level
        gained' — the trigger named, in the loop reason's own shape."""
        if self.trigger == "killer":
            return "died %d times to %s within 30 minutes, with no level gained" % (
                self.deaths,
                self.killer,
            )
        if self.trigger == "zone":
            return "died %d times in %s within 30 minutes, with no level gained" % (
                self.deaths,
                self.place,
            )
        return "died %d times within an hour, with no level gained" % self.deaths

    def blocker(self) -> str:
        """`reason`, capitalised, with a stop, as Loop.blocker."""
        reason = self.reason()
        return reason[0].upper() + reason[1:] + "."


def _risk(name, window, trigger, level) -> Risk:
    newest = window[0]
    return Risk(
        name=name,
        zone=newest.zone,
        map_id=newest.map_id,
        deaths=len(window),
        killer=_top_killer(window),
        level=level,
        trigger=trigger,
        first_age=window[-1].age,
        last_age=newest.age,
    )


def _risk_window(name, current, key, trigger, level):
    """The newest window of one key's deaths (same killer, or same zone)
    inside RISK_WINDOW_SECONDS that holds RISK_MIN_DEATHS, or None."""
    groups: dict = {}
    for d in current:
        k = key(d)
        if k:
            groups.setdefault(k, []).append(d)
    best = None
    for group in groups.values():
        for window in _windows(group, RISK_WINDOW_SECONDS):
            if len(window) >= RISK_MIN_DEATHS:
                found = _risk(name, window, trigger, level)
                if best is None or found.last_age < best.last_age:
                    best = found
                break
    return best


def _risk_of(name, deaths, level_now) -> Risk | None:
    """One member's risk, or None. Only deaths at the member's level now
    count: a level gained since resets the run, which is the ticket's "no
    level gained since the first of those deaths". Without a level read, the
    run is the same-level prefix of the deaths, as `loops` judges it."""
    if level_now is not None:
        level = int(level_now)
        current = [d for d in deaths if d.level == level]
    else:
        level = deaths[0].level
        current = []
        for d in deaths:
            if d.level != level:
                break
            current.append(d)
    if not current or current[0].age > QUIET_SECONDS:
        return None
    found = _risk_window(name, current, lambda d: d.killer, "killer", level)
    if found is not None:
        return found
    found = _risk_window(name, current, lambda d: d.zone, "zone", level)
    if found is not None:
        return found
    for window in _windows(current, WINDOW_SECONDS):
        if len(window) >= RISK_DEATHS:
            return _risk(name, window, "deaths", level)
    return None


def risk(rows, levels=None) -> dict:
    """name -> Risk for every member of SQL's rows heading into a death loop.

    `levels` is name -> the member's level now, as for `loops`."""
    levels = levels or {}
    out = {}
    for name, deaths in _deaths_of(rows).items():
        found = _risk_of(name, deaths, levels.get(name))
        if found is not None:
            out[name] = found
    return out


def _formed_level(zone_deaths) -> int | None:
    """The level of a loop that formed in one zone's deaths, or None: a
    window of MIN_DEATHS inside WINDOW_SECONDS all at one level. The quiet
    clock does not clear it here; `avoided` is the memory `loops` lacks."""
    for window in _windows(zone_deaths, WINDOW_SECONDS):
        if len(window) < MIN_DEATHS:
            continue
        levels = {d.level for d in window}
        if len(levels) == 1:
            return levels.pop()
    return None


def avoided(rows, levels=None) -> dict:
    """name -> the zones a formed death loop leaves avoided until a level
    gain (#2591), as a sorted tuple. Judged over the AVOID_READ_SECONDS
    history: once a loop has formed in a zone, the zone stays avoided while
    the member is still the level it looped at, long after `loops` has let
    the loop itself clear on the quiet window.

    `levels` is name -> the member's level now, as for `loops`; a member it
    does not name is judged by its newest death's level."""
    levels = levels or {}
    out = {}
    for name, deaths in _deaths_of(rows).items():
        level_now = levels.get(name)
        if level_now is None:
            level_now = deaths[0].level
        by_zone: dict = {}
        for d in deaths:
            by_zone.setdefault(d.zone, []).append(d)
        zones = tuple(
            sorted(
                zone
                for zone, zone_deaths in by_zone.items()
                if zone and _formed_level(zone_deaths) == int(level_now)
            )
        )
        if zones:
            out[name] = zones
    return out
