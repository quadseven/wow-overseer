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

import council


def _m(name, level, **over):
    return council.Member(name=name, level=level,
                          class_name=over.pop("class_name", "Warrior"),
                          gold=over.pop("gold", 999999),
                          trades=over.pop("trades", 5))


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
            389: 15, 43: 17, 36: 17, 33: 22, 48: 24, 34: 24, 90: 29, 47: 30,
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
            self.members, self.rows, [],
            {"scarlet": 25, "scarlet-library": 25},
        )
        self.assertIsNotNone(proposal)
        self.assertEqual("scarlet-armory", proposal.keyword)

    def test_it_is_raised_by_and_for_the_weakest_member(self):
        rows = _levels([("Grug", 45), ("Ugga", 45), ("Grog", 45), ("Bork", 41),
                        ("Og", 45)])
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

    def test_a_non_scarlet_target_carries_no_keyword(self):
        rows = _levels([(n, 30) for n in FAMILY_NAMES])
        members = _members_at(30)
        proposal = council._dungeon_proposal(members, rows, [])
        self.assertIsNotNone(proposal)
        self.assertEqual("", proposal.keyword)


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
        members = [_m("Grug", 41), _m("Ugga", 41), _m("Grog", 41),
                  _m("Bork", 41), _m("Og", 30)]
        rows = _levels([(n, 41) for n in ("Grug", "Ugga", "Grog", "Bork")]
                       + [("Og", 30)])
        held = council.hold(members, history=[], level_rows=rows, cards=[])
        self.assertIsNotNone(held.plan)
        self.assertEqual("level", held.plan.kind)
        self.assertEqual("Og", held.plan.beneficiary)

    def test_the_dungeon_proposal_is_spoken_even_when_it_loses(self):
        members = [_m("Grug", 41), _m("Ugga", 41), _m("Grog", 41),
                  _m("Bork", 41), _m("Og", 30)]
        rows = _levels([(n, 41) for n in ("Grug", "Ugga", "Grog", "Bork")]
                       + [("Og", 30)])
        held = council.hold(members, history=[], level_rows=rows, cards=[])
        self.assertTrue(any("we went than waited" in line
                           or "will not trouble us now" in line
                           for line in held.lines), held.lines)


if __name__ == "__main__":
    unittest.main()
