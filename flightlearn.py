"""Which taxi node a character should go and learn, so the family can fly.

infra#4206. mod-overseer has been able to walk a character to a flight master
ON PURPOSE since mod-overseer#388 - `travel_npc = 'flight master:<nodeId>'` -
and it says so in its own logs when a route is refused:

    'Grug' is sent to 'at:1:-3618.4,-4437.9,13.5' 5329 yards away and could fly
    node 79 to node 80, but has not discovered node 40 on that route - trying
    the next node out, or walking. 'flight master:40' would go learn it

Nothing in this process ever wrote that aim. The aims the control plane
actually issues are `vendor`, `repair`, `banker`, `auctioneer` and ground
walks, so the family's flight network has never grown by one node since it was
created, and every trip that needs a node nobody has ends as a walk that
terrain can refuse outright. This module is the pure half of the missing
caller: given what a character knows, where it stands and who is standing at
each node, WHICH node it should be sent to learn. `bridge` owns the reads and
the write; nothing here touches a database or a clock.

NO COORDINATE IS AUTHORED HERE, OR ANYWHERE ON THIS PATH. The aim names a NODE
and mod-overseer resolves the flight master's own spawn row on the character's
map - the same restraint `craft_supply.supply_trip` takes for a named vendor
entry, and for the same stated reason: a hand-written z has no navmesh under
it, which once lifted one character and killed another in the void at full
health. The node positions below are read only to RANK candidates and to ask
whether anything is standing at them; not one of them ever becomes an aim.

THIS DOES NOT MIRROR THE MODULE'S ROUTE SEARCH, AND THAT IS A MEASUREMENT
RATHER THAN A PREFERENCE. The obvious shape for this file is "recompute the
route mod-overseer refused and take the hop it named". `ConsiderFlight` asks
mod-playerbots' `sTravelNodeMap.FindTaxiPath`, which is a BFS over TravelNodes
rather than over TaxiPath.dbc's own edges - and the two disagree. Measured on
2026-09-19 against the pinned client data: a plain TaxiPath BFS answers
79 -> 39 directly and 79 -> 39 -> 80 for the pair in the log line above, while
the module routed 79 -> 40 -> 80 and named 40. A second copy of a search that
already answers differently is a second opinion that will drift, which is the
argument `travel.is_ground_aim` makes for refusing to re-parse an `at:` aim.
So the question asked here is the one this side can answer on its own facts:
WHICH NODE WOULD THIS CHARACTER MOST LIKE TO HAVE THAT IT HAS NOT GOT.

AND ECHOING THE MODULE'S OWN SUGGESTION WOULD HAVE ISSUED AN ERRAND THAT CAN
NEVER FINISH. Node 40 is the HORDE flight point in Gadgetzan (Bulkrek Ragefist,
creature 7824, faction 29); node 39 is the ALLIANCE one 180 yards away (Bera
Stonehammer, creature 7823) and is the one the family already boards at. The
family is Alliance - races 1, 3 and 7 - so node 40 is a node no member of it
can ever learn, and `ResolveTravelTarget`'s own faction gate would refuse the
aim after the walk. mod-overseer's `unknownHop` scan does not ask whose network
a hop belongs to, so its suggestion is honest about the route and wrong about
the errand. infra#3703's rule is that an errand which cannot finish must not
hold the family's one travel column, so the team gate below is not politeness:
it is the difference between a trip and a lease spent on nothing.

THE THREE GATES A CANDIDATE HAS TO PASS, AND WHY NONE IS OPTIONAL.

  1. IT HAS TO BE ON THIS CHARACTER'S NETWORK. `ObjectMgr::GetNearestTaxiNode`
     skips a node whose `MountCreatureID[team == TEAM_ALLIANCE ? 1 : 0]` is
     zero, so the pair of mount ids IS the team gate - not the faction of
     whatever creature stands there.
  2. SOMETHING HAS TO BE STANDING AT IT. TaxiNodes.dbc carries rows that pass
     every other mechanical test and have no flight master anywhere near them.
     mod_overseer.cpp names its own example: node 168, "Filming", in Elwynn
     Forest, which "carries an alliance mount id, and has a real taxi path to
     Stormwind" while "the nearest creature with UNIT_NPC_FLAG_FLIGHTMASTER is
     740 yards away, so nothing can ever discover it". Measured here on the
     same day: the three nodes nearest the family's own destination that pass
     gate 1 alone are "Quest - Caverns of Time (Intro Flight Path) (End)",
     "(Start)" and "Quest - Dustwallow - Alcaz Survey End". Without this gate
     the pass would spend the column walking to scenery.

  3. AND IT HAS TO BE WHAT THAT SOMETHING IS STANDING THERE FOR. Gate 2 asks
     whether anything is near the node; this asks whether the node is what is
     near the creature. Measured on the same day: creature 4321 is 3.6 yards
     from node 32, Theramore - and 8.8 and 10.0 yards from nodes 180 and 181,
     "Quest - Dustwallow - Alcaz Survey Start" and "... End". All three pass
     gate 2. Without gate 3 a discovery errand would spend four thousand yards
     and the family's one travel column walking to Theramore to learn a row
     that is scenery, while Theramore's own node went on being missing.
     `node_of` is that gate, and it is `ResolveTravelTarget`'s own tie-break
     read the other way round.

  The radius for gate 2 is mod-overseer's own `TRAVEL_FLIGHT_NODE_MATCH_YARDS`,
  mirrored in `travel.FLIGHT_NODE_MATCH_YARDS`, because that is the radius
  `ResolveTravelTarget` will re-apply on the other side of the column. A looser
  one here picks nodes the module then refuses; a tighter one picks fewer nodes
  than it would accept.

NEAREST TO THE CHARACTER, NOT NEAREST TO WHERE IT IS GOING. Both were measured
on 2026-09-19 against the live roster. Ranking by the destination returns
Mudsprocket at 2703 yards and Theramore at 3449 for every member of the family,
because the destination is across a mountain range from all of them; ranking by
the character returns Thalanaar at 2119 and Cenarion Hold at 1880 - real
Alliance flight points, on the ground they are standing on. A node is worth the
same on every future route whichever trip paid for it, so the cheap one is the
one to buy, and a walk the family can actually complete is the only kind that
ends with a taximask bit set.

AN UNREADABLE TAXIMASK IS NOT AN EMPTY ONE. `characters.taximask` is a string
of space-separated 32-bit words and a character that has never been saved, or a
world image that spells the column differently, produces something this cannot
read. Treating that as "knows nothing" would make every node in the world look
undiscovered and send the family after whichever happened to be nearest, for
ever. `known_nodes` answers None for it, and `choose` refuses on None.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import travel

# The two sides, spelled as the words that appear in the log lines rather than
# as the core's numeric TeamId, because nothing here indexes anything by them.
TEAM_ALLIANCE = "alliance"
TEAM_HORDE = "horde"

# Which side each playable race belongs to (ChrRaces.dbc, and the same table
# `bridge.RACE_NAMES` is keyed by). Death knights aside, a character's race
# decides its team for the whole of its life, so this is a fact rather than a
# reading - but it is written out in full because a race missing from it must
# answer "no side I can name" rather than default to one.
TEAMS = {
    1: TEAM_ALLIANCE,  # Human
    2: TEAM_HORDE,  # Orc
    3: TEAM_ALLIANCE,  # Dwarf
    4: TEAM_ALLIANCE,  # Night Elf
    5: TEAM_HORDE,  # Undead
    6: TEAM_HORDE,  # Tauren
    7: TEAM_ALLIANCE,  # Gnome
    8: TEAM_HORDE,  # Troll
    10: TEAM_HORDE,  # Blood Elf
    11: TEAM_ALLIANCE,  # Draenei
}

# UNIT_NPC_FLAG_FLIGHTMASTER (Unit.h:764), the flag `travel.ROLES` names as a
# string and nothing on this side has ever needed as a number until now. The
# survey that finds who is standing at a node has to ask the creature table for
# it, and a bare 8192 in a WHERE clause is a fact about the game hiding in an
# adapter. It is the same flag `TravelRoles` keys the `flight master` keyword
# on, so the two sides are looking for the same creatures.
FLIGHT_MASTER_NPC_FLAG = 0x2000

# HOW FAST A LONG WALK ACTUALLY GOES, mod-overseer's own measured effective
# rate rather than its walk speed: straight-line distance against wall-clock
# arrival, so pathing is already inside the number.
# `townslot.GATHER_LEASE_SECONDS` derives itself from the same reading and
# quotes it in full - 2391 yards in 345 seconds.
WALK_YARDS_PER_MINUTE = 416.0

# HOW LONG AFTER AN ARRIVAL ANYBODY NOTICES. The pass that would see it runs on
# its own clock, so a lease dimensioned to the walk alone expires while the
# walk is finishing. One goal interval, the same allowance
# `townslot.GATHER_LEASE_SECONDS` adds for the same reason.
ARRIVAL_SEEN_SECONDS = 60.0

# HOW FAR A DISCOVERY WALK MAY BE, AND WHY IT IS THIS NUMBER.
#
# The bound is a LEASE, not an opinion about ambition: this errand takes the
# family's one travel column, so it has to be a trip that can end inside the
# lease it is given or it becomes exactly the errand infra#3703 says must not
# hold the column for ever. So the two numbers are DERIVED FROM EACH OTHER
# below rather than chosen separately, which is the only way they cannot drift
# into disagreeing.
#
# THE CEILING ON BOTH IS THE MODULE'S OWN BACKSTOP. mod-overseer gives up on a
# target it cannot reach after `TRAVEL_BACKSTOP_SECONDS`, which is 20 minutes,
# and `townslot.ORPHAN_LEASE_SECONDS` is the same 1200 for the same stated
# reason: "past it, the world has stopped believing in the errand too". At 416
# yards a minute that is 8320 yards, so a bound inside it is a bound the world
# will honour rather than one this process would be alone in believing.
#
# 5000 IS MEASURED, NOT ROUNDED DOWN FROM THAT. Against the live roster on
# 2026-09-19 the nearest node each member could actually learn was:
#
#     leader Grug   Mudsprocket, Dustwallow Marsh      4001 yards
#     Bork/Og/Grog  Cenarion Hold, Silithus            3254 yards
#     Ugga          Theramore, Dustwallow Marsh        5131 yards
#
# and an earlier reading the same day, with the family in Un'Goro, put them at
# 1880 to 4226. A 3000-yard bound - one `GATHER_LEASE_SECONDS` of walking -
# refuses every one of those, which is a caller that would have shipped and
# never fired: the same "written and never read" failure this issue is about,
# one level up. 5000 covers the measured spread and stays 3320 yards inside
# what the world's own backstop will wait for.
REACH_YARDS = 5000.0


def lease_for(yards: float) -> float:
    """How long a walk of `yards` needs before anybody may take the column.

    The town slot is handed this for `FLIGHT_CLAIMANT`, so the lease and the
    bound above are one number expressed twice rather than two numbers that
    have to be kept in step. A trip this refuses to bound - a negative or
    unreadable distance - gets nothing, and `townslot` then applies its own
    ordinary lease, which is the fail-closed direction.
    """
    try:
        walk = float(yards)
    except (TypeError, ValueError):
        return 0.0
    if walk <= 0:
        return 0.0
    return walk / WALK_YARDS_PER_MINUTE * 60.0 + ARRIVAL_SEEN_SECONDS


@dataclass(frozen=True)
class Node:
    """One row of TaxiNodes.dbc, as `taxinodes.json` projects it.

    `horde` and `alliance` are the two `MountCreatureID` entries, kept as the
    raw creature ids rather than as booleans because zero-or-not is the game's
    own test and a reader who wants to check it against the DBC should see the
    same number the DBC holds.
    """

    id: int
    map_id: int
    x: float
    y: float
    z: float
    name: str = ""
    horde: int = 0
    alliance: int = 0

    def serves(self, team: str) -> bool:
        """Is this node on `team`'s network at all?"""
        if team == TEAM_ALLIANCE:
            return bool(self.alliance)
        if team == TEAM_HORDE:
            return bool(self.horde)
        return False


@dataclass(frozen=True)
class Master:
    """One live flight master spawn, straight out of `acore_world.creature`.

    `entry` rides along for the log line only. Nothing here aims at it: the
    aim names the NODE and mod-overseer resolves the creature itself, which is
    what keeps the resolution in one place.
    """

    map_id: int
    x: float
    y: float
    entry: int = 0
    name: str = ""


@dataclass(frozen=True)
class Errand:
    """Either the aim that learns a node, or why nobody is being sent.

    The same two-field shape `travel.ForgeAim` and `gatheraim.Choice` already
    use, so a caller reads all three the same way: a non-empty `refused` is a
    promise that `aim` is empty, and `refused` is a whole sentence rather than
    a code.
    """

    aim: str = ""
    node: int = 0
    node_name: str = ""
    yards: float = 0.0
    master: int = 0
    refused: str = ""
    why: str = ""


def load_nodes(static_dir: str) -> tuple:
    """The frozen client taxi node table, from the file beside the code.

    Loaded the same way `armory.TalentBook` loads talents.json and `Geometry`
    loads zones.json: once, from a committed projection, so the suite runs
    stdlib-only with no cluster and no client data. `tools/taxi_nodes_from_dbc.py`
    is what writes it and what asserts it still agrees with the realm.
    """
    with open(os.path.join(static_dir, "taxinodes.json"), encoding="utf-8") as f:
        book = json.load(f)
    return tuple(
        Node(
            id=int(row["id"]),
            map_id=int(row["map"]),
            x=float(row["x"]),
            y=float(row["y"]),
            z=float(row["z"]),
            name=str(row.get("name") or ""),
            horde=int(row.get("horde") or 0),
            alliance=int(row.get("alliance") or 0),
        )
        for row in book["nodes"]
    )


NODES = load_nodes(os.path.dirname(os.path.abspath(__file__)))


def team_of(race_id):
    """Which side a race is on, or "" for a race this does not know.

    "" is a refusal and never a default. Guessing a side would put the team
    gate the wrong way round for that character, and the whole point of the
    gate is that the wrong side is a flight master who will not speak to them.
    """
    try:
        return TEAMS.get(int(race_id), "")
    except (TypeError, ValueError):
        return ""


def known_nodes(taximask):
    """The set of node ids this taximask holds, or None if it cannot be read.

    `characters.taximask` is a string of space-separated unsigned 32-bit words,
    least significant word first, and bit N-1 of word W is node W*32 + N. The
    off-by-one is the game's: node ids start at 1 and bits start at 0.

    NONE IS NOT AN EMPTY SET AND THE DIFFERENCE IS THE WHOLE POINT. A mask
    nobody can read means "I do not know what this character has discovered";
    an empty set means "it has discovered nothing", which would make every node
    in the world a candidate. The first must never be allowed to read as the
    second - that is the shape that has produced four false greens on this
    project already, and here it would spend the family's travel column on a
    walk chosen from no information at all.
    """
    if taximask is None:
        return None
    words = str(taximask).split()
    if not words:
        return None
    known = set()
    for index, word in enumerate(words):
        try:
            value = int(word)
        except (TypeError, ValueError):
            return None
        if value < 0:
            return None
        for bit in range(32):
            if value >> bit & 1:
                known.add(index * 32 + bit + 1)
    return frozenset(known)


def knows(taximask, node_id):
    """True, False, or None when the mask cannot be read."""
    holds = known_nodes(taximask)
    if holds is None:
        return None
    try:
        return int(node_id) in holds
    except (TypeError, ValueError):
        return None


def learned(before, after, node_id) -> bool:
    """Did this errand actually put `node_id` into the character's taximask?

    THE POSITIVE ASSERTION, AND IT IS THE ONLY THING THAT COUNTS AS SUCCESS.
    `overseer_command.status = 'delivered'` proves nothing and neither does an
    emptied `travel_npc` - mod-overseer releases the errand whether the node
    was learned or not, and says so itself: "node {} was {learned | not learned
    - see the line above}". The bit flipping is the change; everything else is
    an attempt.

    FALSE FOR EVERY READING THIS CANNOT MAKE. An unreadable mask on either
    side, a node that was ALREADY held before the walk, an unchanged mask - all
    of them are "not yet", never "done". A check that can only report good news
    is worse than no check, and the costliest version of that on this project
    was a query whose empty result read as a pass.
    """
    was = knows(before, node_id)
    now = knows(after, node_id)
    if was is None or now is None:
        return False
    return bool(now and not was)


def answering_master(node: Node, masters, match_yards=None):
    """The flight master standing at `node`, or None if nothing is.

    The nearest spawn to the NODE's own position wins, which is the rule
    `ResolveTravelTarget` applies on the other side of the column: "a duplicate
    spawn row further from the node than another candidate is the wrong copy to
    send anybody to".

    PLANAR, like every other reach question in this package. A flight master is
    reached across the floor, not up a tower, and the node's own z is the
    landing pad's rather than the creature's.
    """
    limit = travel.FLIGHT_NODE_MATCH_YARDS if match_yards is None else match_yards
    best = None
    for master in masters or ():
        if int(master.map_id) != int(node.map_id):
            continue
        dx = float(master.x) - float(node.x)
        dy = float(master.y) - float(node.y)
        d2 = dx * dx + dy * dy
        if d2 > float(limit) * float(limit):
            continue
        if best is None or d2 < best[0]:
            best = (d2, master)
    return None if best is None else best[1]


def node_of(master: Master, nodes=None) -> int:
    """Which node this flight master actually stands at, or 0.

    THE SAME TIE-BREAK `ResolveTravelTarget` MAKES, POINTING THE OTHER WAY.
    That side picks, out of the spawns near a node, the one nearest the node -
    "a duplicate spawn row further from the node than another candidate is the
    wrong copy to send anybody to". This picks, out of the nodes near a spawn,
    the one nearest the spawn, and the two together make the pairing a
    one-to-one that neither side can disagree about.

    WHY IT IS NEEDED AT ALL, measured 2026-09-19 against the live world. Node
    32 is Theramore and creature 4321 stands 3.6 yards from it. Two more rows
    sit on top of the same creature: node 180, "Quest - Dustwallow - Alcaz
    Survey Start", 8.8 yards away, and node 181, "... End", 10.0 yards away.
    All three pass the `answering_master` radius, so without this a discovery
    errand would spend four thousand yards and the family's one travel column
    to walk to Theramore and learn a row that is scenery. `answering_master`
    asks whether ANYTHING is standing there; this asks whether that thing is
    standing there FOR THIS NODE.

    ALL NODES ON THE MAP, NOT JUST THIS TEAM'S. A creature nearest to the other
    side's node is that node's creature, and a candidate that has to reach past
    it is not this master's node either.
    """
    best = None
    for node in NODES if nodes is None else nodes:
        if int(node.map_id) != int(master.map_id):
            continue
        dx = float(node.x) - float(master.x)
        dy = float(node.y) - float(master.y)
        d2 = dx * dx + dy * dy
        # Ties broken by the lower id so the pairing is the same every run;
        # two nodes at identical coordinates is not a state this world has, and
        # a stable answer is worth more than an arbitrary one if it ever does.
        if best is None or (d2, node.id) < best:
            best = (d2, node.id)
    return 0 if best is None else best[1]


def _given_up_on(skip) -> set:
    """The node ids the caller has already spent its patience on.

    One reading for both sides, so `candidates`' filter and the count `choose`
    puts in its refusal can never disagree about what was skipped - including
    about the de-duplication, which is what makes "2 given up on" the number of
    NODES rather than the number of times the caller named one.
    """
    return {int(node) for node in (skip or ())}


def _through_the_gates(
    node: Node, *, here, team, known, passed_over, masters, table, stands_at: dict
):
    """The flight master answering for `node`, or None if a gate refuses it.

    The module note's three gates, asked in the order that costs least: the
    field tests that read one row first, the two table scans last, so a node
    ruled out by its map or by the taximask never pays for a distance sweep.
    Split out of `candidates` so the gates read as the list the note describes
    (Grug - Elder, cyclomatic cap); no gate moved, and none of them is optional.

    `stands_at` is the caller's memo of `node_of` per master and is written
    through: three scenery rows sitting on one creature would otherwise scan
    the node table three times to reach the same answer.
    """
    if int(node.map_id) != here:
        return None
    if node.id in known or node.id in passed_over:
        return None
    # GATE 1, the team gate - the pair of MountCreatureID entries, not the
    # faction of whatever happens to stand there.
    if not node.serves(team):
        return None
    # GATE 2, is anything standing at it at all.
    master = answering_master(node, masters)
    if master is None:
        return None
    # GATE 3, and is that something standing there FOR THIS NODE.
    if master not in stands_at:
        stands_at[master] = node_of(master, table)
    if stands_at[master] != node.id:
        return None
    return master


def candidates(
    *, standing, known, team, nodes=None, masters=(), reach_yards=REACH_YARDS, skip=()
):
    """Every node this character could go and learn, nearest first.

    `standing` is the character's own snapshot row - {"map_id", "pos_x",
    "pos_y"} - so the ranking is measured from where it IS, not from where the
    leader is or from where it is going. See the module note for the
    measurement behind that choice.

    `skip` is the set of nodes the caller has already spent its patience on. It
    is a SEPARATE argument from `known` on purpose: a node given up on is not a
    node discovered, and folding the two together would make the give-up
    memory read as a taximask bit - which is the fabricated-state shape this
    package keeps paying for. Skipping moves the pass on to the next candidate
    rather than stalling it on the same one for ever, which is the other half
    of infra#3703's rule.

    The three gates themselves are `_through_the_gates`. What is left here is
    the reading of the snapshot row, the reach bound and the ranking.

    Returns a list of (yards, Node, Master). Empty is an ordinary answer.
    """
    if not standing or known is None or not team:
        return []
    passed_over = _given_up_on(skip)
    try:
        here = int(standing["map_id"])
        px = float(standing["pos_x"])
        py = float(standing["pos_y"])
        reach = float(reach_yards)
    except (TypeError, ValueError, KeyError):
        return []
    table = NODES if nodes is None else nodes
    # One memo for the whole sweep rather than one per node, so gate 3 costs a
    # table scan per creature instead of a scan per node that creature is near.
    stands_at: dict = {}
    out = []
    for node in table:
        master = _through_the_gates(
            node,
            here=here,
            team=team,
            known=known,
            passed_over=passed_over,
            masters=masters,
            table=table,
            stands_at=stands_at,
        )
        if master is None:
            continue
        dx = float(node.x) - px
        dy = float(node.y) - py
        d2 = dx * dx + dy * dy
        if d2 > reach * reach:
            continue
        # Sorted on the SQUARE, and the root is taken only for the one
        # candidate that wins, because a root per node is arithmetic for its
        # own sake - the same argument `travel.within_focus` makes.
        out.append((d2, node.id, node, master))
    out.sort(key=lambda row: (row[0], row[1]))
    return [(row[0] ** 0.5, row[2], row[3]) for row in out]


def choose(
    *,
    character,
    standing,
    taximask,
    race,
    nodes=None,
    masters=(),
    reach_yards=REACH_YARDS,
    skip=(),
):
    """The node `character` should be sent to learn, or why there is not one.

    Every fact comes in as an argument. `taximask` is the raw column value so
    that "cannot be read" reaches this function as a state rather than as an
    exception somewhere upstream.
    """
    # EVERY PART OF THE ROW, NOT JUST THE MAP. `candidates` answers the empty
    # list for a row it cannot read, and the refusal below that would turn
    # that into "already holds every flight point within reach" - a sentence
    # that is not merely unhelpful but FALSE, and false in the direction that
    # reads as success. Where a reading is missing, this has to say so.
    if (
        not standing
        or standing.get("map_id") is None
        or standing.get("pos_x") is None
        or standing.get("pos_y") is None
    ):
        return Errand(
            refused=(
                "nobody can say where %s is standing - overseer_snapshot has no "
                "fresh row for it, so the family is either offline or the module "
                "has stopped writing the snapshot" % (character or "it",)
            ),
            why="no standing row.",
        )

    # The name every refusal below spells, read once. Four copies of the same
    # fallback is four places for it to drift apart; the sentence above keeps
    # its own word because it reads "where IT is standing".
    who = character or "that character"

    known = known_nodes(taximask)
    if known is None:
        return Errand(
            refused=(
                "%s's taximask cannot be read, and a mask nobody can read is not "
                "an empty one - treating it as empty would make every flight point "
                "in the world look undiscovered and send the family after whichever "
                "is nearest, for ever" % (who,)
            ),
            why="unreadable taximask.",
        )

    team = team_of(race)
    if not team:
        return Errand(
            refused=(
                "%s's race (%r) is not one this process can put on a side, and a "
                "guess would aim it at a flight master that will never speak to it"
                % (who, race)
            ),
            why="no team for this race.",
        )

    found = candidates(
        standing=standing,
        known=known,
        team=team,
        nodes=nodes,
        masters=masters,
        reach_yards=reach_yards,
        skip=skip,
    )
    if not found:
        given_up = len(_given_up_on(skip))
        return Errand(
            refused=(
                "%s already holds every %s flight point within %d yards of it on "
                "map %s that a flight master actually stands at - %d node(s) known "
                "in all%s - so there is nothing on this map left for it to walk to "
                "and learn"
                % (
                    who,
                    team,
                    int(reach_yards),
                    standing.get("map_id"),
                    len(known),
                    ", and %d given up on" % given_up if given_up else "",
                )
            ),
            why="no reachable undiscovered node on this map.",
        )

    yards, node, master = found[0]
    aim = travel.flight_master_aim(node.id)
    if not aim:
        # `flight_master_aim` refuses a node id it could not name inside
        # `overseer_roster.travel_npc`'s width. Nothing a real DBC holds can
        # reach that, so this branch is a guard rather than a live case - but a
        # truncated aim is a DIFFERENT node that nobody chose, and this project
        # has already paid for that shape in dead characters.
        return Errand(
            refused=(
                "node %d cannot be named in the %d characters "
                "overseer_roster.travel_npc holds, so aiming at it would truncate "
                "into a node nobody chose" % (node.id, travel.COLUMN_WIDTH)
            ),
            why="the aim does not fit the column.",
        )

    return Errand(
        aim=aim,
        node=node.id,
        node_name=node.name,
        yards=yards,
        master=master.entry,
        why="nearest %s flight point %s has not discovered, %d "
        "yards off, with creature %d standing at it."
        % (team, who, int(yards), master.entry),
    )


def report(errand: Errand) -> str:
    """One sentence for the log and the thought stream."""
    if errand.refused:
        return errand.refused
    return (
        "sending them to learn taxi node %d (%s), %d yards off, by aiming "
        "%r - the flight master's own spawn is resolved by the module, so "
        "no coordinate is written"
        % (errand.node, errand.node_name or "unnamed", int(errand.yards), errand.aim)
    )
