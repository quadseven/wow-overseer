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
in a day, every pass refusing them with "no row takes it".

THE ORB (`ORB_ENTRY`, `orbs_from`, `Choice.orb`). A Blood Elf player leaves by
clicking the Orb of Translocation in Silvermoon City: gameobject 184502, whose
spell (35376) runs the script that casts Translocate (25649) and sets the
player down in the Undercity on map 0. Nothing is granted: it is the world's
own object, open to any Horde player who walks up to it. The member walks to
the orb's spawn (`walk-to-spawn gameobject:<spawn>`) and clicks it with the
module's `use-gameobject <entry>` row (quadseven/mod-overseer#865, the click a
class quest makes), when it stands in the starting lands (the far walk's ground
there) and a hub on map 0 fits its level; it walks on to that hub from the
Undercity on a later pass. Measured on the dev realm on 2026-10-10: 7 of
Bonkers' Blood Elves stood on map 530 at levels 21 to 30 past the Ghostlands'
band, and a hearth puts a Blood Elf back on Sunstrider Isle, so one that had
levelled on Kalimdor came home to the island and stayed. A member whose
continent has no hub that fits, or whose way off map 530 is unread, is still
named in the pass's notes with the hub it would go to and the way there, and
left where it stands.

WHERE THE WALK ENDS (`hub_masters`). The hub's flight master: the flight-master
spawn of the world's creature table nearest the hub's taxi node, within
travel.FLIGHT_NODE_MATCH_YARDS, whose faction does not attack the hub's side.
The row names that spawn by its id, so the place walked to is a spawn row of the
world and never a coordinate computed here.

OPEN QUESTS (`quest_book`, `open_quests`, 2026-10-10). A player leaves a zone
when its quests run out, not when its band's ceiling is passed, and goes where
it has the most quests left. The band alone kept a member in one zone until
the zone's 90th-percentile level and never read what it had done. Run against
the live bands of 2026-10-10, Horde members on the Eastern Kingdoms stayed in
Hillsbrad from 21 to 40, Alliance members on Kalimdor in Ashenvale from 22 to
32, and Duskwood, Dustwallow Marsh, Un'Goro, Felwood, both Plaguelands and
Silithus were never chosen. Rokk (22) and Whakk (20) stood in Searing Gorge
with no quest open, and Tugga (26) in Hillsbrad with one. So once the member's
rewarded quests are read (`Member.rewarded`), a quest is open for it when:

  * it is of a hub zone, its side may take it (levelroute.side_quests), its
    race mask holds the member's race and its minimum level is met;
  * a lone member works it: not a group, dungeon, raid or PvP quest, not
    suggested for a group, not repeatable (`PARTY_QUEST_INFO`);
  * a creature or object of the world that gives it is spawned outside a
    seasonal event (`QUEST_FACTS_SQL`);
  * the member has not been rewarded for it, and the quest before it, if any,
    is rewarded or itself open by these rules (a chain counts from its head);
  * its level lies in levelroute's window around the member's level
    (GREEN_BELOW under, ABOVE over).

A member has then outgrown a hub zone once fewer than MIN_OPEN quests are open
for it there, whatever its band says, and `choose` takes the fitting hub with
the most open quests, a hub whose flight point it knows before one it does not,
then the lower band. Unread rewarded quests or unread quest facts fall back to
the band rule above.

THE GROUND A SIDE WALKS (`POCKETS`, `ground_of`). A walk crosses a continent by
road. Some hubs lie past the other side's ground: from the Horde's north of the
Eastern Kingdoms, Stranglethorn Vale is reached through Duskwood, the Badlands
through the Wetlands and Loch Modan, the Swamp of Sorrows through Redridge or
Duskwood. A Horde player takes the zeppelin to Grom'gol and the flight paths to
Kargath and Stonard instead. So a hub is walked to only on the member's own
ground. The module's far walk still refuses a road far above the walker's
level (quadseven/mod-overseer#897), and flies whenever a known flight beats it.

THE ZEPPELINS AND BOATS (`TRANSPORTS`). Each side's rides between the two
continents, and the one from the Undercity to Grom'gol. A member none of whose
own ground's hubs fit rides its side's way to the other continent with the
module's `cross-to-map map:<id>` row (`Choice.cross_to`, `Choice.transport`),
when a hub fits on the ground that ride lands on. The module picks the ride by
its own price, so the member may land elsewhere on that map; the next pass
reads where it stands. The Undercity to Grom'gol zeppelin never leaves map 0,
and `cross-to-map` names only a map, so no row rides it yet (`Transport.rides`):
a Horde member in the north is offered Kalimdor's hubs before Stranglethorn's,
and is told so when only Stranglethorn fits.

PURE MODULE: rows in, choices and sentences out. No MySQL, no clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

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

# The way off map 530 a player of each side takes, for the notes and the log.
EXITS = {
    levelroute.ALLIANCE: "the boat from Valaar's Berth on Azuremyst Isle to "
    "Auberdine in Darkshore",
    levelroute.HORDE: "the Orb of Translocation in Silvermoon City to the Undercity",
}

# The map a side's own boat off map 530 lands on: Elune's Blessing (world
# transport 181646) from Valaar's Berth to Auberdine on Kalimdor. The Horde's
# way is the orb below.
BOAT_EXITS = {levelroute.ALLIANCE: 1}

# THE HORDE'S WAY OFF MAP 530: the Orb of Translocation in Silvermoon City
# (gameobject 184502). Its spell 35376 is a script effect whose spell_scripts
# row casts Translocate (25649), whose spell_target_position is the Undercity on
# map 0 (1804.9, 326.9). The Undercity's own orb (184503) is the way back and is
# never taken here.
ORB_ENTRY = 184502
ORB_LANDS_ON = 0
ORB_SIDE = levelroute.HORDE

# The source action of the level step's orb rows (the walk to it and the click),
# apart from the walk's and the boat's, and how long one holds the member: the
# walk to the orb takes up to half an hour (guildroute.FAR_WALK_FOLLOW_SECONDS).
ORB_ACTION = ACTION + "-orb"
ORB_COOLDOWN_MINUTES = 60
ORB_NAME = "the Orb of Translocation"

# The source action of the level step's crossing row (guildjobs.source_for),
# apart from the walk's so that the walk's cooldown never reads it.
CROSS_ACTION = ACTION + "-cross"

# THE HEARTH AT THE ZONE A MEMBER LEVELS IN (2026-10-10). On the dev realm 140
# of the two guilds' 142 members were bound at their starting inn, 39 of them on
# map 530 (Ammen Vale, Sunstrider Isle), so a hearth put an outgrown Draenei or
# Blood Elf back on its island and the boat or the orb had to take it off again.
# A player rebinds at the inn of the zone it levels in. Once a member whose
# hearth is bound somewhere it has outgrown stands in a zone whose band fits its
# level, it walks to the innkeeper of that zone's hub (`bind_inn`) and binds
# there: the walk ends within INN_NEAR_YARDS of the innkeeper (the spawn walk's
# `near:`, quadseven/mod-overseer), inside the core's interaction distance, and
# `kind='bind'` `here` is the core's own HandleBinderActivateOpcode. Nothing is
# moved and nothing is granted. INN_ACTION is the source action of both rows.
INN_ACTION = ACTION + "-bind"
# A hub's inn is the friendly innkeeper nearest its taxi node within this many
# yards: every hub of the dev world with an inn has one within 220 of its node,
# and the next nearest innkeeper of the hubs without one stands 850 off.
INN_YARDS = 300.0
INN_NEAR_YARDS = 3
# One bind walk per member in this long: a bind that went through moves the
# home, and the member is not asked again; one that failed waits this long.
INN_COOLDOWN_MINUTES = 6 * 60
# New bind walks one guild starts in one pass (each may be a far walk).
INN_STEPS_PER_GUILD = 2

# OPEN QUESTS (see the module docstring). levelroute's window and floor, so a
# guild member and a family read a zone the same way.
MIN_OPEN = levelroute.MIN_OPEN
GREEN_BELOW = levelroute.GREEN_BELOW
ABOVE = levelroute.ABOVE
# quest_template.QuestInfoID of quests a lone member does not work: group (1),
# PvP (41), raid (62), dungeon (81), heroic (85), 10- and 25-man raid (88, 89).
# Read against the dev world on 2026-10-10, 127 of the 2,178 hub zone quests.
PARTY_QUEST_INFO = frozenset({1, 41, 62, 81, 85, 88, 89})
# quest_template_addon.SpecialFlags: QUEST_SPECIAL_FLAGS_REPEATABLE.
REPEATABLE_FLAG = 1
# How many quests back a chain is followed to its head.
CHAIN_DEPTH = 30
# The maps a quest's giver is read on: the two continents and map 530.
GIVER_MAPS = (*classic.CLASSIC_CONTINENTS, classic.OUTLAND_MAP)

# One row per quest of a hub zone: the quest before it, its kind, and whether a
# creature or object that gives it is spawned outside a seasonal event (a
# positive game_event entry spawns it only while that event runs). The only
# interpolated parts are this module's integer constants.
QUEST_FACTS_SQL = (
    "SELECT t.ID AS quest, COALESCE(a.PrevQuestID, 0) AS prev, "  # noqa: S608
    "t.QuestInfoID AS info, t.SuggestedGroupNum AS group_size, "
    "COALESCE(a.SpecialFlags, 0) AS special, ("
    "EXISTS (SELECT 1 FROM acore_world.creature_queststarter s "
    "JOIN acore_world.creature c ON c.id = s.id WHERE s.quest = t.ID "
    "AND c.map IN (" + ", ".join(str(int(m)) for m in GIVER_MAPS) + ") "
    "AND NOT EXISTS (SELECT 1 FROM acore_world.game_event_creature e "
    "WHERE e.guid = c.guid AND e.eventEntry > 0)) "
    "OR EXISTS (SELECT 1 FROM acore_world.gameobject_queststarter s "
    "JOIN acore_world.gameobject g ON g.id = s.id WHERE s.quest = t.ID "
    "AND g.map IN (" + ", ".join(str(int(m)) for m in GIVER_MAPS) + ") "
    "AND NOT EXISTS (SELECT 1 FROM acore_world.game_event_gameobject e "
    "WHERE e.guid = g.guid AND e.eventEntry > 0))"
    ") AS given FROM acore_world.quest_template t "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = t.ID "
    "WHERE t.QuestSortID IN (" + ", ".join(str(int(z)) for z in levelroute.ZONES) + ")"
)

# THE GROUND A SIDE WALKS (see the module docstring): side -> map -> the zones
# of each pocket that side reaches only past the other side's ground. Every
# other zone of the map is the side's own ground there (MAIN_GROUND).
MAIN_GROUND = ""
POCKETS = {
    levelroute.HORDE: {
        0: {
            # Past Duskwood. Grom'gol's zeppelins and Booty Bay's boat call.
            "Stranglethorn Vale": frozenset({33}),
            # Past the Wetlands and Loch Modan: Badlands, Searing Gorge and
            # Burning Steppes, one ground by Blackrock Mountain.
            "the Badlands": frozenset({3, 46, 51}),
            # Past Redridge or Duskwood: the Swamp of Sorrows and the Blasted
            # Lands.
            "the Swamp of Sorrows": frozenset({4, 8}),
        },
    },
}

# Zone ids of the berths below.
TIRISFAL, DUROTAR, STRANGLETHORN, BARRENS = 85, 14, 33, 17
WETLANDS, DARKSHORE, DUSTWALLOW = 11, 148, 15


@dataclass(frozen=True)
class Transport:
    """A zeppelin or boat: its name, the sides whose crew welcome them, its two
    ends as (map, zone), and whether a row can ride it (`cross-to-map` takes a
    member only to another map)."""

    name: str
    sides: tuple
    ends: tuple
    rides: bool = True


TRANSPORTS = (
    Transport(
        "the zeppelin from the Undercity to Orgrimmar",
        (levelroute.HORDE,),
        ((0, TIRISFAL), (1, DUROTAR)),
    ),
    Transport(
        "the zeppelin from Grom'gol to Orgrimmar",
        (levelroute.HORDE,),
        ((0, STRANGLETHORN), (1, DUROTAR)),
    ),
    Transport(
        "the zeppelin from the Undercity to Grom'gol",
        (levelroute.HORDE,),
        ((0, TIRISFAL), (0, STRANGLETHORN)),
        rides=False,
    ),
    Transport(
        "the boat from Booty Bay to Ratchet",
        (levelroute.HORDE, levelroute.ALLIANCE),
        ((0, STRANGLETHORN), (1, BARRENS)),
    ),
    Transport(
        "the boat from Menethil Harbor to Auberdine",
        (levelroute.ALLIANCE,),
        ((0, WETLANDS), (1, DARKSHORE)),
    ),
    Transport(
        "the boat from Menethil Harbor to Theramore",
        (levelroute.ALLIANCE,),
        ((0, WETLANDS), (1, DUSTWALLOW)),
    ),
)


@dataclass(frozen=True)
class HubMaster:
    """A hub's flight master: its creature spawn id and where it stands."""

    spawn: int
    map_id: int
    x: float
    y: float
    name: str = ""


@dataclass(frozen=True)
class Orb:
    """A side's orb off map 530: its gameobject spawn id and entry, where it
    stands, and the map it sets a member down on."""

    spawn: int
    entry: int
    map_id: int
    x: float
    y: float
    lands_on: int


def orbs_from(rows) -> dict:
    """side -> Orb off the world's gameobject rows (guid, entry, map_id, x, y).
    Only the Silvermoon orb (ORB_ENTRY) on map 530; an unreadable row is left
    out, and a side with none has no orb."""
    out = {}
    for row in rows or ():
        try:
            entry, map_id = int(row["entry"]), int(row["map_id"])
            if entry != ORB_ENTRY or map_id != classic.OUTLAND_MAP:
                continue
            orb = Orb(
                spawn=int(row["guid"]),
                entry=entry,
                map_id=map_id,
                x=float(row["x"]),
                y=float(row["y"]),
                lands_on=ORB_LANDS_ON,
            )
        except (KeyError, TypeError, ValueError):
            continue
        if ORB_SIDE not in out or orb.spawn < out[ORB_SIDE].spawn:
            out[ORB_SIDE] = orb
    return out


@dataclass(frozen=True)
class Choice:
    """The hub a member is sent to, or why it is not sent.

    A non-empty `refused` means `master` is None. `hub` and `band` may still
    name the hub it would go to, for the note. `cross_to` set means the member
    first crosses to that map by its side's boat (BOAT_EXITS), or by its orb
    when `orb` is set, or between the two continents by `transport`, with
    `master` None: `hub` is where it levels once it has landed. `open` is the
    member's open quests at `hub`, None while they are unread.
    """

    hub: levelroute.Hub | None = None
    band: tuple | None = None
    master: HubMaster | None = None
    refused: str = ""
    cross_to: int | None = None
    orb: Orb | None = None
    open: int | None = None
    transport: str = ""

    @property
    def place(self) -> str:
        if self.hub is None:
            return ""
        return "%s in %s" % (self.hub.name, self.hub.zone)


def side_of(race) -> str:
    """levelroute's side for one race, or "" when unknown."""
    return levelroute.team_of([{"race": race}])


@dataclass(frozen=True)
class Quest:
    """One quest a lone member may take: its zone, level, minimum level, race
    mask and the quest before it (PrevQuestID; 0 or below for none)."""

    id: int
    zone: int
    level: int
    min_level: int
    races: int
    prev: int


def quest_book(quest_rows, fact_rows) -> dict | None:
    """side -> {quest id: Quest} off levelroute.QUESTS_SQL's rows and
    QUEST_FACTS_SQL's, keeping the quests a lone member of that side works and
    whose giver is spawned (`_solo`); None while either read is missing or
    empty, so a zone is then judged by its band alone."""
    if not quest_rows or not fact_rows:
        return None
    facts = {}
    for row in fact_rows:
        try:
            facts[int(row["quest"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    out = {}
    for team in (levelroute.HORDE, levelroute.ALLIANCE):
        book = {}
        for row in levelroute.side_quests(quest_rows, team):
            try:
                qid = int(row["quest"])
                fact = facts.get(qid)
                if fact is None or not _solo(fact):
                    continue
                book[qid] = Quest(
                    id=qid,
                    zone=int(row["zone"]),
                    level=int(row["level"]),
                    min_level=int(row.get("min_level") or 0),
                    races=int(row.get("races") or 0),
                    prev=int(fact.get("prev") or 0),
                )
            except (KeyError, TypeError, ValueError):
                continue
        out[team] = book
    return out


def _solo(fact) -> bool:
    """A quest a lone member works, given by a spawn of the world."""
    return (
        bool(int(fact.get("given") or 0))
        and int(fact.get("info") or 0) not in PARTY_QUEST_INFO
        and int(fact.get("group_size") or 0) <= 1
        and not int(fact.get("special") or 0) & REPEATABLE_FLAG
    )


def open_quests(book, level, race, done) -> dict | None:
    """zone id -> the quests open for a member of this level and race that has
    been rewarded for `done` (see the module docstring), out of one side's
    `quest_book`. None when the book or `done` is unread."""
    if book is None or done is None:
        return None
    level = int(level)
    bit = 1 << (int(race) - 1) if race and int(race) > 0 else 0
    done = frozenset(int(q) for q in done)
    takeable: dict = {}

    def can_take(qid, depth=0) -> bool:
        if qid in takeable:
            return takeable[qid]
        quest = book.get(qid)
        takeable[qid] = False  # a chain that loops back is not takeable
        if quest is None or qid in done or depth > CHAIN_DEPTH:
            return False
        if quest.min_level > level or (quest.races and not quest.races & bit):
            return False
        ok = quest.prev <= 0 or quest.prev in done or can_take(quest.prev, depth + 1)
        takeable[qid] = ok
        return ok

    out: dict = {}
    for qid, quest in book.items():
        if not level - GREEN_BELOW <= quest.level <= level + ABOVE:
            continue
        if can_take(qid):
            out[quest.zone] = out.get(quest.zone, 0) + 1
    return out


def member_opens(world, race, level, done) -> dict | None:
    """`open_quests` for one member off the pass's World, None when unread."""
    books = getattr(world, "quests", None)
    if books is None:
        return None
    return open_quests(books.get(side_of(race)), level, race, done)


def ground_of(team, map_id, zone_id) -> str:
    """The pocket of `team`'s POCKETS the zone lies in, MAIN_GROUND otherwise."""
    if map_id is None:
        return MAIN_GROUND
    for name, zones in POCKETS.get(team, {}).get(int(map_id), {}).items():
        if zone_id is not None and int(zone_id) in zones:
            return name
    return MAIN_GROUND


def ground_name(team, ground) -> str:
    """The words for a ground in a note."""
    return ground or "the %s's own ground" % (
        "Horde" if team == levelroute.HORDE else "Alliance"
    )


def rides_from(team, map_id, ground, zone_id=None, to_zone=None) -> list:
    """[(Transport, far map, far ground)] of `team`'s rides from `ground` on
    `map_id` to another map that a row can take: one calling in the member's
    zone (`zone_id`) first, then one landing in the hub's zone (`to_zone`),
    then TRANSPORTS' order."""
    out = []
    for order, ride in enumerate(TRANSPORTS):
        if team not in ride.sides or not ride.rides:
            continue
        for (here_map, here_zone), (far_map, far_zone) in (
            ride.ends,
            ride.ends[::-1],
        ):
            if here_map != int(map_id) or far_map == here_map:
                continue
            if ground_of(team, here_map, here_zone) != ground:
                continue
            rank = (here_zone != zone_id, far_zone != to_zone, order)
            out.append((rank, ride, far_map, ground_of(team, far_map, far_zone)))
    out.sort(key=lambda r: r[0])
    return [r[1:] for r in out]


def unridden_to(team, map_id, ground, far_ground) -> str:
    """The name of `team`'s transport from `ground` to `far_ground` on the same
    map that no row rides yet, "" for none."""
    for ride in TRANSPORTS:
        if team not in ride.sides or ride.rides:
            continue
        grounds = {ground_of(team, m, z) for m, z in ride.ends if m == int(map_id)}
        if {ground, far_ground} <= grounds:
            return ride.name
    return ""


def hub_masters(rows) -> dict:
    """hub key -> HubMaster off the world's flight-master spawn rows.

    `rows` carry guid, map_id, x, y, name and enemy_group (the faction
    template's EnemyGroup, None when the template is unread). For each hub the
    nearest spawn to its taxi node within MASTER_YARDS whose faction does not
    attack the hub's side; a hub with none is left out, so it is never chosen.
    """
    return _hub_spawns(rows, MASTER_YARDS)


def hub_inns(rows) -> dict:
    """hub key -> HubMaster of the hub's innkeeper, off the world's innkeeper
    spawn rows (the same columns as hub_masters'): the nearest to its taxi
    node within INN_YARDS whose faction does not attack the hub's side."""
    return _hub_spawns(rows, INN_YARDS)


def _hub_spawns(rows, reach) -> dict:
    """hub key -> the friendly spawn of `rows` nearest the hub's taxi node
    within `reach` yards."""
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
            if yards > reach:
                continue
            if best is None or (yards, master.spawn) < best[0]:
                best = ((yards, master.spawn), master)
        if best is not None:
            out[hub.key] = best[1]
    return out


def outgrown(level, race, map_id, zone_id, bands, opens=None) -> str:
    """Why a member has outgrown where it stands, or "" when it has not or
    where it stands cannot be judged.

    `bands` is levelroute.bands for the member's side: zone id -> (floor,
    ceiling, quest count). `opens` is the member's `open_quests`; once read, a
    hub zone is outgrown when fewer than MIN_OPEN quests are open there,
    whatever its ceiling.
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
    if opens is not None:
        left = int(opens.get(int(zone_id), 0))
        if left < MIN_OPEN:
            return "it has %s left in %s at level %d" % (
                quests_word(left),
                zone,
                int(level),
            )
        return ""
    if int(level) > int(band[1]):
        return "it has outgrown %s, whose quests top out at %d" % (zone, band[1])
    return ""


def quests_word(n) -> str:
    """ "1 open quest", "4 open quests"."""
    return "%d open quest%s" % (int(n), "" if int(n) == 1 else "s")


def fits(band, level, left=None) -> bool:
    """A band a member of `level` may be sent to: not outgrown, not too high.
    With `left`, its open quests there, MIN_OPEN of them stand for the
    ceiling."""
    if band is None:
        return False
    if int(band[0]) > int(level) + int(council.NEAR_ENOUGH):
        return False
    if left is not None:
        return int(left) >= MIN_OPEN
    return int(band[1]) >= int(level)


def hubs_from(team, map_id, zone_id) -> tuple:
    """The hubs a member of `team` standing at (map, zone) may be sent to:
    levelroute's, and its side's starting-land hub while it stands in the
    starting lands."""
    hubs = levelroute.hubs_for(team)
    if classic.is_starting_land(map_id, zone_id):
        hubs += tuple(h for h in levelroute.STARTING_LAND_HUBS if h.team == team)
    return hubs


def choose(
    level, race, map_id, bands, masters, zone_id=None, orbs=None, opens=None, nodes=None
) -> Choice:
    """The hub a member of this level and race is walked to from `map_id`.

    Among the hubs with a known flight master (`hubs_from`) whose band fits:
    with `opens` read (`open_quests`), those with MIN_OPEN quests open for the
    member, the most open first, then one whose flight point is in `nodes` (the
    member's known taxi nodes), then the lowest band; unread, the lowest band
    first. Then levelroute's order. Only on its own map and its own ground
    (`ground_of`); from map 530, on the map its side's boat or orb (`orbs`,
    orbs_from) lands on, and from a continent, on the ground its side's
    zeppelin or boat lands on (`Choice.cross_to`); see the module docstring.
    """
    team = side_of(race)
    if not team:
        return Choice(refused="its side cannot be read off its race")
    level = int(level)
    fitting = _fitting(team, level, map_id, zone_id, bands, masters, opens, nodes)
    if not fitting:
        return Choice(refused="no %s hub fits level %d" % (team, level))
    ground = ground_of(team, map_id, zone_id)
    home = [
        f
        for f in fitting
        if map_id is not None
        and f.master.map_id == int(map_id)
        and _ground(team, f.hub) == ground
    ]
    if home:
        return home[0].choice()
    if classic.is_expansion_map(map_id):
        return _away(
            team, level, map_id, fitting, _orb_for(team, map_id, zone_id, orbs)
        )
    return _across(team, level, map_id, zone_id, fitting)


@dataclass(frozen=True)
class _Fit:
    """A hub that fits, with what it is ranked by."""

    rank: tuple
    hub: levelroute.Hub
    band: tuple
    master: HubMaster
    open: int | None

    def choice(self, **over) -> Choice:
        fields = dict(hub=self.hub, band=self.band, master=self.master, open=self.open)
        fields.update(over)
        return Choice(**fields)


def _ground(team, hub) -> str:
    return ground_of(team, hub.map_id, hub.zone_id)


def _orb_for(team, map_id, zone_id, orbs):
    """The side's orb, when the member stands in the starting lands, where a
    far walk to it starts (mod-overseer#765); None otherwise."""
    if not classic.is_starting_land(map_id, zone_id):
        return None
    return (orbs or {}).get(team)


def _fitting(team, level, map_id, zone_id, bands, masters, opens=None, nodes=None):
    """_Fit of every friendly hub of `team` whose band fits `level` (with its
    open quests, when `opens` is read) and whose flight master is known, best
    first (see `choose`)."""
    fitting = []
    for order, hub in enumerate(hubs_from(team, map_id, zone_id)):
        band = (bands or {}).get(hub.zone_id)
        master = (masters or {}).get(hub.key)
        left = None if opens is None else int(opens.get(hub.zone_id, 0))
        if not hub.friendly or master is None or not fits(band, level, left):
            continue
        if left is None:
            rank = (int(band[0]), order)
        else:
            flies = nodes is not None and hub.node in nodes
            rank = (-left, not flies, int(band[0]), order)
        fitting.append(_Fit(rank, hub, band, master, left))
    fitting.sort(key=lambda f: f.rank)
    return fitting


def _away(team, level, map_id, fitting, orb=None) -> Choice:
    """The choice from map 530 when no fitting hub stands there: its side's
    boat (BOAT_EXITS) or orb (`orb`) to the best hub that fits where it lands,
    or the best hub of all, named and refused."""
    boat = BOAT_EXITS.get(team)
    if boat is not None:
        orb = None
    landing = boat if boat is not None else (orb.lands_on if orb else None)
    landed = [f for f in fitting if landing is not None and f.master.map_id == landing]
    if landed:
        return landed[0].choice(master=None, cross_to=landing, orb=orb)
    best = fitting[0]
    why = "no walk leaves map %d; its way to %s is %s, and no row takes it" % (
        int(map_id),
        best.hub.zone,
        EXITS[team],
    )
    return best.choice(master=None, refused=why)


def _across(team, level, map_id, zone_id, fitting) -> Choice:
    """The choice on a continent when no fitting hub stands on the member's own
    ground: its side's zeppelin or boat from that ground to the best hub that
    fits on the ground it lands on (`rides_from`), or the best hub of all,
    named and refused."""
    ground = ground_of(team, map_id, zone_id)
    for f in fitting:
        if map_id is None or f.master.map_id == int(map_id):
            continue
        rides = rides_from(team, map_id, ground, zone_id, f.hub.zone_id)
        for ride, far_map, far_ground in rides:
            if f.master.map_id == far_map and _ground(team, f.hub) == far_ground:
                return f.choice(master=None, cross_to=far_map, transport=ride.name)
    best = fitting[0]
    here = ground_name(team, ground)
    if map_id is not None and best.master.map_id == int(map_id):
        link = unridden_to(team, map_id, ground, _ground(team, best.hub))
        why = "%s lies past the other side's ground from %s%s" % (
            best.hub.zone,
            here,
            (", and no row rides %s yet" % link) if link else "",
        )
    else:
        why = "no hub on %s fits level %d; %s is across the sea, and no %s ride %s" % (
            here,
            level,
            best.hub.zone,
            team,
            "from here lands where it fits"
            if map_id is not None and rides_from(team, map_id, ground)
            else "leaves %s" % here,
        )
    return best.choice(master=None, refused=why)


def there(map_id, x, y, master: HubMaster) -> bool:
    """Is a member at (map, x, y) within ARRIVED_YARDS of the flight master?"""
    if map_id is None or x is None or y is None:
        return False
    if int(map_id) != master.map_id:
        return False
    return math.hypot(float(x) - master.x, float(y) - master.y) <= ARRIVED_YARDS


def bind_inn(level, race, map_id, zone_id, x, y, home_map, home_zone, bands, inns):
    """(inn, hub) a member sets its hearth at, or (None, None).

    Only a member whose home is read and lies where it has outgrown
    (`outgrown`), standing in a zone of its side's hub whose band fits its level
    (`fits`), where that hub has an inn on the member's map (`hub_inns`). Of
    several such hubs in the zone, the nearest inn."""
    team = side_of(race)
    if not _bind_due(team, level, race, map_id, zone_id, home_map, home_zone, bands):
        return None, None
    return _zone_inn(team, map_id, zone_id, x, y, inns)


def _bind_due(team, level, race, map_id, zone_id, home_map, home_zone, bands) -> bool:
    """Whether a member of `team` is bound where it has outgrown and stands in
    a zone whose band fits its level; False when anything is unread."""
    if not team or map_id is None or not zone_id or home_map is None:
        return False
    side_bands = (bands or {}).get(team, {})
    if not home_zone or not outgrown(level, race, home_map, home_zone, side_bands):
        return False
    return fits(side_bands.get(int(zone_id)), level)


def _zone_inn(team, map_id, zone_id, x, y, inns):
    """(inn, hub) of the nearest inn of `team`'s friendly hubs in the zone, on
    the member's map, or (None, None)."""
    best = None
    for hub in hubs_from(team, map_id, zone_id):
        inn = (inns or {}).get(hub.key)
        if hub.zone_id != int(zone_id) or not hub.friendly or inn is None:
            continue
        if inn.map_id != int(map_id):
            continue
        key = (_yards_to(x, y, inn), inn.spawn)
        if best is None or key < best[0]:
            best = (key, inn, hub)
    return (best[1], best[2]) if best else (None, None)


def _yards_to(x, y, spawn) -> float:
    """Yards from (x, y) to a spawn, 0 when the position is unread."""
    if x is None or y is None:
        return 0.0
    return math.hypot(float(x) - spawn.x, float(y) - spawn.y)


def bind_said(name, level, inn, hub, home_zone) -> str:
    """The sentence the pass logs for a walk to bind at a zone's inn."""
    return (
        "%s sets its hearth at %s in %s, the zone it levels in at %d: its "
        "hearthstone is bound in %s, which it has outgrown"
        % (
            name,
            inn.name or "the innkeeper",
            "%s, %s" % (hub.name, hub.zone),
            int(level),
            levelroute.zone_name(home_zone),
        )
    )


def said(name, level, why, choice: Choice) -> str:
    """The sentence the pass logs for a level walk."""
    return (
        "%s walks to the flight master at %s to level (quests %d to %d fit its "
        "level %d%s): %s"
        % (
            name,
            choice.place,
            int(choice.band[0]),
            int(choice.band[1]),
            int(level),
            _open_words(choice),
            why,
        )
    )


def _open_words(choice: Choice) -> str:
    """ "; 12 open quests there" when the member's open quests are read."""
    if choice.open is None:
        return ""
    return "; %s there" % quests_word(choice.open)


def crossing_said(name, level, why, choice: Choice) -> str:
    """The sentence the pass logs for a member sent to its side's boat off map
    530, or to its zeppelin or boat between the continents."""
    if choice.transport:
        return (
            "%s takes %s to level, then walks on to %s (quests %d to %d fit its "
            "level %d%s): %s"
            % (
                name,
                choice.transport,
                choice.place,
                int(choice.band[0]),
                int(choice.band[1]),
                int(level),
                _open_words(choice),
                why,
            )
        )
    return (
        "%s takes the boat off map 530 to level: %s, then on to %s (quests %d "
        "to %d fit its level %d%s): %s"
        % (
            name,
            EXITS[choice.hub.team],
            choice.place,
            int(choice.band[0]),
            int(choice.band[1]),
            int(level),
            _open_words(choice),
            why,
        )
    )


def orb_said(name, level, why, choice: Choice) -> str:
    """The sentence the pass logs for a member sent to its side's orb."""
    return (
        "%s takes %s to level, then walks on to %s (quests %d to %d fit its "
        "level %d%s): %s"
        % (
            name,
            EXITS[choice.hub.team],
            choice.place,
            int(choice.band[0]),
            int(choice.band[1]),
            int(level),
            _open_words(choice),
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
    orbs     side -> Orb (`orbs_from`), its way off map 530 by an orb
    inns     hub key -> HubMaster of its innkeeper (`hub_inns`)
    quests   side -> {quest id: Quest} (`quest_book`), None while unread, which
             judges every zone by its band alone
    """

    bands: dict
    masters: dict
    roster: frozenset = frozenset()
    orbs: dict = field(default_factory=dict)
    inns: dict = field(default_factory=dict)
    quests: dict | None = None


def world(
    quest_rows, master_rows, roster=(), orb_rows=(), inn_rows=(), fact_rows=None
) -> World | None:
    """The World off levelroute.QUESTS_SQL's rows, the flight-master rows, the
    orb's gameobject rows, the innkeeper rows and QUEST_FACTS_SQL's rows, or
    None while the quests are unread (no step is taken from no bands)."""
    if quest_rows is None:
        return None
    return World(
        bands={
            team: levelroute.bands(quest_rows, team)
            for team in (levelroute.HORDE, levelroute.ALLIANCE)
        },
        masters=hub_masters(master_rows),
        roster=frozenset(str(n) for n in roster or ()),
        orbs=orbs_from(orb_rows),
        inns=hub_inns(inn_rows),
        quests=quest_book(quest_rows, fact_rows),
    )
