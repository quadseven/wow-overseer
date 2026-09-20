"""Growing the family's flight network: the caller that never existed.

infra#4206. mod-overseer has understood `travel_npc = 'flight master:<nodeId>'`
since mod-overseer#388 and prints the exact aim it wants issued whenever a
route is refused for a node nobody has discovered:

    'Grug' is sent to 'at:1:-3618.4,-4437.9,13.5' 5329 yards away and could fly
    node 79 to node 80, but has not discovered node 40 on that route - trying
    the next node out, or walking. 'flight master:40' would go learn it

No Python caller ever issued it. Measured over 200,000 worldserver log lines,
the only aim kind this process has EVER written is `vendor`. So the family's
flight network has never grown by one node, and every trip that needs a node
nobody holds degrades to a walk that terrain can refuse outright.

WHAT THIS SUITE PINS THAT A LIVE RUN CANNOT, and every one of these is a way
the fix could ship and still be useless or harmful:

  * A NODE ON THE OTHER SIDE'S NETWORK. Echoing the module's own suggestion is
    the obvious implementation and it is wrong here. Measured on the live realm
    2026-09-19: node 40 is Gadgetzan's HORDE flight point (Bulkrek Ragefist,
    creature 7824, faction 29); node 39 is the ALLIANCE one 180 yards away
    (Bera Stonehammer, 7823) and is the one this family already boards at. The
    family is Alliance - races 1, 3 and 7 - so `flight master:40` is an errand
    no member of it can ever finish, and infra#3703's rule is that one of those
    must not hold the family's single travel column.
  * A NODE NOTHING STANDS AT. TaxiNodes.dbc carries rows that pass every other
    mechanical test with no flight master anywhere near them.
    `mod_overseer.cpp` names its own example, node 168 "Filming". Ranked by
    distance to the family's own destination on 2026-09-19, the three nearest
    undiscovered Alliance rows were "Quest - Caverns of Time (Intro Flight
    Path) (End)", "(Start)" and "Quest - Dustwallow - Alcaz Survey End".
  * AN UNREADABLE TAXIMASK READ AS AN EMPTY ONE, which would make every node in
    the world look undiscovered.
  * A SUCCESS BRANCH THAT CANNOT FAIL. `overseer_command.status = 'delivered'`
    proves nothing, and neither does an emptied `travel_npc`: mod-overseer
    releases a flight errand whether or not the node was learned and says so
    itself. The taximask bit is the only proof, and `learned` has to answer
    "not yet" for every reading it cannot make.
  * A PASS WITH NO BOUND, re-sending a walk that never sets the bit for ever.

THE FIXTURES BELOW ARE THE REAL TABLE where they can be. `taxinodes.json` is a
projection of the worldserver's own TaxiNodes.dbc (md5
3a870df7039a76607e31846237a1daec on 2026-09-19), so the Gadgetzan pair and the
Un'Goro node are asserted against it rather than restated.
"""
import pathlib
import re
import sys
import unittest

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import flightlearn  # noqa: E402
import townslot  # noqa: E402
import travel  # noqa: E402

# The three taxi nodes this issue was measured on, as the live realm answered.
GADGETZAN_ALLIANCE = 39
GADGETZAN_HORDE = 40
MARSHALS_REFUGE = 79

# Two nodes and two flight masters, built by hand so a rule cannot pass by
# accident on the real table's density. Positions are the DBC's own.
ALLIANCE_NODE = flightlearn.Node(
    id=39, map_id=1, x=-7224.0, y=-3734.6, z=8.4,
    name="Gadgetzan, Tanaris", horde=0, alliance=541)
HORDE_NODE = flightlearn.Node(
    id=40, map_id=1, x=-7048.9, y=-3780.4, z=10.2,
    name="Gadgetzan, Tanaris", horde=2224, alliance=0)
NEUTRAL_NODE = flightlearn.Node(
    id=79, map_id=1, x=-6113.8, y=-1142.7, z=-187.6,
    name="Marshal's Refuge, Un'Goro Crater", horde=2224, alliance=541)

BERA = flightlearn.Master(map_id=1, x=-7224.9, y=-3738.2, entry=7823,
                          name="Bera Stonehammer")
BULKREK = flightlearn.Master(map_id=1, x=-7045.2, y=-3779.4, entry=7824,
                             name="Bulkrek Ragefist")
GRYFE = flightlearn.Master(map_id=1, x=-6110.5, y=-1140.3, entry=10583,
                           name="Gryfe")
MASTERS = (BERA, BULKREK, GRYFE)

# A human standing in Gadgetzan, a hundred yards from both nodes.
IN_TOWN = {"map_id": 1, "pos_x": -7150.0, "pos_y": -3760.0}
HUMAN = 1
ORC = 2

# An empty taximask that is READABLE - fourteen zero words, the shape
# `characters.taximask` holds for a character that has discovered nothing.
NOTHING_KNOWN = " ".join(["0"] * 14)


def _mask(*nodes) -> str:
    """The `characters.taximask` string holding exactly these node ids."""
    words = [0] * 14
    for node in nodes:
        words[(node - 1) // 32] |= 1 << ((node - 1) % 32)
    return " ".join(str(word) for word in words)


class TheTaximaskIsReadTheWayTheGameWritesIt(unittest.TestCase):
    """Bit N-1 of word W is node W*32 + N. The off-by-one is the game's: node
    ids start at 1 and bits start at 0, and getting it wrong shifts the whole
    network by one - which reads as a plausible set of nodes."""

    def test_a_single_node_round_trips(self):
        for node in (1, 32, 33, 39, 40, 79, 80, 448):
            with self.subTest(node=node):
                self.assertEqual(flightlearn.known_nodes(_mask(node)),
                                 frozenset({node}))

    def test_the_live_reading_that_opened_this_issue(self):
        """Grug's own column, read off wow-dev on 2026-09-19. The issue's table
        says he holds 39, 79 and 80 and does NOT hold 40; this is that row."""
        grug = "43114 64 49408 8 0 0 4 0 0 0 0 0 0 0"
        known = flightlearn.known_nodes(grug)
        self.assertIn(GADGETZAN_ALLIANCE, known)
        self.assertIn(MARSHALS_REFUGE, known)
        self.assertIn(80, known)
        self.assertNotIn(GADGETZAN_HORDE, known)

    def test_an_all_zero_mask_is_empty_and_readable(self):
        self.assertEqual(flightlearn.known_nodes(NOTHING_KNOWN), frozenset())

    def test_a_mask_nobody_can_read_is_none_and_never_empty(self):
        """THE FALSE-GREEN GUARD. An empty set means "has discovered nothing"
        and would make every node in the world a candidate; None means "I do
        not know", which is a refusal. Four false greens on this project have
        come from an unreadable reading being taken for a negative one."""
        for unreadable in (None, "", "   ", "nonsense", "12 x 4", "12 -1 4"):
            with self.subTest(mask=unreadable):
                self.assertIsNone(flightlearn.known_nodes(unreadable))

    def test_knows_carries_the_same_three_answers_through(self):
        self.assertTrue(flightlearn.knows(_mask(39), 39))
        self.assertFalse(flightlearn.knows(_mask(39), 40))
        self.assertIsNone(flightlearn.knows("nonsense", 39))


class OnlyTheBitFlippingCountsAsLearned(unittest.TestCase):
    """The issue is explicit: "verified by reading `taximask` before and after,
    not by the command reaching `delivered`". mod-overseer releases the errand
    either way and says so - "node {} was {learned | not learned}" - so the
    column is the only witness."""

    def test_a_bit_that_appears_is_the_proof(self):
        self.assertTrue(flightlearn.learned(NOTHING_KNOWN, _mask(40), 40))

    def test_an_unchanged_mask_is_not_yet_and_never_done(self):
        self.assertFalse(flightlearn.learned(NOTHING_KNOWN, NOTHING_KNOWN, 40))

    def test_a_node_already_held_before_the_walk_proves_nothing(self):
        """The costliest shape of all: a check that reports success for a state
        that was already true before anything was asked."""
        self.assertFalse(flightlearn.learned(_mask(40), _mask(40), 40))

    def test_a_different_node_appearing_does_not_count(self):
        self.assertFalse(flightlearn.learned(NOTHING_KNOWN, _mask(39), 40))

    def test_an_unreadable_reading_on_either_side_is_not_success(self):
        self.assertFalse(flightlearn.learned(None, _mask(40), 40))
        self.assertFalse(flightlearn.learned(NOTHING_KNOWN, None, 40))
        self.assertFalse(flightlearn.learned("nonsense", "nonsense", 40))


class WhichSideANodeBelongsTo(unittest.TestCase):
    """`ObjectMgr::GetNearestTaxiNode` skips a node whose
    `MountCreatureID[team == TEAM_ALLIANCE ? 1 : 0]` is zero, so the pair of
    mount ids IS the team gate - not the faction of whatever creature happens
    to stand there."""

    def test_the_gadgetzan_pair_is_one_node_per_side(self):
        self.assertTrue(ALLIANCE_NODE.serves(flightlearn.TEAM_ALLIANCE))
        self.assertFalse(ALLIANCE_NODE.serves(flightlearn.TEAM_HORDE))
        self.assertTrue(HORDE_NODE.serves(flightlearn.TEAM_HORDE))
        self.assertFalse(HORDE_NODE.serves(flightlearn.TEAM_ALLIANCE))

    def test_a_neutral_town_serves_both(self):
        self.assertTrue(NEUTRAL_NODE.serves(flightlearn.TEAM_ALLIANCE))
        self.assertTrue(NEUTRAL_NODE.serves(flightlearn.TEAM_HORDE))

    def test_a_side_nobody_named_serves_nothing(self):
        self.assertFalse(NEUTRAL_NODE.serves(""))

    def test_the_races_this_family_is_made_of(self):
        self.assertEqual(flightlearn.team_of(HUMAN), flightlearn.TEAM_ALLIANCE)
        self.assertEqual(flightlearn.team_of(3), flightlearn.TEAM_ALLIANCE)
        self.assertEqual(flightlearn.team_of(7), flightlearn.TEAM_ALLIANCE)
        self.assertEqual(flightlearn.team_of(ORC), flightlearn.TEAM_HORDE)

    def test_a_race_nobody_can_place_is_refused_rather_than_guessed(self):
        for race in (None, 0, 9, "", "elf"):
            with self.subTest(race=race):
                self.assertEqual(flightlearn.team_of(race), "")


class SomethingHasToBeStandingAtTheNode(unittest.TestCase):
    """mod-overseer refuses a `flight master:<nodeId>` aim whose node no spawn
    within `TRAVEL_FLIGHT_NODE_MATCH_YARDS` answers for, so a candidate chosen
    by any looser rule is a candidate the module will decline after the walk."""

    def test_the_nearest_spawn_to_the_node_answers_for_it(self):
        self.assertIs(flightlearn.answering_master(ALLIANCE_NODE, MASTERS),
                      BERA)
        self.assertIs(flightlearn.answering_master(HORDE_NODE, MASTERS),
                      BULKREK)

    def test_a_node_with_nothing_near_it_answers_none(self):
        """node 168, "Filming", is mod_overseer.cpp's own example: it carries a
        mount id and a real taxi path and the nearest flight master is 740
        yards away, so nothing can ever discover it."""
        filming = flightlearn.Node(id=168, map_id=1, x=-9441.0, y=65.0, z=0.0,
                                   name="Filming", horde=0, alliance=3837)
        self.assertIsNone(flightlearn.answering_master(filming, MASTERS))

    def test_a_spawn_on_another_map_does_not_answer(self):
        elsewhere = flightlearn.Master(map_id=0, x=ALLIANCE_NODE.x,
                                       y=ALLIANCE_NODE.y, entry=1)
        self.assertIsNone(
            flightlearn.answering_master(ALLIANCE_NODE, (elsewhere,)))

    def test_the_radius_is_the_modules_own(self):
        just_outside = flightlearn.Master(
            map_id=1, x=ALLIANCE_NODE.x + travel.FLIGHT_NODE_MATCH_YARDS + 1,
            y=ALLIANCE_NODE.y, entry=1)
        just_inside = flightlearn.Master(
            map_id=1, x=ALLIANCE_NODE.x + travel.FLIGHT_NODE_MATCH_YARDS - 1,
            y=ALLIANCE_NODE.y, entry=2)
        self.assertIsNone(
            flightlearn.answering_master(ALLIANCE_NODE, (just_outside,)))
        self.assertIs(
            flightlearn.answering_master(ALLIANCE_NODE, (just_inside,)),
            just_inside)


class SceneryIsNotAFlightPoint(unittest.TestCase):
    """Gate 3, and the one that only a measurement finds. Creature 4321 stands
    3.6 yards from node 32 (Theramore) and 8.8 and 10.0 yards from nodes 180
    and 181, "Quest - Dustwallow - Alcaz Survey Start" and "... End" - all
    three inside the module's own 100-yard match radius, measured on wow-dev
    2026-09-19. Without this gate a discovery errand spends four thousand
    yards and the family's one travel column to walk to Theramore and learn a
    row that is scenery, while Theramore's own node goes on being missing."""

    THERAMORE = flightlearn.Node(id=32, map_id=1, x=-3827.0, y=-4523.0, z=10.0,
                                 name="Theramore, Dustwallow Marsh",
                                 horde=0, alliance=541)
    SURVEY_START = flightlearn.Node(id=180, map_id=1, x=-3822.0, y=-4530.0,
                                    z=10.0,
                                    name="Quest - Dustwallow - Alcaz Survey "
                                         "Start", horde=0, alliance=541)
    SURVEY_END = flightlearn.Node(id=181, map_id=1, x=-3819.0, y=-4531.0,
                                  z=10.0,
                                  name="Quest - Dustwallow - Alcaz Survey End",
                                  horde=0, alliance=541)
    KELLY = flightlearn.Master(map_id=1, x=-3826.0, y=-4525.0, entry=4321,
                               name="the Theramore flight master")
    TABLE = (THERAMORE, SURVEY_START, SURVEY_END)

    def test_all_three_rows_pass_the_match_radius(self):
        """The premise. If they did not, gate 2 would already be enough."""
        for node in self.TABLE:
            with self.subTest(node=node.id):
                self.assertIs(
                    flightlearn.answering_master(node, (self.KELLY,)),
                    self.KELLY)

    def test_the_master_stands_at_exactly_one_of_them(self):
        self.assertEqual(flightlearn.node_of(self.KELLY, self.TABLE), 32)

    def test_only_that_one_is_ever_offered(self):
        found = flightlearn.candidates(
            standing={"map_id": 1, "pos_x": -3900.0, "pos_y": -4600.0},
            known=frozenset(), team=flightlearn.TEAM_ALLIANCE,
            nodes=self.TABLE, masters=(self.KELLY,))
        self.assertEqual([node.id for _yards, node, _master in found], [32])

    def test_once_it_is_known_the_scenery_is_still_not_offered(self):
        found = flightlearn.candidates(
            standing={"map_id": 1, "pos_x": -3900.0, "pos_y": -4600.0},
            known=frozenset({32}), team=flightlearn.TEAM_ALLIANCE,
            nodes=self.TABLE, masters=(self.KELLY,))
        self.assertEqual(found, [])

    def test_the_pairing_is_the_modules_own_tie_break_read_backwards(self):
        """`ResolveTravelTarget` picks, out of the spawns near a node, the one
        nearest the node. This picks, out of the nodes near a spawn, the one
        nearest the spawn - so the pairing is a one-to-one neither side can
        disagree about."""
        self.assertEqual(flightlearn.node_of(BERA, (ALLIANCE_NODE, HORDE_NODE)),
                         GADGETZAN_ALLIANCE)
        self.assertEqual(flightlearn.node_of(BULKREK, (ALLIANCE_NODE, HORDE_NODE)),
                         GADGETZAN_HORDE)

    def test_a_master_with_no_node_on_its_map_answers_for_nothing(self):
        stray = flightlearn.Master(map_id=571, x=0.0, y=0.0, entry=1)
        self.assertEqual(flightlearn.node_of(stray, self.TABLE), 0)


class TheWalkIsBoundedByTheLeaseItWillBeGiven(unittest.TestCase):
    """infra#3703's rule, arithmetic rather than asserted: an errand that
    cannot finish must not hold the family's one travel column, so the longest
    walk this pass will ask for and the lease it is given are one number
    expressed twice."""

    def test_the_lease_covers_the_longest_walk_the_bound_allows(self):
        lease = flightlearn.lease_for(flightlearn.REACH_YARDS)
        walk = flightlearn.REACH_YARDS / flightlearn.WALK_YARDS_PER_MINUTE * 60
        self.assertGreater(lease, walk)
        self.assertEqual(lease, walk + flightlearn.ARRIVAL_SEEN_SECONDS)

    def test_the_lease_stays_inside_the_worlds_own_backstop(self):
        """mod-overseer gives up on an unreachable target after
        `TRAVEL_BACKSTOP_SECONDS`, and `townslot.ORPHAN_LEASE_SECONDS` is the
        same 1200 for the same reason: "past it, the world has stopped
        believing in the errand too". A lease past that is one this process
        would be alone in believing."""
        self.assertLess(flightlearn.lease_for(flightlearn.REACH_YARDS),
                        townslot.ORPHAN_LEASE_SECONDS)

    def test_the_bound_is_wide_enough_to_ever_fire(self):
        """A caller that ships and never fires is the same written-and-never-
        read failure this issue is about, one level up. Measured on the live
        roster 2026-09-19, the nearest learnable node was 3254 yards for three
        of the family and 4001 for the leader, so a bound of one
        `GATHER_LEASE_SECONDS` walk - 3120 yards - would have refused all of
        them."""
        self.assertGreater(flightlearn.REACH_YARDS, 4001)

    def test_a_distance_it_cannot_read_gets_no_lease_of_its_own(self):
        for bad in (None, "", -1, 0, "far"):
            with self.subTest(yards=bad):
                self.assertEqual(flightlearn.lease_for(bad), 0.0)


class ExactlyOneAimAndOnlyWhenThereIsSomethingToLearn(unittest.TestCase):
    """The issue's own unit test plan: "a route refusal naming an undiscovered
    node produces exactly one aim, and produces none when the node is already
    known"."""

    def _choose(self, taximask, race=HUMAN, **kwargs):
        return flightlearn.choose(
            character="Grug", standing=IN_TOWN, taximask=taximask, race=race,
            nodes=(ALLIANCE_NODE, HORDE_NODE, NEUTRAL_NODE), masters=MASTERS,
            **kwargs)

    def test_an_undiscovered_node_produces_exactly_one_aim(self):
        errand = self._choose(NOTHING_KNOWN)
        self.assertEqual(errand.aim, "flight master:39")
        self.assertEqual(errand.node, GADGETZAN_ALLIANCE)
        self.assertEqual(errand.master, BERA.entry)
        self.assertFalse(errand.refused)

    def test_a_node_already_known_produces_none(self):
        """THE NEGATIVE CASE. Everything this family can reach is already in
        the mask, so the honest answer is a refusal with a sentence, not an
        aim at a node that would teach nobody anything."""
        errand = self._choose(_mask(39, 79))
        self.assertEqual(errand.aim, "")
        self.assertEqual(errand.node, 0)
        self.assertIn("already holds every", errand.refused)

    def test_the_other_sides_node_is_never_offered(self):
        """Node 40 is the one mod-overseer's own log line names, and it is the
        Horde flight point. An Alliance character sent there walks 5,000 yards
        to somebody who will not speak to it, and holds the family's one travel
        column while it does."""
        errand = self._choose(_mask(39, 79))
        self.assertNotIn(str(GADGETZAN_HORDE), errand.aim)
        horde = self._choose(_mask(39, 79), race=ORC)
        self.assertEqual(horde.aim, "flight master:40")

    def test_a_node_nothing_stands_at_is_never_offered(self):
        errand = flightlearn.choose(
            character="Grug", standing=IN_TOWN, taximask=NOTHING_KNOWN,
            race=HUMAN, nodes=(ALLIANCE_NODE,), masters=(),
        )
        self.assertEqual(errand.aim, "")
        self.assertIn("flight master actually stands at", errand.refused)

    def test_a_node_on_another_map_is_not_a_longer_walk_it_is_not_one(self):
        far = flightlearn.Node(id=100, map_id=0, x=IN_TOWN["pos_x"],
                               y=IN_TOWN["pos_y"], z=0.0, name="Elsewhere",
                               horde=1, alliance=1)
        elsewhere = flightlearn.Master(map_id=0, x=far.x, y=far.y, entry=3)
        errand = flightlearn.choose(
            character="Grug", standing=IN_TOWN, taximask=NOTHING_KNOWN,
            race=HUMAN, nodes=(far,), masters=(elsewhere,),
        )
        self.assertEqual(errand.aim, "")

    def test_a_node_further_than_one_lease_of_walking_is_refused(self):
        """The bound is a lease and not an opinion: the errand takes the
        family's one travel column, so a walk that cannot end inside the lease
        it is given is exactly the errand infra#3703 says must not hold it."""
        errand = self._choose(NOTHING_KNOWN, reach_yards=10.0)
        self.assertEqual(errand.aim, "")
        self.assertIn("within 10 yards", errand.refused)

    def test_the_nearest_candidate_wins(self):
        """Measured 2026-09-19: ranking by the DESTINATION returned Mudsprocket
        at 2703 yards for every member of the family, because the destination
        was across a mountain range from all of them; ranking by the character
        returned Thalanaar at 2119 and Cenarion Hold at 1880. A node is worth
        the same on every future route whichever trip paid for it."""
        errand = self._choose(NOTHING_KNOWN, race=ORC)
        self.assertEqual(errand.node, GADGETZAN_HORDE)
        near = flightlearn.candidates(
            standing=IN_TOWN, known=frozenset(), team=flightlearn.TEAM_HORDE,
            nodes=(HORDE_NODE, NEUTRAL_NODE), masters=MASTERS)
        self.assertEqual([node.id for _yards, node, _master in near],
                         [GADGETZAN_HORDE, MARSHALS_REFUGE])

    def test_a_node_given_up_on_is_passed_over_not_treated_as_known(self):
        """A give-up memory that folded into the taximask would be fabricated
        state: the character does NOT hold that node, and saying it does would
        make the next reader believe a flight it cannot take."""
        errand = self._choose(NOTHING_KNOWN, skip=(GADGETZAN_ALLIANCE,))
        self.assertEqual(errand.aim, "flight master:79")

    def test_every_candidate_passed_over_leaves_a_refusal_that_says_so(self):
        errand = self._choose(NOTHING_KNOWN,
                              skip=(GADGETZAN_ALLIANCE, MARSHALS_REFUGE))
        self.assertEqual(errand.aim, "")
        self.assertIn("given up on", errand.refused)

    def test_no_standing_row_is_a_refusal_with_a_sentence(self):
        for row in (None, {}, {"map_id": 1},
                    {"map_id": 1, "pos_x": -7150.0},
                    {"map_id": None, "pos_x": -7150.0, "pos_y": -3760.0}):
            with self.subTest(standing=row):
                errand = flightlearn.choose(character="Grug", standing=row,
                                            taximask=NOTHING_KNOWN, race=HUMAN)
                self.assertEqual(errand.aim, "")
                self.assertIn("overseer_snapshot", errand.refused)
                # And never the OTHER refusal, which would claim the family
                # already holds everything it can reach - false, and false in
                # the direction that reads as success.
                self.assertNotIn("already holds every", errand.refused)

    def test_an_unreadable_taximask_refuses_rather_than_aims(self):
        errand = self._choose("nonsense")
        self.assertEqual(errand.aim, "")
        self.assertIn("not an empty one", errand.refused)

    def test_a_race_with_no_side_refuses_rather_than_guesses(self):
        errand = self._choose(NOTHING_KNOWN, race=None)
        self.assertEqual(errand.aim, "")
        self.assertIn("not one this process can put on a side", errand.refused)

    def test_every_aim_it_produces_is_one_the_module_will_parse(self):
        for race, node in ((HUMAN, GADGETZAN_ALLIANCE), (ORC, GADGETZAN_HORDE)):
            with self.subTest(race=race):
                errand = self._choose(NOTHING_KNOWN, race=race)
                self.assertEqual(travel.resolve(errand.aim), errand.aim)
                self.assertTrue(travel.is_target(errand.aim))
                self.assertEqual(travel.flight_master_node(errand.aim), node)
                self.assertLessEqual(len(errand.aim), travel.COLUMN_WIDTH)

    def test_a_refusal_never_carries_an_aim_and_an_aim_never_a_refusal(self):
        for errand in (self._choose(NOTHING_KNOWN), self._choose("nonsense"),
                       self._choose(_mask(39, 79))):
            with self.subTest(why=errand.why):
                self.assertNotEqual(bool(errand.aim), bool(errand.refused))


class TheProjectionIsTheRealmsOwnTable(unittest.TestCase):
    """`taxinodes.json` is a projection of the worldserver's TaxiNodes.dbc.
    These pin the rows this issue was measured on, so a regenerated file that
    read the fields in a different order cannot land quietly."""

    def setUp(self):
        self.by_id = {node.id: node for node in flightlearn.NODES}

    def test_the_table_is_not_empty_and_is_indexed_by_id(self):
        self.assertGreater(len(flightlearn.NODES), 300)
        self.assertEqual(len(self.by_id), len(flightlearn.NODES))

    def test_the_gadgetzan_pair_is_one_node_per_side(self):
        alliance = self.by_id[GADGETZAN_ALLIANCE]
        horde = self.by_id[GADGETZAN_HORDE]
        self.assertEqual(alliance.name, "Gadgetzan, Tanaris")
        self.assertEqual(horde.name, "Gadgetzan, Tanaris")
        self.assertTrue(alliance.serves(flightlearn.TEAM_ALLIANCE))
        self.assertFalse(alliance.serves(flightlearn.TEAM_HORDE))
        self.assertTrue(horde.serves(flightlearn.TEAM_HORDE))
        self.assertFalse(horde.serves(flightlearn.TEAM_ALLIANCE))

    def test_the_node_the_family_stands_at_is_neutral(self):
        refuge = self.by_id[MARSHALS_REFUGE]
        self.assertEqual(refuge.name, "Marshal's Refuge, Un'Goro Crater")
        self.assertEqual(refuge.map_id, 1)
        self.assertTrue(refuge.serves(flightlearn.TEAM_ALLIANCE))
        self.assertTrue(refuge.serves(flightlearn.TEAM_HORDE))

    def test_the_node_nothing_stands_at_is_still_in_the_table(self):
        """Dropping it in the generator would bake a judgement into the DATA,
        where no test can see it. The gate lives in `answering_master`."""
        self.assertIn(168, self.by_id)
        self.assertEqual(self.by_id[168].name, "Filming")


class TheCallerIsWiredAndCannotLatchTheColumn(unittest.TestCase):
    """A CONTRACT TEST OVER bridge.py's SOURCE, the pattern test_forge_aim.py
    and test_craft_rhythm.py use for their own callers - and the one this whole
    issue exists because nothing had: a pure decision no live control flow
    reaches is a thing this repository has shipped before, and `flight
    master:<nodeId>` is the case where it shipped in C++ too."""

    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(encoding="utf-8", errors="replace")
        start = cls.source.index("async def _flight_learn_once(self)")
        cls.body = cls.source[start:cls.source.index(
            "async def _flight_learn_loop(self)")]
        opened = cls.body.index('"""')
        cls.code = cls.body[cls.body.index('"""', opened + 3) + 3:]

    def test_the_pass_exists_and_asks_the_pure_module(self):
        self.assertIn("flightlearn.choose(", self.code)
        self.assertIn("import flightlearn", self.source)

    def test_the_loop_runs_under_the_gateway_and_headless_alike(self):
        """Two lists, and a loop registered in only one of them is a feature
        that silently does not exist in dev - which is the realm this is for."""
        self.assertEqual(self.source.count("self._flight_learn_loop,"), 2)

    def test_it_goes_through_the_one_sanctioned_writer(self):
        """`_claim_town_slot` is the single door every travel aim goes through
        (infra#3703). A second writer of `travel_npc` is how the column came to
        need four release fixes in one night."""
        self.assertIn("_claim_town_slot(FLIGHT_CLAIMANT", self.code)
        self.assertNotIn("_write_trade_errand", self.code)

    def test_the_aim_is_releasable_so_a_starved_pass_can_take_it_back(self):
        """infra#3703's rule, and the acceptance criterion this issue states:
        an errand that cannot finish must not hold the column for ever. An aim
        `_retaskable_from` does not recognise is untouchable by `_is_economy_aim`
        and has no terminal path at all."""
        guard = self.source[self.source.index("def _retaskable_from("):]
        guard = guard[:guard.index("def _is_economy_aim(")]
        self.assertIn("travel.is_flight_master_aim(aim)", guard)

    def test_the_claimant_has_a_lease_of_its_own(self):
        """The walk is longer than a town errand's - measured at 3254 to 5131
        yards to the nearest learnable node - so it is keyed into
        `long_leases` under its own claimant, which is the mechanism
        infra#4183 built for exactly this and NOT an exemption from the
        lease."""
        self.assertIn("FLIGHT_CLAIMANT: TOWN_SLOT_FLIGHT_LEASE_SECONDS",
                      self.source)
        self.assertIn('FLIGHT_CLAIMANT = "flight"', self.source)

    def test_the_lease_is_derived_from_the_bound_and_not_chosen_beside_it(self):
        """Two numbers that have to agree are two numbers that can drift, and
        drifting here means a bound the lease cannot cover - an errand that
        cannot finish holding the column, which is infra#3703 exactly."""
        self.assertIn(
            "TOWN_SLOT_FLIGHT_LEASE_SECONDS = flightlearn.lease_for(",
            self.source)
        self.assertIn("FLIGHT_LEARN_REACH_YARDS", self.source)

    def test_the_cadence_is_longer_than_the_lease_it_takes(self):
        """Otherwise the pass queues for a column it is already holding."""
        cycle = float(re.search(
            r'FLIGHT_LEARN_CYCLE_SECONDS.*?"([0-9.]+)"',
            self.source, re.DOTALL).group(1))
        self.assertGreater(cycle,
                           flightlearn.lease_for(flightlearn.REACH_YARDS))

    def test_the_walk_is_bounded_by_the_same_lease_it_will_be_given(self):
        self.assertIn("reach_yards=FLIGHT_LEARN_REACH_YARDS", self.code)

    def test_it_is_bounded_and_gives_up_on_a_node_that_never_lands(self):
        """Without this the pass re-issues the same refused walk every cycle
        for ever, which is infra#3703's failure with a flight master in it."""
        self.assertIn("FLIGHT_LEARN_ATTEMPTS", self.code)
        self.assertIn("skip=spent", self.code)

    def test_the_only_proof_of_success_is_the_taximask_bit(self):
        """The issue is explicit that `delivered` proves nothing. The settle
        step asks `flightlearn.learned`, which needs a bit that was absent
        before and present after, and answers False for every reading it
        cannot make."""
        settle = self.source[self.source.index("def _settle_flight_attempts("):]
        settle = settle[:settle.index("async def _flight_learn_once(")]
        self.assertIn("flightlearn.learned(", settle)
        self.assertNotIn("delivered", settle)
        # And the settle runs before anything new is asked for, so a node that
        # HAS been learned leaves the give-up memory first.
        self.assertLess(self.code.index("_settle_flight_attempts"),
                        self.code.index("flightlearn.choose("))

    def test_it_reads_the_mask_before_the_walk_it_will_judge(self):
        """"The bit flipped" is a question about a pair of readings, and a
        single reading cannot answer it."""
        self.assertIn("self._flight_attempts[errand.node] = (tried + 1, taximask)",
                      self.code)

    def test_only_the_leader_is_aimed(self):
        """A follower aim is an UPDATE that moves nobody and is never released.
        The followers learn the node anyway, by arriving with the leader:
        mod-overseer's opportunistic discovery runs for every character that
        ends up beside a flight master."""
        self.assertIn("_head_now", self.code)
        self.assertIn("leader", self.code)

    def test_it_stands_down_during_a_dungeon_run(self):
        self.assertIn("self._mid_run(names)", self.code)

    def test_no_coordinate_is_ever_authored(self):
        """The aim names a NODE and mod-overseer resolves the flight master's
        own spawn row. A hand-written z has no navmesh under it, which once
        lifted one character and killed another in the void at full health."""
        self.assertNotIn("ground_aim", self.body)
        self.assertNotIn("at:", self.code)

    def test_no_gm_command_and_no_taximask_write_anywhere_on_this_path(self):
        """The character has to walk to the flight master and discover the node
        the way a player does. Granting it would make the acceptance criterion
        unprovable as well as wrong."""
        # Scoped to THIS pass for the GM half: other features in this file use
        # `_insert_gm` legitimately, and a repository-wide ban is a different
        # change with a different argument.
        for verb in ("_insert_gm", "_insert_job", ".additem", ".learn"):
            with self.subTest(verb=verb):
                self.assertNotIn(verb, self.body)
        # The taximask half IS repository-wide: nothing in this process has
        # ever written that column and nothing may start.
        for writer in ("UPDATE characters", "SET taximask",
                       "UPDATE acore_characters.characters"):
            with self.subTest(writer=writer):
                self.assertNotIn(writer, self.source)
        # The one statement this path builds against `characters` is a SELECT.
        reader = self.source[self.source.index("_TAXIMASK_SQL = ("):]
        reader = reader[:reader.index("def _fetch_taximasks")]
        self.assertIn("SELECT name, race, taximask", reader)

    def test_the_survey_asks_for_the_flag_the_module_keys_the_role_on(self):
        sql = self.source[self.source.index("_FLIGHT_MASTER_SQL = ("):]
        sql = sql[:sql.index("def _fetch_taximasks")]
        self.assertIn("ct.npcflag & %s", sql)
        self.assertIn("flightlearn.FLIGHT_MASTER_NPC_FLAG", sql)
        self.assertIn("c.map = %s", sql)
        self.assertEqual(flightlearn.FLIGHT_MASTER_NPC_FLAG, 0x2000)


if __name__ == "__main__":
    unittest.main()
