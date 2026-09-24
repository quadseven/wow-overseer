"""Getting the family from one continent to another, and refusing to pretend.

Wailing Caverns is on map 1. The family is on map 0. `entrances.json` gives the
door at map 1, x -753.596, y -2212.78, and every existing way to aim a character
at it refuses across a map boundary. That refusal is not a bug to route around,
it is the whole subject of this module.

WHAT THIS REPOSITORY CAN ACTUALLY OBSERVE ABOUT A CROSSING. Two things:

    overseer_snapshot.map_id            which continent a character is on
    overseer_snapshot.pos_x/pos_y/pos_z where on it

and one thing about both of those: how old the reading is, measured by the
database's own clock (`TIMESTAMPDIFF(SECOND, updated_at, NOW())`, which is what
map_server._fetch_family already selects). That is the complete list. There is
no column anywhere in mod-overseer's schema that says a character is standing on
a transport, none that says where a boat is, and none that says whether it is
docked. `overseer_snapshot` is a flat presence row: guid, name, level, race,
class, map, zone, area, x, y, z, health, combat, bot, guild, group leader,
target, updated_at.

WHAT THAT MEANS FOR A BOAT. The worldserver knows perfectly well - the module's
own terrain recovery already asks `bot->GetTransport() != nullptr` and stands
down on it (overseer_decisions.cpp, TerrainRecoveryMayInspect's `onTransport`
argument). So somebody has thought about transports before. But that answer is
read inside the world update and thrown away; nothing writes it down, so no
Python process can read it. A decision layer that takes "is this character
aboard" as an input is taking an input that does not exist.

THE RULE THIS MODULE IS BUILT ON, AND THE ONLY ONE THAT MATTERS: A STATE IT
CANNOT READ IS NEVER "WE ARE ABOARD". Every unknown resolves toward doing
nothing. An absent snapshot row is not "left the boat"; a stale row is not a
position; four members read on the far side while the fifth is unreadable is not
an arrival. The failure this is written against is the shape that has already
cost this codebase four separate stranding incidents (#79, #85, #87 and the
corpse case, catalogued in 2026_08_30_00_overseer_dungeon_run.sql): a state
nothing owns, produced by inferring ownership from a partial reading.

WHY A SPLIT PARTY IS THE ONE THING WORTH ALARMING ON. It is the only crossing
failure this repository can both observe and prove, and it is unrecoverable by
anything already here:

  * `follow` does not cross a map. FollowAction only acts while the master is
    on the same map (mod_overseer.cpp's escort comment, citing
    FollowActions.cpp:285). Measured live, twice, at the Deadmines door: the
    leader walks in under his own power and the other four stop outside.
  * An `at:<map>:<x>,<y>,<z>` aim does not cross a map either. ResolveTravelTarget
    returns false when `bot->GetMapId() != m`, deliberately, so that walking
    through a portal ENDS the errand rather than needing a special case.
  * A `trigger:<id>` aim does not cross a map: same check against the trigger's
    own map.
  * The catch-up escort says so out loud when it happens: "is no longer on the
    map ... is on - its catch-up walk ends, there is nowhere on this map to
    walk to."

So five characters on two continents are five characters that no drive in this
system can bring back together. That is worth saying loudly and immediately,
and it is worth never causing.

WHAT THIS MODULE REFUSES TO INVENT.

  * A dock or pier position. Menethil Harbor's berth is not in this repository.
    `zones.json` carries zone bounding boxes and `entrances.json` carries
    instance doors; neither is a place a boat ties up. A guessed berth is
    exactly the failure mod-overseer#121 already paid for, where a staging point
    was written as a trigger's coordinates offset along +X and the offset went
    into a wall while the Z belonged to a different floor.
  * A boat schedule, a transport GUID, or a transport position.
  * The Z of anything. `entrances.json` records map, x and y and no z at all,
    while the `at:` grammar requires one. See `approach`, which refuses for
    precisely that reason rather than filling it in.
  * An areatrigger id for Wailing Caverns. The one portal this module's C++
    sibling knows is Deadmines, and both of its trigger ids are quoted in
    mod_overseer.cpp out of the pinned core's own areatrigger.sql. There is no
    such row here for map 43 and this module will not guess one.

PURE MODULE: no MySQL, no core, no clock, no network. Rows come in, a verdict
goes out. `travel.py` is imported for one number - the width of the column an
aim has to fit in - because two copies of that number is how an aim gets
silently truncated by MySQL into something the world can never parse back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import travel

# The two continents this leg is about. Named rather than spelled 0 and 1 at
# each site: a bare 1 in a comparison against `map_id` is indistinguishable from
# a bare 1 that means "one member".
EASTERN_KINGDOMS = 0
KALIMDOR = 1

# How old a snapshot row may be and still be a reading.
#
# SIXTY SECONDS BECAUSE THAT IS ALREADY THE ANSWER HERE. map_server._fetch_family
# and /api/map both cut at sixty, and its comment gives the reason: a member the
# sweep has removed must read as gone on the card at the same moment they leave
# the map, or two surfaces disagree about who is online. A crossing that used a
# different freshness rule would be a third surface disagreeing with both.
#
# The age is MEASURED BY THE DATABASE and passed in, never recomputed here. The
# bridge and the worldserver are separate deployments and do not share a clock;
# subtracting a bridge-side `now` from a world-side timestamp is a skew bug
# waiting for a slow container.
SNAPSHOT_MAX_AGE_SECONDS = 60

# --- where one member is -------------------------------------------------
#
# UNREADABLE IS A PLACE. It is not a fifth kind of "not here": it is the answer
# whenever the row is missing, stale, or does not carry an integer map. It has
# to be a value the rest of the module can carry around, because the entire
# point is that it must never be quietly collapsed into one of the other three.
ORIGIN = "origin"
DESTINATION = "destination"
ELSEWHERE = "elsewhere"
UNREADABLE = "unreadable"

# --- where the party is --------------------------------------------------
BLIND = "blind"  # anybody unreadable: the world is not answering
SCATTERED = "scattered"  # somebody readable on a map that is neither end
SPLIT = "split"  # readable members on both ends at once
ASSEMBLED = "assembled"  # every member readable, all on the origin map
ARRIVED = "arrived"  # every member readable, all on the destination map

# --- what to do about it -------------------------------------------------
#
# A CLOSED SET OF FIVE, and three of them do nothing. That ratio is the design,
# not a gap in it: of the six legs below, five are blocked on a fact this
# deployment cannot supply, and a decision layer that emitted actions for them
# would be emitting orders nothing can carry out.
WAIT = "wait"  # unreadable world. Act on nothing.
ALARM = "alarm"  # the party is across two maps, or off both. Say so.
HOLD = "hold"  # assembled, and the next leg needs a fact nobody has.
CROSS = "cross"  # assembled, and every leg's facts are in hand.
ARRIVE = "arrive"  # every member observed on the far map. Hand the party on.

# --- the facts a crossing needs, one name each ----------------------------
#
# WHY THESE ARE NAMED VALUES AND NOT `if row.get(...)`. A missing fact has to be
# reportable. "Held at the dock" is useless; "held at the dock because no dock
# position exists in this repository" is a sentence somebody can act on, and it
# is the same sentence every time because it comes from here.
FACT_MEMBER_MAP = "member map"
FACT_MEMBER_POSITION = "member position"
FACT_DOCK_POSITION = "dock position"
FACT_TRANSPORT_PRESENT = "transport present"
FACT_MEMBER_ON_TRANSPORT = "member on transport"
FACT_TRANSPORT_IDENTITY = "which transport"
FACT_BOARDING_ACTUATOR = "a way to board"
FACT_LANDING_POSITION = "landing position"
FACT_TARGET_FOOTING = "target footing"

# Where each fact would have to come from, quoted so a reader can check whether
# it has appeared since without running anything.
FACT_SOURCES = {
    FACT_MEMBER_MAP: "overseer_snapshot.map_id",
    FACT_MEMBER_POSITION: "overseer_snapshot.pos_x, pos_y, pos_z",
    FACT_DOCK_POSITION: "nothing in this repository records a berth; zones.json holds zone "
    "boxes and entrances.json holds instance doors, and neither is a pier",
    FACT_TRANSPORT_PRESENT: "no table records a transport's position or its schedule",
    FACT_MEMBER_ON_TRANSPORT: "the worldserver has it (bot->GetTransport(), already read by "
    "TerrainRecoveryMayInspect) and writes it nowhere",
    FACT_TRANSPORT_IDENTITY: "no table records WHICH transport a character is on, so two members on "
    "two different boats read exactly like two members on one",
    FACT_BOARDING_ACTUATOR: "no command puts a character on a transport; boarding is a claim the "
    "game client makes in its movement packet, the same part of a player a "
    "bot does not have that already stopped the party at the Deadmines door",
    FACT_LANDING_POSITION: "the far-side berth is not in this repository either",
    FACT_TARGET_FOOTING: "entrances.json carries map, x and y and no z, and the at: grammar "
    "requires one",
}

# WHAT THIS DEPLOYMENT CAN SEE, as of mod-overseer's schema at
# data/sql/characters/base/2026_08_21_00_overseer.sql. Two facts out of nine.
#
# PASSED AS AN ARGUMENT EVERYWHERE rather than consulted as a global, so the day
# a column lands that publishes transport membership, the leg it unblocks is a
# one-line change to this frozenset and a test that passes the larger set. The
# machine below is not hardcoded to refuse - it refuses because of what is in
# here, and `test_a_world_that_can_see_everything_crosses` proves the difference.
OBSERVABLE = frozenset({FACT_MEMBER_MAP, FACT_MEMBER_POSITION})

# Every fact, for callers that want to ask "what would a complete world look
# like" without listing them again.
ALL_FACTS = frozenset(FACT_SOURCES)


@dataclass(frozen=True)
class Leg:
    """One stretch of a crossing, and the facts without which it is a guess.

    `fails_closed_to` is the action taken when any of `needs` is unavailable.
    It is a field rather than a rule applied uniformly because writing it down
    per leg is what makes "which of these fails open" a question a reader can
    answer by reading, instead of by tracing branches.
    """

    name: str
    needs: tuple[str, ...]
    fails_closed_to: str
    why: str


# THE SIX LEGS, IN ORDER. Each one fails differently, which is the reason they
# are six things and not one "take the boat" step.
LEGS = (
    Leg(
        "walk to the dock",
        (FACT_MEMBER_MAP, FACT_MEMBER_POSITION, FACT_DOCK_POSITION),
        HOLD,
        "The failure is walking to the wrong water. Nothing here records where "
        "a boat ties up, and a berth this module invented would be the "
        "mod-overseer#121 staging point again: coordinates derived by offsetting "
        "a known point in a direction nobody checked, landing in a wall, "
        "carrying a Z that belonged to another floor.",
    ),
    Leg(
        "wait for the boat",
        (FACT_TRANSPORT_PRESENT,),
        HOLD,
        "The failure is the boat leaving without you. An unknown boat is never "
        "a docked boat: with no reading at all, waiting forever is correct and "
        "boarding is not, because there is nothing to board.",
    ),
    Leg(
        "board",
        (FACT_TRANSPORT_PRESENT, FACT_BOARDING_ACTUATOR, FACT_MEMBER_ON_TRANSPORT),
        HOLD,
        "The failure is standing on the deck and not being a passenger. "
        "Boarding a moving transport is something the CLIENT asserts in its "
        "movement packet, and a server-side bot has no client - the identical "
        "shape to the areatrigger that never fired for a bot walking over a "
        "portal, which this codebase solved by synthesising the packet in C++ "
        "and could not solve any other way.",
    ),
    Leg(
        "transit",
        (FACT_MEMBER_ON_TRANSPORT, FACT_TRANSPORT_IDENTITY),
        HOLD,
        "The failure is falling off, or riding a different boat. A set of names "
        "is not a set of passengers: without a transport identity, four members "
        "on the boat that sailed and one on the next boat read identically to "
        "five members on one boat, and a decision layer that cannot tell those "
        "apart will declare the party reunited in the middle of the ocean.",
    ),
    Leg(
        "disembark",
        (FACT_MEMBER_MAP, FACT_MEMBER_ON_TRANSPORT, FACT_LANDING_POSITION),
        HOLD,
        "The failure is getting off at the wrong end, or riding back. "
        "'No longer on the transport' is not the same fact as 'standing on the "
        "far dock', and only one of the two is a place to walk on from.",
    ),
    Leg(
        "walk on",
        (FACT_MEMBER_MAP, FACT_MEMBER_POSITION, FACT_TARGET_FOOTING),
        HOLD,
        "The only leg whose member facts this deployment actually has. It is "
        "blocked on the target instead: entrances.json gives the Wailing Caverns "
        "door as map 1, x -753.596, y -2212.78 and no z, and an at: aim without "
        "a z is not an aim.",
    ),
)


@dataclass(frozen=True)
class Crossing:
    """Who is crossing, from which map to which. No route, deliberately.

    THE ROUTE IS NOT A FIELD because choosing one is a decision this module is
    not in a position to make honestly. Menethil Harbor to Theramore is the
    short way to the Barrens for an Alliance party and is very probably right,
    but "probably right" is a claim about a berth, a schedule and a landing
    point, and this module holds none of the three. What it holds is the pair of
    maps, which is the part that is certain and the part the observations answer.
    """

    members: frozenset[str]
    origin_map: int
    destination_map: int


def plan(members: Sequence[str], origin_map: int, destination_map: int) -> Crossing:
    """A crossing for a named roster between two different maps.

    Raises rather than returning None, unlike travel.resolve: an empty roster or
    a crossing from a map to itself is a caller bug, not an ordinary answer.
    """
    names = frozenset(str(name) for name in (members or ()) if str(name).strip())
    if not names:
        raise ValueError("a crossing needs at least one family member")
    if int(origin_map) == int(destination_map):
        raise ValueError(
            "a crossing needs two different maps, not map %d twice" % int(origin_map)
        )
    return Crossing(names, int(origin_map), int(destination_map))


def _readable_map(
    row: Mapping[str, object] | None, max_age_seconds: int
) -> tuple[int | None, str]:
    """The map this row proves, or None and the reason it proves nothing.

    THE THREE WAYS A ROW SAYS NOTHING, each answered separately so the reason
    survives into the log line. They are genuinely different situations and
    lumping them into a falsy check is how "the worldserver stopped writing"
    becomes indistinguishable from "he is standing in Elwynn".
    """
    if not row:
        return None, "no snapshot row"

    age = row.get("age_seconds")
    if age is None:
        # A row with no age is a row whose freshness nobody established. The
        # query that produces these selects the age explicitly; a row arriving
        # without it came from somewhere else and has not been vouched for.
        return None, "snapshot row carries no age"
    try:
        age = int(age)
    except (TypeError, ValueError):
        return None, "snapshot age is not a number: %r" % (row.get("age_seconds"),)
    if age < 0:
        # Clock skew between the database's NOW() and its own stored timestamp.
        # A negative age is not a very fresh row, it is a broken reading.
        return None, "snapshot age is negative (%d seconds): clocks disagree" % age
    if age >= max_age_seconds:
        # EXCLUSIVE, because the query that produces these rows is:
        # `updated_at > NOW() - INTERVAL 60 SECOND` excludes exactly age 60 and
        # up. Accepting one second more here than the query returns would make
        # this a third surface disagreeing with the map and the family card
        # about who is online.
        return None, "snapshot is %d seconds old" % age

    raw = row.get("map_id")
    if raw is None:
        return None, "snapshot row carries no map"
    try:
        return int(raw), ""
    except (TypeError, ValueError):
        return None, "snapshot map is not a number: %r" % (raw,)


def read_member(
    name: str,
    row: Mapping[str, object] | None,
    crossing: Crossing,
    max_age_seconds: int = SNAPSHOT_MAX_AGE_SECONDS,
) -> dict:
    """Where one member is, or why that cannot be said.

    `row` is an overseer_snapshot row as map_server._fetch_family selects it:
    at least `map_id` and `age_seconds`. None means the query returned nothing
    for this member, which is the ordinary case for somebody logged out, and
    which is UNREADABLE rather than any kind of "not there" - see the module
    docstring for why that distinction is the whole point.
    """
    map_id, refusal = _readable_map(row, max_age_seconds)
    if map_id is None:
        return {"name": name, "where": UNREADABLE, "map_id": None, "reason": refusal}
    if map_id == crossing.origin_map:
        where = ORIGIN
    elif map_id == crossing.destination_map:
        where = DESTINATION
    else:
        where = ELSEWHERE
    return {"name": name, "where": where, "map_id": map_id, "reason": ""}


def read_party(
    crossing: Crossing,
    rows: Iterable[Mapping[str, object]] | None,
    max_age_seconds: int = SNAPSHOT_MAX_AGE_SECONDS,
) -> list[dict]:
    """One reading per roster member, in name order, however many rows arrived.

    DRIVEN BY THE ROSTER AND NOT BY THE ROWS. A member with no row must produce
    a reading saying so; iterating the rows instead would produce four readings
    for a party of five and a count that looks complete. Rows for names not on
    the roster are ignored: the crossing is about these five.
    """
    by_name: dict[str, Mapping[str, object]] = {}
    for row in rows or ():
        name = row.get("name")
        if name is None:
            continue
        # Last row wins, and the sort below makes that deterministic rather
        # than dependent on cursor order.
        by_name[str(name)] = row
    return [
        read_member(name, by_name.get(name), crossing, max_age_seconds)
        for name in sorted(crossing.members)
    ]


def standing(readings: Sequence[Mapping[str, object]]) -> str:
    """The party's one standing, from the readings.

    THE ORDER OF THESE TESTS IS THE FAIL-CLOSED RULE, written out.

    BLIND FIRST, ahead of everything. One unreadable member outranks four
    members read on the far side, because "four of five are on Kalimdor" is
    not evidence about the fifth, and ARRIVED is a claim about all five. This is
    the single branch that separates this module from a decision layer that
    treats a missing row as a negative reading.

    SCATTERED BEFORE SPLIT because a member on a third map is a worse fact than
    a member on the wrong end of a known route, and reporting it as SPLIT would
    describe it with a vocabulary that does not fit it.
    """
    where = [str(r.get("where")) for r in readings]
    if not where:
        # No roster is not an empty crossing, it is a caller that lost its
        # roster. `plan` refuses to build one; this refuses to grade one.
        return BLIND
    if UNREADABLE in where:
        return BLIND
    if ELSEWHERE in where:
        return SCATTERED
    if ORIGIN in where and DESTINATION in where:
        return SPLIT
    if all(w == DESTINATION for w in where):
        return ARRIVED
    return ASSEMBLED


def leg_blockers(leg: Leg, available: Iterable[str] = OBSERVABLE) -> tuple[str, ...]:
    """The facts this leg needs and this world does not have, in leg order."""
    have = frozenset(available)
    return tuple(fact for fact in leg.needs if fact not in have)


def first_blocked_leg(available: Iterable[str] = OBSERVABLE) -> Leg | None:
    """The earliest leg that cannot be attempted, or None if all six can.

    EARLIEST AND NOT WORST. A crossing is a chain: being able to disembark is
    worth nothing while there is no way to reach the dock, and reporting the
    later blocker would send somebody to solve the wrong problem first.
    """
    for leg in LEGS:
        if leg_blockers(leg, available):
            return leg
    return None


# WHAT THE MODULE SAYS IT CAN DO ACROSS AN OCEAN (mod-overseer#671).
#
# Everything above is about a crossing THIS process would drive, and it still
# refuses: nothing it can read says who is aboard. Since mod-overseer#671 the
# worldserver drives one itself, inside a dungeon run: its coordinator walks
# the leader to a surveyed berth, steps the family onto the docked transport,
# and walks them off at the far landing. It reports that in `overseer_build`
# as `crossing = boards`. A realm with no such row runs a module that refuses
# every crossing, and reads exactly as before.
#
# ONLY A DUNGEON DOOR MAY LEAN ON IT. The module crosses for a dungeon run and
# nothing else: every other aim is an `at:` point the module refuses across a
# map. So `dungeon_door_blocked` is what the council asks about a door, and
# `first_blocked_leg` stays what every other caller asks.
MODULE_BOARDS = "boards"

_module_crossing = ""


def note_module_crossing(value: str | None) -> bool:
    """Record the module's `crossing` build fact. True when it changed."""
    seen = str(value or "").strip().lower()
    global _module_crossing
    changed = seen != _module_crossing
    _module_crossing = seen
    return changed


def module_boards() -> bool:
    """True when the running module reports it boards transports itself."""
    return _module_crossing == MODULE_BOARDS


def dungeon_door_blocked() -> bool:
    """True while no crossing to a dungeon door on the other continent can be
    made: neither this process nor the module can make one."""
    return not module_boards() and first_blocked_leg() is not None


def decide(
    crossing: Crossing,
    rows: Iterable[Mapping[str, object]] | None,
    available: Iterable[str] = OBSERVABLE,
    max_age_seconds: int = SNAPSHOT_MAX_AGE_SECONDS,
) -> dict:
    """One safe next action, from rows the caller fetched and nothing else.

    Returns a verdict dict rather than a bare action so that every refusal
    carries the reason with it. A caller that logs only `action` gets "hold"
    forever with no way to find out what would end it, which is the failure mode
    a permanently-true alarm has: it trains itself away.
    """
    readings = read_party(crossing, rows, max_age_seconds)
    state = standing(readings)
    verdict = {
        "standing": state,
        "action": WAIT,
        "leg": "",
        "blocked_on": (),
        "members": readings,
        "reason": "",
        "origin_map": crossing.origin_map,
        "destination_map": crossing.destination_map,
    }

    if state == BLIND:
        unread = tuple(r["name"] for r in readings if r["where"] == UNREADABLE)
        if unread:
            why = "; ".join(
                "%s: %s" % (r["name"], r["reason"])
                for r in readings
                if r["where"] == UNREADABLE
            )
            verdict["reason"] = (
                "the world is not answering for %s (%s); nothing is decided "
                "about a party that cannot be seen" % (_and_list(unread), why)
            )
        else:
            verdict["reason"] = "no roster to read"
        verdict["unreadable"] = unread
        return verdict

    if state == SCATTERED:
        astray = [(r["name"], r["map_id"]) for r in readings if r["where"] == ELSEWHERE]
        verdict["action"] = ALARM
        verdict["reason"] = (
            "%s on neither end of this crossing (%s); no drive in this system "
            "aims across a map boundary, so this does not resolve itself"
            % (
                _and_list([n for n, _ in astray]),
                ", ".join("%s on map %d" % (n, m) for n, m in astray),
            )
        )
        verdict["astray"] = tuple(astray)
        return verdict

    if state == SPLIT:
        behind = tuple(r["name"] for r in readings if r["where"] == ORIGIN)
        ahead = tuple(r["name"] for r in readings if r["where"] == DESTINATION)
        verdict["action"] = ALARM
        verdict["reason"] = (
            "the party is across two maps: %s still on map %d, %s already on "
            "map %d. `follow` only acts while the master is on the same map, "
            "and both `at:` and `trigger:` aims refuse when the map differs, so "
            "nothing here can close this gap"
            % (
                _and_list(behind),
                crossing.origin_map,
                _and_list(ahead),
                crossing.destination_map,
            )
        )
        verdict["behind"] = behind
        verdict["ahead"] = ahead
        return verdict

    if state == ARRIVED:
        verdict["action"] = ARRIVE
        verdict["reason"] = "every member observed on map %d within %d seconds" % (
            crossing.destination_map,
            max_age_seconds,
        )
        return verdict

    # ASSEMBLED: everybody read, everybody on the origin map. The only state in
    # which starting a crossing is even a question.
    blocked = first_blocked_leg(available)
    if blocked is None:
        verdict["action"] = CROSS
        verdict["leg"] = LEGS[0].name
        verdict["reason"] = "every member on map %d and every leg's facts in hand" % (
            crossing.origin_map,
        )
        return verdict

    missing = leg_blockers(blocked, available)
    verdict["action"] = blocked.fails_closed_to
    verdict["leg"] = blocked.name
    verdict["blocked_on"] = missing
    verdict["reason"] = "cannot %s: %s" % (
        blocked.name,
        "; ".join("no %s (%s)" % (fact, FACT_SOURCES[fact]) for fact in missing),
    )
    return verdict


def say(verdict: Mapping[str, object]) -> str:
    """The verdict as one log line, including when the answer is 'nothing'.

    IT SAYS SOMETHING EVEN WHEN IT DID NOTHING, for the reason questshare.say
    gives: "nothing to do" and "everything was refused because no dock position
    exists" are one line apart rather than indistinguishable silence.
    """
    action = str(verdict.get("action", ""))
    reason = str(verdict.get("reason", ""))
    leg = str(verdict.get("leg", ""))
    head = "crossing %s" % str(verdict.get("standing", "?"))
    if leg:
        head += " at '%s'" % leg
    return "%s: %s%s" % (head, action, (" - " + reason) if reason else "")


# --- turning a verdict into something the world could carry out ----------
#
# ONE COMMAND SHAPE EXISTS AND IT IS SAME-MAP ONLY. `overseer_roster.travel_npc`
# takes a role keyword, a bare creature entry, or `at:<map>:<x>,<y>,<z>` naming
# ground, and ResolveTravelTarget refuses the last of those unless the character
# is already on that map. So the walk-on leg - and only the walk-on leg - is
# expressible today. The five before it have no command form at all, which is
# why this section is short and why `decide` returns HOLD rather than an order
# nothing could execute.


def aim_at_place(map_id: int, x: float, y: float, z: float) -> str:
    """An `at:` aim in the exact grammar ResolveTravelTarget parses.

    THE SEPARATORS ARE THE CONTRACT. The parser reads `m ':' x ',' y ',' z` off
    an istringstream and CHECKS each separator rather than assuming it, so a
    value assembled any other way is refused in the world with no explanation
    reaching here.

    THE WIDTH IS THE OTHER HALF OF THE CONTRACT, and it is the one that fails
    silently. `travel_npc` is VARCHAR(32). MySQL truncates an over-long value
    rather than refusing it outside strict mode, and a truncated aim is one the
    parser can never read back: the errand is written, never resolves, and looks
    exactly like a character who simply did not walk. Raising here is the only
    place that failure can still be seen. The limit is imported from travel.py
    rather than restated, because two copies of a column width is how they drift.
    """
    aim = "at:%d:%s,%s,%s" % (int(map_id), _coord(x), _coord(y), _coord(z))
    if len(aim) > travel.COLUMN_WIDTH:
        raise ValueError(
            "aim does not fit overseer_roster.travel_npc (%d chars, limit %d): %s"
            % (len(aim), travel.COLUMN_WIDTH, aim)
        )
    return aim


def _coord(value: float) -> str:
    """A coordinate as short as it can be without changing where it points.

    Trailing zeros cost characters against a 32-character limit that a real
    aim is already close to, and `-753.5960083007812` says nothing more about
    where a door is than `-753.596` does. Two decimals is well under a yard.
    """
    text = "%.2f" % float(value)
    text = text.rstrip("0").rstrip(".")
    return text if text not in ("", "-") else "0"


def approach(
    entrance: Mapping[str, object] | None, destination_map: int = KALIMDOR
) -> dict:
    """The walk-on aim for an entrances.json record, or the reason there is none.

    THIS REFUSES TODAY, AND THE REFUSAL IS THE DELIVERABLE. `entrances.json` is
    generated by tools/gen_geometry.py out of the world database's areatrigger
    rows, and it keeps `map`, `x` and `y`. It does not keep `z`. The Wailing
    Caverns record is exactly `{"map": 1, "x": -753.596..., "y": -2212.78...}`.

    An `at:` aim without a z is not an aim, and a z chosen here would be a guess
    about footing at a cave mouth in the Barrens - which is the same guess
    mod-overseer#121 catalogues, where a staging Z was carried over from a
    trigger that stood on a different floor and the party was aimed into rock.
    So this names the missing field and stops.

    THE HONEST FIX IS NOT A NUMBER, IT IS A DIFFERENT AIM. The C++ side already
    has one: `trigger:<areatrigger id>` walks to the door AND knocks on it, and
    takes both the position and the z from the areatrigger table so the two
    cannot drift. That needs Wailing Caverns' entry trigger id, which is not in
    this repository and is not invented here.
    """
    if not entrance:
        return {"usable": False, "aim": "", "refused": "no entrance record"}
    for field in ("map", "x", "y"):
        if entrance.get(field) is None:
            return {
                "usable": False,
                "aim": "",
                "refused": "entrance record has no %s" % field,
            }
    try:
        entrance_map = int(entrance["map"])
    except (TypeError, ValueError):
        return {
            "usable": False,
            "aim": "",
            "refused": "entrance map is not a number: %r" % (entrance["map"],),
        }
    if entrance_map != int(destination_map):
        return {
            "usable": False,
            "aim": "",
            "refused": "entrance is on map %d, not the crossing's map %d"
            % (entrance_map, int(destination_map)),
        }
    if entrance.get("z") is None:
        return {
            "usable": False,
            "aim": "",
            "refused": "entrance record carries no z, and %s"
            % FACT_SOURCES[FACT_TARGET_FOOTING],
        }
    try:
        aim = aim_at_place(
            entrance_map,
            float(entrance["x"]),
            float(entrance["y"]),
            float(entrance["z"]),
        )
    except (TypeError, ValueError) as exc:
        return {"usable": False, "aim": "", "refused": str(exc)}
    return {"usable": True, "aim": aim, "refused": ""}


def _and_list(names: Sequence[str]) -> str:
    """Names as a person would read them out. Empty is "nobody", not ""."""
    ordered = sorted(str(n) for n in names)
    if not ordered:
        return "nobody"
    if len(ordered) == 1:
        return ordered[0]
    return "%s and %s" % (", ".join(ordered[:-1]), ordered[-1])
