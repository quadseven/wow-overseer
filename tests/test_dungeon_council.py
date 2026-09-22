"""The council can now decide to run a dungeon (infra dungeon-decision gap).

Before this, `prospects()` computed real dungeon readiness - the weakest
member's level, a gate word, what drops have been seen, a verdict sentence -
and threw it away the moment the Council tab finished drawing it. `assess()`
had no `dungeon` proposal kind at all, so the reasoning that already existed
in this file was never consulted by the family's own decision loop. These
tests pin the wiring that closes that gap: PLACES now reaches the family's
actual level range, `hold()` can fold prospects() into a family-wide
proposal, and that proposal only ever fires for a REAL, ready-or-near target.
"""

import unittest
from pathlib import Path

import council
import dungeonpath
import jobs


def _m(name, level, **over):
    return council.Member(
        name=name,
        level=level,
        class_name=over.pop("class_name", "Warrior"),
        gold=over.pop("gold", 999999),
        trades=over.pop("trades", 5),
    )


FAMILY_NAMES = ("Grug", "Ugga", "Grog", "Bork", "Og")


def _levels(rows):
    return [{"name": n, "level": lv} for n, lv in rows]


class PlacesReachTheFamilysRange(unittest.TestCase):
    """The gap this whole feature is about: PLACES topped out at 30 while the
    family sat at 41-42, so prospects() had nothing to say for them."""

    def test_scarlet_monastery_is_in_the_catalogue(self):
        self.assertIn(189, council.PLACES)

    def test_scarlet_monastery_wants_the_graveyard_level_not_the_finale(self):
        """One number per map id - PLACES cannot hold four wings - and it is
        the level that gets the family IN, matching every other entry."""
        self.assertEqual(28, council.PLACES[189])

    def test_the_new_entries_do_not_disturb_the_existing_ones(self):
        for map_id, want in {
            389: 15,
            43: 17,
            36: 17,
            33: 22,
            48: 24,
            34: 24,
            90: 29,
            47: 30,
        }.items():
            self.assertEqual(want, council.PLACES[map_id])

    def test_razorfen_downs_uldaman_and_zulfarrak_were_added_too(self):
        for map_id in (129, 70, 209):
            self.assertIn(map_id, council.PLACES)


class ScarletWingSelection(unittest.TestCase):
    """Which of the four wings the council actually sends the family to."""

    def test_a_family_barely_past_the_door_gets_the_graveyard(self):
        self.assertEqual("scarlet", council.SCARLET_WINGS[0][0])
        self.assertEqual("scarlet", council._scarlet_keyword(28))

    def test_a_stronger_family_is_not_sent_back_to_the_graveyard(self):
        self.assertEqual("scarlet-cathedral", council._scarlet_keyword(41))

    def test_the_wing_rises_with_level_in_order(self):
        seen = [council._scarlet_keyword(lv) for lv in (28, 33, 36, 39)]
        self.assertEqual(
            ["scarlet", "scarlet-library", "scarlet-armory", "scarlet-cathedral"],
            seen,
        )

    def test_near_enough_still_reaches_the_next_wing(self):
        """The same NEAR_ENOUGH slack prospects() extends everywhere else."""
        self.assertEqual(
            "scarlet-library", council._scarlet_keyword(33 - council.NEAR_ENOUGH)
        )


def _members_at(level):
    return [_m(n, level) for n in FAMILY_NAMES]


class TheDungeonProposalOnlyFiresWhenReady(unittest.TestCase):
    """It must not be idle noise - a family nowhere near ready gets nothing."""

    def test_no_level_rows_means_no_proposal(self):
        members = _members_at(41)
        self.assertIsNone(council._dungeon_proposal(members, [], []))

    def test_far_below_every_place_in_the_catalogue_proposes_nothing(self):
        members = _members_at(5)
        rows = _levels([(n, 5) for n in FAMILY_NAMES])
        self.assertIsNone(council._dungeon_proposal(members, rows, []))

    def test_the_weakest_member_must_actually_be_at_the_sitting(self):
        """A proposal is persisted against a real character_name - there is no
        FAMILY_AT_LARGE row in overseer_goal - so an absent weakest member
        means nobody to put the sentence in."""
        speakers = [_m(n, 41) for n in FAMILY_NAMES if n != "Og"]
        rows = _levels([(n, 41) for n in FAMILY_NAMES[:-1]] + [("Og", 20)])
        self.assertIsNone(council._dungeon_proposal(speakers, rows, []))


class TheDungeonProposalFiresWhenReady(unittest.TestCase):
    def setUp(self):
        self.members = _members_at(41)
        self.rows = _levels([(n, 41) for n in FAMILY_NAMES])

    def test_it_proposes_the_frontier_dungeon(self):
        proposal = council._dungeon_proposal(self.members, self.rows, [])
        self.assertIsNotNone(proposal)
        self.assertEqual("dungeon", proposal.kind)
        self.assertEqual("scarlet-cathedral", proposal.keyword)

    def test_durable_scarlet_counts_force_the_first_unfinished_wing(self):
        proposal = council._dungeon_proposal(
            self.members, self.rows, [], {"scarlet": 0}
        )
        self.assertIsNotNone(proposal)
        self.assertEqual("scarlet", proposal.keyword)

    def test_durable_scarlet_counts_advance_one_wing_at_a_time(self):
        proposal = council._dungeon_proposal(
            self.members,
            self.rows,
            [],
            {"scarlet": 25, "scarlet-library": 25},
        )
        self.assertIsNotNone(proposal)
        self.assertEqual("scarlet-armory", proposal.keyword)

    def test_it_is_raised_by_and_for_the_weakest_member(self):
        rows = _levels(
            [("Grug", 45), ("Ugga", 45), ("Grog", 45), ("Bork", 41), ("Og", 45)]
        )
        proposal = council._dungeon_proposal(self.members, rows, [])
        self.assertEqual("Bork", proposal.proposer)
        self.assertEqual("Bork", proposal.beneficiary)

    def test_it_carries_the_operators_own_campaign_size(self):
        proposal = council._dungeon_proposal(self.members, self.rows, [])
        self.assertEqual(25, proposal.target)
        self.assertEqual(council.DUNGEON_RUNS_WANTED, proposal.target)

    def test_the_said_line_means_something_in_the_familys_voice(self):
        proposal = council._dungeon_proposal(self.members, self.rows, [])
        self.assertIn("Scarlet Monastery", proposal.said)

    def test_a_near_enough_target_says_so_rather_than_claiming_ready(self):
        rows = _levels([(n, 34) for n in FAMILY_NAMES])
        members = _members_at(34)
        proposal = council._dungeon_proposal(members, rows, [])
        self.assertIsNotNone(proposal)
        self.assertIn("close enough", proposal.said)

    def test_a_non_scarlet_target_carries_its_own_door(self):
        """#202: this used to be "", the bare `dungeon` job, which runs the
        Deadmines whatever the council had chosen."""
        rows = _levels([(n, 30) for n in FAMILY_NAMES])
        members = _members_at(30)
        proposal = council._dungeon_proposal(members, rows, [])
        self.assertIsNotNone(proposal)
        self.assertEqual("razorfen-kraul", proposal.keyword)


class ALevelSixtyFamilyIsNotSentBackToScarletMonastery(unittest.TestCase):
    """infra#4247, and the shape of the defect matters more than the fix.

    THE OLD CODE HAD TWO SEPARATE WAYS TO SAY `scarlet-cathedral` FOR EVER, and
    both of them fired at level 60. Reproduced against the live state as it
    actually was on 2026-09-19 - all five of the family at 60, four dungeon
    goals on record and every one of them carrying skill_name
    'scarlet-cathedral', a wing 21 levels below them:

      1. LEDGER ABSENT. overseer_dungeon_run on wow-dev has no portal_keyword
         column, so the read fails with MySQL 1054 and hands the council None.
         The old code then fell through to _scarlet_keyword(60), whose highest
         wing is the cathedral. Nothing about it could ever return anything
         else, at any level, for ever.

      2. LEDGER PRESENT AND THE CAMPAIGN FINISHED. next_scarlet_wing returned
         None once all four wings were at 25, and the same fallback ran. Also
         for ever.

    PLACES topping out at Zul'Farrak (36) is what made both of those the END of
    the road rather than a stale rung: there was no harder place for the level
    frontier to name, so the frontier agreed with the stuck answer.
    """

    def setUp(self):
        self.members = _members_at(60)
        self.rows = _levels([(n, 60) for n in FAMILY_NAMES])

    def test_the_frontier_now_reaches_past_scarlet_monastery(self):
        self.assertIn(230, council.PLACES)
        self.assertGreater(council.PLACES[230], council.PLACES[189])
        self.assertGreater(
            council.PLACES[230], max(wants for _, wants in council.SCARLET_WINGS)
        )

    def test_a_missing_ledger_no_longer_means_the_cathedral_for_ever(self):
        """Stratholme since #202 put it in PLACES: the hardest door a level 60
        family can walk into is now its main gate, not Blackrock Depths."""
        proposal = council._dungeon_proposal(self.members, self.rows, [], None)
        self.assertIsNotNone(proposal)
        self.assertEqual("stratholme-live", proposal.keyword)
        self.assertIn("Stratholme", proposal.said)

    def test_a_finished_scarlet_campaign_no_longer_means_the_cathedral_either(self):
        done = {
            keyword: council.DUNGEON_RUNS_WANTED for keyword, _ in council.SCARLET_WINGS
        }
        proposal = council._dungeon_proposal(self.members, self.rows, [], done)
        self.assertIsNotNone(proposal)
        self.assertEqual("stratholme-live", proposal.keyword)

    def test_an_unfinished_scarlet_campaign_does_not_drag_a_sixty_back(self):
        """The ledger used to OUTRANK the level frontier outright, so a single
        uncleared graveyard run pinned the whole family to map 189 whatever
        they had outgrown. The frontier picks the place now."""
        proposal = council._dungeon_proposal(
            self.members, self.rows, [], {"scarlet": 0}
        )
        self.assertIsNotNone(proposal)
        self.assertEqual("stratholme-live", proposal.keyword)

    def test_it_repeats_rather_than_standing_down_once_the_count_is_met(self):
        """The operator asked for Blackrock Depths "over and over ...
        incrementally get better gear". A campaign at its target means run it
        again, not stop - the repeat was never the defect.

        At 52, where Blackrock Depths is the frontier: since #202 a level 60
        family's frontier is Stratholme."""
        done = {"blackrock-depths": council.DUNGEON_RUNS_WANTED}
        members = _members_at(52)
        rows = _levels([(n, 52) for n in FAMILY_NAMES])
        proposal = council._dungeon_proposal(members, rows, [], done)
        self.assertIsNotNone(proposal)
        self.assertEqual("blackrock-depths", proposal.keyword)
        self.assertEqual(council.DUNGEON_RUNS_WANTED, proposal.target)

    def test_the_campaign_size_is_the_one_the_operator_set(self):
        proposal = council._dungeon_proposal(self.members, self.rows, [], None)
        self.assertEqual(25, proposal.target)

    def test_a_family_too_low_for_it_is_never_sent_there(self):
        """Blackrock Depths joining PLACES must not put a level 41 family in
        front of a 52-60 instance. The same readiness gate every other place
        is held to, and nothing new."""
        members = _members_at(41)
        rows = _levels([(n, 41) for n in FAMILY_NAMES])
        proposal = council._dungeon_proposal(members, rows, [], None)
        self.assertIsNotNone(proposal)
        self.assertEqual("scarlet-cathedral", proposal.keyword)

    def test_the_weakest_member_still_gates_the_whole_family(self):
        """Four at 60 and one at 41 is a family that goes to Scarlet, because
        the gate is asked of whoever would die at the door."""
        members = [_m(n, 60) for n in FAMILY_NAMES[:-1]] + [_m("Og", 41)]
        rows = _levels([(n, 60) for n in FAMILY_NAMES[:-1]] + [("Og", 41)])
        proposal = council._dungeon_proposal(members, rows, [], None)
        self.assertIsNotNone(proposal)
        self.assertEqual("scarlet-cathedral", proposal.keyword)
        self.assertEqual("Og", proposal.beneficiary)


class TheProposalReachesHold(unittest.TestCase):
    """hold()'s own signature is additive - existing callers see nothing new
    unless they hand in level_rows and cards."""

    def test_omitting_level_rows_changes_nothing(self):
        members = _members_at(41)
        held_old = council.hold(members, history=[])
        held_new = council.hold(members, history=[], level_rows=None, cards=None)
        self.assertEqual(held_old.reason, held_new.reason)

    def test_a_ready_family_can_have_its_dungeon_plan_carry(self):
        members = _members_at(41)
        rows = _levels([(n, 41) for n in FAMILY_NAMES])
        held = council.hold(members, history=[], level_rows=rows, cards=[])
        self.assertIsNotNone(held.plan)
        # Weight 70 beats a round-number level proposal (20) and an idle day
        # (5); with everyone at the same level nobody is a laggard (which
        # would win outright) so the dungeon proposal is free to carry.
        self.assertEqual("dungeon", held.plan.kind)
        self.assertEqual("scarlet-cathedral", held.plan.keyword)
        self.assertEqual(25, held.plan.target)

    def test_a_laggard_still_outranks_the_dungeon(self):
        """Nobody left behind outranks anywhere the family could go next."""
        members = [
            _m("Grug", 41),
            _m("Ugga", 41),
            _m("Grog", 41),
            _m("Bork", 41),
            _m("Og", 30),
        ]
        rows = _levels(
            [(n, 41) for n in ("Grug", "Ugga", "Grog", "Bork")] + [("Og", 30)]
        )
        held = council.hold(members, history=[], level_rows=rows, cards=[])
        self.assertIsNotNone(held.plan)
        self.assertEqual("level", held.plan.kind)
        self.assertEqual("Og", held.plan.beneficiary)

    def test_the_dungeon_proposal_is_spoken_even_when_it_loses(self):
        members = [
            _m("Grug", 41),
            _m("Ugga", 41),
            _m("Grog", 41),
            _m("Bork", 41),
            _m("Og", 30),
        ]
        rows = _levels(
            [(n, 41) for n in ("Grug", "Ugga", "Grog", "Bork")] + [("Og", 30)]
        )
        held = council.hold(members, history=[], level_rows=rows, cards=[])
        self.assertTrue(
            any(
                "we went than waited" in line or "will not trouble us now" in line
                for line in held.lines
            ),
            held.lines,
        )


# --- #202: the right door, and only doors the family can walk to -----------

ALLIANCE_RACE = 1  # Human
HORDE_RACE = 2  # Orc


def _family(level, race):
    members = [
        council.Member(
            name=n,
            level=level,
            class_name="Warrior",
            gold=999999,
            trades=5,
            race=race,
        )
        for n in FAMILY_NAMES
    ]
    rows = [{"name": n, "level": level, "race": race} for n in FAMILY_NAMES]
    return members, rows


class EveryPortalMapGetsItsOwnDoor(unittest.TestCase):
    """The bare `dungeon` job runs the Deadmines, so "" for any other map sent
    the family to the wrong dungeon."""

    def test_the_councils_keywords_are_the_portal_keywords(self):
        self.assertEqual(set(jobs.PORTAL_KEYWORDS), set(council.DUNGEON_KEYWORDS))
        for keyword, map_id in dungeonpath.PORTAL_MAPS.items():
            self.assertEqual(map_id, council.DUNGEON_KEYWORDS[keyword][0], keyword)

    def test_every_portal_map_is_sent_by_a_keyword_that_opens_it(self):
        for map_id in sorted(set(dungeonpath.PORTAL_MAPS.values())):
            with self.subTest(map_id=map_id):
                keyword = council._campaign_keyword(map_id, 60, None)
                self.assertIn(keyword, jobs.PORTAL_KEYWORDS)
                self.assertEqual(map_id, dungeonpath.PORTAL_MAPS[keyword])

    def test_a_map_with_two_doors_is_sent_to_the_front_one(self):
        for map_id, keyword in (
            (90, "gnomeregan"),
            (70, "uldaman"),
            (329, "stratholme-live"),
        ):
            self.assertEqual(keyword, council._campaign_keyword(map_id, 60, None))

    def test_a_map_without_a_portal_has_no_door(self):
        self.assertEqual("", council.front_door(389))  # Ragefire Chasm

    def test_the_new_classic_doors_are_in_places_at_the_pages_floors(self):
        lows = {step.map_id: step.low for step in dungeonpath.PATH}
        for map_id in (109, 229, 329):
            self.assertEqual(lows[map_id], council.PLACES[map_id])


class ALevelTwentyFourAllianceFamily(unittest.TestCase):
    def setUp(self):
        self.members, self.rows = _family(24, ALLIANCE_RACE)

    def test_it_is_sent_to_blackfathom_deeps_not_the_deadmines(self):
        proposal = council._dungeon_proposal(self.members, self.rows, [])
        self.assertIsNotNone(proposal)
        self.assertEqual("blackfathom", proposal.keyword)
        self.assertIn("Blackfathom Deeps", proposal.said)

    def test_the_plan_that_carries_names_the_same_door(self):
        held = council.hold(self.members, history=[], level_rows=self.rows, cards=[])
        self.assertIsNotNone(held.plan)
        self.assertEqual("dungeon", held.plan.kind)
        self.assertEqual("blackfathom", held.plan.keyword)
        self.assertEqual("dungeon:blackfathom", jobs.dungeon_job(held.plan.keyword))

    def test_its_own_capital_stays_on_its_list(self):
        self.assertIn(34, [p["map_id"] for p in council.prospects(self.rows, [])])


class AHordeFamilyIsNeverSentIntoStormwind(unittest.TestCase):
    def test_a_level_sixteen_family_never_proposes_the_stockade(self):
        members, rows = _family(16, HORDE_RACE)
        proposal = council._dungeon_proposal(members, rows, [])
        self.assertIsNotNone(proposal)
        self.assertNotEqual("stockades", proposal.keyword)
        self.assertIn(proposal.keyword, jobs.PORTAL_KEYWORDS)

    def test_no_level_proposes_the_stockade(self):
        for level in range(10, 61):
            members, rows = _family(level, HORDE_RACE)
            proposal = council._dungeon_proposal(members, rows, [])
            if proposal is None:
                continue
            with self.subTest(level=level):
                self.assertNotEqual("stockades", proposal.keyword)
                self.assertNotIn("Stockade", proposal.said)

    def test_the_stockade_is_off_its_list(self):
        _, rows = _family(24, HORDE_RACE)
        self.assertNotIn(34, [p["map_id"] for p in council.prospects(rows, [])])

    def test_an_alliance_family_is_never_sent_into_orgrimmar(self):
        for level in range(10, 61):
            members, rows = _family(level, ALLIANCE_RACE)
            proposal = council._dungeon_proposal(members, rows, [])
            if proposal is None:
                continue
            with self.subTest(level=level):
                self.assertNotIn("Ragefire", proposal.said)


class AnUnknownFactionIsNotSentIntoACapital(unittest.TestCase):
    def test_a_roster_without_races_gets_the_door_outside_the_city(self):
        members = _members_at(24)
        rows = _levels([(n, 24) for n in FAMILY_NAMES])
        proposal = council._dungeon_proposal(members, rows, [])
        self.assertIsNotNone(proposal)
        self.assertEqual("blackfathom", proposal.keyword)


class ADungeonWithoutAPortalIsNeverProposed(unittest.TestCase):
    def test_ragefire_chasm_alone_in_range_proposes_nothing(self):
        """Ragefire Chasm has no portal row. Written anyway, it used to become
        the bare `dungeon` job, which is the Deadmines."""
        members, rows = _family(13, HORDE_RACE)
        self.assertIsNone(council._dungeon_proposal(members, rows, []))

    def test_every_proposal_at_every_level_is_a_real_job(self):
        for race in (ALLIANCE_RACE, HORDE_RACE, 0):
            for level in range(10, 61):
                members, rows = _family(level, race)
                proposal = council._dungeon_proposal(members, rows, [])
                if proposal is None:
                    continue
                with self.subTest(race=race, level=level):
                    self.assertTrue(proposal.keyword)
                    self.assertIsNotNone(jobs.dungeon_job(proposal.keyword))


class TheLedgerCannotSendAFamilyAboveItsLevel(unittest.TestCase):
    def test_an_unfinished_cathedral_waits_for_the_level(self):
        """Three wings done at 34: the ledger says the Cathedral (39) is next,
        five levels over the weakest member. The family keeps to the Armory,
        the highest wing it can walk into."""
        members, rows = _family(34, ALLIANCE_RACE)
        done = {
            "scarlet": council.DUNGEON_RUNS_WANTED,
            "scarlet-library": council.DUNGEON_RUNS_WANTED,
            "scarlet-armory": council.DUNGEON_RUNS_WANTED,
        }
        proposal = council._dungeon_proposal(members, rows, [], done)
        self.assertIsNotNone(proposal)
        self.assertEqual("scarlet-armory", proposal.keyword)


class TheBridgeHandsTheCouncilTheFamilysRaces(unittest.TestCase):
    def test_the_member_read_selects_race_and_passes_it_on(self):
        source = (Path(__file__).resolve().parent.parent / "bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"SELECT c.name, c.class, c.race, c.money, "', source)
        self.assertIn('race=int(row.get("race") or 0),', source)
        self.assertIn('"race": m.race}', source)


if __name__ == "__main__":
    unittest.main()
