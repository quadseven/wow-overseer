"""Where a family levels next: a quest hub in level order, chosen like a group.

WHY THIS EXISTS. Nothing chose where a family quests. The leader's `new rpg`
picks from its own log and rolls level-bracket grind spots, so the Horde
family ended one day scattered across the Barrens, Ashenvale and Stonetalon,
dying to Sharptalon, to the Ashenvale Sentinels of Astranaar (an Alliance
town) and to Kolkar and Grimtotem elites, with two of the five holding no
quest at all. A group of players does it the other way round: it picks one
hub the weakest member can survive, works that hub's quests together, and
moves to the next hub when the quests run out or turn grey.

WHAT A HUB IS (`HUBS`). One friendly flight point per zone per side, named by
its taxi node, so the place the family is walked to is a spot the client's own
data puts a flight master of their side on (flightlearn.NODES). The zone's
LEVELS are not written here: they come from the realm's quest_template, the
10th to 90th percentile of the quest levels this side can take in that zone
(`bands`). Kalimdor and the Eastern Kingdoms only, per classic.py.

WHAT IS READ FROM THE WORLD DATABASE (`QUESTS_SQL`, `DANGER_SQL`), once per
process because none of it changes while a realm runs:

  * every quest of every hub zone: level, minimum level, race and class masks;
  * every spawn on the two continents that is hostile to somebody, grouped
    into CELL-yard cells with its level, whether it is elite, and which side
    it belongs to.

From those: a zone's band, the quests a family can still do there, and, within
DANGER_YARDS of the hub, how many hostile spawns stand well above the weakest
member, its hostile elites, and the other side's towns (the other side's
flight points, confirmed by that side's own NPCs standing around them).

WHY A RADIUS AND NOT THE ZONE, FOR SPAWNS. creature.zoneId is empty for nearly
every row on this realm, and zones.json's rectangles overlap so badly that the
Crossroads flight point falls inside Mulgore's. A hub's neighbourhood is what
the family actually walks, so danger is measured there.

WHAT IS READ ABOUT THE FAMILY, every pass: levels, races and classes; who has
been rewarded for and holds which quest; where the leader stands; the family's
own deaths per zone in the last DEATH_HOURS (the most honest danger reading
there is); worn gear.

WHAT MAY BE CHOSEN (`options`, `refusals`). A hub of the family's side, whose
quests start no more than council.NEAR_ENOUGH levels above the weakest
member, that the weakest member has not outgrown, that still holds MIN_OPEN
quests every member can take, on the continent the family stands on (the
crossing is refused while crossing.py says it cannot be made), and whose
flight point is not beside a town of the other side.

WHICH ONE (`heuristic`). Level order: the lowest band that still has work,
after putting last a zone where the family keeps dying (DEATHS_AVOID) or whose
hostile spawns are mostly far above the weakest (DANGER_SHARE). Jev is asked
the same question over the same options (jev_choices.zone_ask) and acts past
its confidence floor.

WHAT THE CHOICE CHANGES (bridge): the leader is walked to the hub's flight
point when the family stands in another zone; the family's quest aim is a
quest of that zone the most members hold (`zone_aim`); quest sharing keeps to
that zone (`share_members`). Never a campaign queue entry: an operator's
queued campaign runs first, and this fills around and after it.

PURE MODULE: no MySQL, no clock. Rows in, choices and sentences out.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, replace

import campaignplan
import classic
import council
import flightlearn
import transform

HORDE = "horde"
ALLIANCE = "alliance"

# characters.race -> side. The same sets core.py keeps.
HORDE_RACES = frozenset({2, 5, 6, 8, 10})
ALLIANCE_RACES = frozenset({1, 3, 4, 7, 11})

# AllowableRaces bits of each side, and factiontemplate FactionGroup bits.
RACE_MASK = {HORDE: 2 | 16 | 32 | 128 | 512, ALLIANCE: 1 | 4 | 8 | 64 | 1024}
GROUP_BIT = {HORDE: 4, ALLIANCE: 2}
OTHER = {HORDE: ALLIANCE, ALLIANCE: HORDE}

# A spawn's side in DANGER_SQL: a member of the Alliance, of the Horde, or a
# monster hostile to players (0).
SIDE_MONSTER = 0

# Levels, per the classic ruleset.
LEVEL_CAP = classic.MAX_LEVEL

# The quest window around the weakest member: a quest more than GREEN_BELOW
# under them is nearly grey, one more than ABOVE over them is a wipe for a
# group whose healer is the weakest.
GREEN_BELOW = 5
ABOVE = 3

# A zone with fewer open quests than this for the whole family is done.
MIN_OPEN = 3

# A zone is outgrown when its band tops out this many levels under the weakest.
OUTGROWN = 2

# The band is the PCT_LOW to PCT_HIGH percentile of a zone's quest levels, so
# a stray level-1 or level-60 quest does not stretch it. Read against the dev
# world, 0.1 to 0.9 gives the Barrens 10-25, Stonetalon 18-27, Ashenvale 20-32
# and Thousand Needles 26-41, which is how the zones are played.
PCT_LOW = 0.1
PCT_HIGH = 0.9

# Danger. DANGER_GAP levels over the weakest is a red mob; a zone where
# DANGER_SHARE of the hostile spawns are red is put last. DEATHS_AVOID of the
# family's own deaths inside DEATH_HOURS puts a zone last whatever the spawns
# say. Spawns and towns are counted within DANGER_YARDS of the hub. A town of
# the other side within TOWN_YARDS of the hub refuses it, and TOWN_GUARDS of
# that side's NPCs within TOWN_YARDS of a flight point make it a town rather
# than a lone flight master.
DANGER_GAP = 5
DANGER_SHARE = 0.5
DEATH_HOURS = 24
DEATHS_AVOID = 6
DANGER_YARDS = 2500.0
TOWN_YARDS = 400.0
TOWN_GUARDS = 5

# The spawn grid, in yards.
CELL = 250

# How many options Jev is shown, lowest band first.
MAX_OPTIONS = 6

# The kind, for overseer_jev_judgment and the switches.
KIND = "leveling_zone"

GEO = transform.Geometry.load(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class Hub:
    """One zone a side levels in, by the flight point the family is sent to."""

    key: str
    team: str
    zone_id: int
    zone: str
    name: str
    node: int

    @property
    def point(self):
        """(map, x, y, z) of the hub's flight point, or None."""
        found = next((n for n in flightlearn.NODES if n.id == self.node), None)
        return None if found is None else (found.map_id, found.x, found.y, found.z)

    @property
    def map_id(self) -> int | None:
        point = self.point
        return None if point is None else int(point[0])

    @property
    def friendly(self) -> bool:
        """Whether the client's own taxi table gives this side a master there."""
        found = next((n for n in flightlearn.NODES if n.id == self.node), None)
        if found is None:
            return False
        return bool(found.horde if self.team == HORDE else found.alliance)


# EVERY HUB, by side. Order is only the tie-break; the band comes from the
# quests. Taxi node ids are the client's (taxinodes.json).
HUBS: tuple = (
    Hub("silverpine", HORDE, 130, "Silverpine Forest", "The Sepulcher", 10),
    Hub("barrens", HORDE, 17, "The Barrens", "the Crossroads", 25),
    Hub("stonetalon", HORDE, 406, "Stonetalon Mountains", "Sun Rock Retreat", 29),
    Hub("ashenvale", HORDE, 331, "Ashenvale", "Splintertree Post", 61),
    Hub("hillsbrad", HORDE, 267, "Hillsbrad Foothills", "Tarren Mill", 13),
    Hub("needles", HORDE, 400, "Thousand Needles", "Freewind Post", 30),
    Hub("desolace", HORDE, 405, "Desolace", "Shadowprey Village", 38),
    Hub("arathi", HORDE, 45, "Arathi Highlands", "Hammerfall", 17),
    Hub("stranglethorn", HORDE, 33, "Stranglethorn Vale", "Grom'gol", 20),
    Hub("dustwallow", HORDE, 15, "Dustwallow Marsh", "Brackenwall Village", 55),
    Hub("badlands", HORDE, 3, "Badlands", "Kargath", 21),
    Hub("swamp", HORDE, 8, "Swamp of Sorrows", "Stonard", 56),
    Hub("feralas", HORDE, 357, "Feralas", "Camp Mojache", 42),
    Hub("tanaris", HORDE, 440, "Tanaris", "Gadgetzan", 40),
    Hub("hinterlands", HORDE, 47, "The Hinterlands", "Revantusk Village", 76),
    Hub("azshara", HORDE, 16, "Azshara", "Valormok", 44),
    Hub("searing", HORDE, 51, "Searing Gorge", "Thorium Point", 75),
    Hub("ungoro", HORDE, 490, "Un'Goro Crater", "Marshal's Refuge", 79),
    Hub("felwood", HORDE, 361, "Felwood", "Bloodvenom Post", 48),
    Hub("burning", HORDE, 46, "Burning Steppes", "Flame Crest", 70),
    Hub("winterspring", HORDE, 618, "Winterspring", "Everlook", 53),
    Hub("plaguelands", HORDE, 139, "Eastern Plaguelands", "Light's Hope Chapel", 68),
    Hub("silithus", HORDE, 1377, "Silithus", "Cenarion Hold", 72),
    Hub("westfall", ALLIANCE, 40, "Westfall", "Sentinel Hill", 4),
    Hub("darkshore", ALLIANCE, 148, "Darkshore", "Auberdine", 26),
    Hub("loch-modan", ALLIANCE, 38, "Loch Modan", "Thelsamar", 8),
    Hub("redridge", ALLIANCE, 44, "Redridge Mountains", "Lakeshire", 5),
    Hub("wetlands", ALLIANCE, 11, "Wetlands", "Menethil Harbor", 7),
    Hub("duskwood", ALLIANCE, 10, "Duskwood", "Darkshire", 12),
    Hub("ashenvale-a", ALLIANCE, 331, "Ashenvale", "Astranaar", 28),
    Hub("stonetalon-a", ALLIANCE, 406, "Stonetalon Mountains", "Stonetalon Peak", 33),
    Hub("hillsbrad-a", ALLIANCE, 267, "Hillsbrad Foothills", "Southshore", 14),
    Hub("arathi-a", ALLIANCE, 45, "Arathi Highlands", "Refuge Pointe", 16),
    Hub("desolace-a", ALLIANCE, 405, "Desolace", "Nijel's Point", 37),
    Hub("stranglethorn-a", ALLIANCE, 33, "Stranglethorn Vale", "Booty Bay", 19),
    Hub("dustwallow-a", ALLIANCE, 15, "Dustwallow Marsh", "Theramore", 32),
    Hub("feralas-a", ALLIANCE, 357, "Feralas", "Thalanaar", 31),
    Hub("tanaris-a", ALLIANCE, 440, "Tanaris", "Gadgetzan", 39),
    Hub("hinterlands-a", ALLIANCE, 47, "The Hinterlands", "Aerie Peak", 43),
    Hub("azshara-a", ALLIANCE, 16, "Azshara", "Talrendis Point", 64),
    Hub("searing-a", ALLIANCE, 51, "Searing Gorge", "Thorium Point", 74),
    Hub("ungoro-a", ALLIANCE, 490, "Un'Goro Crater", "Marshal's Refuge", 79),
    Hub("felwood-a", ALLIANCE, 361, "Felwood", "Talonbranch Glade", 65),
    Hub("burning-a", ALLIANCE, 46, "Burning Steppes", "Morgan's Vigil", 71),
    Hub("western-plague-a", ALLIANCE, 28, "Western Plaguelands", "Chillwind Camp", 66),
    Hub("winterspring-a", ALLIANCE, 618, "Winterspring", "Everlook", 52),
    Hub(
        "plaguelands-a", ALLIANCE, 139, "Eastern Plaguelands", "Light's Hope Chapel", 67
    ),
    Hub("silithus-a", ALLIANCE, 1377, "Silithus", "Cenarion Hold", 73),
)

BY_KEY = {hub.key: hub for hub in HUBS}
ZONES = tuple(sorted({hub.zone_id for hub in HUBS}))


def hubs_for(team: str) -> tuple:
    return tuple(h for h in HUBS if h.team == team)


def team_of(level_rows) -> str:
    """The family's side from its races, or "" when they disagree or are unread."""
    sides = set()
    for row in level_rows or ():
        try:
            race = int(row.get("race") or 0)
        except (TypeError, ValueError):
            continue
        if race in HORDE_RACES:
            sides.add(HORDE)
        elif race in ALLIANCE_RACES:
            sides.add(ALLIANCE)
    return sides.pop() if len(sides) == 1 else ""


# --- the reads -----------------------------------------------------------
#
# S608 on the two statements below: the only interpolated parts are this
# module's own integer constants (ZONES, CELL, classic.CLASSIC_CONTINENTS).

QUESTS_SQL = (
    "SELECT t.ID AS quest, t.QuestSortID AS zone, t.QuestLevel AS level, "  # noqa: S608
    "t.MinLevel AS min_level, t.AllowableRaces AS races, "
    "COALESCE(a.AllowableClasses, 0) AS classes "
    "FROM acore_world.quest_template t "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = t.ID "
    "WHERE t.QuestSortID IN (" + ", ".join(str(int(z)) for z in ZONES) + ") "
    "AND t.QuestLevel > 0 AND t.LogTitle NOT LIKE '<%%'"
)

DANGER_SQL = (
    "SELECT c.map AS map_id, ROUND(c.position_x / " + str(int(CELL)) + ") AS cx, "  # noqa: S608
    "ROUND(c.position_y / " + str(int(CELL)) + ") AS cy, ct.minlevel AS level, "
    "(ct.`rank` IN (1, 2)) AS elite, "
    "CASE WHEN (ft.FactionGroup & 2) THEN 2 WHEN (ft.FactionGroup & 4) THEN 4 "
    "ELSE 0 END AS side, COUNT(*) AS n "
    "FROM acore_world.creature c "
    "JOIN acore_world.creature_template ct ON ct.entry = c.id "
    "JOIN acore_world.factiontemplate_dbc ft ON ft.ID = ct.faction "
    "WHERE c.map IN ("
    + ", ".join(str(int(m)) for m in classic.CLASSIC_CONTINENTS)
    + ") AND (ft.EnemyGroup & 7) > 0 GROUP BY 1, 2, 3, 4, 5, 6"
)

DEATHS_SQL = (
    "SELECT zone, COUNT(*) AS n FROM overseer_death "
    "WHERE character_name IN ({holes}) "
    "AND created_at > NOW() - INTERVAL %s HOUR GROUP BY zone"
)

HELD_SQL = (
    "SELECT c.name, q.quest FROM character_queststatus q "
    "JOIN characters c ON c.guid = q.guid WHERE c.name IN ({holes})"
)

MEMBERS_SQL = (
    "SELECT name, level, race, class, map AS map_id FROM characters "
    "WHERE name IN ({holes})"
)


def by_name(rows, column: str) -> dict:
    """name -> frozenset of `column` off (name, value) rows."""
    out: dict = {}
    for row in rows or ():
        out.setdefault(str(row.get("name") or ""), set()).add(int(row[column]))
    return {k: frozenset(v) for k, v in out.items()}


def deaths(rows) -> dict:
    """zone id -> the family's deaths there in the window."""
    return {int(r.get("zone") or 0): int(r.get("n") or 0) for r in rows or ()}


# --- the world, once -----------------------------------------------------


@dataclass(frozen=True)
class Cell:
    """A group of spawns: where, how high, elite or not, whose side."""

    map_id: int
    x: float
    y: float
    level: int
    elite: bool
    side: int
    n: int


def cells(rows) -> tuple:
    """DANGER_SQL's rows as Cells at their cell's centre."""
    out = []
    for row in rows or ():
        try:
            map_id = int(row["map_id"])
            x = float(row["cx"]) * CELL
            y = float(row["cy"]) * CELL
        except (KeyError, TypeError, ValueError):
            continue
        out.append(
            Cell(
                map_id=map_id,
                x=x,
                y=y,
                level=int(row.get("level") or 0),
                elite=bool(int(row.get("elite") or 0)),
                side=int(row.get("side") or 0),
                n=int(row.get("n") or 0),
            )
        )
    return tuple(out)


def hostile_to(cell: Cell, team: str) -> bool:
    return cell.side in (SIDE_MONSTER, GROUP_BIT[OTHER[team]])


def _near(map_id, x, y, point, yards: float) -> bool:
    return (
        point is not None
        and int(map_id) == int(point[0])
        and math.hypot(float(x) - point[1], float(y) - point[2]) <= yards
    )


def towns(team: str, spawns) -> tuple:
    """The other side's towns on the two continents: (name, zone, map, x, y).

    A town is a flight point the client gives only the other side, with at
    least TOWN_GUARDS of that side's NPCs within TOWN_YARDS. A lone flight
    master in the wild is not a town anybody walks into by accident. The zone
    is the client's own, off the node's name ("Astranaar, Ashenvale"), because
    zones.json's rectangles overlap too much to place a point.
    """
    bit = GROUP_BIT[OTHER[team]]
    theirs_near = [c for c in spawns or () if c.side == bit]
    out = []
    seen = set()
    for node in flightlearn.NODES:
        named = _their_town_node(node, team)
        if named is None:
            continue
        name, zone = named
        point = (node.map_id, node.x, node.y)
        guards = sum(
            c.n for c in theirs_near if _near(c.map_id, c.x, c.y, point, TOWN_YARDS)
        )
        if guards >= TOWN_GUARDS and name not in seen:
            seen.add(name)
            out.append((name, zone, node.map_id, node.x, node.y))
    return tuple(out)


def _their_town_node(node, team: str):
    """(town, zone) off a flight point only the other side has on a classic
    continent, or None. Quest, transport and test nodes are not towns."""
    mine = node.horde if team == HORDE else node.alliance
    theirs = node.alliance if team == HORDE else node.horde
    if mine or not theirs or node.map_id not in classic.CLASSIC_CONTINENTS:
        return None
    if not (node.x or node.y) or "," not in node.name:
        return None
    name, zone = (part.strip() for part in node.name.split(",", 1))
    if name.lower().startswith(("quest", "transport", "generic")):
        return None
    return name, zone


def towns_in(hub: "Hub", found) -> tuple:
    """The names of `found` towns in the hub's zone, by the client's name."""
    zone = hub.zone.lower()
    return tuple(t[0] for t in found if t[1].lower() in zone)


def towns_beside(hub: "Hub", found) -> tuple:
    """The names of `found` towns within TOWN_YARDS of the hub's flight point."""
    return tuple(t[0] for t in found if _near(t[2], t[3], t[4], hub.point, TOWN_YARDS))


def _percentile(values: list, fraction: float) -> int:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return int(ordered[index])


def side_quests(quest_rows, team: str) -> tuple:
    """The quests this side can take: race mask open to it, no class lock."""
    mask = RACE_MASK[team]
    out = []
    for row in quest_rows or ():
        races = int(row.get("races") or 0)
        if races and not races & mask:
            continue
        if int(row.get("classes") or 0):
            continue
        if int(row.get("zone") or 0) <= 0 or int(row.get("level") or 0) <= 0:
            continue
        out.append(row)
    return tuple(out)


def bands(quest_rows, team: str) -> dict:
    """zone id -> (floor, ceiling, quest count) off the side's quest levels."""
    levels: dict = {}
    for row in side_quests(quest_rows, team):
        levels.setdefault(int(row["zone"]), []).append(int(row["level"]))
    return {
        zone: (
            _percentile(found, PCT_LOW),
            min(_percentile(found, PCT_HIGH), LEVEL_CAP),
            len(found),
        )
        for zone, found in levels.items()
    }


def here_of(spot) -> tuple | None:
    """(map, zone id, x, y) off one overseer_snapshot row, or None."""
    spot = spot or {}
    if spot.get("pos_x") is None or spot.get("pos_y") is None:
        return None
    return (
        int(spot.get("map_id") or 0),
        int(spot.get("zone_id") or 0),
        float(spot["pos_x"]),
        float(spot["pos_y"]),
    )


# The words for who made a recorded choice, by overseer_jev_judgment.acted.
CHOOSERS = {"jev": "Jev", "both": "Jev and the heuristic, agreeing"}
HEURISTIC_CHOOSER = "the heuristic"


def recorded_choice(row) -> tuple:
    """(hub key, who chose it) off the latest leveling_zone judgment row, or
    ("", "") for none. The hub carried out: Jev's where it acted, else the
    heuristic's."""
    if not row:
        return "", ""
    acted = str(row.get("acted") or "")
    key = row.get("jev") if acted == "jev" else row.get("heuristic")
    return str(key or ""), CHOOSERS.get(acted, HEURISTIC_CHOOSER)


# --- the facts -----------------------------------------------------------


@dataclass(frozen=True)
class Facts:
    """Everything one choice is made from, for one family.

    members   each member's name, level, race and class
    here      the leader's (map, zone id, x, y) off the snapshot, or None
    zones     name -> zone id each member stands in (snapshot)
    quests    QUESTS_SQL rows, or None when unread
    rewarded  name -> quest ids rewarded
    held      name -> quest ids in the log
    spawns    Cells, or None when unread
    deaths    zone id -> the family's deaths in DEATH_HOURS, or None
    gear      name -> (mean worn item level, empty slots), or None
    """

    family: str
    members: tuple
    here: tuple | None = None
    zones: dict | None = None
    quests: tuple | None = None
    rewarded: dict | None = None
    held: dict | None = None
    spawns: tuple | None = None
    deaths: dict | None = None
    gear: dict | None = None

    @property
    def team(self) -> str:
        return team_of(self.members)

    @property
    def weakest(self) -> tuple:
        known = [
            (int(m.get("level") or 0), str(m.get("name") or ""))
            for m in self.members
            if str(m.get("name") or "") and int(m.get("level") or 0) > 0
        ]
        if not known:
            return "", 0
        level, name = min(known)
        return name, level


@dataclass(frozen=True)
class Option:
    """One hub the family could level at now."""

    key: str
    zone_id: int
    zone: str
    hub: str
    floor: int
    ceiling: int
    ready: bool
    open: int
    done: int
    held: int
    held_by_all: int
    above: int
    hostile: int
    elites: int
    towns: tuple
    deaths: int | None
    yards: int | None
    here: bool
    order: int

    @property
    def heavy(self) -> bool:
        """Put last: the family keeps dying here, or most of it is red."""
        if self.deaths is not None and self.deaths >= DEATHS_AVOID:
            return True
        return bool(self.hostile) and self.above / self.hostile >= DANGER_SHARE

    @property
    def place(self) -> str:
        return "%s (%s)" % (self.zone, self.hub)


def _allowed(row, member) -> bool:
    races = int(row.get("races") or 0)
    bit = 1 << (int(member.get("race") or 1) - 1)
    return (not races or bool(races & bit)) and int(member.get("level") or 0) >= int(
        row.get("min_level") or 0
    )


def zone_work(facts: Facts, zone_id: int, level: int) -> tuple:
    """(open, done) quests in a zone for the family, at the weakest's `level`.

    open  every member can take it, it is inside the window around `level`,
          and the weakest member has not been rewarded for it
    done  quests of the zone any member has been rewarded for
    """
    team = facts.team
    if not team or facts.quests is None:
        return 0, 0
    rewarded = facts.rewarded or {}
    who, _level = facts.weakest
    theirs = rewarded.get(who, frozenset())
    anyone = frozenset().union(*rewarded.values()) if rewarded else frozenset()
    opened = done = 0
    for row in side_quests(facts.quests, team):
        if int(row["zone"]) != int(zone_id):
            continue
        qid = int(row["quest"])
        if qid in anyone:
            done += 1
        if qid in theirs:
            continue
        qlevel = int(row["level"])
        if not level - GREEN_BELOW <= qlevel <= level + ABOVE:
            continue
        if int(row.get("min_level") or 0) > level:
            continue
        if all(_allowed(row, m) for m in facts.members):
            opened += 1
    return opened, done


def _held(facts: Facts, zone_id: int) -> tuple:
    """(quests of the zone somebody holds, those every member holds)."""
    if facts.quests is None or not facts.held:
        return 0, 0
    ids = {int(r["quest"]) for r in facts.quests if int(r["zone"]) == int(zone_id)}
    logs = [facts.held.get(str(m.get("name")), frozenset()) for m in facts.members]
    somebody = {q for log in logs for q in log} & ids
    everyone = set(ids)
    for log in logs:
        everyone &= set(log)
    return len(somebody), len(everyone)


def _danger(facts: Facts, hub: Hub, level: int) -> tuple:
    """(hostile spawns DANGER_GAP over `level`, hostile spawns, hostile elites
    at or over `level`) within DANGER_YARDS of the hub."""
    above = hostile = elites = 0
    point = hub.point
    for c in facts.spawns or ():
        if not hostile_to(c, facts.team) or not _near(
            c.map_id, c.x, c.y, point, DANGER_YARDS
        ):
            continue
        hostile += c.n
        if c.level >= level + DANGER_GAP:
            above += c.n
        if c.elite and c.level >= level:
            elites += c.n
    return above, hostile, elites


def _yards(facts: Facts, hub: Hub) -> int | None:
    point = hub.point
    if facts.here is None or point is None:
        return None
    map_id, _zone, x, y = facts.here
    if int(map_id) != int(point[0]):
        return None
    return int(math.hypot(float(x) - point[1], float(y) - point[2]))


def _continent(map_id) -> int | None:
    return council.continent_of(map_id)


def _crossing_blocked() -> bool:
    import crossing

    return crossing.first_blocked_leg() is not None


def _refusal(facts: Facts, hub: Hub, band, level: int, home, near) -> str:
    """Why one hub is not offered at `level`, or ""."""
    who = facts.weakest[0] or "the weakest"
    if not hub.friendly or hub.point is None:
        return "no %s flight master stands there" % hub.team
    if band is None:
        return "no quest there is one the %s can take" % hub.team
    if band[0] > level + council.NEAR_ENOUGH:
        return "too high: its quests start at %d and %s is %d" % (band[0], who, level)
    if band[1] < level - OUTGROWN:
        return "outgrown: its quests top out at %d" % band[1]
    if home is not None and _continent(hub.map_id) != home and _crossing_blocked():
        return "on another continent, and the crossing cannot be made yet"
    beside = towns_beside(hub, near)
    if beside:
        return "its flight point stands beside %s" % ", ".join(beside)
    opened, _done = zone_work(facts, hub.zone_id, level)
    if facts.quests is not None and opened < MIN_OPEN:
        return "done: %d quest%s left there for the family at %d" % (
            opened,
            "" if opened == 1 else "s",
            level,
        )
    return ""


def refusals(facts: Facts, level: int | None = None) -> dict:
    """Hub key -> why it is not offered, for every hub of the family's side."""
    team = facts.team
    if not team:
        return {}
    level = facts.weakest[1] if level is None else int(level)
    found = bands(facts.quests or (), team)
    near = towns(team, facts.spawns or ())
    home = _continent(facts.here[0]) if facts.here else None
    out = {}
    for hub in hubs_for(team):
        why = _refusal(facts, hub, found.get(hub.zone_id), level, home, near)
        if why:
            out[hub.key] = why
    return out


def options(facts: Facts, level: int | None = None) -> list:
    """Every hub the family could level at, lowest band first."""
    team = facts.team
    _who, weakest = facts.weakest
    level = weakest if level is None else int(level)
    if not team or not level or level >= LEVEL_CAP or facts.quests is None:
        return []
    refused = refusals(facts, level)
    found = bands(facts.quests, team)
    near = towns(team, facts.spawns or ())
    here_zone = int(facts.here[1] or 0) if facts.here else 0
    out = []
    for order, hub in enumerate(hubs_for(team)):
        if hub.key in refused:
            continue
        floor, ceiling, _count = found[hub.zone_id]
        opened, done = zone_work(facts, hub.zone_id, level)
        held, everyone = _held(facts, hub.zone_id)
        above, hostile, elites = _danger(facts, hub, level)
        out.append(
            Option(
                key=hub.key,
                zone_id=hub.zone_id,
                zone=hub.zone,
                hub=hub.name,
                floor=floor,
                ceiling=ceiling,
                ready=level >= floor,
                open=opened,
                done=done,
                held=held,
                held_by_all=everyone,
                above=above,
                hostile=hostile,
                elites=elites,
                towns=towns_in(hub, near),
                deaths=None
                if facts.deaths is None
                else int(facts.deaths.get(hub.zone_id, 0)),
                yards=_yards(facts, hub),
                here=here_zone == hub.zone_id,
                order=order,
            )
        )
    out.sort(key=lambda o: (o.floor, o.order))
    return out[:MAX_OPTIONS]


def heuristic(opts: list) -> Option | None:
    """The hub a group of players would pick. See the module docstring."""
    if not opts:
        return None
    return min(opts, key=lambda o: (o.heavy, not o.ready, o.floor, o.order))


def heuristic_why(pick: Option) -> str:
    return (
        "the lowest band with work left: %d open quests for the family at "
        "levels %d to %d%s"
        % (
            pick.open,
            pick.floor,
            pick.ceiling,
            "" if not pick.heavy else ", though the family has been dying there",
        )
    )


# --- what the choice changes ---------------------------------------------


def zone_aim(facts: Facts, zone_id: int, skip=()) -> tuple:
    """(quest id, holders) for the family's quest aim inside the chosen zone,
    or (0, ()) when nobody holds one of its quests.

    The quest the most members hold, so the kills pay the most of them; then
    the lowest quest level, so the weakest is not dragged to a red one; then
    the id. A quest over the window (ABOVE the weakest) is not aimed, and
    `skip` names quests whose aim was released unhanded-in.
    """
    if facts.quests is None or not facts.held:
        return 0, ()
    _who, level = facts.weakest
    levels = {
        int(r["quest"]): int(r["level"])
        for r in facts.quests
        if int(r["zone"]) == int(zone_id)
    }
    holders: dict = {}
    for m in facts.members:
        name = str(m.get("name") or "")
        for qid in facts.held.get(name, ()):
            if qid in levels and qid not in skip and levels[qid] <= level + ABOVE:
                holders.setdefault(qid, []).append(name)
    if not holders:
        return 0, ()
    qid = min(holders, key=lambda q: (-len(holders[q]), levels[q], q))
    return qid, tuple(sorted(holders[qid]))


def share_members(members, zone_id: int) -> list:
    """questbook Members held to the chosen zone, so a share outside it is
    refused as ELSEWHERE by questbook.blockers."""
    return [replace(m, zones=frozenset({int(zone_id)})) for m in members]


def walk_aim(hub: Hub) -> tuple | None:
    """(map, x, y, z) the leader is walked to."""
    return hub.point


# --- the route, for the page ---------------------------------------------

BAND_WIDTH = 10

# Class quests and trainer rank milestones worth a line, by class id and level.
MILESTONES = {
    1: (
        (10, "Defensive Stance (class quest)"),
        (30, "Whirlwind Axe (class quest)"),
        (40, "Shield Slam (protection talent)"),
    ),
    7: ((20, "Water totem (class quest)"), (30, "Air totem (class quest)")),
    11: (
        (10, "Bear Form (class quest)"),
        (16, "Aquatic Form (class quest)"),
        (20, "Cat Form (trainer)"),
    ),
    3: ((10, "tame a pet (class quest)"),),
    9: (
        (10, "Voidwalker (class quest)"),
        (20, "Succubus (class quest)"),
        (30, "Felhunter (class quest)"),
    ),
}
MOUNT_LEVEL = 40


def milestones(members, low: int, high: int) -> list:
    """Sentences for the class quests, the mount and the trainer between two
    levels, for these members."""
    out = []
    for m in members:
        name = str(m.get("name") or "")
        for at, what in MILESTONES.get(int(m.get("class") or 0), ()):
            if low <= at <= high and int(m.get("level") or 0) < at:
                out.append("%s at %d: %s" % (name, at, what))
    if low <= MOUNT_LEVEL <= high and any(
        int(m.get("level") or 0) < MOUNT_LEVEL for m in members
    ):
        out.append("everyone at %d: riding and a mount" % MOUNT_LEVEL)
    return out


def dungeons(level_rows, low: int, high: int, level: int = 0) -> list:
    """The dungeons of a band the family may be sent to (council.door_refusal
    with the level taken as met): those whose doors open inside [low, high],
    and, with `level`, those opening below it that `level` has not outgrown."""
    out = []
    for run in campaignplan.RUNS:
        opens = low <= run.floor <= high
        still = bool(level) and run.floor < low and run.ceiling >= level
        if not (opens or still):
            continue
        rows = [dict(r, level=max(run.floor, 1)) for r in level_rows]
        if council.door_refusal(run.keyword, rows):
            continue
        out.append("%s %d-%d" % (run.place, run.floor, run.ceiling))
    return out


def route(facts: Facts) -> list:
    """The route from the weakest member's level to the cap, by band:
    [{"band", "zones", "dungeons", "milestones"}]. Each hub sits in the band
    its quests start in, or the first band when it starts below the weakest
    member and is not outgrown. A forecast, not a promise: Jev may choose
    differently when it is asked."""
    team = facts.team
    _who, level = facts.weakest
    if not team or not level or facts.quests is None or level >= LEVEL_CAP:
        return []
    found = bands(facts.quests, team)
    near = towns(team, facts.spawns or ())
    home = _continent(facts.here[0]) if facts.here else None
    start = (level // BAND_WIDTH) * BAND_WIDTH
    placed: dict = {}
    for hub in hubs_for(team):
        band = found.get(hub.zone_id)
        if band is None or not hub.friendly or band[1] < level - OUTGROWN:
            continue
        low = (max(band[0], start) // BAND_WIDTH) * BAND_WIDTH
        placed.setdefault(low, []).append(
            {
                "key": hub.key,
                "zone": hub.zone,
                "hub": hub.name,
                "levels": "%d-%d" % (band[0], band[1]),
                "floor": band[0],
                "away": home is not None and _continent(hub.map_id) != home,
                "towns": list(towns_in(hub, near)),
            }
        )
    out = []
    for low in range(start, LEVEL_CAP, BAND_WIDTH):
        high = min(low + BAND_WIDTH - 1, LEVEL_CAP)
        zones = sorted(placed.get(low, []), key=lambda z: (z["away"], z["floor"]))
        out.append(
            {
                "band": "%d-%d" % (max(low, level), high),
                "zones": zones,
                "dungeons": dungeons(
                    list(facts.members),
                    max(low, level),
                    high,
                    level if low == start else 0,
                ),
                "milestones": milestones(facts.members, max(low, level), high),
            }
        )
    return out


def zone_name(zone_id) -> str:
    """A zone's name: a hub's, a dungeon's, the rectangles', or "somewhere"."""
    zone_id = int(zone_id or 0)
    for hub in HUBS:
        if hub.zone_id == zone_id:
            return hub.zone
    for run in campaignplan.RUNS:
        if run.zone == zone_id:
            return run.place
    return GEO.zone_by_id(zone_id) or "somewhere this page cannot place"


def where_line(facts: Facts) -> str:
    """Where the family stands, grouped by zone."""
    grouped: dict = {}
    for name, zone_id in sorted((facts.zones or {}).items()):
        grouped.setdefault(zone_name(zone_id), []).append(name)
    if not grouped:
        return "Where we are: nobody's position can be read."
    parts = [
        "%s in %s" % (", ".join(names), zone) for zone, names in sorted(grouped.items())
    ]
    return "Where we are: %s." % "; ".join(parts)


def next_after(facts: Facts, now: Option) -> tuple:
    """(Option, level) the family moves on to once `now` is outgrown."""
    _who, level = facts.weakest
    at = max(level, now.ceiling + OUTGROWN + 1)
    if at >= LEVEL_CAP:
        return None, at
    later = [o for o in options(facts, at) if o.key != now.key]
    return heuristic(later), at


def page_view(facts: Facts, chosen: str = "", chooser: str = "") -> dict:
    """The Family tab's leveling block: where we are, where next, the route.

    `chosen` is the hub the bridge last chose (off overseer_jev_judgment) and
    `chooser` who chose it; without one the heuristic's pick is shown.
    """
    _who, level = facts.weakest
    where = where_line(facts)
    if not level:
        return {
            "where": where,
            "now": "Nobody's level can be read.",
            "next": "",
            "route": [],
            "refused": {},
        }
    if level >= LEVEL_CAP:
        return {
            "where": where,
            "now": "At the level cap: no leveling zone.",
            "next": "",
            "route": [],
            "refused": {},
        }
    opts = options(facts)
    pick = heuristic(opts)
    now_opt = next((o for o in opts if o.key == chosen), None) or pick
    if now_opt is None:
        now = "Leveling zone: none open for a family whose weakest is %d." % level
    else:
        who = chooser if now_opt.key == chosen and chooser else "the heuristic"
        now = "Leveling zone: %s, levels %d-%d, %d open quests; chosen by %s." % (
            now_opt.place,
            now_opt.floor,
            now_opt.ceiling,
            now_opt.open,
            who,
        )
    nxt = ""
    if now_opt is not None:
        after, at = next_after(facts, now_opt)
        if after is not None:
            nxt = "Next: %s at about level %d." % (after.place, at)
    return {
        "where": where,
        "now": now,
        "next": nxt,
        "route": route(facts),
        "refused": refusals(facts),
    }


def line(family: str, pick: Option, chooser: str, why: str) -> str:
    """The log line for a chosen zone."""
    return (
        "levelroute: family=%s chose zone %s (%s, levels %d-%d, open=%d "
        "deaths=%s towns=%s) by %s because %s"
        % (
            family,
            pick.key,
            pick.place,
            pick.floor,
            pick.ceiling,
            pick.open,
            "?" if pick.deaths is None else pick.deaths,
            ",".join(pick.towns) or "-",
            chooser,
            why,
        )
    )
