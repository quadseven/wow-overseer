"""Where a guild member levels: out of a zone it has outgrown, to a quest hub.

WHY THIS EXISTS. Measured on the dev realm on 2026-10-05: natural guild members
never left their starting zones. mod-playerbots' random level teleport is
skipped for a natural guild member ("keeps its own kit - random teleport
skipped"), which is right, since a teleport is not a player's verb. But nothing
walked them anywhere instead, so Cave's priests stood at levels 14 and 15 with
19 to 23 days played in Azuremyst Isle, Elwynn Forest, Dun Morogh and
Darnassus, where every mob was grey. They never reached 17, the dungeon
finder's floor, and Cave's guild groups never formed.

WHAT A PLAYER DOES. Leaves the zone once its quests turn grey and goes to the
next zone of its level. This is that walk for one guild member: to the flight
master of the lowest quest hub of its side whose band fits its level, on its
own continent. There its own quest and grind AI works. Nothing is granted and
nothing is teleported: the walk is the module's `walk-to-spawn creature:`, at
the far cap, mounted and by the flight paths the member knows.

OUTGROWN (`outgrown`). A member has outgrown where it stands when:

  * it stands on Outland ground (map 530) outside the Draenei and Blood Elf
    starting lands, outside the classic world (classic.py);
  * it stands in a zone where its side has no quest band: a capital, a starting
    zone, or any zone that is not one of levelroute's hubs or starting-land
    hubs;
  * its level is above the zone's band ceiling.

An unread zone (no fresh snapshot) is not judged, and neither is any map other
than the two continents and 530 (a dungeon, a battleground). In the starting
lands (classic.is_starting_land) a member is judged as on a continent: Azuremyst
Isle, Eversong Woods and the two capitals have no band, and Bloodmyst Isle and
the Ghostlands have their own (levelroute.STARTING_LAND_HUBS).

WHICH HUB (`choose`). levelroute's HUBS and levelroute's bands, never a second
table. A hub fits a level when its band's ceiling is at or above the level (so
the member is not outgrown the moment it arrives) and its floor is at most
council.NEAR_ENOUGH above it. Of the hubs that fit, the lowest band first, then
levelroute's own order. Only a hub on the member's own map: the module refuses a
spawn on another map than the walker's. A far walk starts on the two classic
continents and in the starting lands (mod-overseer#765), so a member standing
in the starting lands is offered their second zone's hub as well: Blood Watch
on Bloodmyst Isle for the Alliance, Tranquillien in the Ghostlands for the
Horde, which is where a Draenei or a Blood Elf player goes from 10 to 20.

LEAVING MAP 530 (`EXITS`, `BOAT_EXITS`). A Draenei leaves by the boat from
Valaar's Berth on Azuremyst Isle to Auberdine in Darkshore; a Blood Elf by the
Orb of Translocation in Silvermoon City to the Undercity. walk-to-spawn refuses
a spawn on another map, so the Draenei's way is the module's `cross-to-map
map:<id>` row (classquest.CROSSING_VERB): the member walks to its own side's
berth, waits for Elune's Blessing, rides it and walks off at Auberdine. A
member past its starting lands is sent that way when a hub on the boat's far
side fits its level (`Choice.cross_to`), and walks on to that hub from the
landing on a later pass. Measured on the dev realm on 2026-10-10: Cave's
Draenei at 22 to 26 stood on Bloodmyst and Azuremyst Isles with no level row
in a day, every pass refusing them with "no row takes it". No row uses an orb,
so a Blood Elf past its starting lands, or a member whose continent has no hub
that fits, is still named in the pass's notes with the hub it would go to and
the way there, and left where it stands.

WHERE THE WALK ENDS (`hub_masters`). The hub's flight master: the flight-master
spawn of the world's creature table nearest the hub's taxi node, within
travel.FLIGHT_NODE_MATCH_YARDS, whose faction does not attack the hub's side.
The row names that spawn by its id, so the place walked to is a spawn row of the
world and never a coordinate computed here.

PURE MODULE: rows in, choices and sentences out. No MySQL, no clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import classic
import council
import levelroute
import situation
import travel

# The step's action word, in the command log's source (guildjobs.source_for).
ACTION = "level"

# A level walk is asked of one member at most this often. A walk takes up to
# half an hour (guildroute.FAR_WALK_FOLLOW_SECONDS), and the module allows two
# far walks per bot per hour.
COOLDOWN_MINUTES = 120

# New level walks one guild starts in one pass, beside guildjobs' other
# allowances: the realm runs at most four far walks at once.
STEPS_PER_GUILD = 2

# A member this near the chosen hub's flight master is there already, whatever
# the zone reading says (it lags the position by a snapshot).
ARRIVED_YARDS = 400.0

# At the cap there is nothing left to level.
LEVEL_CAP = levelroute.LEVEL_CAP

# A flight master belongs to a hub's node within this many yards of it.
MASTER_YARDS = float(travel.FLIGHT_NODE_MATCH_YARDS)

# The way off map 530 a player of each side takes, for the note. Named, never
# walked: no row the bridge writes boards a boat or uses an orb.
EXITS = {
    levelroute.ALLIANCE: "the boat from Valaar's Berth on Azuremyst Isle to "
    "Auberdine in Darkshore",
    levelroute.HORDE: "the Orb of Translocation in Silvermoon City to the Undercity",
}

# The map a side's own boat off map 530 lands on: Elune's Blessing (world
# transport 181646) from Valaar's Berth to Auberdine on Kalimdor. The Horde's
# way is an orb, which no row uses, so it has none.
BOAT_EXITS = {levelroute.ALLIANCE: 1}

# The source action of the level step's crossing row (guildjobs.source_for),
# apart from the walk's so that the walk's cooldown never reads it.
CROSS_ACTION = ACTION + "-cross"


@dataclass(frozen=True)
class HubMaster:
    """A hub's flight master: its creature spawn id and where it stands."""

    spawn: int
    map_id: int
    x: float
    y: float
    name: str = ""


@dataclass(frozen=True)
class Choice:
    """The hub a member is sent to, or why it is not sent.

    A non-empty `refused` means `master` is None. `hub` and `band` may still
    name the hub it would go to, for the note. `cross_to` set means the member
    first crosses to that map by its side's boat (BOAT_EXITS), with `master`
    None: `hub` is where it levels once it has landed.
    """

    hub: levelroute.Hub | None = None
    band: tuple | None = None
    master: HubMaster | None = None
    refused: str = ""
    cross_to: int | None = None

    @property
    def place(self) -> str:
        if self.hub is None:
            return ""
        return "%s in %s" % (self.hub.name, self.hub.zone)


def side_of(race) -> str:
    """levelroute's side for one race, or "" when unknown."""
    return levelroute.team_of([{"race": race}])


def hub_masters(rows) -> dict:
    """hub key -> HubMaster off the world's flight-master spawn rows.

    `rows` carry guid, map_id, x, y, name and enemy_group (the faction
    template's EnemyGroup, None when the template is unread). For each hub the
    nearest spawn to its taxi node within MASTER_YARDS whose faction does not
    attack the hub's side; a hub with none is left out, so it is never chosen.
    """
    spawns = []
    for row in rows or ():
        try:
            spawns.append(
                (
                    HubMaster(
                        spawn=int(row["guid"]),
                        map_id=int(row["map_id"]),
                        x=float(row["x"]),
                        y=float(row["y"]),
                        name=str(row.get("name") or ""),
                    ),
                    row.get("enemy_group"),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    out = {}
    for hub in levelroute.HUBS + levelroute.STARTING_LAND_HUBS:
        point = hub.point
        if point is None:
            continue
        side = (
            situation.ALLIANCE_MASK
            if hub.team == levelroute.ALLIANCE
            else (situation.HORDE_MASK)
        )
        best = None
        for master, enemy in spawns:
            if master.map_id != int(point[0]):
                continue
            if situation.hostile(enemy, side) is True:
                continue
            yards = math.hypot(master.x - point[1], master.y - point[2])
            if yards > MASTER_YARDS:
                continue
            if best is None or (yards, master.spawn) < best[0]:
                best = ((yards, master.spawn), master)
        if best is not None:
            out[hub.key] = best[1]
    return out


def outgrown(level, race, map_id, zone_id, bands) -> str:
    """Why a member has outgrown where it stands, or "" when it has not or
    where it stands cannot be judged.

    `bands` is levelroute.bands for the member's side: zone id -> (floor,
    ceiling, quest count).
    """
    if map_id is None:
        return ""
    starting = classic.is_starting_land(map_id, zone_id)
    if classic.is_expansion_map(map_id) and not starting:
        return classic.outside_note("it", map_id)
    if int(map_id) not in classic.CLASSIC_CONTINENTS and not starting:
        return ""
    if not zone_id:
        return ""
    zone = levelroute.zone_name(zone_id)
    band = (bands or {}).get(int(zone_id))
    if band is None:
        return (
            "its side has no quest band in %s (a capital, a starting zone or no hub)"
            % (zone)
        )
    if int(level) > int(band[1]):
        return "it has outgrown %s, whose quests top out at %d" % (zone, band[1])
    return ""


def fits(band, level) -> bool:
    """A band a member of `level` may be sent to: not outgrown, not too high."""
    if band is None:
        return False
    return int(band[1]) >= int(level) and int(band[0]) <= int(level) + int(
        council.NEAR_ENOUGH
    )


def hubs_from(team, map_id, zone_id) -> tuple:
    """The hubs a member of `team` standing at (map, zone) may be sent to:
    levelroute's, and its side's starting-land hub while it stands in the
    starting lands."""
    hubs = levelroute.hubs_for(team)
    if classic.is_starting_land(map_id, zone_id):
        hubs += tuple(h for h in levelroute.STARTING_LAND_HUBS if h.team == team)
    return hubs


def choose(level, race, map_id, bands, masters, zone_id=None) -> Choice:
    """The hub a member of this level and race is walked to from `map_id`.

    The lowest band of its side that fits, then levelroute's order, among the
    hubs with a known flight master (`hubs_from`). Only on its own map, or,
    from map 530, on the map its side's boat lands on (`Choice.cross_to`); see
    the module docstring.
    """
    team = side_of(race)
    if not team:
        return Choice(refused="its side cannot be read off its race")
    level = int(level)
    fitting = []
    for order, hub in enumerate(hubs_from(team, map_id, zone_id)):
        band = (bands or {}).get(hub.zone_id)
        if not hub.friendly or not fits(band, level):
            continue
        master = (masters or {}).get(hub.key)
        if master is None:
            continue
        fitting.append((int(band[0]), order, hub, band, master))
    if not fitting:
        return Choice(refused="no %s hub fits level %d" % (team, level))
    fitting.sort(key=lambda f: f[:2])
    home = [f for f in fitting if map_id is not None and f[4].map_id == int(map_id)]
    if home:
        _floor, _order, hub, band, master = home[0]
        return Choice(hub=hub, band=band, master=master)
    boat = BOAT_EXITS.get(team) if classic.is_expansion_map(map_id) else None
    landed = [f for f in fitting if boat is not None and f[4].map_id == boat]
    if landed:
        _floor, _order, hub, band, _master = landed[0]
        return Choice(hub=hub, band=band, cross_to=boat)
    _floor, _order, hub, band, _master = fitting[0]
    if classic.is_expansion_map(map_id):
        why = "no walk leaves map %d; its way to %s is %s, and no row takes it" % (
            int(map_id),
            hub.zone,
            EXITS[team],
        )
    else:
        why = "no hub on its continent fits level %d; %s is across the sea" % (
            level,
            hub.zone,
        )
    return Choice(hub=hub, band=band, refused=why)


def there(map_id, x, y, master: HubMaster) -> bool:
    """Is a member at (map, x, y) within ARRIVED_YARDS of the flight master?"""
    if map_id is None or x is None or y is None:
        return False
    if int(map_id) != master.map_id:
        return False
    return math.hypot(float(x) - master.x, float(y) - master.y) <= ARRIVED_YARDS


def said(name, level, why, choice: Choice) -> str:
    """The sentence the pass logs for a level walk."""
    return (
        "%s walks to the flight master at %s to level (quests %d to %d fit its "
        "level %d): %s"
        % (
            name,
            choice.place,
            int(choice.band[0]),
            int(choice.band[1]),
            int(level),
            why,
        )
    )


def crossing_said(name, level, why, choice: Choice) -> str:
    """The sentence the pass logs for a member sent to its side's boat."""
    return (
        "%s takes the boat off map 530 to level: %s, then on to %s (quests %d "
        "to %d fit its level %d): %s"
        % (
            name,
            EXITS[choice.hub.team],
            choice.place,
            int(choice.band[0]),
            int(choice.band[1]),
            int(level),
            why,
        )
    )


def walled_note(name, level, why, choice: Choice, wall) -> str:
    """The note for a member the module will not carry across (`wall`, its own
    words in the newest crossing row)."""
    return "%s at level %d stays: %s, and the module will not cross it (%s)%s" % (
        name,
        int(level),
        why,
        wall,
        (" (it would go to %s)" % choice.place) if choice.hub is not None else "",
    )


def refused_note(name, level, why, choice: Choice) -> str:
    """The note for a member that has outgrown its zone and is not walked."""
    aim = (" (it would go to %s)" % choice.place) if choice.hub is not None else ""
    return "%s at level %d stays: %s, and %s%s" % (
        name,
        int(level),
        why,
        choice.refused,
        aim,
    )


@dataclass(frozen=True)
class World:
    """What every member's level step is chosen from, read once per pass.

    bands    side -> levelroute.bands for that side
    masters  hub key -> HubMaster (`hub_masters`)
    roster   every roster family member's name: levelroute serves those
    """

    bands: dict
    masters: dict
    roster: frozenset = frozenset()


def world(quest_rows, master_rows, roster=()) -> World | None:
    """The World off levelroute.QUESTS_SQL's rows and the flight-master rows,
    or None while the quests are unread (no step is taken from no bands)."""
    if quest_rows is None:
        return None
    return World(
        bands={
            team: levelroute.bands(quest_rows, team)
            for team in (levelroute.HORDE, levelroute.ALLIANCE)
        },
        masters=hub_masters(master_rows),
        roster=frozenset(str(n) for n in roster or ()),
    )
